/** Pieces shared by the admin screens: the prototype's AdminHeader and KPI tiles, query states and a dialog. */
import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { errorText, gap } from "./util";

export function AdminHeader({ title, sub, right }: { title: string; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="row between wrap top" style={gap("12px")}>
      <div className="stack" style={gap("4px")}>
        <h1 className="h1">{title}</h1>
        {sub && <span className="muted">{sub}</span>}
      </div>
      {right}
    </div>
  );
}

export function Kpis({ items }: { items: { label: string; value: string; sub: string }[] }) {
  return (
    <div className="kpis">
      {items.map((k) => (
        <div key={k.label} className="card flat kpi">
          <span className="small muted">{k.label}</span>
          <div className="v">{k.value}</div>
          <span className="xs muted">{k.sub}</span>
        </div>
      ))}
    </div>
  );
}

/** Loading and error states for a query, so pages render their header straight away. */
export function QueryState({ isLoading, error, children }: { isLoading: boolean; error: unknown; children: ReactNode }) {
  if (isLoading) {
    return (
      <p className="page-loading" role="status">
        Loading…
      </p>
    );
  }
  if (error) {
    return (
      <div className="soft small" role="alert">
        {errorText(error)}
      </div>
    );
  }
  return <>{children}</>;
}

export function FormError({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <span className="field-error" role="alert">
      {errorText(error)}
    </span>
  );
}

/**
 * A modal dialog: focus moves into it and back to whatever opened it, Escape closes it.
 * (Not <dialog>, so it behaves the same in every browser and in tests.)
 */
export function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const id = useId();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const first = box.current?.querySelector<HTMLElement>("input, textarea, select, button:not(.dialog-x)");
    (first ?? box.current)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
  }, [onClose]);
  return (
    <div className="dialog-backdrop">
      <div ref={box} className="dialog card stack" role="dialog" aria-modal="true" aria-labelledby={id} tabIndex={-1} style={gap("14px")}>
        <div className="row between top">
          <h2 id={id} className="h3">
            {title}
          </h2>
          <button type="button" className="icon-btn dialog-x" aria-label="Close" onClick={onClose}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function TextArea({
  label,
  value,
  onChange,
  hint,
  required,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint?: string;
  required?: boolean;
}) {
  const id = useId();
  return (
    <div className="field">
      <label className="label" htmlFor={id}>
        {label}
      </label>
      {hint && <span className="hint">{hint}</span>}
      <textarea id={id} className="input" value={value} required={required} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}
