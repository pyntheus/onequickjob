import { useQueryClient } from "@tanstack/react-query";
import { useState, type CSSProperties } from "react";
import { useNavigate } from "react-router";
import { api, call, type Schemas } from "../../api/client";
import { Chip } from "../../shared/Chip";
import { fmt } from "../../shared/format";
import { Toggle } from "../../shared/Toggle";
import { useToast } from "../../shared/toast-context";
import { errorText, type BookingCard, type PlanOut } from "../api";
import { dateText } from "../text";

const g = (px: number) => ({ "--g": `${px}px` }) as CSSProperties;
type Frequency = NonNullable<Schemas["PlanUpdate"]["frequency"]>;
const FREQUENCIES: [Frequency, string][] = [
  ["weekly", "Weekly"],
  ["fortnightly", "Every 2 weeks"],
  ["threeweekly", "Every 3 weeks"],
  ["fourweekly", "Every 4 weeks"],
  ["monthly", "Monthly"],
];
const CHANGEABLE = new Set<string>(["weekly", "fortnightly", "threeweekly", "fourweekly", "eightweekly", "monthly", "threemonthly"]);

function PlanCard({ plan }: { plan: PlanOut }) {
  const qc = useQueryClient();
  const notify = useToast();
  const who = plan.provider.first_name;
  const [busy, setBusy] = useState(false);
  const [away, setAway] = useState({ open: !!plan.away_from, from: plan.away_from ?? "", to: plan.away_to ?? "" });
  const [changing, setChanging] = useState(false);
  const cancelled = plan.status === "cancelled";

  const patch = async (body: Schemas["PlanUpdate"], done: string) => {
    setBusy(true);
    try {
      await call(api.PATCH("/api/c/plans/{series_id}", { params: { path: { series_id: plan.series_id } }, body }));
      notify(done);
      await qc.invalidateQueries({ queryKey: ["c"] });
    } catch (e) {
      notify(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const cancel = async () => {
    if (!window.confirm(`Cancel your ${plan.category_name.toLowerCase()} plan with ${who}? There's no fee.`)) return;
    setBusy(true);
    try {
      await call(api.POST("/api/c/plans/{series_id}/cancel", { params: { path: { series_id: plan.series_id } } }));
      notify("Plan cancelled. There's no fee.");
      await qc.invalidateQueries({ queryKey: ["c"] });
    } catch (e) {
      notify(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card stack" style={g(4)}>
      <div className="row between top" style={{ paddingBottom: 10 }}>
        <div className="stack" style={g(2)}>
          <h2 className="h3">
            {plan.category_name}, {plan.frequency_label}
          </h2>
          <span className="small muted">
            with {plan.provider.short}
            {plan.next_visit_date && !cancelled ? `, next visit ${dateText(plan.next_visit_date)}` : ""}
          </span>
        </div>
        <b>
          {fmt(plan.price_pence)} {plan.unit}
        </b>
      </div>
      {cancelled ? (
        <p className="small muted">This plan is cancelled.</p>
      ) : (
        <>
          <hr />
          {plan.outside ? (
            <Toggle
              on={plan.pause_winter}
              onChange={(v) => patch({ pause_winter: v }, v ? "Paused over winter" : "Visits carry on over winter")}
              label="Pause over winter"
              hint="No visits November to February. We restart your plan in March, nothing to remember."
            />
          ) : (
            <>
              <Toggle
                on={away.open}
                onChange={(v) => {
                  setAway((a) => ({ ...a, open: v }));
                  if (!v && plan.away_from) void patch({ away_from: null, away_to: null }, "Away dates cleared");
                }}
                label="Pause while I'm away"
                hint="Tell us your dates and those visits are skipped automatically."
              />
              {away.open && (
                <div className="row wrap" style={{ ...g(10), paddingBottom: 12 }}>
                  <label className="field">
                    <span className="label small">Away from</span>
                    <input className="input" type="date" value={away.from} onChange={(e) => setAway((a) => ({ ...a, from: e.target.value }))} />
                  </label>
                  <label className="field">
                    <span className="label small">Back on</span>
                    <input className="input" type="date" value={away.to} onChange={(e) => setAway((a) => ({ ...a, to: e.target.value }))} />
                  </label>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    style={{ alignSelf: "flex-end" }}
                    disabled={busy || !away.from || !away.to}
                    onClick={() => patch({ away_from: away.from, away_to: away.to }, "Those visits are skipped")}
                  >
                    Save dates
                  </button>
                </div>
              )}
            </>
          )}
          <hr />
          <Toggle
            on={plan.cover_when_away}
            onChange={(v) => patch({ cover_when_away: v }, v ? "Cover is on" : "Cover is off")}
            label={`Cover when ${who}'s away`}
            hint={`We'll offer the visit to another checked local provider at the same price. ${who} carries on afterwards.`}
          />
          <hr />
          {changing && (
            <div className="stack" style={{ ...g(8), paddingTop: 12 }}>
              <span className="label" id={`freq-${plan.series_id}`}>
                How often?
              </span>
              <div className="chips" role="group" aria-labelledby={`freq-${plan.series_id}`}>
                {FREQUENCIES.map(([v, l]) => (
                  <Chip
                    key={v}
                    on={plan.frequency === v}
                    disabled={busy}
                    onClick={() => v !== plan.frequency && patch({ frequency: v }, `Now ${l.toLowerCase()}`).then(() => setChanging(false))}
                  >
                    {l}
                  </Chip>
                ))}
              </div>
              <p className="xs muted">
                The price per visit stays at {fmt(plan.price_pence)}. Your next visit stays as it is; we'll let {who} know.
              </p>
            </div>
          )}
          <div className="row wrap" style={{ ...g(10), paddingTop: 12 }}>
            {CHANGEABLE.has(plan.frequency) && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setChanging((c) => !c)} aria-expanded={changing}>
                Change how often
              </button>
            )}
            <button type="button" className="btn btn-link small" style={{ color: "var(--danger)" }} onClick={cancel} disabled={busy}>
              Cancel plan
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function OneOffCard({ booking }: { booking: BookingCard }) {
  const navigate = useNavigate();
  const notify = useToast();
  const [busy, setBusy] = useState(false);
  const who = booking.provider.first_name;
  const again = async () => {
    setBusy(true);
    try {
      const req = await call(
        api.POST("/api/c/bookings/{booking_id}/rebook", { params: { path: { booking_id: booking.id } }, body: { note: "" } }),
      );
      notify(`Request sent to ${who}`);
      navigate(`/requests/${req.ref}`);
    } catch (e) {
      notify(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="card stack" style={g(12)}>
      <h2 className="h3">{booking.category_name}: no regular plan</h2>
      <p className="small muted">
        This was a one-off with {booking.provider.short.replace(/\.$/, "")}. You can book {who} again at the same price (
        {fmt(booking.price_pence)}) in one tap.
      </p>
      <button type="button" className="btn btn-primary btn-sm" style={{ alignSelf: "flex-start" }} onClick={again} disabled={busy}>
        Book {who} again
      </button>
    </div>
  );
}

export function PlansTab({ plans, bookings }: { plans: PlanOut[]; bookings: BookingCard[] }) {
  const oneOffs = bookings.filter((b) => !b.recurring && b.status !== "cancelled");
  const seen = new Set<string>();
  const latestOneOffs = oneOffs.filter((b) => {
    const k = `${b.category_id}:${b.provider.provider_id}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  if (!plans.length && !latestOneOffs.length) {
    return (
      <div className="card stack" style={g(8)}>
        <h2 className="h3">No regular plan</h2>
        <p className="small muted">When you book a regular job, you can pause it, change how often or cancel it here.</p>
      </div>
    );
  }
  return (
    <div className="stack" style={g(14)}>
      {plans.map((p) => (
        <PlanCard key={p.series_id} plan={p} />
      ))}
      {latestOneOffs.map((b) => (
        <OneOffCard key={b.id} booking={b} />
      ))}
    </div>
  );
}
