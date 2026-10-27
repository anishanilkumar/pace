"""Reading tracked hours out of Time Doctor Classic with a headless browser.

The API (webapi.timedoctor.com) no longer answers, so the worker does what a
person would: open the company's Time Doctor site, sign in, and read the same
data the dashboard's Timesheet panel reads.

What the web app does (seen in its network traffic, October 2026):

* The company site is https://<company>.timedoctor.com (TD_BASE_URL). Its
  /login is a plain form: #email, #password, #signinFormButton.
* The dashboard's Timesheet panel calls
  ``/individual-timesheet?fromDate=YYYY-MM-DD&toDate=YYYY-MM-DD`` and gets
  JSON: ``users -> {id: {timeline: {date: {totaltime, worktime, editedtime,
  mobiletime}}}}``, seconds per day in the company's time zone. The session
  alone picks the user; the other parameters the panel sends change nothing.
* Without a session it answers 302 to /login, or, as XHR,
  ``{"status": "Error", "message": "not authenticated, please login"}``.
* Time per task per day, for the meetings/work split, comes from the Projects
  report (``/v2/index.php?page=projects_report``). The page POSTs a form to
  ``/v2/content/projectsReport/renderProjectsReport.php`` with every project
  id, the user's id, a CSRF token from the page and the dates, and gets JSON:
  ``report -> [project {name, users -> [{tasks -> [{id, name, entries ->
  [{date, workedTime}]}]}]}]``. Rather than rebuild that form, the worker
  opens the page, takes the request it makes on load, and sends it again with
  its own dates. Six months in one request is about 85 KB.

So the browser is only needed to sign in. The request itself goes through the
browser context (page.request), which carries its cookies. The cookies are
kept between runs (storage_state), so a fetch every 20 minutes doesn't mean a
login every 20 minutes: the worker signs in again only when told it isn't.

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

def _state_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings().db_path)), "timedoctor-state.json")


def _on_login_page(url: str) -> bool:
    return url.rstrip("/").endswith("/login") or "/login?" in url


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


def parse_timesheet(data: dict, user_id: str = "") -> dict[date, int]:
    """Seconds per day from /individual-timesheet's JSON.

    `totaltime` is what the dashboard shows: computer, mobile and edited
    (manual) time together, which is what gets paid.
    """
    if data.get("status") == "Error":
        raise _NotSignedIn(data.get("message", ""))
    users = data.get("users")
    if not isinstance(users, dict) or not users:
        raise FetchError("Time Doctor's timesheet came back without a user.")
    if user_id:
        if user_id not in users:
            raise FetchError(f"TD_USER_ID {user_id} is not in Time Doctor's timesheet.")
        user = users[user_id]
    elif len(users) == 1:
        user = next(iter(users.values()))
    else:
        raise FetchError(f"Time Doctor's timesheet has {len(users)} people; set TD_USER_ID to pick one.")
    out = {}
    for day, row in (user.get("timeline") or {}).items():
        out[date.fromisoformat(day)] = int(row.get("totaltime") or 0)
    return out


async def _timesheet(page, start: date, end: date) -> dict[date, int]:
    s = settings()
    r = await page.request.get(
        s.td_base_url + "/individual-timesheet",
        params={"fromDate": start.isoformat(), "toDate": end.isoformat()},
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    )
    if _on_login_page(r.url) or r.status in (401, 403):
        raise _NotSignedIn()
    if not r.ok:
        raise FetchError(f"Time Doctor's timesheet answered HTTP {r.status}.")
    try:
        data = await r.json()
    except Exception:
        # An HTML page where JSON should be: most likely a login page.
        raise _NotSignedIn()
    return parse_timesheet(data, s.td_user_id)


TaskRow = tuple[date, str, str, str, int]  # day, task_id, task, project, seconds
_PROJECTS_PAGE = "/v2/index.php?page=projects_report"
_PROJECTS_RENDER = "/v2/content/projectsReport/renderProjectsReport.php"


def parse_projects_report(data: dict, user_id: str = "") -> list[TaskRow]:
    """Per-day task time from renderProjectsReport's JSON.

    The report is filtered to the signed-in user already; `user_id` only
    matters for an account that sees others (TD_USER_ID).
    """
    if not isinstance(data.get("report"), list):
        raise FetchError("Time Doctor's projects report came back without a report.")
    rows: list[TaskRow] = []
    for project in data["report"]:
        pname = str(project.get("name") or "")
        for user in project.get("users") or []:
            if user_id and str(user.get("id")) != user_id:
                continue
            for task in user.get("tasks") or []:
                tid, tname = str(task.get("id") or ""), str(task.get("name") or "").strip()
                for e in task.get("entries") or []:
                    seconds = int(e.get("workedTime") or 0)
                    if seconds:
                        rows.append((date.fromisoformat(e["date"]), tid, tname, pname, seconds))
    return rows


async def _tasks(page, start: date, end: date) -> list[TaskRow]:
    s = settings()
    async with page.expect_request(lambda r: _PROJECTS_RENDER in r.url, timeout=45_000) as req:
        await page.goto(s.td_base_url + _PROJECTS_PAGE, wait_until="domcontentloaded")
    form = parse_qsl((await req.value).post_data or "", keep_blank_values=True)
    if not any(k == "csrf_token" for k, _ in form):
        raise FetchError("The projects report's request has changed shape (no csrf_token).")
    form = [(k, start.isoformat() if k == "fromDate" else end.isoformat() if k == "toDate" else
             "daily" if k == "reportType" else v) for k, v in form]
    r = await page.request.post(
        s.td_base_url + _PROJECTS_RENDER,
        data=urlencode(form),
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                 "X-Requested-With": "XMLHttpRequest"},
    )
    if not r.ok:
        raise FetchError(f"Time Doctor's projects report answered HTTP {r.status}.")
    return parse_projects_report(await r.json(), s.td_user_id)


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


async def fetch_spans(
    spans: list[tuple[date, date]],
    task_span: tuple[date, date] | None = None,
    headed: bool = False,
) -> tuple[dict[date, int], list[TaskRow] | None]:
    """Several ranges in one browser session (the backfill reads a month at a time).

    Returns seconds per day, every day of every range present (0 where
    nothing was tracked), and, if `task_span` is given, the task time in it.
    The task read is a bonus: if it fails, the hours still count, the error
    is logged, and the tasks come back as None so the old ones are kept.
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
            out: dict[date, int] = {}
            signed_in = False
            for start, end in spans:
                try:
                    found = await _timesheet(page, start, end)
                except _NotSignedIn:
                    if signed_in:
                        raise FetchError("Signed in, but the timesheet still says not signed in.")
                    # The saved cookies have run out (or there were none).
                    await _login(page)
                    signed_in = True
                    try:
                        found = await _timesheet(page, start, end)
                    except _NotSignedIn:
                        raise FetchError("Signed in, but the timesheet still says not signed in.")
                    await context.storage_state(path=state)
                    os.chmod(state, 0o600)
                out.update(cover(found, start, end))
            tasks = None
            if task_span:
                try:
                    tasks = await _tasks(page, *task_span)
                except Exception as e:
                    log.warning("task time not read: %s: %s", type(e).__name__, str(e)[:200])
                    await _save_debug(page, "tasks-failed")
            return out, tasks
        except FetchError:
            await _save_debug(page, "failed")
            raise
        except Exception as e:
            await _save_debug(page, "failed")
            raise FetchError(f"Reading Time Doctor failed: {type(e).__name__}: {str(e)[:200]}") from e
        finally:
            await browser.close()
