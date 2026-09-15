"""Unit tests for Human-in-the-Loop (HITL) components."""

import pytest
import pytest_asyncio
from unittest.mock import Mock, AsyncMock
from pathlib import Path

from synthscript.hitl.manager import (
    SessionControlManager,
    InterventionContext,
    InterventionReason,
    InterventionStatus,
    HumanAction,
    InterventionSession,
)
from synthscript.hitl.operator_ui import TerminalOperatorUI, SimpleOperatorUI


class TestInterventionContext:
    """Tests for InterventionContext."""

    def test_initialization(self):
        """Test context initialization."""
        context = InterventionContext(
            reason=InterventionReason.HARD_FAILURE,
            message="Test failure",
        )
        
        assert context.reason == InterventionReason.HARD_FAILURE
        assert context.message == "Test failure"
        assert context.step_id is None
        assert context.current_url is None

    def test_initialization_with_all_fields(self):
        """Test context initialization with all fields."""
        context = InterventionContext(
            reason=InterventionReason.RISKY_ACTION,
            message="Risky action detected",
            step_id="step_1",
            current_url="http://example.com",
            error_message="Action requires confirmation",
        )
        
        assert context.step_id == "step_1"
        assert context.current_url == "http://example.com"
        assert context.error_message == "Action requires confirmation"


class TestHumanAction:
    """Tests for HumanAction."""

    def test_initialization(self):
        """Test action initialization."""
        action = HumanAction(
            action_type="CLICK",
            element_description="Submit button",
        )
        
        assert action.action_type == "CLICK"
        assert action.element_description == "Submit button"
        assert action.value is None

    def test_initialization_with_value(self):
        """Test action initialization with value."""
        action = HumanAction(
            action_type="TYPE",
            element_description="Username field",
            value="testuser",
        )
        
        assert action.value == "testuser"


class TestSessionControlManager:
    """Tests for SessionControlManager."""

    def test_initialization(self):
        """Test manager initialization."""
        manager = SessionControlManager()
        
        assert manager.intervention_timeout_seconds == 300
        assert manager.auto_terminate_on_timeout is True
        assert manager._current_session is None

    def test_initialization_with_custom_config(self):
        """Test manager initialization with custom config."""
        manager = SessionControlManager(
            intervention_timeout_seconds=600,
            auto_terminate_on_timeout=False,
            headless_mode=False,
        )
        
        assert manager.intervention_timeout_seconds == 600
        assert manager.auto_terminate_on_timeout is False
        assert manager.headless_mode is False

    def test_register_adapter(self):
        """Test adapter registration."""
        manager = SessionControlManager()
        adapter = Mock()
        adapter._page = Mock()
        
        manager.register_adapter(adapter)
        
        assert manager._adapter == adapter
        assert manager._page == adapter._page

    def test_register_intervention_callback(self):
        """Test callback registration."""
        manager = SessionControlManager()
        callback = Mock()
        
        manager.register_intervention_callback(callback)
        
        assert callback in manager._intervention_callbacks

    def test_request_intervention(self):
        """Test intervention request."""
        manager = SessionControlManager()
        context = InterventionContext(
            reason=InterventionReason.HARD_FAILURE,
            message="Test failure",
        )
        
        session_id = manager.request_intervention(context)
        
        assert session_id is not None
        assert manager._current_session is not None
        assert manager._current_session.session_id == session_id
        assert manager._current_session.status == InterventionStatus.PENDING

    def test_request_intervention_duplicate(self):
        """Test duplicate intervention request."""
        manager = SessionControlManager()
        context = InterventionContext(
            reason=InterventionReason.HARD_FAILURE,
            message="Test failure",
        )
        
        session_id = manager.request_intervention(context)
        manager.take_control(session_id)
        
        with pytest.raises(RuntimeError, match="already in progress"):
            manager.request_intervention(context)

    def test_take_control(self):
        """Test taking control."""
        manager = SessionControlManager()
        context = InterventionContext(
            reason=InterventionReason.HARD_FAILURE,
            message="Test failure",
        )
     
        session_id = manager.request_intervention(context)
        manager.take_control(session_id)
        
        assert manager._current_session.status == InterventionStatus.IN_PROGRESS
        assert manager._current_session.started_at is not None

    def test_take_control_invalid_session(self):
        """Test taking control with invalid session ID."""
        manager = SessionControlManager()
        
        with pytest.raises(ValueError, match="not found"):
            manager.take_control("invalid_id")

    def test_take_control_not_pending(self):
        """Test taking control when session not pending."""
        manager = SessionControlManager()
        context = InterventionContext(
            reason=InterventionReason.HARD_FAILURE,
            message="Test failure",
        )
        
        session_id = manager.request_intervention(context)
        manager.take_control(session_id)
        
        with pytest.raises(ValueError, match="not pending"):
            manager.take_control(session_id)

    @pytest.mark.asyncio
    async def test_resume_automation(self):
        """Test resuming automation."""
        manager = SessionControlManager()
        adapter = Mock()
        adapter.capture_state = AsyncMock()
        adapter.capture_state.return_value = Mock(
            url="http://example.com",
            timestamp=0.0,
            accessibility_tree={},
            ocr_text="",
        )
        
        manager.register_adapter(adapter)
        context = InterventionContext(
            reason=InterventionReason.HARD_FAILURE,
            message="Test failure",
        )
        
        session_id = manager.request_intervention(context)
        manager.take_control(session_id)
        
        final_state = await manager.resume_automation(session_id)
        
        assert manager._current_session.status == InterventionStatus.COMPLETED
        assert manager._current_session.completed_at is not None
        assert manager._current_session.resolution == "human_resolved"
        assert final_state is not None

    @pytest.mark.asyncio
    async def test_resume_automation_invalid_session(self):
        """Test resuming with invalid session ID."""
        manager = SessionControlManager()
        
        with pytest.raises(ValueError, match="not found"):
            await manager.resume_automation("invalid_id")

    def test_abort_intervention(self):
        """Test aborting intervention."""
        manager = SessionControlManager()
        context = InterventionContext(
            reason=InterventionReason.HARD_FAILURE,
            message="Test failure",
        )
        
        session_id = manager.request_intervention(context)
        manager.take_control(session_id)
        manager.abort_intervention(session_id)
        
        assert manager._current_session.status == InterventionStatus.ABORTED
        assert manager._current_session.resolution == "aborted_by_operator"

    def test_record_human_action(self):
        """Test recording human action."""
        manager = SessionControlManager()
        context = InterventionContext(
            reason=InterventionReason.HARD_FAILURE,
            message="Test failure",
        )
        
        manager.request_intervention(context)
        action = HumanAction(
            action_type="CLICK",
            element_description="Submit button",
        )
        
        manager.record_human_action(action)
        
        assert len(manager._current_session.human_actions) == 1
        assert manager._current_session.human_actions[0] == action

    def test_record_human_action_no_session(self):
        """Test recording action without active session."""
        manager = SessionControlManager()
        action = HumanAction(action_type="CLICK")
        
        with pytest.raises(RuntimeError, match="No active intervention session"):
            manager.record_human_action(action)

    def test_get_current_session(self):
        """Test getting current session."""
        manager = SessionControlManager()
        context = InterventionContext(
            reason=InterventionReason.HARD_FAILURE,
            message="Test failure",
        )
        
        manager.request_intervention(context)
        
        session = manager.get_current_session()
        
        assert session is not None
        assert session.session_id == manager._current_session.session_id

    def test_get_current_session_none(self):
        """Test getting current session when none exists."""
        manager = SessionControlManager()
        
        session = manager.get_current_session()
        
        assert session is None

    def test_is_intervention_active(self):
        """Test checking if intervention is active."""
        manager = SessionControlManager()
        context = InterventionContext(
            reason=InterventionReason.HARD_FAILURE,
            message="Test failure",
        )
        
        assert manager.is_intervention_active() is False
        
        manager.request_intervention(context)
        assert manager.is_intervention_active() is False
        
        manager.take_control(manager._current_session.session_id)
        assert manager.is_intervention_active() is True

    def test_check_timeout(self):
        """Test timeout checking."""
        manager = SessionControlManager(intervention_timeout_seconds=0.01)
        context = InterventionContext(
            reason=InterventionReason.HARD_FAILURE,
            message="Test failure",
        )
        
        session_id = manager.request_intervention(context)
        manager.take_control(session_id)
        
        import time
        time.sleep(0.1)
        
        assert manager.check_timeout() is True
        assert manager._current_session.status == InterventionStatus.ABORTED

    def test_check_timeout_no_session(self):
        """Test timeout checking without active session."""
        manager = SessionControlManager()
        
        assert manager.check_timeout() is False

    def test_get_session_summary(self):
        """Test getting session summary."""
        manager = SessionControlManager()
        context = InterventionContext(
            reason=InterventionReason.HARD_FAILURE,
            message="Test failure",
        )
        
        session_id = manager.request_intervention(context)
        summary = manager.get_session_summary(session_id)
        
        assert summary is not None
        assert summary["session_id"] == session_id
        assert summary["status"] == "pending"
        assert summary["reason"] == "hard_failure"

    def test_get_session_summary_invalid(self):
        """Test getting summary for invalid session."""
        manager = SessionControlManager()
        
        summary = manager.get_session_summary("invalid_id")
        
        assert summary is None

    def test_cleanup(self):
        """Test cleanup."""
        manager = SessionControlManager()
        adapter = Mock()
        manager.register_adapter(adapter)
        
        context = InterventionContext(
            reason=InterventionReason.HARD_FAILURE,
            message="Test failure",
        )
        manager.request_intervention(context)
        
        manager.cleanup()
        
        assert manager._current_session is None
        assert manager._adapter is None
        assert manager._page is None


class TestSimpleOperatorUI:
    """Tests for SimpleOperatorUI."""

    def test_initialization(self):
        """Test UI initialization."""
        manager = SessionControlManager()
        ui = SimpleOperatorUI(manager)
        
        assert ui.manager == manager

    def test_handle_intervention(self):
        """Test handling intervention."""
        manager = SessionControlManager()
        ui = SimpleOperatorUI(manager)
        
        context = InterventionContext(
            reason=InterventionReason.HARD_FAILURE,
            message="Test failure",
        )
        
        session_id = ui.handle_intervention(context)
        
        assert session_id is not None
        assert manager._current_session.status == InterventionStatus.PENDING

    @pytest.mark.asyncio
    async def test_auto_resume(self):
        """Test automatic resume."""
        manager = SessionControlManager()
        adapter = Mock()
        adapter.capture_state = AsyncMock()
        adapter.capture_state.return_value = Mock(
            url="http://example.com",
            timestamp=0.0,
            accessibility_tree={},
            ocr_text="",
        )
        
        manager.register_adapter(adapter)
        ui = SimpleOperatorUI(manager)
        
        context = InterventionContext(
            reason=InterventionReason.HARD_FAILURE,
            message="Test failure",
        )
        
        session_id = ui.handle_intervention(context)
        manager.take_control(session_id)
        
        mock_action = HumanAction(action_type="CLICK", element_description="Button")
        final_state = await ui.auto_resume(session_id, [mock_action])
        
        assert manager._current_session.status == InterventionStatus.COMPLETED
        assert len(manager._current_session.human_actions) == 1
        assert final_state is not None

    @pytest.mark.asyncio
    async def test_auto_resume_no_actions(self):
        """Test automatic resume without actions."""
        manager = SessionControlManager()
        adapter = Mock()
        adapter.capture_state = AsyncMock()
        adapter.capture_state.return_value = Mock(
            url="http://example.com",
            timestamp=0.0,
            accessibility_tree={},
            ocr_text="",
        )
        
        manager.register_adapter(adapter)
        ui = SimpleOperatorUI(manager)
        
        context = InterventionContext(
            reason=InterventionReason.HARD_FAILURE,
            message="Test failure",
        )
        
        session_id = ui.handle_intervention(context)
        manager.take_control(session_id)
        final_state = await ui.auto_resume(session_id)
        
        assert manager._current_session.status == InterventionStatus.COMPLETED
        assert len(manager._current_session.human_actions) == 0
