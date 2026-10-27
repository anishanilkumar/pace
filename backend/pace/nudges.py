"""When to nudge, and what to say. Pure: the worker stores what this returns.

Each nudge has a key that names its occasion ("evening:2026-10-27"), and the
database keeps a key once, so running these rules after every fetch sends each
nudge at most once however often the worker runs.

The rules, on working days, inside the working window (W = day_start..day_end):

=========  ===================================  ==================================
key        when                                 if
=========  ===================================  ==================================
month      first 2 h of W                       finished days are behind the even plan
start      from W start + 90 min                under 15 min tracked today
idle       inside W, until 30 min before end    today has started, isn't done, and
                                                hasn't grown for 75 min
midday     from the middle of W                 under 45 % of today's quota
evening    from 2 h before W ends, to 1 h after at least 30 min of quota left
done       any time                             today's quota met (once a day)
target     any time                             the month's target met (once)
stale      inside W                             no good read of Time Doctor for 3 h
=========  ===================================  ==================================

When the hours are stale only the stale nudge goes out: the others would
quote numbers that may be wrong ("the display never lies").

Copy is terse and plain, in the house voice: no exclamation marks, no emoji.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .plan import Prefs, month_plan

STALE_AFTER = timedelta(hours=3)
IDLE_AFTER = timedelta(minutes=75)


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


def evaluate(
    prefs: Prefs,
    hours: dict[date, float],
    now: datetime,
    last_change: datetime | None,
    last_good: datetime | None,
) -> list[Nudge]:
    if not prefs.nudges:
        return []
    now = now.astimezone(prefs.zone)
    today = now.date()
    start, end = prefs.window(today)
    in_window = start <= now <= end
    month_name = today.strftime("%B")

    if in_window and prefs.is_working(today) and (last_good is None or now - last_good > STALE_AFTER):
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

    if start <= now < start + timedelta(hours=2):
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

    if now >= start + timedelta(minutes=90) and done < 0.25 and now <= end:
        out.append(Nudge(f"start:{today}", "warn", "Not started yet",
                         f"Today needs {fmt_h(quota)}. The day's window closes at {prefs.day_end}."))

    if (done >= 0.25 and last_change is not None and start <= now <= end - timedelta(minutes=30)
            and now - last_change >= IDLE_AFTER):
        out.append(Nudge(
            f"idle:{today}:{last_change.astimezone(prefs.zone).strftime('%H%M')}", "warn",
            f"Nothing tracked since {_clock(last_change, prefs)}",
            f"{fmt_h(left)} left for today.",
        ))

    if now >= start + (end - start) / 2 and now <= end and done < 0.45 * quota and done >= 0.25:
        out.append(Nudge(f"midday:{today}", "warn", "Behind today",
                         f"{fmt_h(done)} of {fmt_h(quota)} done, and half the day has gone."))

    if end - timedelta(hours=2) <= now <= end + timedelta(hours=1) and left >= 0.5:
        out.append(Nudge(f"evening:{today}", "warn", f"{fmt_h(left)} left for today",
                         f"Today's quota is {fmt_h(quota)}; {fmt_h(done)} done."))
    return out
