import { tabId } from "./tab-id";

export type TabItem<T extends string> = { id: T; label: string };

/** The prototype's .tabs (role tablist); the caller renders the panel. With `panelId`, each tab
 * names the panel it controls (and the panel can name its tab with tabId). */
export function Tabs<T extends string>({
  items,
  value,
  onChange,
  label,
  panelId,
}: {
  items: TabItem<T>[];
  value: T;
  onChange: (v: T) => void;
  label: string;
  panelId?: string;
}) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {items.map((t) => (
        <button
          key={t.id}
          id={panelId ? tabId(panelId, t.id) : undefined}
          type="button"
          role="tab"
          aria-selected={value === t.id}
          aria-controls={panelId}
          className={value === t.id ? "on" : ""}
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
