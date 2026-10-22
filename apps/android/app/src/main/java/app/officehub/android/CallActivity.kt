package app.officehub.android

import android.app.KeyguardManager
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.button.MaterialButton
import java.lang.ref.WeakReference
import kotlin.concurrent.thread

/** A call rings: shown over the lock screen, like a phone call. */
class CallActivity : AppCompatActivity() {
    private var meeting = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (android.os.Build.VERSION.SDK_INT < android.os.Build.VERSION_CODES.O_MR1) {
            // Android 8.0 knows "show over the lock screen" only as window flags
            @Suppress("DEPRECATION")
            window.addFlags(android.view.WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or android.view.WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON)
        }
        setContentView(R.layout.activity_call)
        meeting = intent.getIntExtra(EXTRA_MEETING, 0)
        current = WeakReference(this)
        val name = intent.getStringExtra(EXTRA_NAME) ?: ""
        val texts = Prefs(this).texts
        findViewById<TextView>(R.id.name).text = name
        findViewById<TextView>(R.id.initials).text = name.split(" ").filter { it.isNotEmpty() }.take(2).joinToString("") { it.take(1).uppercase() }
        findViewById<TextView>(R.id.text).text = texts.optString("callIncoming", getString(R.string.call_incoming))
        findViewById<MaterialButton>(R.id.accept).apply {
            text = texts.optString("callAccept", getString(R.string.call_accept))
            setOnClickListener { accept() }
        }
        findViewById<MaterialButton>(R.id.decline).apply {
            text = texts.optString("callDecline", getString(R.string.call_decline))
            setOnClickListener { decline(this@CallActivity, meeting); finish() }
        }
    }

    private fun accept() {
        Notifier.stopCall(this, meeting)
        val keyguard = getSystemService(KeyguardManager::class.java)
        keyguard?.requestDismissKeyguard(this, null)
        startActivity(
            Intent(this, MainActivity::class.java)
                .putExtra(MainActivity.EXTRA_LINK, "/meetings/$meeting/room")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
        )
        finish()
    }

    override fun onDestroy() {
        if (current?.get() === this) current = null
        super.onDestroy()
    }

    companion object {
        const val EXTRA_MEETING = "meeting"
        const val EXTRA_NAME = "name"
        private var current: WeakReference<CallActivity>? = null

        /** The call stopped ringing (answered elsewhere, ended, missed): close the screen. */
        fun finishFor(meeting: Int) {
            val activity = current?.get() ?: return
            if (activity.meeting == meeting) activity.runOnUiThread { activity.finish() }
        }

        fun decline(context: Context, meeting: Int) {
            Notifier.stopCall(context, meeting)
            val server = Prefs(context).server ?: return
            thread { runCatching { Http.post(server, "/api/calls/$meeting/decline") } }
        }
    }
}
