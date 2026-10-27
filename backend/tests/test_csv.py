from datetime import date

import pytest

from pace.timedoctor import FetchError, cover, parse_worklog

# The Classic worklog export the old dashboard took: per day, a h:mm column
# headed "Mon 1-Dec" and then the decimal hours.
WIDE = (
    '"Name","Mon 1-Dec","","Tue 2-Dec","","Wed 3-Dec","","Total",""\n'
    '"Sample","5:15","5.25","0:00","0","3:30","3.5","8:45","8.75"\n'
)


def test_wide_export():
    out = parse_worklog(WIDE, near=date(2025, 12, 10))
    assert out == {date(2025, 12, 1): 18900, date(2025, 12, 2): 0, date(2025, 12, 3): 12600}


def test_wide_year_follows_near_date_across_new_year():
    out = parse_worklog(WIDE, near=date(2026, 1, 2))
    assert date(2025, 12, 1) in out


def test_wide_sums_project_rows_and_ignores_total_row():
    text = (
        '"Project","Mon 1-Dec",""\n'
        '"Alpha","2:00","2"\n'
        '"Beta","1:30","1.5"\n'
        '"Total","3:30","3.5"\n'
    )
    assert parse_worklog(text, near=date(2025, 12, 1)) == {date(2025, 12, 1): 12600}


def test_long_format():
    text = "Date,Task,Time Worked\n2026-10-01,Build,2:30:00\n2026-10-01,Review,0:30:00\n2026-10-02,Build,1:00\n"
    assert parse_worklog(text, near=date(2026, 10, 2)) == {date(2026, 10, 1): 10800, date(2026, 10, 2): 3600}


def test_not_a_worklog():
    with pytest.raises(FetchError):
        parse_worklog("a,b\n1,2\n", near=date(2026, 10, 1))
    with pytest.raises(FetchError):
        parse_worklog("only a header\n", near=date(2026, 10, 1))


def test_cover_fills_missing_days_with_zero():
    out = cover({date(2026, 10, 2): 60}, date(2026, 10, 1), date(2026, 10, 3))
    assert out == {date(2026, 10, 1): 0, date(2026, 10, 2): 60, date(2026, 10, 3): 0}


# getTimeLineReportData.php, as the Timeline page gets it for one day (trimmed).
TIMELINE = {"users": [{"userFullName": "Sample", "totalWorkedTimeInSec": 7200, "tasks": [
    {"start_time": "2026-09-04 00:00:00", "end_time": "2026-09-04 09:10:00", "task_name": "Not Working",
     "client_name": "No Project", "work_time": 33000, "work_mode": "5"},
    {"start_time": "2026-09-04 09:10:00", "end_time": "2026-09-04 10:10:00", "task_name": "Engineering Meeting",
     "client_name": "TAI", "work_time": 3600, "work_mode": "0"},
    {"start_time": "2026-09-04 10:20:00", "end_time": "2026-09-04 10:50:00", "task_name": "Engineering Meeting",
     "client_name": "TAI", "work_time": "1800", "work_mode": "0"},
    {"start_time": "2026-09-04 20:30:00", "end_time": "2026-09-04 21:00:00", "task_name": "Certificate issue ",
     "client_name": "TAI", "work_time": 1800, "work_mode": "3"},
    {"start_time": "2026-09-04 21:00:00", "end_time": "2026-09-04 21:00:00", "task_name": "Certificate issue",
     "client_name": "TAI", "work_time": 0, "work_mode": "0"},
]}]}


def test_timeline_day():
    from pace.timedoctor import parse_timeline

    total, rows = parse_timeline(TIMELINE, date(2026, 9, 4))
    # "Not Working" is left out; edited time (mode 3) counts; work_time may be a string.
    assert total == 7200
    assert sorted(rows) == [
        (date(2026, 9, 4), "TAI/Certificate issue", "Certificate issue", "TAI", 1800),
        (date(2026, 9, 4), "TAI/Engineering Meeting", "Engineering Meeting", "TAI", 5400),
    ]


def test_timeline_empty_and_malformed():
    from pace.timedoctor import parse_timeline

    assert parse_timeline({"users": []}, date(2026, 9, 6)) == (0, [])
    with pytest.raises(FetchError):
        parse_timeline({"status": "Error"}, date(2026, 9, 6))
    with pytest.raises(FetchError):
        parse_timeline({"users": [{"tasks": []}, {"tasks": []}]}, date(2026, 9, 6))


def test_timezone_id_lookup():
    from pace.timedoctor import find_timezone_id

    tzs = {"timezones": [
        {"id": 31, "name": "(GMT+01:00) Berlin, Stockholm", "timezone": "Europe/Berlin", "offset": 3600},
        {"id": 47, "name": "(GMT+05:30) Mumbai, Kolkata", "timezone": "Asia/Colombo", "offset": 19800},
    ]}
    assert find_timezone_id(tzs, "Europe/Berlin") == "31"
    assert find_timezone_id(tzs["timezones"], "Asia/Colombo") == "47"
    assert find_timezone_id(tzs, "Mars/Olympus") is None
