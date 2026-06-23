"""Tests for the async Umami client, using httpx.MockTransport (no network)."""

import httpx

from umami_mcp.client import UmamiClient
from umami_mcp.config import Settings


def make_client(handler, **settings_kwargs) -> UmamiClient:
    settings_kwargs.setdefault("api_url", "https://umami.test")
    settings = Settings(**settings_kwargs)
    return UmamiClient(settings, transport=httpx.MockTransport(handler))


async def test_api_key_sets_header_and_skips_login():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["api_key"] = request.headers.get("x-umami-api-key")
        seen["path"] = request.url.path
        return httpx.Response(200, json={"data": []})

    client = make_client(handler, api_key="secret", team_id="team-1")
    await client.get_websites()

    assert seen["api_key"] == "secret"
    # With a team configured, the team-scoped endpoint is used.
    assert seen["path"] == "/api/teams/team-1/websites"


async def test_personal_websites_when_no_team():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={"data": []})

    client = make_client(handler, api_key="secret")
    await client.get_websites()
    assert seen["path"] == "/api/websites"


async def test_username_password_login_sets_bearer():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"token": "tok-123"})
        assert request.headers.get("Authorization") == "Bearer tok-123"
        return httpx.Response(200, json={"data": []})

    client = make_client(handler, username="u", password="p", team_id="t")
    await client.get_websites()

    assert calls[0] == "/api/auth/login"
    assert calls[1] == "/api/teams/t/websites"


async def test_reauthenticates_once_on_401():
    state = {"logins": 0, "stats_seen": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            state["logins"] += 1
            return httpx.Response(200, json={"token": f"tok-{state['logins']}"})
        # First stats hit returns 401 (expired token); second succeeds.
        state["stats_seen"] += 1
        if state["stats_seen"] == 1:
            return httpx.Response(401, json={})
        return httpx.Response(200, json={"pageviews": {"value": 7}})

    client = make_client(handler, username="u", password="p")
    data = await client.get_website_stats("w1", 0, 1)

    assert data == {"pageviews": {"value": 7}}
    assert state["logins"] == 2  # initial login + one re-auth


async def test_session_id_pagination_dedupes_and_stops():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"token": "t"})
        page = int(request.url.params["page"])
        if page == 1:
            return httpx.Response(
                200,
                json={
                    "data": [{"sessionId": "a"}, {"sessionId": "b"}, {"sessionId": "a"}],
                    "count": 400,
                    "page": 1,
                },
            )
        return httpx.Response(
            200,
            json={"data": [{"sessionId": "b"}, {"sessionId": "c"}], "count": 400, "page": 2},
        )

    client = make_client(handler, username="u", password="p")
    ids = await client.get_event_session_ids("w1", 0, 1, "checkout")

    assert ids == ["a", "b", "c"]  # deduped and sorted


async def test_session_ids_handle_empty_payload():
    # Regression: the original crashed with a TypeError when a page came back null.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"token": "t"})
        # A JSON `null` body decodes to None; the loop must break, not crash.
        return httpx.Response(200, content=b"null", headers={"Content-Type": "application/json"})

    client = make_client(handler, username="u", password="p")
    assert await client.get_event_session_ids("w1", 0, 1, None) == []


async def test_none_event_query_param_is_dropped():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"token": "t"})
        seen["has_query"] = "query" in request.url.params
        return httpx.Response(200, json={"data": [], "count": 0, "page": 1})

    client = make_client(handler, username="u", password="p")
    await client.get_event_session_ids("w1", 0, 1, None)
    # A None event filter must not become the literal string "None" in the query.
    assert seen["has_query"] is False


async def test_metrics_translates_legacy_url_type_to_path():
    # Current Umami renamed the page metric "url" -> "path"; the legacy name must
    # be translated transparently so it stops 400ing.
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["type"] = request.url.params.get("type")
        return httpx.Response(200, json=[{"x": "/best-card", "y": 9}])

    client = make_client(handler, api_key="k")
    data = await client.get_website_metrics("w1", 0, 1, "url")

    assert seen["type"] == "path"
    assert data == [{"x": "/best-card", "y": 9}]


async def test_metrics_passes_through_non_aliased_types():
    # A type that is already the Umami name must be sent unchanged.
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["type"] = request.url.params.get("type")
        return httpx.Response(200, json=[])

    client = make_client(handler, api_key="k")
    for t in ("path", "entry", "exit", "referrer", "event"):
        await client.get_website_metrics("w1", 0, 1, t)
        assert seen["type"] == t


async def test_http_error_is_wrapped():
    from umami_mcp.client import UmamiError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = make_client(handler, api_key="k")
    try:
        await client.get_website_stats("w1", 0, 1)
    except UmamiError as exc:
        assert "500" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected UmamiError")
