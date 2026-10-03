/** Small helpers for the admin screens (kept apart from components for fast refresh). */
import type { CSSProperties } from "react";
import { ApiError } from "../api/client";

export const gap = (g: string) => ({ "--g": g }) as CSSProperties;

export function errorText(e: unknown): string {
  return e instanceof ApiError ? e.message : "Something went wrong. Please try again.";
}

/** Pounds typed by a person, as integer pence ("12.50" -> 1250); null if it isn't an amount. */
export function poundsToPence(text: string): number | null {
  const m = /^\s*£?\s*(\d{1,6})(?:\.(\d{1,2}))?\s*$/.exec(text);
  if (!m) return null;
  return Number(m[1]) * 100 + Number((m[2] ?? "").padEnd(2, "0"));
}

/** "2026-10-12" -> "12 Oct 2026". */
export function shortDate(iso: string): string {
  return new Date(iso + "T12:00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}
