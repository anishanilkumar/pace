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


# /individual-timesheet, as the dashboard's Timesheet panel gets it (trimmed).
TIMESHEET = {
    "users": {
        "1001": {
            "name": "Sample",
            "timeline": {
                "2026-10-01": {"date": "2026-10-01", "worktime": 0, "editedtime": 0, "mobiletime": 0, "totaltime": 0},
                "2026-10-02": {"date": "2026-10-02", "worktime": 889, "editedtime": 600, "mobiletime": 0, "totaltime": 1489},
            },
        }
    },
    "datesSelected": "", "countUsers": 1, "haveData": True, "reportType": "",
}


def test_timesheet_json():
    from pace.timedoctor import parse_timesheet

    assert parse_timesheet(TIMESHEET) == {date(2026, 10, 1): 0, date(2026, 10, 2): 1489}
    assert parse_timesheet(TIMESHEET, "1001")[date(2026, 10, 2)] == 1489


def test_timesheet_not_signed_in_and_ambiguous():
    from pace.timedoctor import _NotSignedIn, parse_timesheet

    with pytest.raises(_NotSignedIn):
        parse_timesheet({"status": "Error", "message": "not authenticated, please login"})
    two = {"users": {"1": {"timeline": {}}, "2": {"timeline": {}}}}
    with pytest.raises(FetchError):
        parse_timesheet(two)
    assert parse_timesheet(two, "2") == {}


# renderProjectsReport.php, as the Projects report page gets it (trimmed).
PROJECTS = {"report": [{"name": "TAI", "users": [{"id": "1001", "name": "Sample", "tasks": [
    {"id": "11", "name": "Engineering Meeting", "entries": [
        {"date": "2026-10-20", "workedTime": 3600}, {"date": "2026-10-21", "workedTime": 0}]},
    {"id": "12", "name": "Foundational certificate issue ", "entries": [{"date": "2026-10-21", "workedTime": 4771}]},
]}]}]}


def test_projects_report_json():
    from pace.timedoctor import parse_projects_report

    rows = parse_projects_report(PROJECTS)
    assert rows == [
        (date(2026, 10, 20), "11", "Engineering Meeting", "TAI", 3600),
        (date(2026, 10, 21), "12", "Foundational certificate issue", "TAI", 4771),
    ]
    assert parse_projects_report(PROJECTS, "999") == []
    with pytest.raises(FetchError):
        parse_projects_report({"status": "Error"})
