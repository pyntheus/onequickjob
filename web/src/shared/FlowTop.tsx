import { ArrowLeft } from "lucide-react";
import type { CSSProperties } from "react";

/** Back button plus "Step 2 of 4" progress, as in the quote flow. */
export function FlowTop({ steps, current, onBack }: { steps: string[]; current: string; onBack: () => void }) {
  const i = Math.max(0, steps.indexOf(current));
  return (
    <div className="flow-top">
      <button type="button" className="icon-btn" onClick={onBack} aria-label="Back">
        <ArrowLeft size={20} aria-hidden="true" />
      </button>
      <div className="grow stack" style={{ "--g": "6px" } as CSSProperties}>
        <span className="xs muted">
          Step {i + 1} of {steps.length}
        </span>
        <div className="progress" aria-hidden="true">
          <i style={{ width: `${((i + 1) / steps.length) * 100}%` }} />
        </div>
      </div>
    </div>
  );
}
