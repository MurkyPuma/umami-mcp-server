<div align="center">

# Umami Analytics MCP Server

**Talk to your [Umami](https://umami.is) web analytics in plain English.**
Let Claude pull your stats, spot trends, trace user journeys, and build dashboards, no SQL, no clicking through charts.

[![CI](https://github.com/MurkyPuma/umami-mcp-server/actions/workflows/ci.yml/badge.svg)](https://github.com/MurkyPuma/umami-mcp-server/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
![MCP](https://img.shields.io/badge/MCP-compatible-1f6feb.svg)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/MurkyPuma/umami-mcp-server/pulls)

</div>

This is a [Model Context Protocol](https://modelcontextprotocol.io) server that connects
Umami to any MCP client (Claude Desktop, Cursor, and others). Ask a question, and the
model picks the right analytics calls, reads the data, and answers, then you can keep
going: drill in, compare ranges, or have it assemble a full dashboard.

It is a modernized, dependency-light rewrite of
[`jakeyShakey/umami_mcp_server`](https://github.com/jakeyShakey/umami_mcp_server):
FastMCP, an async HTTP client, a tiny core install, optional heavy features, and a test
suite. See [`CHANGELOG.md`](CHANGELOG.md) for the full diff in spirit.

## See it in action

```text
You:    Which pages drove the most traffic last week, and where did those visitors come from?

Claude: (get_websites → get_website_metrics type=url → get_website_metrics type=referrer)
        Your top pages last week were /pricing, /blog/getting-started, and /. Most of
        that traffic came from Google, then a Hacker News thread, then direct visits.
        Want me to break the /pricing visitors down by country or device?

You:    Yeah, and show me what a typical /pricing visitor did before they left.

Claude: (get_website_metrics type=country → get_session_ids → get_tracking_data)
        ...
```

The model drives the tools. You just ask.

## Why you might want this

- **Plain-language analytics.** No dashboards to navigate or queries to write.
- **Lightweight by default.** The core install is just `mcp`, `httpx`, and `python-dotenv`. No torch, no headless browser unless you opt in.
- **Async and non-blocking.** The Umami client is built on `httpx.AsyncClient`.
- **Works with self-hosted or Umami Cloud.** API-key or username/password auth.
- **Honest about quality.** Pure-function test suite plus CI (ruff + pytest) on Python 3.10 to 3.13.

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

There is also a **Create Dashboard** prompt that walks the model through building a full
dashboard for a website and date range. Date arguments accept `YYYY-MM-DD` or
`YYYY-MM-DD HH:MM:SS` and are interpreted as UTC.

## Quick start

Requires Python 3.10+.

**1. Install**

```bash
pip install "git+https://github.com/MurkyPuma/umami-mcp-server.git"
```

**2. Add it to Claude Desktop**

Edit your config file:
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

**3. Restart Claude Desktop** and ask it something like *"List my websites and last week's
visitors."* The tools appear under the tools (hammer) icon.

> If `umami-mcp-server` is not on Claude Desktop's `PATH`, use the absolute path to the
> console script (for example `/path/to/.venv/bin/umami-mcp-server`), or set `"command"`
> to your Python interpreter with `"args": ["-m", "umami_mcp"]`.

## Optional features (extras)

The heavy, situational tools are opt-in so the default install stays small.

```bash
# Semantic journey search (get_docs). Pulls torch-sized wheels.
pip install "umami-mcp-server[rag] @ git+https://github.com/MurkyPuma/umami-mcp-server.git"

# Rendered screenshots (get_screenshot). Then install the browser once.
pip install "umami-mcp-server[screenshot] @ git+https://github.com/MurkyPuma/umami-mcp-server.git"
playwright install chromium

# Everything
pip install "umami-mcp-server[all] @ git+https://github.com/MurkyPuma/umami-mcp-server.git"
```

Without an extra, its tool still appears but returns a one-line install hint instead of
failing, so nothing breaks.

## Configuration

Set these as environment variables (in the MCP client config) or in a local `.env`
(see [`.env.example`](.env.example)).

| Variable | Required | Description |
| --- | --- | --- |
| `UMAMI_API_URL` | yes | Your Umami base URL, for example `https://cloud.umami.is` |
| `UMAMI_API_KEY` | one of | API key, sent as `x-umami-api-key` (Umami Cloud / newer self-hosted) |
| `UMAMI_USERNAME` / `UMAMI_PASSWORD` | one of | Credentials exchanged for a bearer token |
| `UMAMI_TEAM_ID` | no | If set, `get_websites` lists that team's sites; otherwise yours |
| `UMAMI_TIMEOUT` | no | Per-request timeout in seconds (default 30) |

Provide **either** `UMAMI_API_KEY`, **or** both `UMAMI_USERNAME` and `UMAMI_PASSWORD`.

## Development

```bash
git clone https://github.com/MurkyPuma/umami-mcp-server.git
cd umami-mcp-server
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest          # run the tests
ruff check .    # lint
```

No live Umami is needed to test: the async client is exercised with
`httpx.MockTransport`, and the RAG tests cover the pure chunking/ranking helpers (the
embedding model is not loaded in CI).

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

## Contributing

Issues and PRs are welcome. The codebase is small and the tests are fast; a good first
contribution is adding a tool for an Umami endpoint that is not covered yet.

If this saves you a trip to the Umami dashboard, a ⭐ helps other people find it.

## Credits

Original concept and first implementation by
[jakeyShakey](https://github.com/jakeyShakey/umami_mcp_server). Licensed under
[MIT](LICENSE).
