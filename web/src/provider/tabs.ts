import { Bell, House, Route as RouteIcon, User, Wallet, type LucideIcon } from "lucide-react";

export type Tab = { id: "jobs" | "today" | "earnings" | "me"; label: string; icon: LucideIcon; to: string };
export const TABS: Tab[] = [
  { id: "jobs", label: "Jobs", icon: Bell, to: "/p" },
  { id: "today", label: "Today", icon: RouteIcon, to: "/p/today" },
  { id: "earnings", label: "Earnings", icon: Wallet, to: "/p/earnings" },
  { id: "me", label: "Me", icon: User, to: "/p/me" },
];

/** A helper only carries out visits (A17): no jobs list and no money. Home (/p) lists the visits
 * they've been sent to; Today is the round; Me has their name and documents. */
export const HELPER_TABS: Tab[] = [
  { id: "jobs", label: "Home", icon: House, to: "/p" },
  { id: "today", label: "Today", icon: RouteIcon, to: "/p/today" },
  { id: "me", label: "Me", icon: User, to: "/p/me" },
];

/** Which bottom-nav tab a screen belongs to (the prototype's tabOf). */
export function tabOf(pathname: string): Tab["id"] | null {
  const p = pathname.replace(/\/+$/, "") || "/p";
  if (p === "/p" || p.startsWith("/p/j/")) return "jobs";
  if (p.startsWith("/p/today") || p.startsWith("/p/visits/")) return "today";
  if (["/p/earnings", "/p/tax", "/p/limit"].some((x) => p.startsWith(x))) return "earnings";
  if (["/p/me", "/p/time-off", "/p/own-customers", "/p/messages"].some((x) => p.startsWith(x))) return "me";
  return null;
}

