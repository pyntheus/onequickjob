import { Minus, Plus } from "lucide-react";
import type { ReactNode } from "react";

type StepperProps = {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  format?: (v: number) => ReactNode;
  label: string;
  compact?: boolean;
};

export function Stepper({ value, onChange, min = 0, max = 999, step = 1, format = (v) => v, label, compact }: StepperProps) {
  return (
    <div className={"stepper" + (compact ? " sm" : "")} role="group" aria-label={label}>
      <button type="button" aria-label={`Less: ${label}`} disabled={value <= min} onClick={() => onChange(Math.max(min, value - step))}>
        <Minus size={compact ? 17 : 20} aria-hidden="true" />
      </button>
      <div className="stepper-val" aria-live="polite">
        {format(value)}
      </div>
      <button type="button" aria-label={`More: ${label}`} disabled={value >= max} onClick={() => onChange(Math.min(max, value + step))}>
        <Plus size={compact ? 17 : 20} aria-hidden="true" />
      </button>
    </div>
  );
}
