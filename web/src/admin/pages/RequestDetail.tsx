/** One request (decisions.md A38), opened from the map and Overview's dispatch list: what the
 * customer asked for and how it was priced, where it stands, every offer and counter, what's
 * happened, the messages about it, any raise waiting for the customer, and who could take it.
 * Its actions are Overview's: the WhatsApp text and raising the guide (A12, unchanged). */
import { ArrowLeft, Copy } from "lucide-react";
import { Fragment, useState } from "react";
import { Link, useParams } from "react-router";
import { api, call } from "../../api/client";
import { CatIcon } from "../../shared/CatIcon";
import { fmt, ukPhone } from "../../shared/format";
import { useToast } from "../../shared/toast-context";
import { useAdminAction, useRequestDetail, type RequestDetail as Detail } from "../api";
import { AdminHeader, QueryState } from "../components";
import { errorText, gap } from "../util";

const STATUS: Record<string, [string, string]> = {
  open: ["Open", "warn"],
  booked: ["Booked", "ok"],
  cancelled: ["Cancelled", ""],
  expired: ["Closed, nobody booked", ""],
};
const OFFER: Record<string, [string, string]> = {
  pending: ["Waiting on the customer", "warn"],
  accepted: ["Accepted", "ok"],
  declined: ["Declined", ""],
  lapsed: ["Lapsed", ""],
  withdrawn: ["Withdrawn", ""],
};
const CHANNEL: Record<string, string> = { sms: "Text", whatsapp: "WhatsApp", email: "Email" };

function when(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/London",
  });
}

function plural(n: number, one: string, many = one + "s") {
  return `${n} ${n === 1 ? one : many}`;
}

function Actions({ r }: { r: Detail }) {
  const notify = useToast();
  const [text, setText] = useState<string | null>(null);
  const raise = useAdminAction((ref: string) =>
    call(api.POST("/api/admin/requests/{ref}/raise-guide", { params: { path: { ref } }, body: { percent: 10, note: "" } })),
  );
  const copy = async () => {
    let message: string;
    try {
      message = (await call(api.GET("/api/admin/requests/{ref}/whatsapp", { params: { path: { ref: r.ref } } }))).text;
    } catch (e) {
      notify(errorText(e));
      return;
    }
    setText(message);
    try {
      await navigator.clipboard.writeText(message);
      notify("Copied. Paste it into the providers' WhatsApp group.");
    } catch {
      notify("Couldn't copy here. The message is shown below.");
    }
  };
  const raiseGuide = async () => {
    try {
      const updated = await raise.mutateAsync(r.ref);
      // A12: the raise waits for the customer's approval.
      notify(`Raise to ${fmt(updated.proposed_guide_pence ?? updated.guide_pence)} sent to the customer to approve. Logged for review.`);
    } catch (e) {
      notify(errorText(e));
    }
  };
  return (
    <div className="card stack" style={gap("10px")}>
      <h2 className="h3">Dispatch</h2>
      <div className="row wrap" style={gap("8px")}>
        <button type="button" className="btn btn-primary btn-sm" onClick={copy}>
          <Copy size={15} aria-hidden="true" /> Copy WhatsApp message
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={raiseGuide} disabled={raise.isPending}>
          Raise guide 10%
        </button>
      </div>
      {text && (
        <div className="soft small" aria-label={`WhatsApp message for ${r.ref}`}>
          {text}
        </div>
      )}
    </div>
  );
}

function TheRequest({ r }: { r: Detail }) {
  const a = r.address;
  return (
    <div className="card stack" style={gap("10px")}>
      <h2 className="h3">What the customer asked for</h2>
      <dl className="a-facts">
        <dt>Customer</dt>
        <dd>
          {r.customer_name}
          {r.customer_phone ? `, ${ukPhone(r.customer_phone)}` : ""}
        </dd>
        <dt>Address</dt>
        <dd>{[a.line1, a.line2, a.locality, a.town, a.postcode].filter(Boolean).join(", ")}</dd>
        <dt>When</dt>
        <dd>{r.when_text}</dd>
        <dt>How often</dt>
        <dd>{r.frequency_text}</dd>
        <dt>Guide price</dt>
        <dd>
          {fmt(r.guide_pence)} {r.unit}
          {r.first_pence ? `, first visit ${fmt(r.first_pence)}` : ""}
        </dd>
        <dt>Estimate</dt>
        <dd>
          {r.mins} minutes{r.first_mins ? `, first visit ${r.first_mins}` : ""}
        </dd>
        {r.answers.map((x) => (
          <Fragment key={x.question}>
            <dt>{x.question}</dt>
            <dd>{x.answer}</dd>
          </Fragment>
        ))}
        {r.notes && (
          <>
            <dt>Notes</dt>
            <dd>{r.notes}</dd>
          </>
        )}
        <dt>Photos</dt>
        <dd>{r.photos ? plural(r.photos, "photo") : "None"}</dd>
      </dl>
      {r.cover && <p className="small muted">Cover for one visit of a provider's time off.</p>}
      {r.direct_provider_short && <p className="small muted">"Book again": offered to {r.direct_provider_short} only.</p>}
    </div>
  );
}

function Lawn({ r }: { r: Detail }) {
  const l = r.lawn;
  if (!l) return null;
  return (
    <div className="card stack" style={gap("10px")}>
      <h2 className="h3">Lawn size</h2>
      <dl className="a-facts">
        <dt>Size</dt>
        <dd>
          {l.area_m2.toLocaleString("en-GB")} m²: {l.summary}
        </dd>
        <dt>How</dt>
        <dd>{l.method_text}</dd>
        <dt>Estimator</dt>
        <dd>
          <code>{l.estimator}</code>
          {l.confidence ? `, confidence ${l.confidence}` : ""}
        </dd>
      </dl>
      {l.lawns.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Lawn</th>
                <th>As given</th>
                <th>In metres</th>
                <th>Area</th>
              </tr>
            </thead>
            <tbody>
              {l.lawns.map((lw, i) => (
                <tr key={i}>
                  <td>{i + 1}</td>
                  <td>{lw.given}</td>
                  <td>{lw.metres}</td>
                  <td>{lw.area_m2} m²</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Offers({ r }: { r: Detail }) {
  return (
    <div className="card stack" style={gap("10px")}>
      <h2 className="h3">Offers and counters</h2>
      {r.offers.length === 0 ? (
        <p className="small muted">No provider has suggested a different price.</p>
      ) : (
        <ul className="a-msgs">
          {r.offers.map((o) => {
            const [word, tone] = OFFER[o.status] ?? [o.status, ""];
            return (
              <li key={o.id} className="a-msg">
                <div className="row between wrap" style={gap("8px")}>
                  <span>
                    <Link to={`/admin/providers/${o.provider_id}`}>{o.provider_short || "A provider"}</Link> suggested{" "}
                    <b>{fmt(o.price_pence)}</b>
                    {o.first_price_pence ? `, first visit ${fmt(o.first_price_pence)}` : ""} (guide then {fmt(o.guide_pence)})
                  </span>
                  <span className={`badge ${tone}`}>{word}</span>
                </div>
                {(o.reasons.length > 0 || o.message) && (
                  <span className="small muted">
                    {[o.reasons.join(", "), o.message].filter(Boolean).join(". ")}
                  </span>
                )}
                <span className="xs muted">
                  {when(o.created_at)}
                  {o.decided_at ? `, decided ${when(o.decided_at)}` : ""}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function Standing({ r }: { r: Detail }) {
  const c = r.coverage;
  const pc = r.price_change;
  return (
    <div className="card stack" style={gap("10px")}>
      <h2 className="h3">Where it stands</h2>
      {r.booked ? (
        <p className="small">
          Booked by <Link to={`/admin/providers/${r.booked.provider_id}`}>{r.booked.provider_short}</Link> at{" "}
          {fmt(r.booked.price_pence)}
          {r.booked.first_price_pence ? ` (first visit ${fmt(r.booked.first_price_pence)})` : ""}
          {r.booked.via === "counter" ? ", their suggested price" : ""} on {when(r.booked.at)}
          {r.booked.booking_ref ? `: booking ${r.booked.booking_ref}` : ""}.
        </p>
      ) : r.status === "open" ? (
        <p className="small">
          Open {r.age_text}
          {r.waiting ? ", nobody's taken it yet. It's on the dispatch list." : "."}
        </p>
      ) : null}
      {r.admin_note && <p className="small muted">{r.admin_note}</p>}
      {pc && (
        <div className="soft small" role="note">
          Awaiting the customer: they've been asked to approve {fmt(pc.guide_pence)}
          {pc.first_pence ? ` (first visit ${fmt(pc.first_pence)})` : ""}, up from {fmt(pc.from_guide_pence)}, since{" "}
          {when(pc.proposed_at)}.
        </div>
      )}
      <h3 className="a-subhead">Who could take it</h3>
      {c.uncovered ? (
        <p className="small">
          <b className="map-uncovered-text">No active provider in reach does {r.category_name.toLowerCase()}.</b>{" "}
          {c.in_reach
            ? `${plural(c.in_reach, "provider")} in reach ${c.in_reach === 1 ? "does" : "do"} other jobs.`
            : "Nobody active is in reach."}
        </p>
      ) : (
        <p className="small">
          In reach of {plural(c.in_reach, "active provider")}, {c.in_reach_doing_it} doing {r.category_name.toLowerCase()}.
        </p>
      )}
      {c.nearby.length > 0 && (
        <ul className="a-near">
          {c.nearby.map((n) => (
            <li key={n.provider_id}>
              <Link to={`/admin/providers/${n.provider_id}`}>{n.short}</Link>, {n.miles} miles
              {n.payouts_paused && <span className="badge warn">Payouts paused</span>}
              {n.does_it && <span className="badge ok">Does this</span>}
              <span className="xs muted"> {n.jobs.join(", ") || "No jobs chosen"}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Timeline({ r }: { r: Detail }) {
  return (
    <div className="card stack" style={gap("10px")}>
      <h2 className="h3">What's happened</h2>
      <ol className="a-timeline">
        {r.timeline.map((t, i) => (
          <li key={i}>
            <span className="xs muted">{when(t.at)}</span> {t.text}
          </li>
        ))}
      </ol>
    </div>
  );
}

function Messages({ r }: { r: Detail }) {
  return (
    <div className="card stack" style={gap("6px")}>
      <h2 className="h3">Messages</h2>
      {r.messages.length === 0 ? (
        <p className="small muted">No messages about this request.</p>
      ) : (
        <ul className="a-msgs">
          {r.messages.map((m) => (
            <li key={m.id} className="a-msg">
              <div className="a-msg-meta">
                <b>{m.recipient.name || "Someone"}</b>
                <span>{CHANNEL[m.channel] ?? m.channel}</span>
                <code>{m.template_id}</code>
                <span>{when(m.created_at)}</span>
              </div>
              <div className={"a-msg-body" + (m.channel === "email" ? " email" : "")}>
                {m.subject && <div className="subject">{m.subject}</div>}
                {m.body}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function RequestDetail() {
  const { requestId = "" } = useParams();
  const { data: r, isLoading, error } = useRequestDetail(requestId);
  const [word, tone] = r ? (STATUS[r.status] ?? [r.status, ""]) : ["", ""];
  return (
    <>
      <Link to="/admin" className="small row" style={gap("6px")}>
        <ArrowLeft size={15} aria-hidden="true" /> Overview and dispatch
      </Link>
      <QueryState isLoading={isLoading} error={error}>
        {r && (
          <>
            <AdminHeader
              title={`${r.category_name} in ${r.address.locality || r.address.town}, ${r.address.district}`}
              sub={
                <span className="row wrap" style={gap("8px")}>
                  <span className="cat-ico sm">
                    <CatIcon id={r.category_id} size={15} />
                  </span>
                  Request {r.ref}, made {when(r.created_at)} ({r.age_text} ago)
                </span>
              }
              right={<span className={`badge ${tone}`}>{word}</span>}
            />
            <div className="a-cols">
              <div className="stack" style={gap("18px")}>
                <TheRequest r={r} />
                <Lawn r={r} />
                <Offers r={r} />
                <Messages r={r} />
              </div>
              <div className="stack" style={gap("18px")}>
                {r.status === "open" && <Actions r={r} />}
                <Standing r={r} />
                <Timeline r={r} />
              </div>
            </div>
          </>
        )}
      </QueryState>
    </>
  );
}
