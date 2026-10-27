"""The worker: reads Time Doctor on a schedule, then decides on nudges.

One long-running process (systemd unit `pace-worker`), separate from the web
app so a headless Chromium never shares memory or a crash with the API. The
web app asks for an early fetch through the database (db.request_fetch); the
worker looks for that every 30 seconds.

Cadence: hours are flexible, so the same every day: every
PACE_FETCH_EVERY_MIN (20) from an hour before the nudge window to an hour
after it, PACE_FETCH_IDLE_EVERY_MIN (120) through the night, so late work
still shows up without the browser running every 20 minutes till morning.

What a read covers (timedoctor.py reads one day per request, so this is
kept small): yesterday and today, which is where new time lands; the whole
month once a day, for time edited after the fact; and, once, the last six
months, in the person's own days.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from . import db, nudges
from .config import settings
from .timedoctor import FetchError, fetch_days

log = logging.getLogger(__name__)
TICK = 30

# Months of history kept for the dashboard's "last 6 months" and the month
# browser, read once and then left alone (finished months don't change).
HISTORY_MONTHS = 6

# kv keys. The history mark names the zone it was read in: changing the
# time zone in settings re-splits the days, so the history is read again.
HISTORY_KEY = "history_read"
MONTH_KEY = "month_reread_on"


def month_start(d: date, back: int) -> date:
    """The first day of the month `back` months before d's."""
    i = d.year * 12 + d.month - 1 - back
    return date(i // 12, i % 12 + 1, 1)


def fetch_span(today: date) -> tuple[date, date]:
    """This month so far; in the first days of a month, last month too.

    Time Doctor time can be edited after the fact (manual time, a deleted
    stretch). Re-reading last month for a few days lets its final numbers
    settle before it stops being read.
    """
    first = today.replace(day=1)
    if today.day <= 3:
        first = (first - timedelta(days=1)).replace(day=1)
    return first, today


def days_to_read(today: date, history_read: str | None, month_reread_on: str | None, zone: str) -> list[date]:
    """The days the next read covers, oldest first, always ending today."""
    oldest = month_start(today, HISTORY_MONTHS)
    read_zone, _, read_from = (history_read or "").partition(":")
    if read_zone != zone or not read_from or date.fromisoformat(read_from) > oldest:
        start = oldest
    elif month_reread_on != today.isoformat():
        start = fetch_span(today)[0]
    else:
        start = today - timedelta(days=1)
    return [start + timedelta(days=n) for n in range((today - start).days + 1)]


def ingest(seconds: dict[date, int]) -> None:
    """Store a read of the hours."""
    db.put_days(seconds)


def run_nudges(now: datetime) -> list[int]:
    prefs = db.get_prefs()
    today = now.astimezone(prefs.zone).date()
    good = db.last_good_fetch()
    last_good = datetime.fromisoformat(good["finished_at"]) if good else None
    hours = db.hours(today.replace(day=1) - timedelta(days=120), today)
    made = []
    for n in nudges.evaluate(prefs, hours, now, last_good):
        nid = db.add_nudge(n.key, n.level, n.title, n.body)
        if nid is not None:
            log.info("nudge %s: %s", n.key, n.title)
            made.append(nid)
    return made


async def fetch_once(headed: bool = False) -> None:
    prefs = db.get_prefs()
    today = datetime.now(timezone.utc).astimezone(prefs.zone).date()
    days = days_to_read(today, db.get_kv(HISTORY_KEY), db.get_kv(MONTH_KEY), prefs.tz)
    fid = db.fetch_started("browser")
    try:
        seconds, tasks = await fetch_days(days, prefs.tz, headed=headed)
    except FetchError as e:
        log.warning("fetch failed: %s", e)
        db.fetch_finished(fid, str(e))
    except Exception as e:
        log.exception("fetch crashed")
        db.fetch_finished(fid, f"{type(e).__name__}: {e}")
    else:
        ingest(seconds)
        db.put_tasks(days[0], days[-1], tasks)
        if days[0] <= month_start(today, HISTORY_MONTHS):
            db.set_kv(HISTORY_KEY, f"{prefs.tz}:{days[0]}")
            log.info("history read from %s, in %s", days[0], prefs.tz)
        if days[0] <= today.replace(day=1):
            db.set_kv(MONTH_KEY, today.isoformat())
        db.fetch_finished(fid)
        log.info("fetched %s..%s (%d days): %.2f h today", days[0], today, len(days), seconds.get(today, 0) / 3600)
    run_nudges(datetime.now(timezone.utc))


def due_every(now: datetime) -> timedelta:
    s, prefs = settings(), db.get_prefs()
    local = now.astimezone(prefs.zone)
    start, end = prefs.nudge_window(local.date())
    busy = start - timedelta(hours=1) <= local <= end + timedelta(hours=1)
    return timedelta(minutes=s.fetch_every_min if busy else s.fetch_idle_every_min)


async def run() -> None:
    db.init()
    log.info("worker started")
    last: datetime | None = None
    while True:
        now = datetime.now(timezone.utc)
        asked = db.take_fetch_request()
        if asked or last is None or now - last >= due_every(now):
            last = now
            await fetch_once()
        await asyncio.sleep(TICK)
