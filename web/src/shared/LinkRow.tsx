import { ChevronRight, type LucideIcon } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { Link } from "react-router";

type LinkRowProps = { icon: LucideIcon; title: ReactNode; sub?: ReactNode } & ({ to: string; onClick?: undefined } | { onClick: () => void; to?: undefined });

export function LinkRow({ icon: I, title, sub, to, onClick }: LinkRowProps) {
  const inner = (
    <>
      <span className="cat-ico sm" aria-hidden="true">
        <I size={17} />
      </span>
      <span className="grow stack" style={{ "--g": "0px" } as CSSProperties}>
        <b>{title}</b>
        {sub && <span className="xs muted">{sub}</span>}
      </span>
      <ChevronRight size={18} aria-hidden="true" />
    </>
  );
  return to !== undefined ? (
    <Link to={to} className="link-row">
      {inner}
    </Link>
  ) : (
    <button type="button" className="link-row" onClick={onClick}>
      {inner}
    </button>
  );
}
