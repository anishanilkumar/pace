"""When to nudge, and what to say. Pure: the worker stores what this returns.

Each nudge has a key that names its occasion ("evening:2026-10-27"), and the
database keeps a key once, so running these rules after every fetch sends each
nudge at most once however often the worker runs.

Hours are flexible, so nothing here assumes when work happens. The rules only
need to know when a notification is welcome (N = nudge_from..nudge_until) and
whether today is a working day:

=========  ====================================  =================================
key        when, inside N                        if
=========  ====================================  =================================
month      first 2 h                             finished days are behind the plan,
                                                 or the target is out of reach
start      from the middle                       under 15 min tracked today
evening    last 3 h                              at least 30 min of quota left
done       any time                              today's quota met
target     any time                              the month's target met (once)
stale      any time, working days                no good read of Time Doctor for 3 h
=========  ====================================  =================================

When the hours are stale only the stale nudge goes out: the others would
quote numbers that may be wrong ("the display never lies"). Nothing at all
is sent outside N.

Copy is terse and plain, in the house voice: no exclamation marks, no emoji.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .plan import Prefs, month_plan

STALE_AFTER = timedelta(hours=3)


@dataclass(frozen=True)
class Nudge:
    key: str
    level: str  # 'info', 'warn' or 'alert'
    title: str
    body: str


def fmt_h(hours: float) -> str:
    """2.42 -> '2 h 25 min'; 0.75 -> '45 min'. Minutes, never decimals: that's how a clock reads."""
    m = max(0, round(hours * 60))
    if m < 60:
        return f"{m} min"
    return f"{m // 60} h" + (f" {m % 60:02d} min" if m % 60 else "")


def _clock(t: datetime, prefs: Prefs) -> str:
    return t.astimezone(prefs.zone).strftime("%H:%M")


def evaluate(prefs: Prefs, hours: dict[date, float], now: datetime, last_good: datetime | None) -> list[Nudge]:
    if not prefs.nudges:
        return []
    now = now.astimezone(prefs.zone)
    today = now.date()
    start, end = prefs.nudge_window(today)
    if not start <= now <= end:
        return []
    month_name = today.strftime("%B")

    if prefs.is_working(today) and (last_good is None or now - last_good > STALE_AFTER):
        since = f"since {_clock(last_good, prefs)}" if last_good and last_good.astimezone(prefs.zone).date() == today else "today"
        return [Nudge(
            f"stale:{today}", "warn", "Can't read Time Doctor",
            f"No good read {since}. The hours here may be behind; check the server's login.",
        )]

    p = month_plan(prefs, hours, now)
    out: list[Nudge] = []

    if p["status"] == "done":
        out.append(Nudge(f"target:{p['month']}", "info", f"{month_name}'s target reached",
                         f"{fmt_h(p['worked_hours'])} tracked, ₹{p['worked_net']:,.0f} after TDS."))

    quota, done, left = p["today_quota"], p["today_hours"], p["today_left"]
    if quota > 0 and left == 0:
        out.append(Nudge(f"done:{today}", "info", f"Today's {fmt_h(quota)} is done",
                         f"{month_name}: {fmt_h(p['worked_hours'])} of {fmt_h(p['target_hours'])}."))

    if not prefs.is_working(today) or p["status"] == "done":
        return out

    if now < start + timedelta(hours=2):
        if p["status"] == "out_of_reach":
            out.append(Nudge(
                f"month:{today}", "alert", f"{month_name}'s target is out of reach",
                f"It needs {fmt_h(quota)} a day, over your {fmt_h(prefs.max_hours_per_day)} limit. "
                "Lower the target or add working days.",
            ))
        elif p["diff_before_today"] < -0.5:
            out.append(Nudge(
                f"month:{today}", "warn", f"{fmt_h(-p['diff_before_today'])} behind for {month_name}",
                f"Today needs {fmt_h(quota)} to catch up over the {p['working_days_left']} working days left.",
            ))

    if left <= 0:
        return out

    if now >= start + (end - start) / 2 and done < 0.25:
        out.append(Nudge(f"start:{today}", "warn", "Nothing tracked today yet",
                         f"Today needs {fmt_h(quota)}."))

    if now >= end - timedelta(hours=3) and left >= 0.5:
        out.append(Nudge(f"evening:{today}", "warn", f"{fmt_h(left)} left for today",
                         f"Today's quota is {fmt_h(quota)}; {fmt_h(done)} done."))
    return out
