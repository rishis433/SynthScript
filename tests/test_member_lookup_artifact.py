"""Runnable Playwright test generated from ``evidence/artifact.json``."""

from threading import Thread

import pytest
import pytest_asyncio
from werkzeug.serving import make_server

from tests.mock_app.app import create_app
from playwright.async_api import Page, async_playwright


class MemberLookupPage:
    """Page object for the member_lookup artifact's web flow."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.frame = page.frame_locator("#member-lookup-frame")
        self.member_id_input = self.frame.locator("#member-id-input")
        self.search_button = self.frame.locator("#search-button")

    async def open(self, base_url: str) -> None:
        await self.page.goto(base_url)

    async def search_member(self, member_id: str) -> None:
        await self.member_id_input.fill(member_id)
        await self.search_button.click()

    def result_row(self, label: str):
        return self.frame.locator("tr").filter(has_text=label).last


@pytest.fixture
def mock_server():
    server = make_server("127.0.0.1", 0, create_app())
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest_asyncio.fixture
async def browser_page():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page()
        try:
            yield page
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_member_lookup_artifact(mock_server, browser_page):
    """Replay the artifact for a known member and validate its output."""
    member_lookup = MemberLookupPage(browser_page)
    await member_lookup.open(mock_server)
    await member_lookup.search_member("12345")

    result = member_lookup.frame.locator(".result-table")
    await result.wait_for()
    assert await result.get_by_text("12345", exact=True).count() == 1
    assert await result.get_by_text("John Smith", exact=True).count() == 1
    assert await result.get_by_text("$15,234.56", exact=True).count() == 1
    assert await result.get_by_text("Active", exact=True).count() == 1
