"""Playwright-based web adapter for interacting with web applications."""

import asyncio
import time
from pathlib import Path
from typing import Any, Optional
from playwright.async_api import async_playwright, Browser, Page, Locator

from synthscript.adapters.base import SurfaceAdapter, SurfaceState, ActionExecutionResult
from synthscript.adapters.locator_engine import LocatorEngine
from synthscript.security.redactor import PIIRedactor


class PlaywrightWebAdapter(SurfaceAdapter):
    """Playwright-based adapter for web surfaces."""

    def __init__(
        self,
        headless: bool = True,
        screenshot_dir: Optional[Path] = None,
        pii_redactor: Optional[PIIRedactor] = None,
    ):
        """Initialize the Playwright web adapter.

        Args:
            headless: Whether to run browser in headless mode
            screenshot_dir: Directory to save screenshots
            pii_redactor: PII redactor for sensitive data
        """
        self.headless = headless
        self.screenshot_dir = screenshot_dir or Path("screenshots")
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.pii_redactor = pii_redactor or PIIRedactor()
        
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None
        self._locator_engine = LocatorEngine()

    async def start(self, url: str) -> None:
        """Start the browser and navigate to the URL.

        Args:
            url: URL to navigate to
        """
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._page = await self._browser.new_page()
        await self._page.goto(url)

    async def capture_state(self) -> SurfaceState:
        """Capture the current state of the web surface.

        Returns:
            SurfaceState with accessibility tree, screenshot, and OCR text.
        """
        if not self._page:
            raise RuntimeError("Browser not started. Call start() first.")

        timestamp = time.time()
        
        # Capture accessibility tree (including iframes)
        accessibility_tree = await self._capture_accessibility_tree()
        
        # Capture full-page screenshot
        screenshot_path = self.screenshot_dir / f"state_{int(timestamp)}.png"
        await self._page.screenshot(path=str(screenshot_path), full_page=True)
        
        # Extract OCR text from screenshot
        ocr_text = await self._extract_ocr_text(screenshot_path)
        
        # Redact PII from accessibility tree and OCR text
        redacted_tree = self.pii_redactor.redact_accessibility_tree(accessibility_tree)
        redacted_ocr = self.pii_redactor.redact_text(ocr_text).redacted
        
        return SurfaceState(
            accessibility_tree=redacted_tree,
            screenshot_path=screenshot_path,
            ocr_text=redacted_ocr,
            timestamp=timestamp,
            url=self._page.url,
        )

    async def _capture_accessibility_tree(self) -> dict[str, Any]:
        """Capture accessibility tree including iframe contents.

        Returns:
            Nested dictionary representing the accessibility tree.
        """
        if not self._page:
            return {}

        # Get the main page accessibility tree
        tree = await self._get_page_accessibility_tree(self._page)
        
        # Handle iframes by traversing into them
        iframes = await self._page.query_selector_all("iframe")
        for iframe in iframes:
            try:
                frame_content = await iframe.content_handle()
                if frame_content:
                    frame = await iframe.content_frame()
                    if frame:
                        iframe_tree = await self._get_page_accessibility_tree(frame)
                        tree["iframes"] = tree.get("iframes", [])
                        tree["iframes"].append(iframe_tree)
            except Exception:
                # Skip iframes that can't be accessed (cross-origin, etc.)
                continue
        
        return tree

    async def _get_page_accessibility_tree(self, page: Page) -> dict[str, Any]:
        """Get accessibility tree for a specific page/frame.

        Args:
            page: Playwright Page object

        Returns:
            Dictionary representing the accessibility tree.
        """
        try:
            # Use Playwright's accessibility tree snapshot
            snapshot = await page.accessibility.snapshot()
            return self._process_accessibility_node(snapshot) if snapshot else {}
        except Exception:
            # Fallback to DOM snapshot if accessibility tree fails
            return await self._get_dom_snapshot(page)

    def _process_accessibility_node(self, node: dict[str, Any]) -> dict[str, Any]:
        """Process a single accessibility node into a cleaner format.

        Args:
            node: Raw accessibility node from Playwright

        Returns:
            Processed node dictionary.
        """
        processed = {
            "role": node.get("role"),
            "name": node.get("name"),
            "description": node.get("description"),
            "value": node.get("value"),
        }
        
        # Include useful attributes
        if "checked" in node:
            processed["checked"] = node["checked"]
        if "expanded" in node:
            processed["expanded"] = node["expanded"]
        if "disabled" in node:
            processed["disabled"] = node["disabled"]
        
        # Process children recursively
        if "children" in node and node["children"]:
            processed["children"] = [
                self._process_accessibility_node(child) 
                for child in node["children"]
            ]
        
        return processed

    async def _get_dom_snapshot(self, page: Page) -> dict[str, Any]:
        """Fallback: Get basic DOM structure when accessibility tree fails.

        Args:
            page: Playwright Page object

        Returns:
            Basic DOM structure.
        """
        # Get all interactive elements
        elements = await page.evaluate("""
            () => {
                const elements = [];
                const allElements = document.querySelectorAll('*');
                allElements.forEach(el => {
                    if (el.tagName === 'INPUT' || el.tagName === 'BUTTON' || 
                        el.tagName === 'SELECT' || el.tagName === 'A' ||
                        el.tagName === 'TEXTAREA') {
                        elements.push({
                            tagName: el.tagName,
                            id: el.id,
                            name: el.name,
                            type: el.type,
                            textContent: el.textContent?.trim(),
                            placeholder: el.placeholder,
                        });
                    }
                });
                return { elements };
            }
        """)
        return elements

    async def _extract_ocr_text(self, screenshot_path: Path) -> str:
        """Extract text from screenshot using OCR.

        Args:
            screenshot_path: Path to screenshot file

        Returns:
            Extracted text string.
        """
        try:
            import pytesseract
            from PIL import Image
            
            image = Image.open(screenshot_path)
            text = pytesseract.image_to_string(image)
            return text.strip()
        except ImportError:
            # OCR not available, return empty string
            return ""
        except Exception as e:
            # OCR failed, log and return empty string
            print(f"OCR extraction failed: {e}")
            return ""

    async def execute_action(
        self,
        action_type: str,
        target: Optional[dict[str, Any]] = None,
        input_value: Optional[str] = None,
    ) -> ActionExecutionResult:
        """Execute an action on the web surface.

        Args:
            action_type: Type of action (CLICK, TYPE_AND_ENTER, EXTRACT_TEXT, WAIT)
            target: Target specification with locators
            input_value: Input value for TYPE_AND_ENTER actions

        Returns:
            ActionExecutionResult with success status and new state.
        """
        if not self._page:
            raise RuntimeError("Browser not started. Call start() first.")

        try:
            if action_type == "CLICK":
                return await self._execute_click(target)
            elif action_type == "TYPE_AND_ENTER":
                return await self._execute_type_and_enter(target, input_value)
            elif action_type == "EXTRACT_TEXT":
                return await self._execute_extract_text(target)
            elif action_type == "WAIT":
                return await self._execute_wait()
            else:
                return ActionExecutionResult(
                    success=False,
                    error_message=f"Unknown action type: {action_type}",
                )
        except Exception as e:
            return ActionExecutionResult(
                success=False,
                error_message=str(e),
            )

    async def _execute_click(self, target: Optional[dict[str, Any]]) -> ActionExecutionResult:
        """Execute a click action.

        Args:
            target: Target specification with locators

        Returns:
            ActionExecutionResult.
        """
        if not target:
            return ActionExecutionResult(
                success=False,
                error_message="Target required for CLICK action",
            )

        # Use locator engine to find the element
        locator = await self._locator_engine.locate_element(self._page, target)
        if not locator:
            return ActionExecutionResult(
                success=False,
                error_message="Could not locate element",
            )

        await locator.click()
        new_state = await self.capture_state()
        
        return ActionExecutionResult(
            success=True,
            new_state=new_state,
        )

    async def _execute_type_and_enter(
        self,
        target: Optional[dict[str, Any]],
        input_value: Optional[str],
    ) -> ActionExecutionResult:
        """Execute a type and enter action.

        Args:
            target: Target specification with locators
            input_value: Value to type

        Returns:
            ActionExecutionResult.
        """
        if not target:
            return ActionExecutionResult(
                success=False,
                error_message="Target required for TYPE_AND_ENTER action",
            )

        if not input_value:
            return ActionExecutionResult(
                success=False,
                error_message="Input value required for TYPE_AND_ENTER action",
            )

        # Use locator engine to find the element
        locator = await self._locator_engine.locate_element(self._page, target)
        if not locator:
            return ActionExecutionResult(
                success=False,
                error_message="Could not locate element",
            )

        await locator.fill(input_value)
        await locator.press("Enter")
        new_state = await self.capture_state()
        
        return ActionExecutionResult(
            success=True,
            new_state=new_state,
        )

    async def _execute_extract_text(self, target: Optional[dict[str, Any]]) -> ActionExecutionResult:
        """Execute a text extraction action.

        Args:
            target: Target specification with locators

        Returns:
            ActionExecutionResult with extracted text.
        """
        if not target:
            return ActionExecutionResult(
                success=False,
                error_message="Target required for EXTRACT_TEXT action",
            )

        # Use locator engine to find the element
        locator = await self._locator_engine.locate_element(self._page, target)
        if not locator:
            return ActionExecutionResult(
                success=False,
                error_message="Could not locate element",
            )

        text = await locator.inner_text()
        
        return ActionExecutionResult(
            success=True,
            extracted_data=text,
        )

    async def _execute_wait(self) -> ActionExecutionResult:
        """Execute a wait action.

        Returns:
            ActionExecutionResult.
        """
        # Wait for a short duration to allow page to settle
        await asyncio.sleep(1)
        new_state = await self.capture_state()
        
        return ActionExecutionResult(
            success=True,
            new_state=new_state,
        )

    async def close(self) -> None:
        """Clean up browser resources."""
        if self._page:
            await self._page.close()
            self._page = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
