import type { CSSProperties } from "react";
import { Link } from "react-router";
import { fmt, fmtDuration } from "../../shared/format";
import { Stars } from "../../shared/Stars";
import type { CustomerVisit } from "../api";
import { dateText } from "../text";

const g = (px: number) => ({ "--g": `${px}px` }) as CSSProperties;

function DateChip({ iso }: { iso: string }) {
  return (
    <div className="date-chip" aria-hidden="true">
      <span>{dateText(iso, { weekday: "short" })}</span>
      <b>{dateText(iso, { day: "numeric" })}</b>
    </div>
  );
}

function doneLine(v: CustomerVisit): string {
  if (v.status === "skipped") return "Skipped";
  const parts: string[] = [];
  if (v.minutes_actual) parts.push(`Took ${fmtDuration(v.minutes_actual)}`);
  if (v.after_photo_url) parts.push("after photo added");
  if (v.rating_stars) parts.push(`rated ${v.rating_stars} ${v.rating_stars === 1 ? "star" : "stars"}`);
  if (v.dispute_ref) parts.push(`problem reported (${v.dispute_ref})`);
  const s = parts.join(", ");
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : "Done";
}

export function VisitsTab({ upcoming, done }: { upcoming: CustomerVisit[]; done: CustomerVisit[] }) {
  return (
    <div className="stack" style={g(18)}>
      {upcoming.length ? (
        <div className="card flat" style={{ padding: "4px 18px" }}>
          {upcoming.map((v) => (
            <div key={v.id} className="list-row">
              <DateChip iso={v.local_date} />
              <div className="grow stack" style={g(0)}>
                <b>
                  {v.category_name}, {dateText(v.local_date, { day: "numeric", month: "long" })}
                </b>
                <span className="small muted">
                  {v.provider_short}, {v.label}
                </span>
              </div>
              <span className="small">{fmt(v.price_pence)}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="small muted">Nothing booked at the moment.</p>
      )}
      <h2 className="h3">Done</h2>
      {done.length ? (
        <div className="card flat" style={{ padding: "4px 18px" }}>
          {done.map((v) => (
            <div key={v.id} className="list-row">
              {v.after_photo_url ? (
                <img className="thumb" src={v.after_photo_url} alt={`After photo, ${dateText(v.local_date)}`} />
              ) : (
                <span className="thumb" aria-hidden="true" />
              )}
              <div className="grow stack" style={g(0)}>
                <b>{dateText(v.local_date)}</b>
                <span className="small muted">
                  {v.category_name} with {v.provider_short}. {doneLine(v)}
                </span>
              </div>
              {v.can_rate ? (
                <Link className="btn btn-primary btn-sm" to={`/account/visits/${v.id}/rate`}>
                  Rate
                </Link>
              ) : v.rating_stars ? (
                <Stars value={v.rating_stars} size={14} />
              ) : v.can_report ? (
                <Link className="btn btn-ghost btn-sm" to={`/account/visits/${v.id}/rate?problem=1`}>
                  Report a problem
                </Link>
              ) : null}
            </div>
          ))}
        </div>
      ) : (
        <p className="small muted">Your finished visits will show here, with their photos.</p>
      )}
    </div>
  );
}
