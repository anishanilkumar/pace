package com.anishsheela.pace

import android.app.Application
import android.content.Context
import com.anishsheela.pace.data.Api
import com.anishsheela.pace.data.Auth
import com.anishsheela.pace.nudge.Nudges

class PaceApp : Application() {
    lateinit var auth: Auth
        private set
    lateinit var api: Api
        private set

    override fun onCreate() {
        super.onCreate()
        auth = Auth(this)
        api = Api(auth)
        Nudges.createChannels(this)
        Nudges.schedule(this)
    }

    companion object {
        fun from(context: Context) = context.applicationContext as PaceApp
    }
}
