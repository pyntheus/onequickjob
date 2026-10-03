import { Check } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

export function Choice({ on, onClick, label, hint }: { on: boolean; onClick: () => void; label: ReactNode; hint?: ReactNode }) {
  return (
    <button type="button" className={"choice" + (on ? " on" : "")} onClick={onClick} aria-pressed={on}>
      <span className="tick">{on && <Check size={14} strokeWidth={3} aria-hidden="true" />}</span>
      <span className="stack" style={{ "--g": "2px" } as CSSProperties}>
        <span style={{ fontWeight: 600 }}>{label}</span>
        {hint && <span className="small muted">{hint}</span>}
      </span>
    </button>
  );
}
