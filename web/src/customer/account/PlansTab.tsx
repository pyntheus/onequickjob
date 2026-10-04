import { useQueryClient } from "@tanstack/react-query";
import { useState, type CSSProperties } from "react";
import { useNavigate } from "react-router";
import { ApiError, api, call, type Schemas } from "../../api/client";
import { Chip } from "../../shared/Chip";
import { fmt } from "../../shared/format";
import { Toggle } from "../../shared/Toggle";
import { useToast } from "../../shared/toast-context";
import { errorText, type BookingCard, type PlanOut } from "../api";
import { dateText } from "../text";

const g = (px: number) => ({ "--g": `${px}px` }) as CSSProperties;
type Frequency = NonNullable<Schemas["PlanUpdate"]["frequency"]>;
type PlanPrice = Schemas["PlanPrice"];

/**
 * A10: a new frequency is re-priced by the API (never here) and sent to the provider to accept;
 * the plan carries on unchanged until they do. A22: an own customer's plan is priced by the
 * provider, so choosing a frequency asks them for a price instead.
 */
function ChangeHowOften({ plan, onDone }: { plan: PlanOut; onDone: () => void }) {
  const qc = useQueryClient();
  const notify = useToast();
  const who = plan.provider.first_name;
  const [quote, setQuote] = useState<PlanPrice | null>(null);
  const [asking, setAsking] = useState<{ frequency: string; label: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const askForPrice = async () => {
    if (!asking) return;
    setBusy(true);
    try {
      await call(
        api.PATCH("/api/c/plans/{series_id}", {
          params: { path: { series_id: plan.series_id } },
          body: { frequency: asking.frequency as Frequency },
        }),
      );
      notify(`We've asked ${who} for a price. Your plan stays as it is until you agree one.`);
      await qc.invalidateQueries({ queryKey: ["c"] });
      onDone();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const choose = async (frequency: string) => {
    if (plan.provider_sets_price) {
      const label = plan.frequency_options?.find((o) => o.value === frequency)?.label ?? frequency;
      setAsking({ frequency, label });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setQuote(
        await call(
          api.GET("/api/c/plans/{series_id}/reprice", { params: { path: { series_id: plan.series_id }, query: { frequency } } }),
        ),
      );
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const ask = async () => {
    if (!quote) return;
    setBusy(true);
    try {
      await call(
        api.PATCH("/api/c/plans/{series_id}", {
          params: { path: { series_id: plan.series_id } },
          // The price shown: if it has changed since, nothing is sent and the new one is shown.
          body: { frequency: quote.frequency as Frequency, expected_price_pence: quote.price_pence },
        }),
      );
      notify(`We've asked ${who}. Your plan stays as it is unless they accept.`);
      await qc.invalidateQueries({ queryKey: ["c"] });
      onDone();
    } catch (e) {
      setError(errorText(e));
      const fresh = e instanceof ApiError && e.code === "price_changed" ? e.extra?.price_pence : undefined;
      if (typeof fresh === "number") setQuote({ ...quote, price_pence: fresh });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="stack" style={{ ...g(8), paddingTop: 12 }}>
      <span className="label" id={`freq-${plan.series_id}`}>
        How often?
      </span>
      <div className="chips" role="group" aria-labelledby={`freq-${plan.series_id}`}>
        {(plan.frequency_options ?? []).map((o) => (
          <Chip
            key={o.value}
            on={(quote?.frequency ?? asking?.frequency ?? plan.frequency) === o.value}
            disabled={busy || o.value === plan.frequency}
            onClick={() => choose(o.value)}
          >
            {o.label.charAt(0).toUpperCase() + o.label.slice(1)}
          </Chip>
        ))}
      </div>
      {quote && (
        <div className="soft small stack" style={g(8)}>
          <span>
            {quote.frequency_label.charAt(0).toUpperCase() + quote.frequency_label.slice(1)}, the price would be{" "}
            <b>{fmt(quote.price_pence)} a visit</b> (it's {fmt(quote.current_price_pence)} now). We'll ask {who} to accept it;
            your plan stays as it is unless they do.
          </span>
          <button type="button" className="btn btn-primary btn-sm" style={{ alignSelf: "flex-start" }} onClick={ask} disabled={busy}>
            Ask {who}
          </button>
        </div>
      )}
      {asking && (
        <div className="soft small stack" style={g(8)}>
          <span>
            {who} sets the price for your plan. We'll ask them for a price to have it {asking.label}; your plan stays as it
            is until you've agreed one.
          </span>
          <button type="button" className="btn btn-primary btn-sm" style={{ alignSelf: "flex-start" }} onClick={askForPrice} disabled={busy}>
            Ask {who} for a price
          </button>
        </div>
      )}
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

/** A22: the provider has named a price for the change; the customer approves or declines it. */
function PriceToAnswer({ plan }: { plan: PlanOut }) {
  const qc = useQueryClient();
  const notify = useToast();
  const who = plan.provider.first_name;
  const pc = plan.pending_change;
  const [busy, setBusy] = useState(false);
  if (!pc || pc.to_price_pence == null) return null;
  const answer = async (how: "approve" | "decline") => {
    setBusy(true);
    try {
      const body = { change_id: pc.change_id };
      const params = { path: { series_id: plan.series_id } };
      await call(
        how === "approve"
          ? api.POST("/api/c/plans/{series_id}/change/approve", { params, body })
          : api.POST("/api/c/plans/{series_id}/change/decline", { params, body }),
      );
      notify(how === "approve" ? `Done: ${pc.to_frequency_label} at ${fmt(pc.to_price_pence ?? 0)} a visit.` : "Your plan stays as it is.");
      await qc.invalidateQueries({ queryKey: ["c"] });
    } catch (e) {
      notify(errorText(e));
      await qc.invalidateQueries({ queryKey: ["c"] });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="soft small stack" style={{ ...g(8), marginTop: 12 }}>
      <span>
        {who} can do it {pc.to_frequency_label} at <b>{fmt(pc.to_price_pence)} a visit</b> (it's {fmt(plan.price_pence)} now).
      </span>
      {pc.split && (
        <span>
          Your agreement is still with {who}. OneQuickJob handles bookings and payments on {who}'s behalf, and {who} pays us a
          small fee of {fmt(pc.split.fee_pence)} a visit ({pc.split.rate_percent}%). It isn't added to your price.
        </span>
      )}
      <div className="row wrap" style={g(8)}>
        <button type="button" className="btn btn-primary btn-sm" onClick={() => answer("approve")} disabled={busy}>
          Agree {fmt(pc.to_price_pence)} a visit
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => answer("decline")} disabled={busy}>
          Keep it as it is
        </button>
      </div>
    </div>
  );
}

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
          {plan.pending_change?.awaiting === "customer" ? (
            <PriceToAnswer plan={plan} />
          ) : plan.pending_change?.kind === "provider_price" ? (
            <p className="soft small" style={{ marginTop: 12 }}>
              Waiting for {who}'s price to have it {plan.pending_change.to_frequency_label}. Your plan carries on as it is until
              you've agreed one.
            </p>
          ) : (
            plan.pending_change && (
              <p className="soft small" style={{ marginTop: 12 }}>
                Waiting for {who} to accept {plan.pending_change.to_frequency_label} at{" "}
                <b>{fmt(plan.pending_change.to_price_pence ?? 0)} a visit</b>. Your plan carries on as it is until then.
              </p>
            )
          )}
          {changing && <ChangeHowOften plan={plan} onDone={() => setChanging(false)} />}
          <div className="row wrap" style={{ ...g(10), paddingTop: 12 }}>
            {(plan.frequency_options ?? []).length > 1 && (
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
