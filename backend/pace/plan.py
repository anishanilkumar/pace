"""The arithmetic: from tracked hours and a monthly net target to "where do I stand".

Pure functions, no I/O, so every number the app shows can be tested.

Hours are flexible: there is no working window, only working days. Two views
of the same month answer different questions:

* **The even plan** spreads the target evenly over the month's working days.
  "Am I behind?" compares hours worked with what the plan asked of the days
  already finished. Today isn't owed anything until it's over, and every hour
  worked today counts at once.
* **Today's quota** is what is left of the target, before today, spread over
  the working days left including today. It's what today actually needs, and
  it stays put through the day: it only moves when a day ends, so an evening
  nudge and a morning one quote the same number.

**Meetings and work** split the same hours by task: a task whose name matches
the meeting pattern ("Engineering Meeting", "Call with …") is a meeting,
everything else is productive work.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

# Whole words only: "Implement" must not count as a meeting.
DEFAULT_MEETING_PATTERN = r"\b(meetings?|stand-?ups?|calls?|sync|retro(spective)?|interviews?|1:1|demo)\b"


class Prefs(BaseModel):
    """What the person sets in the app. Stored as one JSON value.

    Fields from older versions (day_start, day_end: the working window that
    flexible hours replaced) are ignored when an old value is read.
    """

    # Placeholders until set in the app's settings.
    hourly_rate_usd: float = Field(25.0, gt=0, le=1000)
    usd_inr: float = Field(85.0, gt=0, le=1000)
    tds_pct: float = Field(10.0, ge=0, le=60)
    target_net_inr: float = Field(100000, ge=0, le=10_000_000)
    # Monday = 0, as Python's weekday().
    work_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    # More than this a day is not a plan, it's a crunch: the target is then
    # shown as out of reach rather than quietly asking for 13 h tomorrow.
    max_hours_per_day: float = Field(10.0, gt=0, le=24)
    leaves: list[str] = Field(default_factory=list, max_length=400)
    # The person's own zone, wherever Time Doctor's company is: a day runs
    # from their midnight to their midnight (the worker asks Time Doctor for
    # days in this zone), and the nudge hours are read in it.
    tz: str = "UTC"
    nudges: bool = True
    # When the phone may be nudged. Not working hours (there are none): the
    # stretch of the day a notification is welcome in.
    nudge_from: str = "09:00"
    nudge_until: str = "21:00"
    # Task names that are meetings; case-insensitive.
    meeting_pattern: str = Field(DEFAULT_MEETING_PATTERN, min_length=1, max_length=300)

    @field_validator("work_days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("work_days are 0 (Monday) to 6 (Sunday)")
        return sorted(set(v))

    @field_validator("nudge_from", "nudge_until")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        time.fromisoformat(v)
        return v

    @field_validator("leaves")
    @classmethod
    def _leaves(cls, v: list[str]) -> list[str]:
        return sorted({date.fromisoformat(d).isoformat() for d in v})

    @field_validator("tz")
    @classmethod
    def _tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown time zone {v!r}")
        return v

    @field_validator("meeting_pattern")
    @classmethod
    def _pattern(cls, v: str) -> str:
        try:
            re.compile(v, re.I)
        except re.error as e:
            raise ValueError(f"meeting pattern is not a valid regular expression: {e}")
        return v

    @model_validator(mode="after")
    def _window(self) -> "Prefs":
        if time.fromisoformat(self.nudge_until) <= time.fromisoformat(self.nudge_from):
            raise ValueError("nudge_until must be after nudge_from")
        return self

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)

    @property
    def net_per_hour(self) -> float:
        return self.hourly_rate_usd * self.usd_inr * (1 - self.tds_pct / 100)

    @property
    def target_hours(self) -> float:
        return self.target_net_inr / self.net_per_hour

    def is_working(self, d: date) -> bool:
        return d.weekday() in self.work_days and d.isoformat() not in self.leaves

    def nudge_window(self, d: date) -> tuple[datetime, datetime]:
        z = self.zone
        return (datetime.combine(d, time.fromisoformat(self.nudge_from), z),
                datetime.combine(d, time.fromisoformat(self.nudge_until), z))

    def is_meeting(self, task: str) -> bool:
        return re.search(self.meeting_pattern, task, re.I) is not None


def month_days(year: int, month: int) -> list[date]:
    return [date(year, month, n) for n in range(1, calendar.monthrange(year, month)[1] + 1)]


def month_plan(prefs: Prefs, hours: dict[date, float], now: datetime, month: tuple[int, int] | None = None) -> dict:
    """Everything the dashboard shows for one month.

    `now` must be aware; it is read in the person's zone. A past month is
    judged as finished; a future one as not begun.
    """
    today = real_today = now.astimezone(prefs.zone).date()
    year, mon = month or (today.year, today.month)
    days = month_days(year, mon)
    working = [d for d in days if prefs.is_working(d)]
    in_month = days[0] <= today <= days[-1]
    if today > days[-1]:
        # A finished month: judged as of the day after its last.
        today = days[-1] + timedelta(days=1)
    elif today < days[0]:
        today = days[0]

    nph = prefs.net_per_hour
    target_h = prefs.target_hours
    worked = sum(hours.get(d, 0.0) for d in days)
    today_h = hours.get(today, 0.0) if in_month else 0.0
    before_today = sum(hours.get(d, 0.0) for d in days if d < today)
    today_working = in_month and prefs.is_working(today)

    finished = [d for d in working if d < today]
    after_today = [d for d in working if d > today]
    plan_per_day = target_h / len(working) if working else 0.0
    expected = plan_per_day * len(finished)

    left_before_today = max(0.0, target_h - before_today)
    slots = len(after_today) + (1 if today_working else 0)
    today_quota = (left_before_today / slots if slots else left_before_today) if today_working else 0.0
    left = max(0.0, target_h - worked)
    per_day_after = left / len(after_today) if after_today else left

    # Projection: the pace of finished working days so far, carried over the
    # days left. Before any day has finished there is nothing to go on, so
    # none is made ("the display never lies").
    avg = before_today / len(finished) if finished else None
    projected_h = (before_today + avg * slots) if avg is not None else None
    if projected_h is not None:
        projected_h = max(projected_h, worked)

    diff = worked - expected
    if worked >= target_h:
        status = "done"
    elif today_quota > prefs.max_hours_per_day or (in_month and not slots and left > 0):
        status = "out_of_reach"
    elif diff < -0.5:
        status = "behind"
    else:
        status = "on_pace"

    return {
        "month": f"{year:04d}-{mon:02d}",
        "today": today.isoformat() if in_month else None,
        "net_per_hour": nph,
        "target_net": prefs.target_net_inr,
        "target_hours": target_h,
        "worked_hours": worked,
        "worked_net": worked * nph,
        "worked_gross": worked * prefs.hourly_rate_usd * prefs.usd_inr,
        "tds": worked * prefs.hourly_rate_usd * prefs.usd_inr * prefs.tds_pct / 100,
        "expected_hours": expected,
        "diff_hours": diff,
        # The same without today's hours: what the morning nudge quotes.
        "diff_before_today": before_today - expected,
        "status": status,
        "plan_per_day": plan_per_day,
        "today_hours": today_h,
        "today_quota": today_quota,
        "today_left": max(0.0, today_quota - today_h),
        "today_working": today_working,
        "per_day_after_today": per_day_after,
        "working_days": len(working),
        "working_days_left": slots,
        "projected_hours": projected_h,
        "projected_net": projected_h * nph if projected_h is not None else None,
        "streak": streak(prefs, hours, min(today, days[-1]), plan_per_day),
        "days": [
            {
                "date": d.isoformat(),
                "hours": hours.get(d, 0.0),
                "working": prefs.is_working(d),
                "leave": d.isoformat() in prefs.leaves,
                "future": d > real_today,
            }
            for d in days
        ],
    }


def work_split(prefs: Prefs, tasks: list[tuple[date, str, str, int]], start: date, end: date) -> dict:
    """Meetings and productive work for start..end, from per-day task time.

    `tasks` rows are (day, task, project, seconds). Returns the two totals,
    meeting hours per day, and the tasks themselves, largest first, each
    marked as a meeting or not so the rule can be checked against them.
    """
    meeting = productive = 0.0
    by_day: dict[str, float] = {}
    per_task: dict[tuple[str, str], float] = {}
    for day, task, project, seconds in tasks:
        if not (start <= day <= end):
            continue
        h = seconds / 3600
        if prefs.is_meeting(task):
            meeting += h
            by_day[day.isoformat()] = by_day.get(day.isoformat(), 0.0) + h
        else:
            productive += h
        per_task[(task, project)] = per_task.get((task, project), 0.0) + h
    total = meeting + productive
    return {
        "meeting_hours": meeting,
        "productive_hours": productive,
        "meeting_share": meeting / total if total else None,
        "meeting_by_day": by_day,
        "tasks": [
            {"task": t, "project": p, "hours": h, "meeting": prefs.is_meeting(t)}
            for (t, p), h in sorted(per_task.items(), key=lambda kv: -kv[1])
        ],
    }


def history(prefs: Prefs, hours: dict[date, float], today: date, months: int,
            tasks: list[tuple[date, str, str, int]] | None = None) -> list[dict]:
    """The last `months` whole months and this one, oldest first.

    Money is at today's rate, exchange rate and TDS: past rates aren't
    recorded, so an older month's rupees are what its hours are worth now.
    The target is today's too: the same for every month.
    """
    out = []
    for back in range(months, -1, -1):
        i = today.year * 12 + today.month - 1 - back
        year, mon = i // 12, i % 12 + 1
        days = month_days(year, mon)
        worked = sum(hours.get(d, 0.0) for d in days)
        split = work_split(prefs, tasks or [], days[0], days[-1])
        out.append({
            "month": f"{year:04d}-{mon:02d}",
            "hours": worked,
            "net": worked * prefs.net_per_hour,
            "target_hours": prefs.target_hours,
            "working_days": sum(1 for d in days if prefs.is_working(d)),
            "days_tracked": sum(1 for d in days if hours.get(d, 0.0) > 0),
            "meeting_hours": split["meeting_hours"],
            "meeting_share": split["meeting_share"],
            "current": back == 0,
        })
    return out


def streak(prefs: Prefs, hours: dict[date, float], today: date, per_day: float) -> int:
    """Working days in a row that met the even plan, back from yesterday.

    Today joins once it has met the plan; until then an unfinished today
    doesn't break the run. Days off are skipped, not counted.
    """
    if per_day <= 0:
        return 0
    met = lambda d: hours.get(d, 0.0) >= per_day * 0.95  # noqa: E731 - rounding of tracked minutes
    n = 1 if prefs.is_working(today) and met(today) else 0
    d = today - timedelta(days=1)
    for _ in range(120):
        if prefs.is_working(d):
            if not met(d):
                break
            n += 1
        d -= timedelta(days=1)
    return n
