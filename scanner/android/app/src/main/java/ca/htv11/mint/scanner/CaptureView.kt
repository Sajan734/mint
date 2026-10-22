package ca.htv11.mint.scanner

import android.graphics.BlurMaskFilter
import android.os.SystemClock
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.CenterFocusWeak
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Flip
import androidx.compose.material.icons.rounded.Timer
import androidx.compose.material.icons.rounded.Verified
import androidx.compose.material.icons.rounded.VerifiedUser
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.asAndroidPath
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.UUID
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin

/** The camera is always live underneath; each phase puts its own screen over it. */
@Composable
fun CaptureView(session: CaptureSession) {
    // Where the camera picture is on screen, for tap to focus (window pixels).
    val cameraBounds = remember { mutableStateOf(Rect.Zero) }
    Box(Modifier.fillMaxSize().background(Color.Black)) {
        // The preview shows the whole 4:3 frame that is recorded, like the camera app's photo mode. Filling the
        // tall screen instead crops the sides, which looks zoomed in and hides what is in the shot.
        AndroidView(
            factory = { session.camera.view },
            modifier = Modifier
                .align(Alignment.Center)
                .fillMaxWidth()
                .aspectRatio(3f / 4f)
                .onGloballyPositioned { cameraBounds.value = it.boundsInWindow() },
        )

        AnimatedVisibility(session.inScanner, enter = fadeIn(tween(450)), exit = fadeOut(tween(450))) {
            ScannerHUD(session, cameraBounds)
        }
        // The full-screen moments are light (paper and ink); the scanner HUD above stays dark over the camera.
        AnimatedContent(
            targetState = screenOf(session.phase),
            transitionSpec = {
                if (targetState == "finished") (fadeIn(tween(450)) + scaleIn(tween(450), initialScale = 1.04f)) togetherWith fadeOut(tween(450))
                else fadeIn(tween(450)) togetherWith fadeOut(tween(450))
            },
            label = "screen",
        ) { screen ->
            when (screen) {
                "waiting" -> WaitingScreen(session, cameraBounds)
                "sending" -> SendingScreen((session.phase as? CaptureSession.Phase.Sending)?.progress ?: 1.0, session.passes.size)
                "finished" -> FinishedScreen(session)
                "failed" -> FailedScreen((session.phase as? CaptureSession.Phase.Failed)?.message ?: "", session)
                else -> Box(Modifier.fillMaxSize())
            }
        }
    }
}

/** Which screen the phase shows (sending progress doesn't change it). */
private fun screenOf(p: CaptureSession.Phase): String = when (p) {
    CaptureSession.Phase.Waiting -> "waiting"
    CaptureSession.Phase.Ready, CaptureSession.Phase.Recording, CaptureSession.Phase.Saving, CaptureSession.Phase.Review -> "scanner"
    is CaptureSession.Phase.Sending -> "sending"
    CaptureSession.Phase.Finished -> "finished"
    is CaptureSession.Phase.Failed -> "failed"
}

/** Saving or reviewing: the pass is over and its coverage stays on screen. */
private val CaptureSession.Phase.isFinished get() = this == CaptureSession.Phase.Saving || this == CaptureSession.Phase.Review

/** Seconds of uptime, updated every frame (SwiftUI's `TimelineView(.animation)`). */
@Composable
fun animationTime(): State<Double> {
    val t = remember { mutableDoubleStateOf(SystemClock.uptimeMillis() / 1000.0) }
    LaunchedEffect(Unit) {
        while (true) withFrameNanos { t.doubleValue = SystemClock.uptimeMillis() / 1000.0 }
    }
    return t
}

/** Seconds of uptime, updated every `period` seconds (`TimelineView(.periodic)`). */
@Composable
fun periodicTime(period: Long = 250): State<Double> {
    val t = remember { mutableDoubleStateOf(SystemClock.uptimeMillis() / 1000.0) }
    LaunchedEffect(Unit) {
        while (true) {
            t.doubleValue = SystemClock.uptimeMillis() / 1000.0
            delay(period)
        }
    }
    return t
}

/** Taps on the camera picture focus there. `point` is in window pixels. */
fun focusOnCamera(session: CaptureSession, cameraBounds: Rect, point: Offset): Boolean {
    if (!cameraBounds.contains(point)) return false
    return session.focus(point.x - cameraBounds.left, point.y - cameraBounds.top)
}

private class FocusTap(val point: Offset, val id: String = UUID.randomUUID().toString())

// MARK: - The scanner: the live camera, and the coverage ring round the scan button

@Composable
private fun ScannerHUD(session: CaptureSession, cameraBounds: MutableState<Rect>) {
    var confirmCancel by remember { mutableStateOf(false) }
    var focusTap by remember { mutableStateOf<FocusTap?>(null) }
    var hudOrigin by remember { mutableStateOf(Offset.Zero) }
    Box(Modifier.fillMaxSize().onGloballyPositioned { hudOrigin = it.boundsInWindow().topLeft }) {
        // Legibility only: the top and bottom edges darken a little; the camera stays wide open.
        Box(
            Modifier.fillMaxSize().background(
                Brush.verticalGradient(
                    0f to Color.Black.copy(alpha = 0.6f), 0.2f to Color.Transparent,
                    0.66f to Color.Transparent, 1f to Color.Black.copy(alpha = 0.75f),
                ),
            ),
        )
        // Tap to focus, anywhere on the camera picture outside the controls (before and during a scan).
        Box(
            Modifier.fillMaxSize().pointerInput(Unit) {
                detectTapGestures { p ->
                    val window = p + hudOrigin
                    if (focusOnCamera(session, cameraBounds.value, window)) focusTap = FocusTap(p)
                }
            },
        )
        focusTap?.let { tap ->
            androidx.compose.runtime.key(tap.id) { FocusMark(tap.point) }
        }

        Column(
            Modifier.fillMaxSize().safeDrawingPadding().padding(start = 16.dp, end = 16.dp, bottom = 10.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            TopBar(session)
            JobChip(session)
            Spacer(Modifier.weight(1f))
            AnimatedContent(
                targetState = session.phase == CaptureSession.Phase.Review,
                transitionSpec = {
                    (slideInVertically(spring(dampingRatio = 0.85f, stiffness = Spring.StiffnessMediumLow)) { it } + fadeIn()) togetherWith
                        (slideOutVertically { it } + fadeOut())
                },
                label = "bottom",
            ) { review ->
                if (review) {
                    ReviewCard(session)
                } else {
                    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        Caption(session)
                        Controls(session) { confirmCancel = true }
                    }
                }
            }
        }
    }
    if (confirmCancel) {
        val n = session.passes.size
        AlertDialog(
            onDismissRequest = { confirmCancel = false },
            title = { Text("Discard this scan?", style = rounded(Type.headline, FontWeight.Bold)) },
            text = { Text("Nothing will be sent.", style = rounded(Type.subheadline)) },
            confirmButton = {
                TextButton(onClick = { confirmCancel = false; session.cancelJob() }) {
                    Text("Discard $n pass${if (n == 1) "" else "es"}", color = Brand.red, style = rounded(Type.body, FontWeight.SemiBold))
                }
            },
            dismissButton = {
                TextButton(onClick = { confirmCancel = false }) { Text("Cancel", color = Brand.ink, style = rounded(Type.body)) }
            },
            containerColor = Brand.paper,
        )
    }
}

// Top: the mark, and the recording clock (or the pass about to start, or the passes saved).
@Composable
private fun TopBar(session: CaptureSession) {
    Row(Modifier.fillMaxWidth().padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        MintMark(ink = Color.White)
        Spacer(Modifier.weight(1f))
        when (session.phase) {
            CaptureSession.Phase.Recording -> {
                val now by periodicTime()
                val t = session.recordStart?.let { now - it / 1000.0 }?.coerceAtLeast(0.0) ?: 0.0
                Row(Modifier.chip(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Box(Modifier.size(9.dp).alpha(if ((t * 2).toInt() % 2 == 0) 1f else 0.35f).clip(CircleShape).background(Brand.red))
                    Text(
                        "REC %d:%02d".format(t.toInt() / 60, t.toInt() % 60),
                        style = androidx.compose.ui.text.TextStyle(fontFamily = FontFamily.Monospace, fontWeight = FontWeight.SemiBold, fontSize = Type.subheadline),
                        color = Color.White,
                    )
                    if (session.nextPass > 1) PassTag(session.nextPass)
                }
            }
            CaptureSession.Phase.Ready -> if (session.nextPass > 1) Box(Modifier.chip()) { PassTag(session.nextPass) }
            else -> Row(Modifier.chip(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Icon(Icons.Rounded.Verified, null, tint = Brand.mint, modifier = Modifier.size(15.dp))
                Text(
                    if (session.passes.size > 1) "${session.passes.size} PASSES" else "PASS SAVED",
                    style = rounded(Type.caption, FontWeight.Bold, tracking = 1.2f), color = Brand.mint,
                )
            }
        }
    }
}

@Composable
private fun PassTag(n: Int) {
    Text("PASS $n", style = rounded(Type.caption, FontWeight.Black, tracking = 1.2f), color = Brand.mint)
}

// Under the mark: the tagline, or what a buyer's verify scan is for.
@Composable
private fun JobChip(session: CaptureSession) {
    val job = session.job ?: return
    val shadow = androidx.compose.ui.graphics.Shadow(Color.Black.copy(alpha = 0.45f), blurRadius = 8f)
    Row(Modifier.fillMaxWidth().padding(start = 4.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        if (job.isVerify) Icon(Icons.Rounded.VerifiedUser, null, tint = Brand.mint, modifier = Modifier.size(14.dp))
        Text(
            if (job.isVerify) "VERIFY · MATCHING THE LISTING" else "MINT CONDITION, MEASURED.",
            style = rounded(Type.caption, FontWeight.Bold, tracking = 2f).copy(shadow = shadow),
            color = Brand.mint, maxLines = 1,
        )
    }
}

// Bottom: cancel, and the scan button inside the coverage ring.
@Composable
private fun Controls(session: CaptureSession, askToDiscard: () -> Unit) {
    val ready = session.phase == CaptureSession.Phase.Ready
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier
                .size(50.dp)
                .alpha(if (ready) 1f else 0f)
                .clip(CircleShape)
                .background(Color(0x8C1C2120))
                .clickable(enabled = ready, role = Role.Button) {
                    if (session.passes.isEmpty()) session.cancelJob() else askToDiscard()
                }
                .semantics { contentDescription = "Cancel this scan" },
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Rounded.Close, null, tint = Color.White, modifier = Modifier.size(20.dp))
        }
        Spacer(Modifier.weight(1f))
        Box(
            Modifier
                .size(214.dp)
                .clip(CircleShape)
                .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null, role = Role.Button) { session.primaryAction() }
                .semantics { contentDescription = if (session.isRecording) "Stop this pass" else "Start scanning" },
        ) {
            CoverageRing(session)
        }
        Spacer(Modifier.weight(1f))
        Spacer(Modifier.width(50.dp))
    }
}

/**
 * Where the camera is focusing, after a tap: a square that drops onto the point, like the camera app's, then fades.
 * `point` is in the HUD's own pixels.
 */
@Composable
private fun FocusMark(point: Offset) {
    val side = 78.dp
    val scale = remember { Animatable(1.45f) }
    val alpha = remember { Animatable(1f) }
    LaunchedEffect(Unit) {
        launch { scale.animateTo(1f, spring(dampingRatio = 0.62f, stiffness = 400f)) }
        delay(1300)
        alpha.animateTo(0f, tween(500))
    }
    val half = with(LocalDensity.current) { side.toPx() / 2 }
    Canvas(
        Modifier
            .offset { IntOffset((point.x - half).toInt(), (point.y - half).toInt()) }
            .size(side)
            .graphicsLayer { scaleX = scale.value; scaleY = scale.value; this.alpha = alpha.value },
    ) {
        val s = size.width
        val stroke = 2.dp.toPx()
        glowStroke(Path().apply { addRoundRect(androidx.compose.ui.geometry.RoundRect(0f, 0f, s, s, 7.dp.toPx(), 7.dp.toPx())) }, Brand.mint.copy(alpha = 0.7f), stroke * 2, 6.dp.toPx())
        drawRoundRect(Brand.mint, cornerRadius = androidx.compose.ui.geometry.CornerRadius(7.dp.toPx()), style = Stroke(stroke))
        val m = s / 2
        val t = 8.dp.toPx()
        for ((a, b) in listOf(Offset(m, 0f) to Offset(m, t), Offset(m, s) to Offset(m, s - t), Offset(0f, m) to Offset(t, m), Offset(s, m) to Offset(s - t, m))) {
            drawLine(Brand.mint, a, b, stroke, StrokeCap.Round)
        }
    }
}

/** A blurred stroke behind a crisp one: SwiftUI's `drawLayer { addFilter(.blur) }` glow. */
fun DrawScope.glowStroke(path: Path, color: Color, width: Float, blur: Float) {
    val paint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG).apply {
        style = android.graphics.Paint.Style.STROKE
        strokeWidth = width
        strokeCap = android.graphics.Paint.Cap.ROUND
        this.color = color.toArgb()
        maskFilter = BlurMaskFilter(blur, BlurMaskFilter.Blur.NORMAL)
    }
    drawIntoCanvas { it.nativeCanvas.drawPath(path.asAndroidPath(), paint) }
}

/**
 * The scan button inside the coverage ring: 72 ticks, one per 5° of turn, filling clockwise from the top as the
 * paper turns clockwise (a tick lights mint once the side it stands for has been seen head-on). While recording, a
 * bright spot marks how far the paper has turned. At a full lap the ring stays full and stops changing, whatever
 * the touch-ups do. Tap: start / stop.
 */
@Composable
private fun CoverageRing(session: CaptureSession) {
    val time by animationTime()
    val finished = session.phase.isFinished
    val ringScale by animateFloatAsState(if (finished) 1.05f else 1f, spring(dampingRatio = 0.55f, stiffness = 250f), label = "ring")
    Box(Modifier.fillMaxSize().scale(ringScale), contentAlignment = Alignment.Center) {
        Canvas(Modifier.fillMaxSize()) {
            val c = Offset(size.width / 2, size.height / 2)
            val r = min(size.width, size.height) / 2 - 16.dp.toPx()
            val t = time
            val recording = session.isRecording
            val live = recording || finished
            val lap = session.lapCompletedAt
            val done = lap != null
            val n = CaptureSession.TICK_COUNT
            val spotDeg = (session.ringTurn * 180 / PI) % 360
            val sweep: Double? = lap?.let { t - it / 1000.0 }?.let { if (it < 1.1) it / 1.1 * 360 else null }
            val pt = 1.dp.toPx()

            val dim = Path()
            val lit = Path()
            val hot = Path()
            for (j in 0 until n) {
                val deg = j * 360.0 / n
                val a = (deg - 90) * PI / 180
                // Tick j: the side that faces the camera once the paper has turned j × 5° clockwise.
                var level = if (live) session.ticks[(n - j) % n] else 0.0
                if (session.phase == CaptureSession.Phase.Ready) level = 0.22 * max(0.0, sin(t * 2.2 - j * 0.17))
                var boost = 0.0
                if (recording && !done && session.paperSeen) {
                    val behind = ((spotDeg - deg) % 360 + 360) % 360
                    if (behind < 30) boost = 1 - behind / 30 else if (behind > 355) boost = (behind - 355) / 5
                }
                if (sweep != null) {
                    val d = abs((deg - sweep) % 360)
                    boost = max(boost, max(0.0, 1 - min(d, 360 - d) / 24))
                }
                val len = ((8 + 6 * level + 6 * boost) * pt).toFloat()
                val ca = cos(a).toFloat()
                val sa = sin(a).toFloat()
                val p0 = Offset(c.x + ca * (r - len / 2), c.y + sa * (r - len / 2))
                val p1 = Offset(c.x + ca * (r + len / 2), c.y + sa * (r + len / 2))
                when {
                    boost > 0.4 -> hot.segment(p0, p1)
                    level > 0.85 -> lit.segment(p0, p1)
                    level > 0.03 -> drawLine(Brand.mint.copy(alpha = (0.3 + 0.6 * level).toFloat()), p0, p1, 3 * pt, StrokeCap.Round)
                    else -> dim.segment(p0, p1)
                }
            }
            drawPath(dim, Color.White.copy(alpha = 0.25f), style = Stroke(3 * pt, cap = StrokeCap.Round))
            glowStroke(lit, Brand.mint.copy(alpha = 0.85f), 5 * pt, 5 * pt)
            glowStroke(hot, Color.White.copy(alpha = 0.8f), 5 * pt, 5 * pt)
            drawPath(lit, Brand.mint, style = Stroke(3.2f * pt, cap = StrokeCap.Round))
            drawPath(hot, Color.White, style = Stroke(3.4f * pt, cap = StrokeCap.Round))
        }
        RingCentre(session)
    }
}

private fun Path.segment(a: Offset, b: Offset) {
    moveTo(a.x, a.y)
    lineTo(b.x, b.y)
}

@Composable
private fun RingCentre(session: CaptureSession) {
    when (session.phase) {
        CaptureSession.Phase.Recording -> {
            val done = session.percent >= 100
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(
                    buildAnnotatedString {
                        append("${session.percent}")
                        withStyle(SpanStyle(fontSize = 22.sp, fontWeight = FontWeight.Bold)) { append("%") }
                    },
                    style = rounded(48.sp, FontWeight.Black).copy(
                        shadow = if (done) androidx.compose.ui.graphics.Shadow(Brand.mint.copy(alpha = 0.6f), blurRadius = 24f) else null,
                        fontFeatureSettings = "tnum",
                    ),
                    color = if (done) Brand.mint else Color.White,
                )
                Text(if (done) "FULL LAP" else "OF A LAP", style = rounded(Type.caption, FontWeight.Bold, tracking = 1.5f), color = Brand.mint)
                Row(Modifier.padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                    Box(Modifier.size(10.dp).clip(RoundedCornerShape(2.5.dp)).background(Brand.red))
                    Text("TAP TO STOP", style = rounded(Type.caption2, FontWeight.Bold, tracking = 1.1f), color = Color.White.copy(alpha = 0.7f))
                }
            }
        }
        CaptureSession.Phase.Saving, CaptureSession.Phase.Review ->
            CircularProgressIndicator(color = Color.White, strokeWidth = 3.dp, modifier = Modifier.size(28.dp))
        else -> Box(
            Modifier.size(128.dp).glow(Brand.mint.copy(alpha = 0.5f), 18.dp, CircleShape).clip(CircleShape).background(Color.White),
            contentAlignment = Alignment.Center,
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text("Scan", style = rounded(26.sp, FontWeight.Black), color = Brand.stageBg)
                if (session.nextPass > 1) {
                    Text("PASS ${session.nextPass}", style = rounded(Type.caption2, FontWeight.Bold, tracking = 1.2f), color = Brand.stageBg)
                }
            }
        }
    }
}

@Composable
private fun Caption(session: CaptureSession) {
    val now by periodicTime()
    val (text, icon) = captionContent(session, now)
    AnimatedContent(
        targetState = text to icon,
        transitionSpec = { (fadeIn(tween(250)) + slideInVertically { it / 2 }) togetherWith (fadeOut(tween(250)) + slideOutVertically { -it / 2 }) },
        label = "caption",
    ) { (t, i) ->
        if (t.isEmpty() || i == null) {
            Spacer(Modifier.size(0.dp, 44.dp))
        } else {
            Row(
                Modifier.clip(RoundedCornerShape(50)).background(Color(0x8C1C2120)).padding(horizontal = 18.dp, vertical = 11.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Icon(i, null, tint = Color.White, modifier = Modifier.size(19.dp))
                Text(t, style = rounded(Type.headline, FontWeight.SemiBold), color = Color.White, textAlign = TextAlign.Center)
            }
        }
    }
}

private fun captionContent(session: CaptureSession, now: Double): Pair<String, ImageVector?> = when (session.phase) {
    CaptureSession.Phase.Ready -> when {
        session.passes.isNotEmpty() -> "Pass ${session.nextPass} · flip it or try another angle" to Icons.Rounded.Flip
        session.job?.isVerify == true -> "Tap the item you're buying to focus" to Icons.Rounded.VerifiedUser
        else -> "Tap the item to focus · then Scan" to Icons.Rounded.CenterFocusWeak
    }
    CaptureSession.Phase.Recording -> {
        val t = session.recordStart?.let { now - it / 1000.0 } ?: 0.0
        val left = kotlin.math.ceil(CaptureSession.MAX_PASS_SECONDS - t).toInt()
        when {
            left <= 8 -> "Wrapping up in $left s" to Icons.Rounded.Timer
            session.lapCompletedAt != null -> "Full lap · touch up, then tap stop" to Icons.Rounded.Verified
            !session.paperSeen -> "Keep the item in view" to Icons.Rounded.CenterFocusWeak
            else -> "Turn it slowly clockwise" to Icons.Rounded.Refresh
        }
    }
    CaptureSession.Phase.Saving -> "Saving pass ${session.nextPass}…" to Icons.Rounded.Verified
    else -> "" to null
}
