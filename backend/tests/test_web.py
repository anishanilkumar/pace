from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from pace import db, worker
from pace.web import create_app

H = {"X-Pace": "1"}


def client() -> TestClient:
    return TestClient(create_app())


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
    assert c.post("/api/fetch", headers=H).status_code == 202
    assert db.take_fetch_request() is True
    assert db.take_fetch_request() is False


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
    assert db.last_good_fetch()["source"] == "upload"
    r = client().post("/api/upload", files={"file": ("w.csv", "x,y\n1,2\n", "text/csv")}, headers=H)
    assert r.status_code == 422


def test_nudge_feed_is_at_most_once():
    assert db.add_nudge("evening:2026-10-27", "warn", "t", "b") is not None
    assert db.add_nudge("evening:2026-10-27", "warn", "t", "b") is None
    r = client().get("/api/nudges?after=0").json()
    assert [n["key"] for n in r["nudges"]] == ["evening:2026-10-27"]
    assert client().get(f"/api/nudges?after={r['latest']}").json()["nudges"] == []


def test_task_time_is_replaced_per_range():
    d = date(2026, 10, 27)
    db.put_tasks(d, d, [(d, "1", "Engineering Meeting", "TAI", 3600), (d, "2", "Build", "TAI", 1800)])
    db.put_tasks(d, d, [(d, "2", "Build", "TAI", 2400)])
    assert db.tasks(d, d) == [(d, "Build", "TAI", 2400)]


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
    today = datetime.now(db.get_prefs().zone).date()
    worker.ingest({today.replace(day=1): 7200})
    db.put_tasks(today.replace(day=1), today, [(today.replace(day=1), "1", "Engineering Meeting", "TAI", 1800)])
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
    assert db.fetch_requested() is False


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
