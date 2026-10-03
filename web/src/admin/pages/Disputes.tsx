/** Disputes (the prototype's AdminDisputes): stages, messages to both parties, a proposed fix,
 * and closing, with any refund paid by the provider through the payment gateway. Owned by L3. */
import { Info, MessageCircle } from "lucide-react";
import { useState } from "react";
import { api, call } from "../../api/client";
import { CatIcon } from "../../shared/CatIcon";
import { TextField } from "../../shared/Field";
import { fmt } from "../../shared/format";
import { useToast } from "../../shared/toast-context";
import { useAdminAction, useDisputes, type DisputeView } from "../api";
import { AdminHeader, Dialog, FormError, QueryState, TextArea } from "../components";
import { errorText, gap, poundsToPence } from "../util";

type Mode = "message" | "return_visit" | "partial_refund" | "close";

function MessageDialog({ d, onClose }: { d: DisputeView; onClose: () => void }) {
  const notify = useToast();
  const [to, setTo] = useState<"both" | "customer" | "provider">("both");
  const [body, setBody] = useState("");
  const send = useAdminAction(() =>
    call(api.POST("/api/admin/disputes/{ref}/message", { params: { path: { ref: d.ref } }, body: { to, body: body.trim() } })),
  );
  const who = { both: "Both", customer: d.customer_name, provider: d.provider_short };
  return (
    <Dialog title={`Message about ${d.ref}`} onClose={onClose}>
      <div className="chips" role="radiogroup" aria-label="Send to">
        {(["both", "customer", "provider"] as const).map((k) => (
          <button key={k} type="button" role="radio" aria-checked={to === k} className={"chip" + (to === k ? " on" : "")} onClick={() => setTo(k)}>
            {who[k]}
          </button>
        ))}
      </div>
      <TextArea label="Message" value={body} onChange={setBody} hint="It goes in the dispute thread and by text." required />
      <FormError error={send.error} />
      <button
        type="button"
        className="btn btn-primary"
        disabled={send.isPending || !body.trim()}
        onClick={async () => {
          try {
            await send.mutateAsync(undefined);
            notify(to === "both" ? "Message sent to both" : `Message sent to ${who[to]}`);
            onClose();
          } catch {
            // shown in the dialog
          }
        }}
      >
        Send
      </button>
    </Dialog>
  );
}

function ProposeDialog({ d, kind, onClose }: { d: DisputeView; kind: "return_visit" | "partial_refund"; onClose: () => void }) {
  const notify = useToast();
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const pence = poundsToPence(amount);
  const propose = useAdminAction(() =>
    call(
      api.POST("/api/admin/disputes/{ref}/propose", {
        params: { path: { ref: d.ref } },
        body: { kind, amount_pence: kind === "partial_refund" ? pence : null, note: note.trim() },
      }),
    ),
  );
  return (
    <Dialog title={kind === "return_visit" ? "Propose a return visit" : "Propose a partial refund"} onClose={onClose}>
      <p className="small muted">
        {kind === "return_visit"
          ? `${d.provider_first} goes back to put it right, free. Both are told.`
          : `Paid by ${d.provider_first}: our fee comes back in proportion and the rest from their earnings. Up to ${fmt(d.refundable_pence)}.`}
      </p>
      {kind === "partial_refund" && (
        <TextField label="Refund (£)" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
      )}
      <TextArea label="Note (optional)" value={note} onChange={setNote} />
      <FormError error={propose.error} />
      <button
        type="button"
        className="btn btn-primary"
        disabled={propose.isPending || (kind === "partial_refund" && !pence)}
        onClick={async () => {
          try {
            await propose.mutateAsync(undefined);
            notify(kind === "return_visit" ? "Proposed: the provider returns to fix it, free" : "Proposed: a partial refund, paid by the provider");
            onClose();
          } catch {
            // shown in the dialog
          }
        }}
      >
        Propose
      </button>
    </Dialog>
  );
}

type Outcome = "return_visit" | "partial_refund" | "full_refund" | "none";

function CloseDialog({ d, onClose }: { d: DisputeView; onClose: () => void }) {
  const notify = useToast();
  const proposed = d.proposed?.kind as Outcome | undefined;
  const [outcome, setOutcome] = useState<Outcome>(proposed ?? "none");
  const [amount, setAmount] = useState(d.proposed?.amount_pence ? (d.proposed.amount_pence / 100).toFixed(2) : "");
  const [note, setNote] = useState("");
  const pence = poundsToPence(amount);
  const close = useAdminAction(() =>
    call(
      api.POST("/api/admin/disputes/{ref}/close", {
        params: { path: { ref: d.ref } },
        body: { outcome, amount_pence: outcome === "partial_refund" ? pence : null, note: note.trim() },
      }),
    ),
  );
  const choices: [Outcome, string][] = [
    ["return_visit", `${d.provider_first} went back and put it right`],
    ["partial_refund", "A partial refund, paid by the provider"],
    ["full_refund", `A full refund of what's left (${fmt(d.refundable_pence)}), paid by the provider`],
    ["none", "No further action"],
  ];
  const refunding = outcome === "partial_refund" || outcome === "full_refund";
  return (
    <Dialog title={`Close ${d.ref}`} onClose={onClose}>
      <div className="stack" style={gap("8px")} role="radiogroup" aria-label="Outcome">
        {choices
          .filter(([k]) => !(k.endsWith("refund") && d.refundable_pence === 0))
          .map(([k, label]) => (
            <button key={k} type="button" role="radio" aria-checked={outcome === k} className={"choice" + (outcome === k ? " on" : "")} onClick={() => setOutcome(k)}>
              <span className="tick" aria-hidden="true" />
              <span className="small">{label}</span>
            </button>
          ))}
      </div>
      {outcome === "partial_refund" && (
        <TextField label="Refund (£)" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} hint={`Up to ${fmt(d.refundable_pence)}`} />
      )}
      <TextArea label="Note (optional)" value={note} onChange={setNote} />
      <FormError error={close.error} />
      <button
        type="button"
        className="btn btn-primary"
        disabled={close.isPending || (outcome === "partial_refund" && !pence)}
        onClick={async () => {
          try {
            const v = await close.mutateAsync(undefined);
            notify(
              v.stage === 3
                ? refunding
                  ? `Closed. ${fmt(v.resolution?.amount_pence ?? 0)} refunded, paid by the provider.`
                  : "Closed. Both have been told."
                : "Refund asked for. The dispute closes once Stripe confirms it.",
            );
            onClose();
          } catch {
            // shown in the dialog
          }
        }}
      >
        {refunding ? "Refund and close" : "Close the dispute"}
      </button>
    </Dialog>
  );
}

function ClosingNote({ d }: { d: DisputeView }) {
  const notify = useToast();
  const check = useAdminAction(() =>
    call(
      api.POST("/api/admin/disputes/{ref}/close", {
        params: { path: { ref: d.ref } },
        body: { outcome: d.closing_outcome ?? "none", amount_pence: d.closing_amount_pence ?? null, note: "" },
      }),
    ),
  );
  return (
    <div className="soft small row between wrap" style={gap("8px")} role="status">
      <span>
        Closing with a {fmt(d.closing_amount_pence ?? 0)} refund, waiting for Stripe to confirm it. It closes by itself once it
        has.
      </span>
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        disabled={check.isPending}
        onClick={async () => {
          try {
            const v = await check.mutateAsync(undefined);
            notify(v.stage === 3 ? "Closed. Both have been told." : "Stripe hasn't confirmed it yet.");
          } catch (e) {
            notify(errorText(e));
          }
        }}
      >
        Check again
      </button>
    </div>
  );
}

function DisputeCard({ d }: { d: DisputeView }) {
  const [mode, setMode] = useState<Mode | null>(null);
  const done = d.stage === 3;
  const closing = !done && !!d.closing_outcome;
  return (
    <div className="card stack" style={{ ...gap("14px"), opacity: done ? 0.75 : 1 }}>
      <div className="row between wrap top" style={gap("10px")}>
        <div className="row top" style={gap("12px")}>
          <span className="cat-ico sm">
            <CatIcon id={d.category_id} size={17} />
          </span>
          <div className="stack" style={gap("2px")}>
            <h2 className="h3">{d.title}</h2>
            <span className="small muted">
              {d.ref}, {d.area}, opened {d.opened_text}. {d.customer_name} and {d.provider_short}, {fmt(d.amount_pence)} job.
              {d.refunded_pence > 0 && ` ${fmt(d.refunded_pence)} refunded.`}
            </span>
          </div>
        </div>
        <span className={`badge ${done ? "ok" : "warn"}`}>{d.status_text}</span>
      </div>
      <div className="stack" style={gap("6px")}>
        <div className="stage" aria-hidden="true">
          {d.stages.map((s, i) => (
            <i key={s} className={i <= d.stage ? "on" : ""} />
          ))}
        </div>
        <div className="row between xs muted">
          {d.stages.map((s, i) => (
            <span key={s} aria-current={i === d.stage ? "step" : undefined}>
              {s}
            </span>
          ))}
        </div>
      </div>
      {d.events.length > 0 && (
        <ol className="dispute-events xs muted" aria-label="What's happened">
          {d.events.slice(-3).map((e, i) => (
            <li key={i}>
              {new Date(e.at).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}: {e.text || e.kind}
            </li>
          ))}
        </ol>
      )}
      {closing && <ClosingNote d={d} />}
      {!done && !closing && (
        <div className="row wrap" style={gap("8px")}>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setMode("message")}>
            <MessageCircle size={15} aria-hidden="true" /> Message both
          </button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setMode("return_visit")}>
            Propose a return visit
          </button>
          {d.refundable_pence > 0 && (
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setMode("partial_refund")}>
              Propose a partial refund
            </button>
          )}
          <button type="button" className="btn btn-primary btn-sm" onClick={() => setMode("close")}>
            Close
          </button>
        </div>
      )}
      {mode === "message" && <MessageDialog d={d} onClose={() => setMode(null)} />}
      {(mode === "return_visit" || mode === "partial_refund") && <ProposeDialog d={d} kind={mode} onClose={() => setMode(null)} />}
      {mode === "close" && <CloseDialog d={d} onClose={() => setMode(null)} />}
    </div>
  );
}

export default function Disputes() {
  const { data, isLoading, error } = useDisputes();
  const month = new Date().toISOString().slice(0, 7);
  const open = (data ?? []).filter((d) => d.stage < 3).length;
  const closed = (data ?? []).filter((d) => d.stage === 3 && d.events.at(-1)?.at.slice(0, 7) === month).length;
  return (
    <>
      <AdminHeader title="Disputes" sub={data ? `${open} open, ${closed} closed this month` : undefined} />
      <div className="soft small row top" style={gap("10px")}>
        <Info size={18} style={{ flex: "none", marginTop: 2 }} aria-hidden="true" />
        <span>
          We mediate; we don't guarantee. The agreement is between customer and provider. Our job is to get it put right, and to
          remove providers who don't.
        </span>
      </div>
      <QueryState isLoading={isLoading} error={error}>
        <div className="stack" style={gap("14px")}>
          {data?.length === 0 && <p className="small muted">No disputes.</p>}
          {data?.map((d) => (
            <DisputeCard key={d.id} d={d} />
          ))}
        </div>
      </QueryState>
    </>
  );
}
