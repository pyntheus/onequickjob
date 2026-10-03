import { BadgeCheck, MapPin, ShieldCheck } from "lucide-react";
import type { CSSProperties } from "react";
import { Avatar } from "../../shared/Avatar";
import { Badge } from "../../shared/Badge";
import { Stars } from "../../shared/Stars";
import type { ProviderCard } from "../api";
import { ratingText } from "../text";

const ICON = { identity: BadgeCheck, dbs: ShieldCheck, insured: ShieldCheck, distance: MapPin, rating: BadgeCheck };

export function ProviderBadges({ p }: { p: ProviderCard }) {
  return (
    <div className="row wrap" style={{ "--g": "6px" } as CSSProperties}>
      {p.badges.map((b) => {
        const I = ICON[b.kind];
        return (
          <Badge key={b.kind} tone={b.tone === "ok" ? "ok" : "plain"}>
            <I size={13} aria-hidden="true" /> {b.label}
          </Badge>
        );
      })}
    </div>
  );
}

/** Avatar, name, stars and the badges (ID checked, Basic DBS, insured until, distance). */
export function ProviderSummary({ p, size = 56 }: { p: ProviderCard; size?: number }) {
  const rated = ratingText(p);
  return (
    <div className="stack" style={{ "--g": "12px" } as CSSProperties}>
      <div className="row" style={{ "--g": "14px" } as CSSProperties}>
        <Avatar initials={p.initials} size={size} />
        <div className="grow stack" style={{ "--g": "4px" } as CSSProperties}>
          <h2 className="h3">{p.short}</h2>
          {rated ? (
            <span className="row small muted" style={{ "--g": "6px" } as CSSProperties}>
              <Stars value={p.rating_avg ?? 0} size={14} /> {rated}
            </span>
          ) : (
            <span className="small muted">New to OneQuickJob</span>
          )}
        </div>
      </div>
      <ProviderBadges p={p} />
    </div>
  );
}
