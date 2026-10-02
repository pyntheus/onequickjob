import type { CSSProperties, ReactNode } from "react";

export function Toggle({ on, onChange, label, hint }: { on: boolean; onChange: (v: boolean) => void; label: ReactNode; hint?: ReactNode }) {
  return (
    <button type="button" role="switch" aria-checked={on} className="toggle-row" onClick={() => onChange(!on)}>
      <span className="stack grow" style={{ "--g": "2px" } as CSSProperties}>
        <span style={{ fontWeight: 600 }}>{label}</span>
        {hint && <span className="small muted">{hint}</span>}
      </span>
      <span className={"switch" + (on ? " on" : "")} aria-hidden="true">
        <i />
      </span>
    </button>
  );
}
