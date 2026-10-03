/** Customer copy built from API values (never prices or fees worked out here). */
import { fmt } from "../shared/format";
import type { ProviderCard } from "./api";

export function ratingText(p: ProviderCard): string | null {
  if (!p.rating_count || p.rating_avg == null) return null;
  return `${p.rating_avg.toFixed(1)} from ${p.rating_count} ${p.rating_count === 1 ? "job" : "jobs"}`;
}

/** "Rated 4.9 from 112 jobs, and lives 1.2 miles away" under a provider's name on the timeline. */
export function aboutLine(p: ProviderCard): string {
  const rated = ratingText(p);
  const lives = p.badges.find((b) => b.kind === "distance")?.label.toLowerCase();
  if (rated && lives) return `Rated ${rated}, and ${lives}`;
  if (rated) return `Rated ${rated}`;
  return lives ? lives.charAt(0).toUpperCase() + lives.slice(1) : "New to OneQuickJob";
}

/** "£36 a visit (first visit £66)": both prices exactly as the offer or booking stores them (A1). */
export function priceText(pence: number, unit: string, firstPence?: number | null): string {
  return `${fmt(pence)} ${unit}${firstPence ? ` (first visit ${fmt(firstPence)})` : ""}`;
}

export function possessive(name: string): string {
  return name.endsWith("s") ? `${name}'` : `${name}'s`;
}

/** A London calendar date from the API ("2026-10-13") as "Tuesday 13 October". */
export function dateText(iso: string, opts: Intl.DateTimeFormatOptions = { weekday: "long", day: "numeric", month: "long" }): string {
  return new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-GB", { ...opts, timeZone: "UTC" });
}
