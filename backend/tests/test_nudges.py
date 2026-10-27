from datetime import date, datetime, timedelta

from pace.nudges import evaluate, fmt_h
from pace.plan import Prefs

# 100 h target (see test_plan), nudges 09:00-21:00, Asia/Kolkata.
PREFS = Prefs(hourly_rate_usd=25, usd_inr=80, tds_pct=10, target_net_inr=180_000, tz="Asia/Kolkata")
Z = PREFS.zone
ON_PLAN = {date(2026, 10, d): 100 / 22 for d in (1, 2, 5, 6, 7, 8, 9, 12, 13)}


def at(hhmm: str, d: str = "2026-10-14") -> datetime:
    return datetime.fromisoformat(f"{d}T{hhmm}").replace(tzinfo=Z)


def keys(nudges) -> list[str]:
    return [n.key.split(":")[0] for n in nudges]


def run(now, hours=ON_PLAN, last_good="fresh", prefs=PREFS):
    good = now - timedelta(minutes=10) if last_good == "fresh" else last_good
    return evaluate(prefs, hours, now, good)


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
    # Only in the first two hours of the nudge window.
    assert "month" not in keys(run(at("12:00"), hours))


def test_no_clock_on_the_work_itself():
    # Flexible hours: nothing tracked at 14:00 is not yet a problem...
    assert run(at("14:00")) == []
    # ...but by the middle of the nudge window (15:00) it's worth a word.
    assert keys(run(at("15:01"))) == ["start"]


def test_evening_and_done():
    hours = {**ON_PLAN, date(2026, 10, 14): 1.0}
    assert keys(run(at("17:59"), hours)) == []
    out = run(at("18:05"), hours)
    assert keys(out) == ["evening"]
    assert out[0].title.endswith("left for today")
    done = {**ON_PLAN, date(2026, 10, 14): 5.0}
    assert keys(run(at("18:05"), done)) == ["done"]


def test_nothing_outside_the_nudge_window():
    assert run(at("08:30")) == []
    assert run(at("22:00"), {**ON_PLAN, date(2026, 10, 14): 1.0}) == []
    late = PREFS.model_copy(update={"nudge_until": "23:00"})
    assert keys(run(at("22:00"), {**ON_PLAN, date(2026, 10, 14): 1.0}, prefs=late)) == ["evening"]


def test_stale_data_silences_the_rest():
    out = run(at("18:10"), {**ON_PLAN, date(2026, 10, 14): 1.0}, last_good=at("13:00"))
    assert keys(out) == ["stale"]
    assert "since 13:00" in out[0].body


def test_days_off_and_switched_off():
    assert run(at("18:10", "2026-10-17")) == []  # Saturday
    assert run(at("15:01"), prefs=PREFS.model_copy(update={"nudges": False})) == []
