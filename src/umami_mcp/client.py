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

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET ``path``, transparently re-logging in once on a 401 (expired token)."""
        await self._ensure_authenticated()
        response = await self._client.get(path, params=_clean_params(params))

        if response.status_code == httpx.codes.UNAUTHORIZED and not self._settings.uses_api_key:
            logger.debug("Got 401; re-authenticating once and retrying.")
            self._authenticated = False
            await self._login()
            response = await self._client.get(path, params=_clean_params(params))

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise UmamiError(
                f"Umami API error {response.status_code} for {path}: {response.text}"
            ) from exc
        return response.json()

    # -- endpoints ----------------------------------------------------------

    async def get_websites(self, team_id: str | None = None, page_size: int = 150) -> Any:
        team_id = team_id or self._settings.team_id
        if team_id:
            path = f"/api/teams/{team_id}/websites"
        else:
            # Personal websites when no team is configured.
            path = "/api/websites"
        return await self._get(path, {"pageSize": page_size})

    async def get_website_stats(self, website_id: str, start_at: int, end_at: int) -> Any:
        return await self._get(
            f"/api/websites/{website_id}/stats",
            {"startAt": start_at, "endAt": end_at},
        )

    async def get_website_metrics(
        self, website_id: str, start_at: int, end_at: int, type: str
    ) -> Any:
        return await self._get(
            f"/api/websites/{website_id}/metrics",
            {"startAt": start_at, "endAt": end_at, "type": type},
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

    async def _get_events(
        self,
        website_id: str,
        start_at: int,
        end_at: int,
        query: str | None,
        page: int,
        page_size: int = _SESSION_PAGE_SIZE,
    ) -> Any:
        return await self._get(
            f"/api/websites/{website_id}/events",
            {
                "startAt": start_at,
                "endAt": end_at,
                "unit": "day",
                "timezone": "UTC",
                "query": query,
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
