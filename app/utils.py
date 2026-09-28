from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc


def utcnow() -> datetime:
    """Return UTC as a naive datetime for SQLite portability."""
    return datetime.now(UTC).replace(tzinfo=None)


def warehouse_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown warehouse timezone: {name}") from exc


def local_naive_to_utc(value: datetime, timezone_name: str) -> datetime:
    """Convert a browser ``datetime-local`` value into naive UTC for storage."""
    if value.tzinfo is not None:
        local_value = value.astimezone(warehouse_timezone(timezone_name))
    else:
        local_value = value.replace(tzinfo=warehouse_timezone(timezone_name))
    return local_value.astimezone(UTC).replace(tzinfo=None)


def utc_naive_to_local(value: datetime, timezone_name: str) -> datetime:
    """Convert a stored naive-UTC datetime into an aware warehouse-local value."""
    if value.tzinfo is None:
        utc_value = value.replace(tzinfo=UTC)
    else:
        utc_value = value.astimezone(UTC)
    return utc_value.astimezone(warehouse_timezone(timezone_name))
