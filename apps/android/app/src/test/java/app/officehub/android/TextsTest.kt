package app.officehub.android

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TextsTest {
    private val texts = JSONObject(
        """{"kinds": {"request_approved": "{name} hat deinen Antrag „{title}“ genehmigt.",
                     "request_submitted": "{name} hat einen Antrag gestellt: {title} ({type})",
                     "other": "Es gibt etwas Neues für dich."},
            "requestTypes": {"vacation": "Urlaub"}}""",
    )

    private fun notice(kind: String, params: String) = JSONObject("""{"id": 1, "kind": "$kind", "params": $params}""")

    @Test
    fun notices_use_the_portals_wording() {
        assertEquals(
            "Anna Mayer hat deinen Antrag „Urlaub im Mai“ genehmigt.",
            Notifier.noticeText(notice("request_approved", """{"name": "Anna Mayer", "title": "Urlaub im Mai"}"""), texts),
        )
        assertEquals(
            "Lukas hat einen Antrag gestellt: Sommer (Urlaub)",
            Notifier.noticeText(notice("request_submitted", """{"name": "Lukas", "title": "Sommer", "type": "vacation"}"""), texts),
        )
        // unknown kinds fall back, missing params stay visible instead of crashing
        assertEquals("Es gibt etwas Neues für dich.", Notifier.noticeText(notice("something_new", "{}"), texts))
        assertEquals("{name} hat deinen Antrag „X“ genehmigt.", Notifier.noticeText(notice("request_approved", """{"title": "X"}"""), texts))
    }

    @Test
    fun addresses_are_completed_like_in_the_browser() {
        assertEquals("https://portal.firma.de/", Origin.normalize("portal.firma.de"))
        assertEquals("https://portal.firma.de/", Origin.normalize(" https://portal.firma.de/start "))
        assertEquals("http://10.0.0.5:8080/", Origin.normalize("http://10.0.0.5:8080"))
        assertNull(Origin.normalize(""))
        assertNull(Origin.normalize("ftp://x"))
        assertNull(Origin.normalize("not an address"))
        assertEquals("https://portal.firma.de", Origin.of("https://portal.firma.de/chat/3"))
    }
}
