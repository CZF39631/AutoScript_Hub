from datetime import datetime, timedelta, timezone

import pytest

from shared.scheduling import due_occurrence, latest_fire, next_fire, validate_trigger


def at(text):
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def test_once_and_manual():
    trigger = {"kind": "once", "start_at": "2026-03-01T09:00:00+08:00"}
    expected = at("2026-03-01T01:00:00+00:00")
    assert next_fire(trigger, expected - timedelta(seconds=1)) == expected
    assert next_fire(trigger, expected) is None
    assert latest_fire(trigger, expected) == expected
    assert next_fire({"kind": "manual"}, expected) is None


def test_daily_week_boundary_and_bounded_backlog():
    trigger = {"kind": "weekly", "time": "09:00", "weekdays": [0]}
    now = at("2026-03-01T23:00:00+08:00")
    assert next_fire(trigger, now) == at("2026-03-02T09:00:00+08:00")
    assert latest_fire(trigger, at("2040-01-03T12:00:00+08:00")) <= at("2040-01-03T12:00:00+08:00")
    daily = {"kind": "daily", "time": "00:00"}
    assert next_fire(daily, now) == at("2026-03-02T00:00:00+08:00")


def test_dst_gap_skips_nonexistent_and_overlap_fires_once():
    daily = {"kind": "daily", "timezone": "America/New_York", "time": "02:30"}
    assert next_fire(daily, at("2026-03-08T00:00:00-05:00")) == at("2026-03-09T02:30:00-04:00")
    daily["time"] = "01:30"
    first = at("2026-11-01T01:30:00-04:00")
    assert next_fire(daily, first - timedelta(seconds=1)) == first
    assert next_fire(daily, first) == at("2026-11-02T01:30:00-05:00")
    assert latest_fire(daily, at("2026-11-01T01:30:00-05:00")) == first


def test_weekly_dst_skip_stays_bounded():
    rule = {"kind": "weekly", "timezone": "America/New_York", "time": "02:30", "weekdays": [6]}
    assert next_fire(rule, at("2026-03-01T03:00:00-05:00")) == at("2026-03-15T02:30:00-04:00")
    assert latest_fire(rule, at("2026-03-08T12:00:00-04:00")) == at("2026-03-01T02:30:00-05:00")


def test_wide_grace_across_short_dst_day_still_runs_only_latest_occurrence():
    trigger = {'kind': 'daily', 'time': '03:30', 'timezone': 'America/New_York',
               'misfire': 'run_once', 'grace_seconds': 86400}
    previous = at('2026-03-07T03:30:00-05:00')
    latest = at('2026-03-08T03:30:00-04:00')
    now = latest + timedelta(minutes=1)
    assert (now - previous).total_seconds() < 86400
    assert not due_occurrence(trigger, previous, now)
    assert due_occurrence(trigger, latest, now)


def test_misfires_and_clock_rollback():
    trigger = {"kind": "daily", "time": "09:00"}
    scheduled = at("2026-03-01T09:00:00+08:00")
    assert due_occurrence(trigger, scheduled, scheduled + timedelta(seconds=30))
    assert not due_occurrence(trigger, scheduled, scheduled + timedelta(seconds=31))
    trigger.update(misfire="run_once", grace_seconds=60)
    assert due_occurrence(trigger, scheduled, scheduled + timedelta(seconds=60))
    assert not due_occurrence(trigger, scheduled, scheduled + timedelta(seconds=61))
    assert not due_occurrence(trigger, scheduled, scheduled - timedelta(seconds=1))


@pytest.mark.parametrize("trigger", [
    {}, {"kind": "cron"}, {"kind": "daily", "time": "25:00"},
    {"kind": []}, {"kind": {}}, {"kind": "manual", "misfire": []},
    {"kind": "daily", "time": "0٢:00"},
    {"kind": "once", "start_at": "0001-01-01T00:00:00+14:00"},
    {"kind": "once", "start_at": "2026-03-01T09:00:00"},
    {"kind": "weekly", "time": "09:00", "weekdays": [True]},
    {"kind": "weekly", "time": "09:00", "weekdays": []},
    {"kind": "daily", "time": "09:00", "timezone": "../etc/passwd"},
    {"kind": "manual", "grace_seconds": False},
    {"kind": "manual", "unknown": "ignored?"},
])
def test_invalid_rules_fail_closed(trigger):
    with pytest.raises(ValueError):
        validate_trigger(trigger)


def test_naive_clock_rejected():
    with pytest.raises(ValueError):
        next_fire({"kind": "daily", "time": "09:00"}, datetime(2026, 1, 1))
