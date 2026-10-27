"""Settings from the environment, read once at startup.

These are the server's own settings. What the person tunes from the app
(rate, target, working days, leave) lives in the database instead, see
plan.Prefs.

Nothing secret has a default. On the server the units set the public values
and `/etc/pace.env` supplies the OIDC client secret and the Time Doctor
password.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    db_path: str
    public_url: str
    # Browser login, as in Foodlog and Recipie: a confidential OIDC client
    # with the session kept server-side.
    oidc_issuer: str
    oidc_client_id: str
    oidc_client_secret: str
    # Local development only: every request is this user, login is skipped.
    # Refused when the public URL is https.
    dev_user: str
    session_days: int
    # Time Doctor Classic, signed in to by the worker's headless browser.
    td_email: str
    td_password: str
    # https://<company>.timedoctor.com: where the login form and the
    # reports live.
    td_base_url: str
    # Screenshots and page HTML of a failed fetch go here, so a change on
    # Time Doctor's side can be seen rather than guessed at. Empty: off.
    debug_dir: str
    # Minutes between fetches through the day (around the nudge hours), and overnight.
    fetch_every_min: int
    fetch_idle_every_min: int
    # Public demo (pace-demo): no login, a made-up freelancer's hours, and
    # nothing a visitor sends is stored. See demo.py.
    demo: bool

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")


@lru_cache(maxsize=1)
def settings() -> Settings:
    db_path = os.environ.get("PACE_DB", "pace.db")
    s = Settings(
        db_path=db_path,
        public_url=os.environ.get("PACE_PUBLIC_URL", "http://localhost:5173").rstrip("/"),
        oidc_issuer=os.environ.get("PACE_OIDC_ISSUER", "").rstrip("/"),
        oidc_client_id=os.environ.get("PACE_OIDC_CLIENT_ID", ""),
        oidc_client_secret=os.environ.get("PACE_OIDC_CLIENT_SECRET", ""),
        dev_user=os.environ.get("PACE_DEV_USER", ""),
        session_days=int(os.environ.get("PACE_SESSION_DAYS", "90")),
        td_email=os.environ.get("TD_EMAIL", ""),
        td_password=os.environ.get("TD_PASSWORD", ""),
        td_base_url=os.environ.get("TD_BASE_URL", "").rstrip("/"),
        debug_dir=os.environ.get("PACE_DEBUG_DIR", ""),
        fetch_every_min=int(os.environ.get("PACE_FETCH_EVERY_MIN", "20")),
        fetch_idle_every_min=int(os.environ.get("PACE_FETCH_IDLE_EVERY_MIN", "120")),
        demo=os.environ.get("PACE_DEMO", "") == "1",
    )
    if s.dev_user and s.secure_cookies:
        raise RuntimeError("PACE_DEV_USER skips login; it cannot be used with an https public URL.")
    # As in Foodlog: the demo is public and logs everyone in as "demo".
    # Holding a real secret means it was started with the real unit's
    # environment, and so very likely pointed at the real data.
    if s.demo and (s.oidc_client_secret or s.td_password):
        raise RuntimeError("PACE_DEMO must not run with an OIDC client secret or a Time Doctor password.")
    return s
