import { MapPin } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { api, call, type Schemas } from "../../api/client";
import type { Address } from "../api";
import { errorText } from "../api";

type Suggestion = Schemas["AddressSuggestion"];

type Props = {
  value: string;
  onText: (text: string) => void;
  onResolved: (address: Address) => void;
  label?: string;
  id?: string;
};

/**
 * Address autocomplete through the API's proxy: suggestions as the customer types (free), and
 * the full address with UPRN and coordinates only once they choose one (the paid lookup).
 * A combobox with a listbox, operable by keyboard.
 */
export function AddressSearch({ value, onText, onResolved, label = "Your address", id }: Props) {
  const auto = useId();
  const inputId = id ?? `${auto}-input`;
  const listId = `${auto}-list`;
  const [items, setItems] = useState<Suggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const typed = useRef(false);
  // Closing the list on blur waits a moment (so a click on an item lands); never after unmounting.
  const closing = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(closing.current), []);

  useEffect(() => {
    const q = value.trim();
    if (!typed.current || q.length < 2) {
      setItems([]);
      return undefined;
    }
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const found = await call(api.GET("/api/address/search", { params: { query: { q } } }));
        if (!cancelled) {
          setItems(found);
          setOpen(true);
          setActive(-1);
          setError(found.length ? null : "No addresses found. Try your postcode.");
        }
      } catch (e) {
        if (!cancelled) setError(errorText(e, "We couldn't look that up just now."));
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [value]);

  const choose = async (s: Suggestion) => {
    setOpen(false);
    setItems([]);
    typed.current = false;
    onText(s.label);
    setBusy(true);
    setError(null);
    try {
      onResolved(await call(api.GET("/api/address/{suggestion_id}", { params: { path: { suggestion_id: s.id } } })));
    } catch (e) {
      setError(errorText(e, "We couldn't look that address up just now."));
    } finally {
      setBusy(false);
    }
  };

  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open || !items.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(items.length - 1, a + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(0, a - 1));
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      void choose(items[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div className="field addr">
      <label className="label" htmlFor={inputId}>
        {label}
      </label>
      <span className="input-icon">
        <MapPin size={18} aria-hidden="true" />
        <input
          id={inputId}
          className="input"
          value={value}
          placeholder="Start typing your address or postcode"
          autoComplete="off"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={open && items.length > 0}
          aria-controls={listId}
          aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
          aria-busy={busy || undefined}
          onChange={(e) => {
            typed.current = true;
            onText(e.target.value);
          }}
          onKeyDown={onKey}
          onBlur={() => {
            closing.current = setTimeout(() => setOpen(false), 150);
          }}
          onFocus={() => items.length && setOpen(true)}
        />
      </span>
      {open && items.length > 0 && (
        <ul className="addr-list" id={listId} role="listbox" aria-label="Addresses">
          {items.map((s, i) => (
            <li
              key={s.id}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "on" : undefined}
              onMouseDown={(e) => {
                e.preventDefault();
                void choose(s);
              }}
            >
              {s.label}
            </li>
          ))}
        </ul>
      )}
      {error && (
        <span className="field-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
