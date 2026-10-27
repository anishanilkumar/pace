"""The HTTP API the web app and the Android app read. Everything under /api needs a session."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from pydantic import ValidationError

from . import auth_web, db, worker
from .plan import Prefs, month_plan
from .timedoctor import FetchError, cover, parse_worklog

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


def _month(param: str | None, today: date) -> tuple[int, int]:
    if not param:
        return today.year, today.month
    try:
        d = date.fromisoformat(param + "-01")
    except ValueError:
        raise HTTPException(400, "month is YYYY-MM.")
    return d.year, d.month


def _fetch_state() -> dict:
    last, good = db.last_fetch(), db.last_good_fetch()
    return {
        "last_at": last["finished_at"] if last else None,
        "last_ok": bool(last["ok"]) if last else None,
        "last_error": last["error"] if last and not last["ok"] else None,
        "last_good_at": good["finished_at"] if good else None,
        "last_good_source": good["source"] if good else None,
        "failures": db.failures_since_good(),
        "requested": db.fetch_requested(),
    }


def summary(month: str | None = None) -> dict:
    prefs = db.get_prefs()
    now = datetime.now(timezone.utc)
    today = now.astimezone(prefs.zone).date()
    year, mon = _month(month, today)
    first = date(year, mon, 1)
    # Back far enough for the streak, which may run into last month.
    hours = db.hours(first - timedelta(days=120), today if (year, mon) == (today.year, today.month) else first + timedelta(days=31))
    return {
        "plan": month_plan(prefs, hours, now, (year, mon)),
        "prefs": prefs.model_dump(),
        "fetch": _fetch_state(),
        "nudges": db.recent_nudges(5),
        "now": now.isoformat(timespec="seconds"),
    }


def create_app() -> FastAPI:
    db.init()
    app = FastAPI(title="Pace", docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(auth_web.router)

    @app.get("/api/me")
    def me(user: str = Depends(require_user)):
        return {"username": user}

    @app.get("/api/summary")
    def get_summary(month: str | None = None, user: str = Depends(require_user)):
        return summary(month)

    @app.put("/api/prefs")
    async def put_prefs(request: Request, user: str = Depends(require_user)):
        try:
            prefs = Prefs.model_validate(await request.json())
        except ValidationError as e:
            raise HTTPException(422, e.errors(include_url=False, include_context=False))
        db.put_prefs(prefs)
        # A new target or day off changes today's quota now, not at the next fetch.
        worker.run_nudges(datetime.now(timezone.utc))
        return summary()

    @app.post("/api/fetch", status_code=202)
    def ask_fetch(user: str = Depends(require_user)):
        db.request_fetch()
        return {"requested": True}

    @app.post("/api/upload")
    async def upload(file: UploadFile, user: str = Depends(require_user)):
        """The manual way in, for when the browser can't get through: the worklog CSV."""
        raw = await file.read(MAX_CSV_BYTES + 1)
        if len(raw) > MAX_CSV_BYTES:
            raise HTTPException(413, "That CSV is over 2 MB; a month's worklog is a few KB.")
        prefs = db.get_prefs()
        today = datetime.now(timezone.utc).astimezone(prefs.zone).date()
        fid = db.fetch_started("upload")
        try:
            found = parse_worklog(raw.decode("utf-8-sig", errors="replace"), near=today)
        except FetchError as e:
            db.fetch_finished(fid, str(e))
            raise HTTPException(422, str(e))
        # Fill the gaps inside the file's own span, not beyond it.
        worker.ingest(cover(found, min(found), max(found)), datetime.now(timezone.utc), live=False)
        db.fetch_finished(fid)
        worker.run_nudges(datetime.now(timezone.utc))
        return {"days": len(found), "from": min(found).isoformat(), "to": max(found).isoformat()}

    @app.get("/api/nudges")
    def get_nudges(after: int = 0, user: str = Depends(require_user)):
        # `latest` lets a newly installed phone start from now instead of
        # replaying every nudge ever made.
        return {"nudges": db.nudges_after(after), "latest": db.latest_nudge_id()}

    return app
