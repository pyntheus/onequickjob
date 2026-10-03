/** Overview and dispatch (the prototype's AdminOverview), on real data. Owned by L3. */
import { Calendar, Copy } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { api, call } from "../../api/client";
import { useConfig } from "../../api/queries";
import { CatIcon } from "../../shared/CatIcon";
import { fmt } from "../../shared/format";
import { useToast } from "../../shared/toast-context";
import { useAdminAction, useOverview, type Overview as OverviewData, type UnfilledRequest } from "../api";
import { AdminHeader, Kpis, QueryState } from "../components";
import { errorText, gap } from "../util";

function plural(n: number, one: string, many = one + "s") {
  return `${n} ${n === 1 ? one : many}`;
}

function Waiting({ r }: { r: UnfilledRequest }) {
  const notify = useToast();
  const [text, setText] = useState<string | null>(null);
  const raise = useAdminAction((ref: string) =>
    call(api.POST("/api/admin/requests/{ref}/raise-guide", { params: { path: { ref } }, body: { percent: 10, note: "" } })),
  );
  const copy = async () => {
    let message: string;
    try {
      message = (await call(api.GET("/api/admin/requests/{ref}/whatsapp", { params: { path: { ref: r.request_ref } } }))).text;
    } catch (e) {
      notify(errorText(e));
      return;
    }
    setText(message);
    try {
      await navigator.clipboard.writeText(message);
      notify("Copied. Paste it into the providers' WhatsApp group.");
    } catch {
      notify("Couldn't copy here. The message is shown below the request.");
    }
  };
  const raiseGuide = async () => {
    try {
      const updated = await raise.mutateAsync(r.request_ref);
      // A12: the raise waits for the customer's approval.
      notify(`Raise to ${fmt(updated.proposed_guide_pence ?? updated.guide_pence)} sent to the customer to approve. Logged for review.`);
    } catch (e) {
      notify(errorText(e));
    }
  };
  return (
    <div className="req">
      <div className="row between top" style={gap("12px")}>
        <div className="row top" style={gap("12px")}>
          <span className="cat-ico sm">
            <CatIcon id={r.category_id} size={17} />
          </span>
          <div className="stack" style={gap("0px")}>
            <b>
              {r.category_name} in {r.area}, {r.district}
            </b>
            <span className="small muted">
              Request {r.request_ref}, waiting {r.age_text}
            </span>
          </div>
        </div>
        <b>{fmt(r.guide_pence)}</b>
      </div>
      <span className="small">{r.why}</span>
      <div className="row wrap" style={gap("8px")}>
        <button type="button" className="btn btn-primary btn-sm" onClick={copy}>
          <Copy size={15} aria-hidden="true" /> Copy WhatsApp message
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={raiseGuide} disabled={raise.isPending}>
          Raise guide 10%
        </button>
      </div>
      {text && (
        <div className="soft small" aria-label={`WhatsApp message for ${r.request_ref}`}>
          {text}
        </div>
      )}
    </div>
  );
}

function Districts({ d }: { d: OverviewData }) {
  const maxJobs = Math.max(1, ...d.districts.map((t) => t.jobs));
  const gaps = d.districts.filter((t) => t.jobs > 0 && t.providers === 0).map((t) => t.code);
  return (
    <div className="card stack" style={gap("12px")}>
      <div className="stack" style={gap("2px")}>
        <h2 className="h3">Where the work is</h2>
        <span className="small muted">Jobs this week by postcode district. Darker means more jobs.</span>
      </div>
      <div className="tiles">
        {d.districts.map((t) => {
          const o = 0.12 + (t.jobs / maxJobs) * 0.8;
          return (
            <div key={t.code} className={"tile" + (o > 0.5 ? " dark" : "")}>
              <span className="fill" style={{ opacity: o }} />
              <div className="in">
                <b>{t.code}</b>
                <span className="xs muted">{t.name}</span>
                <span className="xs" style={{ fontWeight: 600 }}>
                  {plural(t.jobs, "job")}, {plural(t.providers, "provider")}
                </span>
              </div>
            </div>
          );
        })}
      </div>
      <p className="small">
        {gaps.length
          ? `${gaps.length > 1 ? gaps.slice(0, -1).join(", ") + " and " + gaps.at(-1) : gaps[0]} ${gaps.length > 1 ? "have" : "has"} demand but no active providers. Recruit there before advertising further out.`
          : "Every district with work this week has a provider living in it."}
      </p>
    </div>
  );
}

function OwnCustomers({ d }: { d: OverviewData }) {
  const { data: config } = useConfig();
  const c = d.own_customers;
  const tiles: [string, string, string][] = [
    ["Active", String(c.active), `from ${plural(c.providers, "provider")}`],
    ["Job value", fmt(c.job_value_pence), "this week"],
    ["Our revenue", fmt(c.revenue_pence), "includes £1 minimums"],
    ["Invites blocked", String(c.invites_blocked), "already our customers"],
  ];
  return (
    <div className="card stack" style={gap("12px")}>
      <div className="row between">
        <h2 className="h3">Customers providers brought</h2>
        <span className="badge ok">{config?.fees.own_customer_percent ?? 5}% fee</span>
      </div>
      <div className="grid2">
        {tiles.map(([l, v, sub]) => (
          <div key={l} className="stack" style={gap("0px")}>
            <span className="xs muted">{l}</span>
            <span className="big-num" style={{ fontSize: 24 }}>
              {v}
            </span>
            <span className="xs muted">{sub}</span>
          </div>
        ))}
      </div>
      <p className="small muted">
        The real return isn't the 5%. Watch whether providers who bring customers also take more of ours, and stay longer.
      </p>
    </div>
  );
}

const NUDGE = { "Send reminder": "insurance_reminder", Chase: "tax_details" } as const;

function Attention({ d }: { d: OverviewData }) {
  const notify = useToast();
  const nudge = useAdminAction(
    (a: { provider_id: string; kind: "insurance_reminder" | "tax_details" }) =>
      call(api.POST("/api/admin/providers/{provider_id}/nudge", { params: { path: { provider_id: a.provider_id } }, body: { kind: a.kind, note: "" } })),
    [],
  );
  return (
    <div className="card stack" style={gap("4px")}>
      <h2 className="h3" style={{ paddingBottom: 6 }}>
        Providers needing attention
      </h2>
      {d.attention.length === 0 && <p className="small muted">Nobody right now.</p>}
      {d.attention.map((a) => (
        <div key={a.provider_id + a.issue} className="list-row">
          <Link to={`/admin/providers/${a.provider_id}`} className={`badge ${a.tone}`}>
            {a.short}
          </Link>
          <span className="grow small">{a.issue}</span>
          {a.action === "Ring them" ? (
            <Link to={`/admin/providers/${a.provider_id}`} className="btn btn-ghost btn-sm">
              Ring them
            </Link>
          ) : (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={nudge.isPending}
              onClick={async () => {
                try {
                  await nudge.mutateAsync({ provider_id: a.provider_id, kind: NUDGE[a.action as keyof typeof NUDGE] });
                  notify(`Reminder sent to ${a.short}. It's in the outbox.`);
                } catch (e) {
                  notify(errorText(e));
                }
              }}
            >
              {a.action}
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

const CHARGE_WORDS: Record<string, string> = {
  failed: "Card declined",
  requires_action: "Waiting for the customer to confirm",
  pending: "Not confirmed yet",
  not_started: "Finished, but the charge never started",
  refund_pending: "Refund not confirmed yet",
  refund_fee_pending: "Refund made; our fee still to return to the provider",
  refund_restore: "Refund failed; giving the provider back what it took from them",
};

function Payments({ d }: { d: OverviewData }) {
  const payments = d.payments ?? [];
  const notify = useToast();
  const retry = useAdminAction((visit_id: string) =>
    call(api.POST("/api/admin/visits/{visit_id}/retry-charge", { params: { path: { visit_id } } })),
  );
  if (payments.length === 0) return null;
  return (
    <div className="card stack" style={gap("4px")}>
      <div className="row between" style={{ paddingBottom: 6 }}>
        <h2 className="h3">Payments needing a look</h2>
        <span className="badge danger">{plural(payments.length, "visit")}</span>
      </div>
      {payments.map((p) => (
        <div key={p.kind + p.visit_id + p.status} className="list-row">
          <div className="grow stack" style={gap("2px")}>
            <span className="small">
              <b>{fmt(p.amount_pence)}</b> {p.category_name}, {p.customer_name} with {p.provider_short}
            </span>
            <span className="xs muted">
              {CHARGE_WORDS[p.status] ?? p.status}
              {p.failure_reason ? `: ${p.failure_reason}` : ""}
            </span>
          </div>
          {p.kind === "refund" ? (
            <span className="xs muted" style={{ maxWidth: 150 }}>
              Checked again every few minutes
            </span>
          ) : (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            disabled={retry.isPending}
            onClick={async () => {
              try {
                const st = await retry.mutateAsync(p.visit_id);
                notify(st.status === "succeeded" ? "Paid. The ledger and receipts are updated." : `Still not paid: ${st.failure_reason ?? st.status}`);
              } catch (e) {
                notify(errorText(e));
              }
            }}
          >
            Retry charge
          </button>
          )}
        </div>
      ))}
    </div>
  );
}

export default function Overview() {
  const { data: d, isLoading, error } = useOverview();
  return (
    <>
      <AdminHeader
        title="This week"
        sub={d?.week_label}
        right={
          d?.season_note && (
            <span className="badge warn">
              <Calendar size={13} aria-hidden="true" /> {d.season_note}
            </span>
          )
        }
      />
      <QueryState isLoading={isLoading} error={error}>
        {d && (
          <>
            <Kpis items={d.kpis} />
            <div className="a-cols">
              <div className="stack" style={gap("18px")}>
                <div className="card stack" style={gap("4px")}>
                  <div className="row between" style={{ paddingBottom: 8 }}>
                    <h2 className="h3">Waiting for a provider</h2>
                    <span className={`badge ${d.waiting.length ? "danger" : "ok"}`}>{plural(d.waiting.length, "job")}</span>
                  </div>
                  {d.waiting.length === 0 && <p className="small muted">Nothing has been waiting more than an hour.</p>}
                  {d.waiting.map((r) => (
                    <Waiting key={r.request_id} r={r} />
                  ))}
                </div>
                <Payments d={d} />
              </div>
              <div className="stack" style={gap("18px")}>
                <Districts d={d} />
                <OwnCustomers d={d} />
                <Attention d={d} />
              </div>
            </div>
          </>
        )}
      </QueryState>
    </>
  );
}
