package com.anishsheela.pace.data

import android.content.Context
import android.net.Uri
import android.util.Base64
import androidx.browser.customtabs.CustomTabColorSchemeParams
import androidx.browser.customtabs.CustomTabsIntent
import com.anishsheela.pace.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.concurrent.TimeUnit

class Unauthorized : IOException("Sign in to continue.")
class ServerError(val code: Int, message: String) : IOException(message)

/** The server's /api, as the web app uses it, with the session as a bearer. */
class Api(private val auth: Auth) {

    /** Everything the home screen shows. The raw JSON comes too, to keep for offline. */
    suspend fun summary(): Pair<Summary, String> {
        val o = call(request("/api/summary").get().build())
        return Summary.parse(o) to o.toString()
    }

    suspend fun nudges(after: Long): Pair<List<Nudge>, Long> {
        val o = call(request("/api/nudges?after=$after").get().build())
        val a = o.getJSONArray("nudges")
        return (0 until a.length()).map { Nudge.parse(a.getJSONObject(it)) } to o.getLong("latest")
    }

    suspend fun fetchNow() {
        call(request("/api/fetch").post(ByteArray(0).toRequestBody()).build())
    }

    private fun request(path: String): Request.Builder {
        val token = auth.token ?: throw Unauthorized()
        return Request.Builder()
            .url(BuildConfig.BASE_URL + path)
            .header("Authorization", "Bearer $token")
            // The server's CSRF guard on writes; harmless on reads.
            .header("X-Pace", "1")
    }

    private suspend fun call(req: Request): JSONObject = withContext(Dispatchers.IO) {
        http.newCall(req).execute().use { res ->
            if (res.code == 401) {
                auth.signedOut()
                throw Unauthorized()
            }
            val text = res.body?.string().orEmpty()
            if (!res.isSuccessful) {
                val detail = runCatching { JSONObject(text).optString("detail") }.getOrNull()
                throw ServerError(res.code, detail?.takeIf { it.isNotBlank() } ?: "HTTP ${res.code}")
            }
            JSONObject(text)
        }
    }

    companion object {
        val http: OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .build()
    }
}

/**
 * The session, and how it is got: the same Kanidm sign-in as the web app, in
 * a browser tab. The app sends a hash of a secret it keeps; the server hands
 * the tab a one-time code at pace://signed-in; the app trades code plus
 * secret for a session (backend auth_web.py, /auth/app/exchange).
 *
 * The token lives in the app's private preferences. Backup is off in the
 * manifest, so it never leaves the phone.
 */
class Auth(context: Context) {
    private val prefs = context.getSharedPreferences("auth", Context.MODE_PRIVATE)

    val token: String? get() = prefs.getString("token", null)
    val username: String? get() = prefs.getString("username", null)
    val signedIn: Boolean get() = token != null

    var onChange: () -> Unit = {}

    fun startSignIn(context: Context) {
        val verifier = randomUrlSafe(48)
        prefs.edit().putString("verifier", verifier).apply()
        val url = Uri.parse(BuildConfig.BASE_URL + "/auth/login").buildUpon()
            .appendQueryParameter("app_challenge", s256(verifier))
            .build()
        val colors = CustomTabColorSchemeParams.Builder().setToolbarColor(0xFF0A0E14.toInt()).build()
        CustomTabsIntent.Builder()
            .setDefaultColorSchemeParams(colors)
            .setShowTitle(false)
            .build()
            .launchUrl(context, url)
    }

    /** The tab came back with a code. */
    suspend fun finishSignIn(code: String) = withContext(Dispatchers.IO) {
        val verifier = prefs.getString("verifier", null) ?: throw IOException("Sign-in was not started here. Try again.")
        val body = JSONObject().put("code", code).put("verifier", verifier)
        val req = Request.Builder()
            .url(BuildConfig.BASE_URL + "/auth/app/exchange")
            .post(body.toString().toRequestBody("application/json".toMediaType()))
            .build()
        Api.http.newCall(req).execute().use { res ->
            val text = res.body?.string().orEmpty()
            if (!res.isSuccessful) {
                throw IOException(runCatching { JSONObject(text).optString("detail") }.getOrNull() ?: "Sign-in failed.")
            }
            val o = JSONObject(text)
            prefs.edit()
                .putString("token", o.getString("token"))
                .putString("username", o.optString("username"))
                .remove("verifier")
                .apply()
        }
        onChange()
    }

    /** The server stopped accepting the session (expired, or signed out elsewhere). */
    fun signedOut() {
        prefs.edit().remove("token").apply()
        onChange()
    }

    suspend fun signOut() = withContext(Dispatchers.IO) {
        val t = token
        if (t != null) {
            runCatching {
                Api.http.newCall(
                    Request.Builder().url(BuildConfig.BASE_URL + "/auth/logout")
                        .header("Authorization", "Bearer $t").header("X-Pace", "1")
                        .post(ByteArray(0).toRequestBody()).build()
                ).execute().close()
            }
        }
        prefs.edit().clear().apply()
        onChange()
    }

    companion object {
        private val random = SecureRandom()

        fun randomUrlSafe(bytes: Int): String =
            ByteArray(bytes).also { random.nextBytes(it) }.let { Base64.encodeToString(it, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP) }

        fun s256(verifier: String): String =
            Base64.encodeToString(
                MessageDigest.getInstance("SHA-256").digest(verifier.toByteArray()),
                Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP,
            )
    }
}
