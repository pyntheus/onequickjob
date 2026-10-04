/**
 * Provider routes (/p), an installable PWA. Owned by L2: change routes here, never in App.tsx.
 * Job-alert links are /p/j/{ref}?t={single-use token}; the layout signs the provider in.
 * Plan-change links (/p/plan-change/{token}) need no sign-in: the token is the authority.
 */
import type { RouteObject } from "react-router";
import { page } from "../app/routing";
import type { ScreenEntry } from "../shared/screens";

export const PROVIDER_SCREENS: ScreenEntry[] = [
  { id: "sms", label: "Text-message alert (shown in the Outbox drawer)", path: "/p", lane: "L2" },
  { id: "jobs", label: "New jobs", path: "/p", lane: "L2" },
  { id: "offer", label: "Job offer", path: "/p/j/:ref", lane: "L2" },
  { id: "onjob", label: "Today's round", path: "/p/today", lane: "L2" },
  { id: "finish", label: "Finish a job", path: "/p/visits/:visitId/finish", lane: "L2" },
  { id: "earnings", label: "Earnings", path: "/p/earnings", lane: "L2" },
  { id: "tax", label: "Tax and records", path: "/p/tax", lane: "L2" },
  { id: "limit", label: "Earnings limit", path: "/p/limit", lane: "L2" },
  { id: "me", label: "Profile and documents", path: "/p/me", lane: "L2" },
  { id: "cover", label: "Time off and helpers", path: "/p/time-off", lane: "L2" },
  { id: "mycustomers", label: "Your own customers", path: "/p/own-customers", lane: "L2" },
  { id: "onboarding", label: "Sign-up", path: "/p/signup", lane: "L2" },
];

export const providerRoutes: RouteObject = {
  path: "/p",
  lazy: page(() => import("./ProviderLayout")),
  children: [
    { index: true, lazy: page(() => import("./pages/Jobs")) },
    { path: "j/:ref", lazy: page(() => import("./pages/Offer")) },
    { path: "today", lazy: page(() => import("./pages/Today")) },
    { path: "visits/:visitId/finish", lazy: page(() => import("./pages/Finish")) },
    { path: "earnings", lazy: page(() => import("./pages/Earnings")) },
    { path: "tax", lazy: page(() => import("./pages/Tax")) },
    { path: "limit", lazy: page(() => import("./pages/Limit")) },
    { path: "me", lazy: page(() => import("./pages/Me")) },
    { path: "time-off", lazy: page(() => import("./pages/TimeOff")) },
    { path: "own-customers", lazy: page(() => import("./pages/OwnCustomers")) },
    { path: "signup", lazy: page(() => import("./pages/Signup")) },
    { path: "messages", lazy: page(() => import("./pages/Messages")) },
    { path: "messages/:threadId", lazy: page(() => import("./pages/Messages")) },
    // A10: the provider's answer to a change of frequency (the link in their text; the token is the authority).
    { path: "plan-change/:token", lazy: page(() => import("./pages/PlanChange")) },
  ],
};
