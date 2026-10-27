// Numbers as the instrument reads them: clock time, never decimal hours,
// and rupees grouped the Indian way (1,50,000).

/** 2.4166 -> "2:25". */
export function clock(hours: number): string {
  const m = Math.max(0, Math.round(hours * 60));
  return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`;
}

/** 2.4166 -> "2 h 25 min"; 0.75 -> "45 min". The same words as the nudges (nudges.fmt_h). */
export function span(hours: number): string {
  const m = Math.max(0, Math.round(Math.abs(hours) * 60));
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h` + (m % 60 ? ` ${String(m % 60).padStart(2, "0")} min` : "");
}

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

export function rupees(n: number): string {
  return `₹${inr.format(Math.round(n))}`;
}

export function monthName(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleString("en-GB", { month: "long" });
}

export function shiftMonth(month: string, by: number): string {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(y, m - 1 + by, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** "14:20" for today, "Mon 14:20" this week, else "27 Oct". */
export function stamp(iso: string, now: Date = new Date()): string {
  const t = new Date(iso);
  const hm = t.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  if (t.toDateString() === now.toDateString()) return hm;
  if (now.getTime() - t.getTime() < 6 * 86400_000) return `${t.toLocaleDateString("en-GB", { weekday: "short" })} ${hm}`;
  return t.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

/** Minutes since an ISO time. */
export function ageMin(iso: string | null, now: Date = new Date()): number {
  return iso ? (now.getTime() - new Date(iso).getTime()) / 60_000 : Infinity;
}
