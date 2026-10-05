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
        "get_event_data",
        "get_active_visitors",
        "get_session_ids",
        "get_tracking_data",
        "get_docs",
        "get_html",
        "get_screenshot",
        "run_report",
        "list_reports",
        "save_report",
        "delete_report",
        "list_segments",
        "save_segment",
        "delete_segment",
        "list_links",
        "save_link",
        "delete_link",
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
        "w1",
        to_unix_millis("2024-01-01"),
        to_unix_millis("2024-01-31", end_of_day=True),
        hostname=None,
        filters={},
    )


def test_filters_maps_segment_and_bounce():
    assert server._filters() == {}
    assert server._filters("None", False) == {}
    assert server._filters("seg-1", True) == {"segment": "seg-1", "excludeBounce": "true"}


async def test_run_report_sends_iso_dates_and_filters(monkeypatch):
    fake = AsyncMock()
    fake.run_report.return_value = [{"visitors": 3}]
    monkeypatch.setattr(server, "_client", fake)

    steps = {
        "window": 60,
        "steps": [{"type": "event", "value": "a"}, {"type": "event", "value": "b"}],
    }
    await server.run_report(
        "w1", "funnel", "2024-01-01", "2024-01-31", steps, hostname="x.ca", exclude_bounce=True
    )

    website_id, type_, params, filters = fake.run_report.await_args.args
    assert (website_id, type_) == ("w1", "funnel")
    assert params["startDate"] == "2024-01-01T00:00:00+00:00"
    assert params["endDate"].startswith("2024-01-31T23:59:59")
    assert params["steps"] == steps["steps"]
    assert filters == {"excludeBounce": "true", "hostname": "x.ca"}


async def test_get_event_data_lists_properties_or_breaks_one_down(monkeypatch):
    fake = AsyncMock()
    fake.get_event_data_properties.return_value = [{"eventName": "e", "propertyName": "p"}]
    fake.get_event_data_values.return_value = [{"value": "gst", "total": 7}]
    monkeypatch.setattr(server, "_client", fake)
    start, end = to_unix_millis("2024-01-01"), to_unix_millis("2024-01-31", end_of_day=True)

    listed = await server.get_event_data("w1", "2024-01-01", "2024-01-31")
    assert json.loads(listed) == [{"eventName": "e", "propertyName": "p"}]
    fake.get_event_data_properties.assert_awaited_once_with("w1", start, end)

    values = await server.get_event_data(
        "w1", "2024-01-01", "2024-01-31", "feature-opened", "feature"
    )
    assert json.loads(values) == [{"value": "gst", "total": 7}]
    fake.get_event_data_values.assert_awaited_once_with(
        "w1", start, end, "feature-opened", "feature"
    )

    # Half a breakdown is a question that cannot be asked; say so, call nothing.
    half = await server.get_event_data("w1", "2024-01-01", "2024-01-31", "feature-opened")
    assert "both" in half
    assert fake.get_event_data_values.await_count == 1


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
