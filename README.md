# Pace

Freelance hours against a monthly target, with a nudge when they slip.

Set a target in rupees after TDS. Pace turns it into hours from your rate,
the exchange rate and the TDS rate. It reads what you've tracked in Time
Doctor Classic every 20 minutes through the day, and tells you where you
stand: today's quota, how far ahead of or behind the month's plan you are,
what's left, and how much of the time went to meetings rather than
productive work. Hours are flexible: there are working days, but no working
hours. When you're working less than the target needs, the Android app gets
a notification.

It replaces an older dashboard that needed a CSV export by hand; the Time
Doctor API it was meant to use no longer answers.

```
backend/    FastAPI + SQLite: the API, Time Doctor reader, pace maths, nudge rules
frontend/   React web app: dashboard and settings
android/    Kotlin/Compose app: the dashboard on the phone, and the nudges
```

The look is the house instrument style (the Jarvis panel, Recipie,
Foodlog): see the header of `frontend/src/styles.css`.

## How the hours get in

Time Doctor Classic's API stopped working, so `pace-worker` signs in to
your company's Time Doctor site
(`https://<company>.timedoctor.com`) with a headless Chromium (Playwright), the
way a person would. It then reads the JSON the dashboard's own Timesheet
panel uses:

```
GET /individual-timesheet?fromDate=2026-10-01&toDate=2026-10-27
→ users → {id: {timeline: {"2026-10-02": {totaltime: 1489, worktime, editedtime, mobiletime}}}}
```

`totaltime` (seconds, in the company's time zone) is what gets paid: computer,
mobile and manual time together. The session cookies are kept between runs,
so the worker logs in again only when Time Doctor says it isn't signed in.
That endpoint, and the login form (`#email`, `#password`,
`#signinFormButton`), were found by watching the web app in October 2026; if
Time Doctor changes them, a failed read saves a screenshot in
`PACE_DEBUG_DIR`, and the app says it can't read Time Doctor rather than
showing stale numbers as fresh.

**Meetings and work** come from the Projects report, which has time per task
per day. Its page POSTs a form (every project id, your user id, a CSRF token
from the page, the dates) to `/v2/content/projectsReport/renderProjectsReport.php`
and gets JSON with `tasks[].entries[{date, workedTime}]`. The worker opens the
page, takes that request, and sends it again with its own dates. A task
whose name matches the meeting rule (Settings; whole words such as meeting,
standup, call, sync) is a meeting; everything else is productive work.

**History:** the first read backfills the last six whole months of hours and
task time, once.

**Fallback:** in Settings, upload a worklog CSV exported from Time Doctor
(Reports, Worklog, CSV). The days in the file replace what's stored.

## The arithmetic (`backend/pace/plan.py`)

- **Target hours** = target ÷ (rate × USD→INR × (1 − TDS)).
- **Even plan**: target hours spread over the month's working days (your
  weekdays, minus leave). "Behind" compares hours worked with what the plan
  asked of the days already finished. There is no clock: today owes nothing
  until it's over, and every hour worked today counts at once.
- **Today's quota**: what's left of the target before today, spread over the
  working days left including today. It holds steady all day.
- **Out of reach** (the one red state): the quota is over your most-hours-a-day.
- **Projection**: the average of finished working days, carried forward.
  None until a day has finished.
- **Meetings / productive**: the month's task time split by the meeting rule,
  with the tasks listed so a wrong verdict is easy to spot.

## Nudges (`backend/pace/nudges.py`)

Only inside the nudge hours (Settings, default 09:00–21:00: when a
notification is welcome, not when you work), on working days, each at most
once:

| Nudge | When |
|---|---|
| Month behind | first 2 h, if finished days are behind the plan |
| Nothing tracked today yet | from the middle of the nudge hours, under 15 min tracked |
| N left for today | the last 3 h of the nudge hours |
| Today's quota done / target reached | when it happens |
| Can't read Time Doctor | no good read for 3 h; replaces all others, which would quote old numbers |

The server decides; the Android app polls `/api/nudges` every 15 minutes
(WorkManager) and on open, and posts them. No Firebase.

## Development

```bash
# Backend (:8778)
cd backend
uv venv .venv && uv pip install -e '.[dev]'
.venv/bin/python -m playwright install chromium   # once, for the worker
.venv/bin/pytest
PACE_DB=dev.db PACE_DEV_USER=me .venv/bin/python -m pace web

# One Time Doctor read, with the browser visible:
TD_BASE_URL=https://<company>.timedoctor.com TD_EMAIL=… \
  TD_PASSWORD="$(security find-generic-password -s pace-timedoctor -w)" \
  PACE_DB=dev.db .venv/bin/python -m pace fetch --headed

# Frontend (proxies /api and /auth to :8778)
cd frontend && npm install && npm run dev && npm test

# Android (Android SDK, JDK 17)
cd android && ./gradlew testDebugUnitTest assembleDebug
```

`PACE_DEV_USER` skips login and is refused with an https public URL.

## Configuration

| Variable | Used by | |
|---|---|---|
| `PACE_DB` | both | SQLite path; `timedoctor-state.json` (cookies, 0600) goes beside it |
| `PACE_PUBLIC_URL` | web | `https://pace.anishsheela.com` |
| `PACE_OIDC_ISSUER` / `_CLIENT_ID` / `_CLIENT_SECRET` | web | Kanidm login, as Foodlog |
| `TD_BASE_URL` | worker | `https://<company>.timedoctor.com` |
| `TD_EMAIL` / `TD_PASSWORD` | worker | Time Doctor login. Secret: `/etc/pace.env` on the server |
| `TD_USER_ID` | worker | only if the account sees more than one person's timesheet |
| `PACE_DEBUG_DIR` | worker | screenshots of failed reads |
| `PACE_FETCH_EVERY_MIN` / `PACE_FETCH_IDLE_EVERY_MIN` | worker | 20 / 120 |

The rate, target, working days, leave, window, time zone (default
Asia/Kolkata, Time Doctor's company zone) and nudges on/off are set in the
app's Settings.

## Deploying

The server side (the `pace-web` and `pace-worker` units, the nginx vhost, the
Kanidm client `pace-web`, backups) is declared in `nixos-config`; see "Pace"
in its CLAUDE.md. Before the first rebuild, create the client secret and
`/etc/pace.env` (`PACE_OIDC_CLIENT_SECRET`, `TD_EMAIL`, `TD_PASSWORD`).
Then ship code with:

```bash
cp .deploy.env.example .deploy.env   # once
./deploy.sh
```

**Android:** release signing reads `android/keystore.properties` (gitignored),
as in Foodlog. Back up the keystore.

## License

MIT, see `LICENSE`. The bundled fonts (Archivo, IBM Plex Mono, Manjari, in
`frontend/public/fonts/` and `android/app/src/main/res/font/`) keep their own
SIL Open Font License; see `frontend/public/fonts/README.md`.
