"""Abstract base class for surface adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional
from pathlib import Path


@dataclass
class SurfaceState:
    """Represents the current state of a UI surface."""

    accessibility_tree: dict[str, Any]
    screenshot_path: Optional[Path] = None
    ocr_text: Optional[str] = None
    timestamp: float = 0.0
    url: Optional[str] = None


@dataclass
class ActionExecutionResult:
    """Result of executing an action on a surface."""

    success: bool
    error_message: Optional[str] = None
    new_state: Optional[SurfaceState] = None
    extracted_data: Optional[Any] = None


class SurfaceAdapter(ABC):
    """Abstract base class for interacting with different UI surfaces."""

    @abstractmethod
    async def capture_state(self) -> SurfaceState:
        """Capture the current state of the surface.

        Returns:
            SurfaceState containing accessibility tree, screenshot, and OCR text.
        """
        pass

    @abstractmethod
    async def execute_action(
        self,
        action_type: str,
        target: Optional[dict[str, Any]] = None,
        input_value: Optional[str] = None,
    ) -> ActionExecutionResult:
        """Execute an action on the surface.

        Args:
            action_type: Type of action (CLICK, TYPE_AND_ENTER, EXTRACT_TEXT, WAIT)
            target: Target specification with locators
            input_value: Input value for TYPE_AND_ENTER actions

        Returns:
            ActionExecutionResult with success status and new state.
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources."""
        pass
