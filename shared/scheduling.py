"""Bounded, timezone-explicit scheduling shared by server and desktop.

No background threads or execution live here. All instants are aware UTC values.
"""

from datetime import datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
KINDS = {"manual", "once", "daily", "weekly"}
_FIELDS = {"kind", "timezone", "start_at", "time", "weekdays", "misfire", "grace_seconds"}


def aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("执行时间必须明确包含时区")
    return value.astimezone(UTC)


def _parse_instant(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("一次性执行必须提供带时区的 start_at")
    try:
        return aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (ValueError, OverflowError) as exc:
        raise ValueError("start_at 必须是带时区的 ISO 日期时间") from exc


def validate_trigger(value):
    if not isinstance(value, dict) or set(value) - _FIELDS:
        raise ValueError("触发规则包含无效字段")
    kind = value.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("执行频率必须是 manual、once、daily 或 weekly")
    zone = value.get("timezone", "Asia/Shanghai")
    if not isinstance(zone, str) or len(zone) > 80:
        raise ValueError("时区无效")
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("时区无效，请使用 IANA 时区名称") from exc
    misfire = value.get("misfire", "skip")
    if not isinstance(misfire, str) or misfire not in {"skip", "run_once"}:
        raise ValueError("错过执行策略必须是 skip 或 run_once")
    grace = value.get("grace_seconds", 300)
    if not isinstance(grace, int) or isinstance(grace, bool) or not 1 <= grace <= 86400:
        raise ValueError("补执行宽限必须在 1–86400 秒之间")
    result = {"kind": kind, "timezone": zone, "misfire": misfire, "grace_seconds": grace}
    if kind == "once":
        result["start_at"] = _parse_instant(value.get("start_at")).isoformat()
    if kind in {"daily", "weekly"}:
        clock = value.get("time")
        if not isinstance(clock, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", clock):
            raise ValueError("执行时刻必须使用 HH:MM")
        result["time"] = clock
    if kind == "weekly":
        days = value.get("weekdays")
        if not isinstance(days, list) or not 1 <= len(days) <= 7 or any(
            not isinstance(day, int) or isinstance(day, bool) or not 0 <= day <= 6 for day in days
        ):
            raise ValueError("请选择执行星期，周一为 0，周日为 6")
        result["weekdays"] = sorted(set(days))
    return result


def _wall_instant(day, clock, zone):
    local = datetime.combine(day, time.fromisoformat(clock)).replace(tzinfo=zone, fold=0)
    candidate = local.astimezone(UTC)
    # Spring gaps are not silently shifted. Fall overlap uses only fold=0.
    roundtrip = candidate.astimezone(zone)
    if roundtrip.replace(tzinfo=None) != local.replace(tzinfo=None):
        return None
    return candidate


def next_fire(trigger, after):
    trigger = validate_trigger(trigger)
    after = aware(after)
    if trigger["kind"] == "manual":
        return None
    if trigger["kind"] == "once":
        candidate = _parse_instant(trigger["start_at"])
        return candidate if candidate > after else None
    zone = ZoneInfo(trigger["timezone"])
    first_day = after.astimezone(zone).date()
    # At most two weekly cycles: includes a weekly occurrence skipped by DST.
    for delta in range(16):
        day = first_day + timedelta(days=delta)
        if trigger["kind"] == "weekly" and day.weekday() not in trigger["weekdays"]:
            continue
        candidate = _wall_instant(day, trigger["time"], zone)
        if candidate is not None and candidate > after:
            return candidate
    raise ValueError("无法在有限时间窗口内计算下次执行")


def latest_fire(trigger, at_or_before):
    """Most recent occurrence; bounded even after years of downtime."""
    trigger = validate_trigger(trigger)
    now = aware(at_or_before)
    if trigger["kind"] == "manual":
        return None
    if trigger["kind"] == "once":
        candidate = _parse_instant(trigger["start_at"])
        return candidate if candidate <= now else None
    zone = ZoneInfo(trigger["timezone"])
    first_day = now.astimezone(zone).date()
    for delta in range(16):
        day = first_day - timedelta(days=delta)
        if trigger["kind"] == "weekly" and day.weekday() not in trigger["weekdays"]:
            continue
        candidate = _wall_instant(day, trigger["time"], zone)
        if candidate is not None and candidate <= now:
            return candidate
    raise ValueError("无法在有限时间窗口内计算最近执行")


def due_occurrence(trigger, scheduled_for, now):
    trigger = validate_trigger(trigger)
    delay = (aware(now) - aware(scheduled_for)).total_seconds()
    tolerance = 30 if trigger["misfire"] == "skip" else trigger["grace_seconds"]
    if not 0 <= delay <= tolerance:
        return False
    # DST 可能让相邻日间隔小于宽限期；也只允许最近一次，不追赶旧排队项。
    return trigger['kind'] == 'manual' or latest_fire(trigger, now) == aware(scheduled_for)
