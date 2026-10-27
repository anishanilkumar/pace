"""Browser login: OIDC authorization code + PKCE, session kept server-side.

Pace is a *confidential* client of the identity provider (Kanidm on the
server). The browser only ever holds an opaque, HttpOnly session cookie; the
access and ID tokens never reach JavaScript, so there is nothing for an XSS or
a stray localStorage dump to steal. Sessions last 90 days and slide forward
while in use, which matters for a phone app that may sit unopened for a week and
should still just work.

Who may log in is decided by the identity provider: Kanidm only issues tokens
for this client to members of the group its scope map names.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re
import secrets
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import db
from .config import settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth")

COOKIE = "pace_session"
_discovery: dict | None = None
_jwks: jwt.PyJWKClient | None = None


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _oidc() -> dict:
    global _discovery
    if _discovery is None:
        s = settings()
        if not (s.oidc_issuer and s.oidc_client_id and s.oidc_client_secret):
            raise HTTPException(503, "Login is not configured on this server.")
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(s.oidc_issuer + "/.well-known/openid-configuration")
            r.raise_for_status()
            _discovery = r.json()
    return _discovery


def _callback_url() -> str:
    return settings().public_url + "/auth/callback"


def _s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def current_user(request: Request) -> str | None:
    s = settings()
    if s.dev_user:
        return s.dev_user
    # The web app sends its session as a cookie; the Android app, which has no
    # cookie jar shared with the browser it signed in through, as a bearer.
    token = request.cookies.get(COOKIE)
    auth = request.headers.get("authorization", "")
    if not token and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        return None
    return db.session_user(_hash(token), s.session_days)


# The Android app signs in through this same flow, in a browser tab. It starts
# with /auth/login?app_challenge=S256(verifier); instead of a cookie, the
# callback hands the tab a one-time code at APP_REDIRECT, which the app trades
# for a session at /auth/app/exchange by showing the verifier. Another app
# that registered the same URL scheme and caught the code can't redeem it.
APP_REDIRECT = "pace://signed-in"
_CHALLENGE = re.compile(r"^[A-Za-z0-9_-]{43}$")


@router.get("/login")
async def login(app_challenge: str = ""):
    if app_challenge and not _CHALLENGE.match(app_challenge):
        raise HTTPException(400, "Bad app_challenge.")
    meta = await _oidc()
    s = settings()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = _s256(verifier)
    db.put_login_state(state, verifier, nonce, app_challenge)
    query = urlencode({
        "response_type": "code",
        "client_id": s.oidc_client_id,
        "redirect_uri": _callback_url(),
        "scope": "openid profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return RedirectResponse(f"{meta['authorization_endpoint']}?{query}", status_code=302)


@router.get("/callback")
async def callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        raise HTTPException(403, f"Sign-in was refused: {error}")
    pending = db.pop_login_state(state) if state else None
    if not code or pending is None:
        # Expired (10 min) or replayed. Start over rather than explain.
        return RedirectResponse("/auth/login", status_code=302)

    meta = await _oidc()
    s = settings()
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            meta["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _callback_url(),
                "code_verifier": pending["verifier"],
            },
            auth=(s.oidc_client_id, s.oidc_client_secret),
        )
    if r.status_code != 200:
        log.warning("token exchange failed: %s %s", r.status_code, r.text[:300])
        raise HTTPException(502, "The sign-in server did not accept the login. Try again.")
    claims = await asyncio.to_thread(_verify_id_token, r.json().get("id_token", ""), meta, pending["nonce"])
    username = claims.get("preferred_username") or claims["sub"]

    if pending.get("app_challenge"):
        code = secrets.token_urlsafe(32)
        db.put_app_handoff(_hash(code), username, pending["app_challenge"])
        log.info("signed in (app handoff): %s", username)
        return HTMLResponse(_handoff_page(f"{APP_REDIRECT}?{urlencode({'code': code})}"),
                            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

    token = secrets.token_urlsafe(32)
    db.create_session(_hash(token), username, s.session_days)
    log.info("signed in: %s", username)
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(
        COOKIE, token,
        max_age=s.session_days * 86400,
        httponly=True,
        secure=s.secure_cookies,
        samesite="lax",
        path="/",
    )
    return resp


def _verify_id_token(id_token: str, meta: dict, nonce: str) -> dict:
    global _jwks
    if _jwks is None:
        _jwks = jwt.PyJWKClient(meta["jwks_uri"], cache_keys=True, lifespan=3600)
    try:
        key = _jwks.get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(
            id_token, key,
            # Pinned, never read from the token header.
            algorithms=["ES256", "RS256"],
            audience=settings().oidc_client_id,
            issuer=meta["issuer"],
            leeway=30,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        log.warning("rejecting id_token: %s", exc)
        raise HTTPException(403, "The sign-in could not be verified. Try again.")
    if not secrets.compare_digest(claims.get("nonce", ""), nonce):
        raise HTTPException(403, "The sign-in could not be verified. Try again.")
    return claims


def _handoff_page(url: str) -> str:
    # A page rather than a 302: Chrome won't follow a redirect into an app
    # without a user gesture, and a sign-in Kanidm completes on its own (an
    # existing session) has none. The script tries; the button always works.
    # The code is URL-safe base64, so the URL needs no HTML escaping.
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0a0e14"><title>Pace</title>
<style>
body {{ margin: 0; min-height: 100dvh; display: grid; place-items: center; background: #0a0e14; color: #e8f1f8;
       font: 16px/1.45 ui-monospace, monospace; text-align: center; }}
a {{ display: inline-block; margin-top: 1rem; padding: 0.875rem 1.5rem; background: #3dd6f5; color: #0a0e14;
     border-radius: 2px; text-decoration: none; text-transform: uppercase; letter-spacing: 0.08em; }}
p {{ color: #7c8fa3; text-transform: uppercase; letter-spacing: 0.16em; font-size: 13px; }}
</style></head>
<body><main><p>Signed in</p><a href="{url}">Open Pace</a></main>
<script>location.replace("{url}")</script></body></html>"""


class Exchange(BaseModel):
    code: str = Field(min_length=20, max_length=200)
    verifier: str = Field(min_length=43, max_length=128)


@router.post("/app/exchange")
async def app_exchange(body: Exchange):
    handoff = db.pop_app_handoff(_hash(body.code))
    if handoff is None or not secrets.compare_digest(_s256(body.verifier), handoff["challenge"]):
        raise HTTPException(403, "Sign-in expired or was not for this app. Sign in again.")
    s = settings()
    token = secrets.token_urlsafe(32)
    db.create_session(_hash(token), handoff["username"], s.session_days)
    return {"token": token, "username": handoff["username"], "days": s.session_days}


@router.post("/logout")
async def logout(request: Request):
    token = request.cookies.get(COOKIE)
    auth = request.headers.get("authorization", "")
    if not token and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if token:
        db.drop_session(_hash(token))
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(COOKIE, path="/")
    return resp
