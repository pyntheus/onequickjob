/** Formatting helpers, ported from the prototype so the copy matches it exactly. */

/** Integer pence to pounds as the prototype's fmt(): £30, £25.50, £1,742. */
export function fmt(pence: number): string {
  const v = Math.round(Math.abs(pence)) / 100;
  const s = v.toLocaleString("en-GB", {
    minimumFractionDigits: Number.isInteger(v) ? 0 : 2,
    maximumFractionDigits: 2,
  });
  return (pence < 0 ? "−£" : "£") + s;
}

/** "38 minutes" under 90 minutes, otherwise half hours: "1½ hours", "8½ hours". */
export function fmtDuration(mins: number): string {
  if (mins < 90) return `${Math.round(mins)} minutes`;
  const h = Math.round((mins / 60) * 2) / 2;
  return `${Math.floor(h)}${h % 1 ? "½" : ""} hours`;
}

/** 0.15 -> "15%". */
export function pct(n: number): string {
  return Math.round(n * 100) + "%";
}

export function initialsOf(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .map((w) => w[0] || "")
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export function firstName(s: string | null | undefined): string {
  return (s || "").trim().split(/\s+/)[0] ?? "";
}

/** +447700900123 -> 07700 900123. Leaves anything else alone. */
export function ukPhone(phone: string | null | undefined): string {
  if (!phone) return "";
  if (!phone.startsWith("+44")) return phone;
  const national = "0" + phone.slice(3);
  return national.length === 11 && national.startsWith("07") ? `${national.slice(0, 5)} ${national.slice(5)}` : national;
}

const LONDON = "Europe/London";

/** "Tuesday 29 September" in London time. */
export function dayText(iso: string | Date): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  return d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", timeZone: LONDON });
}

/** "10:30" in London time. */
export function timeText(iso: string | Date): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  return d.toLocaleTimeString("en-GB", { hour: "numeric", minute: "2-digit", timeZone: LONDON });
}

/** "just now", "4 min ago", "1 hr ago", "3 days ago". */
export function relativeTime(iso: string | Date, now: Date = new Date()): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  const s = Math.max(0, Math.round((now.getTime() - d.getTime()) / 1000));
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} hr ago`;
  const days = Math.round(h / 24);
  return `${days} ${days === 1 ? "day" : "days"} ago`;
}
