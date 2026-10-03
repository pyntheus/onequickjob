import type { CSSProperties, ReactNode } from "react";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p className="page-loading" role="status">
      {label}
    </p>
  );
}

export function Notice({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="card stack" style={{ "--g": "10px" } as CSSProperties}>
      <h1 className="h2">{title}</h1>
      {children}
    </div>
  );
}
