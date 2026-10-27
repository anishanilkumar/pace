from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from pace import db, worker
from pace.web import create_app

H = {"X-Pace": "1"}
# conftest signs every request in as this dev user.
ME = "tester"


def client() -> TestClient:
    return TestClient(create_app())


def as_user(monkeypatch, name: str) -> TestClient:
    """A client signed in as `name` through a real session, the way Kanidm logins end up."""
    import hashlib

    from pace import config

    monkeypatch.delenv("PACE_DEV_USER", raising=False)
    config.settings.cache_clear()
    token = f"token-for-{name}"
    db.create_session(hashlib.sha256(token.encode()).hexdigest(), name, 90)
    return TestClient(create_app(), headers={"Authorization": f"Bearer {token}"})


def test_summary_defaults():
    r = client().get("/api/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["prefs"]["target_net_inr"] == 100000
    assert body["fetch"]["last_good_at"] is None
    assert len(body["plan"]["days"]) >= 28


def test_writes_need_the_csrf_header():
    c = client()
    assert c.post("/api/fetch").status_code == 403
    # No Time Doctor login yet: nothing to sync with.
    assert c.post("/api/fetch", headers=H).status_code == 409
    assert c.put("/api/timedoctor", json={"email": "me@example.com", "password": "pw"}, headers=H).status_code == 200
    assert db.take_fetch_request(ME) is True   # saving a login asks for a read at once
    assert c.post("/api/fetch", headers=H).status_code == 202
    assert db.take_fetch_request(ME) is True
    assert db.take_fetch_request(ME) is False


def test_prefs_round_trip_and_validation():
    c = client()
    prefs = c.get("/api/summary").json()["prefs"]
    prefs["target_net_inr"] = 200000
    r = c.put("/api/prefs", json=prefs, headers=H)
    assert r.status_code == 200
    assert r.json()["prefs"]["target_net_inr"] == 200000
    prefs["nudge_until"] = "08:00"
    assert c.put("/api/prefs", json=prefs, headers=H).status_code == 422


def test_upload_csv():
    text = '"Name","Mon 1-Dec","","Tue 2-Dec",""\n"Sample","2:00","2","1:00","1"\n'
    r = client().post("/api/upload", files={"file": ("w.csv", text, "text/csv")}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["days"] == 2
    assert db.last_good_fetch(ME)["source"] == "upload"
    r = client().post("/api/upload", files={"file": ("w.csv", "x,y\n1,2\n", "text/csv")}, headers=H)
    assert r.status_code == 422


def test_nudge_feed_is_at_most_once():
    assert db.add_nudge(ME, "evening:2026-10-27", "warn", "t", "b") is not None
    assert db.add_nudge(ME, "evening:2026-10-27", "warn", "t", "b") is None
    r = client().get("/api/nudges?after=0").json()
    assert [n["key"] for n in r["nudges"]] == ["evening:2026-10-27"]
    assert client().get(f"/api/nudges?after={r['latest']}").json()["nudges"] == []


def test_task_time_is_replaced_per_range():
    d = date(2026, 10, 27)
    db.put_tasks(ME, d, d, [(d, "1", "Engineering Meeting", "TAI", 3600), (d, "2", "Build", "TAI", 1800)])
    db.put_tasks(ME, d, d, [(d, "2", "Build", "TAI", 2400)])
    assert db.tasks(ME, d, d) == [(d, "Build", "TAI", 2400)]


def test_reads_history_once_then_the_month_daily_then_two_days():
    today = date(2026, 10, 27)
    z = "Europe/Berlin"
    first = worker.days_to_read(today, None, None, z)
    assert first[0] == date(2026, 4, 1) and first[-1] == today
    month = worker.days_to_read(today, f"{z}:2026-04-01", None, z)
    assert month[0] == date(2026, 10, 1)
    assert worker.days_to_read(today, f"{z}:2026-04-01", "2026-10-27", z) == [date(2026, 10, 26), today]
    # A new month doesn't send the whole history round again...
    assert worker.days_to_read(date(2026, 11, 20), f"{z}:2026-04-01", "2026-11-20", z)[0] == date(2026, 11, 19)
    # ...but a new time zone does: the days split differently.
    assert worker.days_to_read(today, "Asia/Kolkata:2026-04-01", "2026-10-27", z)[0] == date(2026, 4, 1)
    # Early in a month, the daily re-read covers last month too.
    assert worker.days_to_read(date(2026, 11, 2), f"{z}:2026-04-01", None, z)[0] == date(2026, 10, 1)


def test_summary_has_history():
    today = datetime.now(db.get_prefs(ME).zone).date()
    worker.ingest(ME, {today.replace(day=1): 7200})
    db.put_tasks(ME, today.replace(day=1), today, [(today.replace(day=1), "1", "Engineering Meeting", "TAI", 1800)])
    h = client().get("/api/summary").json()["history"]
    assert len(h) == 7
    assert h[-1]["current"] is True
    assert h[-1]["hours"] >= 2
    assert h[-1]["meeting_hours"] == 0.5
    work = client().get("/api/summary").json()["work"]
    assert work["tasks_known"] is True
    assert work["tasks"][0]["meeting"] is True


def test_fetch_span_rereads_last_month_early_on():
    assert worker.fetch_span(date(2026, 11, 2)) == (date(2026, 10, 1), date(2026, 11, 2))
    assert worker.fetch_span(date(2026, 11, 4)) == (date(2026, 11, 1), date(2026, 11, 4))


def demo_client(monkeypatch) -> TestClient:
    from pace import config

    monkeypatch.setenv("PACE_DEMO", "1")
    monkeypatch.delenv("PACE_DEV_USER", raising=False)
    config.settings.cache_clear()
    return TestClient(create_app())


def test_demo_has_a_lived_in_history_and_stores_nothing(monkeypatch):
    c = demo_client(monkeypatch)
    s = c.get("/api/summary").json()
    assert s["demo"] is True
    assert c.get("/api/me").json() == {"username": "demo", "demo": True}
    assert s["prefs"]["target_net_inr"] == 200000
    assert len(s["history"]) == 7
    assert all(m["hours"] > 40 for m in s["history"][:-1])
    assert s["work"]["tasks_known"] is True and s["work"]["meeting_hours"] > 0
    assert s["fetch"]["last_ok"] is True
    # Settings and uploads are refused; Sync works and stores nothing new.
    assert c.put("/api/prefs", json=s["prefs"], headers=H).status_code == 403
    r = c.post("/api/upload", files={"file": ("w.csv", "a,b\n1,2\n", "text/csv")}, headers=H)
    assert r.status_code == 403
    assert c.post("/api/fetch", headers=H).json() == {"requested": False}
    assert db.fetch_requested("demo") is False


def test_demo_days_are_stable_and_today_follows_the_clock():
    from datetime import date, datetime, timezone

    from pace import demo

    p = demo.prefs(date(2026, 10, 27))
    assert demo.plan_day(date(2026, 9, 15), p) == demo.plan_day(date(2026, 9, 15), p)
    assert demo.plan_day(date(2026, 10, 16), p) == []  # third Friday: leave
    total = 4 * 3600
    t = lambda h, m: datetime(2026, 10, 27, h, m, tzinfo=timezone.utc)  # noqa: E731 - Berlin is UTC+1
    assert demo.worked_so_far(t(8, 0), total) == 0          # 09:00 Berlin
    assert demo.worked_so_far(t(10, 15), total) == 2 * 3600  # 11:15: two hours in
    assert demo.worked_so_far(t(12, 15), total) == 3.5 * 3600  # 13:15: lunch since 12:45
    assert demo.worked_so_far(t(20, 0), total) == total


def test_demo_refuses_real_secrets(monkeypatch):
    import pytest

    from pace import config

    monkeypatch.setenv("PACE_DEMO", "1")
    monkeypatch.setenv("TD_PASSWORD", "x")
    config.settings.cache_clear()
    with pytest.raises(RuntimeError):
        config.settings()


# --- several people ----------------------------------------------------------------

def test_nobody_sees_anyone_elses_numbers(monkeypatch):
    alice, bob = as_user(monkeypatch, "alice"), as_user(monkeypatch, "bob")
    today = datetime.now(db.get_prefs("alice").zone).date()
    worker.ingest("alice", {today: 5 * 3600})
    db.put_tasks("alice", today, today, [(today, "1", "Secret project", "X", 5 * 3600)])
    db.add_nudge("alice", "evening:x", "warn", "Alice's nudge", "b")
    a = alice.get("/api/summary").json()
    b = bob.get("/api/summary").json()
    assert a["user"] == "alice" and b["user"] == "bob"
    assert a["plan"]["today_hours"] == 5 and b["plan"]["today_hours"] == 0
    assert a["work"]["tasks"] and b["work"]["tasks"] == []
    assert alice.get("/api/nudges").json()["nudges"] and bob.get("/api/nudges").json()["nudges"] == []
    # Settings are per person too.
    prefs = b["prefs"] | {"target_net_inr": 123000}
    assert bob.put("/api/prefs", json=prefs, headers=H).status_code == 200
    assert alice.get("/api/summary").json()["prefs"]["target_net_inr"] == 100000


def test_time_doctor_password_is_encrypted_and_never_returned(monkeypatch):
    alice = as_user(monkeypatch, "alice")
    r = alice.put("/api/timedoctor", json={"email": "alice@example.com", "password": "hunter2"}, headers=H)
    assert r.json() == {"timedoctor": {"connected": True, "email": "alice@example.com", "source": "settings"}}
    stored = db.get_td_login("alice")
    assert stored[0] == "alice@example.com" and "hunter2" not in stored[1]
    assert worker.td_login("alice") == ("alice@example.com", "hunter2")
    s = alice.get("/api/summary").text
    assert "hunter2" not in s and stored[1] not in s
    assert worker.readers() == ["alice"]
    # Removing it stops the reads; the hours already read stay.
    assert alice.delete("/api/timedoctor", headers=H).json()["timedoctor"]["connected"] is False
    assert worker.readers() == []
    assert alice.put("/api/timedoctor", json={"email": "not-an-email", "password": "x"}, headers=H).status_code == 422


def test_owner_keeps_the_server_login(monkeypatch):
    from pace import config

    monkeypatch.setenv("TD_EMAIL", "owner@example.com")
    monkeypatch.setenv("TD_PASSWORD", "env-pw")
    monkeypatch.setenv("PACE_OWNER", "anish")
    config.settings.cache_clear()
    assert worker.readers() == ["anish"]
    assert worker.td_login("anish") == ("owner@example.com", "env-pw")
    assert worker.td_login("bob") is None  # the env login is the owner's alone


def test_single_user_data_moves_to_its_owner(tmp_path, monkeypatch):
    import sqlite3

    from pace import config

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE days (day TEXT PRIMARY KEY, seconds INTEGER NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE task_time (day TEXT NOT NULL, task_id TEXT NOT NULL, task TEXT NOT NULL, project TEXT NOT NULL,
                                seconds INTEGER NOT NULL, PRIMARY KEY (day, task_id));
        CREATE TABLE fetches (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, started_at TEXT NOT NULL,
                              finished_at TEXT, ok INTEGER, error TEXT);
        CREATE TABLE nudges (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL UNIQUE, level TEXT NOT NULL,
                             title TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, created_at REAL NOT NULL,
                               expires_at REAL NOT NULL);
        INSERT INTO days VALUES ('2026-10-01', 7200, 'x');
        INSERT INTO task_time VALUES ('2026-10-01', 'TAI/Build', 'Build', 'TAI', 7200);
        INSERT INTO fetches (source, started_at, finished_at, ok) VALUES ('browser', 'x', 'x', 1);
        INSERT INTO nudges (key, level, title, body, created_at) VALUES ('done:2026-10-01', 'info', 't', 'b', 'x');
        INSERT INTO kv VALUES ('prefs', '{"tz": "Europe/Berlin"}', 'x');
        INSERT INTO sessions VALUES ('h', 'anish', 0, 9e9);
    """)
    old.close()
    monkeypatch.setenv("PACE_DB", str(path))
    config.settings.cache_clear()
    db.init()
    assert db.owner() == "anish"
    assert db.hours("anish", date(2026, 10, 1), date(2026, 10, 1)) == {date(2026, 10, 1): 2.0}
    assert db.tasks("anish", date(2026, 10, 1), date(2026, 10, 1)) == [(date(2026, 10, 1), "Build", "TAI", 7200)]
    assert db.get_prefs("anish").tz == "Europe/Berlin"
    assert db.recent_nudges("anish")[0]["key"] == "done:2026-10-01"
    assert db.last_good_fetch("anish")["source"] == "browser"
    assert db.hours("someone-else", date(2026, 10, 1), date(2026, 10, 1)) == {}
    db.init()  # a second start changes nothing


def test_migration_refuses_to_guess_the_owner(tmp_path, monkeypatch):
    import sqlite3

    import pytest

    from pace import config

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE days (day TEXT PRIMARY KEY, seconds INTEGER NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE task_time (day TEXT, task_id TEXT, task TEXT, project TEXT, seconds INTEGER);
        CREATE TABLE fetches (id INTEGER PRIMARY KEY, source TEXT, started_at TEXT, finished_at TEXT, ok INTEGER, error TEXT);
        CREATE TABLE nudges (id INTEGER PRIMARY KEY, key TEXT, level TEXT, title TEXT, body TEXT, created_at TEXT);
        CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
        CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, username TEXT, created_at REAL, expires_at REAL);
        INSERT INTO days VALUES ('2026-10-01', 7200, 'x');
        INSERT INTO sessions VALUES ('a', 'anish', 0, 9e9), ('b', 'bob', 0, 9e9);
    """)
    old.close()
    monkeypatch.setenv("PACE_DB", str(path))
    config.settings.cache_clear()
    with pytest.raises(db.MigrationError):
        db.init()
    # Nothing was half-done: the old table is untouched.
    assert sqlite3.connect(path).execute("SELECT COUNT(*) FROM days").fetchone()[0] == 1
