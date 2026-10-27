package com.anishsheela.pace.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun SignInScreen(error: String?, onSignIn: () -> Unit) {
    val p = LocalPalette.current
    Column(
        Modifier.fillMaxSize().background(p.ground).systemBarsPadding().padding(Dim.pad),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("PACE", style = Type.wordmark, color = p.ink)
        Box(Modifier.height(24.dp))
        Text("Hours against the month's target.", style = Type.body, color = p.inkDim)
        Box(Modifier.height(32.dp))
        Btn("Sign in", onSignIn, Modifier.fillMaxWidth(), kind = BtnKind.Primary, minHeight = 56.dp)
        if (error != null) {
            Box(Modifier.height(16.dp))
            Text(error, style = Type.control, color = p.gold)
        }
    }
}
