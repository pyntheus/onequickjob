/** A provider's page (new; opened from the Providers table): documents to verify or reject,
 * suspension, reminders, their payment account, ledger and ratings. Owned by L3. */
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { api, call, type Schemas } from "../../api/client";
import { useCategories } from "../../api/queries";
import { Avatar } from "../../shared/Avatar";
import { TextField } from "../../shared/Field";
import { fmt } from "../../shared/format";
import { Stars } from "../../shared/Stars";
import { useToast } from "../../shared/toast-context";
import { adminKeys, useAdminAction, useProvider, type AdminDocument, type ProviderDetail as Detail } from "../api";
import { AdminHeader, Dialog, FormError, QueryState, TextArea } from "../components";
import { errorText, gap, poundsToPence, shortDate } from "../util";
import { InsuranceBadge, StatusBadge } from "./Providers";

type Ledger = Schemas["LedgerEntry"];
type Helper = Schemas["AdminHelper"];
/** A document to verify or reject: the provider's own, or one of their helpers'. */
type Target = { doc: AdminDocument; helper?: Helper };

const DOC_TONE: Record<AdminDocument["status"], string> = {
  verified: "ok",
  pending: "warn",
  rejected: "danger",
  expired: "danger",
  missing: "danger",
};
const DOC_WORD: Record<AdminDocument["status"], string> = {
  verified: "Checked",
  pending: "Waiting for a check",
  rejected: "Rejected",
  expired: "Expired",
  missing: "Not uploaded",
};
const HELPER_WORD: Record<Helper["status"], string> = {
  invited: "Invited",
  checking: "Checking documents",
  ready: "Ready to send",
};
const DAYS: Record<string, string> = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };
const KIND: Record<Ledger["kind"], string> = { charge: "Visit", tip: "Tip", refund: "Refund", adjustment: "Adjustment" };

function VerifyDialog({ p, target, onClose }: { p: Detail; target: Target; onClose: () => void }) {
  const { doc, helper } = target;
  const notify = useToast();
  const { data: catalogue } = useCategories();
  const type = catalogue?.document_types.find((t) => t.id === doc.type);
  const [issued, setIssued] = useState(doc.issued_on ?? "");
  const [expires, setExpires] = useState(doc.expires_on ?? "");
  const verify = useAdminAction(() => {
    // The upload the admin reviewed: if it's been replaced since, the API refuses (409).
    const body = { file_id: doc.file_id ?? null, issued_on: issued || null, expires_on: expires || null };
    return helper
      ? call(
          api.POST("/api/admin/providers/{provider_id}/helpers/{user_id}/documents/{doc_type}/verify", {
            params: { path: { provider_id: p.id, user_id: helper.user_id, doc_type: doc.type } },
            body,
          }),
        )
      : call(
          api.POST("/api/admin/providers/{provider_id}/documents/{doc_type}/verify", {
            params: { path: { provider_id: p.id, doc_type: doc.type } },
            body,
          }),
        );
  });
  const byIssue = !!type?.valid_months;
  return (
    <Dialog title={`Verify ${helper ? `${helper.name}'s ` : ""}${doc.label.toLowerCase()}`} onClose={onClose}>
      {doc.file_url ? (
        <a href={doc.file_url} target="_blank" rel="noreferrer" className="small">
          Open the upload <ExternalLink size={13} aria-hidden="true" />
        </a>
      ) : (
        <p className="small muted">No file was uploaded with this one.</p>
      )}
      {byIssue && (
        <TextField
          label="Issue date"
          type="date"
          value={issued}
          onChange={(e) => setIssued(e.target.value)}
          hint={`Valid for ${type?.valid_months} months from the issue date.`}
          required
        />
      )}
      {!byIssue && type?.expires && (
        <TextField label="Expiry date" type="date" value={expires} onChange={(e) => setExpires(e.target.value)} required />
      )}
      <FormError error={verify.error} />
      <div className="row" style={gap("8px")}>
        <button
          type="button"
          className="btn btn-primary"
          disabled={verify.isPending}
          onClick={async () => {
            try {
              await verify.mutateAsync(undefined);
              notify(`${doc.label} checked. ${helper ? helper.name : p.short} has been told.`);
              onClose();
            } catch {
              // shown in the dialog
            }
          }}
        >
          Mark as checked
        </button>
        <button type="button" className="btn btn-ghost" onClick={onClose}>
          Cancel
        </button>
      </div>
    </Dialog>
  );
}

function ReasonDialog({
  title,
  label,
  action,
  done,
  onClose,
}: {
  title: string;
  label: string;
  action: (reason: string) => Promise<unknown>;
  done: string;
  onClose: () => void;
}) {
  const notify = useToast();
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  return (
    <Dialog title={title} onClose={onClose}>
      <TextArea label={label} value={reason} onChange={setReason} hint="The provider sees this in their text." required />
      <FormError error={error} />
      <div className="row" style={gap("8px")}>
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy || reason.trim().length < 3}
          onClick={async () => {
            setBusy(true);
            try {
              await action(reason.trim());
              await qc.invalidateQueries({ queryKey: adminKeys.all });
              notify(done);
              onClose();
            } catch (e) {
              setError(e);
            } finally {
              setBusy(false);
            }
          }}
        >
          {title}
        </button>
        <button type="button" className="btn btn-ghost" onClick={onClose}>
          Cancel
        </button>
      </div>
    </Dialog>
  );
}

/** One row per document: the copy to check next, with the checked copy's expiry beside a renewal. */
function DocTable({ docs, onPick }: { docs: AdminDocument[]; onPick: (doc: AdminDocument, action: "verify" | "reject") => void }) {
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label="Documents">
      <table className="table">
        <thead>
          <tr>
            <th>Document</th>
            <th>Status</th>
            <th>Expires</th>
            <th>
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {docs.map((d) => (
            <tr key={d.type}>
              <td>
                {d.file_url ? (
                  <a href={d.file_url} target="_blank" rel="noreferrer">
                    {d.label}
                  </a>
                ) : (
                  d.label
                )}
                {d.note && <div className="xs muted">{d.note}</div>}
              </td>
              <td>
                {d.current_expires_on ? (
                  <>
                    <span className="badge warn">Renewal waiting</span>
                    <div className="xs muted">Checked copy until {shortDate(d.current_expires_on)}</div>
                  </>
                ) : (
                  <span className={`badge ${DOC_TONE[d.status]}`}>{DOC_WORD[d.status]}</span>
                )}
              </td>
              <td>{d.expires_on ? shortDate(d.expires_on) : <span className="muted">n/a</span>}</td>
              <td>
                {d.status !== "missing" && (
                  <div className="row" style={gap("6px")}>
                    <button type="button" className="btn btn-ghost btn-sm" onClick={() => onPick(d, "verify")}>
                      Verify
                    </button>
                    <button type="button" className="btn btn-ghost btn-sm" onClick={() => onPick(d, "reject")}>
                      Reject
                    </button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The provider's helpers: their documents to check, and marking them ready to be sent to visits. */
function Helpers({ p, onPick }: { p: Detail; onPick: (target: Target, action: "verify" | "reject") => void }) {
  const notify = useToast();
  const ready = useAdminAction((user_id: string) =>
    call(api.POST("/api/admin/providers/{provider_id}/helpers/{user_id}/ready", { params: { path: { provider_id: p.id, user_id } } })),
  );
  const helpers = p.helper_checks ?? [];
  if (helpers.length === 0) return null;
  return (
    <div className="card stack" style={gap("14px")}>
      <h2 className="h3">Helpers</h2>
      {helpers.map((h) => (
        <div key={h.user_id} className="stack" style={gap("6px")}>
          <div className="row between wrap" style={gap("8px")}>
            <span className="small">
              <b>{h.name}</b>
              {h.relationship && <span className="muted"> ({h.relationship.toLowerCase()})</span>}
              {h.phone && <span className="muted"> · {h.phone}</span>}
            </span>
            <span className={`badge ${h.status === "ready" ? "ok" : "warn"}`}>{HELPER_WORD[h.status]}</span>
          </div>
          {h.documents.length > 0 ? (
            <DocTable docs={h.documents} onPick={(doc, action) => onPick({ doc, helper: h }, action)} />
          ) : (
            <p className="small muted">Nothing uploaded yet.</p>
          )}
          {h.can_mark_ready && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              style={{ alignSelf: "flex-start" }}
              disabled={ready.isPending}
              onClick={async () => {
                try {
                  await ready.mutateAsync(h.user_id);
                  notify(`${h.name} is ready to send. ${p.short} has been told.`);
                } catch (e) {
                  notify(errorText(e));
                }
              }}
            >
              Mark ready to send
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

function RefundDialog({ entry, onClose }: { entry: Ledger; onClose: () => void }) {
  const notify = useToast();
  const [amount, setAmount] = useState((entry.gross_pence / 100).toFixed(2));
  const [reason, setReason] = useState("");
  const pence = poundsToPence(amount);
  const refund = useAdminAction(() =>
    call(
      api.POST("/api/admin/visits/{visit_id}/refund", {
        params: { path: { visit_id: entry.visit_id ?? "" } },
        body: { amount_pence: pence ?? 0, reason: reason.trim() },
      }),
    ),
  );
  return (
    <Dialog title="Refund this visit" onClose={onClose}>
      <p className="small muted">
        Paid {fmt(entry.gross_pence)}. Refunds are paid by the provider: our fee comes back in proportion, the rest from their
        earnings.
      </p>
      <TextField label="Amount (£)" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
      <TextArea label="Reason" value={reason} onChange={setReason} required />
      <FormError error={refund.error} />
      <button
        type="button"
        className="btn btn-primary"
        disabled={refund.isPending || !pence || reason.trim().length < 3}
        onClick={async () => {
          try {
            const out = await refund.mutateAsync(undefined);
            notify(`Refunded ${fmt(out.amount_pence)}: ${fmt(out.provider_refunded_pence)} from the provider, ${fmt(out.fee_refunded_pence)} of our fee.`);
            onClose();
          } catch {
            // shown in the dialog
          }
        }}
      >
        Refund {pence ? fmt(pence) : ""}
      </button>
    </Dialog>
  );
}

function PaymentAccount({ p }: { p: Detail }) {
  const notify = useToast();
  const open = useAdminAction(() => call(api.POST("/api/admin/providers/{provider_id}/payment-account", { params: { path: { provider_id: p.id } } })), [adminKeys.provider(p.id)]);
  const sync = useAdminAction(() => call(api.POST("/api/admin/providers/{provider_id}/payment-account/sync", { params: { path: { provider_id: p.id } } })), [adminKeys.provider(p.id)]);
  const words = { none: "Not set up", pending: "Started, not finished", enabled: "Ready to be paid", restricted: "Stripe needs more details" };
  return (
    <div className="card stack" style={gap("10px")}>
      <h2 className="h3">Payment account</h2>
      <dl className="kv">
        <dt>Status</dt>
        <dd>
          <span className={`badge ${p.payout_account_status === "enabled" ? "ok" : "warn"}`}>{words[p.payout_account_status]}</span>
        </dd>
        {p.payout_account_id && (
          <>
            <dt>Account</dt>
            <dd className="ident">{p.payout_account_id}</dd>
          </>
        )}
      </dl>
      <div className="row wrap" style={gap("8px")}>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={open.isPending}
          onClick={async () => {
            try {
              const link = await open.mutateAsync(undefined);
              window.open(link.url, "_blank", "noopener");
              notify("Onboarding opened in a new tab.");
            } catch (e) {
              notify(errorText(e));
            }
          }}
        >
          <ExternalLink size={15} aria-hidden="true" /> {p.payout_account_id ? "Continue onboarding" : "Set up payment account"}
        </button>
        {p.payout_account_id && (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            disabled={sync.isPending}
            onClick={async () => {
              try {
                await sync.mutateAsync(undefined);
                notify("Checked with the payment provider.");
              } catch (e) {
                notify(errorText(e));
              }
            }}
          >
            Check status
          </button>
        )}
      </div>
    </div>
  );
}

function Reminders({ p }: { p: Detail }) {
  const notify = useToast();
  const nudge = useAdminAction(
    (kind: "insurance_reminder" | "tax_details" | "signup_help") =>
      call(api.POST("/api/admin/providers/{provider_id}/nudge", { params: { path: { provider_id: p.id } }, body: { kind, note: "" } })),
    [],
  );
  const send = async (kind: "insurance_reminder" | "tax_details" | "signup_help") => {
    try {
      await nudge.mutateAsync(kind);
      notify(`Text sent to ${p.short}. It's in the outbox.`);
    } catch (e) {
      notify(errorText(e));
    }
  };
  return (
    <div className="row wrap" style={gap("8px")}>
      <button type="button" className="btn btn-ghost btn-sm" onClick={() => send("insurance_reminder")} disabled={nudge.isPending}>
        Send document reminder
      </button>
      {!p.hmrc_complete && (
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => send("tax_details")} disabled={nudge.isPending}>
          Chase tax details
        </button>
      )}
      {p.status === "signing_up" && (
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => send("signup_help")} disabled={nudge.isPending}>
          Offer help with sign-up
        </button>
      )}
    </div>
  );
}

export default function ProviderDetail() {
  const { providerId = "" } = useParams();
  const { data: p, isLoading, error } = useProvider(providerId);
  const { data: catalogue } = useCategories();
  const [verifying, setVerifying] = useState<Target | null>(null);
  const [rejecting, setRejecting] = useState<Target | null>(null);
  const pick = (target: Target, action: "verify" | "reject") => (action === "verify" ? setVerifying : setRejecting)(target);
  const [suspending, setSuspending] = useState(false);
  const [refunding, setRefunding] = useState<Ledger | null>(null);
  const notify = useToast();
  const reinstate = useAdminAction(() => call(api.POST("/api/admin/providers/{provider_id}/reinstate", { params: { path: { provider_id: providerId } } })));
  const names = Object.fromEntries((catalogue?.categories ?? []).map((c) => [c.id, c.name]));

  return (
    <>
      <Link to="/admin/providers" className="small row" style={gap("6px")}>
        <ArrowLeft size={15} aria-hidden="true" /> All providers
      </Link>
      <QueryState isLoading={isLoading} error={error}>
        {p && (
          <>
            <AdminHeader
              title={p.name}
              sub={
                <span className="row wrap" style={gap("8px")}>
                  <StatusBadge status={p.status} /> {p.area}, {p.district}
                  {p.phone && <> · {p.phone}</>}
                  {p.email && <> · {p.email}</>}
                </span>
              }
              right={
                p.status === "suspended" ? (
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={reinstate.isPending}
                    onClick={async () => {
                      try {
                        await reinstate.mutateAsync(undefined);
                        notify(`${p.short} is active again and has been told.`);
                      } catch (e) {
                        notify(errorText(e));
                      }
                    }}
                  >
                    Reinstate
                  </button>
                ) : (
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSuspending(true)}>
                    Suspend
                  </button>
                )
              }
            />
            {p.status_reason && <div className="soft small">Suspended: {p.status_reason}</div>}
            {(p.issues ?? []).length > 0 && (
              <div className="soft small stack" style={gap("4px")} role="note">
                {(p.issues ?? []).map((i) => (
                  <span key={i}>• {i}</span>
                ))}
              </div>
            )}
            <div className="a-cols">
              <div className="stack" style={gap("18px")}>
                <div className="card stack" style={gap("10px")}>
                  <h2 className="h3">Documents</h2>
                  <DocTable docs={p.documents} onPick={(doc, action) => pick({ doc }, action)} />
                  <span className="xs muted">
                    Insurance <InsuranceBadge p={p} /> · HMRC details{" "}
                    {p.hmrc_complete ? <span className="badge ok">Complete</span> : <span className="badge danger">Missing</span>}
                  </span>
                </div>
                <div className="card stack" style={gap("10px")}>
                  <h2 className="h3">Money</h2>
                  {p.ledger.length === 0 ? (
                    <p className="small muted">Nothing charged yet.</p>
                  ) : (
                    <div className="table-wrap" tabIndex={0} role="region" aria-label="Money">
                      <table className="table">
                        <thead>
                          <tr>
                            <th>Date</th>
                            <th>What</th>
                            <th>Customer paid</th>
                            <th>Our fee</th>
                            <th>To provider</th>
                            <th>
                              <span className="sr-only">Actions</span>
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {p.ledger.map((e) => (
                            <tr key={e.id}>
                              <td>{shortDate(e.local_date)}</td>
                              <td>
                                {KIND[e.kind]}
                                {e.source === "own_customer" && <span className="muted"> (own customer)</span>}
                              </td>
                              <td>{fmt(e.gross_pence)}</td>
                              <td>{fmt(e.fee_pence)}</td>
                              <td>{fmt(e.net_pence)}</td>
                              <td>
                                {e.kind === "charge" && e.visit_id && (
                                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => setRefunding(e)}>
                                    Refund
                                  </button>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
              <div className="stack" style={gap("18px")}>
                <div className="card stack" style={gap("10px")}>
                  <div className="row" style={gap("12px")}>
                    <Avatar initials={p.initials} size={44} />
                    <div className="stack" style={gap("2px")}>
                      <b>{p.short}</b>
                      <span className="small muted">
                        {p.rating_avg ? `${p.rating_avg.toFixed(1)} stars from ${p.rating_count}` : "No ratings yet"} · {p.jobs_30d} jobs in 30
                        days
                      </span>
                    </div>
                  </div>
                  <dl className="kv">
                    <dt>Jobs they do</dt>
                    <dd>{p.skills.map((s) => names[s] ?? s).join(", ") || "None yet"}</dd>
                    <dt>Travels</dt>
                    <dd>Up to {p.travel_radius_miles} miles</dd>
                    <dt>Works</dt>
                    <dd>{p.working_days.map((d) => DAYS[d] ?? d).join(", ")}</dd>
                    {p.helpers.length > 0 && (
                      <>
                        <dt>Helpers</dt>
                        <dd>{p.helpers.join(", ")}</dd>
                      </>
                    )}
                  </dl>
                  <Reminders p={p} />
                </div>
                <Helpers p={p} onPick={pick} />
                <PaymentAccount p={p} />
                <div className="card stack" style={gap("6px")}>
                  <h2 className="h3">Recent ratings</h2>
                  {p.ratings.length === 0 && <p className="small muted">None yet.</p>}
                  {p.ratings.map((r) => (
                    <div key={r.visit_id} className="list-row">
                      <Stars value={r.stars} size={14} />
                      <span className="grow small">
                        {r.customer_name}
                        {r.tags.length > 0 && <span className="muted">: {r.tags.join(", ")}</span>}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            {verifying && <VerifyDialog p={p} target={verifying} onClose={() => setVerifying(null)} />}
            {rejecting && (
              <ReasonDialog
                title="Reject document"
                label="What's wrong with it?"
                done={`Rejected. ${rejecting.helper ? rejecting.helper.name : p.short} has been asked to upload it again.`}
                action={(reason) =>
                  rejecting.helper
                    ? call(
                        api.POST("/api/admin/providers/{provider_id}/helpers/{user_id}/documents/{doc_type}/reject", {
                          params: { path: { provider_id: p.id, user_id: rejecting.helper.user_id, doc_type: rejecting.doc.type } },
                          body: { reason, file_id: rejecting.doc.file_id ?? null },
                        }),
                      )
                    : call(
                        api.POST("/api/admin/providers/{provider_id}/documents/{doc_type}/reject", {
                          params: { path: { provider_id: p.id, doc_type: rejecting.doc.type } },
                          body: { reason, file_id: rejecting.doc.file_id ?? null },
                        }),
                      )
                }
                onClose={() => setRejecting(null)}
              />
            )}
            {suspending && (
              <ReasonDialog
                title="Suspend"
                label="Why are we pausing their account?"
                done={`${p.short} is suspended and won't get new jobs.`}
                action={(reason) => call(api.POST("/api/admin/providers/{provider_id}/suspend", { params: { path: { provider_id: p.id } }, body: { reason } }))}
                onClose={() => setSuspending(false)}
              />
            )}
            {refunding && <RefundDialog entry={refunding} onClose={() => setRefunding(null)} />}
          </>
        )}
      </QueryState>
    </>
  );
}
