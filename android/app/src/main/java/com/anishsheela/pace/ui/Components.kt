package com.anishsheela.pace.ui

import androidx.compose.animation.core.animateFloat
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/** A raised panel with two engraved corner brackets: brackets, not boxes. */
fun Modifier.instrument(p: Palette, lit: Boolean = false): Modifier = this
    .background(if (lit) p.panelLit else p.panel)
    .drawBehind {
        val r = Dim.rule.toPx()
        val b = Dim.bracket.toPx()
        val half = r / 2
        // Top-left
        drawLine(p.engrave, Offset(0f, half), Offset(b, half), r)
        drawLine(p.engrave, Offset(half, 0f), Offset(half, b), r)
        // Bottom-right
        drawLine(p.engrave, Offset(size.width - b, size.height - half), Offset(size.width, size.height - half), r)
        drawLine(p.engrave, Offset(size.width - half, size.height - b), Offset(size.width - half, size.height), r)
    }

/** The house mark for "estimated, not measured": a dotted underline. */
fun Modifier.estimated(color: Color): Modifier = drawBehind {
    val y = size.height + 3.dp.toPx()
    drawLine(color, Offset(0f, y), Offset(size.width, y), 1.5.dp.toPx(),
        pathEffect = PathEffect.dashPathEffect(floatArrayOf(2.dp.toPx(), 3.dp.toPx())))
}

enum class BtnKind { Default, Primary, Quiet, Danger, Add }

@Composable
fun Btn(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    kind: BtnKind = BtnKind.Default,
    enabled: Boolean = true,
    icon: ImageVector? = null,
    textColor: Color? = null,
    minHeight: Dp = 48.dp,
) {
    val p = LocalPalette.current
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val (fill, border, fg) = when (kind) {
        BtnKind.Primary -> Triple(if (pressed) p.ink else p.arc, if (pressed) p.ink else p.arc, p.ground)
        BtnKind.Danger -> Triple(if (pressed) p.engrave else Color.Transparent, p.alert, p.alert)
        BtnKind.Quiet -> Triple(if (pressed) p.engrave else Color.Transparent, p.engrave, p.inkDim)
        BtnKind.Add -> Triple(if (pressed) p.engrave else Color.Transparent, p.engrave, p.arc)
        BtnKind.Default -> Triple(if (pressed) p.engrave else Color.Transparent, p.engrave, p.ink)
    }
    val shape = RoundedCornerShape(Dim.radius)
    Row(
        modifier
            .alpha(if (enabled) 1f else 0.35f)
            .defaultMinSize(minHeight = minHeight)
            .background(fill, shape)
            .then(
                if (kind == BtnKind.Add) Modifier.dashedBorder(border)
                else Modifier.border(BorderStroke(Dim.rule, border), shape)
            )
            .clickable(interaction, indication = null, enabled = enabled, onClick = onClick)
            .padding(horizontal = 20.dp),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            Icon(icon, null, Modifier.size(20.dp), tint = textColor ?: fg)
            Spacer(Modifier.width(8.dp))
        }
        Text(text.uppercase(), style = Type.control, color = textColor ?: fg, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

private fun Modifier.dashedBorder(color: Color) = drawBehind {
    val r = Dim.rule.toPx()
    drawRect(color, topLeft = Offset(r / 2, r / 2),
        size = androidx.compose.ui.geometry.Size(size.width - r, size.height - r),
        style = Stroke(r, pathEffect = PathEffect.dashPathEffect(floatArrayOf(6.dp.toPx(), 4.dp.toPx()))))
}

@Composable
fun Label(text: String, modifier: Modifier = Modifier, color: Color? = null) {
    Text(text.uppercase(), modifier, style = Type.label, color = color ?: LocalPalette.current.arcDim)
}

@Composable
fun Stamp(text: String, modifier: Modifier = Modifier, color: Color? = null, upper: Boolean = false) {
    Text(if (upper) text.uppercase() else text, modifier, style = Type.stamp, color = color ?: LocalPalette.current.inkDim,
        maxLines = 1, overflow = TextOverflow.Ellipsis)
}

/** Status: a square dot carries the state, the text says it. */
@Composable
fun StatusPill(text: String, dot: Color, textColor: Color? = null, blink: Boolean = false, onClick: (() -> Unit)?) {
    val p = LocalPalette.current
    val alpha = if (blink) blinkAlpha() else 1f
    Row(
        Modifier
            .heightIn(min = 44.dp)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(8.dp).alpha(alpha).background(dot))
        Spacer(Modifier.width(8.dp))
        Text(text.uppercase(), style = Type.stamp, color = textColor ?: p.inkDim)
    }
}

/** A mechanical blink, steps(2): on or off, never a smooth pulse. */
@Composable
private fun blinkAlpha(): Float {
    val t = androidx.compose.animation.core.rememberInfiniteTransition(label = "blink")
    val v by t.animateFloat(
        initialValue = 1f, targetValue = 0.2f,
        animationSpec = androidx.compose.animation.core.infiniteRepeatable(
            androidx.compose.animation.core.keyframes {
                durationMillis = 900
                1f at 0
                1f at 449
                0.2f at 450
                0.2f at 899
            }
        ),
        label = "blink",
    )
    return v
}

@Composable
fun RowScope.Grow() = Spacer(Modifier.weight(1f))

// --- line icons, 20-unit grid, stroke 1.6, round caps (house icon style) ------

private fun lineIcon(name: String, vararg paths: String): ImageVector {
    val b = ImageVector.Builder(name, 20.dp, 20.dp, 20f, 20f)
    for (d in paths) {
        b.addPath(
            PathParser().parsePathString(d).toNodes(),
            stroke = SolidColor(Color.White), strokeLineWidth = 1.6f,
            strokeLineCap = StrokeCap.Round, strokeLineJoin = StrokeJoin.Round,
        )
    }
    return b.build()
}

object Icons {
    val Refresh = lineIcon("refresh", "M4 8a6 6 0 0 1 11-2.5M16 12a6 6 0 0 1-11 2.5", "M15 2.5v3h-3M5 17.5v-3h3")
    val Settings = lineIcon("settings", "M3 6h8M15 6h2M3 14h2M9 14h8", "M11 4v4h4V4ZM5 12v4h4v-4Z")
}
