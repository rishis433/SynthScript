"""Integration tests for surface adapters and locator engine."""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch

from synthscript.adapters.base import SurfaceState, ActionExecutionResult
from synthscript.adapters.playwright_adapter import PlaywrightWebAdapter
from synthscript.adapters.locator_engine import LocatorEngine
from synthscript.schema.models import Locator, LocatorStrategy, ResolutionStrategy


@pytest.fixture
def mock_page():
    """Create a mock Playwright Page."""
    page = Mock()
    page.url = "http://localhost:5000"
    page.accessibility = Mock()
    page.accessibility.snapshot = AsyncMock(return_value={
        "role": "WebArea",
        "name": "Legacy Banking System",
        "children": []
    })
    page.screenshot = AsyncMock()
    page.query_selector_all = AsyncMock(return_value=[])
    page.locator = Mock(return_value=Mock())
    page.get_by_test_id = Mock(return_value=Mock(count=AsyncMock(return_value=0)))
    page.get_by_label = Mock(return_value=Mock(count=AsyncMock(return_value=0)))
    page.get_by_text = Mock(return_value=Mock(count=AsyncMock(return_value=0)))
    return page


@pytest.fixture
def mock_browser():
    """Create a mock Playwright Browser."""
    browser = Mock()
    browser.new_page = AsyncMock()
    browser.close = AsyncMock()
    return browser


@pytest.fixture
def mock_playwright():
    """Create a mock Playwright instance."""
    pw = Mock()
    pw.chromium = Mock()
    pw.chromium.launch = AsyncMock()
    pw.stop = AsyncMock()
    return pw


class TestLocatorEngine:
    """Tests for the LocatorEngine."""

    @pytest.mark.asyncio
    async def test_locate_by_a11y_id_with_test_id(self, mock_page):
        """Test locating element by test ID."""
        engine = LocatorEngine()
        locator = Locator(strategy=LocatorStrategy.A11Y_ID, value="submit-button")
        
        mock_element = Mock()
        mock_element.count = AsyncMock(return_value=1)
        mock_page.get_by_test_id.return_value = mock_element
        
        result = await engine._locate_by_a11y_id(mock_page, locator)
        
        assert result is not None
        mock_page.get_by_test_id.assert_called_once_with("submit-button")

    @pytest.mark.asyncio
    async def test_locate_by_a11y_id_with_id(self, mock_page):
        """Test locating element by standard ID."""
        engine = LocatorEngine()
        locator = Locator(strategy=LocatorStrategy.A11Y_ID, value="member-id-input")
        
        mock_element = Mock()
        mock_element.count = AsyncMock(return_value=1)
        mock_page.locator = Mock(return_value=mock_element)
        mock_page.get_by_test_id.return_value = Mock(count=AsyncMock(return_value=0))
        mock_page.get_by_label.return_value = Mock(count=AsyncMock(return_value=0))
        
        result = await engine._locate_by_a11y_id(mock_page, locator)
        
        assert result is not None
        mock_page.locator.assert_called_with("#member-id-input")

    @pytest.mark.asyncio
    async def test_locate_by_ocr_relative_right_of(self, mock_page):
        """Test OCR-relative locating 'right of' text."""
        engine = LocatorEngine()
        locator = Locator(strategy=LocatorStrategy.OCR_RELATIVE, value="right of 'Member ID'")
        
        # Mock reference element
        mock_ref = Mock()
        mock_ref.count = AsyncMock(return_value=1)
        mock_ref.bounding_box = AsyncMock(return_value={"x": 100, "y": 100, "width": 50, "height": 20})
        mock_page.get_by_text.return_value = mock_ref
        
        # Mock target element
        mock_target = Mock()
        mock_target.bounding_box = AsyncMock(return_value={"x": 200, "y": 105, "width": 100, "height": 30})
        
        mock_all = Mock()
        mock_all.count = AsyncMock(return_value=1)
        mock_all.nth = Mock(return_value=mock_target)
        mock_page.locator.return_value = mock_all
        
        result = await engine._locate_by_ocr_relative(mock_page, locator)
        
        assert result is not None

    @pytest.mark.asyncio
    async def test_locate_by_xpath(self, mock_page):
        """Test locating element by XPath."""
        engine = LocatorEngine()
        locator = Locator(strategy=LocatorStrategy.XPATH, value="//button[@type='submit']")
        
        mock_element = Mock()
        mock_element.count = AsyncMock(return_value=1)
        mock_page.locator = Mock(return_value=mock_element)
        
        result = await engine._locate_by_xpath(mock_page, locator)
        
        assert result is not None
        mock_page.locator.assert_called_with("xpath=//button[@type='submit']")

    @pytest.mark.asyncio
    async def test_cascade_strategy(self, mock_page):
        """Test cascade resolution strategy."""
        engine = LocatorEngine()
        
        target = {
            "locators": [
                {"strategy": "a11y_id", "value": "test-id"},
                {"strategy": "xpath", "value": "//button"},
            ],
            "resolution_strategy": "cascade",
        }
        
        # First strategy fails, second succeeds
        mock_page.get_by_test_id.return_value = Mock(count=AsyncMock(return_value=0))
        mock_page.get_by_label.return_value = Mock(count=AsyncMock(return_value=0))
        
        mock_element = Mock()
        mock_element.count = AsyncMock(return_value=1)
        mock_page.locator = Mock(return_value=mock_element)
        
        result = await engine.locate_element(mock_page, target)
        
        assert result is not None

    @pytest.mark.asyncio
    async def test_first_match_strategy(self, mock_page):
        """Test first_match resolution strategy."""
        engine = LocatorEngine()
        
        target = {
            "locators": [
                {"strategy": "a11y_id", "value": "test-id"},
                {"strategy": "xpath", "value": "//button"},
            ],
            "resolution_strategy": "first_match",
        }
        
        # First strategy succeeds
        mock_element = Mock()
        mock_element.count = AsyncMock(return_value=1)
        mock_page.get_by_test_id.return_value = mock_element
        
        result = await engine.locate_element(mock_page, target)
        
        assert result is not None
        # Should not try second strategy
        assert mock_page.locator.call_count == 0


class TestPlaywrightWebAdapter:
    """Tests for the PlaywrightWebAdapter."""

    def test_adapter_initialization(self):
        """Test adapter initialization."""
        adapter = PlaywrightWebAdapter(headless=True)
        
        assert adapter.headless is True
        assert adapter.screenshot_dir.exists()
        assert adapter._browser is None
        assert adapter._page is None

    @pytest.mark.asyncio
    async def test_start_browser(self, mock_playwright, mock_browser):
        """Test starting the browser."""
        adapter = PlaywrightWebAdapter(headless=True)
        
        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_page = AsyncMock(return_value=Mock(goto=AsyncMock()))
        
        async_context_manager = AsyncMock()
        async_context_manager.start = AsyncMock(return_value=mock_playwright)
        
        with patch("synthscript.adapters.playwright_adapter.async_playwright", return_value=async_context_manager):
            await adapter.start("http://localhost:5000")
            
            async_context_manager.start.assert_called_once()
            mock_playwright.chromium.launch.assert_called_once_with(headless=True)
            mock_browser.new_page.assert_called_once()
            assert adapter._browser is not None
            assert adapter._page is not None

    @pytest.mark.asyncio
    async def test_capture_state(self, mock_page):
        """Test capturing surface state."""
        adapter = PlaywrightWebAdapter(headless=True)
        adapter._page = mock_page
        
        with patch.object(adapter, "_extract_ocr_text", return_value="OCR text"):
            state = await adapter.capture_state()
            
            assert isinstance(state, SurfaceState)
            assert state.accessibility_tree is not None
            assert state.screenshot_path is not None
            assert state.ocr_text == "OCR text"
            assert state.url == "http://localhost:5000"
            assert state.timestamp > 0

    @pytest.mark.asyncio
    async def test_capture_state_without_page(self):
        """Test capturing state without starting browser."""
        adapter = PlaywrightWebAdapter(headless=True)
        
        with pytest.raises(RuntimeError, match="Browser not started"):
            await adapter.capture_state()

    @pytest.mark.asyncio
    async def test_execute_click_success(self, mock_page):
        """Test successful click execution."""
        adapter = PlaywrightWebAdapter(headless=True)
        adapter._page = mock_page
        
        target = {
            "locators": [{"strategy": "a11y_id", "value": "button"}],
            "resolution_strategy": "cascade",
        }
        
        mock_element = Mock()
        mock_element.click = AsyncMock()
        mock_element.count = AsyncMock(return_value=1)
        mock_page.get_by_test_id.return_value = mock_element
        
        with patch.object(adapter, "capture_state", return_value=SurfaceState(accessibility_tree={})):
            result = await adapter.execute_action("CLICK", target)
            
            assert result.success is True
            assert result.new_state is not None
            mock_element.click.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_click_no_target(self, mock_page):
        """Test click execution without target."""
        adapter = PlaywrightWebAdapter(headless=True)
        adapter._page = mock_page
        
        result = await adapter.execute_action("CLICK", None)
        
        assert result.success is False
        assert "Target required" in result.error_message

    @pytest.mark.asyncio
    async def test_execute_type_and_enter(self, mock_page):
        """Test type and enter execution."""
        adapter = PlaywrightWebAdapter(headless=True)
        adapter._page = mock_page
        
        target = {
            "locators": [{"strategy": "a11y_id", "value": "input"}],
            "resolution_strategy": "cascade",
        }
        
        mock_element = Mock()
        mock_element.fill = AsyncMock()
        mock_element.press = AsyncMock()
        mock_element.count = AsyncMock(return_value=1)
        mock_page.get_by_test_id.return_value = mock_element
        
        with patch.object(adapter, "capture_state", return_value=SurfaceState(accessibility_tree={})):
            result = await adapter.execute_action("TYPE_AND_ENTER", target, "test value")
            
            assert result.success is True
            mock_element.fill.assert_called_once_with("test value")
            mock_element.press.assert_called_once_with("Enter")

    @pytest.mark.asyncio
    async def test_execute_extract_text(self, mock_page):
        """Test text extraction execution."""
        adapter = PlaywrightWebAdapter(headless=True)
        adapter._page = mock_page
        
        target = {
            "locators": [{"strategy": "a11y_id", "value": "element"}],
            "resolution_strategy": "cascade",
        }
        
        mock_element = Mock()
        mock_element.inner_text = AsyncMock(return_value="Extracted text")
        mock_element.count = AsyncMock(return_value=1)
        mock_page.get_by_test_id.return_value = mock_element
        
        result = await adapter.execute_action("EXTRACT_TEXT", target)
        
        assert result.success is True
        assert result.extracted_data == "Extracted text"

    @pytest.mark.asyncio
    async def test_execute_wait(self, mock_page):
        """Test wait execution."""
        adapter = PlaywrightWebAdapter(headless=True)
        adapter._page = mock_page
        
        with patch.object(adapter, "capture_state", return_value=SurfaceState(accessibility_tree={})):
            result = await adapter.execute_action("WAIT")
            
            assert result.success is True
            assert result.new_state is not None

    @pytest.mark.asyncio
    async def test_execute_unknown_action(self, mock_page):
        """Test executing unknown action type."""
        adapter = PlaywrightWebAdapter(headless=True)
        adapter._page = mock_page
        
        result = await adapter.execute_action("UNKNOWN_ACTION")
        
        assert result.success is False
        assert "Unknown action type" in result.error_message

    @pytest.mark.asyncio
    async def test_close(self, mock_playwright, mock_browser):
        """Test closing the adapter."""
        adapter = PlaywrightWebAdapter(headless=True)
        adapter._playwright = mock_playwright
        adapter._browser = mock_browser
        mock_page = Mock()
        mock_page.close = AsyncMock()
        adapter._page = mock_page
        
        await adapter.close()
        
        mock_page.close.assert_called_once()
        mock_browser.close.assert_called_once()
        mock_playwright.stop.assert_called_once()
        assert adapter._page is None
        assert adapter._browser is None
        assert adapter._playwright is None


class TestOCRIntegration:
    """Tests for OCR integration."""

    @pytest.mark.asyncio
    async def test_ocr_extraction_without_pytesseract(self, tmp_path):
        """Test OCR extraction when pytesseract is not available."""
        adapter = PlaywrightWebAdapter(headless=True, screenshot_dir=tmp_path)
        
        # Create a dummy image file
        img_path = tmp_path / "test.png"
        img_path.write_text("dummy image content")
        
        with patch("builtins.__import__", side_effect=ImportError("No module named 'pytesseract'")):
            result = await adapter._extract_ocr_text(img_path)
            
            assert result == ""
