"""The worker: reads Time Doctor on a schedule, then decides on nudges.

One long-running process (systemd unit `pace-worker`), separate from the web
app so a headless Chromium never shares memory or a crash with the API. The
web app asks for an early fetch through the database (db.request_fetch); the
worker looks for that every 30 seconds.

Cadence: every PACE_FETCH_EVERY_MIN (20) from an hour before the working
window to an hour after it on working days, PACE_FETCH_IDLE_EVERY_MIN (120)
otherwise, so a weekend session still shows up without the browser running
all night.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from . import db, nudges
from .config import settings
from .timedoctor import FetchError, fetch_spans

log = logging.getLogger(__name__)
TICK = 30


def fetch_span(today: date) -> tuple[date, date]:
    """This month so far; in the first days of a month, last month too.

    Time Doctor time can be edited after the fact (manual time, a deleted
    stretch). Re-reading last month for a few days lets its final numbers
    settle before it stops being fetched.
    """
    first = today.replace(day=1)
    if today.day <= 3:
        first = (first - timedelta(days=1)).replace(day=1)
    return first, today


# Months of history kept for the dashboard's "last 6 months" and the month
# browser, read once and then left alone (finished months don't change).
HISTORY_MONTHS = 6


def month_start(d: date, back: int) -> date:
    """The first day of the month `back` months before d's."""
    i = d.year * 12 + d.month - 1 - back
    return date(i // 12, i % 12 + 1, 1)


def backfill_spans(today: date, done_from: date | None) -> list[tuple[date, date]]:
    """Whole months to read once, a month per request, before the regular span.

    `done_from` is how far back an earlier backfill already reached; only
    the months before it are read.
    """
    oldest = month_start(today, HISTORY_MONTHS)
    regular_start = fetch_span(today)[0]
    upto = min(regular_start, done_from) if done_from else regular_start
    spans = []
    m = oldest
    while m < upto:
        nxt = month_start(m, -1)
        spans.append((m, min(nxt, upto) - timedelta(days=1)))
        m = nxt
    return spans


def ingest(seconds: dict[date, int], now: datetime, live: bool) -> None:
    """Store a read. A live read also records today's running total for idle detection."""
    db.put_days(seconds)
    today = now.astimezone(db.get_prefs().zone).date()
    if live and today in seconds:
        db.add_sample(now, today, seconds[today])


def run_nudges(now: datetime) -> list[int]:
    prefs = db.get_prefs()
    today = now.astimezone(prefs.zone).date()
    good = db.last_good_fetch()
    last_good = datetime.fromisoformat(good["finished_at"]) if good else None
    hours = db.hours(today.replace(day=1) - timedelta(days=120), today)
    made = []
    for n in nudges.evaluate(prefs, hours, now, db.last_change(today), last_good):
        nid = db.add_nudge(n.key, n.level, n.title, n.body)
        if nid is not None:
            log.info("nudge %s: %s", n.key, n.title)
            made.append(nid)
    return made


async def fetch_once(headed: bool = False) -> None:
    prefs = db.get_prefs()
    now = datetime.now(timezone.utc)
    today = now.astimezone(prefs.zone).date()
    start, end = fetch_span(today)
    done = db.get_kv("backfilled_from")
    history = backfill_spans(today, date.fromisoformat(done) if done else None)
    fid = db.fetch_started("browser")
    try:
        seconds = await fetch_spans(history + [(start, end)], headed=headed)
    except FetchError as e:
        log.warning("fetch failed: %s", e)
        db.fetch_finished(fid, str(e))
    except Exception as e:
        log.exception("fetch crashed")
        db.fetch_finished(fid, f"{type(e).__name__}: {e}")
    else:
        ingest(seconds, datetime.now(timezone.utc), live=True)
        if history:
            db.set_kv("backfilled_from", history[0][0].isoformat())
            log.info("backfilled %s..%s", history[0][0], history[-1][1])
        db.fetch_finished(fid)
        log.info("fetched %s..%s: %.2f h today", start, end, seconds.get(end, 0) / 3600)
    run_nudges(datetime.now(timezone.utc))


def due_every(now: datetime) -> timedelta:
    s, prefs = settings(), db.get_prefs()
    local = now.astimezone(prefs.zone)
    start, end = prefs.window(local.date())
    busy = prefs.is_working(local.date()) and start - timedelta(hours=1) <= local <= end + timedelta(hours=1)
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
