import { Check } from "lucide-react";
import type { CSSProperties } from "react";
import { Chip } from "../../shared/Chip";
import { Choice } from "../../shared/Choice";
import { Stepper } from "../../shared/Stepper";
import type { IntakeField as Field } from "../api";
import { PhotoPicker } from "./PhotoPicker";

type Props = {
  field: Field;
  value: unknown;
  onChange: (v: unknown) => void;
  /** Photo fields hold files in memory until the request is sent. */
  files?: File[];
  onFiles?: (files: File[]) => void;
};

/**
 * One intake question, rendered from the category's schema (choice, chips, multi, number,
 * counts, text, photos), as the prototype's IntakeField. Nothing here knows any category.
 */
export function IntakeField({ field, value, onChange, files = [], onFiles }: Props) {
  const id = `f-${field.key}`;
  const unit = (v: number) => (v === 1 && field.unit1 ? field.unit1 : field.unit ?? "");
  const list = Array.isArray(value) ? (value as string[]) : [];
  return (
    <div className="field" role="group" aria-labelledby={id}>
      <span className="label" id={id}>
        {field.label}
      </span>
      {field.hint && <span className="hint">{field.hint}</span>}
      {field.type === "choice" && (
        <div className="stack" style={{ "--g": "8px" } as CSSProperties}>
          {(field.options ?? []).map((o) => (
            <Choice key={o.value} on={value === o.value} onClick={() => onChange(o.value)} label={o.label} hint={o.hint} />
          ))}
        </div>
      )}
      {field.type === "chips" && (
        <div className="chips">
          {(field.options ?? []).map((o) => (
            <Chip key={o.value} on={value === o.value} onClick={() => onChange(o.value)}>
              {o.label}
            </Chip>
          ))}
        </div>
      )}
      {field.type === "multi" && (
        <div className="chips">
          {(field.options ?? []).map((o) => {
            const on = list.includes(o.value);
            return (
              <Chip key={o.value} on={on} onClick={() => onChange(on ? list.filter((v) => v !== o.value) : [...list, o.value])}>
                {on && <Check size={15} strokeWidth={3} aria-hidden="true" />}
                {o.label}
              </Chip>
            );
          })}
        </div>
      )}
      {field.type === "number" && (
        <Stepper
          value={Number(value ?? field.min ?? 0)}
          onChange={onChange}
          min={field.min ?? 0}
          max={field.max ?? 99}
          step={field.step ?? 1}
          label={field.label}
          format={(v) => `${v} ${unit(v)}`.trim()}
        />
      )}
      {field.type === "counts" && (
        <div className="card flat" style={{ padding: "2px 16px" }}>
          {(field.items ?? []).map((it) => {
            const counts = (value as Record<string, number>) ?? {};
            return (
              <div key={it.key} className="list-row">
                <div className="grow stack" style={{ "--g": "0px" } as CSSProperties}>
                  <b>{it.label}</b>
                  {it.hint && <span className="xs muted">{it.hint}</span>}
                </div>
                <Stepper
                  compact
                  value={counts[it.key] || 0}
                  onChange={(n) => onChange({ ...counts, [it.key]: n })}
                  min={0}
                  max={10}
                  label={it.label}
                />
              </div>
            );
          })}
        </div>
      )}
      {field.type === "text" && (
        <textarea
          className="input"
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.placeholder ?? undefined}
          aria-labelledby={id}
          maxLength={1000}
        />
      )}
      {field.type === "photos" && <PhotoPicker files={files} onChange={(f) => onFiles?.(f)} max={field.max_photos ?? 4} />}
    </div>
  );
}
