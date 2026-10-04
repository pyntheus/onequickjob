import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";

type Handler = (url: URL, request: Request) => unknown | Response | Promise<unknown | Response>;

/** Mock fetch by path: { "GET /api/config": () => ({...}) }. Unmatched paths return 404. */
export function mockApi(routes: Record<string, Handler>) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(String(input), init);
    const url = new URL(request.url);
    const handler = routes[`${request.method} ${url.pathname}`];
    if (!handler) {
      return new Response(JSON.stringify({ detail: { code: "not_found", message: "Not mocked" } }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      });
    }
    const result = await handler(url, request);
    if (result instanceof Response) return result;
    return new Response(JSON.stringify(result), { status: 200, headers: { "Content-Type": "application/json" } });
  });
}

export function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export const unauthorised = () => jsonResponse(403, { detail: { code: "not_signed_in", message: "Please sign in." } });

export function config(demo: boolean) {
  return {
    brand: "OneQuickJob",
    demo_mode: demo,
    public_base_url: "https://dev.onequickjob.co.uk",
    timezone: "Europe/London",
    fees: { standard_percent: 15, own_customer_percent: 5, own_customer_min_pence: 100 },
    payments: { gateway: "fake", publishable_key: null },
    address_lookup: "fake",
    area_estimator: "manual_bands_v0",
  };
}

/** Render inside a fresh QueryClient and a memory router at `path`. */
export function renderWithProviders(ui: ReactNode, { path = "/" }: { path?: string } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter([{ path: "*", element: ui }], { initialEntries: [path] });
  return { qc, ...render(<QueryClientProvider client={qc}><RouterProvider router={router} /></QueryClientProvider>) };
}
