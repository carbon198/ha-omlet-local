"""Device clock parsing and POSIX time zone handling."""

import calendar
import re
from datetime import date, datetime, timedelta, timezone

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
_MONTH_INDEX = {name: index for index, name in enumerate(_MONTHS, 1)}
_OFFSET = r"[+-]?\d{1,3}(?::\d{1,2}(?::\d{1,2})?)?"
_TZ_RE = re.compile(
    rf"^(?P<std_name><[^>]+>|[A-Za-z]{{3,}})"
    rf"(?P<std_offset>{_OFFSET})?"
    rf"(?:"
    rf"(?P<dst_name><[^>]+>|[A-Za-z]{{3,}})"
    rf"(?P<dst_offset>{_OFFSET})?,"
    rf"M(?P<start_month>\d{{1,2}})\.(?P<start_week>\d)\."
    rf"(?P<start_weekday>\d)(?:/(?P<start_time>{_OFFSET}))?,"
    rf"M(?P<end_month>\d{{1,2}})\.(?P<end_week>\d)\."
    rf"(?P<end_weekday>\d)(?:/(?P<end_time>{_OFFSET}))?"
    rf")?$"
)
_DATETIME_RE = re.compile(
    r"^(?P<weekday>Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
    r"(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"(?P<day>\d{1,2}) (?P<hour>\d{2}):(?P<minute>\d{2}):"
    r"(?P<second>\d{2}) (?P<year>\d{4})$"
)


def parse_device_datetime(value: str) -> datetime:
    """Parse the device's English abbreviated local datetime."""
    match = _DATETIME_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"Unsupported device datetime: {value!r}")
    return datetime(
        int(match["year"]),
        _MONTH_INDEX[match["month"]],
        int(match["day"]),
        int(match["hour"]),
        int(match["minute"]),
        int(match["second"]),
    )


def format_device_datetime(value: datetime) -> str:
    """Format a local datetime using the device's English abbreviated format."""
    return (
        f"{_WEEKDAYS[value.weekday()]} {_MONTHS[value.month - 1]} "
        f"{value.day:02d} {value:%H:%M:%S} {value.year:04d}"
    )


def device_local_datetime(timezone_value: str, now_utc: datetime) -> datetime:
    """Convert UTC time to a device local time using its POSIX time zone."""
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("UTC time must be timezone-aware")
    now_utc = now_utc.astimezone(timezone.utc)
    match = _TZ_RE.fullmatch(timezone_value.strip())
    if match is None:
        raise ValueError(f"Unsupported POSIX time zone: {timezone_value!r}")

    standard_offset = _parse_posix_offset(match["std_offset"] or "0")
    offset = standard_offset
    if match["dst_name"] is not None:
        daylight_offset = (
            _parse_posix_offset(match["dst_offset"])
            if match["dst_offset"]
            else standard_offset + timedelta(hours=1)
        )
        year = now_utc.year
        start_utc = _transition_utc(
            year,
            match["start_month"],
            match["start_week"],
            match["start_weekday"],
            match["start_time"],
            standard_offset,
        )
        end_utc = _transition_utc(
            year,
            match["end_month"],
            match["end_week"],
            match["end_weekday"],
            match["end_time"],
            daylight_offset,
        )
        in_daylight_time = (
            start_utc <= now_utc < end_utc
            if start_utc < end_utc
            else now_utc >= start_utc or now_utc < end_utc
        )
        if in_daylight_time:
            offset = daylight_offset

    return now_utc.replace(tzinfo=None) + offset


def _parse_posix_offset(value: str) -> timedelta:
    """Convert a POSIX offset (whose sign is reversed) to a UTC offset."""
    sign = -1 if value.startswith("-") else 1
    components = [int(part) for part in value.lstrip("+-").split(":")]
    if len(components) > 1 and components[1] > 59:
        raise ValueError(f"Invalid POSIX time zone offset: {value!r}")
    if len(components) > 2 and components[2] > 59:
        raise ValueError(f"Invalid POSIX time zone offset: {value!r}")
    seconds = components[0] * 3600
    if len(components) > 1:
        seconds += components[1] * 60
    if len(components) > 2:
        seconds += components[2]
    if seconds > 24 * 3600:
        raise ValueError(f"POSIX time zone offset is out of range: {value!r}")
    return timedelta(seconds=-sign * seconds)


def _transition_utc(
    year: int,
    month_value: str,
    week_value: str,
    weekday_value: str,
    time_value: str | None,
    offset: timedelta,
) -> datetime:
    """Calculate a POSIX M-rule transition as a UTC datetime."""
    month = int(month_value)
    week = int(week_value)
    weekday = int(weekday_value)
    if not 1 <= month <= 12 or not 1 <= week <= 5 or not 0 <= weekday <= 6:
        raise ValueError("Invalid POSIX daylight-saving transition rule")

    first_weekday = (date(year, month, 1).weekday() + 1) % 7
    day = 1 + (weekday - first_weekday) % 7 + (week - 1) * 7
    days_in_month = calendar.monthrange(year, month)[1]
    if day > days_in_month:
        day -= 7
    transition_time = _parse_transition_time(time_value or "2")
    local_transition = datetime(year, month, day) + timedelta(
        seconds=transition_time
    )
    return (local_transition - offset).replace(tzinfo=timezone.utc)


def _parse_transition_time(value: str) -> int:
    """Parse a POSIX transition time, allowing signed or extended hours."""
    sign = -1 if value.startswith("-") else 1
    components = [int(part) for part in value.lstrip("+-").split(":")]
    if len(components) > 1 and components[1] > 59:
        raise ValueError(f"Invalid POSIX transition time: {value!r}")
    if len(components) > 2 and components[2] > 59:
        raise ValueError(f"Invalid POSIX transition time: {value!r}")
    seconds = components[0] * 3600
    if len(components) > 1:
        seconds += components[1] * 60
    if len(components) > 2:
        seconds += components[2]
    return sign * seconds
