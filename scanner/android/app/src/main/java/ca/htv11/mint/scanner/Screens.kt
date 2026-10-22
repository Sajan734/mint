package ca.htv11.mint.scanner

import android.content.Context
import android.content.Intent
import android.graphics.BitmapFactory
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Autorenew
import androidx.compose.material.icons.rounded.CenterFocusWeak
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.CloudOff
import androidx.compose.material.icons.rounded.Laptop
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.automirrored.rounded.Send
import androidx.compose.material.icons.rounded.Share
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.RoundRect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathFillType
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import kotlin.math.min
import kotlin.math.sin

// The full-screen moments around the scanner: waiting for the dashboard, sending, done, failed, and the card after
// each pass.

/** Covers the live camera behind a full-screen moment. Light: paper over the camera, like the website's pages. */
@Composable
private fun Backdrop() {
    Box(Modifier.fillMaxSize().background(Brand.paper.copy(alpha = 0.97f)))
}

/** Rings rippling out from the middle (done). */
@Composable
private fun Ripples(modifier: Modifier, color: Color = Brand.mint) {
    val time by animationTime()
    Canvas(modifier) {
        val c = Offset(size.width / 2, size.height / 2)
        val start = 46.dp.toPx()
        for (k in 0 until 3) {
            val f = ((time / 2.4 + k / 3.0) % 1.0).toFloat()
            val r = start + f * (min(size.width, size.height) / 2 - start)
            drawCircle(color.copy(alpha = 0.5f * (1 - f)), r, c, style = Stroke(1.5.dp.toPx()))
        }
    }
}

// MARK: - Buttons (SwiftUI's .borderedProminent in mint, and .bordered in ink)

@Composable
fun MintButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    prominent: Boolean = false,
    minHeight: Dp = 50.dp,
    content: @Composable RowScope.(Color) -> Unit,
) {
    val fg = if (prominent) Brand.stageBg else Brand.ink
    Row(
        modifier
            .defaultMinSize(minHeight = minHeight)
            .clip(RoundedCornerShape(14.dp))
            .background(if (prominent) Brand.mint else Brand.ink.copy(alpha = 0.08f))
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically,
    ) { content(fg) }
}

@Composable
private fun ButtonLabel(text: String, icon: androidx.compose.ui.graphics.vector.ImageVector?, color: Color, weight: FontWeight = FontWeight.SemiBold, size: androidx.compose.ui.unit.TextUnit = Type.body) {
    if (icon != null) Icon(icon, null, tint = color, modifier = Modifier.size(20.dp))
    Text(text, style = rounded(size, weight), color = color)
}

// MARK: - Waiting for the dashboard

/** The camera window on the waiting screen: a square a little above the middle of the screen (the middle of the camera picture). */
private fun qrWindow(size: Size, density: Float): Rect {
    val side = min(size.width - 110 * density, 260 * density)
    return Rect(Offset((size.width - side) / 2, size.height / 2 - side / 2 - 60 * density), Size(side, side))
}

@Composable
fun WaitingScreen(session: CaptureSession, cameraBounds: MutableState<Rect>) {
    val density = LocalDensity.current.density
    var origin by remember { mutableStateOf(Offset.Zero) }
    BoxWithConstraints(Modifier.fillMaxSize().onGloballyPositioned { origin = it.boundsInWindow().topLeft }) {
        val full = Size(constraints.maxWidth.toFloat(), constraints.maxHeight.toFloat())
        val window = qrWindow(full, density)
        // Paper over the camera, with a window in the middle where the live camera shows: you can see the QR code
        // you're aiming at. The camera reads the whole frame, so the code needn't sit exactly in the window.
        Canvas(Modifier.fillMaxSize()) {
            val p = Path().apply {
                fillType = PathFillType.EvenOdd
                addRect(Rect(Offset.Zero, size))
                addRoundRect(RoundRect(window, CornerRadius(30 * density)))
            }
            drawPath(p, Brand.paper.copy(alpha = 0.96f))
        }
        QRWindow(
            Modifier
                .offset { IntOffset(window.left.toInt(), window.top.toInt()) }
                .size((window.width / density).dp)
                .pointerInput(Unit) {
                    // A soft QR: tap it.
                    detectTapGestures { focusOnCamera(session, cameraBounds.value, it + origin + window.topLeft) }
                },
        )
        Column(
            Modifier.fillMaxWidth().padding(top = (window.bottom / density + 26).dp).padding(horizontal = 20.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("Ready when you are", style = rounded(30.sp, FontWeight.Black), color = Brand.ink)
            Text(
                buildAnnotatedString {
                    append("Point this phone at the ")
                    withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append("QR code") }
                    append(" on the website\n(Scan an item, or Scan on a listing).")
                },
                style = rounded(Type.body), color = Brand.ink.copy(alpha = 0.75f), textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 10.dp),
            )
            if (session.link == CaptureSession.Link.ONLINE) LinkStatus(session.link, Modifier.padding(top = 18.dp))
        }
        Column(Modifier.fillMaxSize().safeDrawingPadding().padding(start = 20.dp, end = 20.dp, bottom = 12.dp)) {
            Row(Modifier.padding(top = 6.dp)) { MintMark() }
            Spacer(Modifier.weight(1f))
            MintButton(session::scanWithoutDashboard, Modifier.fillMaxWidth()) { ButtonLabel("Scan without the dashboard", Icons.Rounded.CenterFocusWeak, it, size = Type.subheadline) }
        }
    }
}

@Composable
private fun LinkStatus(link: CaptureSession.Link, modifier: Modifier) {
    val (target, text) = when (link) {
        CaptureSession.Link.ONLINE -> Brand.mint to "Connected · New product opens here by itself"
        CaptureSession.Link.CONNECTING -> Brand.ink.copy(alpha = 0.6f) to "Connecting to your dashboard…"
        CaptureSession.Link.OFFLINE -> Brand.amber to "Can't reach your dashboard. Check the Wi-Fi."
        CaptureSession.Link.NOT_SET_UP -> Brand.amber to "Dashboard link isn't set up on this phone"
    }
    val color by animateColorAsState(target, label = "link")
    Row(
        modifier.clip(RoundedCornerShape(50)).background(Brand.ink.copy(alpha = 0.06f)).padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        GlowDot(color, 8.dp, glow = if (link == CaptureSession.Link.ONLINE) 5.dp else 0.dp)
        Text(text, style = rounded(Type.footnote, FontWeight.SemiBold), color = Brand.ink)
    }
}

/** Corner marks and a sweeping line over the camera window on the waiting screen. */
@Composable
private fun QRWindow(modifier: Modifier) {
    val time by animationTime()
    Canvas(modifier) {
        val inset = 2.dp.toPx()
        val r = Rect(inset, inset, size.width - inset, size.height - inset)
        val len = 34.dp.toPx()
        val bend = 16.dp.toPx()
        val marks = Path()
        for ((c, dx, dy) in listOf(Triple(r.topLeft, 1f, 1f), Triple(r.topRight, -1f, 1f), Triple(r.bottomLeft, 1f, -1f), Triple(r.bottomRight, -1f, -1f))) {
            marks.moveTo(c.x + dx * len, c.y)
            marks.lineTo(c.x + dx * bend, c.y)
            marks.quadraticTo(c.x, c.y, c.x, c.y + dy * bend)
            marks.lineTo(c.x, c.y + dy * len)
        }
        drawPath(marks, Brand.mint, style = Stroke(5.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round))
        // A line sweeping down and up, like a reader at work.
        val f = ((sin(time * 1.6) + 1) / 2).toFloat()
        val pad = 22.dp.toPx()
        val y = r.top + pad + f * (r.height - 2 * pad)
        val line = Path().apply { moveTo(r.left + pad, y); lineTo(r.right - pad, y) }
        glowStroke(line, Brand.mint.copy(alpha = 0.9f), 2.dp.toPx(), 6.dp.toPx())
        drawLine(Brand.mint, Offset(r.left + pad, y), Offset(r.right - pad, y), 2.dp.toPx())
    }
}

// MARK: - After each pass: another pass, or send them all

@Composable
fun ReviewCard(session: CaptureSession) {
    val passes = session.passes
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(26.dp)).background(Color(0xF2F2F1EE)).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text(if (passes.size == 1) "Pass saved" else "${passes.size} passes saved", style = rounded(Type.title2, FontWeight.Black), color = Brand.ink)
            Spacer(Modifier.weight(1f))
            passes.lastOrNull()?.let { last ->
                Text(
                    "%.0f s · %d frames".format(last.seconds, last.frames),
                    style = rounded(Type.subheadline).copy(fontFeatureSettings = "tnum"), color = Brand.ink.copy(alpha = 0.55f),
                )
            }
        }
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            for (p in passes) {
                Box(contentAlignment = Alignment.BottomStart) {
                    Thumbnail(p.directory, 58.dp)
                    Box(Modifier.padding(4.dp).size(20.dp).clip(CircleShape).background(Brand.mint), contentAlignment = Alignment.Center) {
                        Text("${p.pass}", style = rounded(Type.caption, FontWeight.Black), color = Brand.stageBg)
                    }
                }
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            MintButton(session::scanAgain, Modifier.weight(1f)) { ButtonLabel("Scan again", Icons.Rounded.Autorenew, it) }
            MintButton(session::finish, Modifier.weight(1f), prominent = true) { ButtonLabel("Done", Icons.AutoMirrored.Rounded.Send, it, FontWeight.Bold) }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                buildAnnotatedString {
                    append("Flip it over or try another angle with ")
                    withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append("Scan again") }
                    append(".")
                },
                style = rounded(Type.footnote), color = Brand.ink.copy(alpha = 0.55f), modifier = Modifier.weight(1f),
            )
            Text(
                "Discard pass ${passes.lastOrNull()?.pass ?: 1}",
                style = rounded(Type.footnote, FontWeight.SemiBold), color = Brand.red,
                modifier = Modifier.clip(RoundedCornerShape(8.dp)).clickable(onClick = session::discardLastPass).padding(6.dp),
            )
        }
    }
}

@Composable
fun Thumbnail(directory: File, size: Dp) {
    val image by produceState<ImageBitmap?>(null, directory) {
        value = withContext(Dispatchers.IO) {
            // The recorder writes thumb.jpg just after the first frame: wait for it briefly.
            repeat(20) {
                val f = File(directory, "thumb.jpg")
                if (f.length() > 0) return@withContext BitmapFactory.decodeFile(f.path)?.asImageBitmap()
                kotlinx.coroutines.delay(100)
            }
            null
        }
    }
    val shape = RoundedCornerShape(size * 0.22f)
    val img = image
    if (img != null) {
        Image(img, null, contentScale = ContentScale.Crop, modifier = Modifier.size(size).clip(shape).border(2.dp, Brand.mint, shape))
    } else {
        Box(Modifier.size(size).clip(shape).background(Brand.mint.copy(alpha = 0.25f)))
    }
}

// MARK: - Sending

@Composable
fun SendingScreen(progress: Double, passes: Int) {
    val shown by animateFloatAsState(progress.toFloat(), tween(300), label = "progress")
    Box(Modifier.fillMaxSize()) {
        Backdrop()
        Column(Modifier.align(Alignment.Center), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(26.dp)) {
            Box(Modifier.size(210.dp), contentAlignment = Alignment.Center) {
                Canvas(Modifier.fillMaxSize()) {
                    val w = 14.dp.toPx()
                    val inset = w / 2
                    val arc = Size(size.width - w, size.height - w)
                    drawCircle(Brand.ink.copy(alpha = 0.12f), size.width / 2 - inset, style = Stroke(w))
                    val sweep = 360f * maxOf(0.02f, shown)
                    val path = Path().apply { addArc(Rect(Offset(inset, inset), arc), -90f, sweep) }
                    glowStroke(path, Brand.mint.copy(alpha = 0.7f), w, 12.dp.toPx())
                    drawArc(Brand.mint, -90f, sweep, false, Offset(inset, inset), arc, style = Stroke(w, cap = StrokeCap.Round))
                }
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("${(progress * 100).toInt()}%", style = rounded(50.sp, FontWeight.Black).copy(fontFeatureSettings = "tnum"), color = Brand.ink)
                    Text("SENDING", style = rounded(Type.caption, FontWeight.Bold, tracking = 2f), color = Brand.mintInk)
                }
            }
            Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Sending to Mint", style = rounded(Type.title2, FontWeight.Black), color = Brand.ink)
                Text("$passes pass${if (passes == 1) "" else "es"} · keep the app open", style = rounded(Type.subheadline), color = Brand.ink.copy(alpha = 0.65f))
            }
        }
    }
}

// MARK: - Done: look back at the computer

@Composable
fun FinishedScreen(session: CaptureSession) {
    val appear = remember { Animatable(0f) }
    LaunchedEffect(Unit) {
        kotlinx.coroutines.delay(100)
        appear.animateTo(1f, spring(dampingRatio = 0.6f, stiffness = 160f))
    }
    val verify = session.job?.isVerify == true
    Box(Modifier.fillMaxSize()) {
        Backdrop()
        Column(
            Modifier.fillMaxSize().safeDrawingPadding().padding(start = 20.dp, end = 20.dp, bottom = 12.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Row(Modifier.fillMaxWidth().padding(top = 6.dp)) { MintMark() }
            Spacer(Modifier.weight(1f))
            Box(
                Modifier.size(320.dp).graphicsLayer {
                    val s = 0.4f + 0.6f * appear.value
                    scaleX = s; scaleY = s; alpha = appear.value.coerceIn(0f, 1f)
                },
                contentAlignment = Alignment.Center,
            ) {
                Ripples(Modifier.fillMaxSize())
                Box(Modifier.size(118.dp).glow(Brand.mint.copy(alpha = 0.8f), 30.dp, CircleShape).clip(CircleShape).background(Brand.mint), contentAlignment = Alignment.Center) {
                    Icon(Icons.Rounded.Check, null, tint = Brand.stageBg, modifier = Modifier.size(64.dp))
                }
            }
            Text("You're done here", style = rounded(Type.title3, FontWeight.SemiBold), color = Brand.mintInk, modifier = Modifier.padding(top = 6.dp))
            Row(Modifier.padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Icon(Icons.Rounded.Laptop, null, tint = Brand.ink, modifier = Modifier.size(36.dp))
                Text(
                    if (verify) "Look back at\nthe listing" else "Look back at\nyour computer",
                    style = rounded(34.sp, FontWeight.Black).copy(lineHeight = 38.sp), color = Brand.ink,
                )
            }
            Text(
                when {
                    verify -> "Mint is checking this scan against the seller's."
                    session.job?.fromDashboard == false -> "Your scan is on its way. Open your dashboard to see it."
                    else -> "Your 3D scan and listing are being built there."
                },
                style = rounded(Type.body), color = Brand.ink.copy(alpha = 0.7f), textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 12.dp),
            )
            Spacer(Modifier.weight(1f))
            MintButton(session::backToWaiting, Modifier.fillMaxWidth(), prominent = true, minHeight = 52.dp) {
                ButtonLabel("Next product", null, it, FontWeight.Bold)
            }
            Text("Or point this phone at the next QR code.", style = rounded(Type.footnote), color = Brand.ink.copy(alpha = 0.5f), modifier = Modifier.padding(top = 8.dp))
        }
    }
}

// MARK: - Couldn't send (or couldn't record)

@Composable
fun FailedScreen(message: String, session: CaptureSession) {
    val context = LocalContext.current
    val passes = session.passes
    val zip by produceState<File?>(null, session.job?.scanId, passes.size) {
        val id = session.job?.scanId
        value = if (id == null || passes.isEmpty()) null else withContext(Dispatchers.IO) { runCatching { ScanExport.zip(context, id) }.getOrNull() }
    }
    Box(Modifier.fillMaxSize()) {
        Backdrop()
        Column(
            Modifier.fillMaxSize().safeDrawingPadding().padding(start = 20.dp, end = 20.dp, bottom = 12.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Spacer(Modifier.weight(1f))
            Icon(Icons.Rounded.CloudOff, null, tint = Brand.amber, modifier = Modifier.size(58.dp))
            Text(if (passes.isEmpty()) "Something went wrong" else "Couldn't send it", style = rounded(Type.title, FontWeight.Black), color = Brand.ink)
            Text(message, style = rounded(Type.footnote), color = Brand.ink.copy(alpha = 0.65f), textAlign = TextAlign.Center, maxLines = 4, overflow = TextOverflow.Ellipsis)
            if (passes.isNotEmpty()) {
                Text(
                    "Your ${if (passes.size == 1) "scan is" else "${passes.size} passes are"} saved on this phone.",
                    style = rounded(Type.subheadline), color = Brand.ink.copy(alpha = 0.8f),
                )
            }
            Spacer(Modifier.weight(1f))
            if (passes.isNotEmpty()) {
                MintButton(session::retrySend, Modifier.fillMaxWidth(), prominent = true, minHeight = 52.dp) { ButtonLabel("Try again", Icons.Rounded.Refresh, it, FontWeight.Bold) }
                zip?.let { f ->
                    MintButton({ ScanExport.share(context, f) }, Modifier.fillMaxWidth(), minHeight = 48.dp) { ButtonLabel("Share the files", Icons.Rounded.Share, it) }
                }
            }
            Text(
                "Back to start", style = rounded(Type.subheadline, FontWeight.SemiBold), color = Brand.ink.copy(alpha = 0.7f),
                modifier = Modifier.clip(RoundedCornerShape(8.dp)).clickable(onClick = session::backToWaiting).padding(horizontal = 10.dp, vertical = 6.dp),
            )
        }
    }
}

object ScanExport {
    /** Zips a scan folder, every pass, into cache/exports/mint-{id}.zip (`{pass}/video.mp4`, …). */
    fun zip(context: Context, scanId: String): File {
        val dir = VideoRecorder.folder(context, scanId)
        val exports = File(context.cacheDir, "exports").apply { mkdirs() }
        val dest = File(exports, "mint-${scanId.take(8)}.zip")
        dest.delete()
        ZipOutputStream(dest.outputStream().buffered()).use { zip ->
            dir.walkTopDown().filter { it.isFile }.forEach { f ->
                zip.putNextEntry(ZipEntry("$scanId/${f.relativeTo(dir).invariantSeparatorsPath}"))
                f.inputStream().use { it.copyTo(zip) }
                zip.closeEntry()
            }
        }
        return dest
    }

    fun share(context: Context, file: File) {
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", file)
        val send = Intent(Intent.ACTION_SEND).apply {
            type = "application/zip"
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        context.startActivity(Intent.createChooser(send, "Share the files").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}
