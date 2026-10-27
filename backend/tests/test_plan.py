from datetime import date, datetime

import pytest
from pydantic import ValidationError

from pace.plan import Prefs, month_plan, streak

# 25 USD x 80 INR x 0.9 = 1800 INR an hour after TDS; 180,000 is 100 h.
PREFS = Prefs(hourly_rate_usd=25, usd_inr=80, tds_pct=10, target_net_inr=180_000, tz="Asia/Kolkata")
Z = PREFS.zone


def at(d: str, hhmm: str) -> datetime:
    return datetime.fromisoformat(f"{d}T{hhmm}").replace(tzinfo=Z)


def test_target_hours_from_net():
    assert PREFS.net_per_hour == pytest.approx(1800)
    assert PREFS.target_hours == pytest.approx(100)


def test_even_plan_and_quota():
    # October 2026: 22 weekdays. Thursday the 1st through Tuesday the 13th
    # are 9 working days before Wednesday the 14th.
    hours = {date(2026, 10, d): 4.0 for d in (1, 2, 5, 6, 7, 8, 9, 12, 13)}
    p = month_plan(PREFS, hours, at("2026-10-14", "09:00"))
    assert p["working_days"] == 22
    assert p["plan_per_day"] == pytest.approx(100 / 22)
    assert p["worked_hours"] == pytest.approx(36)
    # Expected by 09:00 on the 14th: 9 full days of the plan, none of today.
    assert p["expected_hours"] == pytest.approx(9 * 100 / 22)
    assert p["status"] == "behind"
    # 64 h left over 13 working days including today.
    assert p["working_days_left"] == 13
    assert p["today_quota"] == pytest.approx(64 / 13)
    assert p["projected_hours"] == pytest.approx(36 + 4 * 13)


def test_quota_holds_through_the_day():
    hours = {date(2026, 10, 14): 3.0}
    morning = month_plan(PREFS, hours, at("2026-10-14", "09:00"))
    evening = month_plan(PREFS, hours, at("2026-10-14", "18:00"))
    assert morning["today_quota"] == evening["today_quota"]
    assert evening["today_left"] == pytest.approx(evening["today_quota"] - 3)


def test_leave_and_weekend_are_not_working_days():
    prefs = PREFS.model_copy(update={"leaves": ["2026-10-02"]})
    p = month_plan(prefs, {}, at("2026-10-02", "12:00"))
    assert p["working_days"] == 21
    assert p["today_working"] is False
    assert p["today_quota"] == 0
    # Hours on a day off still count.
    p = month_plan(prefs, {date(2026, 10, 3): 2.0}, at("2026-10-05", "08:00"))
    assert p["worked_hours"] == 2


def test_out_of_reach_and_done():
    p = month_plan(PREFS, {}, at("2026-10-29", "09:00"))
    assert p["status"] == "out_of_reach"  # 100 h over 3 days
    p = month_plan(PREFS, {date(2026, 10, 5): 101.0}, at("2026-10-29", "09:00"))
    assert p["status"] == "done"


def test_no_projection_before_a_day_has_finished():
    p = month_plan(PREFS, {date(2026, 10, 1): 2.0}, at("2026-10-01", "12:00"))
    assert p["projected_hours"] is None


def test_past_month_is_judged_whole():
    hours = {date(2026, 9, d): 5.0 for d in range(1, 31)}
    p = month_plan(PREFS, hours, at("2026-10-14", "09:00"), (2026, 9))
    assert p["today"] is None
    assert p["expected_hours"] == pytest.approx(100)
    assert p["worked_hours"] == 150
    assert p["status"] == "done"


def test_streak_skips_days_off_and_waits_for_today():
    per_day = 4.0
    hours = {date(2026, 10, 9): 4.0, date(2026, 10, 12): 4.2, date(2026, 10, 8): 1.0}
    # Tuesday 13th, nothing yet today: Mon 12 and Fri 9 count, the weekend is skipped, Thu 8 breaks it.
    assert streak(PREFS, hours, date(2026, 10, 13), per_day) == 2
    hours[date(2026, 10, 13)] = 4.0
    assert streak(PREFS, hours, date(2026, 10, 13), per_day) == 3


def test_prefs_validation():
    with pytest.raises(ValidationError):
        Prefs(nudge_from="21:00", nudge_until="09:00")
    with pytest.raises(ValidationError):
        Prefs(meeting_pattern="(unclosed")
    # Prefs saved before flexible hours still load; the old window is ignored.
    assert Prefs.model_validate({"day_start": "09:00", "day_end": "19:00", "tds_pct": 5}).tds_pct == 5
    with pytest.raises(ValidationError):
        Prefs(tz="Mars/Olympus")
    with pytest.raises(ValidationError):
        Prefs(work_days=[7])
    assert Prefs(leaves=["2026-10-02", "2026-10-02"]).leaves == ["2026-10-02"]


def test_behind_counts_finished_days_and_today_helps_at_once():
    hours = {date(2026, 10, d): 4.0 for d in (1, 2, 5, 6, 7, 8, 9, 12, 13)}
    morning = month_plan(PREFS, hours, at("2026-10-14", "06:00"))
    night = month_plan(PREFS, hours, at("2026-10-14", "23:00"))
    # No clock: the same verdict at 06:00 and 23:00 with nothing done today.
    assert morning["diff_hours"] == night["diff_hours"]
    worked = month_plan(PREFS, {**hours, date(2026, 10, 14): 3.0}, at("2026-10-14", "10:00"))
    assert worked["diff_hours"] == pytest.approx(morning["diff_hours"] + 3)


def test_meeting_rule_is_whole_words():
    assert PREFS.is_meeting("Engineering Meeting")
    assert PREFS.is_meeting("Meeting - Daily Standup")
    assert PREFS.is_meeting("Call with Nijo on Enrollment")
    assert not PREFS.is_meeting("Implement Juanita's changes")
    assert not PREFS.is_meeting("Recall the cache keys")


def test_work_split():
    from pace.plan import work_split

    rows = [
        (date(2026, 10, 1), "Engineering Meeting", "TAI", 3600),
        (date(2026, 10, 1), "Foundational certificate issue", "TAI", 7200),
        (date(2026, 10, 2), "Meeting - Daily Standup", "TAI", 900),
        (date(2026, 9, 30), "Engineering Meeting", "TAI", 3600),  # outside the month
    ]
    s = work_split(PREFS, rows, date(2026, 10, 1), date(2026, 10, 31))
    assert s["meeting_hours"] == pytest.approx(1.25)
    assert s["productive_hours"] == pytest.approx(2)
    assert s["meeting_share"] == pytest.approx(1.25 / 3.25)
    assert s["meeting_by_day"] == {"2026-10-01": 1.0, "2026-10-02": 0.25}
    assert s["tasks"][0] == {"task": "Foundational certificate issue", "project": "TAI", "hours": 2.0, "meeting": False}
    assert work_split(PREFS, [], date(2026, 10, 1), date(2026, 10, 31))["meeting_share"] is None
