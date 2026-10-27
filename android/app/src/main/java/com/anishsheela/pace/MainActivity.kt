package com.anishsheela.pace

import android.Manifest
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.browser.customtabs.CustomTabColorSchemeParams
import androidx.browser.customtabs.CustomTabsIntent
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.lifecycleScope
import com.anishsheela.pace.data.Summary
import com.anishsheela.pace.data.Unauthorized
import com.anishsheela.pace.nudge.Nudges
import com.anishsheela.pace.ui.HomeScreen
import com.anishsheela.pace.ui.HomeState
import com.anishsheela.pace.ui.PaceTheme
import com.anishsheela.pace.ui.SignInScreen
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.io.IOException

class MainActivity : ComponentActivity() {
    private var signedIn by mutableStateOf(false)
    private var signInError by mutableStateOf<String?>(null)
    private var home by mutableStateOf(HomeState(null, offline = false, error = null, loading = true))
    private var watching: Job? = null

    private val askNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(0xFF0A0E14.toInt()),
            navigationBarStyle = SystemBarStyle.dark(0xFF0A0E14.toInt()),
        )
        super.onCreate(savedInstanceState)
        val app = PaceApp.from(this)
        signedIn = app.auth.signedIn
        app.auth.onChange = { runOnUiThread { signedIn = app.auth.signedIn; if (signedIn) refresh() } }
        // The last numbers seen, shown at once and marked with their age
        // until fresh ones arrive (or don't, offline).
        cached()?.let { home = home.copy(summary = it) }
        if (savedInstanceState == null) handle(intent)
        if (Build.VERSION.SDK_INT >= 33) askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)

        setContent {
            PaceTheme(offline = home.offline) {
                if (!signedIn) {
                    SignInScreen(signInError) { app.auth.startSignIn(this) }
                } else {
                    HomeScreen(
                        state = home,
                        onFetchNow = ::fetchNow,
                        onRetry = ::refresh,
                        onSettings = { openWeb("/#settings") },
                        onSignOut = {
                            lifecycleScope.launch {
                                app.auth.signOut()
                                getSharedPreferences("cache", Context.MODE_PRIVATE).edit().clear().apply()
                                Nudges.forget(this@MainActivity)
                                home = HomeState(null, offline = false, error = null, loading = true)
                            }
                        },
                    )
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    override fun onResume() {
        super.onResume()
        if (signedIn) refresh()
    }

    /** The sign-in handoff. */
    private fun handle(intent: Intent?) {
        if (intent?.data?.scheme == "pace" && intent.data?.host == "signed-in") {
            val code = intent.data?.getQueryParameter("code") ?: return
            lifecycleScope.launch {
                runCatching { PaceApp.from(this@MainActivity).auth.finishSignIn(code) }
                    .onSuccess { signInError = null }
                    .onFailure { signInError = it.message ?: "Sign-in failed. Try again." }
            }
        }
    }

    private fun refresh(): Job = lifecycleScope.launch {
        home = home.copy(loading = true)
        val app = PaceApp.from(this@MainActivity)
        try {
            val (summary, raw) = app.api.summary()
            getSharedPreferences("cache", Context.MODE_PRIVATE).edit().putString("summary", raw).apply()
            home = HomeState(summary, offline = false, error = null, loading = false)
            // Opening the app delivers waiting nudges too, not only the worker.
            runCatching { Nudges.poll(this@MainActivity) }
        } catch (_: Unauthorized) {
            home = home.copy(loading = false)
        } catch (e: IOException) {
            home = home.copy(offline = e !is com.anishsheela.pace.data.ServerError, error = e.message, loading = false)
        }
    }

    /** Ask the server to read Time Doctor now, then watch until it has. */
    private fun fetchNow() {
        watching?.cancel()
        watching = lifecycleScope.launch {
            runCatching { PaceApp.from(this@MainActivity).api.fetchNow() }
            refresh().join()
            // The worker looks every 30 s and a read takes a few more.
            repeat(24) {
                delay(5000)
                refresh().join()
                if (home.summary?.fetchRequested != true) return@launch
            }
        }
    }

    private fun cached(): Summary? =
        getSharedPreferences("cache", Context.MODE_PRIVATE).getString("summary", null)
            ?.let { runCatching { Summary.parse(JSONObject(it)) }.getOrNull() }

    /** Settings live in the web app: a form is better on a page than rebuilt here. */
    private fun openWeb(path: String) {
        val colors = CustomTabColorSchemeParams.Builder().setToolbarColor(0xFF0A0E14.toInt()).build()
        CustomTabsIntent.Builder().setDefaultColorSchemeParams(colors).build()
            .launchUrl(this, Uri.parse(BuildConfig.BASE_URL + path))
    }
}
