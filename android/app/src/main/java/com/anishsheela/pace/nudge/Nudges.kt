package com.anishsheela.pace.nudge

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.anishsheela.pace.MainActivity
import com.anishsheela.pace.PaceApp
import com.anishsheela.pace.R
import com.anishsheela.pace.data.Nudge
import com.anishsheela.pace.data.Unauthorized
import java.util.concurrent.TimeUnit

/**
 * The server decides when to nudge (backend nudges.py); the phone only
 * delivers. Every 15 minutes, WorkManager's shortest period, the worker asks
 * /api/nudges for anything after the last id it has seen and posts each as a
 * notification. No Firebase: nothing goes through Google, at the cost of a
 * nudge arriving up to a quarter of an hour (more in Doze) after it was made.
 *
 * A fresh install starts from the server's latest id rather than 0, so it
 * doesn't replay every nudge ever made.
 */
object Nudges {
    private const val CHANNEL_NUDGES = "nudges"
    private const val CHANNEL_PROGRESS = "progress"
    private const val WORK = "pace-nudges"
    private const val CURSOR = "nudge_cursor"

    fun createChannels(context: Context) {
        val nm = context.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_NUDGES, context.getString(R.string.channel_nudges), NotificationManager.IMPORTANCE_HIGH)
                .apply { description = context.getString(R.string.channel_nudges_about) }
        )
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_PROGRESS, context.getString(R.string.channel_progress), NotificationManager.IMPORTANCE_LOW)
                .apply { description = context.getString(R.string.channel_progress_about) }
        )
    }

    fun schedule(context: Context) {
        val req = PeriodicWorkRequestBuilder<PollWorker>(15, TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(WORK, ExistingPeriodicWorkPolicy.KEEP, req)
    }

    /** Fetch and post what's new. Returns how many were posted. */
    suspend fun poll(context: Context): Int {
        val app = PaceApp.from(context)
        val prefs = context.getSharedPreferences("nudges", Context.MODE_PRIVATE)
        val cursor = prefs.getLong(CURSOR, -1)
        val (items, latest) = app.api.nudges(if (cursor < 0) Long.MAX_VALUE / 2 else cursor)
        if (cursor < 0) {
            prefs.edit().putLong(CURSOR, latest).apply()
            return 0
        }
        items.forEach { post(context, it) }
        val last = items.maxOfOrNull { it.id } ?: cursor
        prefs.edit().putLong(CURSOR, maxOf(last, cursor)).apply()
        return items.size
    }

    fun forget(context: Context) {
        context.getSharedPreferences("nudges", Context.MODE_PRIVATE).edit().clear().apply()
    }

    private fun post(context: Context, n: Nudge) {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        val open = PendingIntent.getActivity(
            context, 0,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val info = n.level == "info"
        val color = ContextCompat.getColor(context, if (info) R.color.arc else R.color.gold)
        val notification = NotificationCompat.Builder(context, if (info) CHANNEL_PROGRESS else CHANNEL_NUDGES)
            .setSmallIcon(R.drawable.ic_notify)
            .setColor(color)
            .setContentTitle(n.title)
            .setContentText(n.body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(n.body))
            .setContentIntent(open)
            .setAutoCancel(true)
            .setWhen(n.createdAt.toInstant().toEpochMilli())
            .setShowWhen(true)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .build()
        // One notification per occasion: the key's kind ("evening", "idle"...)
        // so a newer nudge of the same kind replaces an unread older one.
        NotificationManagerCompat.from(context).notify(n.key.substringBefore(':').hashCode(), notification)
    }
}

class PollWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result = try {
        Nudges.poll(applicationContext)
        Result.success()
    } catch (_: Unauthorized) {
        // Signed out: nothing to do until the app signs in again.
        Result.success()
    } catch (_: Exception) {
        Result.retry()
    }
}
