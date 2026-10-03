/** Pricing and calibration (the prototype's AdminCalibration), plus pricing versions: one admin
 * drafts a change, a different admin approves it and it goes live. Owned by L3. */
import { Check } from "lucide-react";
import { useState } from "react";
import { api, call } from "../../api/client";
import { useMe } from "../../api/queries";
import { fmt, pct } from "../../shared/format";
import { useToast } from "../../shared/toast-context";
import { useAdminAction, useCalibration, useVersions, type Calibration, type PricingVersionSummary, type Suggestion } from "../api";
import { AdminHeader, Kpis, QueryState } from "../components";
import { errorText, gap } from "../util";

function EstimateScatter({ data }: { data: Calibration }) {
  const W = 560;
  const H = 340;
  const P = { l: 46, r: 14, t: 14, b: 42 };
  const top = Math.max(...data.points.flatMap((p) => [p.est_mins, p.actual_mins]), 300);
  const max = Math.ceil((top * 1.05) / 60) * 60;
  const x = (v: number) => P.l + (v / max) * (W - P.l - P.r);
  const y = (v: number) => H - P.b - (v / max) * (H - P.t - P.b);
  const color = Object.fromEntries(data.segments.map((s) => [s.id, `var(${s.color_token})`]));
  const ticks = Array.from({ length: max / 60 + 1 }, (_, i) => i * 60);
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="chart"
      role="img"
      aria-label={`Estimated minutes against actual minutes for ${data.points.length} timed jobs`}
    >
      {ticks.map((t) => (
        <g key={t}>
          <line x1={x(0)} x2={x(max)} y1={y(t)} y2={y(t)} style={{ stroke: "var(--hair)" }} />
          <text x={x(0) - 8} y={y(t) + 4} textAnchor="end" className="chart-lbl">
            {t}
          </text>
          <text x={x(t)} y={H - P.b + 16} textAnchor="middle" className="chart-lbl">
            {t}
          </text>
        </g>
      ))}
      <path d={`M${x(0)} ${y(0)} L${x(max / 1.25)} ${y(max)} L${x(max)} ${y(max)} Z`} style={{ fill: "var(--primary)", opacity: 0.06 }} />
      <line x1={x(0)} y1={y(0)} x2={x(max)} y2={y(max)} style={{ stroke: "var(--muted)", strokeDasharray: "5 5" }} />
      <text x={x(max * 0.8)} y={y(max * 0.86)} className="chart-lbl" transform={`rotate(-31 ${x(max * 0.8)} ${y(max * 0.86)})`}>
        Actual = estimate
      </text>
      {data.points.map((p) => (
        <circle
          key={p.visit_id}
          cx={x(p.est_mins)}
          cy={y(Math.min(p.actual_mins, max))}
          r="4.5"
          style={{ fill: color[p.segment] ?? "var(--muted)", opacity: 0.85, stroke: "var(--surface)", strokeWidth: 1 }}
        />
      ))}
      <text x={(x(0) + x(max)) / 2} y={H - 6} textAnchor="middle" className="chart-lbl">
        Estimated minutes
      </text>
      <text x={12} y={(y(0) + y(max)) / 2} textAnchor="middle" className="chart-lbl" transform={`rotate(-90 12 ${(y(0) + y(max)) / 2})`}>
        Actual minutes
      </text>
    </svg>
  );
}

function changeText(c: PricingVersionSummary["changes"][number]): string {
  const show = (v: unknown) => (typeof v === "number" && c.path.includes("pence") ? fmt(v) : String(v));
  return `${c.category_id} ${c.path}: ${show(c.before)} → ${show(c.after)}`;
}

function Insight({ s, liveId, drafted, onDrafted }: { s: Suggestion; liveId?: string; drafted?: number; onDrafted: (v: number) => void }) {
  const notify = useToast();
  const draft = useAdminAction(() =>
    call(
      api.POST("/api/admin/pricing/versions", {
        body: {
          based_on: liveId ?? "",
          changes: [{ category_id: s.change.category_id, path: s.change.path, after: s.change.after }],
          notes: s.title,
        },
      }),
    ),
  );
  return (
    <div className="card insight stack" style={gap("10px")}>
      <h3 className="h3">{s.title}</h3>
      <p className="small muted">{s.body}</p>
      <div className="soft small">
        <b>Suggested:</b> {s.change_text}
      </div>
      {drafted ? (
        <span className="badge ok" style={{ alignSelf: "flex-start" }}>
          <Check size={13} aria-hidden="true" /> Drafted as version {drafted}
        </span>
      ) : (
        <button
          type="button"
          className="btn btn-primary btn-sm"
          style={{ alignSelf: "flex-start" }}
          disabled={!liveId || draft.isPending}
          onClick={async () => {
            try {
              const v = await draft.mutateAsync(undefined);
              onDrafted(v.version);
              notify("Change drafted. It goes live after sign-off.");
            } catch (e) {
              notify(errorText(e));
            }
          }}
        >
          Draft this change
        </button>
      )}
    </div>
  );
}

function Versions({ versions }: { versions: PricingVersionSummary[] }) {
  const notify = useToast();
  const approve = useAdminAction((id: string) => call(api.POST("/api/admin/pricing/versions/{version_id}/approve", { params: { path: { version_id: id } } })));
  const live = versions.find((v) => v.status === "live");
  const when = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  return (
    <div className="card stack" style={gap("6px")}>
      <div className="stack" style={gap("2px")}>
        <h2 className="h3">Pricing versions</h2>
        <span className="small muted">
          A change goes live only when a second admin approves it. Every quote keeps the version it was priced with.
        </span>
      </div>
      {versions.map((v) => (
        <div key={v.id} className="list-row top">
          <span className={`badge ${v.status === "live" ? "ok" : v.status === "draft" ? "warn" : ""}`}>
            v{v.version} {v.status}
          </span>
          <div className="grow stack" style={gap("2px")}>
            <span className="small">
              {v.changes.length ? v.changes.map(changeText).join("; ") : v.notes || "The prices from the prototype"}
            </span>
            <span className="xs muted">
              Drafted by {v.created_by_name}, {when(v.created_at)}
              {v.approved_by_name && v.approved_at && `. Approved by ${v.approved_by_name}, ${when(v.approved_at)}`}
            </span>
          </div>
          {v.status === "draft" &&
            (v.can_approve ? (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                disabled={approve.isPending}
                onClick={async () => {
                  try {
                    await approve.mutateAsync(v.id);
                    notify(`Version ${v.version} is live.${live ? ` Version ${live.version} is retired.` : ""}`);
                  } catch (e) {
                    notify(errorText(e));
                  }
                }}
              >
                Approve and make live
              </button>
            ) : (
              <span className="xs muted" style={{ maxWidth: 140 }}>
                Waiting for another admin to approve
              </span>
            ))}
        </div>
      ))}
    </div>
  );
}

export default function Pricing() {
  const { data, isLoading, error } = useCalibration();
  const { data: versions } = useVersions();
  const { data: me } = useMe();
  const [drafted, setDrafted] = useState<Record<string, number>>({});
  const liveId = versions?.find((v) => v.status === "live")?.id;
  const pendingByMe = (versions ?? []).filter((v) => v.status === "draft" && v.created_by === me?.user_id);
  return (
    <>
      <AdminHeader
        title="Pricing and calibration"
        sub={`Guide prices compared with what jobs actually took. Last 90 days.${data ? ` Live prices: version ${data.live_version}.` : ""}`}
      />
      <QueryState isLoading={isLoading} error={error}>
        {data && (
          <>
            <Kpis items={data.kpis} />
            <div className="a-cols">
              <div className="card stack" style={gap("12px")}>
                <h2 className="h3">Estimated against actual time</h2>
                <EstimateScatter data={data} />
                <div className="legend">
                  {data.segments.map((s) => (
                    <span key={s.id}>
                      <span className="dot" style={{ background: `var(${s.color_token})` }} /> {s.label}
                    </span>
                  ))}
                </div>
                <p className="small muted">The shaded band is up to 25% over estimate. Points above it are jobs we underpriced.</p>
              </div>
              <div className="stack" style={gap("14px")}>
                {data.suggestions.length === 0 && (
                  <div className="card small muted">No suggestions: no job type is far enough off, across enough jobs, to change.</div>
                )}
                {data.suggestions.map((s) => (
                  <Insight
                    key={s.id}
                    s={s}
                    liveId={liveId}
                    drafted={drafted[s.id]}
                    onDrafted={(v) => setDrafted((d) => ({ ...d, [s.id]: v }))}
                  />
                ))}
              </div>
            </div>
            <div className="card">
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Job type</th>
                      <th>Jobs</th>
                      <th>Taken at guide</th>
                      <th>Countered</th>
                      <th>Median counter</th>
                      <th>Median overrun</th>
                      <th>Over by 25%+</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.table.map((r) => (
                      <tr key={r.segment}>
                        <td>
                          <b>{r.label}</b>
                        </td>
                        <td>{r.jobs}</td>
                        <td>{pct(r.taken_at_guide)}</td>
                        <td>{r.countered > 0.5 ? <span className="badge warn">{pct(r.countered)}</span> : pct(r.countered)}</td>
                        <td>{r.median_counter_uplift_pence ? `+${fmt(r.median_counter_uplift_pence)}` : <span className="muted">n/a</span>}</td>
                        <td>
                          {r.median_overrun >= 0.2 ? (
                            <span className="badge danger">+{pct(r.median_overrun)}</span>
                          ) : (
                            `${r.median_overrun >= 0 ? "+" : ""}${pct(r.median_overrun)}`
                          )}
                        </td>
                        <td>{pct(r.over_25)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </QueryState>
      {versions && <Versions versions={versions} />}
      {pendingByMe.length > 0 && (
        <p className="small muted">You drafted {pendingByMe.length === 1 ? "a change" : "changes"}: another admin signs it off.</p>
      )}
    </>
  );
}
