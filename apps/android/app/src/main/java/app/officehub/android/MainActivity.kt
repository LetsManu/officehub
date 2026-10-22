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
import android.provider.OpenableColumns
import android.provider.Settings
import android.view.View
import android.webkit.CookieManager
import android.webkit.PermissionRequest
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
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
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import androidx.webkit.ServiceWorkerClientCompat
import androidx.webkit.ServiceWorkerControllerCompat
import androidx.webkit.WebViewCompat
import com.google.android.material.bottomnavigation.BottomNavigationView
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
    private lateinit var refresh: SwipeRefreshLayout
    private lateinit var nav: BottomNavigationView
    private var origin = ""
    /** The portal says whether a pull down would reload (only at the very top of the page). */
    private var atTop = true
    private var navAllowed = false
    private var keyboardOpen = false
    /** What another app shared, until the portal's /share page has read it. */
    @Volatile private var pendingShare: Shared? = null

    private class Shared(val title: String, val text: String, val files: List<Uri>)
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
        setContentView(R.layout.activity_main)
        web = WebView(this)
        refresh = findViewById(R.id.refresh)
        nav = findViewById(R.id.bottom_nav)
        refresh.addView(web)
        refresh.setOnChildScrollUpCallback { _, _ -> !atTop }
        refresh.setOnRefreshListener { web.reload() }
        val root = findViewById<View>(R.id.root)
        ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            val ime = insets.getInsets(WindowInsetsCompat.Type.ime())
            keyboardOpen = insets.isVisible(WindowInsetsCompat.Type.ime())
            showNav()
            // Like Teams: the bottom bar steps aside for the keyboard
            val bottom = if (keyboardOpen) ime.bottom else if (nav.visibility == View.VISIBLE) 0 else bars.bottom
            view.updatePadding(top = bars.top, left = bars.left, right = bars.right, bottom = bottom)
            nav.updatePadding(bottom = bars.bottom)
            WindowInsetsCompat.CONSUMED
        }
        setUpNav()

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

        origin = Origin.of(server) ?: server
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

            override fun onPageFinished(view: WebView, url: String) {
                refresh.isRefreshing = false
                atTop = true
            }

            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                shareResponse(request)

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

        // Requests the portal's service worker makes for the shared files reach the app the same way
        if (WebViewFeature.isFeatureSupported(WebViewFeature.SERVICE_WORKER_BASIC_USAGE)) {
            ServiceWorkerControllerCompat.getInstance().setServiceWorkerClient(object : ServiceWorkerClientCompat() {
                override fun shouldInterceptRequest(request: WebResourceRequest): WebResourceResponse? = shareResponse(request)
            })
        }

        // The company login may have been set up (or moved) since the last start
        kotlin.concurrent.thread { Http.config(server)?.let { prefs.signInOrigins = Http.signInOrigins(it) } }

        applyTexts()
        val shared = takeShare(intent)
        if (savedInstanceState != null && !shared) web.restoreState(savedInstanceState) else web.loadUrl(startUrl(intent, server, shared))
    }

    private fun startUrl(intent: Intent?, server: String, shared: Boolean): String {
        val link = if (shared) "/share?from=app" else intent?.getStringExtra(EXTRA_LINK)?.takeIf { it.startsWith("/") }
        return if (link != null) server.trimEnd('/') + link else server
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        val server = prefs.server ?: return
        if (takeShare(intent)) {
            web.loadUrl(startUrl(intent, server, true))
            return
        }
        intent.getStringExtra(EXTRA_LINK)?.takeIf { it.startsWith("/") }?.let { web.loadUrl(server.trimEnd('/') + it) }
    }

    // ---------- bottom bar (like Teams) ----------

    private val tabs by lazy {
        mapOf(R.id.nav_activity to "/activity", R.id.nav_chat to "/chat", R.id.nav_spaces to "/spaces", R.id.nav_calendar to "/calendar")
    }

    private fun setUpNav() {
        nav.setOnItemSelectedListener { item ->
            if (item.itemId == R.id.nav_more) {
                tellPage(JSONObject().put("menu", true))
                false
            } else {
                tabs[item.itemId]?.let { tellPage(JSONObject().put("navigate", it)) }
                true
            }
        }
        // Tapping the open tab again goes back to its start, like Teams
        nav.setOnItemReselectedListener { item -> tabs[item.itemId]?.let { tellPage(JSONObject().put("navigate", it)) } }
    }

    private fun tellPage(detail: JSONObject) {
        web.evaluateJavascript("window.dispatchEvent(new CustomEvent('officehub-app', { detail: $detail }))", null)
    }

    /** Shown when signed in, hidden in meetings, documents, sign-in and while typing. */
    private fun showNav() {
        // No pull to refresh in meetings and documents: a slip of the finger must not reload them
        refresh.isEnabled = navAllowed
        val visible = navAllowed && prefs.signedIn && !keyboardOpen
        val state = if (visible) View.VISIBLE else View.GONE
        if (nav.visibility != state) {
            nav.visibility = state
            ViewCompat.requestApplyInsets(findViewById(R.id.root))
        }
    }

    private fun markTab(path: String) {
        val current = tabs.entries.firstOrNull { path == it.value || path.startsWith(it.value + "/") }?.key
        nav.menu.setGroupCheckable(0, true, false)
        for (i in 0 until nav.menu.size()) {
            val item = nav.menu.getItem(i)
            item.isChecked = item.itemId == current
        }
        nav.menu.setGroupCheckable(0, true, true)
    }

    private fun applyTexts() {
        val texts = prefs.texts ?: return
        mapOf(
            R.id.nav_activity to "navActivity", R.id.nav_chat to "navChat", R.id.nav_spaces to "navSpaces",
            R.id.nav_calendar to "navCalendar", R.id.nav_more to "navMore",
        ).forEach { (id, key) -> texts.optString(key).takeIf { it.isNotBlank() }?.let { nav.menu.findItem(id)?.title = it } }
    }

    private fun setCount(id: Int, count: Int) {
        if (count > 0) nav.getOrCreateBadge(id).apply { isVisible = true; number = count } else nav.removeBadge(id)
    }

    // ---------- "Share to OfficeHub" ----------

    /** Keeps what another app shared; the portal's /share page reads it from /__app/share/. */
    private fun takeShare(intent: Intent?): Boolean {
        if (intent == null || (intent.action != Intent.ACTION_SEND && intent.action != Intent.ACTION_SEND_MULTIPLE)) return false
        val files = mutableListOf<Uri>()
        if (intent.action == Intent.ACTION_SEND) {
            intentUri(intent)?.let { files += it }
        } else {
            intentUris(intent)?.let { files += it }
        }
        val text = intent.getStringExtra(Intent.EXTRA_TEXT).orEmpty()
        val title = intent.getStringExtra(Intent.EXTRA_SUBJECT).orEmpty()
        if (files.isEmpty() && text.isBlank()) return false
        pendingShare = Shared(title, text, files.take(MAX_SHARED_FILES))
        intent.action = Intent.ACTION_MAIN // handled: a rotation must not share it again
        return true
    }

    @Suppress("DEPRECATION")
    private fun intentUri(intent: Intent): Uri? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
        else intent.getParcelableExtra(Intent.EXTRA_STREAM)

    @Suppress("DEPRECATION")
    private fun intentUris(intent: Intent): List<Uri>? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java)
        else intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM)

    /** Answers the portal's /__app/share/meta and /__app/share/file/<n>, only on the company's own address. */
    private fun shareResponse(request: WebResourceRequest): WebResourceResponse? {
        val url = request.url
        val path = url.path ?: return null
        if (!path.startsWith("/__app/share/") || Origin.of(url.toString()) != origin) return null
        val shared = pendingShare ?: return WebResourceResponse("text/plain", "utf-8", 404, "Not Found", emptyMap(), null)
        return try {
            if (path == "/__app/share/meta") {
                val files = org.json.JSONArray()
                shared.files.forEach { uri ->
                    files.put(JSONObject().put("name", fileName(uri)).put("type", contentResolver.getType(uri) ?: "application/octet-stream").put("size", 0))
                }
                val meta = JSONObject().put("title", shared.title).put("text", shared.text).put("url", "").put("files", files)
                WebResourceResponse("application/json", "utf-8", meta.toString().byteInputStream())
            } else {
                val index = path.removePrefix("/__app/share/file/").toIntOrNull()
                val uri = index?.let { shared.files.getOrNull(it) } ?: return null
                WebResourceResponse(contentResolver.getType(uri) ?: "application/octet-stream", null, contentResolver.openInputStream(uri))
            }
        } catch (_: Exception) {
            WebResourceResponse("text/plain", "utf-8", 404, "Not Found", emptyMap(), null)
        }
    }

    private fun fileName(uri: Uri): String =
        runCatching {
            contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst()) c.getString(0) else null
            }
        }.getOrNull() ?: uri.lastPathSegment ?: "file"


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
                showNav()
                if (signedIn) {
                    FeedService.start(this)
                    if (!was) askNotificationsOnce()
                } else {
                    FeedService.stop(this)
                }
            }
            "texts" -> {
                prefs.texts = message
                applyTexts()
            }
            "place" -> onPlace(message.optString("path"))
            "counts" -> {
                setCount(R.id.nav_activity, message.optInt("activity"))
                setCount(R.id.nav_chat, message.optInt("chat"))
            }
            "scroll" -> atTop = message.optBoolean("atTop", true)
        }
    }

    /** The page open in the portal (it keeps the address bar plain, so it says so itself). */
    private fun onPlace(path: String) {
        currentPath = path
        navAllowed = !NO_NAV.containsMatchIn(path)
        if (!path.startsWith("/share")) pendingShare = null
        showNav()
        markTab(path)
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
        private const val MAX_SHARED_FILES = 10
        /** Full-screen places without the bottom bar: meetings, documents, sign-in, guests, sharing. */
        private val NO_NAV = Regex("^/(login|guest/|office/|wordcraft|deckcraft|share|install)|^/meetings/\\d+/room")

        @Volatile var inFront = false
        @Volatile var currentPath: String? = null
    }
}
