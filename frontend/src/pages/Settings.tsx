import { useState } from "react";
import { api, ApiError } from "../api";
import { clock, rupees } from "../format";
import type { Prefs } from "../types";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function Settings({ prefs, onSaved, onBack }: {
  prefs: Prefs;
  onSaved: () => void;
  onBack: () => void;
}) {
  const [p, setP] = useState<Prefs>(prefs);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [leave, setLeave] = useState("");
  const [upload, setUpload] = useState<string | null>(null);
  const dirty = JSON.stringify(p) !== JSON.stringify(prefs);

  const set = <K extends keyof Prefs>(k: K, v: Prefs[K]) => { setP({ ...p, [k]: v }); setSaved(false); };
  const num = (k: "hourly_rate_usd" | "usd_inr" | "tds_pct" | "target_net_inr" | "max_hours_per_day") =>
    (e: React.ChangeEvent<HTMLInputElement>) => set(k, e.target.value === "" ? (0 as never) : Number(e.target.value));

  const netPerHour = p.hourly_rate_usd * p.usd_inr * (1 - p.tds_pct / 100);
  const targetHours = netPerHour > 0 ? p.target_net_inr / netPerHour : 0;

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.savePrefs(p);
      setSaved(true);
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't reach the server.");
    } finally {
      setBusy(false);
    }
  }

  async function sendCsv(file: File | undefined) {
    if (!file) return;
    setUpload("Reading…");
    try {
      const r = await api.upload(file);
      setUpload(`Took ${r.days} days, ${r.from} to ${r.to}.`);
      onSaved();
    } catch (e) {
      setUpload(e instanceof ApiError ? e.message : "Couldn't reach the server.");
    }
  }

  return (
    <>
      <button className="back" onClick={onBack}>Back</button>

      <section className="instrument form">
        <div className="label">Money</div>
        <div className="form-grid">
          <label className="field"><span>Rate, USD an hour</span>
            <input type="number" inputMode="decimal" step="0.01" min="0" value={p.hourly_rate_usd} onChange={num("hourly_rate_usd")} /></label>
          <label className="field"><span>USD to INR</span>
            <input type="number" inputMode="decimal" step="0.01" min="0" value={p.usd_inr} onChange={num("usd_inr")} /></label>
          <label className="field"><span>TDS, %</span>
            <input type="number" inputMode="decimal" step="0.1" min="0" max="60" value={p.tds_pct} onChange={num("tds_pct")} /></label>
          <label className="field"><span>Target a month, INR after TDS</span>
            <input type="number" inputMode="numeric" step="1000" min="0" value={p.target_net_inr} onChange={num("target_net_inr")} /></label>
        </div>
        <div className="field-note">
          {rupees(netPerHour)} an hour after TDS, so the target is {clock(targetHours)} h a month.
        </div>
      </section>

      <section className="instrument form">
        <div className="label">Working days</div>
        <div className="days" role="group" aria-label="Working days">
          {DAYS.map((d, i) => {
            const on = p.work_days.includes(i);
            return (
              <button key={d} type="button" className="tick" aria-pressed={on}
                onClick={() => set("work_days", on ? p.work_days.filter((x) => x !== i) : [...p.work_days, i].sort())}>
                {d}
              </button>
            );
          })}
        </div>
        <div className="form-grid">
          <label className="field"><span>Day starts</span>
            <input type="time" value={p.day_start} onChange={(e) => set("day_start", e.target.value)} /></label>
          <label className="field"><span>Day ends</span>
            <input type="time" value={p.day_end} onChange={(e) => set("day_end", e.target.value)} /></label>
          <label className="field"><span>Most hours in a day</span>
            <input type="number" inputMode="decimal" step="0.5" min="1" max="24" value={p.max_hours_per_day} onChange={num("max_hours_per_day")} /></label>
          <label className="field"><span>Time zone</span>
            <input type="text" value={p.tz} onChange={(e) => set("tz", e.target.value)} spellCheck={false} /></label>
        </div>
        <div className="field-note">
          The time zone must match Time Doctor's company zone: its days are the days here.
        </div>
      </section>

      <section className="instrument form">
        <div className="label">Leave</div>
        <div className="add-row">
          <label className="field"><span>Day off</span>
            <input type="date" value={leave} onChange={(e) => setLeave(e.target.value)} /></label>
          <button className="btn" type="button" disabled={!leave}
            onClick={() => { set("leaves", [...new Set([...p.leaves, leave])].sort()); setLeave(""); }}>Add</button>
        </div>
        {p.leaves.length > 0 ? (
          <div className="chips">
            {p.leaves.map((d) => (
              <span className="chip" key={d}>{d}
                <button type="button" aria-label={`Remove ${d}`} onClick={() => set("leaves", p.leaves.filter((x) => x !== d))}>×</button>
              </span>
            ))}
          </div>
        ) : (
          <div className="field-note">No leave set. A day of leave drops out of the plan.</div>
        )}
      </section>

      <section className="instrument form">
        <div className="label">Nudges</div>
        <button type="button" className="tick" aria-pressed={p.nudges} onClick={() => set("nudges", !p.nudges)}>
          {p.nudges ? "On" : "Off"}
        </button>
        <div className="field-note">
          Sent to the Android app: a slow start, an hour and a quarter with nothing tracked, a short
          afternoon, what's left in the evening, and when Time Doctor can't be read.
        </div>
      </section>

      <div className="form-actions">
        {error && <span className="error">{error}</span>}
        {saved && !dirty && <span className="saved">Saved</span>}
        {dirty && <span className="unsaved">Unsaved</span>}
        <button className="btn btn-quiet" type="button" disabled={!dirty || busy} onClick={() => { setP(prefs); setError(null); }}>Reset</button>
        <button className="btn btn-primary" type="button" disabled={!dirty || busy} onClick={save}>Save</button>
      </div>

      <section className="instrument form">
        <div className="label">Upload a worklog</div>
        <div className="field-note">
          For when the server can't sign in to Time Doctor: Reports, Worklog, export as CSV, and upload it here.
          Days in the file replace what's stored.
        </div>
        <label className="btn btn-add">
          Choose CSV
          <input type="file" accept=".csv,text/csv" hidden onChange={(e) => { sendCsv(e.target.files?.[0]); e.target.value = ""; }} />
        </label>
        {upload && <div className="field-note">{upload}</div>}
      </section>

      <form method="post" action="/auth/logout">
        <button className="btn btn-quiet" type="submit">Sign out</button>
      </form>
    </>
  );
}
