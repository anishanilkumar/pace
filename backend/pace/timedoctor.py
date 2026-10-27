"""Reading tracked hours out of Time Doctor Classic with a headless browser.

The API (webapi.timedoctor.com) no longer answers, so the worker does what a
person would: open the company's Time Doctor site, sign in, and read the data
its own reports read.

Which report, and why
---------------------
The timesheet and projects reports bucket time into days by the date each
worklog was stamped with, in the Time Doctor profile's time zone (the
company's, GMT+05:30), and their ``timezone`` parameter doesn't re-bucket.
For someone working from Germany, everything after 19:30 their time lands
on the next India day. The **Timeline** report is different: it lists every
stretch of work with its start and end, converted to the time zone asked
for, for the day asked for in that zone. So the worker reads the Timeline,
one day per request, in the person's own zone, and days begin at their
midnight. (Checked October 2026: the totals over two months match the
timesheet's; only work after 19:30 Berlin moves to the right day.)

What the web app does (seen in its network traffic, October 2026):

* The company site is https://<company>.timedoctor.com (TD_BASE_URL). Its
  /login is a plain form: #email, #password, #signinFormButton.
* ``/timezones`` lists Time Doctor's zones as ``{id, name, timezone (IANA),
  offset}``; the worker looks up the id for the person's IANA zone there.
* The Timeline page (``/v2/index.php?page=timeline_report``) POSTs
  ``userIds, fromDate, toDate, timezone, exportToType=web`` to
  ``/v2/content/reports/timeline_report/getTimeLineReportData.php`` and gets
  ``users -> [{tasks -> [{start_time, end_time, task_name, client_name,
  work_time, work_mode}]}]`` for one day, whatever toDate says. work_mode
  5 is "Not Working"; 0 is computer time, 3 edited (manual) time. The worker
  opens the page, takes the request it makes on load (for the user ids),
  and sends it again per day with its own date and zone.
* Without a session the site answers with a redirect to /login.

So the browser is only needed to sign in. The requests go through the
browser context (page.request), which carries its cookies. The cookies are
kept between runs (storage_state), so a read every 20 minutes doesn't mean a
login every 20 minutes: the worker signs in again only when sent to /login.

The worklog CSV parser below is the manual way in, for when the login can't
get through (a new captcha, a changed form): export from Time Doctor and
upload in the app.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import re
from datetime import date, datetime, timedelta
from urllib.parse import parse_qsl, urlencode

from .config import settings

log = logging.getLogger(__name__)


class FetchError(Exception):
    """A fetch that failed in a way worth showing the person, in plain words."""


# --- CSV ---------------------------------------------------------------------

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
# The worklog export's day columns: "Mon 1-Dec", optionally with a year.
_WIDE_DAY = re.compile(r"^\s*[A-Za-z]{3}\s+(\d{1,2})-([A-Za-z]{3})(?:-(\d{2,4}))?\s*$")
_DURATION = re.compile(r"^\s*(\d+):(\d{1,2})(?::(\d{1,2}))?\s*$")


def _seconds(cell: str) -> int | None:
    """'5.25' (decimal hours) or '5:15[:00]' (h:mm[:ss]) to seconds."""
    cell = (cell or "").strip().strip('"')
    if not cell:
        return None
    m = _DURATION.match(cell)
    if m:
        return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3] or 0)
    try:
        return round(float(cell) * 3600)
    except ValueError:
        return None


def _year_for(day: int, month: int, near: date) -> date:
    """The year is missing from the export's headers: take the one nearest `near`."""
    candidates = []
    for y in (near.year - 1, near.year, near.year + 1):
        try:
            candidates.append(date(y, month, day))
        except ValueError:
            pass
    return min(candidates, key=lambda d: abs((d - near).days))


def _is_total(row: list[str]) -> bool:
    return bool(row) and row[0].strip().lower().startswith("total")


def parse_worklog(text: str, near: date) -> dict[date, int]:
    """Seconds per day from a Time Doctor worklog CSV.

    Two shapes are understood:

    * **wide**, the Classic worklog export: one column per day headed
      "Mon 1-Dec", followed by that day's decimal hours. Rows are summed
      (one per project or user), except a "Total" row, which is used alone
      when it is all there is.
    * **long**: a date column and an hours, time or duration column, one row
      per day or per stretch of work.

    `near` resolves the year the wide headers leave out.
    """
    rows = [r for r in csv.reader(io.StringIO(text.lstrip("﻿"))) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise FetchError("The worklog CSV has no data rows.")
    header = [h.strip() for h in rows[0]]
    data = rows[1:]

    day_cols = [(i, _WIDE_DAY.match(h)) for i, h in enumerate(header)]
    day_cols = [(i, m) for i, m in day_cols if m]
    if day_cols:
        body = [r for r in data if not _is_total(r)] or [r for r in data if _is_total(r)]
        out: dict[date, int] = {}
        for i, m in day_cols:
            month = _MONTHS.get(m[2].lower())
            if not month:
                continue
            d = (date(int(m[3]) + (2000 if len(m[3]) == 2 else 0), month, int(m[1]))
                 if m[3] else _year_for(int(m[1]), month, near))
            # The day's decimal hours sit in the column after it (the day's
            # own cell holds h:mm); use the own cell when there is no such column.
            value_col = i + 1 if i + 1 < len(header) and not _WIDE_DAY.match(header[i + 1]) else i
            total = 0
            for r in body:
                s = _seconds(r[value_col]) if value_col < len(r) else None
                if s is None and i < len(r):
                    s = _seconds(r[i])
                total += s or 0
            out[d] = out.get(d, 0) + total
        if not out:
            raise FetchError("The worklog CSV's day columns couldn't be read as dates.")
        return out

    lower = [h.lower() for h in header]
    date_col = next((i for i, h in enumerate(lower) if h in ("date", "day") or h.startswith("date")), None)
    time_col = next((i for i, h in enumerate(lower)
                     if any(k in h for k in ("decimal", "hours", "duration", "time worked", "total time"))), None)
    if date_col is None or time_col is None:
        raise FetchError("The CSV doesn't look like a Time Doctor worklog: no day columns, "
                         "and no date and hours columns.")
    out = {}
    for r in data:
        if _is_total(r) or max(date_col, time_col) >= len(r):
            continue
        d = _parse_date(r[date_col])
        s = _seconds(r[time_col])
        if d is None or s is None:
            continue
        out[d] = out.get(d, 0) + s
    if not out:
        raise FetchError("The worklog CSV had rows, but none with a date and a time.")
    return out


def _parse_date(cell: str) -> date | None:
    cell = cell.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%b %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(cell, fmt).date()
        except ValueError:
            pass
    return None


def cover(found: dict[date, int], start: date, end: date) -> dict[date, int]:
    """Every day of the range, with 0 where the report had nothing.

    A day the report covers but leaves out had no tracked time; storing 0
    replaces anything older, so a day Time Doctor emptied doesn't linger.
    """
    out = {}
    d = start
    while d <= end:
        out[d] = found.get(d, 0)
        d += timedelta(days=1)
    return out


# --- the browser -----------------------------------------------------------------

TaskRow = tuple[date, str, str, str, int]  # day, task_id, task, project, seconds
_TIMELINE_PAGE = "/v2/index.php?page=timeline_report"
_TIMELINE_DATA = "/v2/content/reports/timeline_report/getTimeLineReportData.php"
NOT_WORKING = "5"


def _state_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings().db_path)), "timedoctor-state.json")


def _on_login_page(url: str) -> bool:
    return url.split("?")[0].rstrip("/").endswith("/login")


async def _login(page) -> None:
    s = settings()
    if not (s.td_email and s.td_password):
        raise FetchError("TD_EMAIL and TD_PASSWORD are not set on the server.")
    await page.goto(s.td_base_url + "/login", wait_until="domcontentloaded")
    await page.fill("#email", s.td_email)
    await page.fill("#password", s.td_password)
    await page.click("#signinFormButton")
    try:
        await page.wait_for_url(lambda u: not _on_login_page(u) and "login_check" not in u, timeout=30_000)
    except Exception:
        raise FetchError("Time Doctor refused the login. Check TD_EMAIL and TD_PASSWORD, "
                         "or whether it now asks for a code.")
    log.info("signed in to Time Doctor")


class _NotSignedIn(Exception):
    pass


def find_timezone_id(data, iana: str) -> str | None:
    """Time Doctor's id for an IANA zone, from /timezones (searched, whatever its nesting)."""
    if isinstance(data, dict):
        if data.get("timezone") == iana and "id" in data:
            return str(data["id"])
        data = list(data.values())
    if isinstance(data, list):
        for item in data:
            found = find_timezone_id(item, iana)
            if found:
                return found
    return None


def parse_timeline(data: dict, day: date) -> tuple[int, list[TaskRow]]:
    """One day's worked seconds and its task time, from getTimeLineReportData's JSON."""
    users = data.get("users")
    if not isinstance(users, list):
        raise FetchError("Time Doctor's timeline came back without users.")
    if len(users) > 1:
        raise FetchError(f"Time Doctor's timeline has {len(users)} people; it should be filtered to one.")
    total = 0
    per_task: dict[tuple[str, str], int] = {}
    for entry in (users[0].get("tasks") if users else None) or []:
        if str(entry.get("work_mode")) == NOT_WORKING:
            continue
        seconds = int(float(entry.get("work_time") or 0))
        if seconds <= 0:
            continue
        task = str(entry.get("task_name") or "").strip() or "No task"
        project = str(entry.get("client_name") or "").strip()
        total += seconds
        per_task[(task, project)] = per_task.get((task, project), 0) + seconds
    rows = [(day, f"{project}/{task}", task, project, sec) for (task, project), sec in per_task.items()]
    return total, rows


async def _timeline_form(page) -> list[tuple[str, str]]:
    """The request the Timeline page makes on load: it carries the user ids."""
    s = settings()
    try:
        async with page.expect_request(lambda r: _TIMELINE_DATA in r.url, timeout=45_000) as req:
            await page.goto(s.td_base_url + _TIMELINE_PAGE, wait_until="domcontentloaded")
    except Exception:
        if _on_login_page(page.url):
            raise _NotSignedIn()
        raise
    form = parse_qsl((await req.value).post_data or "", keep_blank_values=True)
    if not any(k == "userIds" for k, _ in form):
        raise FetchError("The timeline report's request has changed shape (no userIds).")
    return form


async def _timezone_id(page, iana: str) -> str:
    r = await page.request.get(settings().td_base_url + "/timezones", headers={"X-Requested-With": "XMLHttpRequest"})
    tzid = find_timezone_id(await r.json(), iana) if r.ok else None
    if not tzid:
        raise FetchError(f"Time Doctor has no time zone for {iana}; pick a city zone it lists in settings.")
    return tzid


async def _timeline_day(page, form: list[tuple[str, str]], tzid: str, day: date) -> tuple[int, list[TaskRow]]:
    d = day.isoformat()
    body = [(k, d if k in ("fromDate", "toDate") else tzid if k == "timezone" else v) for k, v in form]
    r = await page.request.post(
        settings().td_base_url + _TIMELINE_DATA,
        data=urlencode(body),
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                 "X-Requested-With": "XMLHttpRequest"},
    )
    if _on_login_page(r.url):
        raise _NotSignedIn()
    if not r.ok:
        raise FetchError(f"Time Doctor's timeline answered HTTP {r.status} for {d}.")
    try:
        data = await r.json()
    except Exception:
        raise _NotSignedIn()
    return parse_timeline(data, day)


async def _save_debug(page, what: str) -> None:
    d = settings().debug_dir
    if not d or page is None:
        return
    os.makedirs(d, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        await page.screenshot(path=os.path.join(d, f"{stamp}-{what}.png"), full_page=True)
        with open(os.path.join(d, f"{stamp}-{what}.html"), "w") as f:
            f.write(await page.content())
        log.info("saved %s page to %s", what, d)
    except Exception as e:  # the page may be gone; the original error matters more
        log.warning("could not save debug page: %s", e)


async def fetch_days(days: list[date], iana: str, headed: bool = False) -> tuple[dict[date, int], list[TaskRow]]:
    """Worked seconds and task time for each day, days counted in `iana`.

    One browser session, one request per day. Every day asked for is in the
    result, 0 where nothing was tracked.
    """
    from playwright.async_api import async_playwright

    if not settings().td_base_url:
        raise FetchError("TD_BASE_URL is not set (the company's https://<name>.timedoctor.com).")
    state = _state_path()
    page = None
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not headed)
        try:
            context = await browser.new_context(
                storage_state=state if os.path.exists(state) else None,
                locale="en-US",
            )
            page = await context.new_page()
            try:
                form = await _timeline_form(page)
            except _NotSignedIn:
                # The saved cookies have run out (or there were none).
                await _login(page)
                try:
                    form = await _timeline_form(page)
                except _NotSignedIn:
                    raise FetchError("Signed in, but Time Doctor still sends the timeline to the login page.")
                await context.storage_state(path=state)
                os.chmod(state, 0o600)
            tzid = await _timezone_id(page, iana)
            seconds: dict[date, int] = {}
            tasks: list[TaskRow] = []
            for day in days:
                total, rows = await _timeline_day(page, form, tzid, day)
                seconds[day] = total
                tasks.extend(rows)
            return seconds, tasks
        except _NotSignedIn:
            await _save_debug(page, "failed")
            raise FetchError("Time Doctor's session ended mid-read; the next read signs in again.")
        except FetchError:
            await _save_debug(page, "failed")
            raise
        except Exception as e:
            await _save_debug(page, "failed")
            raise FetchError(f"Reading Time Doctor failed: {type(e).__name__}: {str(e)[:200]}") from e
        finally:
            await browser.close()
