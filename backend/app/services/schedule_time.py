"""Managed schedule validation and UTC-naive cursor calculation."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter


def ensure_utc_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def utc_naive(value: datetime) -> datetime:
    return ensure_utc_aware(value).replace(tzinfo=None)


def validate_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError("无效的 IANA timezone")
    return name


def validate_cron_expression(expression: str) -> str:
    expression = " ".join(expression.split())
    if len(expression.split()) != 5 or not croniter.is_valid(expression):
        raise ValueError("cron_expression 必须是有效的五段 cron 表达式")
    return expression


def next_schedule_time(
    *,
    schedule_type: str,
    after: datetime,
    interval_seconds: Optional[int] = None,
    cron_expression: Optional[str] = None,
    timezone_name: str = "UTC",
) -> datetime:
    """Return the first occurrence strictly after ``after`` as UTC-aware datetime."""
    after = ensure_utc_aware(after)
    if schedule_type == "interval":
        if interval_seconds is None or interval_seconds < 60:
            raise ValueError("interval 调度必须提供至少 60 秒的 interval_seconds")
        return after + timedelta(seconds=interval_seconds)
    if schedule_type != "cron":
        raise ValueError("schedule_type 必须是 interval 或 cron")
    expression = validate_cron_expression(cron_expression or "")
    timezone_name = validate_timezone(timezone_name)
    local_after = after.astimezone(ZoneInfo(timezone_name))
    return croniter(expression, local_after).get_next(datetime).astimezone(timezone.utc)
