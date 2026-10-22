"""Tests for device datetime parsing and POSIX time zones."""

from datetime import datetime, timezone

import pytest

from custom_components.omlet_coop.clock import (
    device_local_datetime,
    format_device_datetime,
    parse_device_datetime,
)

DEVICE_TZ = "EST5EDT,M3.2.0,M11.1.0"


def test_device_datetime_format_and_parse():
    """Device timestamps use English weekday/month abbreviations."""
    parsed = parse_device_datetime("Thu Oct 22 07:21:12 2026")

    assert parsed == datetime(2026, 10, 22, 7, 21, 12)
    assert format_device_datetime(parsed) == "Thu Oct 22 07:21:12 2026"


@pytest.mark.parametrize(
    "value",
    ["", "Thu Oct 22 07:21 2026", "Thu Not 22 07:21:12 2026"],
)
def test_parse_rejects_malformed_datetime(value):
    """Malformed timestamp text is rejected."""
    with pytest.raises(ValueError):
        parse_device_datetime(value)


def test_parse_rejects_invalid_calendar_datetime():
    """Invalid dates and times are rejected after lexical parsing."""
    with pytest.raises(ValueError):
        parse_device_datetime("Thu Feb 30 07:21:12 2026")


def test_device_timezone_applies_standard_and_daylight_offsets():
    """The observed POSIX zone applies EST in winter and EDT in fall."""
    assert device_local_datetime(
        DEVICE_TZ, datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
    ) == datetime(2026, 1, 15, 7)
    assert device_local_datetime(
        DEVICE_TZ, datetime(2026, 10, 22, 11, 21, 12, tzinfo=timezone.utc)
    ) == datetime(2026, 10, 22, 7, 21, 12)


def test_device_timezone_handles_spring_and_fall_transitions():
    """M-rules use the correct local transition and offsets."""
    assert device_local_datetime(
        DEVICE_TZ, datetime(2026, 3, 8, 6, 59, 59, tzinfo=timezone.utc)
    ) == datetime(2026, 3, 8, 1, 59, 59)
    assert device_local_datetime(
        DEVICE_TZ, datetime(2026, 3, 8, 7, tzinfo=timezone.utc)
    ) == datetime(2026, 3, 8, 3)
    assert device_local_datetime(
        DEVICE_TZ, datetime(2026, 11, 1, 5, 59, 59, tzinfo=timezone.utc)
    ) == datetime(2026, 11, 1, 1, 59, 59)
    assert device_local_datetime(
        DEVICE_TZ, datetime(2026, 11, 1, 6, tzinfo=timezone.utc)
    ) == datetime(2026, 11, 1, 1)


def test_device_timezone_handles_fixed_and_signed_offsets():
    """Fixed offsets follow POSIX's reversed offset sign convention."""
    assert device_local_datetime(
        "UTC0", datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    ) == datetime(2026, 1, 1, 12)
    assert device_local_datetime(
        "XST-3", datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    ) == datetime(2026, 1, 1, 15)


def test_timezone_supports_minute_and_second_offsets():
    """POSIX offsets with sub-hour and second components are applied."""
    assert device_local_datetime(
        "NST-3:30:15",
        datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
    ) == datetime(2026, 1, 1, 15, 30, 15)


def test_device_timezone_handles_explicit_dst_offset_and_southern_rules():
    """Explicit daylight offsets and southern-hemisphere rules are supported."""
    assert device_local_datetime(
        "EST5EDT4,M3.2.0,M11.1.0",
        datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
    ) == datetime(2026, 7, 1, 8)
    assert device_local_datetime(
        "AEST-10AEDT-11,M10.1.0,M4.1.0",
        datetime(2026, 1, 1, 0, tzinfo=timezone.utc),
    ) == datetime(2026, 1, 1, 11)


def test_timezone_supports_last_weekday_and_transition_seconds():
    """The fifth-weekday rule means last weekday; transition times allow seconds."""
    assert device_local_datetime(
        "EST5EDT,M2.5.0,M11.1.0",
        datetime(2026, 2, 22, 7, tzinfo=timezone.utc),
    ) == datetime(2026, 2, 22, 3)
    assert device_local_datetime(
        "EST5EDT,M3.2.0/2:30:15,M11.1.0/2:30:15",
        datetime(2026, 3, 8, 7, 30, 15, tzinfo=timezone.utc),
    ) == datetime(2026, 3, 8, 3, 30, 15)


def test_timezone_parser_rejects_naive_time_and_unknown_zone():
    """Unsupported inputs do not silently fall back to another time zone."""
    with pytest.raises(ValueError, match="timezone-aware"):
        device_local_datetime(DEVICE_TZ, datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="Unsupported POSIX"):
        device_local_datetime("not-a-zone", datetime.now(timezone.utc))


@pytest.mark.parametrize("value", ["ABC25", "ABC5:60", "ABC5:00:60"])
def test_timezone_parser_rejects_invalid_offsets(value):
    """Out-of-range offsets and components fail explicitly."""
    with pytest.raises(ValueError):
        device_local_datetime(value, datetime(2026, 1, 1, tzinfo=timezone.utc))


@pytest.mark.parametrize(
    "value",
    [
        "EST5EDT,M13.2.0,M11.1.0",
        "EST5EDT,M3.6.0,M11.1.0",
        "EST5EDT,M3.2.7,M11.1.0",
        "EST5EDT,M3.2.0/2:99,M11.1.0",
        "EST5EDT,M3.2.0/2:00:99,M11.1.0",
    ],
)
def test_timezone_parser_rejects_invalid_transition_rules(value):
    """Invalid POSIX daylight-saving rules are not used."""
    with pytest.raises(ValueError):
        device_local_datetime(value, datetime(2026, 1, 1, tzinfo=timezone.utc))
