package app.officehub.android

import android.Manifest
import android.annotation.SuppressLint
import android.app.DownloadManager
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.PowerManager
import android.provider.Settings
import android.webkit.CookieManager
import android.webkit.PermissionRequest
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.net.toUri
import androidx.core.view.updatePadding
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import org.json.JSONObject

/**
 * The company's OfficeHub in the app, like Teams: the portal itself comes from the server, the app adds
 * notifications and ringing calls in the background (FeedService), camera and microphone for meetings, file
 * upload and download. Only the company's address may talk to the app (WebMessageListener restricted to it).
 */
class MainActivity : AppCompatActivity() {
    private lateinit var web: WebView
    private lateinit var prefs: Prefs
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private var pendingPermission: PermissionRequest? = null

    private val pickFiles = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val data = result.data
        val uris = when {
            result.resultCode != RESULT_OK || data == null -> null
            data.clipData != null -> Array(data.clipData!!.itemCount) { data.clipData!!.getItemAt(it).uri }
            data.data != null -> arrayOf(data.data!!)
            else -> null
        }
        fileCallback?.onReceiveValue(uris)
        fileCallback = null
    }

    private val askMedia = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { granted ->
        val request = pendingPermission ?: return@registerForActivityResult
        pendingPermission = null
        val allowed = request.resources.filter { resource ->
            when (resource) {
                PermissionRequest.RESOURCE_VIDEO_CAPTURE -> granted[Manifest.permission.CAMERA] == true || has(Manifest.permission.CAMERA)
                PermissionRequest.RESOURCE_AUDIO_CAPTURE -> granted[Manifest.permission.RECORD_AUDIO] == true || has(Manifest.permission.RECORD_AUDIO)
                else -> false
            }
        }
        if (allowed.isEmpty()) request.deny() else request.grant(allowed.toTypedArray())
    }

    private val askNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) { askBattery() }

    private fun has(permission: String) = ContextCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        val server = prefs.server
        if (server == null) {
            startActivity(Intent(this, ConnectActivity::class.java))
            finish()
            return
        }
        Notifier.createChannels(this)
        web = WebView(this)
        setContentView(web)
        ViewCompat.setOnApplyWindowInsetsListener(web) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            view.updatePadding(top = bars.top, bottom = bars.bottom, left = bars.left, right = bars.right)
            WindowInsetsCompat.CONSUMED
        }

        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            mediaPlaybackRequiresUserGesture = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            setSupportMultipleWindows(false)
            allowFileAccess = false
            userAgentString = userAgentString + Http.userAgentSuffix
            Http.userAgent = userAgentString
        }
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false)

        val origin = Origin.of(server) ?: server
        if (WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
            WebViewCompat.addWebMessageListener(web, "OfficeHubAndroid", setOf(origin)) { _, message, sourceOrigin, isMainFrame, _ ->
                if (isMainFrame && sourceOrigin.toString().trimEnd('/') == origin) onPortalMessage(message.data ?: "")
            }
        }

        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val url = request.url
                val target = Origin.of(url.toString())
                // OfficeHub itself and the company login page (Authentik, Keycloak …) stay in the app
                if (target == origin || target in prefs.signInOrigins) return false
                // Everything outside OfficeHub opens in the browser (or the app it belongs to)
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, url))
                } catch (_: ActivityNotFoundException) {
                    // nothing can open it
                }
                return true
            }

            override fun doUpdateVisitedHistory(view: WebView, url: String, isReload: Boolean) {
                runCatching { Uri.parse(url).path }.getOrNull()?.takeIf { it != "/" }?.let { onPlace(it) }
            }
        }

        web.webChromeClient = object : WebChromeClient() {
            override fun onPermissionRequest(request: PermissionRequest) {
                if (Origin.of(request.origin.toString()) != origin) {
                    request.deny()
                    return
                }
                val needed = mutableListOf<String>()
                if (PermissionRequest.RESOURCE_VIDEO_CAPTURE in request.resources && !has(Manifest.permission.CAMERA)) needed += Manifest.permission.CAMERA
                if (PermissionRequest.RESOURCE_AUDIO_CAPTURE in request.resources && !has(Manifest.permission.RECORD_AUDIO)) needed += Manifest.permission.RECORD_AUDIO
                if (needed.isEmpty()) {
                    request.grant(request.resources.filter {
                        it == PermissionRequest.RESOURCE_VIDEO_CAPTURE || it == PermissionRequest.RESOURCE_AUDIO_CAPTURE
                    }.toTypedArray())
                } else {
                    pendingPermission = request
                    askMedia.launch(needed.toTypedArray())
                }
            }

            override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                fileCallback?.onReceiveValue(null)
                fileCallback = callback
                val intent = params.createIntent().apply {
                    if (params.mode == FileChooserParams.MODE_OPEN_MULTIPLE) putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                }
                return try {
                    pickFiles.launch(intent)
                    true
                } catch (_: ActivityNotFoundException) {
                    fileCallback = null
                    false
                }
            }
        }

        web.setDownloadListener { url, userAgent, contentDisposition, mimeType, _ ->
            if (url.startsWith("blob:") || url.startsWith("data:")) return@setDownloadListener
            val name = URLUtil.guessFileName(url, contentDisposition, mimeType)
            val request = DownloadManager.Request(Uri.parse(url))
                .setMimeType(mimeType)
                .addRequestHeader("Cookie", CookieManager.getInstance().getCookie(url) ?: "")
                .addRequestHeader("User-Agent", userAgent)
                .setTitle(name)
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name)
            getSystemService(DownloadManager::class.java)?.enqueue(request)
            Toast.makeText(this, name, Toast.LENGTH_SHORT).show()
        }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (web.canGoBack()) web.goBack() else moveTaskToBack(true)
            }
        })

        // The company login may have been set up (or moved) since the last start
        kotlin.concurrent.thread { Http.config(server)?.let { prefs.signInOrigins = Http.signInOrigins(it) } }

        if (savedInstanceState != null) web.restoreState(savedInstanceState) else web.loadUrl(startUrl(intent, server))
    }

    private fun startUrl(intent: Intent?, server: String): String {
        val link = intent?.getStringExtra(EXTRA_LINK)?.takeIf { it.startsWith("/") }
        return if (link != null) server.trimEnd('/') + link else server
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        val server = prefs.server ?: return
        intent.getStringExtra(EXTRA_LINK)?.takeIf { it.startsWith("/") }?.let { web.loadUrl(server.trimEnd('/') + it) }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        if (::web.isInitialized) web.saveState(outState)
    }

    override fun onResume() {
        super.onResume()
        inFront = true
        if (::web.isInitialized) web.onResume()
    }

    override fun onPause() {
        inFront = false
        if (::web.isInitialized) web.onPause()
        CookieManager.getInstance().flush()
        super.onPause()
    }

    /** What the portal tells the app (frontend lib/native.ts). */
    private fun onPortalMessage(data: String) {
        val message = runCatching { JSONObject(data) }.getOrNull() ?: return
        when (message.optString("type")) {
            "session" -> {
                val signedIn = message.optBoolean("signedIn")
                val was = prefs.signedIn
                prefs.signedIn = signedIn
                CookieManager.getInstance().flush()
                if (signedIn) {
                    FeedService.start(this)
                    if (!was) askNotificationsOnce()
                } else {
                    FeedService.stop(this)
                }
            }
            "texts" -> prefs.texts = message
            "place" -> onPlace(message.optString("path"))
        }
    }

    /** The page open in the portal (it keeps the address bar plain, so it says so itself). */
    private fun onPlace(path: String) {
        currentPath = path
        Regex("^/chat/(\\d+)").find(path)?.let { Notifier.clearMessages(this, it.groupValues[1].toInt()) }
    }

    /** Like Teams: ask once to show notifications, then whether OfficeHub may stay connected while the phone sleeps. */
    private fun askNotificationsOnce() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && !has(Manifest.permission.POST_NOTIFICATIONS)) {
            askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else {
            askBattery()
        }
    }

    @SuppressLint("BatteryLife")
    private fun askBattery() {
        if (prefs.batteryAsked) return
        prefs.batteryAsked = true
        val power = getSystemService(PowerManager::class.java) ?: return
        if (power.isIgnoringBatteryOptimizations(packageName)) return
        try {
            startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, "package:$packageName".toUri()))
        } catch (_: ActivityNotFoundException) {
            // not offered on this phone
        }
    }

    companion object {
        const val EXTRA_LINK = "link"

        @Volatile var inFront = false
        @Volatile var currentPath: String? = null
    }
}
