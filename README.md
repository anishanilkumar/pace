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
your company's Time Doctor site (`https://<company>.timedoctor.com`) with a
headless Chromium (Playwright), the way a person would, and reads the
**Timeline** report: every stretch of work with its start, end and task.

```
POST /v2/content/reports/timeline_report/getTimeLineReportData.php
     userIds, fromDate=toDate=<day>, timezone=<Time Doctor's id for your zone>, exportToType=web
→ users → [{tasks → [{start_time, end_time, task_name, client_name, work_time, work_mode}]}]
```

Why the Timeline and not the timesheet: Time Doctor's daily totals are cut at
the company's midnight (GMT+05:30 here). Working from Germany, everything
after 19:30 lands on the next day there. The Timeline converts each stretch
to the zone asked for, so Pace asks in yours (**Settings, Your time zone**)
and a day runs from your midnight. Over September and October the totals
match the timesheet's; only late-evening work moves to the right day.

One request per day: each read takes yesterday and today, the whole month
once a day (for edited time), and, once, six months of history (about 200
requests, under a minute). `work_mode` 5 is "Not Working" and is left out;
computer time (0) and edited time (3) count. The session cookies are kept
between runs, so the worker logs in again only when sent to the login page.
These endpoints and the login form (`#email`, `#password`,
`#signinFormButton`) were found by watching the web app in October 2026; if
Time Doctor changes them, a failed read saves a screenshot in
`PACE_DEBUG_DIR`, and the app says it can't read Time Doctor rather than
showing stale numbers as fresh.

**Meetings and work** come from the same entries: a task whose name matches
the meeting rule (Settings; whole words such as meeting, standup, call,
sync) is a meeting; everything else is productive work.

**History:** the first read backfills the last six whole months, once, and
again if you change your time zone.

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

## Several people

Pace serves anyone allowed in by the identity provider (Kanidm group
`pace.users`), and each person sees only their own hours, settings, Time
Doctor login and nudges: every table carries the Kanidm username, and every
query is filtered by the signed-in person (`backend/pace/db.py`).

- **Time Doctor logins** are given by each person in Settings. The password
  is stored as a Fernet token (`backend/pace/secrets.py`) with the key in
  `PACE_SECRET_KEY` or, if unset, a `secret.key` file made beside the
  database (0600). The backup copies only the database, so a leaked backup
  holds no usable passwords; a restore without the key just means everyone
  enters their password again. The API never returns a password.
- **The worker** reads for everyone with a login, one after another, each on
  their own schedule, time zone and saved session (`timedoctor-state-<user>.json`).
- **The owner** (`PACE_OWNER`, or whoever the single-user data was migrated
  to) can keep using `TD_EMAIL`/`TD_PASSWORD` from the environment until
  they set a login in Settings.
- **Adding someone** is a Kanidm matter: a person in group `pace.users`, and a
  credential reset link for them. They then sign in, add their Time Doctor
  login and rate in Settings, and the first read takes in six months.

## Public demo

`PACE_DEMO=1` runs the web app as a public demo, on the same build: no
login (every visitor is `demo`), no worker and no Time Doctor. A made-up
freelancer in Berlin (30 USD an hour, ₹2,00,000 a month after TDS) has six
months of history, good months and slow ones, with standups, planning and
client calls among the tasks (`backend/pace/demo.py`). Each past day is drawn
from a generator seeded with its date, so it's the same for every visitor;
today fills up with the clock. Sync regenerates it to the minute, the nudge
rules run on it as on real hours, and settings changes and uploads are
refused, so nothing a visitor does is kept. It refuses to start with an OIDC
client secret or a Time Doctor password set.

## Development

```bash
# Backend (:8778)
cd backend
uv venv .venv && uv pip install -e '.[dev]'
.venv/bin/python -m playwright install chromium   # once, for the worker
.venv/bin/pytest
PACE_DB=dev.db PACE_DEV_USER=me .venv/bin/python -m pace web

# One Time Doctor read for one person, with the browser visible:
TD_BASE_URL=https://<company>.timedoctor.com TD_EMAIL=… PACE_OWNER=me \
  TD_PASSWORD="$(security find-generic-password -s pace-timedoctor -w)" \
  PACE_DB=dev.db .venv/bin/python -m pace fetch --user me --headed

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
| `TD_EMAIL` / `TD_PASSWORD` | worker | The owner's Time Doctor login, until they set one in Settings. Secret: `/etc/pace.env` |
| `PACE_OWNER` | both | Whose that env login (and any single-user data) is; found from the sessions if unset |
| `PACE_SECRET_KEY` | both | Key for the stored Time Doctor passwords; a `secret.key` file beside the database if unset |
| `PACE_DEBUG_DIR` | worker | screenshots of failed reads |
| `PACE_FETCH_EVERY_MIN` / `PACE_FETCH_IDLE_EVERY_MIN` | worker | 20 / 120 |

The rate, target, working days, leave, your time zone, nudge hours, the
meeting rule and nudges on/off are set in the app's Settings.

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
