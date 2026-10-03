/** Categories (the prototype's AdminCategories): grouped list with how many providers can take
 * each, the record viewer and the jobs we never list. Viewing only. Owned by L3. */
import { Plus } from "lucide-react";
import { useState } from "react";
import { useCategories } from "../../api/queries";
import { CatIcon } from "../../shared/CatIcon";
import { useToast } from "../../shared/toast-context";
import { useAdminCategories, useCategoryRecord, type CategoryAdminRow, type CategoryRecord } from "../api";
import { AdminHeader, QueryState } from "../components";
import { gap } from "../util";

function schemaOf(rec: CategoryRecord) {
  const c = rec.category;
  return {
    id: c.id,
    group: c.group,
    status: c.status,
    skill: c.skill,
    pricingModel: c.pricing_model,
    pricingVersion: rec.pricing_version,
    pricingParams: rec.pricing_params,
    measure: c.measure ?? null,
    recurring: c.recurring,
    requires: c.requires,
    intake: c.intake.map((f) => ({
      key: f.key,
      type: f.type,
      ...(f.options ? { options: f.options.map((o) => o.value) } : {}),
      ...(f.items ? { items: f.items.map((it) => it.key) } : {}),
      ...(f.unit ? { unit: f.unit, min: f.min, max: f.max } : {}),
      default: f.default,
    })),
  };
}

function Pool({ row }: { row: CategoryAdminRow }) {
  const n = row.provider_count;
  return <span className={`badge ${n >= 2 ? "ok" : n === 1 ? "warn" : "danger"}`}>{n} {n === 1 ? "provider" : "providers"}</span>;
}

export default function Categories() {
  const notify = useToast();
  const { data: rows, isLoading, error } = useAdminCategories();
  const { data: catalogue } = useCategories();
  const [selected, setSelected] = useState("mowing");
  const { data: record } = useCategoryRecord(selected);
  const live = (rows ?? []).filter((r) => r.category.status === "live");
  const current = rows?.find((r) => r.category.id === selected);
  return (
    <>
      <AdminHeader
        title="Categories"
        sub={`${live.length || 15} live job types. Each is a record, not code: questions, a pricing model and the documents a provider needs.`}
        right={
          <button type="button" className="btn btn-primary btn-sm" onClick={() => notify("Adding categories comes after the prototype. For now they're seeded data.")}>
            <Plus size={15} aria-hidden="true" /> New category
          </button>
        }
      />
      <QueryState isLoading={isLoading} error={error}>
        <div className="a-cols">
          <div className="stack" style={gap("18px")}>
            {(catalogue?.groups ?? []).map((g) => (
              <div key={g.id} className="stack" style={gap("8px")}>
                <h2 className="h3">{g.name}</h2>
                {(rows ?? [])
                  .filter((r) => r.category.group === g.id)
                  .map((r) => (
                    <button
                      key={r.category.id}
                      type="button"
                      className={"choice" + (selected === r.category.id ? " on" : "")}
                      onClick={() => setSelected(r.category.id ?? "")}
                      aria-pressed={selected === r.category.id}
                    >
                      <span className="cat-ico sm">
                        <CatIcon icon={r.category.icon} id={r.category.id} size={17} />
                      </span>
                      <span className="grow stack" style={gap("6px")}>
                        <span className="row between wrap" style={gap("8px")}>
                          <b>{r.category.name}</b>
                          <span className="row" style={gap("6px")}>
                            {r.category.status !== "live" && <span className="badge">Planned</span>}
                            <Pool row={r} />
                          </span>
                        </span>
                        <span className="req-docs">
                          {r.extra_documents.map((d) => (
                            <span key={d} className="badge">
                              {d}
                            </span>
                          ))}
                          {r.extra_documents.length === 0 && <span className="xs muted">Insurance only</span>}
                        </span>
                      </span>
                    </button>
                  ))}
              </div>
            ))}
          </div>
          <div className="stack" style={gap("18px")}>
            <div className="card stack" style={gap("12px")}>
              <div className="row between wrap">
                <h2 className="h3">{current?.category.name ?? "Category"} record</h2>
                {current && <span className="ident">{current.category.pricing_model}</span>}
              </div>
              <p className="small muted">The quote flow, provider matching and document checks all render from this.</p>
              {record ? <pre className="code">{JSON.stringify(schemaOf(record), null, 2)}</pre> : <p className="small muted">Loading…</p>}
            </div>
            <div className="card stack" style={gap("12px")}>
              <h2 className="h3">Never listed</h2>
              <p className="small muted">Shown to customers on the home page, with who to use instead.</p>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Job</th>
                      <th>Why not</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(catalogue?.excluded ?? []).map((x) => (
                      <tr key={x.name}>
                        <td>
                          <b>{x.name}</b>
                        </td>
                        <td className="muted wrap-cell">{x.why}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </QueryState>
    </>
  );
}
