import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { ageMin, shiftMonth, stamp } from "./format";
import { Dashboard, STALE_MIN } from "./pages/Dashboard";
import { Settings } from "./pages/Settings";
import type { FetchState, Summary } from "./types";

type View = "dashboard" | "settings";

const viewFromHash = (): View => (location.hash === "#settings" ? "settings" : "dashboard");

export function App() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [month, setMonth] = useState<string | null>(null);
  const [view, setView] = useState<View>(viewFromHash);
  const [failed, setFailed] = useState<string | null>(null);
  const poll = useRef<number | null>(null);

  const load = useCallback(async (m: string | null = month) => {
    try {
      const s = await api.summary(m ?? undefined);
      setSummary(s);
      setFailed(null);
      document.documentElement.removeAttribute("data-connection");
      return s;
    } catch (e) {
      if (e instanceof ApiError) setFailed(e.message);
      else {
        // The server out of reach: the last numbers stay, in the offline look.
        document.documentElement.setAttribute("data-connection", "offline");
        setFailed("Offline");
      }
      return null;
    }
  }, [month]);

  useEffect(() => { load(); }, [load]);

  // Fresh numbers when the tab comes back, and every five minutes while open.
  useEffect(() => {
    const onVisible = () => { if (document.visibilityState === "visible") load(); };
    document.addEventListener("visibilitychange", onVisible);
    const t = window.setInterval(() => load(), 5 * 60_000);
    return () => { document.removeEventListener("visibilitychange", onVisible); window.clearInterval(t); };
  }, [load]);

  useEffect(() => {
    const onHash = () => setView(viewFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const go = (v: View) => { location.hash = v === "settings" ? "settings" : ""; setView(v); window.scrollTo(0, 0); };

  async function fetchNow() {
    await api.fetchNow().catch(() => null);
    await load();
    // The worker looks for a request every 30 s and a read takes a few more:
    // check back until it has answered, for at most two minutes.
    if (poll.current) window.clearInterval(poll.current);
    const until = Date.now() + 120_000;
    poll.current = window.setInterval(async () => {
      const s = await load();
      if (!s || !s.fetch.requested || Date.now() > until) {
        window.clearInterval(poll.current!);
        poll.current = null;
      }
    }, 5000);
  }

  return (
    <main className="page">
      <header className="topbar">
        {/* Home: the dashboard, on this month. */}
        <button className="wordmark wordmark-home" onClick={() => { setMonth(null); go("dashboard"); }} aria-label="Pace, home">
          Pace
        </button>
        <div className="topbar-right">
          {summary && (summary.demo ? (
            <span className="pill pill-status pill-demo" title="Made-up hours; nothing you change is kept">
              <span className="pill-dot pill-dot-demo" aria-hidden="true" />Demo
            </span>
          ) : <FetchStatus fetch={summary.fetch} offline={failed === "Offline"} />)}
          {summary && (
            <button className="btn btn-sync" onClick={fetchNow} disabled={failed === "Offline" || summary.fetch.requested || !summary.timedoctor.connected}
              title="Read Time Doctor now" aria-label="Sync with Time Doctor">
              <svg className={`icon${summary.fetch.requested ? " icon-turning" : ""}`} viewBox="0 0 20 20" aria-hidden="true">
                <path d="M4 8a6 6 0 0 1 11-2.5M16 12a6 6 0 0 1-11 2.5" />
                <path d="M15 2.5v3h-3M5 17.5v-3h3" />
              </svg>
              <span className="btn-label">{summary.fetch.requested ? "Syncing" : "Sync"}</span>
            </button>
          )}
          {view === "dashboard" && <button className="pill" onClick={() => go("settings")}>Settings</button>}
        </div>
      </header>

      {summary?.demo && view === "dashboard" && (
        <p className="demo-note">
          A demo with made-up hours: a freelancer in Berlin aiming for ₹2,00,000 a month after TDS. Today fills
          up as the day goes on. Sync brings it up to the minute; nothing you change is kept.{" "}
          <a href="https://github.com/anishanilkumar/pace">Source</a>
        </p>
      )}

      {!summary ? (
        failed ? (
          <div className="empty">
            <div className="empty-title">Can't load</div>
            <div>{failed}</div>
            <button className="btn" onClick={() => load()}>Try again</button>
          </div>
        ) : (
          <>
            <div className="placeholder instrument"><div className="placeholder-line" /></div>
            <div className="placeholder instrument" style={{ minHeight: "20rem" }} />
          </>
        )
      ) : view === "settings" ? (
        <Settings key={JSON.stringify(summary.prefs)} prefs={summary.prefs} demo={summary.demo}
          user={summary.user} timedoctor={summary.timedoctor} onSaved={() => load()} onBack={() => go("dashboard")} />
      ) : (
        <Dashboard
          plan={summary.plan}
          work={summary.work}
          prefs={summary.prefs}
          fetch={summary.fetch}
          timedoctor={summary.timedoctor}
          nudges={summary.nudges}
          history={summary.history}
          month={summary.plan.month}
          onMonth={(by) => { const m = shiftMonth(summary.plan.month, by); setMonth(m); }}
          onOpenMonth={(m) => {
            setMonth(summary.history.find((h) => h.month === m)?.current ? null : m);
            window.scrollTo(0, 0);
          }}
          onOpenSettings={() => go("settings")}
        />
      )}
    </main>
  );
}

/** Where the hours came from and how old they are; the Sync button beside it reads Time Doctor now. */
function FetchStatus({ fetch, offline }: { fetch: FetchState; offline: boolean }) {
  let dot = "";
  let text: string;
  // "Read" before a time: dropped on a narrow phone, where the time alone says it.
  let word = "";
  let warn = false;
  if (offline) {
    dot = "pill-dot-stale";
    text = "Offline";
  } else if (fetch.requested) {
    dot = "pill-dot-reading";
    text = "Reading";
  } else if (fetch.last_ok === false) {
    dot = "pill-dot-failing";
    warn = true;
    [word, text] = fetch.last_good_at ? ["Read", stamp(fetch.last_good_at)] : ["", "Not read"];
  } else if (!fetch.last_good_at) {
    dot = "pill-dot-stale";
    text = "Not read yet";
  } else {
    dot = ageMin(fetch.last_good_at) > STALE_MIN ? "pill-dot-stale" : "";
    word = fetch.last_good_source === "upload" ? "Uploaded" : "Read";
    text = stamp(fetch.last_good_at);
  }
  return (
    <span className={`pill pill-status${warn ? " pill-warn" : ""}`} title={fetch.last_error ?? undefined} role="status">
      <span className={`pill-dot ${dot}`} />
      {word && <span className="pill-word">{word}</span>}
      {text}
    </span>
  );
}
