package com.anishsheela.pace.data

import org.json.JSONObject
import java.time.Duration
import java.time.OffsetDateTime
import kotlin.math.abs
import kotlin.math.roundToInt

/** The part of /api/summary the phone shows (backend web.py and plan.py). */
data class Summary(
    val month: String,
    /** Today in the server's zone (Time Doctor's days), or null for another month. */
    val today: String?,
    val inMonth: Boolean,
    val status: String,
    val targetNet: Double,
    val targetHours: Double,
    val workedHours: Double,
    val workedNet: Double,
    val expectedHours: Double,
    val diffHours: Double,
    val planPerDay: Double,
    val todayHours: Double,
    val todayQuota: Double,
    val todayLeft: Double,
    val todayWorking: Boolean,
    val workingDaysLeft: Int,
    val projectedNet: Double?,
    val streak: Int,
    val maxHoursPerDay: Double,
    val days: List<Day>,
    /** Meetings and productive work for the month (backend plan.work_split); null until task time has been read. */
    val work: Work?,
    val lastGoodAt: OffsetDateTime?,
    val lastOk: Boolean?,
    val lastError: String?,
    val fetchRequested: Boolean,
    val nudges: List<Nudge>,
) {
    data class Day(val date: String, val hours: Double, val working: Boolean, val leave: Boolean, val future: Boolean)

    data class Work(val meetingHours: Double, val productiveHours: Double, val meetingByDay: Map<String, Double>)

    companion object {
        fun parse(o: JSONObject): Summary {
            val p = o.getJSONObject("plan")
            val prefs = o.getJSONObject("prefs")
            val f = o.getJSONObject("fetch")
            val d = p.getJSONArray("days")
            val n = o.getJSONArray("nudges")
            return Summary(
                month = p.getString("month"),
                today = if (p.isNull("today")) null else p.getString("today"),
                inMonth = !p.isNull("today"),
                status = p.getString("status"),
                targetNet = p.getDouble("target_net"),
                targetHours = p.getDouble("target_hours"),
                workedHours = p.getDouble("worked_hours"),
                workedNet = p.getDouble("worked_net"),
                expectedHours = p.getDouble("expected_hours"),
                diffHours = p.getDouble("diff_hours"),
                planPerDay = p.getDouble("plan_per_day"),
                todayHours = p.getDouble("today_hours"),
                todayQuota = p.getDouble("today_quota"),
                todayLeft = p.getDouble("today_left"),
                todayWorking = p.getBoolean("today_working"),
                workingDaysLeft = p.getInt("working_days_left"),
                projectedNet = if (p.isNull("projected_net")) null else p.getDouble("projected_net"),
                streak = p.getInt("streak"),
                maxHoursPerDay = prefs.getDouble("max_hours_per_day"),
                days = (0 until d.length()).map {
                    val x = d.getJSONObject(it)
                    Day(x.getString("date"), x.getDouble("hours"), x.getBoolean("working"), x.getBoolean("leave"), x.getBoolean("future"))
                },
                work = o.optJSONObject("work")?.takeIf { it.optBoolean("tasks_known") }?.let { w ->
                    val byDay = w.getJSONObject("meeting_by_day")
                    Work(
                        meetingHours = w.getDouble("meeting_hours"),
                        productiveHours = w.getDouble("productive_hours"),
                        meetingByDay = byDay.keys().asSequence().associateWith { byDay.getDouble(it) },
                    )
                },
                lastGoodAt = f.optString("last_good_at").takeIf { it.isNotEmpty() && it != "null" }?.let(OffsetDateTime::parse),
                lastOk = if (f.isNull("last_ok")) null else f.getBoolean("last_ok"),
                lastError = f.optString("last_error").takeIf { it.isNotEmpty() && it != "null" },
                fetchRequested = f.optBoolean("requested"),
                nudges = (0 until n.length()).map { Nudge.parse(n.getJSONObject(it)) },
            )
        }
    }
}

data class Nudge(val id: Long, val key: String, val level: String, val title: String, val body: String, val createdAt: OffsetDateTime) {
    companion object {
        fun parse(o: JSONObject) = Nudge(
            id = o.getLong("id"),
            key = o.getString("key"),
            level = o.getString("level"),
            title = o.getString("title"),
            body = o.getString("body"),
            createdAt = OffsetDateTime.parse(o.getString("created_at")),
        )
    }
}

/** Hours older than this are shown as stale: dimmed, with their age. As the web app. */
val STALE: Duration = Duration.ofMinutes(60)

fun Summary.isStale(now: OffsetDateTime = OffsetDateTime.now()): Boolean =
    inMonth && (lastGoodAt == null || Duration.between(lastGoodAt, now) > STALE)

// --- numbers as the instrument reads them (frontend/src/format.ts) ----------

object Fmt {
    /** 2.4166 -> "2:25". */
    fun clock(hours: Double): String {
        val m = (hours * 60).roundToInt().coerceAtLeast(0)
        return "${m / 60}:${(m % 60).toString().padStart(2, '0')}"
    }

    /** 2.4166 -> "2 h 25 min"; 0.75 -> "45 min". The nudges' words. */
    fun span(hours: Double): String {
        val m = (abs(hours) * 60).roundToInt()
        if (m < 60) return "$m min"
        return "${m / 60} h" + if (m % 60 != 0) " ${(m % 60).toString().padStart(2, '0')} min" else ""
    }

    /**
     * 150000 -> "₹1,50,000": the last three digits, then pairs. By hand,
     * because en-IN's lakh grouping depends on the platform's locale data
     * (the JVM's gives "150,000").
     */
    fun rupees(n: Double): String {
        val v = n.roundToInt()
        val digits = abs(v).toString()
        val grouped = if (digits.length <= 3) digits else {
            val head = digits.dropLast(3)
            head.reversed().chunked(2).joinToString(",").reversed() + "," + digits.takeLast(3)
        }
        return (if (v < 0) "-₹" else "₹") + grouped
    }
}
