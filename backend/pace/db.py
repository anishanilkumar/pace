"""SQLite storage, shared by the web app and the worker.

Two processes write this file: the web app (prefs, sessions, a fetch request,
a CSV upload) and the worker (hours, fetch runs, nudges). Every write runs
inside `BEGIN IMMEDIATE`, as in Foodlog, and WAL lets the dashboard read
while the worker writes.

Hours are kept per day in seconds, as Time Doctor reports them, and replaced
wholesale for every day a fetch covers: Time Doctor is the source of truth,
and a day it later corrects (manual time, a deleted stretch) must follow.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

from .config import settings
from .plan import Prefs

SCHEMA = """
CREATE TABLE IF NOT EXISTS days (
    day         TEXT PRIMARY KEY,         -- YYYY-MM-DD, in the person's zone
    seconds     INTEGER NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Time per task per day, from Time Doctor's Projects report: what splits the
-- hours into meetings and productive work. Replaced wholesale for every
-- range a fetch covers, like days.
CREATE TABLE IF NOT EXISTS task_time (
    day         TEXT NOT NULL,
    task_id     TEXT NOT NULL,
    task        TEXT NOT NULL,
    project     TEXT NOT NULL,
    seconds     INTEGER NOT NULL,
    PRIMARY KEY (day, task_id)
);

CREATE TABLE IF NOT EXISTS fetches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,            -- 'browser' or 'upload'
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    ok          INTEGER,
    error       TEXT
);

-- Nudges are made once and read by the phone in id order. `key` makes each
-- one at-most-once: "evening:2026-10-27" can't be sent twice, however many
-- fetches run that evening.
CREATE TABLE IF NOT EXISTS nudges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT NOT NULL UNIQUE,
    level       TEXT NOT NULL,            -- 'info', 'warn' or 'alert'
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    username    TEXT NOT NULL,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS login_states (
    state         TEXT PRIMARY KEY,
    verifier      TEXT NOT NULL,
    nonce         TEXT NOT NULL,
    app_challenge TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL
);

-- The Android app's sign-in handoff, as in Foodlog (auth_web.py).
CREATE TABLE IF NOT EXISTS app_handoffs (
    code_hash   TEXT PRIMARY KEY,
    username    TEXT NOT NULL,
    challenge   TEXT NOT NULL,
    created_at  REAL NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or settings().db_path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init(path: str | None = None) -> None:
    with closing(connect(path)) as conn:
        conn.executescript(SCHEMA)


@contextmanager
def closing(conn: sqlite3.Connection):
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def write_tx(path: str | None = None):
    with closing(connect(path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")


def _read(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    with closing(connect()) as conn:
        return conn.execute(sql, args).fetchall()


# --- prefs and flags -----------------------------------------------------------

def get_kv(key: str) -> str | None:
    rows = _read("SELECT value FROM kv WHERE key = ?", (key,))
    return rows[0]["value"] if rows else None


def set_kv(key: str, value: str) -> None:
    with write_tx() as conn:
        conn.execute(
            "INSERT INTO kv (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, now_iso()),
        )


def get_prefs() -> Prefs:
    raw = get_kv("prefs")
    return Prefs.model_validate_json(raw) if raw else Prefs()


def put_prefs(p: Prefs) -> None:
    set_kv("prefs", p.model_dump_json())


def request_fetch() -> None:
    """Ask the worker for a fetch now. It looks every 30 seconds."""
    set_kv("fetch_requested", now_iso())


def take_fetch_request() -> bool:
    with write_tx() as conn:
        n = conn.execute("DELETE FROM kv WHERE key = 'fetch_requested'").rowcount
    return n > 0


def fetch_requested() -> bool:
    return get_kv("fetch_requested") is not None


# --- hours ---------------------------------------------------------------------

def put_days(seconds: dict[date, int]) -> None:
    """Replace the given days. A day the report covered with no time is passed as 0."""
    stamp = now_iso()
    with write_tx() as conn:
        conn.executemany(
            "INSERT INTO days (day, seconds, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(day) DO UPDATE SET seconds = excluded.seconds, updated_at = excluded.updated_at",
            [(d.isoformat(), int(s), stamp) for d, s in seconds.items()],
        )


def hours(start: date, end: date) -> dict[date, float]:
    rows = _read("SELECT day, seconds FROM days WHERE day BETWEEN ? AND ?", (start.isoformat(), end.isoformat()))
    return {date.fromisoformat(r["day"]): r["seconds"] / 3600 for r in rows}


TaskRow = tuple[date, str, str, str, int]  # day, task_id, task, project, seconds


def put_tasks(start: date, end: date, rows: list[TaskRow]) -> None:
    """Replace start..end's task time: a task gone from the report goes from here too."""
    with write_tx() as conn:
        conn.execute("DELETE FROM task_time WHERE day BETWEEN ? AND ?", (start.isoformat(), end.isoformat()))
        conn.executemany(
            "INSERT INTO task_time (day, task_id, task, project, seconds) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(day, task_id) DO UPDATE SET seconds = seconds + excluded.seconds",
            [(d.isoformat(), tid, task, project, int(s)) for d, tid, task, project, s in rows],
        )


def tasks(start: date, end: date) -> list[tuple[date, str, str, int]]:
    """(day, task, project, seconds) for start..end."""
    rows = _read("SELECT day, task, project, seconds FROM task_time WHERE day BETWEEN ? AND ?",
                 (start.isoformat(), end.isoformat()))
    return [(date.fromisoformat(r["day"]), r["task"], r["project"], r["seconds"]) for r in rows]


# --- fetch runs ----------------------------------------------------------------

def fetch_started(source: str) -> int:
    with write_tx() as conn:
        conn.execute("DELETE FROM fetches WHERE started_at < ?",
                     ((datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),))
        return conn.execute("INSERT INTO fetches (source, started_at) VALUES (?, ?)", (source, now_iso())).lastrowid


def fetch_finished(fetch_id: int, error: str | None = None) -> None:
    with write_tx() as conn:
        conn.execute("UPDATE fetches SET finished_at = ?, ok = ?, error = ? WHERE id = ?",
                     (now_iso(), 0 if error else 1, (error or None) and error[:500], fetch_id))


def last_fetch() -> dict | None:
    rows = _read("SELECT * FROM fetches WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1")
    return dict(rows[0]) if rows else None


def last_good_fetch() -> dict | None:
    rows = _read("SELECT * FROM fetches WHERE ok = 1 ORDER BY id DESC LIMIT 1")
    return dict(rows[0]) if rows else None


def failures_since_good() -> int:
    good = last_good_fetch()
    rows = _read("SELECT COUNT(*) AS n FROM fetches WHERE ok = 0 AND id > ?", (good["id"] if good else 0,))
    return rows[0]["n"]


# --- nudges --------------------------------------------------------------------

def add_nudge(key: str, level: str, title: str, body: str) -> int | None:
    """Store a nudge unless one with this key exists. Returns its id, or None."""
    with write_tx() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO nudges (key, level, title, body, created_at) VALUES (?, ?, ?, ?, ?)",
            (key, level, title, body, now_iso()),
        )
        return cur.lastrowid if cur.rowcount else None


def has_nudge(key: str) -> bool:
    return bool(_read("SELECT 1 FROM nudges WHERE key = ?", (key,)))


def nudges_after(after: int, limit: int = 20) -> list[dict]:
    rows = _read("SELECT id, key, level, title, body, created_at FROM nudges WHERE id > ? ORDER BY id LIMIT ?",
                 (after, limit))
    return [dict(r) for r in rows]


def latest_nudge_id() -> int:
    return _read("SELECT COALESCE(MAX(id), 0) AS n FROM nudges")[0]["n"]


def recent_nudges(limit: int = 10) -> list[dict]:
    rows = _read("SELECT id, key, level, title, body, created_at FROM nudges ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


# --- sessions (as Foodlog) -------------------------------------------------------

def put_login_state(state: str, verifier: str, nonce: str, app_challenge: str = "") -> None:
    with write_tx() as conn:
        # Abandoned logins are swept here rather than by a timer.
        conn.execute("DELETE FROM login_states WHERE created_at < ?", (time.time() - 600,))
        conn.execute(
            "INSERT INTO login_states (state, verifier, nonce, created_at, app_challenge) VALUES (?, ?, ?, ?, ?)",
            (state, verifier, nonce, time.time(), app_challenge),
        )


def pop_login_state(state: str) -> dict | None:
    with write_tx() as conn:
        r = conn.execute(
            "SELECT * FROM login_states WHERE state = ? AND created_at >= ?",
            (state, time.time() - 600),
        ).fetchone()
        conn.execute("DELETE FROM login_states WHERE state = ?", (state,))
    return dict(r) if r else None


HANDOFF_SECONDS = 120


def put_app_handoff(code_hash: str, username: str, challenge: str) -> None:
    with write_tx() as conn:
        conn.execute("DELETE FROM app_handoffs WHERE created_at < ?", (time.time() - HANDOFF_SECONDS,))
        conn.execute(
            "INSERT INTO app_handoffs (code_hash, username, challenge, created_at) VALUES (?, ?, ?, ?)",
            (code_hash, username, challenge, time.time()),
        )


def pop_app_handoff(code_hash: str) -> dict | None:
    """Single use: the row is gone after the first attempt, right or wrong."""
    with write_tx() as conn:
        r = conn.execute(
            "SELECT * FROM app_handoffs WHERE code_hash = ? AND created_at >= ?",
            (code_hash, time.time() - HANDOFF_SECONDS),
        ).fetchone()
        conn.execute("DELETE FROM app_handoffs WHERE code_hash = ?", (code_hash,))
    return dict(r) if r else None


def create_session(token_hash: str, username: str, days: int) -> None:
    now = time.time()
    with write_tx() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        conn.execute(
            "INSERT INTO sessions (token_hash, username, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token_hash, username, now, now + days * 86400),
        )


def session_user(token_hash: str, days: int) -> str | None:
    """Look a session up, sliding its expiry forward at most once a day."""
    now = time.time()
    with closing(connect()) as conn:
        r = conn.execute(
            "SELECT username, expires_at FROM sessions WHERE token_hash = ?", (token_hash,)
        ).fetchone()
        if r is None or r["expires_at"] < now:
            return None
        if r["expires_at"] < now + (days - 1) * 86400:
            conn.execute(
                "UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
                (now + days * 86400, token_hash),
            )
        return r["username"]


def drop_session(token_hash: str) -> None:
    with write_tx() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

