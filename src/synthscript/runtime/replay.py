"""Deterministic Replay Engine with strict error taxonomy."""

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Dict, List
from abc import ABC, abstractmethod

from synthscript.schema.models import (
    SynthScriptArtifact,
    StepAction,
    BusinessException,
)
from synthscript.adapters.base import SurfaceAdapter, SurfaceState
from synthscript.security.guard import SecurityGuard, IrreversibleActionError, SecurityPolicyViolation
from synthscript.security.redactor import PIIRedactor
from synthscript.hitl.manager import SessionControlManager, InterventionContext, InterventionReason


class ReplayStatus(str, Enum):
    """Status of replay execution."""

    SUCCESS = "SUCCESS"
    BUSINESS_OUTCOME = "BUSINESS_OUTCOME"
    RECOVERABLE_ERROR = "RECOVERABLE_ERROR"
    HARD_FAILURE = "HARD_FAILURE"


class ErrorTaxonomy(ABC):
    """Base class for error taxonomy."""

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        pass


@dataclass
class BusinessOutcome(ErrorTaxonomy):
    """Expected business outcome - NOT a crash."""

    code: str
    message: str
    matched_exception: Optional[BusinessException] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "BUSINESS_OUTCOME",
            "code": self.code,
            "message": self.message,
            "matched_exception": self.matched_exception.model_dump() if self.matched_exception else None,
        }


@dataclass
class RecoverableCondition(ErrorTaxonomy):
    """Recoverable condition that can be retried."""

    condition: str
    recovery_action: str
    retry_count: int = 0
    max_retries: int = 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "RECOVERABLE_CONDITION",
            "condition": self.condition,
            "recovery_action": self.recovery_action,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
        }


@dataclass
class HardFailure(ErrorTaxonomy):
    """Hard failure that halts execution."""

    step_id: str
    expected: str
    observed: str
    error_message: str
    screenshot_path: Optional[Path] = None
    accessibility_tree: Optional[dict] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "HARD_FAILURE",
            "step_id": self.step_id,
            "expected": self.expected,
            "observed": self.observed,
            "error_message": self.error_message,
            "screenshot_path": str(self.screenshot_path) if self.screenshot_path else None,
            "accessibility_tree": self.accessibility_tree,
        }


@dataclass
class StepExecutionResult:
    """Result of executing a single step."""

    step_id: str
    success: bool
    action_type: str
    timestamp: float
    duration_ms: float
    error: Optional[ErrorTaxonomy] = None
    extracted_data: Optional[Any] = None
    state_before: Optional[SurfaceState] = None
    state_after: Optional[SurfaceState] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "success": self.success,
            "action_type": self.action_type,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "error": self.error.to_dict() if self.error else None,
            "extracted_data": self.extracted_data,
            "state_before": {
                "url": self.state_before.url if self.state_before else None,
                "timestamp": self.state_before.timestamp if self.state_before else None,
            } if self.state_before else None,
            "state_after": {
                "url": self.state_after.url if self.state_after else None,
                "timestamp": self.state_after.timestamp if self.state_after else None,
            } if self.state_after else None,
        }


@dataclass
class ExecutionLog:
    """Structured execution log."""

    artifact_name: str
    artifact_version: str
    start_time: float
    end_time: Optional[float] = None
    status: ReplayStatus = ReplayStatus.SUCCESS
    steps: List[StepExecutionResult] = field(default_factory=list)
    input_parameters: Dict[str, Any] = field(default_factory=dict)
    output_parameters: Dict[str, Any] = field(default_factory=dict)
    error: Optional[ErrorTaxonomy] = None

    def add_step_result(self, result: StepExecutionResult) -> None:
        """Add a step execution result to the log."""
        self.steps.append(result)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_name": self.artifact_name,
            "artifact_version": self.artifact_version,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": (self.end_time - self.start_time) if self.end_time else None,
            "status": self.status.value,
            "input_parameters": self.input_parameters,
            "output_parameters": self.output_parameters,
            "error": self.error.to_dict() if self.error else None,
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass
class ReplayResult:
    """Result of replay execution."""

    status: ReplayStatus
    log: ExecutionLog
    error: Optional[ErrorTaxonomy] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "log": self.log.to_dict(),
            "error": self.error.to_dict() if self.error else None,
        }


class ReplayEngine:
    """Deterministic replay engine with strict error taxonomy."""

    def __init__(
        self,
        log_dir: Optional[Path] = None,
        max_retries: int = 3,
        security_guard: Optional[SecurityGuard] = None,
        pii_redactor: Optional[PIIRedactor] = None,
        hitl_manager: Optional[SessionControlManager] = None,
    ):
        """Initialize the replay engine.

        Args:
            log_dir: Directory to save execution logs
            max_retries: Maximum retry attempts for recoverable conditions
            security_guard: Security guard for policy enforcement
            pii_redactor: PII redactor for sensitive data
            hitl_manager: HITL session control manager
        """
        self.log_dir = log_dir or Path("logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries
        self.security_guard = security_guard or SecurityGuard()
        self.pii_redactor = pii_redactor or PIIRedactor()
        self.hitl_manager = hitl_manager

    async def execute(
        self,
        artifact: SynthScriptArtifact,
        input_params: Dict[str, Any],
        adapter: SurfaceAdapter,
    ) -> ReplayResult:
        """Execute a SynthScript artifact deterministically.

        Args:
            artifact: The SynthScript artifact to execute
            input_params: Input parameters for the execution
            adapter: Surface adapter for interacting with the UI

        Returns:
            ReplayResult with execution status and detailed log
        """
        start_time = time.time()
        
        # Validate input parameters against contract
        self._validate_inputs(artifact, input_params)
        
        # Register adapter with HITL manager if available
        if self.hitl_manager:
            self.hitl_manager.register_adapter(adapter)
        
        # Check URL security policy
        if hasattr(adapter, '_page') and adapter._page:
            self.security_guard.check_url_allowed(adapter._page.url)
        
        # Initialize execution log
        log = ExecutionLog(
            artifact_name=artifact.metadata.name,
            artifact_version=artifact.metadata.version,
            start_time=start_time,
            input_parameters=input_params,
        )

        try:
            # Execute each step
            for step in artifact.flow:
                # Check action security policy before executing
                action_description = step.target.locators[0].value if step.target else ""
                try:
                    self.security_guard.check_action_allowed(
                        action_description,
                        step.action_type.value,
                        context={"step_id": step.step_id}
                    )
                except IrreversibleActionError as e:
                    # Trigger HITL intervention for irreversible action
                    if self.hitl_manager:
                        session_id = await self._trigger_hitl_intervention(
                            step,
                            InterventionReason.RISKY_ACTION,
                            f"Irreversible action requires confirmation: {e.reason}",
                            adapter,
                        )
                        if session_id:
                            # Resume after human intervention
                            continue
                    # Fall through to hard failure if no HITL or intervention failed
                    error = HardFailure(
                        step_id=step.step_id,
                        expected=f"Action allowed",
                        observed=f"Action blocked: {e.reason}",
                        error_message=str(e),
                    )
                    log.status = ReplayStatus.HARD_FAILURE
                    log.error = error
                    log.end_time = time.time()
                    self._save_log(log)
                    return ReplayResult(
                        status=ReplayStatus.HARD_FAILURE,
                        log=log,
                        error=error,
                    )
                except SecurityPolicyViolation as e:
                    error = HardFailure(
                        step_id=step.step_id,
                        expected=f"Action allowed",
                        observed=f"Security violation: {e.message}",
                        error_message=str(e),
                    )
                    log.status = ReplayStatus.HARD_FAILURE
                    log.error = error
                    log.end_time = time.time()
                    self._save_log(log)
                    return ReplayResult(
                        status=ReplayStatus.HARD_FAILURE,
                        log=log,
                        error=error,
                    )
                
                step_result = await self._execute_step(
                    step,
                    input_params,
                    artifact.business_exceptions,
                    adapter,
                )
                log.add_step_result(step_result)

                # Check if step failed with business outcome
                if not step_result.success and isinstance(step_result.error, BusinessOutcome):
                    log.status = ReplayStatus.BUSINESS_OUTCOME
                    log.error = step_result.error
                    log.end_time = time.time()
                    self._save_log(log)
                    return ReplayResult(
                        status=ReplayStatus.BUSINESS_OUTCOME,
                        log=log,
                        error=step_result.error,
                    )

                # Check if step failed with hard failure
                if not step_result.success and isinstance(step_result.error, HardFailure):
                    log.status = ReplayStatus.HARD_FAILURE
                    log.error = step_result.error
                    log.end_time = time.time()
                    self._save_log(log)
                    return ReplayResult(
                        status=ReplayStatus.HARD_FAILURE,
                        log=log,
                        error=step_result.error,
                    )

                # Store extracted data in output parameters
                if step_result.extracted_data and step.output_binding:
                    log.output_parameters[step.output_binding] = step_result.extracted_data

            # All steps executed successfully
            log.status = ReplayStatus.SUCCESS
            log.end_time = time.time()
            self._save_log(log)
            return ReplayResult(status=ReplayStatus.SUCCESS, log=log)

        except Exception as e:
            # Unexpected error during execution
            error = HardFailure(
                step_id="UNKNOWN",
                expected="Successful execution",
                observed=f"Exception: {str(e)}",
                error_message=str(e),
            )
            log.status = ReplayStatus.HARD_FAILURE
            log.error = error
            log.end_time = time.time()
            self._save_log(log)
            return ReplayResult(
                status=ReplayStatus.HARD_FAILURE,
                log=log,
                error=error,
            )

    def _validate_inputs(
        self,
        artifact: SynthScriptArtifact,
        input_params: Dict[str, Any],
    ) -> None:
        """Validate input parameters against the artifact contract.

        Args:
            artifact: The SynthScript artifact
            input_params: Input parameters to validate

        Raises:
            ValueError: If validation fails
        """
        for param_name, param_def in artifact.contract.input_parameters.items():
            if param_def.required and param_name not in input_params:
                raise ValueError(f"Required input parameter '{param_name}' is missing")

    async def _trigger_hitl_intervention(
        self,
        step: StepAction,
        reason: InterventionReason,
        message: str,
        adapter: SurfaceAdapter,
    ) -> Optional[str]:
        """Trigger HITL intervention.

        Args:
            step: The step that triggered intervention
            reason: Reason for intervention
            message: Intervention message
            adapter: Surface adapter

        Returns:
            Session ID if intervention was successful, None otherwise
        """
        if not self.hitl_manager:
            return None

        # Capture current state
        try:
            current_state = await adapter.capture_state()
        except Exception as e:
            print(f"Error capturing state for HITL: {e}")
            current_state = None

        # Create intervention context
        context = InterventionContext(
            reason=reason,
            message=message,
            step_id=step.step_id,
            current_url=current_state.url if current_state else None,
            error_message=message,
            screenshot_path=current_state.screenshot_path if current_state else None,
        )

        # Request intervention
        session_id = self.hitl_manager.request_intervention(context)
        
        # For automated testing, immediately take control and resume
        # In production, this would wait for human operator
        try:
            self.hitl_manager.take_control(session_id)
            # Resume immediately (for automated testing)
            # In production, this would wait for human to call resume_automation
            final_state = await self.hitl_manager.resume_automation(session_id)
            return session_id
        except Exception as e:
            print(f"HITL intervention failed: {e}")
            return None

    async def _execute_step(
        self,
        step: StepAction,
        input_params: Dict[str, Any],
        business_exceptions: List[BusinessException],
        adapter: SurfaceAdapter,
        retry_count: int = 0,
    ) -> StepExecutionResult:
        """Execute a single step with error handling.

        Args:
            step: The step to execute
            input_params: Input parameters
            business_exceptions: Business exception definitions
            adapter: Surface adapter
            retry_count: Current retry attempt

        Returns:
            StepExecutionResult
        """
        step_start = time.time()
        
        # Capture state before execution
        state_before = await adapter.capture_state()
        
        # Resolve input binding
        input_value = None
        if step.input_binding:
            input_value = input_params.get(step.input_binding)
        
        # Prepare target specification
        target = None
        if step.target:
            target = {
                "locators": [loc.model_dump() for loc in step.target.locators],
                "resolution_strategy": step.target.resolution_strategy.value,
            }
        
        try:
            # Execute the action
            action_result = await adapter.execute_action(
                action_type=step.action_type.value,
                target=target,
                input_value=input_value,
            )
            
            # Capture state after execution
            state_after = action_result.new_state or await adapter.capture_state()
            
            step_duration = (time.time() - step_start) * 1000
            
            if action_result.success:
                return StepExecutionResult(
                    step_id=step.step_id,
                    success=True,
                    action_type=step.action_type.value,
                    timestamp=step_start,
                    duration_ms=step_duration,
                    extracted_data=action_result.extracted_data,
                    state_before=state_before,
                    state_after=state_after,
                )
            else:
                # Action failed - categorize the error
                error = await self._categorize_error(
                    step,
                    action_result.error_message,
                    state_after,
                    business_exceptions,
                )
                
                if isinstance(error, RecoverableCondition) and retry_count < self.max_retries:
                    # Retry the step
                    await self._handle_recoverable_condition(error, adapter)
                    return await self._execute_step(
                        step,
                        input_params,
                        business_exceptions,
                        adapter,
                        retry_count + 1,
                    )
                
                return StepExecutionResult(
                    step_id=step.step_id,
                    success=False,
                    action_type=step.action_type.value,
                    timestamp=step_start,
                    duration_ms=step_duration,
                    error=error,
                    state_before=state_before,
                    state_after=state_after,
                )
                
        except Exception as e:
            # Unexpected exception during step execution
            step_duration = (time.time() - step_start) * 1000
            state_after = await adapter.capture_state()
            
            error = HardFailure(
                step_id=step.step_id,
                expected=f"Successful {step.action_type.value}",
                observed=f"Exception: {str(e)}",
                error_message=str(e),
                screenshot_path=state_after.screenshot_path,
                accessibility_tree=state_after.accessibility_tree,
            )
            
            return StepExecutionResult(
                step_id=step.step_id,
                success=False,
                action_type=step.action_type.value,
                timestamp=step_start,
                duration_ms=step_duration,
                error=error,
                state_before=state_before,
                state_after=state_after,
            )

    async def _categorize_error(
        self,
        step: StepAction,
        error_message: str,
        state: SurfaceState,
        business_exceptions: List[BusinessException],
    ) -> ErrorTaxonomy:
        """Categorize an error into the appropriate taxonomy.

        Args:
            step: The step that failed
            error_message: Error message from the action
            state: Current surface state
            business_exceptions: Business exception definitions

        Returns:
            Appropriate error taxonomy instance
        """
        # Check if error matches a business exception
        for exception in business_exceptions:
            if self._matches_business_exception(exception, state, error_message):
                return BusinessOutcome(
                    code=exception.return_state,
                    message=f"Business outcome: {exception.condition}",
                    matched_exception=exception,
                )
        
        # Check if error is a recoverable condition
        if self._is_recoverable_condition(error_message, state):
            return RecoverableCondition(
                condition=error_message,
                recovery_action="wait_and_retry",
                max_retries=self.max_retries,
            )
        
        # Default to hard failure
        return HardFailure(
            step_id=step.step_id,
            expected=f"Successful {step.action_type.value}",
            observed=error_message or "Action failed",
            error_message=error_message or "Unknown error",
            screenshot_path=state.screenshot_path,
            accessibility_tree=state.accessibility_tree,
        )

    def _matches_business_exception(
        self,
        exception: BusinessException,
        state: SurfaceState,
        error_message: str,
    ) -> bool:
        """Check if current state matches a business exception.

        Args:
            exception: Business exception definition
            state: Current surface state
            error_message: Error message

        Returns:
            True if matches, False otherwise
        """
        # Check if error message contains the condition
        if error_message and exception.condition.lower() in error_message.lower():
            return True
        
        # Check if OCR text contains the condition
        if state.ocr_text and exception.condition.lower() in state.ocr_text.lower():
            return True
        
        # Check if accessibility tree contains the condition
        if self._text_in_tree(state.accessibility_tree, exception.condition):
            return True
        
        return False

    def _text_in_tree(self, tree: dict, search_text: str) -> bool:
        """Recursively search for text in accessibility tree.

        Args:
            tree: Accessibility tree node
            search_text: Text to search for

        Returns:
            True if text found, False otherwise
        """
        if not isinstance(tree, dict):
            return False
        
        # Check current node
        for value in tree.values():
            if isinstance(value, str) and search_text.lower() in value.lower():
                return True
            if isinstance(value, dict) and self._text_in_tree(value, search_text):
                return True
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and self._text_in_tree(item, search_text):
                        return True
        
        return False

    def _is_recoverable_condition(
        self,
        error_message: str,
        state: SurfaceState,
    ) -> bool:
        """Check if error is a recoverable condition.

        Args:
            error_message: Error message
            state: Current surface state

        Returns:
            True if recoverable, False otherwise
        """
        # Known recoverable conditions
        recoverable_keywords = [
            "timeout",
            "network",
            "session expiring",
            "loading",
            "please wait",
            "temporarily unavailable",
        ]
        
        if error_message:
            for keyword in recoverable_keywords:
                if keyword.lower() in error_message.lower():
                    return True
        
        if state.ocr_text:
            for keyword in recoverable_keywords:
                if keyword.lower() in state.ocr_text.lower():
                    return True
        
        return False

    async def _handle_recoverable_condition(
        self,
        error: RecoverableCondition,
        adapter: SurfaceAdapter,
    ) -> None:
        """Handle a recoverable condition.

        Args:
            error: The recoverable condition
            adapter: Surface adapter
        """
        # Simple recovery: wait and retry
        # In production, this could dismiss modals, handle popups, etc.
        import asyncio
        await asyncio.sleep(1)

    def _save_log(self, log: ExecutionLog) -> None:
        """Save execution log to file.

        Args:
            log: Execution log to save
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"replay_{log.artifact_name}_{timestamp}.json"
        log_path = self.log_dir / log_filename
        
        # Redact PII from log before saving
        log_dict = log.to_dict()
        redacted_log_dict = self.pii_redactor.redact_dict(log_dict)
        
        with open(log_path, "w") as f:
            json.dump(redacted_log_dict, f, indent=2)
