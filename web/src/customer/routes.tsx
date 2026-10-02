/**
 * Customer routes (/). Owned by L1: add or change routes here, never in App.tsx.
 * Outbox links already point at /requests/{ref}, /bookings/{id}, /account and /invite/{token}.
 */
import type { RouteObject } from "react-router";
import { page } from "../app/routing";
import type { ScreenEntry } from "../shared/screens";

export const CUSTOMER_SCREENS: ScreenEntry[] = [
  { id: "landing", label: "Home and quote", path: "/", lane: "L1" },
  { id: "measure", label: "Lawn measurement", path: "/quote/:categoryId/size", lane: "L1" },
  { id: "details", label: "Job questions", path: "/quote/:categoryId/details", lane: "L1" },
  { id: "price", label: "Guide price", path: "/quote/:categoryId/price", lane: "L1" },
  { id: "contact", label: "Contact and card", path: "/quote/:categoryId/contact", lane: "L1" },
  { id: "offers", label: "Waiting for providers", path: "/requests/:ref", lane: "L1" },
  { id: "booked", label: "Booking confirmed", path: "/bookings/:bookingId", lane: "L1" },
  { id: "account", label: "My account", path: "/account", lane: "L1" },
  { id: "rate", label: "Rate a visit", path: "/account/visits/:visitId/rate", lane: "L1" },
  { id: "invite", label: "Invite from a provider", path: "/invite/:token", lane: "L1" },
];

export const customerRoutes: RouteObject = {
  path: "/",
  lazy: page(() => import("./CustomerLayout")),
  children: [
    { index: true, lazy: page(() => import("./pages/Landing")) },
    { path: "quote/:categoryId/size", lazy: page(() => import("./pages/Measure")) },
    { path: "quote/:categoryId/details", lazy: page(() => import("./pages/Details")) },
    { path: "quote/:categoryId/price", lazy: page(() => import("./pages/Price")) },
    { path: "quote/:categoryId/contact", lazy: page(() => import("./pages/Contact")) },
    { path: "requests/:ref", lazy: page(() => import("./pages/Offers")) },
    { path: "bookings/:bookingId", lazy: page(() => import("./pages/Booked")) },
    { path: "account", lazy: page(() => import("./pages/Account")) },
    { path: "account/visits/:visitId/rate", lazy: page(() => import("./pages/Rate")) },
    { path: "invite/:token", lazy: page(() => import("./pages/Invite")) },
  ],
};
