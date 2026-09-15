"""Unit tests for the Replay Engine."""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from synthscript.runtime.replay import (
    ReplayEngine,
    ReplayResult,
    ReplayStatus,
    ExecutionLog,
    StepExecutionResult,
    ErrorTaxonomy,
    BusinessOutcome,
    RecoverableCondition,
    HardFailure,
)
from synthscript.schema.models import (
    SynthScriptArtifact,
    ArtifactMetadata,
    Contract,
    ParameterDefinition,
    StepAction,
    ActionType,
    Target,
    Locator,
    LocatorStrategy,
    ResolutionStrategy,
    BusinessException,
)
from synthscript.adapters.base import SurfaceState, ActionExecutionResult, SurfaceAdapter


class TestErrorTaxonomy:
    """Tests for error taxonomy classes."""

    def test_business_outcome_to_dict(self):
        """Test BusinessOutcome serialization."""
        outcome = BusinessOutcome(
            code="NOT_FOUND",
            message="Record not found",
        )
        result = outcome.to_dict()
        
        assert result["type"] == "BUSINESS_OUTCOME"
        assert result["code"] == "NOT_FOUND"
        assert result["message"] == "Record not found"

    def test_recoverable_condition_to_dict(self):
        """Test RecoverableCondition serialization."""
        condition = RecoverableCondition(
            condition="timeout",
            recovery_action="retry",
            retry_count=1,
            max_retries=3,
        )
        result = condition.to_dict()
        
        assert result["type"] == "RECOVERABLE_CONDITION"
        assert result["condition"] == "timeout"
        assert result["recovery_action"] == "retry"
        assert result["retry_count"] == 1
        assert result["max_retries"] == 3

    def test_hard_failure_to_dict(self):
        """Test HardFailure serialization."""
        failure = HardFailure(
            step_id="step_1",
            expected="Click button",
            observed="Element not found",
            error_message="Could not locate element",
        )
        result = failure.to_dict()
        
        assert result["type"] == "HARD_FAILURE"
        assert result["step_id"] == "step_1"
        assert result["expected"] == "Click button"
        assert result["observed"] == "Element not found"


class TestExecutionLog:
    """Tests for ExecutionLog."""

    def test_add_step_result(self):
        """Test adding step results to log."""
        log = ExecutionLog(
            artifact_name="test",
            artifact_version="1.0",
            start_time=0.0,
        )
        
        step_result = StepExecutionResult(
            step_id="step_1",
            success=True,
            action_type="CLICK",
            timestamp=0.0,
            duration_ms=100.0,
        )
        
        log.add_step_result(step_result)
        
        assert len(log.steps) == 1
        assert log.steps[0].step_id == "step_1"

    def test_to_dict(self):
        """Test ExecutionLog serialization."""
        log = ExecutionLog(
            artifact_name="test",
            artifact_version="1.0",
            start_time=0.0,
            end_time=1.0,
            status=ReplayStatus.SUCCESS,
        )
        
        result = log.to_dict()
        
        assert result["artifact_name"] == "test"
        assert result["artifact_version"] == "1.0"
        assert result["status"] == "SUCCESS"
        assert result["duration_seconds"] == 1.0

    def test_save_to_file(self, tmp_path):
        """Test saving log to file."""
        log = ExecutionLog(
            artifact_name="test",
            artifact_version="1.0",
            start_time=0.0,
        )
        
        # Save using the replay engine's _save_log method
        from synthscript.runtime.replay import ReplayEngine
        engine = ReplayEngine(log_dir=tmp_path)
        engine._save_log(log)
        
        # Check file was created
        log_files = list(tmp_path.glob("replay_test_*.json"))
        assert len(log_files) == 1


class TestReplayEngine:
    """Tests for ReplayEngine."""

    @pytest.fixture
    def mock_adapter(self):
        """Create a mock SurfaceAdapter."""
        adapter = Mock(spec=SurfaceAdapter)
        adapter.capture_state = AsyncMock()
        adapter.execute_action = AsyncMock()
        # Add mock page with URL for security checks
        mock_page = Mock()
        mock_page.url = "http://localhost:5000"
        adapter._page = mock_page
        # Mock async methods for HITL state capture
        adapter.capture_state.return_value = SurfaceState(
            accessibility_tree={},
            timestamp=0.0,
            url="http://localhost:5000",
        )
        return adapter

    @pytest.fixture
    def simple_artifact(self):
        """Create a simple test artifact."""
        return SynthScriptArtifact(
            metadata=ArtifactMetadata(
                name="test_flow",
                version="1.0.0",
                target_surface="web",
            ),
            contract=Contract(
                input_parameters={
                    "username": ParameterDefinition(type="string", required=True),
                },
                output_parameters={
                    "result": ParameterDefinition(type="string", required=False),
                },
            ),
            flow=[
                StepAction(
                    step_id="step_1",
                    action_type=ActionType.CLICK,
                    target=Target(
                        locators=[Locator(strategy=LocatorStrategy.A11Y_ID, value="button")],
                        resolution_strategy=ResolutionStrategy.CASCADE,
                    ),
                ),
            ],
            business_exceptions=[],
        )

    def test_initialization(self):
        """Test ReplayEngine initialization."""
        engine = ReplayEngine()
        
        assert engine.log_dir.exists()
        assert engine.max_retries == 3

    @pytest.mark.asyncio
    async def test_successful_execution(self, simple_artifact, mock_adapter):
        """Test successful execution of artifact."""
        engine = ReplayEngine()
        
        # Mock adapter responses
        mock_adapter.execute_action.return_value = ActionExecutionResult(
            success=True,
            new_state=SurfaceState(
                accessibility_tree={},
                timestamp=0.0,
                url="http://localhost:5000",
            ),
        )
        
        result = await engine.execute(
            artifact=simple_artifact,
            input_params={"username": "test"},
            adapter=mock_adapter,
        )
        
        assert result.status == ReplayStatus.SUCCESS
        assert result.log.status == ReplayStatus.SUCCESS
        assert len(result.log.steps) == 1
        assert result.log.steps[0].success is True

    @pytest.mark.asyncio
    async def test_missing_required_input(self, simple_artifact, mock_adapter):
        """Test execution with missing required input parameter."""
        engine = ReplayEngine()
        
        with pytest.raises(ValueError, match="Required input parameter"):
            await engine.execute(
                artifact=simple_artifact,
                input_params={},  # Missing required "username"
                adapter=mock_adapter,
            )

    @pytest.mark.asyncio
    async def test_business_outcome_detection(self, mock_adapter):
        """Test detection of business outcomes."""
        engine = ReplayEngine()
        
        artifact = SynthScriptArtifact(
            metadata=ArtifactMetadata(
                name="test_flow",
                version="1.0.0",
                target_surface="web",
            ),
            contract=Contract(),
            flow=[
                StepAction(
                    step_id="step_1",
                    action_type=ActionType.CLICK,
                    target=Target(
                        locators=[Locator(strategy=LocatorStrategy.A11Y_ID, value="button")],
                        resolution_strategy=ResolutionStrategy.CASCADE,
                    ),
                ),
            ],
            business_exceptions=[
                BusinessException(
                    condition="Record not found",
                    return_state="NOT_FOUND",
                ),
            ],
        )
        
        # Mock adapter to return error state
        mock_adapter.execute_action.return_value = ActionExecutionResult(
            success=False,
            error_message="Record not found",
            new_state=SurfaceState(
                accessibility_tree={},
                ocr_text="Record not found",
                timestamp=0.0,
                url="http://localhost:5000",
            ),
        )
        
        result = await engine.execute(
            artifact=artifact,
            input_params={},
            adapter=mock_adapter,
        )
        
        assert result.status == ReplayStatus.BUSINESS_OUTCOME
        assert isinstance(result.error, BusinessOutcome)
        assert result.error.code == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_hard_failure_detection(self, simple_artifact, mock_adapter):
        """Test detection of hard failures."""
        engine = ReplayEngine()
        
        # Mock adapter to return error state
        mock_adapter.execute_action.return_value = ActionExecutionResult(
            success=False,
            error_message="Element not found",
            new_state=SurfaceState(
                accessibility_tree={},
                timestamp=0.0,
                url="http://localhost:5000",
            ),
        )
        
        result = await engine.execute(
            artifact=simple_artifact,
            input_params={"username": "test"},
            adapter=mock_adapter,
        )
        
        assert result.status == ReplayStatus.HARD_FAILURE
        assert isinstance(result.error, HardFailure)
        assert result.error.step_id == "step_1"

    @pytest.mark.asyncio
    async def test_recoverable_condition_retry(self, simple_artifact, mock_adapter):
        """Test retry on recoverable condition."""
        engine = ReplayEngine(max_retries=2)
        
        # Mock adapter to return timeout error first, then success
        call_count = [0]
        
        async def mock_execute(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return ActionExecutionResult(
                    success=False,
                    error_message="timeout waiting for element",
                    new_state=SurfaceState(
                        accessibility_tree={},
                        timestamp=0.0,
                        url="http://localhost:5000",
                    ),
                )
            else:
                return ActionExecutionResult(
                    success=True,
                    new_state=SurfaceState(
                        accessibility_tree={},
                        timestamp=0.0,
                        url="http://localhost:5000",
                    ),
                )
        
        mock_adapter.capture_state.return_value = SurfaceState(
            accessibility_tree={},
            timestamp=0.0,
            url="http://localhost:5000",
        )
        mock_adapter.execute_action.side_effect = mock_execute
        
        result = await engine.execute(
            artifact=simple_artifact,
            input_params={"username": "test"},
            adapter=mock_adapter,
        )
        
        assert result.status == ReplayStatus.SUCCESS
        assert call_count[0] == 2  # Initial call + 1 retry

    @pytest.mark.asyncio
    async def test_output_parameter_binding(self, mock_adapter):
        """Test output parameter binding."""
        engine = ReplayEngine()
        
        artifact = SynthScriptArtifact(
            metadata=ArtifactMetadata(
                name="test_flow",
                version="1.0.0",
                target_surface="web",
            ),
            contract=Contract(
                input_parameters={},
                output_parameters={
                    "result": ParameterDefinition(type="string", required=False),
                },
            ),
            flow=[
                StepAction(
                    step_id="step_1",
                    action_type=ActionType.EXTRACT_TEXT,
                    output_binding="result",
                ),
            ],
            business_exceptions=[],
        )
        
        mock_adapter.execute_action.return_value = ActionExecutionResult(
            success=True,
            extracted_data="Extracted value",
            new_state=SurfaceState(
                accessibility_tree={},
                timestamp=0.0,
                url="http://localhost:5000",
            ),
        )
        
        # Add mock page with URL for security check
        mock_page = Mock()
        mock_page.url = "http://localhost:5000"
        mock_adapter._page = mock_page
        
        result = await engine.execute(
            artifact=artifact,
            input_params={},
            adapter=mock_adapter,
        )
        
        assert result.status == ReplayStatus.SUCCESS
        assert result.log.output_parameters["result"] == "Extracted value"

    @pytest.mark.asyncio
    async def test_input_parameter_binding(self, mock_adapter):
        """Test input parameter binding."""
        engine = ReplayEngine()
        
        artifact = SynthScriptArtifact(
            metadata=ArtifactMetadata(
                name="test_flow",
                version="1.0.0",
                target_surface="web",
            ),
            contract=Contract(
                input_parameters={
                    "username": ParameterDefinition(type="string", required=True),
                },
                output_parameters={},
            ),
            flow=[
                StepAction(
                    step_id="step_1",
                    action_type=ActionType.TYPE_AND_ENTER,
                    input_binding="username",
                ),
            ],
            business_exceptions=[],
        )
        
        mock_adapter.execute_action.return_value = ActionExecutionResult(
            success=True,
            new_state=SurfaceState(
                accessibility_tree={},
                timestamp=0.0,
                url="http://localhost:5000",
            ),
        )
        
        result = await engine.execute(
            artifact=artifact,
            input_params={"username": "testuser"},
            adapter=mock_adapter,
        )
        
        assert result.status == ReplayStatus.SUCCESS
        # Verify the input value was passed to execute_action
        mock_adapter.execute_action.assert_called_once()
        call_args = mock_adapter.execute_action.call_args
        assert call_args.kwargs["input_value"] == "testuser"

    @pytest.mark.asyncio
    async def test_evidence_logging(self, simple_artifact, mock_adapter, tmp_path):
        """Test that execution logs are saved to file."""
        engine = ReplayEngine(log_dir=tmp_path)
        
        mock_adapter.execute_action.return_value = ActionExecutionResult(
            success=True,
            new_state=SurfaceState(
                accessibility_tree={},
                timestamp=0.0,
                url="http://localhost:5000",
            ),
        )
        
        await engine.execute(
            artifact=simple_artifact,
            input_params={"username": "test"},
            adapter=mock_adapter,
        )
        
        # Check that log file was created
        log_files = list(tmp_path.glob("replay_*.json"))
        assert len(log_files) == 1
        
        # Verify log content
        import json
        with open(log_files[0]) as f:
            log_data = json.load(f)
            assert log_data["artifact_name"] == "test_flow"
            assert log_data["status"] == "SUCCESS"
            assert len(log_data["steps"]) == 1

    @pytest.mark.asyncio
    async def test_step_execution_with_validation_rule(self, mock_adapter):
        """Test step execution with validation rule."""
        engine = ReplayEngine()
        
        artifact = SynthScriptArtifact(
            metadata=ArtifactMetadata(
                name="test_flow",
                version="1.0.0",
                target_surface="web",
            ),
            contract=Contract(),
            flow=[
                StepAction(
                    step_id="step_1",
                    action_type=ActionType.CLICK,
                    validation_rule="element.visible == true",
                ),
            ],
            business_exceptions=[],
        )
        
        mock_adapter.execute_action.return_value = ActionExecutionResult(
            success=True,
            new_state=SurfaceState(
                accessibility_tree={},
                timestamp=0.0,
                url="http://localhost:5000",
            ),
        )
        
        result = await engine.execute(
            artifact=artifact,
            input_params={},
            adapter=mock_adapter,
        )
        
        assert result.status == ReplayStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_unexpected_exception_handling(self, simple_artifact, mock_adapter):
        """Test handling of unexpected exceptions during execution."""
        engine = ReplayEngine()
        
        mock_adapter.capture_state.side_effect = Exception("Unexpected error")
        
        result = await engine.execute(
            artifact=simple_artifact,
            input_params={"username": "test"},
            adapter=mock_adapter,
        )
        
        assert result.status == ReplayStatus.HARD_FAILURE
        assert isinstance(result.error, HardFailure)
        assert "Unexpected error" in result.error.error_message
