package app.officehub.android

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.Person
import org.json.JSONObject

/** Everything that shows up in the Android notification shade: messages, notices, reminders and ringing calls. */
object Notifier {
    const val CHANNEL_MESSAGES = "messages"
    const val CHANNEL_CALLS = "calls"
    const val CHANNEL_REMINDERS = "reminders"
    const val CHANNEL_CONNECTION = "connection"
    const val ID_CONNECTION = 1
    private const val ID_CALL_BASE = 2_000_000
    private const val ID_NOTICE_BASE = 1_000_000
    private const val ID_REMINDER_BASE = 3_000_000

    private fun german(context: Context) = context.resources.configuration.locales[0].language == "de"

    fun createChannels(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        val de = german(context)
        val messages = NotificationChannel(CHANNEL_MESSAGES, if (de) "Nachrichten und Hinweise" else "Messages and notices", NotificationManager.IMPORTANCE_HIGH)
        val calls = NotificationChannel(CHANNEL_CALLS, if (de) "Anrufe" else "Calls", NotificationManager.IMPORTANCE_HIGH).apply {
            setSound(
                RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE),
                AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build(),
            )
            enableVibration(true)
            vibrationPattern = longArrayOf(0, 800, 600, 800, 600, 800)
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
        }
        val reminders = NotificationChannel(CHANNEL_REMINDERS, if (de) "Meeting-Erinnerungen" else "Meeting reminders", NotificationManager.IMPORTANCE_HIGH)
        val connection = NotificationChannel(CHANNEL_CONNECTION, if (de) "Verbindung" else "Connection", NotificationManager.IMPORTANCE_MIN).apply {
            setShowBadge(false)
        }
        manager.createNotificationChannels(listOf(messages, calls, reminders, connection))
    }

    fun canNotify(context: Context) = NotificationManagerCompat.from(context).areNotificationsEnabled()

    /** Opens the app on a page of OfficeHub. */
    fun openPage(context: Context, link: String, requestCode: Int): PendingIntent {
        val intent = Intent(context, MainActivity::class.java)
            .setAction(Intent.ACTION_VIEW)
            .putExtra(MainActivity.EXTRA_LINK, link)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        return PendingIntent.getActivity(context, requestCode, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    fun connection(context: Context): Notification {
        val de = german(context)
        return NotificationCompat.Builder(context, CHANNEL_CONNECTION)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(if (de) "OfficeHub ist verbunden" else "OfficeHub is connected")
            .setContentText(if (de) "Nachrichten und Anrufe kommen sofort an." else "Messages and calls arrive right away.")
            .setOngoing(true)
            .setSilent(true)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setContentIntent(openPage(context, "/", 0))
            .build()
    }

    private fun show(context: Context, id: Int, notification: Notification) {
        if (!canNotify(context)) return
        try {
            NotificationManagerCompat.from(context).notify(id, notification)
        } catch (_: SecurityException) {
            // notifications were not allowed
        }
    }

    fun message(context: Context, m: JSONObject, texts: JSONObject) {
        val conversation = m.optInt("conversation_id")
        val name = m.optString("name")
        val author = m.optString("author").takeIf { it.isNotEmpty() && it != "null" }
        val body = if (m.optBoolean("call")) texts.optString("callPreview", "📞") else m.optString("body")
        val sender = Person.Builder().setName(author ?: name).build()
        val style = NotificationCompat.MessagingStyle(Person.Builder().setName(if (german(context)) "Ich" else "Me").build())
            .setConversationTitle(if (m.optString("kind") == "channel") name else null)
            .setGroupConversation(m.optString("kind") == "channel")
            .addMessage(body, System.currentTimeMillis(), sender)
        val notification = NotificationCompat.Builder(context, CHANNEL_MESSAGES)
            .setSmallIcon(R.drawable.ic_notification)
            .setStyle(style)
            .setContentTitle(name)
            .setContentText(body)
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .setAutoCancel(true)
            .setContentIntent(openPage(context, "/chat/$conversation", conversation))
            .build()
        show(context, conversation, notification)
    }

    /** "{name} hat deinen Antrag „{title}“ genehmigt." from kind + params, in the wording the portal handed over. */
    fun noticeText(n: JSONObject, texts: JSONObject): String {
        val kinds = texts.optJSONObject("kinds") ?: JSONObject()
        val template = kinds.optString(n.optString("kind")).ifEmpty { kinds.optString("other", "OfficeHub") }
        val params = n.optJSONObject("params") ?: JSONObject()
        val requestTypes = texts.optJSONObject("requestTypes") ?: JSONObject()
        return Regex("\\{(\\w+)\\}").replace(template) { match ->
            val key = match.groupValues[1]
            when {
                !params.has(key) -> match.value
                key == "type" -> requestTypes.optString(params.optString(key)).ifEmpty { params.optString(key) }
                else -> params.optString(key)
            }
        }
    }

    fun notice(context: Context, n: JSONObject, texts: JSONObject) {
        if (n.optString("kind") == "meeting_reminder") return // reminders come on their own (with the time)
        val id = n.optInt("id")
        val link = n.optString("link").takeIf { it.startsWith("/") } ?: "/activity"
        val text = noticeText(n, texts)
        val notification = NotificationCompat.Builder(context, CHANNEL_MESSAGES)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(texts.optString("channelName", "OfficeHub"))
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setAutoCancel(true)
            .setContentIntent(openPage(context, link, ID_NOTICE_BASE + id))
            .build()
        show(context, ID_NOTICE_BASE + id, notification)
    }

    fun reminder(context: Context, r: JSONObject, texts: JSONObject) {
        val meeting = r.optInt("meeting_id")
        val startsAt = runCatching { java.time.Instant.parse(r.optString("starts_at")) }.getOrNull()
        val minutes = startsAt?.let { ((it.toEpochMilli() - System.currentTimeMillis()) / 60_000).coerceAtLeast(0) } ?: 0
        val text = if (minutes > 0) texts.optString("reminderIn", "in {n} min").replace("{n}", minutes.toString()) else texts.optString("reminderNow", "now")
        val notification = NotificationCompat.Builder(context, CHANNEL_REMINDERS)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(r.optString("title"))
            .setContentText(text)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setAutoCancel(true)
            .setContentIntent(openPage(context, "/meetings/$meeting/room", ID_REMINDER_BASE + meeting))
            .build()
        show(context, ID_REMINDER_BASE + meeting, notification)
    }

    /** Rings like a phone call: full screen over the lock screen, with Accept and Decline. */
    fun call(context: Context, call: JSONObject, texts: JSONObject) {
        val meeting = call.optInt("meeting_id")
        val caller = call.optJSONObject("caller")?.optString("full_name")?.takeIf { it.isNotEmpty() } ?: call.optString("title")
        val incoming = texts.optString("callIncoming", "is calling …")
        val full = Intent(context, CallActivity::class.java)
            .putExtra(CallActivity.EXTRA_MEETING, meeting)
            .putExtra(CallActivity.EXTRA_NAME, caller)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_NO_USER_ACTION)
        val fullIntent = PendingIntent.getActivity(context, ID_CALL_BASE + meeting, full, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val accept = openPage(context, "/meetings/$meeting/room", ID_CALL_BASE + meeting + 1)
        val decline = PendingIntent.getBroadcast(
            context, ID_CALL_BASE + meeting + 2,
            Intent(context, CallActionReceiver::class.java).setAction(CallActionReceiver.ACTION_DECLINE).putExtra(CallActivity.EXTRA_MEETING, meeting),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val person = Person.Builder().setName(caller).setImportant(true).build()
        val builder = NotificationCompat.Builder(context, CHANNEL_CALLS)
            .setSmallIcon(R.drawable.ic_call)
            .setContentTitle(caller)
            .setContentText(incoming)
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setOngoing(true)
            .setFullScreenIntent(fullIntent, true)
            .setTimeoutAfter(60_000)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            builder.setStyle(NotificationCompat.CallStyle.forIncomingCall(person, decline, accept))
        } else {
            builder.addAction(0, texts.optString("callDecline", "Decline"), decline)
                .addAction(0, texts.optString("callAccept", "Accept"), accept)
                .setContentIntent(fullIntent)
        }
        show(context, ID_CALL_BASE + meeting, builder.build())
    }

    fun stopCall(context: Context, meeting: Int) {
        NotificationManagerCompat.from(context).cancel(ID_CALL_BASE + meeting)
        CallActivity.finishFor(meeting)
    }

    fun clearMessages(context: Context, conversation: Int) {
        NotificationManagerCompat.from(context).cancel(conversation)
    }
}
