package com.anishsheela.pace

import com.anishsheela.pace.data.Fmt
import com.anishsheela.pace.data.Summary
import com.anishsheela.pace.data.isStale
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.OffsetDateTime

class LogicTest {
    @Test fun clock() {
        assertEquals("2:25", Fmt.clock(2.4166))
        assertEquals("0:00", Fmt.clock(0.0))
    }

    @Test fun span() {
        assertEquals("2 h 25 min", Fmt.span(2.4166))
        assertEquals("45 min", Fmt.span(0.75))
        assertEquals("3 h", Fmt.span(3.0))
        assertEquals("1 h 30 min", Fmt.span(-1.5))
    }

    @Test fun rupees() {
        assertEquals("₹1,50,000", Fmt.rupees(150000.0))
        assertEquals("₹1,23,45,678", Fmt.rupees(12345678.0))
        assertEquals("₹999", Fmt.rupees(999.0))
    }

    // Trimmed from a real /api/summary response.
    private val json = """
        {"plan": {"month": "2026-10", "today": "2026-10-27", "net_per_hour": 1800, "target_net": 150000,
          "target_hours": 89.25, "worked_hours": 79.2, "worked_net": 133077, "worked_gross": 147863, "tds": 14786,
          "expected_hours": 80.0, "diff_hours": -0.8, "diff_before_today": -0.5, "status": "behind",
          "plan_per_day": 4.46, "today_hours": 3.2, "today_quota": 4.42, "today_left": 1.22, "today_working": true,
          "per_day_after_today": 5.0, "working_days": 20, "working_days_left": 3, "projected_hours": null,
          "projected_net": null, "streak": 1,
          "days": [{"date": "2026-10-01", "hours": 4.0, "working": true, "leave": false, "future": false}]},
         "prefs": {"max_hours_per_day": 10, "nudge_from": "09:00", "nudge_until": "21:00"},
         "work": {"meeting_hours": 1.5, "productive_hours": 3.0, "meeting_share": 0.333,
           "meeting_by_day": {"2026-10-01": 1.5}, "tasks": [], "tasks_known": true},
         "fetch": {"last_at": "2026-10-27T08:00:00+00:00", "last_ok": true, "last_error": null,
           "last_good_at": "2026-10-27T08:00:00+00:00", "last_good_source": "browser", "failures": 0, "requested": false},
         "nudges": [{"id": 3, "key": "evening:2026-10-27", "level": "warn", "title": "t", "body": "b",
           "created_at": "2026-10-27T11:30:00+00:00"}],
         "now": "2026-10-27T08:10:00+00:00"}
    """.trimIndent()

    @Test fun parsesSummary() {
        val s = Summary.parse(JSONObject(json))
        assertEquals("2026-10-27", s.today)
        assertEquals("behind", s.status)
        assertNull(s.projectedNet)
        assertNull(s.lastError)
        assertEquals(1, s.nudges.size)
        assertEquals(1, s.days.size)
        assertEquals(1.5, s.work!!.meetingByDay["2026-10-01"]!!, 1e-9)
    }

    @Test fun noWorkUntilTasksKnown() {
        val o = JSONObject(json)
        o.getJSONObject("work").put("tasks_known", false)
        assertNull(Summary.parse(o).work)
        o.remove("work")
        assertNull(Summary.parse(o).work)
    }

    @Test fun staleAfterAnHour() {
        val s = Summary.parse(JSONObject(json))
        assertFalse(s.isStale(OffsetDateTime.parse("2026-10-27T08:30:00+00:00")))
        assertTrue(s.isStale(OffsetDateTime.parse("2026-10-27T09:30:00+00:00")))
    }
}
