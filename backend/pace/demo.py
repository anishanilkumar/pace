"""The public demo: a made-up freelancer's hours, generated rather than stored.

Foodlog's and Recipie's demos seed a database at start-up. Pace's has a
different need: "today" only makes sense if it fills up as the day goes on.
So the hours are a pure function of the date (and, for today, the time):
every past day is drawn from a random generator seeded with the date itself,
so it is the same on every refresh and for every visitor, and today is
whatever of its planned work the clock says has happened.

`refresh` writes that into the demo's own database every few minutes (and
when a visitor presses Sync), records a successful "read", and runs the real
nudge rules over it, so the dashboard and nudges are the real code on
made-up hours. Nothing a visitor sends is stored: the demo's settings are
fixed (web.py refuses changes) and uploads are refused.

The freelancer: 30 USD an hour, 85 INR to the dollar, 10 % TDS, ₹2,00,000 a
month after TDS (about 87 hours), Monday to Friday, in Berlin. Months vary
on purpose, some comfortably over target and some short, so the history
panel has something to show.
"""

from __future__ import annotations

import logging
import random
from datetime import date, datetime, time, timedelta, timezone

from . import db
from .plan import Prefs
from .worker import HISTORY_MONTHS, month_start, run_nudges

log = logging.getLogger(__name__)

REFRESH_EVERY = timedelta(minutes=5)
PROJECT = "Atlas"
# Productive tasks, a few per week; the week picks which.
TASKS = [
    "Checkout API", "Payment retries", "Search indexing", "Admin dashboard",
    "Migrate to Postgres 17", "Fix flaky tests", "Invoice PDFs", "Rate limiting",
    "Onboarding emails", "Code review",
]


def third_friday(year: int, month: int) -> date:
    d = date(year, month, 15)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def prefs(today: date) -> Prefs:
    # A day of leave each month (its third Friday), so the plan shows one.
    leaves = [third_friday((m := month_start(today, b)).year, m.month).isoformat() for b in range(HISTORY_MONTHS + 1)]
    return Prefs(
        hourly_rate_usd=30, usd_inr=85, tds_pct=10, target_net_inr=200_000,
        work_days=[0, 1, 2, 3, 4], max_hours_per_day=10, leaves=leaves,
        tz="Europe/Berlin", nudges=True, nudge_from="09:00", nudge_until="21:00",
    )


def plan_day(d: date, p: Prefs) -> list[tuple[str, int]]:
    """(task, seconds) for a whole day, the same every time it's asked."""
    rng = random.Random(f"pace-demo:{d.isoformat()}")
    if d.isoformat() in p.leaves:
        return []
    if d.weekday() >= 5:
        # The odd weekend hour.
        return [("Fix flaky tests", int(rng.uniform(0.5, 1.5) * 3600))] if rng.random() < 0.12 else []
    # Some months go well and some don't.
    month_mood = random.Random(f"pace-demo:{d.year}-{d.month}").uniform(0.78, 1.15)
    total = max(1.0, min(8.0, rng.gauss(4.2, 1.1) * month_mood)) * 3600
    meetings = [("Meeting - Daily Standup", 15 * 60)]
    if d.weekday() == 0 and d.isocalendar().week % 2 == 0:
        meetings.append(("Sprint planning meeting", 60 * 60))
    if d.weekday() == 3:
        meetings.append(("Call with client", int(rng.choice([30, 45, 60]) * 60)))
    if rng.random() < 0.25:
        meetings.append(("Design review meeting", 45 * 60))
    left = max(0, int(total) - sum(s for _, s in meetings))
    week = random.Random(f"pace-demo:week:{d.isocalendar().year}-{d.isocalendar().week}")
    picks = week.sample(TASKS, 3)
    shares = [rng.uniform(0.2, 1) for _ in picks[: rng.choice([1, 2, 2, 3])]]
    work = [(picks[i], int(left * s / sum(shares))) for i, s in enumerate(shares)]
    return meetings + work


def worked_so_far(now: datetime, total: int) -> int:
    """How much of today's plan has happened by `now` (Berlin): from 09:15, lunch at 12:45 for an hour."""
    local = now.astimezone(prefs(now.date()).zone)
    start = datetime.combine(local.date(), time(9, 15), local.tzinfo)
    lunch = datetime.combine(local.date(), time(12, 45), local.tzinfo)
    seconds = max(0.0, (min(local, lunch) - start).total_seconds())
    if local > lunch + timedelta(hours=1):
        seconds += (local - lunch - timedelta(hours=1)).total_seconds()
    return min(total, int(seconds))


def refresh(now: datetime | None = None, force: bool = False) -> None:
    now = now or datetime.now(timezone.utc)
    last = db.get_kv("demo_refreshed")
    if not force and last and now - datetime.fromisoformat(last) < REFRESH_EVERY:
        return
    p = prefs(now.date())
    today = now.astimezone(p.zone).date()
    days: dict[date, int] = {}
    tasks: list[db.TaskRow] = []
    d = month_start(today, HISTORY_MONTHS)
    while d <= today:
        planned = plan_day(d, p)
        if d == today:
            # Today's tasks shrink to what the clock says has been done.
            total = sum(s for _, s in planned)
            share = worked_so_far(now, total) / total if total else 0
            planned = [(t, int(s * share)) for t, s in planned if int(s * share) > 0]
        days[d] = sum(s for _, s in planned)
        tasks += [(d, f"{PROJECT}/{t}", t, PROJECT, s) for t, s in planned]
        d += timedelta(days=1)
    db.put_prefs(p)
    db.put_days(days)
    db.put_tasks(month_start(today, HISTORY_MONTHS), today, tasks)
    with db.write_tx() as conn:
        # Only the latest "read" matters, and the demo makes one every few minutes.
        conn.execute("DELETE FROM fetches")
        # Yesterday's nudges are yesterday's: keep the list to today's.
        conn.execute("DELETE FROM nudges WHERE created_at < ?", ((now - timedelta(days=1)).isoformat(),))
    db.fetch_finished(db.fetch_started("browser"))
    db.set_kv("demo_refreshed", now.isoformat())
    run_nudges(now)
    log.info("demo: refreshed to %s, %.2f h today", now.isoformat(timespec="minutes"), days[today] / 3600)
