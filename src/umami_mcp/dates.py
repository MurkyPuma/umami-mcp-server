"""Date parsing helpers.

Umami's REST API takes time ranges as Unix timestamps in milliseconds. The MCP
tools accept human/LLM-friendly date strings instead, and this module converts
them.

Inputs are interpreted as UTC. The original project used ``datetime.timestamp()``
on a naive datetime, which silently used the host machine's local timezone, so the
same query produced different ranges on different machines (and made tests
non-deterministic). Treating the input as UTC is predictable and reproducible.
"""

from __future__ import annotations

from datetime import datetime, timezone

_DATETIME_FMT = "%Y-%m-%d %H:%M:%S"
_DATE_FMT = "%Y-%m-%d"


def to_unix_millis(date_str: str, *, end_of_day: bool = False) -> int:
    """Convert a date string to a UTC Unix timestamp in milliseconds.

    Accepts ``YYYY-MM-DD`` or ``YYYY-MM-DD HH:MM:SS``.

    Args:
        date_str: The date (and optional time) to convert.
        end_of_day: When the string is a bare date (no time component) and this is
            True, the time is set to 23:59:59.999 so the day is fully included in an
            end-of-range boundary. Ignored when an explicit time is given.

    Returns:
        Milliseconds since the Unix epoch (UTC).

    Raises:
        ValueError: If the string matches neither supported format.
    """
    if not isinstance(date_str, str):
        raise ValueError(f"Expected a date string, got {type(date_str).__name__}")

    text = date_str.strip()

    # Try the full datetime form first; fall back to a bare date.
    try:
        dt = datetime.strptime(text, _DATETIME_FMT)
    except ValueError:
        try:
            dt = datetime.strptime(text, _DATE_FMT)
        except ValueError as exc:
            raise ValueError(
                "Invalid date format. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS "
                f"(got {date_str!r})."
            ) from exc
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59, microsecond=999000)

    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
