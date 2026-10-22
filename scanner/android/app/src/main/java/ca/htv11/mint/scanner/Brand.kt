package ca.htv11.mint.scanner

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.addOutline
import androidx.compose.ui.graphics.asAndroidPath
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp

/**
 * Brand tokens (CLAUDE.md §15), the same palette as the website. The full-screen moments are light (paper,
 * ink, mint); the scanner HUD over the live camera stays white on a dark scrim.
 */
object Brand {
    val mint = Color(0xFF3DDC97)
    val mintInk = Color(0xFF1B6B49)   // green text on paper (bright mint fails contrast there)
    val ink = Color(0xFF0B0F0E)
    val stageBg = Color(0xFF0B0F0E)
    val paper = Color(0xFFFAF7F2)
    val amber = Color(0xFFF5B53F)
    val red = Color(0xFFFF4D4D)
    val slate = Color(0xFF8A9499)
}

/** Rounded type, like the iOS app's SF Rounded: Nunito (OFL, assets/licenses), one variable font for every weight. */
private fun nunito(weight: Int) = Font(
    R.font.nunito, FontWeight(weight),
    variationSettings = FontVariation.Settings(FontVariation.weight(weight)),
)

val Rounded = FontFamily(
    nunito(400), nunito(500), nunito(600), nunito(700), nunito(800), nunito(900),
)

/** A rounded text style; `tracking` in points like SwiftUI's `.tracking`. */
fun rounded(size: TextUnit, weight: FontWeight = FontWeight.Normal, tracking: Float = 0f) = TextStyle(
    fontFamily = Rounded,
    fontWeight = weight,
    fontSize = size,
    letterSpacing = if (tracking == 0f) TextUnit.Unspecified else (tracking / size.value).em,
)

// iOS text styles at the default size (the app was designed on them).
object Type {
    val title = 28.sp
    val title2 = 22.sp
    val title3 = 20.sp
    val headline = 17.sp
    val body = 17.sp
    val subheadline = 15.sp
    val footnote = 13.sp
    val caption = 12.sp
    val caption2 = 11.sp
}

/** The mint dot and wordmark. White over the camera (scanner HUD), ink on the light screens. */
@Composable
fun MintMark(ink: Color = Brand.ink) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        GlowDot(Brand.mint, 10.dp, glow = 6.dp)
        Text("mint", style = rounded(28.sp, FontWeight.ExtraBold), color = ink)
    }
}

/** A dot with a soft glow round it (`.shadow(color:radius:)`). */
@Composable
fun GlowDot(color: Color, size: Dp, glow: Dp = 0.dp) {
    androidx.compose.foundation.layout.Box(
        Modifier
            .size(size)
            .glow(color, glow, CircleShape)
            .clip(CircleShape)
            .background(color),
    )
}

/** A coloured shadow: SwiftUI's `.shadow(color:radius:)`, drawn as a blurred copy of the shape behind it. */
fun Modifier.glow(color: Color, radius: Dp, shape: androidx.compose.ui.graphics.Shape = RoundedCornerShape(0.dp)): Modifier =
    if (radius.value <= 0f || color.alpha == 0f) this else drawBehind {
        val r = radius.toPx()
        val outline = shape.createOutline(size, layoutDirection, this)
        val path = androidx.compose.ui.graphics.Path().apply { addOutline(outline) }
        val paint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG).apply {
            this.color = color.toArgb()
            maskFilter = android.graphics.BlurMaskFilter(r, android.graphics.BlurMaskFilter.Blur.NORMAL)
        }
        drawIntoCanvas { it.nativeCanvas.drawPath(path.asAndroidPath(), paint) }
    }

/** The capsule behind HUD labels over the camera (the frosted material on iOS): a dark translucent pill. */
fun Modifier.chip(): Modifier = this
    .clip(RoundedCornerShape(50))
    .background(Color(0x8C1C2120))
    .padding(horizontal = 12.dp, vertical = 8.dp)
