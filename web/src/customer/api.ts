/** L1's data hooks: the customer endpoints (/api/c) through the generated client. */
import { useQuery } from "@tanstack/react-query";
import { ApiError, api, call, type Schemas } from "../api/client";

export type Address = Schemas["Address"];
export type AreaOptions = Schemas["AreaOptions"];
export type Category = Schemas["Category"];
export type IntakeField = Schemas["IntakeField"];
export type QuoteOut = Schemas["QuoteOut"];
export type RequestDetail = Schemas["RequestDetail"];
export type RequestSummary = Schemas["RequestSummary"];
export type CounterOfferView = Schemas["CounterOfferView"];
export type TimelineEvent = Schemas["TimelineEvent"];
export type ProviderCard = Schemas["ProviderCard"];
export type BookingCard = Schemas["BookingCard"];
export type BookingDetail = Schemas["BookingDetail"];
export type CustomerVisit = Schemas["CustomerVisit"];
export type PlanOut = Schemas["PlanOut"];
export type ThreadSummary = Schemas["ThreadSummary"];
export type MessageOut = Schemas["MessageOut"];
export type InvitePreview = Schemas["InvitePreview"];
export type CustomerProfile = Schemas["CustomerProfile"];
export type FeeSplit = Schemas["FeeSplit"];

export const ck = {
  areaOptions: ["c", "area-options"] as const,
  feeExample: ["c", "fee-example"] as const,
  profile: ["c", "profile"] as const,
  card: ["c", "card"] as const,
  requests: ["c", "requests"] as const,
  request: (ref: string) => ["c", "request", ref] as const,
  bookings: ["c", "bookings"] as const,
  booking: (id: string) => ["c", "booking", id] as const,
  visits: ["c", "visits"] as const,
  visit: (id: string) => ["c", "visit", id] as const,
  plans: ["c", "plans"] as const,
  threads: ["c", "threads"] as const,
  messages: (id: string) => ["c", "messages", id] as const,
  invite: (token: string) => ["c", "invite", token] as const,
};

/** A customer endpoint that answers 404 no_customer_profile before the first booking: null then. */
async function orNull<T>(p: Promise<T>): Promise<T | null> {
  try {
    return await p;
  } catch (e) {
    if (e instanceof ApiError && e.code === "no_customer_profile") return null;
    throw e;
  }
}

export function useAreaOptions() {
  return useQuery({ queryKey: ck.areaOptions, queryFn: () => call(api.GET("/api/area/options")), staleTime: Infinity });
}

export function useFeeExample() {
  return useQuery({
    queryKey: ck.feeExample,
    queryFn: () => call(api.GET("/api/c/fees/example", { params: { query: { price_pence: 3000 } } })),
    staleTime: Infinity,
  });
}

export function useProfile(enabled = true) {
  return useQuery({ queryKey: ck.profile, queryFn: () => orNull(call(api.GET("/api/c/profile"))), enabled });
}

export function useRequest(ref: string, enabled = true) {
  return useQuery({
    queryKey: ck.request(ref),
    queryFn: () => call(api.GET("/api/c/requests/{ref}", { params: { path: { ref } } })),
    enabled,
    // The "Finding someone local" screen polls while the request is open.
    refetchInterval: (q) => (q.state.data?.status === "open" ? 3000 : false),
  });
}

export function useRequests(enabled = true) {
  return useQuery({ queryKey: ck.requests, queryFn: () => orNull(call(api.GET("/api/c/requests"))), enabled });
}

export function useBooking(id: string, enabled = true) {
  return useQuery({
    queryKey: ck.booking(id),
    queryFn: () => call(api.GET("/api/c/bookings/{booking_id}", { params: { path: { booking_id: id } } })),
    enabled,
  });
}

export function useBookings(enabled = true) {
  return useQuery({ queryKey: ck.bookings, queryFn: () => orNull(call(api.GET("/api/c/bookings"))), enabled });
}

export function useVisits(enabled = true) {
  return useQuery({ queryKey: ck.visits, queryFn: () => orNull(call(api.GET("/api/c/visits"))), enabled });
}

export function useVisit(id: string, enabled = true) {
  return useQuery({
    queryKey: ck.visit(id),
    queryFn: () => call(api.GET("/api/c/visits/{visit_id}", { params: { path: { visit_id: id } } })),
    enabled,
  });
}

export function usePlans(enabled = true) {
  return useQuery({ queryKey: ck.plans, queryFn: () => orNull(call(api.GET("/api/c/plans"))), enabled });
}

export function useThreads(enabled = true) {
  return useQuery({
    queryKey: ck.threads,
    queryFn: () => orNull(call(api.GET("/api/c/threads"))),
    enabled,
    refetchInterval: 15_000,
  });
}

export function useMessages(threadId: string | null) {
  return useQuery({
    queryKey: ck.messages(threadId ?? ""),
    queryFn: () =>
      call(api.GET("/api/c/threads/{thread_id}/messages", { params: { path: { thread_id: threadId ?? "" } } })),
    enabled: !!threadId,
    refetchInterval: 10_000,
  });
}

export function useInvite(token: string) {
  return useQuery({
    queryKey: ck.invite(token),
    queryFn: () => call(api.GET("/api/c/invites/{token}", { params: { path: { token } } })),
    retry: false,
  });
}

/** The message to show for a failed call. */
export function errorText(e: unknown, fallback = "Something went wrong. Please try again."): string {
  return e instanceof ApiError ? e.message : fallback;
}
