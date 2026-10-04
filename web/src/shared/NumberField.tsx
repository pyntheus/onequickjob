import type { ReactNode } from "react";

type NumberFieldProps = {
  /** The input's id: the caller's visible <label htmlFor> names it. */
  id: string;
  /** Names the −1 and +1 buttons ("Minutes taken: +1"); the visible label is the caller's. */
  label: string;
  /** The text as typed; the caller decides what's valid. */
  value: string;
  onChange: (value: string) => void;
  /** −1 and +1 stay inside these. */
  min?: number;
  max?: number;
  /** Decimals allowed (two places at most): no −1 and +1 buttons. */
  decimals?: boolean;
  /** Shown after the number: "min", "m", "ft". */
  unit?: ReactNode;
  invalid?: boolean;
  describedBy?: string;
};

const DECIMAL = /^\d{0,4}([.]\d{0,2})?$/;

/** Clean up what was typed: digits only (whole numbers, no longer than max), or a decimal with
 * at most two places (a comma counts as the point). Returns null to keep the old value. */
function cleanNumber(raw: string, decimals: boolean, max?: number): string | null {
  if (decimals) {
    const v = raw.replace(",", ".").replace(/[^\d.]/g, "");
    return DECIMAL.test(v) ? v : null;
  }
  const v = raw.replace(/\D/g, "");
  return max !== undefined ? v.slice(0, String(max).length) : v;
}

/**
 * A number you can type, with −1 and +1 buttons beside it (whole numbers), or a decimal with
 * its unit. Inputmode brings up the number pad on phones. Every button is at least 44px.
 */
export function NumberField({ id, label, value, onChange, min = 0, max, decimals = false, unit, invalid, describedBy }: NumberFieldProps) {
  const input = (
    <input
      id={id}
      className={decimals ? undefined : "stepper-input"}
      type="text"
      inputMode={decimals ? "decimal" : "numeric"}
      pattern={decimals ? undefined : "[0-9]*"}
      autoComplete="off"
      value={value}
      aria-invalid={invalid || undefined}
      aria-describedby={describedBy}
      onChange={(e) => {
        const v = cleanNumber(e.target.value, decimals, max);
        if (v !== null) onChange(v);
      }}
    />
  );
  if (decimals) {
    return (
      <div className={"input input-suffix" + (invalid ? " invalid" : "")}>
        {input}
        {unit && <span aria-hidden="true">{unit}</span>}
      </div>
    );
  }
  const n = Number.parseInt(value, 10);
  const step = (by: number) => {
    const from = Number.isNaN(n) ? (by > 0 ? min - by : min) : n;
    const next = Math.max(min, max === undefined ? from + by : Math.min(max, from + by));
    onChange(String(next));
  };
  return (
    <div className={"stepper stepper-typed" + (invalid ? " invalid" : "")}>
      <button type="button" aria-label={`${label}: −1`} disabled={!Number.isNaN(n) && n <= min} onClick={() => step(-1)}>
        −1
      </button>
      {input}
      {unit && (
        <span className="stepper-unit" aria-hidden="true">
          {unit}
        </span>
      )}
      <button type="button" aria-label={`${label}: +1`} disabled={max !== undefined && !Number.isNaN(n) && n >= max} onClick={() => step(1)}>
        +1
      </button>
    </div>
  );
}
