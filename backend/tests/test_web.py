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
    prefs["day_end"] = "08:00"
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


def test_idle_detection_from_samples():
    d = date(2026, 10, 27)
    t = lambda h, m: datetime(2026, 10, 27, h, m, tzinfo=timezone.utc)  # noqa: E731
    worker.ingest({d: 3600}, t(9, 0), live=True)
    worker.ingest({d: 5400}, t(9, 30), live=True)
    worker.ingest({d: 5400}, t(10, 0), live=True)
    assert db.last_change(d) == t(9, 30)


def test_backfill_reads_six_months_once():
    today = date(2026, 10, 27)
    spans = worker.backfill_spans(today, None)
    assert spans[0] == (date(2026, 4, 1), date(2026, 4, 30))
    assert spans[-1] == (date(2026, 9, 1), date(2026, 9, 30))
    assert len(spans) == 6
    # Done already: nothing more to read.
    assert worker.backfill_spans(today, date(2026, 4, 1)) == []
    # A month on, the window moves forward over data already read.
    assert worker.backfill_spans(date(2026, 11, 20), date(2026, 4, 1)) == []
    # A deeper window (or a first backfill that reached less far) reads only the gap.
    assert worker.backfill_spans(today, date(2026, 6, 1)) == [
        (date(2026, 4, 1), date(2026, 4, 30)), (date(2026, 5, 1), date(2026, 5, 31))]
    # Early in a month the regular span covers last month, so it isn't backfilled.
    early = worker.backfill_spans(date(2026, 11, 2), None)
    assert early[-1] == (date(2026, 9, 1), date(2026, 9, 30))


def test_summary_has_history():
    today = datetime.now(db.get_prefs().zone).date()
    worker.ingest({today.replace(day=1): 7200}, datetime.now(timezone.utc), live=False)
    h = client().get("/api/summary").json()["history"]
    assert len(h) == 7
    assert h[-1]["current"] is True
    assert h[-1]["hours"] >= 2


def test_fetch_span_rereads_last_month_early_on():
    assert worker.fetch_span(date(2026, 11, 2)) == (date(2026, 10, 1), date(2026, 11, 2))
    assert worker.fetch_span(date(2026, 11, 4)) == (date(2026, 11, 1), date(2026, 11, 4))
