import { useQueryClient } from "@tanstack/react-query";
import { Check, Info, PoundSterling, Send, Users, X, type LucideIcon } from "lucide-react";
import { useState, type CSSProperties } from "react";
import { useParams } from "react-router";
import { ApiError, api, call } from "../../api/client";
import { useConfig, useMe } from "../../api/queries";
import { Badge } from "../../shared/Badge";
import { Button } from "../../shared/Button";
import { fmt } from "../../shared/format";
import { SignInForm } from "../../shared/SignInForm";
import { useToast } from "../../shared/toast-context";
import { Loading, Notice } from "../../app/Status";
import { ck, errorText, useRequest, type CounterOfferView, type RequestDetail, type TimelineEvent } from "../api";
import { aboutLine, priceText } from "../text";

const g = (px: number) => ({ "--g": `${px}px` }) as CSSProperties;
const ICONS: Record<TimelineEvent["kind"], LucideIcon> = {
  sent: Send,
  viewing: Users,
  counter: PoundSterling,
  accepted: Check,
  declined: X,
  cancelled: X,
  note: Info,
};

function CounterItem({
  ev,
  offer,
  req,
  onAccept,
  onDecline,
  busy,
}: {
  ev: TimelineEvent;
  offer: CounterOfferView;
  req: RequestDetail;
  onAccept: (o: CounterOfferView) => void;
  onDecline: (o: CounterOfferView) => void;
  busy: boolean;
}) {
  // A1: both prices exactly as stored on the offer; the web never works out a first-visit price.
  const terms = priceText(offer.price_pence, req.unit, offer.first_price_pence);
  const open = req.status === "open" && offer.status === "pending";
  return (
    <div className="tl-item">
      <span className="tl-ico alert" aria-hidden="true">
        <PoundSterling size={16} />
      </span>
      <div className="grow stack" style={g(8)}>
        <span>
          <b>
            {offer.provider.short} suggested {terms}
          </b>{" "}
          <span className="muted">instead of {fmt(offer.guide_pence)}</span>
        </span>
        {offer.reason_text && <span className="small muted">"{offer.reason_text}"</span>}
        <span className="xs muted">{aboutLine(offer.provider)}</span>
        {open && (
          <div className="row wrap" style={g(8)}>
            <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => onAccept(offer)}>
              Accept {terms}
            </button>
            <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => onDecline(offer)}>
              Keep waiting
            </button>
          </div>
        )}
        {offer.status === "declined" && req.status === "open" && (
          <span className="xs muted">You're waiting for someone at the guide price.</span>
        )}
        {offer.status === "accepted" && (
          <span style={{ alignSelf: "flex-start" }}>
            <Badge tone="ok">
              <Check size={12} aria-hidden="true" /> You accepted this
            </Badge>
          </span>
        )}
        {(offer.status === "lapsed" || offer.status === "withdrawn") && ev.offer?.status !== "pending" && (
          <span className="xs muted">This price is no longer on offer.</span>
        )}
      </div>
    </div>
  );
}

function Timeline({
  req,
  onAccept,
  onDecline,
  busy,
}: {
  req: RequestDetail;
  onAccept: (o: CounterOfferView) => void;
  onDecline: (o: CounterOfferView) => void;
  busy: boolean;
}) {
  return (
    <div className="stack" style={g(14)}>
      <h2 className="h3">What's happened so far</h2>
      <ol className="tl-list" aria-label="What's happened so far">
        {req.timeline.map((ev, i) => {
          if (ev.kind === "counter" && ev.offer) {
            const live = req.pending_offers.find((o) => o.offer_id === ev.offer?.offer_id) ?? ev.offer;
            return (
              <li key={i}>
                <CounterItem ev={ev} offer={live} req={req} onAccept={onAccept} onDecline={onDecline} busy={busy} />
              </li>
            );
          }
          const Icon = ICONS[ev.kind];
          return (
            <li key={i} className="tl-item">
              <span className={"tl-ico" + (ev.kind === "accepted" ? " good" : "")} aria-hidden="true">
                <Icon size={16} />
              </span>
              <div className="grow stack" style={{ ...g(2), paddingTop: 5 }}>
                {ev.kind === "accepted" ? <b>{ev.text}</b> : <span>{ev.text}</span>}
                {ev.provider && ev.kind === "accepted" && <span className="small muted">{aboutLine(ev.provider)}</span>}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function Status({ req }: { req: RequestDetail }) {
  if (req.status === "booked" && req.booked_with) {
    const p = req.booked_with;
    return (
      <div className="card stack" style={g(16)} aria-live="polite">
        <div className="row" style={g(14)}>
          <span className="success-mark sm" aria-hidden="true">
            <Check size={22} strokeWidth={3} />
          </span>
          <div className="stack" style={g(2)}>
            <h1 className="h2">You're booked with {p.short}</h1>
            <span className="small muted">
              {req.booked_via === "guide" || req.booked_via === "direct"
                ? `They accepted your guide price of ${fmt(req.booked_price_pence ?? req.guide_pence)}.`
                : `You accepted ${priceText(req.booked_price_pence ?? 0, req.unit, req.booked_first_price_pence)}.`}
            </span>
          </div>
        </div>
        <Button to={`/bookings/${req.booking_id}`} variant="cta" size="lg" block>
          See your booking
        </Button>
      </div>
    );
  }
  if (req.status === "cancelled" || req.status === "expired") {
    return (
      <Notice title={req.status === "cancelled" ? "You cancelled this request" : "This request has closed"}>
        <p className="muted">Nothing has been charged.</p>
        <Button to="/" variant="primary">
          Get a new price
        </Button>
      </Notice>
    );
  }
  return (
    <div className="card stack" style={g(10)} aria-live="polite">
      <div className="row" style={g(14)}>
        <span className="pulse" aria-hidden="true" />
        <h1 className="h2">Finding someone local</h1>
      </div>
      <p className="muted">
        {req.alerted
          ? `We've sent your ${req.category_name.toLowerCase()} request to checked providers near ${req.district}.`
          : "We're finding someone local by hand, which can take a little longer."}{" "}
        We'll text you as soon as it's booked, so you can close this page.
      </p>
      <p className="small">
        Guide price <b>{priceText(req.guide_pence, req.unit, req.first_pence)}</b>
        {req.size_text ? `, for ${req.size_text}` : ""}.
      </p>
    </div>
  );
}

/** A12: a raised guide the team suggested, waiting for the customer's approval. */
function PriceChangeCard({
  req,
  onApprove,
  onDecline,
  busy,
}: {
  req: RequestDetail;
  onApprove: () => void;
  onDecline: () => void;
  busy: boolean;
}) {
  const pc = req.price_change;
  if (!pc) return null;
  const proposed = priceText(pc.guide_pence, req.unit, pc.first_pence);
  return (
    <div className="card stack price-change" style={g(12)} aria-live="polite">
      <h2 className="h3">A higher guide price?</h2>
      <p className="small">
        Nobody has taken your job yet. To help find someone local, we suggest raising the guide price to <b>{proposed}</b>{" "}
        (it's {priceText(pc.from_guide_pence, req.unit, pc.from_first_pence)} now). Nothing changes unless you approve it.
      </p>
      <div className="row wrap" style={g(8)}>
        <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={onApprove}>
          Approve {proposed}
        </button>
        <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={onDecline}>
          Keep {fmt(pc.from_guide_pence)}
        </button>
      </div>
    </div>
  );
}

/** "Finding someone local": polls the request, shows counters and the booking. */
export default function Offers() {
  const { ref = "" } = useParams();
  const { data: me, isLoading: meLoading } = useMe();
  const { data: config } = useConfig();
  const qc = useQueryClient();
  const notify = useToast();
  const { data: req, isLoading, error, refetch } = useRequest(ref, !!me);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  if (meLoading) return <Loading />;
  if (!me) {
    return (
      <div className="c-flow">
        <SignInForm title="Sign in to see your request" intro="Use the mobile number you gave us. We'll text you a code." />
      </div>
    );
  }
  if (isLoading) return <Loading />;
  if (error || !req) {
    return (
      <div className="c-flow">
        <Notice title="We can't find that request">
          <p className="muted">{errorText(error, "It may belong to a different account.")}</p>
          <Button to="/account" variant="primary">
            Go to my account
          </Button>
        </Notice>
      </div>
    );
  }

  const act = async (fn: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    setMessage(null);
    try {
      await fn();
      if (done) notify(done);
    } catch (e) {
      // e.g. provider_unavailable: "Mike can no longer take this job. We're still finding someone local."
      setMessage(errorText(e));
      if (e instanceof ApiError && e.status === 409) notify(e.message);
    } finally {
      await qc.invalidateQueries({ queryKey: ["c"] });
      await refetch();
      setBusy(false);
    }
  };

  const accept = (o: CounterOfferView) =>
    act(() => call(api.POST("/api/c/offers/{offer_id}/accept", { params: { path: { offer_id: o.offer_id } } })));
  const decline = (o: CounterOfferView) =>
    act(
      () => call(api.POST("/api/c/offers/{offer_id}/decline", { params: { path: { offer_id: o.offer_id } } })),
      `We'll tell ${o.provider.first_name} you'd rather wait for the guide price.`,
    );
  const cancel = () => {
    if (!window.confirm("Cancel this request? Nothing has been charged.")) return;
    void act(() => call(api.POST("/api/c/requests/{ref}/cancel", { params: { path: { ref } } })), "Request cancelled");
  };
  // A12: the answer names the proposal shown, so a stale page can't approve a newer one.
  const changeId = req.price_change?.change_id ?? "";
  const approveRaise = () =>
    act(
      () =>
        call(api.POST("/api/c/requests/{ref}/price-change/approve", { params: { path: { ref } }, body: { change_id: changeId } })),
      "Done. We've sent your job to providers again at the new price.",
    );
  const declineRaise = () =>
    act(
      () =>
        call(api.POST("/api/c/requests/{ref}/price-change/decline", { params: { path: { ref } }, body: { change_id: changeId } })),
      "Your guide price stays as it is.",
    );
  const simulate = () =>
    act(async () => {
      const s = await call(api.POST("/api/c/requests/{ref}/demo/simulate", { params: { path: { ref } } }));
      notify(`${s.provider_short} will reply in a few seconds.`);
      qc.setQueryData(ck.request(ref), { ...req, simulating: true });
    });

  return (
    <div className="c-flow">
      <Status req={req} />
      {message && (
        <p className="soft small" role="alert">
          {message}
        </p>
      )}
      <PriceChangeCard req={req} onApprove={approveRaise} onDecline={declineRaise} busy={busy} />
      <Timeline req={req} onAccept={accept} onDecline={decline} busy={busy} />
      {req.status === "open" && (
        <div className="row between wrap" style={g(12)}>
          <button type="button" className="btn btn-link small" onClick={cancel} disabled={busy}>
            Cancel this request
          </button>
        </div>
      )}
      {config?.demo_mode && req.demo_simulator && (
        <div className="soft row between wrap xs" style={g(10)}>
          <span className="muted">Prototype: there are no real providers yet.</span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={simulate} disabled={busy || req.simulating}>
            {req.simulating ? "Local responses on their way…" : "Simulate local responses"}
          </button>
        </div>
      )}
    </div>
  );
}
