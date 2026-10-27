package com.anishsheela.pace.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import com.anishsheela.pace.data.Fmt
import com.anishsheela.pace.data.Nudge
import com.anishsheela.pace.data.Summary
import com.anishsheela.pace.data.isStale
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.TextStyle
import java.util.Locale
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/** What the home screen is showing: the last summary, and whether it could refresh. */
data class HomeState(val summary: Summary?, val offline: Boolean, val error: String?, val loading: Boolean)

@Composable
fun HomeScreen(
    state: HomeState,
    onFetchNow: () -> Unit,
    onRetry: () -> Unit,
    onSettings: () -> Unit,
    onSignOut: () -> Unit,
) {
    val p = LocalPalette.current
    Column(
        Modifier
            .fillMaxSize()
            .background(p.ground)
            .systemBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = Dim.gap, vertical = Dim.gap),
        verticalArrangement = Arrangement.spacedBy(Dim.gap),
    ) {
        TopBar(state, onFetchNow, onSettings)
        val s = state.summary
        when {
            s == null && state.loading -> {
                Box(Modifier.fillMaxWidth().height(160.dp).instrument(p))
                Box(Modifier.fillMaxWidth().height(320.dp).instrument(p))
            }
            s == null -> Empty(state.error ?: "Can't load", onRetry)
            else -> {
                val stale = s.isStale()
                if (stale) StaleNote(s)
                Box(Modifier.alpha(if (stale) 0.7f else 1f)) {
                    Column(verticalArrangement = Arrangement.spacedBy(Dim.gap)) {
                        if (s.inMonth) Today(s, stale)
                        Verdict(s)
                        Month(s, stale)
                    }
                }
                if (s.nudges.isNotEmpty()) RecentNudges(s.nudges)
            }
        }
        Btn("Sign out", onSignOut, kind = BtnKind.Quiet)
    }
}

@Composable
private fun TopBar(state: HomeState, onFetchNow: () -> Unit, onSettings: () -> Unit) {
    val p = LocalPalette.current
    val s = state.summary
    Row(
        Modifier
            .fillMaxWidth()
            .drawBehind {
                val r = Dim.rule.toPx()
                drawLine(p.engrave, Offset(0f, size.height - r / 2), Offset(size.width, size.height - r / 2), r)
            }
            .padding(bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("PACE", style = Type.wordmark, color = p.ink)
        Grow()
        if (s != null) {
            val (dot, text, warn) = when {
                state.offline -> Triple(p.slate, "Offline", false)
                s.fetchRequested -> Triple(p.arc, "Reading", false)
                s.lastOk == false -> Triple(p.gold, s.lastGoodAt?.let { "Read ${stamp(it)}" } ?: "Not read", true)
                s.lastGoodAt == null -> Triple(p.slate, "Not read yet", false)
                s.isStale() -> Triple(p.slate, "Read ${stamp(s.lastGoodAt)}", false)
                else -> Triple(p.arc, "Read ${stamp(s.lastGoodAt)}", false)
            }
            // Status only; the Sync button beside it does the reading.
            StatusPill(text, dot, textColor = if (warn) p.gold else null, blink = s.fetchRequested, onClick = null)
            Spacer(Modifier.width(8.dp))
            Btn(
                if (s.fetchRequested) "Syncing" else "Sync", onFetchNow,
                kind = BtnKind.Add, icon = Icons.Refresh, minHeight = 44.dp,
                enabled = !state.offline && !s.fetchRequested,
            )
        }
        Spacer(Modifier.width(8.dp))
        Box(
            Modifier.size(44.dp).clickable(onClick = onSettings),
            contentAlignment = Alignment.Center,
        ) { Icon(Icons.Settings, "Settings", Modifier.size(20.dp), tint = p.inkDim) }
    }
}

@Composable
private fun StaleNote(s: Summary) {
    val since = s.lastGoodAt?.let { "since ${stamp(it)}" } ?: "yet"
    Callout(LocalPalette.current.stale, "Time Doctor not read $since",
        (s.lastError?.let { "$it " } ?: "The hours below may be behind. ") +
            "If it keeps failing, upload a worklog CSV in settings.")
}

@Composable
private fun Today(s: Summary, stale: Boolean) {
    val p = LocalPalette.current
    Column(Modifier.fillMaxWidth().instrument(p).padding(Dim.pad), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Label("Today")
        Row(verticalAlignment = Alignment.Bottom) {
            Text(Fmt.clock(s.todayHours), style = Type.hero, color = if (stale) p.inkDim else p.ink)
            if (s.todayWorking) {
                Spacer(Modifier.width(10.dp))
                Text("of ${Fmt.clock(s.todayQuota)}", style = Type.major.copy(fontSize = Type.headline.fontSize), color = p.inkDim,
                    modifier = Modifier.padding(bottom = 8.dp))
            }
        }
        if (s.todayWorking) {
            // One tick per quarter hour of today's quota, at most a 12-hour day of them.
            val total = min(48, max(1, kotlin.math.ceil(s.todayQuota * 4).toInt()))
            val lit = floor(s.todayHours * 4).toInt()
            Ticks(total, min(lit, total), lit = if (stale) p.slate else p.arc)
            Text(
                if (s.todayLeft > 0) "${Fmt.span(s.todayLeft)} left for today, whenever suits."
                else "Today's quota is done. More now eases the days ahead.",
                style = Type.body, color = p.inkDim,
            )
        } else {
            Text("Day off. Anything tracked still counts toward the month.", style = Type.body, color = p.inkDim)
        }
    }
}

@Composable
private fun Verdict(s: Summary) {
    val p = LocalPalette.current
    val name = monthName(s.month)
    val (color, head, detail) = when {
        !s.inMonth -> Triple(
            if (s.status == "done") p.onPace else p.behind,
            if (s.status == "done") "$name: target reached" else "$name: ${Fmt.span(s.targetHours - s.workedHours)} short",
            "${Fmt.span(s.workedHours)} tracked of ${Fmt.span(s.targetHours)}, ${Fmt.rupees(s.workedNet)} after TDS.",
        )
        s.status == "done" -> Triple(p.onPace, "$name's target reached",
            "${Fmt.span(s.workedHours - s.targetHours)} over. ${Fmt.rupees(s.workedNet)} after TDS.")
        s.status == "out_of_reach" -> Triple(p.outOfReach, "Target out of reach",
            if (s.workingDaysLeft > 0) "It needs ${Fmt.span(s.todayQuota)} a day for ${s.workingDaysLeft} days, over your " +
                "${Fmt.span(s.maxHoursPerDay)} limit. Lower the target or add working days."
            else "No working days are left this month.")
        s.status == "behind" -> Triple(p.behind, "${Fmt.span(-s.diffHours)} behind plan",
            "Catching up means ${Fmt.span(s.todayQuota)} a day for the ${s.workingDaysLeft} working days left, today included.")
        else -> Triple(p.onPace,
            if (s.diffHours >= 0.25) "${Fmt.span(s.diffHours)} ahead of plan" else "On pace",
            "The even plan is ${Fmt.span(s.planPerDay)} a working day; ${s.workingDaysLeft} working days left.")
    }
    Callout(color, head, detail)
}

@Composable
private fun Month(s: Summary, stale: Boolean) {
    val p = LocalPalette.current
    val n = 40
    val per = s.targetHours / n
    val lit = if (per > 0) min(n, floor(s.workedHours / per).toInt()) else 0
    val expected = if (per > 0) min(n, floor(s.expectedHours / per).toInt()) else 0
    Column(Modifier.fillMaxWidth().instrument(p).padding(Dim.pad), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Label("${monthName(s.month)} ${s.month.take(4)}")
        Column {
            Text(Fmt.rupees(s.workedNet), style = Type.major, color = if (stale) p.inkDim else p.ink)
            Stamp("of ${Fmt.rupees(s.targetNet)} after TDS", upper = true)
        }
        Ticks(n, lit, warn = max(0, expected - lit), lit = if (stale) p.slate else p.onPace, gap = 2.dp)
        Row(Modifier.fillMaxWidth()) {
            Fact("Hours", "${Fmt.clock(s.workedHours)} / ${Fmt.clock(s.targetHours)}", Modifier.weight(1f))
            Fact("Projected", s.projectedNet?.let(Fmt::rupees) ?: "Too early", Modifier.weight(1f), estimated = s.projectedNet != null)
            Fact("Streak", "${s.streak} ${if (s.streak == 1) "day" else "days"}", Modifier.weight(0.8f))
        }
        s.work?.let { WorkSplit(it) }
        DayBars(s)
    }
}

/** Meetings against productive work, as the web app's split: productive arc, meetings violet. */
@Composable
private fun WorkSplit(w: Summary.Work) {
    val p = LocalPalette.current
    val total = w.meetingHours + w.productiveHours
    if (total <= 0) return
    val n = 40
    val meetingTicks = (w.meetingHours / total * n).roundToInt()
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(Modifier.fillMaxWidth()) {
            Fact("Productive", "${Fmt.clock(w.productiveHours)}  ${(w.productiveHours / total * 100).roundToInt()}%", Modifier.weight(1f))
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Stamp("Meetings", upper = true)
                Text("${Fmt.clock(w.meetingHours)}  ${(w.meetingHours / total * 100).roundToInt()}%", style = Type.rowTitle, color = p.meeting)
            }
        }
        // Every tick is a share of the month: productive lit arc, the rest meeting.
        Ticks(n, n - meetingTicks, warn = meetingTicks, lit = p.arc, warnColor = p.meeting, gap = 2.dp)
    }
}

@Composable
private fun Fact(label: String, value: String, modifier: Modifier, estimated: Boolean = false) {
    val p = LocalPalette.current
    Column(modifier, verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Stamp(label, upper = true)
        Text(value, style = Type.rowTitle, color = p.ink,
            modifier = if (estimated) Modifier.estimated(p.arcDim) else Modifier)
    }
}

/** Hours per day, as the web app's chart: met plan arc, short arc-dim, day off slate, plan dashed gold. */
@Composable
private fun DayBars(s: Summary) {
    val p = LocalPalette.current
    val today = s.today
    val top = max(max(s.planPerDay * 1.6, s.days.maxOfOrNull { it.hours } ?: 0.0), 1.0)
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Canvas(Modifier.fillMaxWidth().height(96.dp)) {
            val col = size.width / s.days.size
            val bar = col * 0.64f
            fun y(h: Double) = size.height - (h / top * size.height).toFloat()
            s.days.forEachIndexed { i, d ->
                val x = i * col + (col - bar) / 2
                when {
                    d.hours > 0 -> {
                        val c = when {
                            !d.working -> p.slate
                            d.date == today -> p.arc
                            d.hours >= s.planPerDay * 0.95 -> p.arc
                            else -> p.arcDim
                        }
                        drawRect(c, Offset(x, y(d.hours)), Size(bar, size.height - y(d.hours)))
                        // Meeting time capped on top, as on the web chart.
                        val met = min(s.work?.meetingByDay?.get(d.date) ?: 0.0, d.hours)
                        if (met > 0) drawRect(p.meeting, Offset(x, y(d.hours)), Size(bar, size.height - y(met)))
                    }
                    d.leave -> drawRect(p.slateDim, Offset(x, y(s.planPerDay)), Size(bar, size.height - y(s.planPerDay)),
                        style = Stroke(2.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(3.dp.toPx(), 3.dp.toPx()))))
                    d.working -> drawRect(p.panelLit, Offset(x, size.height - 3.dp.toPx()), Size(bar, 3.dp.toPx()))
                }
            }
            if (s.planPerDay > 0) {
                drawLine(p.gold, Offset(0f, y(s.planPerDay)), Offset(size.width, y(s.planPerDay)), 2.dp.toPx(),
                    pathEffect = PathEffect.dashPathEffect(floatArrayOf(6.dp.toPx(), 4.dp.toPx())))
            }
        }
        Row(Modifier.fillMaxWidth()) {
            Stamp("1")
            Grow()
            Stamp(s.days.size.toString())
        }
    }
}

@Composable
private fun RecentNudges(items: List<Nudge>) {
    val p = LocalPalette.current
    Column(Modifier.fillMaxWidth().instrument(p).padding(Dim.pad)) {
        Label("Recent nudges", Modifier.padding(bottom = 8.dp))
        items.forEachIndexed { i, n ->
            Row(
                Modifier
                    .fillMaxWidth()
                    .drawBehind {
                        if (i > 0) drawLine(p.engrave, Offset(0f, 0f), Offset(size.width, 0f), Dim.rule.toPx())
                    }
                    .heightIn(min = 56.dp)
                    .padding(vertical = 10.dp),
            ) {
                val dot = when (n.level) { "alert" -> p.alert; "warn" -> p.gold; else -> p.arc }
                Box(Modifier.padding(top = 7.dp).size(8.dp).background(dot))
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(n.title, style = Type.rowTitle.copy(fontSize = Type.body.fontSize), color = p.ink)
                    Text(n.body, style = Type.body, color = p.inkDim)
                }
                Spacer(Modifier.width(8.dp))
                Stamp(stamp(n.createdAt))
            }
        }
    }
}

// --- pieces -------------------------------------------------------------------

/** A thick left border in the state's colour. */
@Composable
fun Callout(color: Color, head: String, detail: String) {
    val p = LocalPalette.current
    Row(Modifier.fillMaxWidth().background(p.panel)) {
        Box(Modifier.width(6.dp).heightIn(min = 72.dp).background(color))
        Column(Modifier.padding(horizontal = Dim.pad, vertical = 14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(head, style = Type.headline, color = p.ink)
            Text(detail, style = Type.body, color = p.inkDim)
        }
    }
}

/** Progress as a row of index ticks: lit, then the shortfall in gold, the rest engraved. */
@Composable
fun Ticks(
    total: Int,
    litCount: Int,
    warn: Int = 0,
    lit: Color = LocalPalette.current.arc,
    warnColor: Color = LocalPalette.current.behind,
    gap: androidx.compose.ui.unit.Dp = 3.dp,
) {
    val p = LocalPalette.current
    Canvas(Modifier.fillMaxWidth().height(18.dp)) {
        val g = gap.toPx()
        val w = (size.width - g * (total - 1)) / total
        for (i in 0 until total) {
            val c = when {
                i < litCount -> lit
                i < litCount + warn -> warnColor
                else -> p.engrave
            }
            drawRect(c, Offset(i * (w + g), 0f), Size(w, size.height))
        }
    }
}

@Composable
private fun Empty(message: String, onRetry: () -> Unit) {
    val p = LocalPalette.current
    Column(
        Modifier.fillMaxWidth().padding(vertical = 48.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text("CAN'T LOAD", style = Type.label.copy(fontSize = Type.body.fontSize), color = p.slate)
        Text(message, style = Type.body, color = p.inkDim)
        Btn("Try again", onRetry)
    }
}

private val hm = DateTimeFormatter.ofPattern("HH:mm")
private val dayHm = DateTimeFormatter.ofPattern("EEE HH:mm", Locale.ENGLISH)
private val dayMonth = DateTimeFormatter.ofPattern("d MMM", Locale.ENGLISH)

/** "14:20" today, "Mon 14:20" this week, else "27 Oct". Phone's own zone, as the web app. */
fun stamp(t: OffsetDateTime, now: OffsetDateTime = OffsetDateTime.now()): String {
    val local = t.atZoneSameInstant(ZoneId.systemDefault())
    val nowLocal = now.atZoneSameInstant(ZoneId.systemDefault())
    return when {
        local.toLocalDate() == nowLocal.toLocalDate() -> local.format(hm)
        java.time.Duration.between(local, nowLocal).toDays() < 6 -> local.format(dayHm)
        else -> local.format(dayMonth)
    }
}

fun monthName(month: String): String =
    java.time.YearMonth.parse(month).month.getDisplayName(TextStyle.FULL, Locale.ENGLISH)
