/** The small panel a clicked marker opens: what it is, where, its status, age or date, and price,
 * with a link to the page that already exists for it. */
import { X } from "lucide-react";
import { useEffect } from "react";
import { Link } from "react-router";
import { fmt } from "../../shared/format";
import { shortDate } from "../util";
import type { Selected } from "./MapCanvas";

const STATUS: Record<string, string> = {
  active: "Active",
  payouts_paused: "Active, payouts paused",
  signing_up: "Signing up",
  suspended: "Suspended",
};

function plural(n: number, one: string, many = one + "s") {
  return `${n} ${n === 1 ? one : many}`;
}

export function MapPanel({ selected, onClose }: { selected: Selected; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <section className="map-panel card" aria-label="Details" aria-live="polite">
      <button type="button" className="map-panel-x" onClick={onClose} aria-label="Close details">
        <X size={18} aria-hidden="true" />
      </button>
      {selected.kind === "request" && <RequestDetails s={selected} />}
      {selected.kind === "job" && <JobDetails s={selected} />}
      {selected.kind === "provider" && <ProviderDetails s={selected} />}
    </section>
  );
}

function RequestDetails({ s }: { s: Extract<Selected, { kind: "request" }> }) {
  const p = s.pin;
  return (
    <>
      <h2 className="h3">
        {p.category_name} in {p.area}, {p.district}
      </h2>
      <dl className="map-facts">
        <dt>Status</dt>
        <dd>
          Open {p.age_text}
          {p.waiting ? ", nobody's taken it yet" : ""}
          {p.cover ? " (cover for a provider's time off)" : ""}
        </dd>
        <dt>Guide price</dt>
        <dd>{fmt(p.guide_pence)}</dd>
        <dt>Coverage</dt>
        <dd>
          {p.uncovered ? (
            <b className="map-uncovered-text">Outside every active provider's travel radius</b>
          ) : (
            `In reach of ${plural(p.in_reach, "active provider")}, ${p.in_reach_doing_it} doing this job`
          )}
        </dd>
        {p.awaiting_customer && (
          <>
            <dt>Price</dt>
            <dd>A raised guide is waiting for the customer</dd>
          </>
        )}
      </dl>
      {p.waiting ? (
        <Link className="btn btn-primary btn-sm" to={`/admin#request-${p.ref}`}>
          Open {p.ref} in dispatch
        </Link>
      ) : (
        <p className="small muted">
          Request {p.ref}. It joins the dispatch list on Overview once it has been open an hour.
        </p>
      )}
    </>
  );
}

function JobDetails({ s }: { s: Extract<Selected, { kind: "job" }> }) {
  const p = s.pin;
  const booked = s.layer === "booked";
  return (
    <>
      <h2 className="h3">
        {p.category_name} in {p.area}, {p.district}
      </h2>
      <dl className="map-facts">
        <dt>Status</dt>
        <dd>
          {booked
            ? `Booked: ${plural(p.visits, "visit")} to come, the next on ${shortDate(p.visit_date)}`
            : `Completed: ${plural(p.visits, "visit")} in the dates chosen, the latest on ${shortDate(p.visit_date)}`}
        </dd>
        <dt>Price</dt>
        <dd>
          {fmt(p.price_pence)} a visit{p.own_customer ? " (a customer the provider brought)" : ""}
        </dd>
        <dt>Provider</dt>
        <dd>{p.provider_short || "Not known"}</dd>
        <dt>Booking</dt>
        <dd>{p.booking_ref}</dd>
      </dl>
      {p.provider_short && (
        <Link className="btn btn-ghost btn-sm" to={`/admin/providers/${p.provider_id}`}>
          {p.provider_short}'s page
        </Link>
      )}
    </>
  );
}

function ProviderDetails({ s }: { s: Extract<Selected, { kind: "provider" }> }) {
  const p = s.pin;
  return (
    <>
      <h2 className="h3">{p.short}</h2>
      <dl className="map-facts">
        <dt>Status</dt>
        <dd>
          {STATUS[p.status] ?? p.status}
          {p.covers ? "" : ": their radius covers no one yet"}
        </dd>
        <dt>Home area</dt>
        <dd>
          {p.area}, {p.district}
        </dd>
        <dt>Travel radius</dt>
        <dd>{plural(p.travel_radius_miles, "mile")}</dd>
        <dt>Jobs</dt>
        <dd>{p.jobs.length ? p.jobs.join(", ") : "None chosen yet"}</dd>
      </dl>
      <p className="xs muted">
        {p.placed_at === "postcode"
          ? "Shown at the centre of their home postcode, not their address."
          : "Shown within about a kilometre of home, not at their address."}
      </p>
      <Link className="btn btn-ghost btn-sm" to={`/admin/providers/${p.provider_id}`}>
        Provider page
      </Link>
    </>
  );
}
