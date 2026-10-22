package ca.htv11.mint.coveragekit

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

private const val PI_F = PI.toFloat()

// Ported from scanner/ios/Packages/CoverageKit/Tests (same scenes, same pass conditions), plus the pieces that
// live in the app on iOS (link parsing, upload naming).

class GeometryTest {
    @Test fun rowMajorPutsTranslationInLastColumn() {
        // Column-major identity with translation (1, 2, 3), as Pose.toMatrix writes it.
        val m = floatArrayOf(1f, 0f, 0f, 0f, 0f, 1f, 0f, 0f, 0f, 0f, 1f, 0f, 1f, 2f, 3f, 1f)
        val r = Geometry.rowMajor4(m)
        assertEquals(1.0, r[0][3], 0.0)
        assertEquals(2.0, r[1][3], 0.0)
        assertEquals(3.0, r[2][3], 0.0)
        assertEquals(listOf(0.0, 0.0, 0.0, 1.0), r[3])
    }

    @Test fun scaleIntrinsics() {
        // K for 1920×1440 → 960×720.
        val k = CameraK(1500f, 1500f, 960f, 720f).scaled(0.5f, 0.5f)
        assertEquals(listOf(listOf(750.0, 0.0, 480.0), listOf(0.0, 750.0, 360.0), listOf(0.0, 0.0, 1.0)), k.rowMajor())
    }
}

class SharpnessTest {
    private fun checker() = GrayImage(16, 16, ByteArray(256) { if ((it % 16 + it / 16) % 2 == 0) 0 else 255.toByte() })

    @Test fun laplacianVariance() {
        val flat = GrayImage(16, 16, ByteArray(256) { 128.toByte() })
        val ramp = GrayImage(16, 16, ByteArray(256) { ((it % 16) * 16).toByte() })
        assertEquals(0.0, FastSharpness.measure(flat)!!.sharpness, 0.0)
        assertEquals(0.0, FastSharpness.measure(ramp)!!.sharpness, 1e-9)   // smooth gradient = no detail
        assertTrue(FastSharpness.measure(checker())!!.sharpness > 1000)
    }

    @Test fun scalesAPaddedPlane() {
        // 8×4 plane with 4 bytes of row padding, scaled to 4×3: sharpness of a flat image is 0.
        val bytes = ByteArray(12 * 4)
        for (y in 0 until 4) for (x in 0 until 8) bytes[y * 12 + x] = 100
        val r = FastSharpness.measure(bytes, 8, 4, 12, thumbWidth = 4, thumbHeight = 3)!!
        assertEquals(0.0, r.sharpness, 1e-6)
        assertEquals(100.0, r.meanLuma, 0.5)
    }

    @Test fun downscaleHonoursRowStride() {
        // 4×2 image stored with 2 bytes of row padding.
        val bytes = byteArrayOf(10, 10, 50, 50, 0, 0, 10, 10, 50, 50, 0, 0)
        val img = FastSharpness.downscale(bytes, 4, 2, 6, 2, 1)
        assertEquals(listOf<Byte>(10, 50), img.pixels.toList())
    }
}

class CaptureJsonTest {
    private val identity = Geometry.rowMajor4(floatArrayOf(1f, 0f, 0f, 0f, 0f, 1f, 0f, 0f, 0f, 0f, 1f, 0f, 0f, 0f, 0f, 1f))

    @Test fun poseRecordIsOneSortedLine() {
        val r = PoseRecord(
            frame = 0, tMs = 0, poseWorld = identity, pose = null, intrinsics = CameraK(1f, 1f, 0f, 0f).rowMajor(),
            tracking = "normal", state = "handling", sharpness = 0.0,
        )
        val line = CaptureJson.encode(r.toJson())
        assertFalse(line.contains("\n"))
        assertFalse(line.contains("\"pose\""))   // absent while handling
        assertFalse(line.contains("\"segment\""))  // optional fields are omitted, not null
        val keys = Regex("\"([a-z_]+)\":").findAll(line).map { it.groupValues[1] }.toList()
        assertEquals(listOf("counted", "frame", "intrinsics", "pose_world", "sharpness", "state", "t_ms", "tracking"), keys)
        assertTrue(line.startsWith("{\"counted\":false,\"frame\":0,\"intrinsics\":[[1,0,0],[0,1,0],[0,0,1]]"))
    }

    @Test fun numbersAndStrings() {
        assertEquals("[143.2,-0.5,3,null]", CaptureJson.encode(listOf(143.2, -0.5, 3.0, Double.NaN)))
        assertEquals("\"a/b \\\"c\\\"\\n\"", CaptureJson.encode("a/b \"c\"\n"))   // slashes not escaped
    }

    @Test fun captureInfoPretty() {
        val info = CaptureInfo(
            scanId = "s", device = "d", os = "16", createdAt = "2026-10-17T00:00:00Z", durationMs = 1000, video = "video.mp4",
            videoWidth = 960, videoHeight = 720, videoFrames = 30, sensorWidth = 1920, sensorHeight = 1440,
            orientation = "sensor_landscape", exposureLocked = true, mode = "turntable", coveragePct = 54, pass = 1,
            kind = "listing",
        )
        val json = CaptureJson.encode(info.toJson(), pretty = true)
        assertTrue(json.startsWith("{\n  \"coverage_pct\" : 54,\n  \"created_at\" : "))
        assertFalse(json.contains("listing_scan_id"))
        assertTrue(json.endsWith("\n}"))
    }
}

class ScanLinksTest {
    private val id = "0b5f3c9e-6a7d-4c1e-9f00-1234567890ab"
    private val other = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"

    @Test fun scanLinks() {
        assertEquals(ScanLinks.Link(id, null), ScanLinks.parse("mint://scan?id=$id"))
        assertEquals(ScanLinks.Link(id, null), ScanLinks.parse("  mintscan://scan?scan_id=${id.uppercase()}\n"))
        assertNull(ScanLinks.parse("mint://scan?id=not-a-uuid"))
        assertNull(ScanLinks.parse("https://scan?id=$id"))
        assertNull(ScanLinks.parse("mint://other?id=$id"))
        assertNull(ScanLinks.parse("hello world"))
    }

    @Test fun verifyLinks() {
        assertEquals(ScanLinks.Link(id, other), ScanLinks.parse("mint://verify?id=$id&listing=${other.uppercase()}"))
        assertEquals(ScanLinks.Link(id, "demo-listing_1"), ScanLinks.parse("mint://verify?id=$id&listing_scan_id=demo-listing_1"))
        assertNull(ScanLinks.parse("mint://verify?id=$id"))                        // no listing
        assertNull(ScanLinks.parse("mint://verify?id=$id&listing=$id"))            // itself
        assertNull(ScanLinks.parse("mint://verify?id=$id&listing=bad%20id"))       // not a plain id
    }
}

class UploadPlanTest {
    private fun pass(root: File, n: Int, thumb: Boolean = n == 1): UploadPlan.Pass {
        val dir = File(root, "pass$n").apply { mkdirs() }
        for (f in listOf("video.mp4", "poses.jsonl", "capture.json") + if (thumb) listOf("thumb.jpg") else emptyList()) File(dir, f).writeText("x")
        return UploadPlan.Pass(dir, n)
    }

    @Test fun listingOrderEndsWithTheMainVideo() {
        val root = Files.createTempDirectory("plan").toFile()
        val keys = UploadPlan.plan(listOf(pass(root, 1), pass(root, 2), pass(root, 3))).map { it.key }
        assertEquals(
            listOf(
                "pass3.poses.jsonl", "pass3.capture.json", "pass3.mp4",
                "bottom.poses.jsonl", "bottom.capture.json", "bottom.mp4",
                "poses.jsonl", "capture.json", "thumb.jpg", "video.mp4",
            ),
            keys,
        )
        assertEquals("video/mp4", UploadPlan.plan(listOf(pass(root, 1))).last().type)
    }

    @Test fun verifyRescansNeverLookLikeAListing() {
        val root = Files.createTempDirectory("plan").toFile()
        val keys = UploadPlan.plan(listOf(pass(root, 1), pass(root, 2)), verify = true).map { it.key }
        assertEquals(
            listOf("rescan2.poses.jsonl", "rescan2.capture.json", "rescan2.mp4", "rescan.poses.jsonl", "rescan.capture.json", "thumb.jpg", "rescan.mp4"),
            keys,
        )
        assertFalse(keys.contains("video.mp4"))
    }
}

class ItemOnPaperTest {
    /**
     * A beige table, a tilted ruled sheet (lines run edge to edge), a dark item on it with a soft
     * shadow, a hand reaching onto the sheet's edge, and a knee in the corner of the frame.
     */
    private fun scene(): ImageGrid {
        val w = 160
        val h = 120
        val luma = IntArray(w * h) { 180 }
        val chroma = IntArray(w * h) { 42 }
        val cx = 80f
        val cy = 55f
        val a = 0.35f
        val ux = cos(a); val uy = sin(a)
        val vx = -sin(a); val vy = cos(a)
        fun len(x: Float, y: Float) = sqrt(x * x + y * y)
        for (y in 0 until h) for (x in 0 until w) {
            val dx = x - cx
            val dy = y - cy
            val i = y * w + x
            val pu = dx * ux + dy * uy
            val pv = dx * vx + dy * vy
            if (abs(pu) < 45 && abs(pv) < 34) {
                luma[i] = 232; chroma[i] = 3                                           // paper
                if ((pv + 100).toInt() % 7 == 0) { luma[i] = 190; chroma[i] = 30 }     // ruled line, edge to edge
            }
            if (len(dx / 14, dy / 9) < 1) { luma[i] = 35; chroma[i] = 4 }              // the item
            else if (len((dx - 3) / 17, (dy - 4) / 12) < 1 && luma[i] > 200) luma[i] = 160  // shadow
            if (len(x - (cx + ux * 45), y - (cy + uy * 45)) < 9) { luma[i] = 150; chroma[i] = 60 }  // hand on the sheet's edge
            if (len(x - 15f, y - 110f) < 20) { luma[i] = 40; chroma[i] = 8 }           // knee
        }
        return ImageGrid(w, h, ByteArray(w * h) { luma[it].toByte() }, ByteArray(w * h) { chroma[it].toByte() })
    }

    @Test fun findsTheItemNotTheHandLinesOrKnee() {
        val g = scene()
        val r = ItemOnPaper.segment(g)!!
        var sx = 0; var sy = 0; var n = 0
        for (y in 0 until g.height) for (x in 0 until g.width) if (r.item[y * g.width + x].toInt() != 0) { sx += x; sy += y; n += 1 }
        assertEquals("item centre x", 80f, sx.toFloat() / n, 2.5f)
        assertEquals("item centre y", 55f, sy.toFloat() / n, 2.5f)
        // The item (π·14·9 ≈ 396 px) plus at most a little shadow; never the hand, lines or knee.
        assertTrue(n > 380)
        assertTrue(n < 700)
        assertEquals("knee", 0, r.item[110 * g.width + 15].toInt())
    }

    @Test fun noPaperNoAnswer() {
        val g = ImageGrid(40, 30, ByteArray(1200) { 180.toByte() }, ByteArray(1200) { 42 })
        assertNull(ItemOnPaper.segment(g))
    }

    @Test fun paperTintUnderWarmLight() {
        // White paper under warm light: Cb < 0, Cr > 0 in proportion to brightness. Measured against the tint it's colourless.
        val n = 400
        val luma = ByteArray(n) { 220.toByte() }
        val cb = FloatArray(n) { -0.08f * 220 }
        val cr = FloatArray(n) { 0.06f * 220 }
        val g = ImageGrid.fromYCbCr(20, 20, luma, cb, cr)
        assertTrue((0 until n).all { g.chromaAt(it) <= 2 })
    }
}

class SheetAngleTest {
    /**
     * A camera 1 unit above the table, pitched 50° down, looking along −Z. On the table: a 0.5 × 0.36 sheet turned
     * `deg` (clockwise from above) with a small item in the middle. The masks are rendered by casting each pixel's ray.
     */
    private fun read(deg: Float): SheetAngle.Reading? {
        val w = 320
        val h = 240
        val phi = -50f * PI_F / 180
        // Column-major rotation about +X (camera → world).
        val r = Mat3(floatArrayOf(1f, 0f, 0f, 0f, cos(phi), sin(phi), 0f, -sin(phi), cos(phi)))
        val frame = SheetAngle.HeadingFrame.of(r)!!
        val k = SheetAngle.Intrinsics(250f, 250f, 160f, 120f)
        val centre = frame.onPlane(160f, 120f, k)!!
        val a = deg * PI_F / 180
        val ex = sin(a); val ez = -cos(a)     // the sheet's long edge direction on the plane (0° = away from the camera)
        val fx = -ez; val fz = ex
        val sheet = ByteArray(w * h)
        val item = ByteArray(w * h)
        for (y in 0 until h) for (x in 0 until w) {
            val p = frame.onPlane(x.toFloat(), y.toFloat(), k) ?: continue
            val dx = p.first - centre.first
            val dz = p.second - centre.second
            val along = dx * ex + dz * ez
            val across = dx * fx + dz * fz
            if (abs(along) < 0.06f && abs(across) < 0.06f) item[y * w + x] = 1
            else if (abs(along) < 0.25f && abs(across) < 0.18f) sheet[y * w + x] = 1
        }
        return SheetAngle.read(sheet, item, w, h, k, frame)
    }

    // A binary mask's edges alias most when they run nearly along the pixel grid (a few degrees off there), so the
    // bounds are the real recording's (mint-33218a6e on iOS: median 1.5°, 95th percentile 4.9° against a tracker).
    @Test fun readsTheSheetsTurnModNinety() {
        val errors = (0 until 18).map { j ->
            val deg = 2.5f + j * 10f
            val reading = read(deg)
            assertNotNull("no reading at $deg°", reading)
            val got = reading!!.angleMod90 * 180 / PI_F
            val diff = abs(SheetAngle.wrap90((got - deg % 90) * PI_F / 180)) * 180 / PI_F
            assertTrue("at $deg° read $got°", diff < 4.9f)
            assertTrue(reading.confidence > 0.5f)
            diff
        }.sorted()
        assertTrue("median ${errors[errors.size / 2]}°", errors[errors.size / 2] < 1.5f)
    }

    @Test fun elevationOfTheMiddle() {
        val phi = -50f * PI_F / 180
        val r = Mat3(floatArrayOf(1f, 0f, 0f, 0f, cos(phi), sin(phi), 0f, -sin(phi), cos(phi)))
        val frame = SheetAngle.HeadingFrame.of(r)!!
        assertEquals(50f, frame.elevation(160f, 120f, SheetAngle.Intrinsics(250f, 250f, 160f, 120f)) * 180 / PI_F, 0.01f)
    }
}

class PaperTurnTest {
    private fun reading(deg: Float, confidence: Float = 0.6f): SheetAngle.Reading {
        var a = (deg * PI_F / 180) % (PI_F / 2)
        if (a < 0) a += PI_F / 2
        return SheetAngle.Reading(a, confidence, 500)
    }

    @Test fun unwrapsTwoLapsBothWays() {
        for (dir in listOf(1f, -1f)) {
            val turn = PaperTurn()
            // Two laps in 20 s read at 7.5 Hz: 4.8° per read, across every 90° wrap.
            for (i in 0..150) turn.update(reading(10 + dir * i * 4.8f), i / 7.5)
            assertEquals(dir * 720, turn.turned * 180 / PI_F, 0.05f)
        }
    }

    @Test fun ignoresUnsureAndImpossibleReadings() {
        val turn = PaperTurn()
        turn.update(reading(20f), 0.0)
        assertFalse(turn.update(reading(60f, confidence = 0.1f), 0.13))   // unsure
        assertFalse(turn.update(reading(55f), 0.13))                      // 35° in 0.13 s: a hand, not the paper
        assertTrue(turn.update(reading(24f), 0.26))
        assertEquals(4f, turn.turned * 180 / PI_F, 0.01f)
    }

    @Test fun restartMakesNowTheStart() {
        val turn = PaperTurn()
        for (i in 0..10) turn.update(reading(i * 3f), i / 7.5)
        turn.restart()
        assertEquals(0f, turn.turned, 0f)
        turn.update(reading(33f), 11 / 7.5)
        assertEquals(3f, turn.turned * 180 / PI_F, 0.01f)
    }
}

class TurnCoverageTest {
    /** Turns the item `degrees` over `seconds` at a fixed elevation, observed at 7.5 Hz. */
    private fun turn(c: TurnCoverage, start: Float, degrees: Float, seconds: Double, elevationDeg: Float) {
        val n = (seconds * 7.5).toInt()
        for (i in 1..n) c.observe((start + degrees * i / n) * PI_F / 180, elevationDeg * PI_F / 180, 1 / 7.5)
    }

    @Test fun oneLapIsFull() {
        val c = TurnCoverage()
        turn(c, 0f, 370f, 10.0, 50f)
        assertEquals(100, c.percent)
        // Touching up from another height afterwards doesn't take anything away.
        turn(c, 370f, 40f, 3.0, 25f)
        assertEquals(100, c.percent)
    }

    @Test fun threeQuartersOfALapIsNotFull() {
        val c = TurnCoverage()
        turn(c, 0f, 270f, 8.0, 50f)
        assertTrue(c.percent > 75)
        assertTrue(c.percent < 100)
    }

    @Test fun twoBandsTwoLapsAtTwoHeightsIsFull() {
        for (dir in listOf(1f, -1f)) {
            val c = TurnCoverage(bands = 2)
            turn(c, 0f, dir * 370, 10.0, 55f)
            turn(c, dir * 370, dir * 370, 10.0, 30f)   // lower, as the demo does
            assertEquals(100, c.percent)
        }
    }

    @Test fun twoBandsOneLapAtOneHeightIsHalf() {
        val c = TurnCoverage(bands = 2)
        c.observe(0f, 0.9f, 0.0)
        turn(c, 0f, 370f, 10.0, 0.9f * 180 / PI_F)
        assertEquals(50, c.percent)
    }

    @Test fun standingStillOnlyCoversTheFront() {
        val c = TurnCoverage()
        repeat(150) { c.observe(0f, 0.9f, 1 / 7.5) }
        assertEquals(1f, c.level(0f), 0.001f)
        assertEquals(0f, c.level(PI_F), 0f)   // the back was never seen
        assertTrue(c.percent < 20)
    }

    @Test fun percentNeverDropsAndOnlyCountsMeasuredTime() {
        val c = TurnCoverage()
        var last = 0
        for (i in 0 until 300) {
            c.observe(i * 0.02f, 0.9f, 1 / 7.5)
            assertTrue(c.percent >= last)
            last = c.percent
        }
        // A long gap (paper lost) counts at most 0.25 s.
        val gap = TurnCoverage()
        gap.observe(0f, 0.9f, 30.0)
        assertEquals(0.5f, gap.level(0f), 0.01f)
    }

    @Test fun sidesSeenAcrossTheSilhouette() {
        val c = TurnCoverage()
        c.observe(0.5f, 0.9f, 0.0)
        assertEquals(-0.5f, c.side(0f), 1e-6f)                  // the middle faces the camera
        assertEquals(-0.5f - PI_F / 2, c.side(1f), 1e-6f)      // the right edge: a quarter turn anticlockwise
        assertEquals(-0.5f + PI_F / 2, c.side(-1f), 1e-6f)
    }
}
