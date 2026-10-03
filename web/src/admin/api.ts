/** Admin data: TanStack Query hooks over the typed client, and the mutations admin screens use. */
import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { api, call, type Schemas } from "../api/client";

export type Overview = Schemas["Overview"];
export type UnfilledRequest = Schemas["UnfilledRequest"];
export type ProviderRow = Schemas["ProviderRow"];
export type ProviderDetail = Schemas["ProviderDetail"];
export type AdminDocument = Schemas["AdminDocument"];
export type Calibration = Schemas["Calibration"];
export type Suggestion = Schemas["Suggestion"];
export type PricingVersionSummary = Schemas["PricingVersionSummary"];
export type DisputeView = Schemas["DisputeView"];
export type CategoryAdminRow = Schemas["CategoryAdminRow"];
export type CategoryRecord = Schemas["CategoryRecord"];
export type OutboxItem = Schemas["OutboxItem"];
export type AuditEntry = Schemas["AuditEntry"];
export type ProviderFilter = "all" | "attention" | "signup";

export const adminKeys = {
  all: ["admin"] as const,
  overview: ["admin", "overview"] as const,
  providers: (filter: ProviderFilter) => ["admin", "providers", filter] as const,
  provider: (id: string) => ["admin", "provider", id] as const,
  calibration: ["admin", "calibration"] as const,
  versions: ["admin", "versions"] as const,
  disputes: ["admin", "disputes"] as const,
  categories: ["admin", "categories"] as const,
  category: (id: string) => ["admin", "category", id] as const,
  outbox: (q: OutboxQuery) => ["admin", "outbox", q] as const,
  audit: ["admin", "audit"] as const,
};

export function useOverview() {
  return useQuery({ queryKey: adminKeys.overview, queryFn: () => call(api.GET("/api/admin/overview")), refetchInterval: 30_000 });
}

export function useProviders(filter: ProviderFilter) {
  return useQuery({
    queryKey: adminKeys.providers(filter),
    queryFn: () => call(api.GET("/api/admin/providers", { params: { query: { filter } } })),
  });
}

export function useProvider(id: string) {
  return useQuery({
    queryKey: adminKeys.provider(id),
    queryFn: () => call(api.GET("/api/admin/providers/{provider_id}", { params: { path: { provider_id: id } } })),
  });
}

export function useCalibration() {
  return useQuery({ queryKey: adminKeys.calibration, queryFn: () => call(api.GET("/api/admin/pricing/calibration")) });
}

export function useVersions() {
  return useQuery({ queryKey: adminKeys.versions, queryFn: () => call(api.GET("/api/admin/pricing/versions")) });
}

export function useDisputes() {
  return useQuery({ queryKey: adminKeys.disputes, queryFn: () => call(api.GET("/api/admin/disputes")) });
}

export function useAdminCategories() {
  return useQuery({ queryKey: adminKeys.categories, queryFn: () => call(api.GET("/api/admin/categories")) });
}

export function useCategoryRecord(id: string) {
  return useQuery({
    queryKey: adminKeys.category(id),
    queryFn: () => call(api.GET("/api/admin/categories/{category_id}", { params: { path: { category_id: id } } })),
    enabled: !!id,
  });
}

export type OutboxQuery = { q?: string; channel?: "sms" | "whatsapp" | "email"; template_id?: string; before?: string };

export function useOutboxPage(query: OutboxQuery) {
  return useQuery({
    queryKey: adminKeys.outbox(query),
    queryFn: () =>
      call(
        api.GET("/api/admin/outbox", {
          params: { query: { ...query, q: query.q || undefined, template_id: query.template_id || undefined, limit: 50 } },
        }),
      ),
    placeholderData: (prev) => prev,
  });
}

export function useAudit(limit = 30) {
  return useQuery({
    queryKey: [...adminKeys.audit, limit],
    queryFn: () => call(api.GET("/api/admin/audit", { params: { query: { limit } } })),
  });
}

/** A mutation that refreshes the given admin queries (default: everything admin) when it succeeds. */
export function useAdminAction<TArgs, TResult>(fn: (args: TArgs) => Promise<TResult>, refresh: QueryKey[] = [adminKeys.all]) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: async () => {
      await Promise.all(refresh.map((queryKey) => qc.invalidateQueries({ queryKey })));
    },
  });
}

export function hmrcExportUrl(year: number): string {
  return `/api/admin/hmrc-export.csv?year=${year}`;
}
