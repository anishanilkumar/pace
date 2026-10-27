import { DayChart } from "../components/DayChart";
import { Ticks } from "../components/Ticks";
import { ageMin, clock, monthName, rupees, span, stamp } from "../format";
import type { FetchState, NudgeItem, Plan, Prefs } from "../types";

/** Hours older than this are shown as stale: dimmed, with their age. */
export const STALE_MIN = 60;

export function Dashboard({ plan, prefs, fetch, nudges, month, onMonth, onOpenSettings }: {
  plan: Plan;
  prefs: Prefs;
  fetch: FetchState;
  nudges: NudgeItem[];
  month: string;
  onMonth: (by: number) => void;
  onOpenSettings: () => void;
}) {
  const current = plan.today !== null;
  const stale = current && ageMin(fetch.last_good_at) > STALE_MIN;
  return (
    <div className={stale ? "is-stale" : ""} style={{ display: "contents" }}>
      {stale && <StaleNote fetch={fetch} onOpenSettings={onOpenSettings} />}
      {current && <Today plan={plan} prefs={prefs} />}
      <Verdict plan={plan} prefs={prefs} />
      <Month plan={plan} month={month} onMonth={onMonth} />
      {nudges.length > 0 && current && <Nudges nudges={nudges} />}
    </div>
  );
}

function StaleNote({ fetch, onOpenSettings }: { fetch: FetchState; onOpenSettings: () => void }) {
  const since = fetch.last_good_at ? `since ${stamp(fetch.last_good_at)}` : "yet";
  return (
    <section className="verdict verdict-stale arrive">
      <div className="verdict-head">Time Doctor not read {since}</div>
      <div className="verdict-detail">
        {fetch.last_error ? `${fetch.last_error} ` : "The hours below may be behind. "}
        If it keeps failing, upload a worklog CSV in{" "}
        <a href="#settings" onClick={(e) => { e.preventDefault(); onOpenSettings(); }}>settings</a>.
      </div>
    </section>
  );
}

function Today({ plan, prefs }: { plan: Plan; prefs: Prefs }) {
  if (!plan.today_working) {
    return (
      <section className="instrument today">
        <div className="label">Today</div>
        <div className="today-figures">
          <span className="hero">{clock(plan.today_hours)}</span>
          <span className="unit">h tracked</span>
        </div>
        <div className="today-left">Day off. Anything tracked still counts toward the month.</div>
      </section>
    );
  }
  // One tick per quarter hour of today's quota, at most a 12-hour day of them.
  const total = Math.min(48, Math.max(1, Math.ceil(plan.today_quota * 4)));
  const lit = Math.floor(plan.today_hours * 4);
  return (
    <section className="instrument today">
      <div className="label">Today</div>
      <div className="today-figures">
        <span className="hero">{clock(plan.today_hours)}</span>
        <span className="today-of">of {clock(plan.today_quota)}</span>
        <span className="unit">h</span>
      </div>
      <Ticks total={total} lit={Math.min(lit, total)} over={Math.max(0, Math.min(lit - total, 16))} />
      <div className="today-left">
        {plan.today_left > 0 ? (
          <><strong>{span(plan.today_left)}</strong> left. The window closes at {prefs.day_end}.</>
        ) : (
          <><strong>Today's quota is done.</strong> More now eases the days ahead.</>
        )}
      </div>
    </section>
  );
}

function Verdict({ plan, prefs }: { plan: Plan; prefs: Prefs }) {
  const name = monthName(plan.month);
  let head: string;
  let detail: string;
  if (plan.today === null) {
    const short = plan.target_hours - plan.worked_hours;
    head = plan.status === "done" ? `${name}: target reached` : `${name}: ${span(short)} short`;
    detail = `${span(plan.worked_hours)} tracked of ${span(plan.target_hours)}, ${rupees(plan.worked_net)} after TDS.`;
  } else if (plan.status === "done") {
    head = `${name}'s target reached`;
    detail = `${span(plan.worked_hours - plan.target_hours)} over. ${rupees(plan.worked_net)} after TDS.`;
  } else if (plan.status === "out_of_reach") {
    head = "Target out of reach";
    detail = plan.working_days_left
      ? `It needs ${span(plan.today_quota)} a day for ${plan.working_days_left} days, over your ${span(prefs.max_hours_per_day)} limit. Lower the target or add working days.`
      : "No working days are left this month.";
  } else if (plan.status === "behind") {
    head = `${span(-plan.diff_hours)} behind plan`;
    detail = `Catching up means ${span(plan.today_quota)} a day for the ${plan.working_days_left} working days left, today included.`;
  } else {
    head = plan.diff_hours >= 0.25 ? `${span(plan.diff_hours)} ahead of plan` : "On pace";
    detail = `The even plan is ${span(plan.plan_per_day)} a working day; ${plan.working_days_left} working days left.`;
  }
  return (
    <section className={`verdict verdict-${plan.status}`}>
      <div className="verdict-head">{head}</div>
      <div className="verdict-detail">{detail}</div>
    </section>
  );
}

function Month({ plan, month, onMonth }: { plan: Plan; month: string; onMonth: (by: number) => void }) {
  const N = 40;
  const per = plan.target_hours / N;
  const lit = per > 0 ? Math.min(N, Math.floor(plan.worked_hours / per)) : 0;
  const expectedTicks = per > 0 ? Math.min(N, Math.floor(plan.expected_hours / per)) : 0;
  return (
    <section className="instrument month">
      <div className="month-head">
        <div className="label">{monthName(month)} {month.slice(0, 4)}</div>
        <div className="month-nav">
          <button className="pill" onClick={() => onMonth(-1)} aria-label="Previous month">‹ Prev</button>
          {plan.today === null && <button className="pill" onClick={() => onMonth(1)} aria-label="Next month">Next ›</button>}
        </div>
      </div>
      <div className="month-money">
        <span className="readout">{rupees(plan.worked_net)}</span>
        <span className="unit">of {rupees(plan.target_net)} after TDS</span>
      </div>
      <Ticks className="ticks-month" total={N} lit={lit} warn={Math.max(0, expectedTicks - lit)} />
      <div className="facts">
        <Fact label="Hours" value={`${clock(plan.worked_hours)} / ${clock(plan.target_hours)}`} />
        <Fact
          label="Projected"
          value={plan.projected_net === null ? "Too early" : rupees(plan.projected_net)}
          estimated={plan.projected_net !== null}
        />
        <Fact label="Streak" value={`${plan.streak} ${plan.streak === 1 ? "day" : "days"}`} />
        <Fact label="Net an hour" value={rupees(plan.net_per_hour)} />
        <Fact label="Gross" value={rupees(plan.worked_gross)} />
        <Fact label="TDS" value={rupees(plan.tds)} />
        <Fact label="Working days" value={`${plan.working_days}`} />
        <Fact label="Plan a day" value={span(plan.plan_per_day)} />
      </div>
      <DayChart days={plan.days} plan={plan.plan_per_day} today={plan.today} />
      <div className="legend stamp">
        <span><i style={{ background: "var(--arc)" }} />Met plan</span>
        <span><i style={{ background: "var(--arc-dim)" }} />Short</span>
        <span><i style={{ background: "var(--slate)" }} />Day off</span>
        <span><i style={{ background: "var(--gold)", height: 2 }} />Plan</span>
      </div>
    </section>
  );
}

function Fact({ label, value, estimated = false }: { label: string; value: string; estimated?: boolean }) {
  return (
    <div className="fact">
      <span className="stamp">{label.toUpperCase()}</span>
      <span className={`fact-value${estimated ? " estimated" : ""}`}>{value}</span>
    </div>
  );
}

function Nudges({ nudges }: { nudges: NudgeItem[] }) {
  return (
    <section className="instrument">
      <div className="section-head"><div className="label">Recent nudges</div></div>
      <ul className="list">
        {nudges.map((n) => (
          <li key={n.id}>
            <span className={`list-dot list-dot-${n.level}`} />
            <div className="list-body">
              <div className="list-title">{n.title}</div>
              <div className="list-detail">{n.body}</div>
            </div>
            <span className="stamp">{stamp(n.created_at)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
