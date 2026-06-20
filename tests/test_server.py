"""Tests for the FastMCP server: registration, wiring, and graceful degradation."""

import asyncio
import json
from unittest.mock import AsyncMock

from umami_mcp import rag, server, web
from umami_mcp.dates import to_unix_millis


def test_expected_tools_and_prompt_are_registered():
    tools = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert tools == {
        "get_websites",
        "get_website_stats",
        "get_website_metrics",
        "get_pageview_series",
        "get_active_visitors",
        "get_session_ids",
        "get_tracking_data",
        "get_docs",
        "get_html",
        "get_screenshot",
    }
    prompts = {p.name for p in asyncio.run(server.mcp.list_prompts())}
    assert prompts == {"create_dashboard"}


def test_normalize_event():
    assert server._normalize_event(None) is None
    assert server._normalize_event("") is None
    assert server._normalize_event("None") is None
    assert server._normalize_event("  checkout  ") == "checkout"


async def test_get_website_stats_converts_dates_and_serializes(monkeypatch):
    fake = AsyncMock()
    fake.get_website_stats.return_value = {"pageviews": {"value": 5}}
    monkeypatch.setattr(server, "_client", fake)

    out = await server.get_website_stats("w1", "2024-01-01", "2024-01-31")

    assert json.loads(out) == {"pageviews": {"value": 5}}
    # Dates are converted to UTC ms, end inclusive of the whole day.
    fake.get_website_stats.assert_awaited_once_with(
        "w1", to_unix_millis("2024-01-01"), to_unix_millis("2024-01-31", end_of_day=True)
    )


async def test_get_docs_without_rag_returns_install_hint(monkeypatch):
    monkeypatch.setattr(rag, "rag_available", lambda: False)
    out = await server.get_docs("why do users churn", "w1", "2024-01-01", "2024-01-31")
    assert out == rag.INSTALL_HINT


async def test_get_screenshot_without_extra_returns_install_hint(monkeypatch):
    monkeypatch.setattr(web, "screenshot_available", lambda: False)
    out = await server.get_screenshot("https://example.com")
    assert out == web.INSTALL_HINT


def test_create_dashboard_prompt_includes_arguments():
    text = server.create_dashboard("My Site", "2024-01-01", "2024-01-31", "UTC")
    assert "My Site" in text
    assert "2024-01-01" in text
    assert "get_websites" in text
