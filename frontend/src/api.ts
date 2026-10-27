import type { Prefs, Summary, TimeDoctorLogin } from "./types";

export class ApiError extends Error {}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...init,
    credentials: "same-origin",
    // The server's CSRF guard on writes (web.py); harmless on reads.
    headers: { "X-Pace": "1", ...(init.headers || {}) },
  });
  if (res.status === 401) {
    location.href = "/auth/login";
    throw new ApiError("Signing in");
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const d = body?.detail;
    const msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((e) => e.msg).join("; ") : `HTTP ${res.status}`;
    throw new ApiError(msg);
  }
  return body as T;
}

export const api = {
  summary: (month?: string) => call<Summary>(`/api/summary${month ? `?month=${month}` : ""}`),
  savePrefs: (p: Prefs) =>
    call<Summary>("/api/prefs", { method: "PUT", body: JSON.stringify(p), headers: { "Content-Type": "application/json" } }),
  fetchNow: () => call<{ requested: boolean }>("/api/fetch", { method: "POST" }),
  setTimeDoctor: (email: string, password: string) =>
    call<{ timedoctor: TimeDoctorLogin }>("/api/timedoctor", {
      method: "PUT", body: JSON.stringify({ email, password }), headers: { "Content-Type": "application/json" },
    }),
  removeTimeDoctor: () => call<{ timedoctor: TimeDoctorLogin }>("/api/timedoctor", { method: "DELETE" }),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return call<{ days: number; from: string; to: string }>("/api/upload", { method: "POST", body: form });
  },
};
