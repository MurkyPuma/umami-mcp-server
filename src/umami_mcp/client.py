"""Async Umami API client.

Rewritten from the original synchronous ``requests`` implementation to use
``httpx.AsyncClient`` so it never blocks the MCP event loop. Authentication is
handled lazily (on first request) and a single transparent re-login is attempted if
a bearer token has expired.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import Settings

logger = logging.getLogger("umami_mcp.client")

# Umami session-events pagination is capped server-side; guard against runaway loops.
_MAX_SESSION_PAGES = 50
_SESSION_PAGE_SIZE = 200

# Current Umami renamed the page-path breakdown metric from "url" to "path"
# (older docs and clients still say "url", which now 400s). Accept the legacy
# name and translate it so existing callers and prompts keep working.
_METRIC_TYPE_ALIASES = {"url": "path"}


class UmamiError(RuntimeError):
    """Raised when the Umami API returns an error or unexpected payload."""


class UmamiClient:
    """A thin async wrapper over the Umami REST API."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        headers = {"Accept": "application/json"}
        if settings.api_key:
            headers["x-umami-api-key"] = settings.api_key
        self._client = httpx.AsyncClient(
            base_url=settings.api_url,
            timeout=settings.timeout,
            headers=headers,
            transport=transport,
            follow_redirects=True,
        )
        # API-key auth needs no login round-trip; user/pass does.
        self._authenticated = settings.uses_api_key

    async def __aenter__(self) -> UmamiClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- authentication -----------------------------------------------------

    async def _login(self) -> None:
        """Exchange username/password for a bearer token. No-op for API-key auth."""
        if self._settings.uses_api_key:
            self._authenticated = True
            return

        try:
            response = await self._client.post(
                "/api/auth/login",
                json={
                    "username": self._settings.username,
                    "password": self._settings.password,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise UmamiError(f"Umami login failed: {exc}") from exc

        token = response.json().get("token")
        if not token:
            raise UmamiError("Umami login succeeded but no token was returned.")

        self._client.headers["Authorization"] = f"Bearer {token}"
        self._authenticated = True
        logger.debug("Authenticated with Umami via username/password.")

    async def _ensure_authenticated(self) -> None:
        if not self._authenticated:
            await self._login()

    async def verify_token(self) -> bool:
        """Best-effort check that the current credentials are accepted."""
        try:
            await self._ensure_authenticated()
            response = await self._client.post("/api/auth/verify")
            return response.status_code == httpx.codes.OK
        except (httpx.HTTPError, UmamiError):
            return False

    # -- request plumbing ---------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: Any = None,
    ) -> Any:
        """Send one request, transparently re-logging in once on a 401 (expired token)."""
        await self._ensure_authenticated()

        def send() -> Any:
            return self._client.request(method, path, params=_clean_params(params), json=body)

        response = await send()

        if response.status_code == httpx.codes.UNAUTHORIZED and not self._settings.uses_api_key:
            logger.debug("Got 401; re-authenticating once and retrying.")
            self._authenticated = False
            await self._login()
            response = await send()

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise UmamiError(
                f"Umami API error {response.status_code} for {method} {path}: {response.text}"
            ) from exc
        # DELETE answers with an empty 200 ("ok").
        return response.json() if response.content else {"ok": True}

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params)

    # -- endpoints ----------------------------------------------------------

    async def get_websites(self, team_id: str | None = None, page_size: int = 150) -> Any:
        team_id = team_id or self._settings.team_id
        if team_id:
            path = f"/api/teams/{team_id}/websites"
        else:
            # Personal websites when no team is configured.
            path = "/api/websites"
        return await self._get(path, {"pageSize": page_size})

    async def get_website_stats(
        self,
        website_id: str,
        start_at: int,
        end_at: int,
        hostname: str | None = None,
        filters: dict[str, str] | None = None,
    ) -> Any:
        return await self._get(
            f"/api/websites/{website_id}/stats",
            {"startAt": start_at, "endAt": end_at, "hostname": hostname, **(filters or {})},
        )

    async def get_website_metrics(
        self,
        website_id: str,
        start_at: int,
        end_at: int,
        type: str,
        hostname: str | None = None,
        filters: dict[str, str] | None = None,
    ) -> Any:
        metric_type = _METRIC_TYPE_ALIASES.get(type, type)
        return await self._get(
            f"/api/websites/{website_id}/metrics",
            {
                "startAt": start_at,
                "endAt": end_at,
                "type": metric_type,
                "hostname": hostname,
                **(filters or {}),
            },
        )

    async def get_event_data_properties(
        self, website_id: str, start_at: int, end_at: int
    ) -> Any:
        """Every (event, property) pair that carried custom data, with counts."""
        return await self._get(
            f"/api/websites/{website_id}/event-data/properties",
            {"startAt": start_at, "endAt": end_at},
        )

    async def get_event_data_values(
        self, website_id: str, start_at: int, end_at: int, event_name: str, property_name: str
    ) -> Any:
        """The values one event's property took, with counts."""
        return await self._get(
            f"/api/websites/{website_id}/event-data/values",
            {
                "startAt": start_at,
                "endAt": end_at,
                "event": event_name,
                "propertyName": property_name,
            },
        )

    async def get_pageview_series(
        self, website_id: str, start_at: int, end_at: int, unit: str, timezone: str
    ) -> Any:
        return await self._get(
            f"/api/websites/{website_id}/pageviews",
            {"startAt": start_at, "endAt": end_at, "unit": unit, "timezone": timezone},
        )

    async def get_active_visitors(self, website_id: str) -> Any:
        return await self._get(f"/api/websites/{website_id}/active")

    async def get_user_activity(
        self, website_id: str, session_id: str, start_at: int, end_at: int
    ) -> Any:
        return await self._get(
            f"/api/websites/{website_id}/sessions/{session_id}/activity",
            {"startAt": start_at, "endAt": end_at},
        )

    # -- reports, segments, links (read and write) ---------------------------

    async def run_report(
        self,
        website_id: str,
        type: str,
        parameters: dict[str, Any],
        filters: dict[str, str] | None = None,
    ) -> Any:
        """Compute a report (funnel, goal, journey, ...) without saving it.

        ``parameters`` must carry ``startDate``/``endDate`` (ISO strings) plus the
        type's own fields; Umami validates them against the type's schema.
        """
        return await self._request(
            "POST",
            f"/api/reports/{type}",
            body={
                "websiteId": website_id,
                "type": type,
                "filters": filters or {},
                "parameters": parameters,
            },
        )

    async def list_reports(self, website_id: str, type: str | None = None) -> Any:
        return await self._get(
            "/api/reports", {"websiteId": website_id, "type": type, "pageSize": 200}
        )

    async def save_report(
        self,
        website_id: str,
        type: str,
        name: str,
        parameters: dict[str, Any],
        description: str | None = None,
        report_id: str | None = None,
    ) -> Any:
        """Create a saved report, or overwrite ``report_id`` when given."""
        path = f"/api/reports/{report_id}" if report_id else "/api/reports"
        return await self._request(
            "POST",
            path,
            body={
                "websiteId": website_id,
                "type": type,
                "name": name,
                "description": description or "",
                "parameters": parameters,
            },
        )

    async def delete_report(self, report_id: str) -> Any:
        return await self._request("DELETE", f"/api/reports/{report_id}")

    async def list_segments(self, website_id: str, type: str = "segment") -> Any:
        return await self._get(f"/api/websites/{website_id}/segments", {"type": type})

    async def save_segment(
        self,
        website_id: str,
        name: str,
        parameters: dict[str, Any],
        type: str = "segment",
        segment_id: str | None = None,
    ) -> Any:
        """Create a segment (or cohort), or overwrite ``segment_id`` when given."""
        path = f"/api/websites/{website_id}/segments"
        if segment_id:
            path += f"/{segment_id}"
        return await self._request(
            "POST", path, body={"type": type, "name": name, "parameters": parameters}
        )

    async def delete_segment(self, website_id: str, segment_id: str) -> Any:
        return await self._request(
            "DELETE", f"/api/websites/{website_id}/segments/{segment_id}"
        )

    async def list_links(self) -> Any:
        return await self._get("/api/links", {"pageSize": 200})

    async def save_link(
        self, name: str, url: str, slug: str, link_id: str | None = None
    ) -> Any:
        """Create a tracked short link, or overwrite ``link_id`` when given."""
        path = f"/api/links/{link_id}" if link_id else "/api/links"
        body: dict[str, Any] = {"name": name, "url": url, "slug": slug}
        if self._settings.team_id and not link_id:
            body["teamId"] = self._settings.team_id
        return await self._request("POST", path, body=body)

    async def delete_link(self, link_id: str) -> Any:
        return await self._request("DELETE", f"/api/links/{link_id}")

    async def _get_events(
        self,
        website_id: str,
        start_at: int,
        end_at: int,
        event_name: str | None,
        page: int,
        page_size: int = _SESSION_PAGE_SIZE,
    ) -> Any:
        # Current Umami filters this endpoint by exact event name via the `event`
        # param (mapped to event_name). The `query` param the original sent is now
        # the url_query filter, which silently matched the wrong events.
        return await self._get(
            f"/api/websites/{website_id}/events",
            {
                "startAt": start_at,
                "endAt": end_at,
                "unit": "day",
                "timezone": "UTC",
                "event": event_name,
                "page": page,
                "pageSize": page_size,
            },
        )

    async def get_event_session_ids(
        self,
        website_id: str,
        start_at: int,
        end_at: int,
        event_name: str | None = None,
    ) -> list[str]:
        """Return the unique session IDs that fired ``event_name`` in the range.

        Pass ``event_name=None`` for all sessions. Pages through the events endpoint
        with a hard page cap so a malformed response can't spin forever (the original
        looped on ``while True`` and crashed with a ``TypeError`` if a page came back
        ``None``).
        """
        session_ids: set[str] = set()
        page = 1
        while page <= _MAX_SESSION_PAGES:
            payload = await self._get_events(
                website_id, start_at, end_at, event_name, page
            )
            if not payload:
                break

            for event in payload.get("data", []):
                # Older Umami versions ignore the `event` filter on this endpoint;
                # re-check locally so they don't silently return every session.
                if event_name is not None and event.get("eventName") != event_name:
                    continue
                session_id = event.get("sessionId")
                if session_id:
                    session_ids.add(session_id)

            count = payload.get("count", 0)
            if _SESSION_PAGE_SIZE * payload.get("page", page) >= count:
                break
            page += 1

        return sorted(session_ids)


def _clean_params(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop ``None`` values so they don't become the literal string 'None' in a query."""
    if not params:
        return params
    return {k: v for k, v in params.items() if v is not None}
