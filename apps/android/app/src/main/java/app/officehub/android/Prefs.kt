package app.officehub.android

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONObject

/** What the app remembers: the company's OfficeHub, whether someone is signed in, the wording for notifications. */
class Prefs(context: Context) {
    private val prefs: SharedPreferences = context.getSharedPreferences("officehub", Context.MODE_PRIVATE)

    /** e.g. "https://portal.firma.de/" (always ending in "/") */
    var server: String?
        get() = prefs.getString("server", null)
        set(value) = prefs.edit().putString("server", value).apply()

    var signedIn: Boolean
        get() = prefs.getBoolean("signedIn", false)
        set(value) = prefs.edit().putBoolean("signedIn", value).apply()

    /** Texts the portal handed over (frontend lib/native.ts → appTexts) */
    var texts: JSONObject
        get() = prefs.getString("texts", null)?.let { runCatching { JSONObject(it) }.getOrNull() } ?: JSONObject()
        set(value) = prefs.edit().putString("texts", value.toString()).apply()

    /** The company login page (Authentik, Keycloak …): it opens in the app, not in the browser */
    var signInOrigins: Set<String>
        get() = prefs.getStringSet("signInOrigins", emptySet()) ?: emptySet()
        set(value) = prefs.edit().putStringSet("signInOrigins", value).apply()

    var batteryAsked: Boolean
        get() = prefs.getBoolean("batteryAsked", false)
        set(value) = prefs.edit().putBoolean("batteryAsked", value).apply()

    fun origin(): String? = server?.let { Origin.of(it) }
}

object Origin {
    /** "https://portal.firma.de/x" → "https://portal.firma.de" */
    fun of(url: String): String? {
        val uri = runCatching { java.net.URI(url) }.getOrNull() ?: return null
        val scheme = uri.scheme ?: return null
        val host = uri.host ?: return null
        val port = if (uri.port == -1) "" else ":${uri.port}"
        return "$scheme://$host$port"
    }

    /** "portal.firma.de" or "http://10.0.0.5:8080/" → "https://portal.firma.de/" or "http://10.0.0.5:8080/" */
    fun normalize(address: String): String? {
        val trimmed = address.trim().trimEnd('/')
        if (trimmed.isEmpty() || trimmed.contains(' ')) return null
        val withScheme = if ("://" in trimmed) trimmed else "https://$trimmed"
        val uri = runCatching { java.net.URI(withScheme) }.getOrNull() ?: return null
        if (uri.scheme != "https" && uri.scheme != "http") return null
        if (uri.host.isNullOrEmpty()) return null
        return of(withScheme)?.plus("/")
    }
}
