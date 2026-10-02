import type { ReactNode } from "react";

export function Chip({ on, onClick, children, disabled }: { on?: boolean; onClick?: () => void; children: ReactNode; disabled?: boolean }) {
  return (
    <button type="button" className={"chip" + (on ? " on" : "")} onClick={onClick} aria-pressed={!!on} disabled={disabled}>
      {children}
    </button>
  );
}
