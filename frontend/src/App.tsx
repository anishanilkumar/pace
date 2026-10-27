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
        <span className="wordmark">Pace</span>
        <div className="topbar-right">
          {summary && <FetchPill fetch={summary.fetch} offline={failed === "Offline"} onClick={fetchNow} />}
          {view === "dashboard" && <button className="pill" onClick={() => go("settings")}>Settings</button>}
        </div>
      </header>

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
        <Settings key={JSON.stringify(summary.prefs)} prefs={summary.prefs} onSaved={() => load()} onBack={() => go("dashboard")} />
      ) : (
        <Dashboard
          plan={summary.plan}
          prefs={summary.prefs}
          fetch={summary.fetch}
          nudges={summary.nudges}
          month={summary.plan.month}
          onMonth={(by) => { const m = shiftMonth(summary.plan.month, by); setMonth(m); }}
          onOpenSettings={() => go("settings")}
        />
      )}
    </main>
  );
}

/** Where the hours came from and how old they are. Tap to read Time Doctor now. */
function FetchPill({ fetch, offline, onClick }: { fetch: FetchState; offline: boolean; onClick: () => void }) {
  let dot = "";
  let text: string;
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
    text = fetch.last_good_at ? `Read ${stamp(fetch.last_good_at)}` : "Not read";
  } else if (!fetch.last_good_at) {
    dot = "pill-dot-stale";
    text = "Not read yet";
  } else {
    dot = ageMin(fetch.last_good_at) > STALE_MIN ? "pill-dot-stale" : "";
    text = `${fetch.last_good_source === "upload" ? "Uploaded" : "Read"} ${stamp(fetch.last_good_at)}`;
  }
  return (
    <button className={`pill${warn ? " pill-warn" : ""}`} onClick={onClick} disabled={offline || fetch.requested}
      title={fetch.last_error ?? "Read Time Doctor now"}>
      <span className={`pill-dot ${dot}`} />
      {text}
    </button>
  );
}
