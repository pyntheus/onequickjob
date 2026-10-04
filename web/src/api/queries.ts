/** Shared TanStack Query hooks. Lanes add their own hooks in their own directories. */
import { useQuery, type QueryClient } from "@tanstack/react-query";
import { ApiError, api, call, type Schemas } from "./client";

export type Me = Schemas["Me"];
export type PublicConfig = Schemas["PublicConfig"];
export type Catalogue = Schemas["Catalogue"];

export const queryKeys = {
  config: ["config"] as const,
  me: ["me"] as const,
  categories: ["categories"] as const,
  demoUsers: ["demo", "users"] as const,
  demoOutbox: ["demo", "outbox"] as const,
};

export function useConfig() {
  return useQuery({
    queryKey: queryKeys.config,
    queryFn: () => call(api.GET("/api/config")),
    staleTime: Infinity,
  });
}

/** Record who has just signed in (a code, a job-alert link). A fetch of /api/auth/me already in
 * flight went out with the old session, or none, and would overwrite this when it lands, so it's
 * cancelled first (its answer is dropped). */
export async function setSignedIn(qc: QueryClient, me: Me): Promise<void> {
  await qc.cancelQueries({ queryKey: queryKeys.me });
  qc.setQueryData(queryKeys.me, me);
}

/** The signed-in user, or null when signed out (401). */
export function useMe() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: async (): Promise<Me | null> => {
      try {
        return await call(api.GET("/api/auth/me"));
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    retry: false,
    staleTime: 30_000,
  });
}

export function useCategories() {
  return useQuery({
    queryKey: queryKeys.categories,
    queryFn: () => call(api.GET("/api/categories")),
    staleTime: 5 * 60_000,
  });
}

export function hasRole(me: Me | null | undefined, role: "customer" | "provider" | "admin"): boolean {
  return !!me && me.roles.includes(role);
}
