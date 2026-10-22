package app.officehub.android

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** After a restart (or an update) OfficeHub connects again, if someone is signed in. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED || intent.action == Intent.ACTION_MY_PACKAGE_REPLACED) {
            FeedService.start(context)
        }
    }
}
