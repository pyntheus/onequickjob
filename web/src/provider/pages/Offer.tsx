/** Job offer: approximate area, fits-your-round, facts, the guide price and what they'd keep,
 * accept at guide (first wins) or suggest a different price. Owned by L2.
 * Lifted from the prototype's OfferDetail and ApproxMap. Opening a job-alert link signs the
 * provider in with its single-use token (the layout does it). */
import { Check, Clock, Info, PiggyBank, Route as RouteIcon, Users } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { api, call } from "../../api/client";
import { Loading } from "../../app/Status";
import { Avatar } from "../../shared/Avatar";
import { Button } from "../../shared/Button";
import { CatIcon } from "../../shared/CatIcon";
import { Chip } from "../../shared/Chip";
import { fmt } from "../../shared/format";
import { Stepper } from "../../shared/Stepper";
import { useToast } from "../../shared/toast-context";
import { useCounterPreview, useInvalidateProvider, useLimit, useOffer, useProviderMutation, type JobOffer } from "../api";
import { ApproxMap, BackLink, ErrorNote, Note } from "../components";
import { css, dateText, periodWord } from "../util";

function CounterPanel({ o, customer, onSent }: { o: JobOffer; customer: string; onSent: () => void }) {
  const [pounds, setPounds] = useState(Math.round(o.counter_start_pence / 100));
  const [reasons, setReasons] = useState<string[]>([]);
  const price = pounds * 100;
  const preview = useCounterPreview(o.card.request_ref, price, true);
  const send = useProviderMutation({
    mutationFn: () =>
      call(
        api.POST("/api/p/requests/{ref}/counter", {
          params: { path: { ref: o.card.request_ref } },
          body: { price_pence: price, reasons, message: "" },
        }),
      ),
    onSuccess: onSent,
  });
  const p = preview.data;
  const current = p && p.price_pence === price ? p : undefined;
  const toggle = (r: string) => setReasons((x) => (x.includes(r) ? x.filter((y) => y !== r) : [...x, r]));
  return (
    <div className="card flat stack" style={css(14)}>
      <span className="label" id="your-price">
        Your price{o.first_pence ? " a visit" : ""}
      </span>
      <div className="row wrap between" style={css(12)}>
        <Stepper
          value={pounds}
          onChange={setPounds}
          min={Math.round(o.counter_min_pence / 100)}
          max={Math.round(o.counter_max_pence / 100)}
          step={1}
          format={(v) => fmt(v * 100)}
          label="Your price"
        />
        <div className="stack" style={{ ...css(0), textAlign: "right" }} aria-live="polite">
          <span className="xs muted">You'd get</span>
          <b>{current ? fmt(current.provider_pence) : "…"}</b>
        </div>
      </div>
      {current && (
        <p className="small" aria-live="polite">
          <b>{current.text}</b>
          {current.first_provider_pence !== null && <> You'd get {fmt(current.first_provider_pence)} for the first visit.</>}
        </p>
      )}
      {o.first_pence !== null && (
        <p className="xs muted">You set the price for each visit. The first visit goes up by the same share as the guide's.</p>
      )}
      {current && !current.valid && <p className="small note-warn soft">{current.problem}</p>}
      <span className="label">
        Why?{" "}
        <span className="muted" style={{ fontWeight: 400 }}>
          It helps {customer} say yes.
        </span>
      </span>
      <div className="chips">
        {o.counter_reasons.map((r) => (
          <Chip key={r} on={reasons.includes(r)} onClick={() => toggle(r)}>
            {r}
          </Chip>
        ))}
      </div>
      <ErrorNote error={send.error} />
      <Button
        variant="primary"
        size="lg"
        block
        disabled={!current?.valid || send.isPending}
        onClick={() => send.mutate()}
      >
        Send {fmt(price)} to {customer}
      </Button>
      <p className="xs muted">
        {customer} approves it before anything is booked. If someone accepts the guide price first, the job goes to them.
      </p>
    </div>
  );
}

export default function Offer() {
  const { ref = "" } = useParams();
  const { data: o, isLoading, error, refetch } = useOffer(ref);
  const { data: limit } = useLimit();
  const refresh = useInvalidateProvider();
  const notify = useToast();
  const [open, setOpen] = useState(false);
  const accept = useProviderMutation({
    mutationFn: () => call(api.POST("/api/p/requests/{ref}/accept", { params: { path: { ref } } })),
    onSuccess: () => void refresh(),
    onError: () => void refetch(),
  });

  if (isLoading) return <Loading />;
  if (error || !o) {
    return (
      <>
        <BackLink to="/p">All jobs</BackLink>
        <ErrorNote error={error ?? new Error()} />
      </>
    );
  }
  const card = o.card;
  const customer = o.customer.name.split(" ")[0] || "The customer";
  const yours = o.booked_by_me;
  const taken = o.request_status === "booked" && !yours;
  const closed = o.request_status === "cancelled" || o.request_status === "expired";

  return (
    <>
      <BackLink to="/p">All jobs</BackLink>
      <div className="row" style={css(14)}>
        <span className="cat-ico lg" aria-hidden="true">
          <CatIcon id={card.category_id} size={26} />
        </span>
        <div className="stack" style={css(2)}>
          <h1 className="h2">{card.category_name}</h1>
          <span className="small muted">
            {card.frequency_label}, {card.area} ({card.district})
          </span>
        </div>
      </div>
      <ApproxMap hint={card.route_hint} />
      {card.route_hint && (
        <div className="card flat row top fits-round" style={css(12)}>
          <RouteIcon size={22} aria-hidden="true" style={{ flex: "none", marginTop: 2 }} />
          <div className="stack" style={css(2)}>
            <b>Fits your round</b>
            <span className="small">{card.route_hint}</span>
          </div>
        </div>
      )}
      {o.cover_text && (
        <Note icon={<Users size={18} aria-hidden="true" />}>
          {o.cover_text}
        </Note>
      )}
      <dl className="facts">
        {o.facts.map((f) => (
          <div key={f.label}>
            <dt>{f.label}</dt>
            <dd>{f.value}</dd>
          </div>
        ))}
      </dl>
      {o.note && (
        <div className="soft small">
          <b>From {customer}:</b> “{o.note}”
        </div>
      )}
      <div className="row" style={css(12)}>
        <Avatar initials={o.customer.initials} size={42} />
        <div className="stack" style={css(0)}>
          <b>{o.customer.name}</b>
          <span className="xs muted">{o.customer.meta}</span>
        </div>
      </div>
      <div className="card">
        <div className="row between" style={{ alignItems: "flex-end" }}>
          <div className="stack" style={css(4)}>
            <span className="small muted">Guide price</span>
            <span className="big-num">{fmt(card.guide_pence)}</span>
          </div>
          <div className="stack" style={{ ...css(4), textAlign: "right" }}>
            <span className="small muted">You get</span>
            <span className="big-num" style={{ color: "var(--primary)" }}>
              {fmt(card.provider_pence)}
            </span>
          </div>
        </div>
        {o.first_pence !== null && o.first_provider_pence !== null && (
          <p className="small" style={{ marginTop: 10 }}>
            First visit {fmt(o.first_pence)}, you get {fmt(o.first_provider_pence)}.
            {o.first_reason ? ` ${o.first_reason}` : ""}
          </p>
        )}
        <p className="xs muted" style={{ marginTop: 10 }}>
          After the {o.fee_percent}% OneQuickJob fee. Paid to your bank with Friday's payout.
        </p>
      </div>

      {yours ? (
        <div className="card stack" style={css(14)}>
          <div className="row" style={css(12)}>
            <span className="success-mark sm" aria-hidden="true">
              <Check size={22} strokeWidth={3} />
            </span>
            <div className="stack" style={css(2)}>
              <h2 className="h3">It's yours</h2>
              {o.first_visit_text && <span className="small muted">{o.first_visit_text}</span>}
              {o.address_line && <span className="small">{o.address_line}</span>}
            </div>
          </div>
          {o.first_visit_date && (
            <Button to={`/p/today?date=${o.first_visit_date}`} variant="primary" size="lg" block>
              See {dateText(o.first_visit_date, { weekday: "long" })}'s round
            </Button>
          )}
        </div>
      ) : taken ? (
        <Note>Sorry, someone else took this job first.</Note>
      ) : closed ? (
        <Note>This job isn't open any more.</Note>
      ) : o.my_counter ? (
        <div className="card flat stack" style={css(8)}>
          <div className="row" style={css(10)}>
            <Clock size={20} aria-hidden="true" />
            <b>
              Waiting for {customer} to decide on {fmt(o.my_counter.price_pence)}
              {o.my_counter.first_price_pence ? ` (first visit ${fmt(o.my_counter.first_price_pence)})` : ""}
            </b>
          </div>
          <p className="small muted">We'll text you the answer. If someone accepts the guide price first, the job goes to them.</p>
        </div>
      ) : (
        <>
          {o.counter_note && <Note icon={<Info size={18} aria-hidden="true" />}>{o.counter_note}</Note>}
          {!o.can_take ? (
            <Note tone="warn">
              {o.not_eligible_reasons.join(" ")}{" "}
              {o.missing_documents.length > 0 && <Link to="/p/me">Check your documents</Link>}
            </Note>
          ) : (
            <>
              {o.over_limit_by_pence !== null && (
                <Note tone="warn" icon={<PiggyBank size={18} aria-hidden="true" />}>
                  Taking this would put you {fmt(o.over_limit_by_pence)} over your {periodWord(limit?.period ?? "week")} limit.
                  It's your choice.
                </Note>
              )}
              <ErrorNote error={accept.error} />
              <Button variant="cta" size="lg" block disabled={accept.isPending} onClick={() => accept.mutate()}>
                Accept at {fmt(card.guide_pence)}
              </Button>
              {o.can_counter && (
                <Button variant="ghost" size="lg" block aria-expanded={open} onClick={() => setOpen((v) => !v)}>
                  {open ? "Cancel" : "Suggest a different price"}
                </Button>
              )}
              {open && o.can_counter && (
                <CounterPanel
                  o={o}
                  customer={customer}
                  onSent={() => {
                    setOpen(false);
                    notify(`Sent to ${customer}. We'll text you the answer.`);
                    void refresh();
                  }}
                />
              )}
              <p className="xs muted center">The first person to accept the guide price gets the job.</p>
            </>
          )}
        </>
      )}
    </>
  );
}
