import { useId, type InputHTMLAttributes, type ReactNode } from "react";

type TextFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "className"> & {
  label: ReactNode;
  optional?: boolean;
  hint?: ReactNode;
  error?: string | null;
};

/** A labelled .input with optional hint and error, wired up for screen readers. */
export function TextField({ label, optional, hint, error, id, ...rest }: TextFieldProps) {
  const auto = useId();
  const inputId = id ?? auto;
  const hintId = hint ? `${inputId}-hint` : undefined;
  const errId = error ? `${inputId}-err` : undefined;
  return (
    <div className="field">
      <label className="label" htmlFor={inputId}>
        {label}
        {optional && (
          <span className="muted" style={{ fontWeight: 400 }}>
            {" "}
            (optional)
          </span>
        )}
      </label>
      {hint && (
        <span className="hint" id={hintId}>
          {hint}
        </span>
      )}
      <input
        id={inputId}
        className="input"
        aria-invalid={error ? true : undefined}
        aria-describedby={[hintId, errId].filter(Boolean).join(" ") || undefined}
        {...rest}
      />
      {error && (
        <span className="field-error" id={errId} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
