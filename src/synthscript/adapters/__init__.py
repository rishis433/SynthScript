"""Surface adapters for interacting with different UI surfaces."""

from .base import SurfaceAdapter, SurfaceState, ActionExecutionResult
from .playwright_adapter import PlaywrightWebAdapter
from .locator_engine import LocatorEngine

__all__ = [
    "SurfaceAdapter",
    "SurfaceState",
    "ActionExecutionResult",
    "PlaywrightWebAdapter",
    "LocatorEngine",
]
