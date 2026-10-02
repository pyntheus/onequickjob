import type { ReactNode } from "react";

export type BadgeTone = "ok" | "warn" | "danger" | "accent" | "plain";

export function Badge({ tone = "plain", children, title }: { tone?: BadgeTone; children: ReactNode; title?: string }) {
  return (
    <span className={"badge" + (tone !== "plain" ? ` ${tone}` : "")} title={title}>
      {children}
    </span>
  );
}
