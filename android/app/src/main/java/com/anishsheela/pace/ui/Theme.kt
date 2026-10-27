package com.anishsheela.pace.ui

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.ExperimentalTextApi
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import com.anishsheela.pace.R

// Pace for Android, in the Jarvis panel's language: a machined instrument,
// not a glowing screen. Tokens from jarvis/frontend/src/styles/tokens.css, as
// the web app uses them (frontend/src/styles.css), with its semantic states:
// on pace is arc, behind is gold, out of reach is alert (the one bad state),
// and stale hours are slate. Meeting time is the one added colour, a violet
// at the arc's brightness (--meeting in the web app).

@Immutable
data class Palette(
    val ground: Color = Color(0xFF0A0E14),
    val panel: Color = Color(0xFF111823),
    val panelLit: Color = Color(0xFF16202E),
    val arc: Color = Color(0xFF3DD6F5),
    val arcDim: Color = Color(0xFF1D7F96),
    val gold: Color = Color(0xFFE8A33D),
    val alert: Color = Color(0xFFFF4D4D),
    val engrave: Color = Color(0xFF2A3543),
    val ink: Color = Color(0xFFE8F1F8),
    val inkDim: Color = Color(0xFF7C8FA3),
    val slate: Color = Color(0xFF55647A),
    val slateDim: Color = Color(0xFF3A4657),
    val meeting: Color = Color(0xFFB39CFF),
) {
    val onPace get() = arc
    val behind get() = gold
    val outOfReach get() = alert
    val stale get() = slate

    /** Offline is a look, not a set of conditionals: the arc goes slate everywhere at once. */
    fun offline() = copy(arc = slate, arcDim = slateDim, gold = Color(0xFF8A7350), ink = Color(0xFFB9C4D1),
        meeting = Color(0xFF6F6596))
}

@OptIn(ExperimentalTextApi::class)
val Archivo = FontFamily(
    listOf(400, 500, 600, 700).map { w ->
        Font(R.font.archivo_var, FontWeight(w), variationSettings = FontVariation.Settings(FontVariation.weight(w)))
    }
)
val PlexMono = FontFamily(
    Font(R.font.plexmono_400, FontWeight.Normal),
    Font(R.font.plexmono_500, FontWeight.Medium),
)

/** Type roles from interior.css, at the phone scale (site.css). Nothing below t-min (12sp). */
object Type {
    val hero = TextStyle(fontFamily = Archivo, fontWeight = FontWeight.SemiBold, fontSize = 72.sp, lineHeight = 66.sp, letterSpacing = (-0.03).em, fontFeatureSettings = "tnum")
    val major = TextStyle(fontFamily = Archivo, fontWeight = FontWeight.SemiBold, fontSize = 32.sp, lineHeight = 32.sp, letterSpacing = (-0.03).em)
    val headline = TextStyle(fontFamily = Archivo, fontWeight = FontWeight.SemiBold, fontSize = 20.sp, lineHeight = 22.sp, letterSpacing = (-0.02).em)
    val rowTitle = TextStyle(fontFamily = Archivo, fontWeight = FontWeight.SemiBold, fontSize = 18.sp, lineHeight = 22.sp, letterSpacing = (-0.01).em)
    val body = TextStyle(fontFamily = Archivo, fontSize = 16.sp, lineHeight = 23.sp, fontFeatureSettings = "tnum")
    val label = TextStyle(fontFamily = PlexMono, fontWeight = FontWeight.Medium, fontSize = 13.sp, letterSpacing = 0.16.em)
    val control = TextStyle(fontFamily = PlexMono, fontWeight = FontWeight.Medium, fontSize = 13.sp, letterSpacing = 0.08.em)
    val stamp = TextStyle(fontFamily = PlexMono, fontSize = 12.sp, letterSpacing = 0.08.em)
    val wordmark = TextStyle(fontFamily = PlexMono, fontWeight = FontWeight.Medium, fontSize = 16.sp, letterSpacing = 0.3.em)
}

object Dim {
    val rule = 2.dp
    val gap = 16.dp
    val pad = 20.dp
    val bracket = 16.dp
    val radius = 2.dp
}

val LocalPalette = staticCompositionLocalOf { Palette() }

@Composable
fun PaceTheme(offline: Boolean, content: @Composable () -> Unit) {
    val p = if (offline) Palette().offline() else Palette()
    // Material 3 only underneath (Text, Icon); mapped onto the
    // house tokens and squared off so they don't read as stock components.
    val scheme = darkColorScheme(
        primary = p.arc, onPrimary = p.ground,
        secondary = p.arcDim, onSecondary = p.ink,
        background = p.ground, onBackground = p.ink,
        surface = p.panel, onSurface = p.ink,
        surfaceVariant = p.panelLit, onSurfaceVariant = p.inkDim,
        surfaceContainer = p.panel, surfaceContainerHigh = p.panelLit, surfaceContainerHighest = p.panelLit,
        surfaceContainerLow = p.panel, surfaceContainerLowest = p.ground,
        outline = p.engrave, outlineVariant = p.engrave,
        error = p.alert, onError = p.ground,
        primaryContainer = p.arcDim, onPrimaryContainer = p.ink,
        tertiary = p.gold, onTertiary = p.ground,
    )
    val square = RoundedCornerShape(Dim.radius)
    CompositionLocalProvider(LocalPalette provides p) {
        MaterialTheme(
            colorScheme = scheme,
            shapes = Shapes(square, square, square, square, square),
            content = content,
        )
    }
}
