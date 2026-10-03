/**
 * Typed API client generated from the FastAPI OpenAPI schema (make types).
 *
 *   const me = await call(api.GET("/api/auth/me"));
 *
 * Same origin only (Vite proxies /api in development, Caddy in production), with the
 * session cookie sent on every request.
 */
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type { paths };

export const api = createClient<paths>({
  // Absolute same-origin URL: identical in the browser, and lets tests run under jsdom.
  baseUrl: typeof window !== "undefined" ? window.location.origin : "",
  credentials: "include",
  headers: { Accept: "application/json" },
  // Look fetch up on each call (not once at import) so tests can mock it.
  fetch: (request: Request) => globalThis.fetch(request),
});

type ErrorBody = { detail?: { code?: string; message?: string; extra?: Record<string, unknown> } | unknown };

/** An API error with the server's code (e.g. "already_taken") and a message safe to show. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly extra: Record<string, unknown> | undefined;

  constructor(status: number, code: string, message: string, extra?: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.extra = extra;
  }
}

const FALLBACK = "Something went wrong. Please try again.";

export function toApiError(status: number, body: unknown): ApiError {
  const detail = (body as ErrorBody | undefined)?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const d = detail as { code?: string; message?: string; extra?: Record<string, unknown> };
    return new ApiError(status, d.code ?? `http_${status}`, d.message ?? FALLBACK, d.extra);
  }
  if (status === 422) return new ApiError(status, "invalid", "Please check the details and try again.");
  return new ApiError(status, `http_${status}`, FALLBACK);
}

/** Unwrap an openapi-fetch result: return data, or throw ApiError. */
export async function call<T>(
  promise: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await promise;
  if (error !== undefined || !response.ok) throw toApiError(response.status, error);
  return data as T;
}
