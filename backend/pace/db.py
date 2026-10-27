"""SQLite storage, shared by the web app and the worker.

Two processes write this file: the web app (prefs, sessions, a fetch request,
a CSV upload, a Time Doctor login) and the worker (hours, fetch runs,
nudges). Every write runs inside `BEGIN IMMEDIATE`, as in Foodlog, and WAL
lets the dashboard read while the worker writes.

Several people
--------------
Everything a person sees is theirs alone: every table below except the
login plumbing carries a `user` column (their Kanidm username), and every
function that reads or writes it takes the user first. There is no query
here that returns more than one person's rows, so the API can't show one
person another's hours by forgetting a filter.

Hours are kept per day in seconds and replaced wholesale for every day a
fetch covers: Time Doctor is the source of truth, and a day it later
corrects (manual time, a deleted stretch) must follow.
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
    user        TEXT NOT NULL,
    day         TEXT NOT NULL,            -- YYYY-MM-DD, in the person's zone
    seconds     INTEGER NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (user, day)
);

-- Time per task per day: what splits the hours into meetings and productive
-- work. Replaced wholesale for every range a fetch covers, like days.
CREATE TABLE IF NOT EXISTS task_time (
    user        TEXT NOT NULL,
    day         TEXT NOT NULL,
    task_id     TEXT NOT NULL,
    task        TEXT NOT NULL,
    project     TEXT NOT NULL,
    seconds     INTEGER NOT NULL,
    PRIMARY KEY (user, day, task_id)
);

CREATE TABLE IF NOT EXISTS fetches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user        TEXT NOT NULL,
    source      TEXT NOT NULL,            -- 'browser' or 'upload'
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    ok          INTEGER,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS fetches_user ON fetches(user, id);

-- Nudges are made once and read by the phone in id order. `key` makes each
-- one at-most-once per person: "evening:2026-10-27" can't be sent twice,
-- however many fetches run that evening.
CREATE TABLE IF NOT EXISTS nudges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user        TEXT NOT NULL,
    key         TEXT NOT NULL,
    level       TEXT NOT NULL,            -- 'info', 'warn' or 'alert'
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (user, key)
);

-- Per person: prefs, the history marks, a fetch request. user '' is global.
CREATE TABLE IF NOT EXISTS kv (
    user        TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (user, key)
);

-- A person's own Time Doctor login, given in settings. The password is
-- encrypted (secrets.py) and never leaves the server again: the API only
-- ever says whether one is set.
CREATE TABLE IF NOT EXISTS users (
    username    TEXT PRIMARY KEY,
    td_email    TEXT NOT NULL,
    td_password TEXT NOT NULL,            -- Fernet token
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

# The per-person tables, and their columns before `user` was added.
_SINGLE_USER = {
    "days": "day, seconds, updated_at",
    "task_time": "day, task_id, task, project, seconds",
    "fetches": "id, source, started_at, finished_at, ok, error",
    "nudges": "id, key, level, title, body, created_at",
    "kv": "key, value, updated_at",
}


class MigrationError(RuntimeError):
    pass


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
        conn.execute("BEGIN IMMEDIATE")
        try:
            _migrate_to_users(conn)
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        conn.executescript(SCHEMA)


def _create_table(conn: sqlite3.Connection, table: str) -> None:
    """Run this table's CREATE TABLE from SCHEMA, so the two can't disagree."""
    head = f"CREATE TABLE IF NOT EXISTS {table} ("
    stmt = next(s for s in SCHEMA.split(";") if head in s)
    conn.execute(stmt)


def _migrate_to_users(conn: sqlite3.Connection) -> None:
    """Pace began single-user. Give that person's rows to them, by name.

    The owner is PACE_OWNER, or else the one username that has ever signed
    in. With neither (several people signed in, or nobody) the data can't
    be placed safely, and the app refuses to start rather than guess.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(days)")}
    if not cols or "user" in cols:
        return
    has_rows = any(conn.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone() for t in _SINGLE_USER)
    owner = settings().owner
    if not owner:
        names = [r[0] for r in conn.execute("SELECT DISTINCT username FROM sessions")]
        owner = names[0] if len(names) == 1 else ""
    if has_rows and not owner:
        raise MigrationError("Pace's data is from before it had several users. Set PACE_OWNER to the "
                             "Kanidm username it belongs to, then start again.")
    for table, columns in _SINGLE_USER.items():
        conn.execute(f"ALTER TABLE {table} RENAME TO {table}_single")
        _create_table(conn, table)
        conn.execute(f"INSERT INTO {table} (user, {columns}) SELECT ?, {columns} FROM {table}_single", (owner,))
        conn.execute(f"DROP TABLE {table}_single")
    if owner:
        # Remembered, so the env Time Doctor login keeps working for them
        # without PACE_OWNER being set (owner() below).
        conn.execute("INSERT OR REPLACE INTO kv (user, key, value, updated_at) VALUES ('', 'owner', ?, ?)",
                     (owner, now_iso()))


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

def get_kv(user: str, key: str) -> str | None:
    rows = _read("SELECT value FROM kv WHERE user = ? AND key = ?", (user, key))
    return rows[0]["value"] if rows else None


def set_kv(user: str, key: str, value: str) -> None:
    with write_tx() as conn:
        conn.execute(
            "INSERT INTO kv (user, key, value, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (user, key, value, now_iso()),
        )


def get_prefs(user: str) -> Prefs:
    raw = get_kv(user, "prefs")
    return Prefs.model_validate_json(raw) if raw else Prefs()


def put_prefs(user: str, p: Prefs) -> None:
    set_kv(user, "prefs", p.model_dump_json())


def request_fetch(user: str) -> None:
    """Ask the worker for a fetch now. It looks every 30 seconds."""
    set_kv(user, "fetch_requested", now_iso())


def take_fetch_request(user: str) -> bool:
    with write_tx() as conn:
        n = conn.execute("DELETE FROM kv WHERE user = ? AND key = 'fetch_requested'", (user,)).rowcount
    return n > 0


def fetch_requested(user: str) -> bool:
    return get_kv(user, "fetch_requested") is not None


# --- people and their Time Doctor logins ----------------------------------------

def owner() -> str:
    """Whose the env Time Doctor login is: PACE_OWNER, or whoever the single-user data went to."""
    return settings().owner or get_kv("", "owner") or ""


def put_td_login(user: str, email: str, password_token: str) -> None:
    with write_tx() as conn:
        conn.execute(
            "INSERT INTO users (username, td_email, td_password, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(username) DO UPDATE SET td_email = excluded.td_email, "
            "td_password = excluded.td_password, updated_at = excluded.updated_at",
            (user, email, password_token, now_iso()),
        )


def get_td_login(user: str) -> tuple[str, str] | None:
    """(email, encrypted password), or None."""
    rows = _read("SELECT td_email, td_password FROM users WHERE username = ?", (user,))
    return (rows[0]["td_email"], rows[0]["td_password"]) if rows else None


def drop_td_login(user: str) -> None:
    with write_tx() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (user,))


def td_users() -> list[str]:
    """Everyone who has given a Time Doctor login."""
    return [r["username"] for r in _read("SELECT username FROM users ORDER BY username")]


# --- hours ---------------------------------------------------------------------

def put_days(user: str, seconds: dict[date, int]) -> None:
    """Replace the given days. A day the report covered with no time is passed as 0."""
    stamp = now_iso()
    with write_tx() as conn:
        conn.executemany(
            "INSERT INTO days (user, day, seconds, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user, day) DO UPDATE SET seconds = excluded.seconds, updated_at = excluded.updated_at",
            [(user, d.isoformat(), int(s), stamp) for d, s in seconds.items()],
        )


def hours(user: str, start: date, end: date) -> dict[date, float]:
    rows = _read("SELECT day, seconds FROM days WHERE user = ? AND day BETWEEN ? AND ?",
                 (user, start.isoformat(), end.isoformat()))
    return {date.fromisoformat(r["day"]): r["seconds"] / 3600 for r in rows}


TaskRow = tuple[date, str, str, str, int]  # day, task_id, task, project, seconds


def put_tasks(user: str, start: date, end: date, rows: list[TaskRow]) -> None:
    """Replace start..end's task time: a task gone from the report goes from here too."""
    with write_tx() as conn:
        conn.execute("DELETE FROM task_time WHERE user = ? AND day BETWEEN ? AND ?",
                     (user, start.isoformat(), end.isoformat()))
        conn.executemany(
            "INSERT INTO task_time (user, day, task_id, task, project, seconds) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user, day, task_id) DO UPDATE SET seconds = seconds + excluded.seconds",
            [(user, d.isoformat(), tid, task, project, int(s)) for d, tid, task, project, s in rows],
        )


def tasks(user: str, start: date, end: date) -> list[tuple[date, str, str, int]]:
    """(day, task, project, seconds) for start..end."""
    rows = _read("SELECT day, task, project, seconds FROM task_time WHERE user = ? AND day BETWEEN ? AND ?",
                 (user, start.isoformat(), end.isoformat()))
    return [(date.fromisoformat(r["day"]), r["task"], r["project"], r["seconds"]) for r in rows]


# --- fetch runs ----------------------------------------------------------------

def fetch_started(user: str, source: str) -> int:
    with write_tx() as conn:
        conn.execute("DELETE FROM fetches WHERE started_at < ?",
                     ((datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),))
        return conn.execute("INSERT INTO fetches (user, source, started_at) VALUES (?, ?, ?)",
                            (user, source, now_iso())).lastrowid


def fetch_finished(fetch_id: int, error: str | None = None) -> None:
    with write_tx() as conn:
        conn.execute("UPDATE fetches SET finished_at = ?, ok = ?, error = ? WHERE id = ?",
                     (now_iso(), 0 if error else 1, (error or None) and error[:500], fetch_id))


def last_fetch(user: str) -> dict | None:
    rows = _read("SELECT * FROM fetches WHERE user = ? AND finished_at IS NOT NULL ORDER BY id DESC LIMIT 1", (user,))
    return dict(rows[0]) if rows else None


def last_good_fetch(user: str) -> dict | None:
    rows = _read("SELECT * FROM fetches WHERE user = ? AND ok = 1 ORDER BY id DESC LIMIT 1", (user,))
    return dict(rows[0]) if rows else None


def failures_since_good(user: str) -> int:
    good = last_good_fetch(user)
    rows = _read("SELECT COUNT(*) AS n FROM fetches WHERE user = ? AND ok = 0 AND id > ?",
                 (user, good["id"] if good else 0))
    return rows[0]["n"]


def clear_fetches(user: str) -> None:
    with write_tx() as conn:
        conn.execute("DELETE FROM fetches WHERE user = ?", (user,))


# --- nudges --------------------------------------------------------------------

def add_nudge(user: str, key: str, level: str, title: str, body: str) -> int | None:
    """Store a nudge unless this person has one with this key. Returns its id, or None."""
    with write_tx() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO nudges (user, key, level, title, body, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user, key, level, title, body, now_iso()),
        )
        return cur.lastrowid if cur.rowcount else None


def nudges_after(user: str, after: int, limit: int = 20) -> list[dict]:
    rows = _read("SELECT id, key, level, title, body, created_at FROM nudges "
                 "WHERE user = ? AND id > ? ORDER BY id LIMIT ?", (user, after, limit))
    return [dict(r) for r in rows]


def latest_nudge_id(user: str) -> int:
    return _read("SELECT COALESCE(MAX(id), 0) AS n FROM nudges WHERE user = ?", (user,))[0]["n"]


def recent_nudges(user: str, limit: int = 10) -> list[dict]:
    rows = _read("SELECT id, key, level, title, body, created_at FROM nudges "
                 "WHERE user = ? ORDER BY id DESC LIMIT ?", (user, limit))
    return [dict(r) for r in rows]


def drop_old_nudges(user: str, before: datetime) -> None:
    with write_tx() as conn:
        conn.execute("DELETE FROM nudges WHERE user = ? AND created_at < ?", (user, before.isoformat()))


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
