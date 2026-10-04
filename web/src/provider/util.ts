/** Small helpers for the provider screens (no components here, so fast refresh stays happy). */
import type { CSSProperties } from "react";
import { ApiError } from "../api/client";

/** The prototype's stack gap: style={css(12)} sets --g. */
export const css = (g: number | string): CSSProperties => ({ "--g": typeof g === "number" ? `${g}px` : g }) as CSSProperties;

/** A friendly error from the API, or a fallback. */
export function errorText(e: unknown, fallback = "Something went wrong. Please try again."): string {
  return e instanceof ApiError ? e.message : fallback;
}

export function periodWord(period: string): string {
  return period === "week" ? "weekly" : "monthly";
}

/** "Tuesday 13 October" for a London calendar date the API sends as YYYY-MM-DD. */
export function dateText(iso: string, opts: Intl.DateTimeFormatOptions = { weekday: "long", day: "numeric", month: "long" }): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d, 12)).toLocaleDateString("en-GB", { ...opts, timeZone: "UTC" });
}

/** Today's London date as YYYY-MM-DD. */
export function londonToday(now: Date = new Date()): string {
  return now.toLocaleDateString("en-CA", { timeZone: "Europe/London" });
}

/** If url is on our own site, the in-app path to open instead (works on a tunnelled lane too). */
export function appPath(url: string, publicBase: string): string | null {
  const base = publicBase.replace(/\/+$/, "");
  if (!base || !url.startsWith(base)) return null;
  const rest = url.slice(base.length);
  return rest.startsWith("/") ? rest : null;
}

/** The timer: 38:05, or 1:02:05 past the hour. */
export function clock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

/** "12.50", "£12.5", "1,200" typed by a person -> integer pence, or null if it isn't an amount. */
export function parsePounds(text: string): number | null {
  const m = /^(\d{1,6})(?:\.(\d{1,2}))?$/.exec(text.replace(/[£,\s]/g, ""));
  if (!m) return null;
  return Number(m[1]) * 100 + Number((m[2] ?? "").padEnd(2, "0"));
}
