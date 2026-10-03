/** Admin routes (/admin). Owned by L3: change routes here, never in App.tsx. */
import type { RouteObject } from "react-router";
import { page } from "../app/routing";
import type { ScreenEntry } from "../shared/screens";

export const ADMIN_SCREENS: ScreenEntry[] = [
  { id: "overview", label: "Overview and dispatch", path: "/admin", lane: "L3" },
  { id: "providers", label: "Providers", path: "/admin/providers", lane: "L3" },
  { id: "provider", label: "Provider", path: "/admin/providers/:providerId", lane: "L3" },
  { id: "calibration", label: "Pricing and calibration", path: "/admin/pricing", lane: "L3" },
  { id: "disputes", label: "Disputes", path: "/admin/disputes", lane: "L3" },
  { id: "categories", label: "Categories", path: "/admin/categories", lane: "L3" },
  { id: "outbox", label: "Outbox", path: "/admin/outbox", lane: "L3" },
];

export const adminRoutes: RouteObject = {
  path: "/admin",
  lazy: page(() => import("./AdminLayout")),
  children: [
    { index: true, lazy: page(() => import("./pages/Overview")) },
    { path: "providers", lazy: page(() => import("./pages/Providers")) },
    { path: "providers/:providerId", lazy: page(() => import("./pages/ProviderDetail")) },
    { path: "pricing", lazy: page(() => import("./pages/Pricing")) },
    { path: "disputes", lazy: page(() => import("./pages/Disputes")) },
    { path: "categories", lazy: page(() => import("./pages/Categories")) },
    { path: "outbox", lazy: page(() => import("./pages/Outbox")) },
  ],
};
