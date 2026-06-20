# Umami Analytics MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io) server that gives Claude (or
any MCP client) read access to your [Umami](https://umami.is) web analytics. Ask
questions in natural language and let the model pull stats, breakdowns, pageview trends,
live visitors, and individual user journeys, then build dashboards or surface insights.

This is a modernized, dependency-light rewrite of
[`jakeyShakey/umami_mcp_server`](https://github.com/jakeyShakey/umami_mcp_server). See
[`CHANGELOG.md`](CHANGELOG.md) for what changed and why.

## Highlights

- **Lightweight core.** A default install is just `mcp`, `httpx`, and `python-dotenv`.
  The heavy features (semantic search, screenshots) are opt-in extras.
- **Async + non-blocking.** The Umami client uses `httpx.AsyncClient`, so it never
  stalls the MCP event loop.
- **Two auth modes.** API key (Umami Cloud / newer self-hosted) or username + password.
- **Tested.** A pure-function `pytest` suite plus CI (ruff + pytest).

## Tools

| Tool | What it returns | Requires |
| --- | --- | --- |
| `get_websites` | Your websites and their ids (start here) | core |
| `get_website_stats` | Pageviews, visitors, visits, bounces, total time | core |
| `get_website_metrics` | Breakdown by url, referrer, browser, os, device, country, or event | core |
| `get_pageview_series` | Pageviews/sessions time series (hour/day/month) | core |
| `get_active_visitors` | Current real-time visitor count | core |
| `get_session_ids` | Unique session ids in a range, optionally filtered by event | core |
| `get_tracking_data` | Full activity timeline for one session | core |
| `get_html` | Raw HTML of a live page (HTTP GET, no JS) | core |
| `get_docs` | Semantic search across many user journeys | `[rag]` |
| `get_screenshot` | Rendered screenshot of a live page | `[screenshot]` |

It also ships a **Create Dashboard** prompt that walks the model through assembling a
full dashboard for a website and date range.

Date arguments accept `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS` and are interpreted as **UTC**.

## Install

Requires Python 3.10+.

```bash
# Core server
pip install "git+https://github.com/MurkyPuma/umami-mcp-server.git"

# With semantic journey search (get_docs) — pulls torch-sized wheels
pip install "umami-mcp-server[rag] @ git+https://github.com/MurkyPuma/umami-mcp-server.git"

# With screenshots (get_screenshot) — also run: playwright install chromium
pip install "umami-mcp-server[screenshot] @ git+https://github.com/MurkyPuma/umami-mcp-server.git"

# Everything
pip install "umami-mcp-server[all] @ git+https://github.com/MurkyPuma/umami-mcp-server.git"
```

If you installed the `screenshot` extra, install the browser once:

```bash
playwright install chromium
```

## Configuration

Configure via environment variables (or a local `.env`, see [`.env.example`](.env.example)):

| Variable | Required | Description |
| --- | --- | --- |
| `UMAMI_API_URL` | yes | Your Umami base URL, e.g. `https://cloud.umami.is` |
| `UMAMI_API_KEY` | one of | API key, sent as `x-umami-api-key` (Umami Cloud / newer self-hosted) |
| `UMAMI_USERNAME` / `UMAMI_PASSWORD` | one of | Credentials exchanged for a bearer token |
| `UMAMI_TEAM_ID` | no | If set, `get_websites` lists that team's sites; otherwise yours |
| `UMAMI_TIMEOUT` | no | Per-request timeout in seconds (default 30) |

Provide **either** `UMAMI_API_KEY` **or** both `UMAMI_USERNAME` and `UMAMI_PASSWORD`.

## Connect to Claude Desktop

Add the server to your Claude Desktop config:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "umami": {
      "command": "umami-mcp-server",
      "env": {
        "UMAMI_API_URL": "https://cloud.umami.is",
        "UMAMI_API_KEY": "your-api-key"
      }
    }
  }
}
```

If `umami-mcp-server` isn't on Claude Desktop's `PATH`, use the absolute path to the
console script (e.g. `/path/to/.venv/bin/umami-mcp-server`) or run the module with your
interpreter: set `"command"` to your Python and `"args"` to `["-m", "umami_mcp"]`.

Restart Claude Desktop; the tools appear under the tools (hammer) icon. Enabling the
**Analysis tool** in Claude Desktop's feature settings lets it render dashboards and
charts from the data.

## Usage

- **Guided:** attach the **Create Dashboard** prompt (the MCP attachment menu), give it a
  website name, date range, and timezone, and let the model do the rest.
- **Freeform:** just ask. "How many visitors last week?", "Top referrers for example.com
  in March?", "Walk me through what users who hit checkout did." The model picks the
  tools.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest          # run the test suite
ruff check .    # lint
```

The test suite is dependency-light and needs no live Umami: the async client is tested
with `httpx.MockTransport`, and the RAG tests cover the pure chunking/ranking helpers
(the embedding model itself is not exercised in CI).

## Architecture

```
src/umami_mcp/
  config.py    # env -> Settings (pure, no side effects)
  dates.py     # date string -> UTC unix millis (pure)
  client.py    # async httpx Umami client (auth, retry, endpoints)
  web.py       # get_html via httpx; optional Playwright screenshot
  rag.py       # optional semantic search (sentence-transformers + numpy)
  server.py    # FastMCP tools + Create Dashboard prompt
  __main__.py  # entry point
```

## Credits

Original concept and first implementation by
[jakeyShakey](https://github.com/jakeyShakey/umami_mcp_server). Licensed under
[MIT](LICENSE).
