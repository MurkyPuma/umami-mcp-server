"""Tests for date -> Unix-millis conversion (UTC, deterministic)."""

import pytest

from umami_mcp.dates import to_unix_millis


def test_bare_date_is_utc_midnight():
    # 2024-03-01T00:00:00Z == 1709251200 seconds.
    assert to_unix_millis("2024-03-01") == 1709251200 * 1000


def test_end_of_day_pushes_to_last_millisecond():
    start = to_unix_millis("2024-03-01")
    end = to_unix_millis("2024-03-01", end_of_day=True)
    # End is the same day, just before the next midnight.
    assert end > start
    assert end == start + (24 * 60 * 60 * 1000) - 1


def test_explicit_time_ignores_end_of_day_flag():
    # When a time is given, end_of_day must not override it.
    with_time = to_unix_millis("2024-03-01 12:30:00", end_of_day=True)
    assert with_time == to_unix_millis("2024-03-01 12:30:00")
    assert with_time == (1709251200 + 12 * 3600 + 30 * 60) * 1000


def test_is_independent_of_host_timezone():
    # The whole point of the rewrite: same input -> same output regardless of TZ.
    # Two well-known instants, computed purely from the UTC interpretation.
    assert to_unix_millis("1970-01-01") == 0
    assert to_unix_millis("1970-01-01 00:00:01") == 1000


def test_invalid_format_raises():
    with pytest.raises(ValueError):
        to_unix_millis("01/03/2024")
    with pytest.raises(ValueError):
        to_unix_millis("not-a-date")
