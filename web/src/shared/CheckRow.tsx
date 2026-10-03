import { Check } from "lucide-react";
import type { ReactNode } from "react";

export function CheckRow({ on, onChange, children }: { on: boolean; onChange: (v: boolean) => void; children: ReactNode }) {
  return (
    <button type="button" role="checkbox" aria-checked={on} className="checkbox-row" onClick={() => onChange(!on)}>
      <span className={"box" + (on ? " on" : "")} aria-hidden="true">
        {on && <Check size={15} strokeWidth={3} />}
      </span>
      <span className="small">{children}</span>
    </button>
  );
}
