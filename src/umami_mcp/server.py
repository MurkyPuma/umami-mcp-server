"""FastMCP server exposing Umami analytics (and live-page helpers) as MCP tools.

Rewritten from the original low-level ``mcp.server.Server`` implementation (which
hand-wrote ~350 lines of JSON Schema) to FastMCP, so tool schemas are generated from
type hints and docstrings. The client is built lazily on first tool call, so importing
this module never requires credentials or a network round-trip.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP, Image

from . import rag, web
from .client import UmamiClient
from .config import Settings
from .dates import to_unix_millis

mcp = FastMCP(
    "umami",
    instructions=(
        "Tools for querying Umami web analytics: website stats, metrics, pageview "
        "time series, live visitors, and per-session user journeys. Date arguments "
        "accept 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS' and are interpreted as UTC. "
        "Call get_websites first to resolve a website name to its id."
    ),
)

MetricType = Literal[
    "path", "entry", "exit", "title", "query",
    "referrer", "browser", "os", "device", "country", "language", "event",
    "url",  # deprecated alias for "path"; translated by the client
]
TimeUnit = Literal["hour", "day", "month"]

_client: UmamiClient | None = None


def _get_client() -> UmamiClient:
    """Lazily build the Umami client from the environment on first use."""
    global _client
    if _client is None:
        _client = UmamiClient(Settings.from_env())
    return _client


def _json(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


def _normalize_event(event_name: str | None) -> str | None:
    """Treat empty string and the literal 'None' as 'no event filter'."""
    if event_name is None:
        return None
    cleaned = event_name.strip()
    return None if cleaned in ("", "None", "none", "null") else cleaned


# -- analytics tools --------------------------------------------------------


@mcp.tool()
async def get_websites() -> str:
    """List the websites in your Umami account, with their ids, names, and domains.

    Takes no arguments. Use the returned ``id`` for the other tools. If a team id is
    configured the team's websites are returned; otherwise your personal websites.
    """
    return _json(await _get_client().get_websites())


@mcp.tool()
async def get_website_stats(website_id: str, start_at: str, end_at: str) -> str:
    """Get overview metrics for a website over a date range.

    Returns pageviews, unique visitors, visits, bounces, and total time. If you get
    no data, double-check the date range before assuming there is none.

    Args:
        website_id: The website id (from get_websites).
        start_at: Range start, 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS' (UTC).
        end_at: Range end, same formats (a bare date includes the whole day).
    """
    data = await _get_client().get_website_stats(
        website_id, to_unix_millis(start_at), to_unix_millis(end_at, end_of_day=True)
    )
    return _json(data)


@mcp.tool()
async def get_website_metrics(
    website_id: str, start_at: str, end_at: str, type: MetricType
) -> str:
    """Get a breakdown of visitors by a dimension over a date range.

    ``type`` selects the dimension: path (pages), entry/exit (landing and exit
    pages), title (page titles), query (query strings), referrer (traffic
    sources), browser, os, device, country, language, or event (tally of tracked
    events). ``url`` is accepted as a deprecated alias for ``path``.

    Args:
        website_id: The website id (from get_websites).
        start_at: Range start (UTC).
        end_at: Range end (UTC).
        type: One of path, entry, exit, title, query, referrer, browser, os,
            device, country, language, event (or the legacy alias url).
    """
    data = await _get_client().get_website_metrics(
        website_id, to_unix_millis(start_at), to_unix_millis(end_at, end_of_day=True), type
    )
    return _json(data)


@mcp.tool()
async def get_pageview_series(
    website_id: str,
    start_at: str,
    end_at: str,
    unit: TimeUnit,
    timezone: str = "UTC",
) -> str:
    """Get a pageviews-and-sessions time series, bucketed by hour, day, or month.

    Use 'hour' for short ranges (1-7 days), 'day' for medium ranges, 'month' for long
    ranges.

    Args:
        website_id: The website id (from get_websites).
        start_at: Range start (UTC).
        end_at: Range end (UTC).
        unit: Bucket size: hour, day, or month.
        timezone: IANA timezone for bucketing, e.g. 'UTC' or 'Europe/London'.
    """
    data = await _get_client().get_pageview_series(
        website_id,
        to_unix_millis(start_at),
        to_unix_millis(end_at, end_of_day=True),
        unit,
        timezone,
    )
    return _json(data)


@mcp.tool()
async def get_active_visitors(website_id: str) -> str:
    """Get the number of visitors currently active on a website (real-time).

    Args:
        website_id: The website id (from get_websites).
    """
    return _json(await _get_client().get_active_visitors(website_id))


@mcp.tool()
async def get_session_ids(
    website_id: str,
    start_at: str,
    end_at: str,
    event_name: str | None = None,
) -> str:
    """Get the unique session ids active in a range, optionally filtered to an event.

    Use this to find sessions to inspect with get_tracking_data, not to count unique
    visitors (use get_website_stats for counts). Pass ``event_name`` to keep only
    sessions that fired that event, or omit it for all sessions.

    Args:
        website_id: The website id (from get_websites).
        start_at: Range start (UTC).
        end_at: Range end (UTC).
        event_name: Optional event name to filter by (e.g. 'checkout_completed').
    """
    ids = await _get_client().get_event_session_ids(
        website_id,
        to_unix_millis(start_at),
        to_unix_millis(end_at, end_of_day=True),
        _normalize_event(event_name),
    )
    return _json(ids)


@mcp.tool()
async def get_tracking_data(
    website_id: str, start_at: str, end_at: str, session_id: str
) -> str:
    """Get the full activity timeline (user journey) for one session.

    Args:
        website_id: The website id (from get_websites).
        start_at: Range start (UTC).
        end_at: Range end (UTC).
        session_id: The session to inspect (from get_session_ids).
    """
    data = await _get_client().get_user_activity(
        website_id,
        session_id,
        to_unix_millis(start_at),
        to_unix_millis(end_at, end_of_day=True),
    )
    return _json(data)


# -- semantic journey search (optional 'rag' extra) -------------------------


@mcp.tool()
async def get_docs(
    user_question: str,
    website_id: str,
    start_at: str,
    end_at: str,
    selected_event: str | None = None,
) -> str:
    """Semantic search over many user journeys to surface the most relevant moments.

    Pulls every session for the range (optionally filtered to ``selected_event``),
    then returns only the journey chunks most relevant to ``user_question`` -- letting
    you analyze behavior across many users without overflowing the context window.

    Requires the optional 'rag' extra; without it, this returns install instructions.

    Args:
        user_question: What you want to learn (used for the similarity search).
        website_id: The website id (from get_websites).
        start_at: Range start (UTC).
        end_at: Range end (UTC).
        selected_event: Optional event name to filter sessions by.
    """
    if not rag.rag_available():
        return rag.INSTALL_HINT

    client = _get_client()
    start = to_unix_millis(start_at)
    end = to_unix_millis(end_at, end_of_day=True)

    session_ids = await client.get_event_session_ids(
        website_id, start, end, _normalize_event(selected_event)
    )

    journeys: list[str] = []
    for session_id in session_ids:
        activity = await client.get_user_activity(website_id, session_id, start, end)
        if activity:
            journeys.append(_json(activity))

    if not journeys:
        return _json([])

    chunks = rag.semantic_search(journeys, user_question)
    return "\n\n---\n\n".join(chunks)


# -- live-page helpers ------------------------------------------------------


@mcp.tool()
async def get_html(url: str) -> str:
    """Fetch the raw HTML of a live web page (HTTP GET, no JavaScript execution).

    Useful for giving the model the structure/markup of a page you're analyzing.

    Args:
        url: Full URL including scheme, e.g. 'https://example.com/pricing'.
    """
    return await web.fetch_html(url)


@mcp.tool()
async def get_screenshot(url: str):
    """Capture a rendered screenshot of a live web page.

    Requires the optional 'screenshot' extra (Playwright); without it, this returns
    install instructions instead of an image.

    Args:
        url: Full URL including scheme, e.g. 'https://example.com'.
    """
    if not web.screenshot_available():
        return web.INSTALL_HINT
    png = await web.fetch_screenshot(url)
    return Image(data=png, format="jpeg")


# -- prompts ----------------------------------------------------------------


@mcp.prompt(title="Create Dashboard")
def create_dashboard(
    website_name: str,
    start_date: str,
    end_date: str,
    timezone: str = "UTC",
) -> str:
    """Guide the model through building a comprehensive analytics dashboard."""
    return f"""You are an analytics expert building a comprehensive dashboard from Umami \
tracking data for the website "{website_name}", covering {start_date} to {end_date} in \
timezone {timezone}.

First call get_websites and find the id for "{website_name}". Use that id for everything else.

1. OVERVIEW: get_website_stats for pageviews, visitors, visits, bounces, total time.
2. TRENDS: get_pageview_series (unit 'hour' for 1-7 days, 'day' up to ~90 days, 'month' beyond).
3. BREAKDOWNS: get_website_metrics for type path, referrer, browser, os, device, country, and event.
4. REAL-TIME: get_active_visitors for current activity.
5. JOURNEYS: get_session_ids then get_tracking_data for individual sessions; get_docs to \
find patterns across many journeys.
6. VISUAL CONTEXT (optional): get_html / get_screenshot to inspect key pages.

Validate date ranges, account for the timezone, highlight notable trends and anomalies, and \
focus on actionable insights. Gather all the data first, then present a clear, well-organized \
dashboard."""
