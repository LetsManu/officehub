package app.officehub.android

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import org.json.JSONObject
import kotlin.concurrent.thread

/**
 * Keeps a connection to the company's OfficeHub open while someone is signed in, like Teams does with its push
 * service, but without any cloud: it waits on /api/me/feed (backend routers/apps.py), which answers as soon as a
 * message, a notice or a call is there. A small permanent notification says that OfficeHub is connected.
 */
class FeedService : Service() {
    @Volatile private var running = false
    private var worker: Thread? = null
    private val ringing = mutableSetOf<Int>()
    private val reminded = mutableSetOf<String>()

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        Notifier.createChannels(this)
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0
        ServiceCompat.startForeground(this, Notifier.ID_CONNECTION, Notifier.connection(this), type)
        if (!running) {
            running = true
            worker = thread(name = "officehub-feed") { loop() }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        worker?.interrupt()
        super.onDestroy()
    }

    private fun loop() {
        val prefs = Prefs(this)
        var notificationAfter = 0
        var chatAfter: String? = null
        var failures = 0
        while (running) {
            val server = prefs.server
            if (server == null || !prefs.signedIn) break
            try {
                val query = if (chatAfter == null) "" else "?wait=true&notification_after=$notificationAfter&chat_after=${java.net.URLEncoder.encode(chatAfter, "UTF-8")}"
                val feed = Http.get(server, "/api/me/feed$query", timeoutMs = 40_000)
                val first = chatAfter == null
                notificationAfter = feed.optInt("notification_after", notificationAfter)
                chatAfter = feed.optString("chat_after").ifEmpty { chatAfter }
                if (!first) show(feed, prefs.texts)
                failures = 0
            } catch (_: Http.Unauthorized) {
                // Signed out (or the session ended): stop until the next sign-in in the app
                prefs.signedIn = false
                break
            } catch (_: InterruptedException) {
                break
            } catch (_: Exception) {
                // No network or the server restarts: try again, waiting a bit longer each time (up to a minute)
                failures++
                try {
                    Thread.sleep((2_000L * failures).coerceAtMost(60_000L))
                } catch (_: InterruptedException) {
                    break
                }
            }
        }
        running = false
        stopSelf()
    }

    private fun show(feed: JSONObject, texts: JSONObject) {
        val foreground = MainActivity.inFront
        feed.optJSONArray("messages")?.let { list ->
            for (i in 0 until list.length()) {
                val m = list.getJSONObject(i)
                // The open chat shows it itself
                if (foreground && MainActivity.currentPath == "/chat/${m.optInt("conversation_id")}") continue
                Notifier.message(this, m, texts)
            }
        }
        feed.optJSONArray("notifications")?.let { list ->
            for (i in 0 until list.length()) Notifier.notice(this, list.getJSONObject(i), texts)
        }
        feed.optJSONArray("reminders")?.let { list ->
            for (i in 0 until list.length()) {
                val r = list.getJSONObject(i)
                val key = "${r.optInt("meeting_id")}-${r.optString("starts_at")}"
                if (reminded.add(key)) Notifier.reminder(this, r, texts)
            }
        }
        val now = mutableSetOf<Int>()
        feed.optJSONArray("calls")?.let { list ->
            for (i in 0 until list.length()) {
                val call = list.getJSONObject(i)
                val id = call.optInt("meeting_id")
                now.add(id)
                // While the app is open, the portal rings itself (frontend IncomingCall.vue)
                if (id !in ringing && !foreground) Notifier.call(this, call, texts)
            }
        }
        for (gone in ringing - now) Notifier.stopCall(this, gone)
        ringing.clear()
        ringing.addAll(now)
    }

    companion object {
        fun start(context: Context) {
            if (!Prefs(context).signedIn || Prefs(context).server == null) return
            try {
                ContextCompat.startForegroundService(context, Intent(context, FeedService::class.java))
            } catch (_: Exception) {
                // Android does not allow starting it right now (e.g. from the background); the app starts it when opened
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, FeedService::class.java))
        }
    }
}
