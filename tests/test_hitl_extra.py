"""Additional tests for Human-in-the-Loop (HITL) flows."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from synthscript.adapters.base import SurfaceState
from synthscript.adapters.playwright_adapter import PlaywrightWebAdapter
from synthscript.hitl.manager import (
    HumanAction,
    InterventionContext,
    InterventionReason,
    InterventionStatus,
    SessionControlManager,
)
from synthscript.hitl.operator_ui import TerminalOperatorUI
from synthscript.runtime.replay import ReplayEngine
from synthscript.schema.models import (
    ActionType,
    ArtifactMetadata,
    Contract,
    Locator,
    LocatorStrategy,
    StepAction,
    SynthScriptArtifact,
    Target,
)


def _surface_state(url: str = "http://localhost:5000") -> SurfaceState:
    return SurfaceState(
        accessibility_tree={"role": "WebArea", "name": "Legacy Banking System"},
        screenshot_path=None,
        ocr_text="",
        timestamp=0.0,
        url=url,
    )


def _playwright_adapter(url: str = "http://localhost:5000") -> PlaywrightWebAdapter:
    adapter = PlaywrightWebAdapter(headless=True)
    adapter._page = Mock()
    adapter._page.url = url
    adapter._page.context = Mock()
    adapter.capture_state = AsyncMock(return_value=_surface_state(url))
    adapter.start = AsyncMock()
    adapter.close = AsyncMock()
    return adapter


@pytest.mark.asyncio
async def test_hitl_with_real_browser():
    """Test HITL with a Playwright adapter session (browser launch mocked)."""
    adapter = _playwright_adapter()
    await adapter.start("http://localhost:5000")

    hitl_manager = SessionControlManager(headless_mode=True)
    hitl_manager.register_adapter(adapter)

    context = InterventionContext(
        reason=InterventionReason.RISKY_ACTION,
        message="Test intervention",
        current_url="http://localhost:5000",
    )

    session_id = hitl_manager.request_intervention(context)
    hitl_manager.take_control(session_id)

    action = HumanAction(action_type="CLICK", element_description="Test button")
    hitl_manager.record_human_action(action)

    final_state = await hitl_manager.resume_automation(session_id)

    assert final_state is not None
    assert hitl_manager.get_current_session().status == InterventionStatus.COMPLETED

    await adapter.close()
    adapter.start.assert_awaited_once_with("http://localhost:5000")
    adapter.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_replay_with_hitl_intervention():
    """Test ReplayEngine triggering HITL intervention for a risky action."""
    artifact = SynthScriptArtifact(
        metadata=ArtifactMetadata(name="test_flow", version="1.0", target_surface="web"),
        contract=Contract(),
        flow=[
            StepAction(
                step_id="step_1",
                action_type=ActionType.CLICK,
                target=Target(
                    locators=[Locator(strategy=LocatorStrategy.A11Y_ID, value="submit_transfer")]
                ),
            ),
        ],
        business_exceptions=[],
    )

    hitl_manager = SessionControlManager(headless_mode=True)
    engine = ReplayEngine(hitl_manager=hitl_manager)

    adapter = _playwright_adapter()
    await adapter.start("http://localhost:5000")

    result = await engine.execute(artifact, {"username": "test"}, adapter)

    assert result is not None
    assert hitl_manager.get_current_session() is not None
    assert hitl_manager.get_current_session().status == InterventionStatus.COMPLETED
    assert hitl_manager.get_current_session().context.reason == InterventionReason.RISKY_ACTION

    await adapter.close()


@pytest.mark.asyncio
async def test_hitl_with_mock_banking_app():
    """Test HITL against the mock banking app factory without a live server."""
    from tests.mock_app.app import create_app

    app = create_app()
    assert app is not None

    adapter = _playwright_adapter()
    await adapter.start("http://localhost:5000")

    hitl_manager = SessionControlManager(headless_mode=True)
    hitl_manager.register_adapter(adapter)

    context = InterventionContext(
        reason=InterventionReason.BUSINESS_EXCEPTION,
        message="Record not found - please verify member ID",
        current_url="http://localhost:5000",
    )

    session_id = hitl_manager.request_intervention(context)
    hitl_manager.take_control(session_id)

    action = HumanAction(
        action_type="TYPE",
        element_description="Member ID field",
        value="12345",
    )
    hitl_manager.record_human_action(action)

    final_state = await hitl_manager.resume_automation(session_id)

    assert final_state is not None
    assert hitl_manager.get_current_session().human_actions[0].value == "12345"
    await adapter.close()


@pytest.mark.asyncio
async def test_hitl_timeout_handling():
    """Test HITL timeout and auto-termination."""
    manager = SessionControlManager(
        intervention_timeout_seconds=0.1,
        auto_terminate_on_timeout=True,
    )

    context = InterventionContext(
        reason=InterventionReason.HARD_FAILURE,
        message="Test timeout",
    )

    session_id = manager.request_intervention(context)
    manager.take_control(session_id)

    import time

    time.sleep(0.2)

    assert manager.check_timeout() is True
    assert manager.get_current_session().status == InterventionStatus.ABORTED
    assert manager.get_current_session().resolution == "timeout"


def test_hitl_audit_trail():
    """Test HITL session summary and audit trail."""
    manager = SessionControlManager()

    context = InterventionContext(
        reason=InterventionReason.RISKY_ACTION,
        message="Test audit trail",
        step_id="step_1",
        current_url="http://example.com",
    )

    session_id = manager.request_intervention(context)

    actions = [
        HumanAction(action_type="CLICK", element_description="Button A"),
        HumanAction(action_type="TYPE", element_description="Field B", value="test"),
        HumanAction(action_type="NAVIGATE", value="http://example.com/page2"),
    ]

    for action in actions:
        manager.record_human_action(action)

    summary = manager.get_session_summary(session_id)
    session = manager.get_current_session()

    assert summary["human_actions_count"] == 3
    assert summary["reason"] == "risky_action"
    assert session.context.step_id == "step_1"
    assert len(session.human_actions) == 3
    assert session.human_actions[0].action_type == "CLICK"
    assert session.human_actions[1].value == "test"


def test_automated_terminal_ui():
    """Drive the terminal operator UI with scripted input instead of pexpect."""
    manager = SessionControlManager()
    ui = TerminalOperatorUI(manager)

    context = InterventionContext(
        reason=InterventionReason.RISKY_ACTION,
        message="Test terminal UI",
        current_url="http://localhost:5000",
    )
    session_id = manager.request_intervention(context)

    responses = iter(["1", "Submit button", "5", "y"])
    manager.resume_automation = Mock(return_value={"url": "http://localhost:5000"})

    with patch("builtins.input", side_effect=lambda *_args, **_kwargs: next(responses)):
        ui.take_control(session_id)

    session = manager.get_current_session()
    assert session is not None
    assert len(session.human_actions) == 1
    assert session.human_actions[0].action_type == "CLICK"
    assert session.human_actions[0].element_description == "Submit button"
    manager.resume_automation.assert_called_once_with(session_id)
