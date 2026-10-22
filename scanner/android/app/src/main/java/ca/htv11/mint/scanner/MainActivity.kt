package ca.htv11.mint.scanner

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import com.google.ar.core.ArCoreApk

/**
 * One screen: the camera is always live underneath ([CaptureView]); the session decides what goes over it.
 * Before the camera can run: camera permission, then ARCore (Google Play Services for AR) installed and current.
 */
class MainActivity : ComponentActivity() {
    private lateinit var session: CaptureSession
    private var blocker by mutableStateOf<Blocker?>(null)
    private var installRequested = false
    private var pendingLink: String? = null

    private enum class Blocker { CAMERA, AR_UNSUPPORTED }

    private val permission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (!granted) blocker = Blocker.CAMERA
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        WindowCompat.getInsetsController(window, window.decorView).apply {
            hide(WindowInsetsCompat.Type.systemBars())
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
        session = CaptureSession(this)
        pendingLink = intent?.dataString
        setContent {
            when (blocker) {
                null -> CaptureView(session)
                Blocker.CAMERA -> BlockedScreen(
                    "Mint needs the camera",
                    "Mint uses the camera to scan your item in 3D.",
                    "Open settings",
                ) { startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", packageName, null))) }
                Blocker.AR_UNSUPPORTED -> BlockedScreen(
                    "This phone can't run Mint",
                    "Mint needs Google Play Services for AR, which this phone doesn't support.",
                    null,
                ) {}
            }
        }
        if (BuildConfig.DEBUG) intent?.getStringExtra("MintPreview")?.let { pendingPreview = it }
    }

    private var pendingPreview: String? = null

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        intent.dataString?.let { session.open(it) }
    }

    override fun onResume() {
        super.onResume()
        if (!ready()) return
        // Coming back from the background (the camera app's QR banner, the app switcher, a call…): run again.
        session.resume()
        pendingLink?.let { session.open(it) }
        pendingLink = null
        pendingPreview?.let { session.preview(it) }
        pendingPreview = null
    }

    override fun onPause() {
        super.onPause()
        session.pause()
    }

    override fun onDestroy() {
        super.onDestroy()
        session.destroy()
    }

    /** Camera permission granted and ARCore installed; asks for whichever is missing (this resumes again after). */
    private fun ready(): Boolean {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            if (blocker == null) permission.launch(Manifest.permission.CAMERA)
            return false
        }
        if (blocker == Blocker.CAMERA) blocker = null
        return try {
            when (ArCoreApk.getInstance().requestInstall(this, !installRequested)) {
                ArCoreApk.InstallStatus.INSTALLED -> true
                ArCoreApk.InstallStatus.INSTALL_REQUESTED -> { installRequested = true; false }
            }
        } catch (e: Exception) {
            blocker = Blocker.AR_UNSUPPORTED
            false
        }
    }
}

@Composable
private fun BlockedScreen(title: String, body: String, action: String?, onAction: () -> Unit) {
    Box(Modifier.fillMaxSize().background(Brand.paper).safeDrawingPadding().padding(20.dp)) {
        Box(Modifier.align(Alignment.TopStart).padding(top = 6.dp)) { MintMark() }
        Column(Modifier.align(Alignment.Center), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(title, style = rounded(Type.title, FontWeight.Black), color = Brand.ink, textAlign = TextAlign.Center)
            Text(body, style = rounded(Type.body), color = Brand.ink.copy(alpha = 0.7f), textAlign = TextAlign.Center)
        }
        if (action != null) {
            MintButton(onAction, Modifier.align(Alignment.BottomCenter).fillMaxWidth(), prominent = true, minHeight = 52.dp) {
                Text(action, style = rounded(Type.body, FontWeight.Bold), color = it)
            }
        }
    }
}
