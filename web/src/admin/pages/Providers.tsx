/** Providers (the prototype's AdminProviders): the table with filters, each row opening the
 * provider's page, and the HMRC export. Owned by L3. */
import { AlertTriangle, Download, Star } from "lucide-react";
import { useId, useState } from "react";
import { Link } from "react-router";
import { useCategories } from "../../api/queries";
import { Avatar } from "../../shared/Avatar";
import { CatIcon } from "../../shared/CatIcon";
import { Chip } from "../../shared/Chip";
import { pct } from "../../shared/format";
import { hmrcExportUrl, useProviders, type ProviderFilter, type ProviderRow } from "../api";
import { AdminHeader, QueryState } from "../components";
import { gap, shortDate } from "../util";

const FILTERS: [ProviderFilter, string][] = [
  ["all", "Everyone"],
  ["attention", "Needs attention"],
  ["signup", "Signing up"],
];
const STATUS: Record<ProviderRow["status"], string> = {
  active: "Active",
  payouts_paused: "Payouts paused",
  suspended: "Suspended",
  signing_up: "Signing up",
};

/** From the copy that counts: a renewal waiting for a check shows beside it, never as "Missing". */
export function InsuranceBadge({ p }: { p: ProviderRow }) {
  const { status, expires_on, renewal_waiting } = p.insurance;
  const renewal = renewal_waiting ? <span className="badge warn">Renewal waiting</span> : null;
  if (status === "ok")
    return (
      <>
        <span className="badge ok">Until {expires_on ? shortDate(expires_on) : "no expiry"}</span> {renewal}
      </>
    );
  if (status === "warn")
    return (
      <>
        <span className="badge warn">
          <AlertTriangle size={12} aria-hidden="true" /> Expires {expires_on ? shortDate(expires_on) : "soon"}
        </span>{" "}
        {renewal}
      </>
    );
  if (status === "renewal")
    return <span className="badge warn">{p.status === "signing_up" ? "Waiting for a check" : "Renewal waiting"}</span>;
  return <span className="badge danger">Missing</span>;
}

export function StatusBadge({ status }: { status: ProviderRow["status"] }) {
  return <span className={`badge ${status === "active" ? "ok" : status === "suspended" ? "danger" : "warn"}`}>{STATUS[status]}</span>;
}

function HmrcExport() {
  const id = useId();
  const thisYear = new Date().getFullYear();
  const [year, setYear] = useState(thisYear);
  return (
    <div className="row wrap" style={gap("8px")}>
      <label htmlFor={id} className="small muted">
        HMRC export
      </label>
      <select id={id} className="input" style={{ width: 110, height: 40 }} value={year} onChange={(e) => setYear(Number(e.target.value))}>
        {[thisYear, thisYear - 1, thisYear - 2].filter((y) => y >= 2024).map((y) => (
          <option key={y} value={y}>
            {y}
          </option>
        ))}
      </select>
      <a className="btn btn-ghost btn-sm" href={hmrcExportUrl(year)} download>
        <Download size={15} aria-hidden="true" /> Download CSV
      </a>
    </div>
  );
}

export default function Providers() {
  const [filter, setFilter] = useState<ProviderFilter>("all");
  const { data: rows, isLoading, error } = useProviders(filter);
  const { data: all } = useProviders("all");
  const { data: catalogue } = useCategories();
  const short = Object.fromEntries((catalogue?.categories ?? []).map((c) => [c.id, c]));
  const counts = all
    ? `${all.filter((p) => p.status !== "signing_up").length} active, ${all.filter((p) => p.status === "signing_up").length} signing up`
    : undefined;
  return (
    <>
      <AdminHeader title="Providers" sub={counts} right={<HmrcExport />} />
      <div className="chips">
        {FILTERS.map(([v, l]) => (
          <Chip key={v} on={filter === v} onClick={() => setFilter(v)}>
            {l}
          </Chip>
        ))}
      </div>
      <QueryState isLoading={isLoading} error={error}>
        <div className="card">
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Providers">
            <table className="table">
              <thead>
                <tr>
                  <th>Provider</th>
                  <th>Area</th>
                  <th>Jobs they do</th>
                  <th>Rating</th>
                  <th>Jobs, 30 days</th>
                  <th>Accept rate</th>
                  <th>Insurance</th>
                  <th>HMRC details</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {(rows ?? []).map((p) => (
                  <tr key={p.id}>
                    <td>
                      <div className="row" style={gap("10px")}>
                        <Avatar initials={p.initials} size={32} />
                        <Link to={`/admin/providers/${p.id}`}>
                          <b>{p.name}</b>
                        </Link>
                      </div>
                    </td>
                    <td>
                      {p.area} <span className="muted">{p.district}</span>
                    </td>
                    <td className="wrap-cell">
                      <div className="row wrap" style={gap("4px")}>
                        {p.skills.map((s) => (
                          <span key={s} className="badge" title={short[s]?.name ?? s}>
                            <CatIcon id={s} size={13} /> {short[s]?.short ?? s}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td>
                      {p.rating_avg ? (
                        <span className="row" style={gap("4px")}>
                          <Star size={14} fill="var(--star)" color="var(--star)" aria-hidden="true" /> {p.rating_avg.toFixed(1)}{" "}
                          <span className="muted">({p.rating_count})</span>
                        </span>
                      ) : (
                        <span className="muted">None yet</span>
                      )}
                    </td>
                    <td>{p.jobs_30d}</td>
                    <td>{p.accept_rate == null ? <span className="muted">n/a</span> : pct(p.accept_rate)}</td>
                    <td>
                      <InsuranceBadge p={p} />
                    </td>
                    <td>{p.hmrc_complete ? <span className="badge ok">Complete</span> : <span className="badge danger">Missing</span>}</td>
                    <td>
                      <StatusBadge status={p.status} />
                    </td>
                  </tr>
                ))}
                {rows?.length === 0 && (
                  <tr>
                    <td colSpan={9} className="muted">
                      Nobody here.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </QueryState>
      <p className="small muted">
        Providers without complete HMRC details can't be paid out, because platform reporting requires them. The HMRC export is a
        draft format: check it against HMRC's specification before any real use.
      </p>
    </>
  );
}
