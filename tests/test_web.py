"""Tests for the live-page helpers (HTML fetch + screenshot availability)."""

import httpx

from umami_mcp import web


async def test_fetch_html_returns_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>hi</body></html>")

    html = await web.fetch_html("https://example.com", transport=httpx.MockTransport(handler))
    assert "hi" in html


async def test_fetch_html_raises_on_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="nope")

    try:
        await web.fetch_html("https://example.com", transport=httpx.MockTransport(handler))
    except httpx.HTTPStatusError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected HTTPStatusError")


def test_screenshot_availability_is_boolean_and_hint_is_actionable():
    assert isinstance(web.screenshot_available(), bool)
    # The hint should tell the user exactly what to install.
    assert "screenshot" in web.INSTALL_HINT
    assert "playwright" in web.INSTALL_HINT.lower()
