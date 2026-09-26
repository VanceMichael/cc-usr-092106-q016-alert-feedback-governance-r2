"""ISO-8601 时间解析与窗口判断。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"时间必须带时区：{value}")
    return dt


def add_days(value: str, days: int) -> datetime:
    return parse_dt(value) + timedelta(days=days)


def seconds_between(start: str, end: str) -> float:
    return (parse_dt(end) - parse_dt(start)).total_seconds()


def epoch_days(dt: datetime) -> int:
    return (dt - _EPOCH).days
