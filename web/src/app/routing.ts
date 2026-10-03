import type { ComponentType } from "react";

/** Route `lazy` helper: load a page module and use its default export as the component. */
export function page(load: () => Promise<{ default: ComponentType }>) {
  return async () => ({ Component: (await load()).default });
}

/** Only follow same-site relative paths from ?next= (no //host or schemes). */
export function safeNext(next: string | null | undefined): string | null {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return null;
  return next;
}
