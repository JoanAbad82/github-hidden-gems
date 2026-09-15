"""Time helpers. All persisted timestamps are timezone-aware UTC."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

_ISO_FORMATS = (
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%S.%f%z",
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    for fmt in _ISO_FORMATS:
        try:
            return ensure_utc(datetime.strptime(text, fmt))
        except ValueError:
            continue
    try:
        return ensure_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError as exc:
        raise ValueError(f"unsupported datetime format: {value!r}") from exc


def to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return ensure_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def days_between(start: datetime, end: datetime) -> int:
    return int((ensure_utc(end) - ensure_utc(start)).total_seconds() // 86400)


def age_days(created_at: datetime, *, as_of: datetime) -> int:
    return max(0, days_between(created_at, as_of))


def days_ago(days: int, *, as_of: datetime) -> datetime:
    return ensure_utc(as_of) - timedelta(days=days)
