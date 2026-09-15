"""Locator engine with cascade strategy for finding UI elements."""

import re
from typing import Any, Optional
from playwright.async_api import Page, Locator

from synthscript.schema.models import (
    Locator as LocatorModel,
    LocatorStrategy,
    ResolutionStrategy,
)


class LocatorEngine:
    """Engine for locating UI elements using a cascade strategy."""

    def __init__(self):
        """Initialize the locator engine."""
        self._strategy_handlers = {
            LocatorStrategy.A11Y_ID: self._locate_by_a11y_id,
            LocatorStrategy.OCR_RELATIVE: self._locate_by_ocr_relative,
            LocatorStrategy.CV_TEMPLATE: self._locate_by_cv_template,
            LocatorStrategy.XPATH: self._locate_by_xpath,
        }

    async def locate_element(
        self,
        page: Page,
        target: dict[str, Any],
    ) -> Optional[Locator]:
        """Locate an element using the cascade strategy.

        Args:
            page: Playwright Page object
            target: Target specification with locators and resolution strategy

        Returns:
            Playwright Locator if found, None otherwise.
        """
        locators_data = target.get("locators", [])
        resolution_strategy = target.get(
            "resolution_strategy",
            ResolutionStrategy.CASCADE,
        )

        if not locators_data:
            return None

        # Convert locator data to LocatorModel objects
        locators = [
            LocatorModel(**loc_data) if isinstance(loc_data, dict) else loc_data
            for loc_data in locators_data
        ]

        if resolution_strategy == ResolutionStrategy.FIRST_MATCH:
            # Try each locator in order, return first success
            for locator in locators:
                element = await self._try_locator(page, locator)
                if element:
                    return element
        else:
            # Cascade: try each strategy in priority order
            # Group locators by strategy
            strategy_order = [
                LocatorStrategy.A11Y_ID,
                LocatorStrategy.OCR_RELATIVE,
                LocatorStrategy.CV_TEMPLATE,
                LocatorStrategy.XPATH,
            ]
            
            for strategy in strategy_order:
                # Try all locators with this strategy
                for locator in locators:
                    if locator.strategy == strategy:
                        element = await self._try_locator(page, locator)
                        if element:
                            return element

        return None

    async def _try_locator(
        self,
        page: Page,
        locator: LocatorModel,
    ) -> Optional[Locator]:
        """Try to locate an element using a specific locator.

        Args:
            page: Playwright Page object
            locator: Locator specification

        Returns:
            Playwright Locator if found, None otherwise.
        """
        handler = self._strategy_handlers.get(locator.strategy)
        if not handler:
            return None

        try:
            element = await handler(page, locator)
            if element and await element.count() > 0:
                return element
        except Exception:
            # Strategy failed, continue to next
            pass

        return None

    async def _locate_by_a11y_id(
        self,
        page: Page,
        locator: LocatorModel,
    ) -> Optional[Locator]:
        """Locate element by accessibility ID.

        Args:
            page: Playwright Page object
            locator: Locator specification

        Returns:
            Playwright Locator if found.
        """
        # Try to find by id attribute
        element = page.get_by_test_id(locator.value)
        if await element.count() > 0:
            return element

        # Try aria-label
        element = page.get_by_label(locator.value)
        if await element.count() > 0:
            return element

        # Try standard id
        element = page.locator(f"#{locator.value}")
        if await element.count() > 0:
            return element

        # Try name attribute
        element = page.locator(f"[name='{locator.value}']")
        if await element.count() > 0:
            return element

        return None

    async def _locate_by_ocr_relative(
        self,
        page: Page,
        locator: LocatorModel,
    ) -> Optional[Locator]:
        """Locate element using OCR-relative positioning.

        Args:
            page: Playwright Page object
            locator: Locator specification with OCR relative value
                Format: "right of 'text'", "left of 'text'", "below 'text'", "above 'text'"

        Returns:
            Playwright Locator if found.
        """
        # Parse the OCR relative value
        # Expected format: "direction of 'reference_text'"
        match = re.match(
            r"(right of|left of|below|above)\s+['\"](.+?)['\"]",
            locator.value,
            re.IGNORECASE,
        )
        
        if not match:
            return None

        direction = match.group(1).lower()
        reference_text = match.group(2)

        # Find the reference element by text
        reference_locator = page.get_by_text(reference_text)
        if await reference_locator.count() == 0:
            # Try partial text match
            reference_locator = page.get_by_text(reference_text, exact=False)
        
        if await reference_locator.count() == 0:
            return None

        # Get bounding box of reference element
        try:
            box = await reference_locator.bounding_box()
            if not box:
                return None
        except Exception:
            return None

        # Search for interactive elements in the specified direction
        all_inputs = page.locator("input, button, select, textarea, a")
        count = await all_inputs.count()
        
        for i in range(count):
            element = all_inputs.nth(i)
            try:
                elem_box = await element.bounding_box()
                if not elem_box:
                    continue

                # Check if element is in the right direction
                if self._is_in_direction(box, elem_box, direction):
                    return element
            except Exception:
                continue

        return None

    def _is_in_direction(
        self,
        reference_box: dict[str, float],
        element_box: dict[str, float],
        direction: str,
    ) -> bool:
        """Check if an element is in a specific direction relative to reference.

        Args:
            reference_box: Bounding box of reference element
            element_box: Bounding box of target element
            direction: Direction to check (right of, left of, below, above)

        Returns:
            True if element is in the specified direction.
        """
        ref_center_x = reference_box["x"] + reference_box["width"] / 2
        ref_center_y = reference_box["y"] + reference_box["height"] / 2
        elem_center_x = element_box["x"] + element_box["width"] / 2
        elem_center_y = element_box["y"] + element_box["height"] / 2

        if direction == "right of":
            return elem_center_x > ref_center_x and abs(elem_center_y - ref_center_y) < 50
        elif direction == "left of":
            return elem_center_x < ref_center_x and abs(elem_center_y - ref_center_y) < 50
        elif direction == "below":
            return elem_center_y > ref_center_y and abs(elem_center_x - ref_center_x) < 50
        elif direction == "above":
            return elem_center_y < ref_center_y and abs(elem_center_x - ref_center_x) < 50

        return False

    async def _locate_by_cv_template(
        self,
        page: Page,
        locator: LocatorModel,
    ) -> Optional[Locator]:
        """Locate element using computer vision template matching.

        Args:
            page: Playwright Page object
            locator: Locator specification with template image path

        Returns:
            Playwright Locator if found.
        """
        # This would use OpenCV or similar for template matching
        # For now, we'll implement a basic version using screenshot comparison
        # In a production system, this would use more sophisticated CV
        
        try:
            # Take a screenshot and search for the template
            screenshot = await page.screenshot()
            
            # This is a placeholder - real implementation would use OpenCV
            # to match the template image against the screenshot
            # and return the element at the matched position
            
            # For now, return None as this requires additional dependencies
            return None
        except Exception:
            return None

    async def _locate_by_xpath(
        self,
        page: Page,
        locator: LocatorModel,
    ) -> Optional[Locator]:
        """Locate element by XPath.

        Args:
            page: Playwright Page object
            locator: Locator specification with XPath

        Returns:
            Playwright Locator if found.
        """
        try:
            element = page.locator(f"xpath={locator.value}")
            if await element.count() > 0:
                return element
        except Exception:
            pass

        return None
