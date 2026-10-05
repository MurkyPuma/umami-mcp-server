"""FastMCP server exposing Umami analytics (and live-page helpers) as MCP tools.

Rewritten from the original low-level ``mcp.server.Server`` implementation (which
hand-wrote ~350 lines of JSON Schema) to FastMCP, so tool schemas are generated from
type hints and docstrings. The client is built lazily on first tool call, so importing
this module never requires credentials or a network round-trip.
"""

from __future__ import annotations

import json
from datetime import datetime
from datetime import timezone as dt_timezone
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
        "time series, live visitors, and per-session user journeys, plus reports "
        "(funnels, goals, journeys, retention, UTM, attribution), segments and "
        "tracked links, which can be run, saved, edited and deleted. Saved items "
        "change the dashboard everyone sees. Date arguments accept 'YYYY-MM-DD' or "
        "'YYYY-MM-DD HH:MM:SS' and are interpreted as UTC. Call get_websites first "
        "to resolve a website name to its id."
    ),
)

MetricType = Literal[
    "path", "entry", "exit", "title", "query",
    "referrer", "browser", "os", "device", "country", "language", "event",
    "hostname",
    "url",  # deprecated alias for "path"; translated by the client
]
TimeUnit = Literal["hour", "day", "month"]
ReportType = Literal[
    "funnel", "goal", "journey", "retention", "utm", "attribution",
    "breakdown", "performance", "revenue",
]
SegmentType = Literal["segment", "cohort"]

_client: UmamiClient | None = None


def _get_client() -> UmamiClient:
    """Lazily build the Umami client from the environment on first use."""
    global _client
    if _client is None:
        _client = UmamiClient(Settings.from_env())
    return _client


def _json(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


def _filters(
    segment_id: str | None = None, exclude_bounce: bool = False
) -> dict[str, str]:
    """The dashboard's own filter params: a saved segment, and the "Exclude bounce"
    checkbox (drop visits with a single pageview, the 0-second visits)."""
    out: dict[str, str] = {}
    segment_id = _normalize_event(segment_id)
    if segment_id:
        out["segment"] = segment_id
    if exclude_bounce:
        out["excludeBounce"] = "true"
    return out


def _iso(millis: int) -> str:
    return datetime.fromtimestamp(millis / 1000, tz=dt_timezone.utc).isoformat()


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
async def get_website_stats(
    website_id: str,
    start_at: str,
    end_at: str,
    hostname: str | None = None,
    segment_id: str | None = None,
    exclude_bounce: bool = False,
) -> str:
    """Get overview metrics for a website over a date range.

    Returns pageviews, unique visitors, visits, bounces, and total time. If you get
    no data, double-check the date range before assuming there is none.

    Args:
        website_id: The website id (from get_websites).
        start_at: Range start, 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS' (UTC).
        end_at: Range end, same formats (a bare date includes the whole day).
        hostname: Optional: count only this hostname, for a site that tracks
            several (see get_website_metrics with type 'hostname').
        segment_id: Optional saved segment to apply (from list_segments).
        exclude_bounce: Drop visits with a single pageview (0-second visits),
            the dashboard's "Exclude bounce" checkbox.
    """
    data = await _get_client().get_website_stats(
        website_id,
        to_unix_millis(start_at),
        to_unix_millis(end_at, end_of_day=True),
        hostname=_normalize_event(hostname),
        filters=_filters(segment_id, exclude_bounce),
    )
    return _json(data)


@mcp.tool()
async def get_website_metrics(
    website_id: str,
    start_at: str,
    end_at: str,
    type: MetricType,
    hostname: str | None = None,
    segment_id: str | None = None,
    exclude_bounce: bool = False,
) -> str:
    """Get a breakdown of visitors by a dimension over a date range.

    ``type`` selects the dimension: path (pages), entry/exit (landing and exit
    pages), title (page titles), query (query strings), referrer (traffic
    sources), browser, os, device, country, language, event (tally of tracked
    events), or hostname (which of a site's hosts the traffic hit). ``url`` is
    accepted as a deprecated alias for ``path``.

    Args:
        website_id: The website id (from get_websites).
        start_at: Range start (UTC).
        end_at: Range end (UTC).
        type: One of path, entry, exit, title, query, referrer, browser, os,
            device, country, language, event, hostname (or the legacy alias url).
        hostname: Optional: count only this hostname.
        segment_id: Optional saved segment to apply (from list_segments).
        exclude_bounce: Drop visits with a single pageview (0-second visits),
            the dashboard's "Exclude bounce" checkbox.
    """
    data = await _get_client().get_website_metrics(
        website_id,
        to_unix_millis(start_at),
        to_unix_millis(end_at, end_of_day=True),
        type,
        hostname=_normalize_event(hostname),
        filters=_filters(segment_id, exclude_bounce),
    )
    return _json(data)


@mcp.tool()
async def get_event_data(
    website_id: str,
    start_at: str,
    end_at: str,
    event_name: str | None = None,
    property_name: str | None = None,
) -> str:
    """Get the custom data events carried: which properties, and their values.

    With no ``event_name``/``property_name``, lists every (event, property) pair
    that carried data, with counts. With both, returns the values that property
    took on that event and how often (e.g. event 'feature-opened', property
    'feature'), which a plain event tally cannot show.

    Args:
        website_id: The website id (from get_websites).
        start_at: Range start (UTC).
        end_at: Range end (UTC).
        event_name: Optional event to break down; requires property_name.
        property_name: Optional property of that event to break down.
    """
    client = _get_client()
    start, end = to_unix_millis(start_at), to_unix_millis(end_at, end_of_day=True)
    event_name, property_name = _normalize_event(event_name), _normalize_event(property_name)
    if event_name and property_name:
        data = await client.get_event_data_values(website_id, start, end, event_name, property_name)
    elif event_name or property_name:
        return "Pass both event_name and property_name, or neither to list them."
    else:
        data = await client.get_event_data_properties(website_id, start, end)
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


# -- reports, segments and links --------------------------------------------


@mcp.tool()
async def run_report(
    website_id: str,
    type: ReportType,
    start_at: str,
    end_at: str,
    parameters: dict[str, Any] | None = None,
    hostname: str | None = None,
    segment_id: str | None = None,
    exclude_bounce: bool = False,
) -> str:
    """Compute a report over a date range without saving it.

    ``parameters`` holds the type's own fields (the dates come from start_at and
    end_at):

    * funnel: ``{"window": 60, "steps": [{"type": "event", "value": "signup-started"},
      ...]}``. 2 to 8 steps; ``type`` is "path" or "event"; a value may start or
      end with ``*`` to match a prefix or suffix (``cta-register-*``); window is
      the minutes allowed between steps.
    * goal: ``{"type": "event", "value": "signup-completed"}`` (or type "path").
    * journey: ``{"steps": 4, "startStep": "/register"}`` (2 to 7 steps).
    * retention: ``{"timezone": "America/Vancouver"}``.
    * utm: ``{}``. breakdown: ``{"fields": ["path", "referrer"]}``.
    * attribution: ``{"model": "first-click", "type": "event", "step": "signup-completed"}``.

    Args:
        website_id: The website id (from get_websites).
        type: Report type.
        start_at: Range start (UTC).
        end_at: Range end (UTC).
        parameters: The type's fields, as above.
        hostname: Optional: count only this hostname.
        segment_id: Optional saved segment to apply.
        exclude_bounce: Drop single-pageview (0-second) visits.
    """
    params = dict(parameters or {})
    params["startDate"] = _iso(to_unix_millis(start_at))
    params["endDate"] = _iso(to_unix_millis(end_at, end_of_day=True))
    filters = _filters(segment_id, exclude_bounce)
    hostname = _normalize_event(hostname)
    if hostname:
        filters["hostname"] = hostname
    return _json(await _get_client().run_report(website_id, type, params, filters))


@mcp.tool()
async def list_reports(website_id: str, type: ReportType | None = None) -> str:
    """List a website's saved reports (its funnels, goals, journeys...).

    Args:
        website_id: The website id (from get_websites).
        type: Optional: only this report type.
    """
    return _json(await _get_client().list_reports(website_id, type))


@mcp.tool()
async def save_report(
    website_id: str,
    type: ReportType,
    name: str,
    parameters: dict[str, Any],
    description: str | None = None,
    report_id: str | None = None,
) -> str:
    """Save a report to the website's dashboard, or overwrite one by ``report_id``.

    ``parameters`` are the type's fields as documented on run_report, without
    dates (the dashboard applies its own range). Check the steps return data
    with run_report first.

    Args:
        website_id: The website id (from get_websites).
        type: Report type.
        name: Name shown on the dashboard.
        parameters: The type's fields.
        description: Optional: the question the report answers.
        report_id: Optional: an existing report to overwrite (from list_reports).
    """
    data = await _get_client().save_report(
        website_id, type, name, parameters, description, _normalize_event(report_id)
    )
    return _json(data)


@mcp.tool()
async def delete_report(report_id: str) -> str:
    """Delete a saved report. Irreversible.

    Args:
        report_id: The report to delete (from list_reports).
    """
    return _json(await _get_client().delete_report(report_id))


@mcp.tool()
async def list_segments(website_id: str, type: SegmentType = "segment") -> str:
    """List a website's saved segments (or cohorts), with their ids and filters.

    Args:
        website_id: The website id (from get_websites).
        type: "segment" (a saved filter) or "cohort".
    """
    return _json(await _get_client().list_segments(website_id, type))


@mcp.tool()
async def save_segment(
    website_id: str,
    name: str,
    filters: list[dict[str, str]],
    match: Literal["all", "any"] = "all",
    type: SegmentType = "segment",
    segment_id: str | None = None,
) -> str:
    """Save a segment (a named filter selectable on every dashboard view), or
    overwrite one by ``segment_id``.

    Each filter is ``{"name": <field>, "operator": <op>, "value": <string>}``.
    Fields: path, referrer, title, query, os, browser, device, country, region,
    city, hostname, language, event, tag, utmSource, utmMedium, utmCampaign,
    utmContent, utmTerm. Operators: eq, neq, c (contains), dnc (does not
    contain), s (starts with), ns, re, nre.

    Args:
        website_id: The website id (from get_websites).
        name: Name shown in the segment picker.
        filters: The filter rows.
        match: "all" to AND the rows, "any" to OR them.
        type: "segment" or "cohort".
        segment_id: Optional: an existing segment to overwrite.
    """
    data = await _get_client().save_segment(
        website_id,
        name,
        {"filters": filters, "match": match},
        type,
        _normalize_event(segment_id),
    )
    return _json(data)


@mcp.tool()
async def delete_segment(website_id: str, segment_id: str) -> str:
    """Delete a saved segment. Irreversible.

    Args:
        website_id: The website id (from get_websites).
        segment_id: The segment to delete (from list_segments).
    """
    return _json(await _get_client().delete_segment(website_id, segment_id))


@mcp.tool()
async def list_links() -> str:
    """List tracked short links (Umami Links), with their slugs and destinations."""
    return _json(await _get_client().list_links())


@mcp.tool()
async def save_link(name: str, url: str, slug: str, link_id: str | None = None) -> str:
    """Create a tracked short link that counts clicks then redirects to ``url``,
    or overwrite one by ``link_id``.

    Args:
        name: Name shown in the Links list.
        url: Destination URL (keep any utm_* tags on it).
        slug: The short path segment.
        link_id: Optional: an existing link to overwrite (from list_links).
    """
    return _json(await _get_client().save_link(name, url, slug, _normalize_event(link_id)))


@mcp.tool()
async def delete_link(link_id: str) -> str:
    """Delete a tracked short link. Irreversible: the short URL stops resolving.

    Args:
        link_id: The link to delete (from list_links).
    """
    return _json(await _get_client().delete_link(link_id))


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
