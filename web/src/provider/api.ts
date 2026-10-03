/**
 * The provider app's data: typed TanStack Query hooks over /api/p (L2) and the shared offer
 * endpoints. Every figure the screens show comes from these: the web never works out a fee,
 * a first-visit price or what a provider keeps (decisions.md A1).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, call, toApiError, type Schemas } from "../api/client";
import { hasRole, useMe } from "../api/queries";

export type ProviderHome = Schemas["ProviderHome"];
export type JobCard = Schemas["JobCard"];
export type JobOffer = Schemas["JobOffer"];
export type CounterPreview = Schemas["CounterPreview"];
export type LimitView = Schemas["LimitView"];
export type TodayRound = Schemas["TodayRound"];
export type RoundItem = Schemas["RoundItem"];
export type ProviderVisit = Schemas["ProviderVisit"];
export type FinishIn = Schemas["FinishIn"];
export type FinishOut = Schemas["FinishOut"];
export type EarningsOut = Schemas["EarningsOut"];
export type TaxSummary = Schemas["TaxSummary"];
export type ProviderProfile = Schemas["ProviderProfile"];
export type DocumentOut = Schemas["DocumentOut"];
export type HelperOut = Schemas["HelperOut"];
export type AffectedVisit = Schemas["AffectedVisit"];
export type TimeOffOut = Schemas["TimeOffOut"];
export type OwnCustomersView = Schemas["OwnCustomersView"];
export type SignupChecklist = Schemas["SignupChecklist"];
export type ThreadSummary = Schemas["ThreadSummary"];
export type MessageOut = Schemas["MessageOut"];
export type DocType = Schemas["DocumentIn"]["type"];
export type FileKind = Schemas["Body_upload_file_api_files_post"]["kind"];

export const pKeys = {
  all: ["p"] as const,
  home: ["p", "home"] as const,
  offer: (ref: string) => ["p", "offer", ref] as const,
  counter: (ref: string, price: number) => ["p", "counter", ref, price] as const,
  today: (date: string | null) => ["p", "today", date ?? "today"] as const,
  visit: (id: string) => ["p", "visit", id] as const,
  earnings: ["p", "earnings"] as const,
  tax: (year: string | null) => ["p", "tax", year ?? "current"] as const,
  limit: ["p", "limit"] as const,
  limitPreview: (period: string, amount: number) => ["p", "limit", "preview", period, amount] as const,
  profile: ["p", "profile"] as const,
  documents: ["p", "documents"] as const,
  timeOff: ["p", "time-off"] as const,
  helpers: ["p", "helpers"] as const,
  own: ["p", "own-customers"] as const,
  ownPreview: (price: number) => ["p", "own-customers", "preview", price] as const,
  threads: ["p", "threads"] as const,
  messages: (id: string) => ["p", "messages", id] as const,
  signup: ["p", "signup"] as const,
};

/** A value that settles a moment after the last change (steppers fetch once you pause). */
export function useDebounced<T>(value: T, ms = 250): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return settled;
}

export function useHome() {
  return useQuery({ queryKey: pKeys.home, queryFn: () => call(api.GET("/api/p/home")), refetchInterval: 60_000 });
}

/** Is a helper using the app? Helpers added in the app have no provider role and no helper_of
 * (so the shared offer endpoints refuse them): the API recognises them through the provider's
 * helper list, and /api/p/home says so. */
export function useHelperMode(): { helper: boolean; known: boolean } {
  const { data: me } = useMe();
  const provider = hasRole(me, "provider") && !me?.helper_of;
  const ask = !!me && !provider && !me.helper_of;
  const home = useQuery({ queryKey: pKeys.home, queryFn: () => call(api.GET("/api/p/home")), enabled: ask, retry: false });
  if (!me) return { helper: false, known: false };
  if (me.helper_of) return { helper: true, known: true };
  if (provider) return { helper: false, known: true };
  return { helper: !!home.data?.helper, known: !home.isLoading };
}

export function useOffer(ref: string) {
  return useQuery({ queryKey: pKeys.offer(ref), queryFn: () => call(api.GET("/api/p/requests/{ref}", { params: { path: { ref } } })) });
}

/** What a suggested price means, worked out by the API (A1). */
export function useCounterPreview(ref: string, pricePence: number, enabled: boolean) {
  const price = useDebounced(pricePence);
  return useQuery({
    queryKey: pKeys.counter(ref, price),
    queryFn: () =>
      call(api.GET("/api/p/requests/{ref}/counter-preview", { params: { path: { ref }, query: { price_pence: price } } })),
    enabled,
    placeholderData: keepPreviousData,
  });
}

export function useToday(date: string | null) {
  return useQuery({
    queryKey: pKeys.today(date),
    queryFn: () => call(api.GET("/api/p/today", { params: { query: date ? { date } : {} } })),
  });
}

export function useVisit(id: string | undefined) {
  return useQuery({
    queryKey: pKeys.visit(id ?? ""),
    queryFn: () => call(api.GET("/api/p/visits/{visit_id}", { params: { path: { visit_id: id ?? "" } } })),
    enabled: !!id,
  });
}

export function useEarnings() {
  return useQuery({ queryKey: pKeys.earnings, queryFn: () => call(api.GET("/api/p/earnings")) });
}

export function useTax(year: string | null) {
  return useQuery({
    queryKey: pKeys.tax(year),
    queryFn: () => call(api.GET("/api/p/tax", { params: { query: year ? { tax_year: year } : {} } })),
    placeholderData: keepPreviousData,
  });
}

export function useLimit() {
  return useQuery({ queryKey: pKeys.limit, queryFn: () => call(api.GET("/api/p/limit")) });
}

/** The limit screen's figures for a draft limit, without saving it. */
export function useLimitPreview(period: "week" | "month", amountPence: number, enabled: boolean) {
  const amount = useDebounced(amountPence);
  return useQuery({
    queryKey: pKeys.limitPreview(period, amount),
    queryFn: () => call(api.GET("/api/p/limit/preview", { params: { query: { period, amount_pence: amount } } })),
    enabled,
    placeholderData: keepPreviousData,
  });
}

export function useProfile(enabled = true) {
  return useQuery({ queryKey: pKeys.profile, queryFn: () => call(api.GET("/api/p/profile")), enabled });
}

export function useDocuments() {
  return useQuery({ queryKey: pKeys.documents, queryFn: () => call(api.GET("/api/p/documents")) });
}

export function useTimeOff() {
  return useQuery({ queryKey: pKeys.timeOff, queryFn: () => call(api.GET("/api/p/time-off")) });
}

export function useHelpers() {
  return useQuery({ queryKey: pKeys.helpers, queryFn: () => call(api.GET("/api/p/helpers")) });
}

export function useOwnCustomers() {
  return useQuery({ queryKey: pKeys.own, queryFn: () => call(api.GET("/api/p/own-customers")) });
}

/** What a provider keeps from their own price for their own customer (money.py, via the API). */
export function useOwnPreview(pricePence: number) {
  const price = useDebounced(pricePence);
  return useQuery({
    queryKey: pKeys.ownPreview(price),
    queryFn: () => call(api.GET("/api/p/own-customers/preview", { params: { query: { price_pence: price } } })),
    placeholderData: keepPreviousData,
  });
}

export function useThreads(enabled = true) {
  return useQuery({ queryKey: pKeys.threads, queryFn: () => call(api.GET("/api/p/threads")), enabled });
}

export function useMessages(id: string) {
  return useQuery({
    queryKey: pKeys.messages(id),
    queryFn: () => call(api.GET("/api/p/threads/{thread_id}/messages", { params: { path: { thread_id: id } } })),
    refetchInterval: 15_000,
  });
}

export function useSignup(enabled = true) {
  return useQuery({ queryKey: pKeys.signup, queryFn: () => call(api.GET("/api/p/signup")), enabled });
}

/** Most changes touch several screens' figures: refetch everything the provider app shows. */
export function useInvalidateProvider() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: pKeys.all });
}

export function usePatchProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["ProfilePatch"]) => call(api.PATCH("/api/p/profile", { body })),
    onSuccess: (profile) => {
      qc.setQueryData(pKeys.profile, profile);
      void qc.invalidateQueries({ queryKey: pKeys.home });
    },
  });
}

/** Upload a photo or document to the FileStore (POST /api/files, multipart). */
export async function uploadFile(file: File, kind: FileKind, visitId?: string): Promise<Schemas["FileOut"]> {
  const form = new FormData();
  form.append("kind", kind);
  form.append("file", file);
  if (visitId) form.append("visit_id", visitId);
  const res = await globalThis.fetch(
    new Request(`${window.location.origin}/api/files`, {
      method: "POST",
      body: form,
      credentials: "include",
      headers: { Accept: "application/json" },
    }),
  );
  const body: unknown = await res.json().catch(() => undefined);
  if (!res.ok) throw toApiError(res.status, body);
  return body as Schemas["FileOut"];
}
