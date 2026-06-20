# Changelog

## 0.2.0 (Modernized rewrite)

A ground-up modernization of the original
[`jakeyShakey/umami_mcp_server`](https://github.com/jakeyShakey/umami_mcp_server)
(Feb 2025). Same idea, rebuilt to be lighter, safer, and tested.

### Changed
- **Migrated to FastMCP.** Replaced the low-level `mcp.server.Server` implementation
  (~350 lines of hand-written JSON Schema) with the modern `FastMCP` API. Tool schemas
  are now generated from type hints and docstrings.
- **Async Umami client.** Rewrote the synchronous `requests` client as an
  `httpx.AsyncClient` so it no longer blocks the MCP event loop. The `httpx` dependency
  was already declared but unused.
- **No import-time side effects.** Config is now resolved lazily; importing the package
  no longer requires credentials or a successful Umami login (the original raised at
  import time and logged in during module import).
- **Dates are interpreted as UTC.** The original used a naive `datetime.timestamp()`,
  which silently used the host's local timezone, so the same query produced different
  ranges on different machines. Conversions are now UTC and deterministic.
- **Lighter, optional dependencies.** The core install is now just `mcp`, `httpx`, and
  `python-dotenv`. Heavy features moved behind extras:
  - `pip install umami-mcp-server[rag]` for semantic journey search (`get_docs`).
  - `pip install umami-mcp-server[screenshot]` for rendered screenshots (`get_screenshot`).

### Removed
- **Dropped crawl4ai.** `get_html` is now a direct `httpx` GET (no headless browser, no
  `crawl4ai-setup` subprocess on startup). `get_screenshot` uses Playwright behind the
  optional `screenshot` extra.
- **Dropped the langchain + faiss + scikit-learn stack** for RAG in favor of
  `sentence-transformers` + a few lines of NumPy. Same capability, far fewer
  dependencies, no deprecated `get_relevant_documents` calls.
- **Removed unused dependencies** `langchain-openai` and `openai` (declared but never
  imported).

### Fixed
- **RAG result contamination.** The original kept a module-level FAISS index and *added*
  to it on every call without clearing it, so repeated `get_docs` calls leaked chunks
  from earlier, unrelated queries. Each call is now self-contained.
- **Session-ID pagination crash.** The pagination loop ran on `while True` and raised a
  `TypeError` if a page came back empty/`None`. It now guards empty payloads and caps the
  page count.
- **`None` query params** are dropped instead of being sent as the literal string
  `"None"`.

### Added
- A `pytest` suite (dates, config, async client with `httpx.MockTransport`, server
  registration + graceful degradation, RAG helpers) and a GitHub Actions CI workflow
  (ruff + pytest).
- API-key authentication (`UMAMI_API_KEY`, sent as `x-umami-api-key`) alongside the
  existing username/password flow, with a transparent single re-login on token expiry.
