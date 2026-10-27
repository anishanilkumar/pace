// The shapes /api/summary returns (backend web.py, plan.py).

export type Status = "on_pace" | "behind" | "out_of_reach" | "done";

export interface Day {
  date: string;
  hours: number;
  working: boolean;
  leave: boolean;
  future: boolean;
}

export interface Plan {
  month: string;
  today: string | null;
  net_per_hour: number;
  target_net: number;
  target_hours: number;
  worked_hours: number;
  worked_net: number;
  worked_gross: number;
  tds: number;
  expected_hours: number;
  diff_hours: number;
  diff_before_today: number;
  status: Status;
  plan_per_day: number;
  today_hours: number;
  today_quota: number;
  today_left: number;
  today_working: boolean;
  per_day_after_today: number;
  working_days: number;
  working_days_left: number;
  projected_hours: number | null;
  projected_net: number | null;
  streak: number;
  days: Day[];
}

export interface Prefs {
  hourly_rate_usd: number;
  usd_inr: number;
  tds_pct: number;
  target_net_inr: number;
  work_days: number[];
  max_hours_per_day: number;
  leaves: string[];
  tz: string;
  nudges: boolean;
  nudge_from: string;
  nudge_until: string;
  meeting_pattern: string;
}

export interface FetchState {
  last_at: string | null;
  last_ok: boolean | null;
  last_error: string | null;
  last_good_at: string | null;
  last_good_source: "browser" | "upload" | null;
  failures: number;
  requested: boolean;
}

export interface NudgeItem {
  id: number;
  key: string;
  level: "info" | "warn" | "alert";
  title: string;
  body: string;
  created_at: string;
}

/** One month of /api/summary's history; money at today's rate (plan.history). */
export interface HistoryMonth {
  month: string;
  hours: number;
  net: number;
  target_hours: number;
  working_days: number;
  days_tracked: number;
  meeting_hours: number;
  meeting_share: number | null;
  current: boolean;
}

/** Meetings and productive work for the month shown (plan.work_split). */
export interface Work {
  meeting_hours: number;
  productive_hours: number;
  meeting_share: number | null;
  meeting_by_day: Record<string, number>;
  tasks: { task: string; project: string; hours: number; meeting: boolean }[];
  /** False until the worker has read task time at all. */
  tasks_known: boolean;
}

export interface Summary {
  plan: Plan;
  work: Work;
  history: HistoryMonth[];
  prefs: Prefs;
  fetch: FetchState;
  nudges: NudgeItem[];
  now: string;
}
