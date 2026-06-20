"""Live-page helpers: HTML fetch and (optional) screenshots.

These power ``get_html`` and ``get_screenshot``. They fetch the *live website* being
analyzed (not Umami) so the model can reason about the page it is looking at.

The original implementation used crawl4ai, which bundles a full headless-browser +
markdown/LLM-extraction stack and required a ``crawl4ai-setup`` subprocess on every
startup. That is overkill:

* HTML only needs a plain HTTP GET (``httpx``), with no browser at all. The tradeoff
  is no JavaScript execution, which is fine for inspecting page structure/markup.
* A screenshot genuinely needs a renderer, so it stays behind the optional
  ``screenshot`` extra (Playwright + Pillow) and degrades gracefully when absent.
"""

from __future__ import annotations

import importlib.util

import httpx

_USER_AGENT = "umami-mcp-server/0.2 (+https://github.com/MurkyPuma/umami-mcp-server)"

INSTALL_HINT = (
    "Screenshots need the optional 'screenshot' extra. Install it with:\n"
    "    pip install 'umami-mcp-server[screenshot]'\n"
    "    playwright install chromium"
)


class ScreenshotUnavailable(RuntimeError):
    """Raised when a screenshot is requested but the optional deps are missing."""


def screenshot_available() -> bool:
    """True if both Playwright and Pillow can be imported (without importing them)."""
    return (
        importlib.util.find_spec("playwright") is not None
        and importlib.util.find_spec("PIL") is not None
    )


async def fetch_html(
    url: str,
    timeout: float = 30.0,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """Fetch raw HTML for ``url`` over HTTP (no browser, no JS execution).

    ``transport`` is an injection point for tests; production calls leave it None.
    """
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": _USER_AGENT},
        transport=transport,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


async def fetch_screenshot(url: str, timeout: float = 30.0, max_bytes: int = 100_000) -> bytes:
    """Render ``url`` in headless Chromium and return optimized JPEG bytes.

    Raises:
        ScreenshotUnavailable: If the optional screenshot dependencies are not
            installed.
    """
    if not screenshot_available():
        raise ScreenshotUnavailable(INSTALL_HINT)

    # Imported lazily so the core install never needs these.
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            await page.goto(url, timeout=timeout * 1000, wait_until="networkidle")
            png_bytes = await page.screenshot(full_page=False)
        finally:
            await browser.close()

    return _optimize(png_bytes, max_bytes=max_bytes)


def _optimize(png_bytes: bytes, *, max_bytes: int) -> bytes:
    """Downscale/recompress a PNG to a JPEG under ``max_bytes`` to save context tokens."""
    from io import BytesIO

    from PIL import Image

    image = Image.open(BytesIO(png_bytes))
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGB")

    max_dimension = 1920
    if max(image.size) > max_dimension:
        ratio = max_dimension / max(image.size)
        image = image.resize(
            (int(image.width * ratio), int(image.height * ratio)),
            Image.Resampling.LANCZOS,
        )

    quality = 85
    while quality >= 20:
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
        data = buffer.getvalue()
        if len(data) <= max_bytes or quality == 20:
            return data
        quality -= 10
    return data  # unreachable, but keeps type checkers happy
