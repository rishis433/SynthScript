"""Human-in-the-Loop (HITL) session control manager."""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Callable
from pathlib import Path


class InterventionReason(str, Enum):
    """Reasons for requesting human intervention."""

    HARD_FAILURE = "hard_failure"
    RISKY_ACTION = "risky_action"
    SECURITY_VIOLATION = "security_violation"
    BUSINESS_EXCEPTION = "business_exception"
    TIMEOUT = "timeout"
    MANUAL_REQUEST = "manual_request"


class InterventionStatus(str, Enum):
    """Status of an intervention request."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABORTED = "aborted"
    TIMED_OUT = "timed_out"


@dataclass
class InterventionContext:
    """Context for an intervention request."""

    reason: InterventionReason
    message: str
    step_id: Optional[str] = None
    current_url: Optional[str] = None
    error_message: Optional[str] = None
    expected_state: Optional[Dict[str, Any]] = None
    observed_state: Optional[Dict[str, Any]] = None
    screenshot_path: Optional[Path] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HumanAction:
    """An action taken by a human operator."""

    action_type: str  # CLICK, TYPE, NAVIGATE, etc.
    element_description: Optional[str] = None
    value: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    screenshot_before: Optional[Path] = None
    screenshot_after: Optional[Path] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InterventionSession:
    """A complete HITL intervention session."""

    session_id: str
    context: InterventionContext
    status: InterventionStatus = InterventionStatus.PENDING
    requested_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    human_actions: List[HumanAction] = field(default_factory=list)
    final_state: Optional[Dict[str, Any]] = None
    resolution: Optional[str] = None


class SessionControlManager:
    """Manages Human-in-the-Loop (HITL) escalation and session control."""

    def __init__(
        self,
        intervention_timeout_seconds: int = 300,
        auto_terminate_on_timeout: bool = True,
        headless_mode: bool = True,
    ):
        """Initialize the session control manager.

        Args:
            intervention_timeout_seconds: Timeout for human intervention
            auto_terminate_on_timeout: Whether to auto-terminate on timeout
            headless_mode: Whether browser is in headless mode
        """
        self.intervention_timeout_seconds = intervention_timeout_seconds
        self.auto_terminate_on_timeout = auto_terminate_on_timeout
        self.headless_mode = headless_mode
        
        self._current_session: Optional[InterventionSession] = None
        self._adapter: Optional[Any] = None  # SurfaceAdapter
        self._page: Optional[Any] = None  # Playwright Page
        self._intervention_callbacks: List[Callable[[InterventionContext], None]] = []
        self._session_id_counter = 0

    def register_adapter(self, adapter: Any) -> None:
        """Register the surface adapter for session control.

        Args:
            adapter: SurfaceAdapter (e.g., PlaywrightWebAdapter)
        """
        self._adapter = adapter
        # Try to get the Playwright page
        if hasattr(adapter, '_page'):
            self._page = adapter._page

    def register_intervention_callback(self, callback: Callable[[InterventionContext], None]) -> None:
        """Register a callback for intervention requests.

        Args:
            callback: Function to call when intervention is requested
        """
        self._intervention_callbacks.append(callback)

    def request_intervention(
        self,
        context: InterventionContext,
    ) -> str:
        """Request human intervention.

        Args:
            context: Intervention context

        Returns:
            Session ID for the intervention
        """
        if self._current_session and self._current_session.status == InterventionStatus.IN_PROGRESS:
            raise RuntimeError("An intervention session is already in progress")

        session_id = self._generate_session_id()
        session = InterventionSession(
            session_id=session_id,
            context=context,
        )
        
        self._current_session = session
        
        # Notify callbacks
        for callback in self._intervention_callbacks:
            try:
                callback(context)
            except Exception as e:
                print(f"Intervention callback error: {e}")

        return session_id

    def take_control(self, session_id: str) -> None:
        """Transfer control to human operator.

        Args:
            session_id: Session ID

        Raises:
            ValueError: If session not found or already completed
        """
        if not self._current_session or self._current_session.session_id != session_id:
            raise ValueError(f"Session {session_id} not found")
        
        if self._current_session.status != InterventionStatus.PENDING:
            raise ValueError(f"Session {session_id} is not pending")

        # Mark session as in progress
        self._current_session.status = InterventionStatus.IN_PROGRESS
        self._current_session.started_at = time.time()

        # Un-hide browser if in headless mode
        if self.headless_mode and self._page:
            self._show_browser()

        print(f"\n{'='*60}")
        print(f"HITL INTERVENTION REQUESTED")
        print(f"{'='*60}")
        print(f"Session ID: {session_id}")
        print(f"Reason: {self._current_session.context.reason.value}")
        print(f"Message: {self._current_session.context.message}")
        if self._current_session.context.step_id:
            print(f"Step ID: {self._current_session.context.step_id}")
        if self._current_session.context.current_url:
            print(f"Current URL: {self._current_session.context.current_url}")
        if self._current_session.context.error_message:
            print(f"Error: {self._current_session.context.error_message}")
        print(f"{'='*60}")
        print(f"Taking control of browser session...")
        print(f"Complete your actions, then call resume_automation()")
        print(f"{'='*60}\n")

    async def resume_automation(self, session_id: str) -> Dict[str, Any]:
        """Resume automation after human intervention.

        Args:
            session_id: Session ID

        Returns:
            New state after human actions

        Raises:
            ValueError: If session not found or not in progress
        """
        if not self._current_session or self._current_session.session_id != session_id:
            raise ValueError(f"Session {session_id} not found")
        
        if self._current_session.status != InterventionStatus.IN_PROGRESS:
            raise ValueError(f"Session {session_id} is not in progress")

        # Capture final state
        final_state = await self._capture_current_state()
        self._current_session.final_state = final_state
        self._current_session.status = InterventionStatus.COMPLETED
        self._current_session.completed_at = time.time()
        self._current_session.resolution = "human_resolved"

        # Re-hide browser if it was headless
        if self.headless_mode and self._page:
            self._hide_browser()

        print(f"\n{'='*60}")
        print(f"AUTOMATION RESUMED")
        print(f"{'='*60}")
        print(f"Session ID: {session_id}")
        print(f"Human actions taken: {len(self._current_session.human_actions)}")
        print(f"Resuming artifact execution...")
        print(f"{'='*60}\n")

        return final_state

    def abort_intervention(self, session_id: str, reason: str = "aborted_by_operator") -> None:
        """Abort the intervention session.

        Args:
            session_id: Session ID
            reason: Reason for abort
        """
        if not self._current_session or self._current_session.session_id != session_id:
            raise ValueError(f"Session {session_id} not found")

        self._current_session.status = InterventionStatus.ABORTED
        self._current_session.completed_at = time.time()
        self._current_session.resolution = reason

        # Re-hide browser if it was headless
        if self.headless_mode and self._page:
            self._hide_browser()

    def record_human_action(self, action: HumanAction) -> None:
        """Record an action taken by the human operator.

        Args:
            action: Human action to record
        """
        if not self._current_session:
            raise RuntimeError("No active intervention session")

        self._current_session.human_actions.append(action)

    def get_current_session(self) -> Optional[InterventionSession]:
        """Get the current intervention session.

        Returns:
            Current session or None
        """
        return self._current_session

    def is_intervention_active(self) -> bool:
        """Check if an intervention is currently active.

        Returns:
            True if intervention is in progress
        """
        return (
            self._current_session is not None and
            self._current_session.status == InterventionStatus.IN_PROGRESS
        )

    def check_timeout(self) -> bool:
        """Check if current session has timed out.

        Returns:
            True if timed out
        """
        if not self._current_session or self._current_session.status != InterventionStatus.IN_PROGRESS:
            return False

        elapsed = time.time() - self._current_session.started_at
        if elapsed > self.intervention_timeout_seconds:
            if self.auto_terminate_on_timeout:
                self.abort_intervention(
                    self._current_session.session_id,
                    reason="timeout"
                )
            return True
        return False

    def _generate_session_id(self) -> str:
        """Generate a unique session ID.

        Returns:
            Session ID
        """
        self._session_id_counter += 1
        timestamp = int(time.time())
        return f"hitl_{timestamp}_{self._session_id_counter}"

    def _show_browser(self) -> None:
        """Show the browser window (un-hide if headless)."""
        if self._page:
            try:
                # For Playwright, we need to close and reopen in non-headless mode
                # This is a simplified approach - in production would use CDP
                if hasattr(self._page, 'context'):
                    print("Browser visibility: Visible (operator control)")
            except Exception as e:
                print(f"Could not show browser: {e}")

    def _hide_browser(self) -> None:
        """Hide the browser window (return to headless)."""
        if self._page:
            try:
                # For Playwright, return to headless mode
                if hasattr(self._page, 'context'):
                    print("Browser visibility: Headless (automation control)")
            except Exception as e:
                print(f"Could not hide browser: {e}")

    async def _capture_current_state(self) -> Dict[str, Any]:
        """Capture the current UI state.

        Returns:
            Current state dictionary
        """
        if self._adapter and hasattr(self._adapter, 'capture_state'):
            try:
                state = await self._adapter.capture_state()
                return {
                    "url": state.url,
                    "timestamp": state.timestamp,
                    "accessibility_tree": state.accessibility_tree,
                    "ocr_text": state.ocr_text,
                }
            except Exception as e:
                print(f"Error capturing state: {e}")
                return {}
        return {}

    def get_session_summary(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get a summary of an intervention session.

        Args:
            session_id: Session ID

        Returns:
            Session summary or None
        """
        if not self._current_session or self._current_session.session_id != session_id:
            return None

        return {
            "session_id": self._current_session.session_id,
            "status": self._current_session.status.value,
            "reason": self._current_session.context.reason.value,
            "message": self._current_session.context.message,
            "requested_at": self._current_session.requested_at,
            "started_at": self._current_session.started_at,
            "completed_at": self._current_session.completed_at,
            "human_actions_count": len(self._current_session.human_actions),
            "resolution": self._current_session.resolution,
            "final_state": self._current_session.final_state,
        }

    def cleanup(self) -> None:
        """Clean up resources."""
        self._current_session = None
        self._adapter = None
        self._page = None
