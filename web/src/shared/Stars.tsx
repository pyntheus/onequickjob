import { Star } from "lucide-react";

/** Read-only stars (role img), or a radio group when onChange is given. */
export function Stars({ value = 0, onChange, size = 16 }: { value?: number; onChange?: (n: number) => void; size?: number }) {
  const rounded = Math.round(value);
  if (onChange) {
    return (
      <span className="stars" role="radiogroup" aria-label="Rating">
        {[1, 2, 3, 4, 5].map((n) => {
          const on = n <= rounded;
          return (
            <button
              key={n}
              type="button"
              role="radio"
              aria-checked={n === value}
              aria-label={`${n} star${n > 1 ? "s" : ""}`}
              className={"star-btn" + (on ? " on" : "")}
              onClick={() => onChange(n)}
            >
              <Star size={size} fill={on ? "currentColor" : "none"} strokeWidth={1.8} aria-hidden="true" />
            </button>
          );
        })}
      </span>
    );
  }
  return (
    <span className="stars" role="img" aria-label={`${value} out of 5`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <span key={n} className={"star" + (n <= rounded ? " on" : "")}>
          <Star size={size} fill={n <= rounded ? "currentColor" : "none"} strokeWidth={1.8} aria-hidden="true" />
        </span>
      ))}
    </span>
  );
}
