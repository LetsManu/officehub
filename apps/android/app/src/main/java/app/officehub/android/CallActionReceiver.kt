package app.officehub.android

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** "Decline" in the call notification. */
class CallActionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == ACTION_DECLINE) CallActivity.decline(context, intent.getIntExtra(CallActivity.EXTRA_MEETING, 0))
    }

    companion object {
        const val ACTION_DECLINE = "app.officehub.android.DECLINE"
    }
}
