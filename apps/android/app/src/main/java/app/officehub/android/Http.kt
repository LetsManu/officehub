package app.officehub.android

import android.webkit.CookieManager
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Talks to the company's OfficeHub with the WebView's sign-in (its session cookie). */
object Http {
    val userAgentSuffix = " OfficeHubApp/${BuildConfig.VERSION_NAME} (android)"
    var userAgent: String = "OfficeHubApp/${BuildConfig.VERSION_NAME} (android)"

    class Unauthorized : Exception()

    private fun open(server: String, path: String, method: String, timeoutMs: Int): HttpURLConnection {
        val connection = URL(server.trimEnd('/') + path).openConnection() as HttpURLConnection
        connection.requestMethod = method
        connection.connectTimeout = 15_000
        connection.readTimeout = timeoutMs
        connection.setRequestProperty("User-Agent", userAgent)
        connection.setRequestProperty("Accept", "application/json")
        connection.setRequestProperty("X-Requested-With", "OfficeHub")
        CookieManager.getInstance().getCookie(server)?.let { connection.setRequestProperty("Cookie", it) }
        return connection
    }

    fun get(server: String, path: String, timeoutMs: Int = 20_000): JSONObject {
        val connection = open(server, path, "GET", timeoutMs)
        try {
            val code = connection.responseCode
            if (code == 401) throw Unauthorized()
            if (code !in 200..299) throw java.io.IOException("HTTP $code")
            return JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
        } finally {
            connection.disconnect()
        }
    }

    fun post(server: String, path: String) {
        val connection = open(server, path, "POST", 15_000)
        try {
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json")
            connection.outputStream.use { it.write("{}".toByteArray()) }
            connection.responseCode
        } finally {
            connection.disconnect()
        }
    }

    /** The portal's public settings, if there is an OfficeHub at this address (they name its version). */
    fun config(server: String): JSONObject? = runCatching {
        get(server, "/api/config", 10_000).takeIf { it.has("version") && it.has("meetings_enabled") }
    }.getOrNull()

    /** Where the company login (OpenID Connect) lives, from the public settings. */
    fun signInOrigins(config: JSONObject): Set<String> {
        val list = config.optJSONObject("sso")?.optJSONArray("origins") ?: return emptySet()
        return (0 until list.length()).map { list.optString(it) }.filter { it.startsWith("http") }.toSet()
    }
}
