"""The HTTP API the web app and the Android app read. Everything under /api needs a session.

Every endpoint works on the signed-in person's own data, by their Kanidm
username: `require_user` gives it, and every db call takes it. Nobody sees
anyone else's hours, settings, Time Doctor login or nudges.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, ValidationError

from . import auth_web, db, demo, secrets, worker
from .config import settings
from .plan import Prefs, history, month_plan, work_split
from .timedoctor import FetchError, cover, parse_worklog, state_path
from .worker import HISTORY_KEY, HISTORY_MONTHS, MONTH_KEY, month_start

log = logging.getLogger(__name__)

MAX_CSV_BYTES = 2 * 1024 * 1024


def require_user(request: Request) -> str:
    user = auth_web.current_user(request)
    if user is None:
        raise HTTPException(401, "Sign in to continue.")
    # As in Foodlog: a plain cross-site form can't set a custom header, so
    # requiring one on writes closes CSRF (SameSite=Lax covers the rest).
    if request.method not in ("GET", "HEAD") and request.headers.get("x-pace") != "1":
        raise HTTPException(403, "Missing X-Pace header.")
    return user


def _no_demo(what: str) -> None:
    if settings().demo:
        raise HTTPException(403, f"The demo {what}. In your own Pace it's yours to set.")


def _month(param: str | None, today: date) -> tuple[int, int]:
    if not param:
        return today.year, today.month
    try:
        d = date.fromisoformat(param + "-01")
    except ValueError:
        raise HTTPException(400, "month is YYYY-MM.")
    return d.year, d.month


def _fetch_state(user: str) -> dict:
    last, good = db.last_fetch(user), db.last_good_fetch(user)
    return {
        "last_at": last["finished_at"] if last else None,
        "last_ok": bool(last["ok"]) if last else None,
        "last_error": last["error"] if last and not last["ok"] else None,
        "last_good_at": good["finished_at"] if good else None,
        "last_good_source": good["source"] if good else None,
        "failures": db.failures_since_good(user),
        "requested": db.fetch_requested(user),
    }


def _timedoctor(user: str) -> dict:
    """Whether the worker can read Time Doctor for this person. Never the password."""
    stored = db.get_td_login(user)
    if stored:
        return {"connected": True, "email": stored[0], "source": "settings"}
    if settings().demo:
        return {"connected": True, "email": None, "source": "demo"}
    if worker.td_login(user):
        return {"connected": True, "email": settings().td_email, "source": "server"}
    return {"connected": False, "email": None, "source": None}


def summary(user: str, month: str | None = None) -> dict:
    if settings().demo:
        demo.refresh()
    prefs = db.get_prefs(user)
    now = datetime.now(timezone.utc)
    today = now.astimezone(prefs.zone).date()
    year, mon = _month(month, today)
    first = date(year, mon, 1)
    # Back far enough for the streak, which may run into last month.
    hours = db.hours(user, first - timedelta(days=120),
                     today if (year, mon) == (today.year, today.month) else first + timedelta(days=31))
    oldest = month_start(today, HISTORY_MONTHS)
    past = db.hours(user, oldest, today)
    month_end = month_start(first, -1) - timedelta(days=1)
    # Task time only exists from the first read that took it; before that
    # the split is empty, and `tasks_known` says so rather than showing 0 h.
    task_rows = db.tasks(user, min(oldest, first), max(today, month_end))
    return {
        "user": user,
        "plan": month_plan(prefs, hours, now, (year, mon)),
        "work": {**work_split(prefs, task_rows, first, month_end), "tasks_known": bool(task_rows)},
        "history": history(prefs, past, today, HISTORY_MONTHS, task_rows),
        "prefs": prefs.model_dump(),
        "fetch": _fetch_state(user),
        "timedoctor": _timedoctor(user),
        "nudges": db.recent_nudges(user, 5),
        "now": now.isoformat(timespec="seconds"),
        "demo": settings().demo,
    }


class TdLogin(BaseModel):
    email: str = Field(min_length=3, max_length=200, pattern=r"^[^@\s]+@[^@\s]+$")
    password: str = Field(min_length=1, max_length=200)


def create_app() -> FastAPI:
    db.init()
    if settings().demo:
        demo.refresh(force=True)
    app = FastAPI(title="Pace", docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(auth_web.router)

    @app.get("/api/me")
    def me(user: str = Depends(require_user)):
        return {"username": user, "demo": settings().demo}

    @app.get("/api/summary")
    def get_summary(month: str | None = None, user: str = Depends(require_user)):
        return summary(user, month)

    @app.put("/api/prefs")
    async def put_prefs(request: Request, user: str = Depends(require_user)):
        _no_demo("keeps its settings fixed")
        try:
            prefs = Prefs.model_validate(await request.json())
        except ValidationError as e:
            raise HTTPException(422, e.errors(include_url=False, include_context=False))
        db.put_prefs(user, prefs)
        # A new target or day off changes today's quota now, not at the next fetch.
        worker.run_nudges(user, datetime.now(timezone.utc))
        return summary(user)

    @app.put("/api/timedoctor")
    def put_timedoctor(body: TdLogin, user: str = Depends(require_user)):
        """Set this person's Time Doctor login. The password is stored encrypted and never returned."""
        _no_demo("has no Time Doctor login")
        db.put_td_login(user, body.email.strip(), secrets.encrypt(body.password))
        # A different account's days are different: read the history again,
        # and start its browser session afresh.
        db.set_kv(user, HISTORY_KEY, "")
        db.set_kv(user, MONTH_KEY, "")
        _forget_session(user)
        db.request_fetch(user)
        return {"timedoctor": _timedoctor(user)}

    @app.delete("/api/timedoctor")
    def delete_timedoctor(user: str = Depends(require_user)):
        """Remove this person's Time Doctor login and its saved session. Their hours stay."""
        _no_demo("has no Time Doctor login")
        db.drop_td_login(user)
        _forget_session(user)
        return {"timedoctor": _timedoctor(user)}

    @app.post("/api/fetch", status_code=202)
    def ask_fetch(user: str = Depends(require_user)):
        if settings().demo:
            # No Time Doctor behind the demo: a sync brings it up to the minute.
            demo.refresh(force=True)
            return {"requested": False}
        if not worker.td_login(user):
            raise HTTPException(409, "Add your Time Doctor login in settings first.")
        db.request_fetch(user)
        return {"requested": True}

    @app.post("/api/upload")
    async def upload(file: UploadFile, user: str = Depends(require_user)):
        """The manual way in, for when the browser can't get through: the worklog CSV."""
        _no_demo("doesn't take uploads")
        raw = await file.read(MAX_CSV_BYTES + 1)
        if len(raw) > MAX_CSV_BYTES:
            raise HTTPException(413, "That CSV is over 2 MB; a month's worklog is a few KB.")
        prefs = db.get_prefs(user)
        today = datetime.now(timezone.utc).astimezone(prefs.zone).date()
        fid = db.fetch_started(user, "upload")
        try:
            found = parse_worklog(raw.decode("utf-8-sig", errors="replace"), near=today)
        except FetchError as e:
            db.fetch_finished(fid, str(e))
            raise HTTPException(422, str(e))
        # Fill the gaps inside the file's own span, not beyond it.
        worker.ingest(user, cover(found, min(found), max(found)))
        db.fetch_finished(fid)
        worker.run_nudges(user, datetime.now(timezone.utc))
        return {"days": len(found), "from": min(found).isoformat(), "to": max(found).isoformat()}

    @app.get("/api/nudges")
    def get_nudges(after: int = 0, user: str = Depends(require_user)):
        # `latest` lets a newly installed phone start from now instead of
        # replaying every nudge ever made.
        return {"nudges": db.nudges_after(user, after), "latest": db.latest_nudge_id(user)}

    return app


def _forget_session(user: str) -> None:
    try:
        os.remove(state_path(user))
    except FileNotFoundError:
        pass
