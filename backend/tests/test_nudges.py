from datetime import date, datetime, timedelta

from pace.nudges import evaluate, fmt_h
from pace.plan import Prefs

# 100 h target (see test_plan), 09:00-19:00, Asia/Kolkata.
PREFS = Prefs(hourly_rate_usd=25, usd_inr=80, tds_pct=10, target_net_inr=180_000, tz="Asia/Kolkata")
Z = PREFS.zone
ON_PLAN = {date(2026, 10, d): 100 / 22 for d in (1, 2, 5, 6, 7, 8, 9, 12, 13)}


def at(hhmm: str, d: str = "2026-10-14") -> datetime:
    return datetime.fromisoformat(f"{d}T{hhmm}").replace(tzinfo=Z)


def keys(nudges) -> list[str]:
    return [n.key.split(":")[0] for n in nudges]


def run(now, hours=ON_PLAN, last_change=None, last_good="fresh", prefs=PREFS):
    good = now - timedelta(minutes=10) if last_good == "fresh" else last_good
    return evaluate(prefs, hours, now, last_change, good)


def test_fmt():
    assert fmt_h(2.4166) == "2 h 25 min"
    assert fmt_h(0.75) == "45 min"
    assert fmt_h(3) == "3 h"


def test_on_plan_morning_is_quiet():
    assert run(at("09:30")) == []


def test_behind_for_the_month_in_the_morning():
    hours = {date(2026, 10, d): 2.0 for d in (1, 2, 5, 6, 7, 8, 9, 12, 13)}
    out = run(at("09:30"), hours)
    assert keys(out) == ["month"]
    assert out[0].title.endswith("behind for October")
    # Only in the first two hours of the window.
    assert "month" not in keys(run(at("12:00"), hours))


def test_not_started():
    assert keys(run(at("10:31"))) == ["start"]
    assert run(at("10:29")) == []


def test_idle_after_75_minutes():
    hours = {**ON_PLAN, date(2026, 10, 14): 1.0}
    out = run(at("12:20"), hours, last_change=at("11:00"))
    assert keys(out) == ["idle"]
    assert out[0].title == "Nothing tracked since 11:00"
    assert out[0].key == "idle:2026-10-14:1100"
    assert run(at("12:10"), hours, last_change=at("11:00")) == []


def test_midday_and_evening():
    hours = {**ON_PLAN, date(2026, 10, 14): 1.0}
    assert "midday" in keys(run(at("14:05"), hours, last_change=at("14:00")))
    out = run(at("17:10"), hours, last_change=at("17:05"))
    assert "evening" in keys(out)


def test_done_for_today():
    hours = {**ON_PLAN, date(2026, 10, 14): 5.0}
    out = run(at("17:10"), hours, last_change=at("17:05"))
    assert keys(out) == ["done"]


def test_stale_data_silences_the_rest():
    out = run(at("17:10"), {**ON_PLAN, date(2026, 10, 14): 1.0}, last_good=at("13:00"))
    assert keys(out) == ["stale"]
    assert "since 13:00" in out[0].body


def test_days_off_and_switched_off():
    assert run(at("17:10", "2026-10-17")) == []  # Saturday
    assert run(at("10:31"), prefs=PREFS.model_copy(update={"nudges": False})) == []
