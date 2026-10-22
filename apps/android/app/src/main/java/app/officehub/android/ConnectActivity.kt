package app.officehub.android

import android.content.Intent
import android.os.Bundle
import android.view.inputmethod.EditorInfo
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.updatePadding
import com.google.android.material.button.MaterialButton
import com.google.android.material.textfield.TextInputEditText
import com.google.android.material.textfield.TextInputLayout
import kotlin.concurrent.thread

/** First start: which OfficeHub this app belongs to (the address people open in the browser). */
class ConnectActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_connect)
        val root = findViewById<android.view.View>(R.id.root)
        ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            view.updatePadding(top = bars.top, bottom = bars.bottom)
            insets
        }
        val layout = findViewById<TextInputLayout>(R.id.addressLayout)
        val input = findViewById<TextInputEditText>(R.id.address)
        val button = findViewById<MaterialButton>(R.id.connect)

        fun connect() {
            val server = Origin.normalize(input.text?.toString() ?: "")
            if (server == null) {
                layout.error = getString(R.string.address_invalid)
                return
            }
            layout.error = null
            button.isEnabled = false
            button.setText(R.string.checking)
            // Without "http://" try https first, then http (many company servers run plain http inside the network)
            val typed = input.text?.toString() ?: ""
            val candidates = if ("://" in typed) listOf(server) else listOf(server, server.replaceFirst("https://", "http://"))
            thread {
                val found = candidates.firstNotNullOfOrNull { candidate -> Http.config(candidate)?.let { candidate to it } }
                runOnUiThread {
                    button.isEnabled = true
                    button.setText(R.string.connect)
                    if (found == null) {
                        layout.error = getString(R.string.address_unreachable)
                        return@runOnUiThread
                    }
                    Prefs(this).server = found.first
                    Prefs(this).signInOrigins = Http.signInOrigins(found.second)
                    startActivity(Intent(this, MainActivity::class.java))
                    finish()
                }
            }
        }

        button.setOnClickListener { connect() }
        input.setOnEditorActionListener { _, action, _ ->
            if (action == EditorInfo.IME_ACTION_GO) {
                connect()
                true
            } else {
                false
            }
        }
    }
}
