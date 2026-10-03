import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { useState, type CSSProperties } from "react";
import { useParams } from "react-router";
import { api, call } from "../../api/client";
import { fmt } from "../../shared/format";
import { Loading, Notice } from "../../app/Status";
import { errorText } from "../api";

const g = (px: number) => ({ "--g": `${px}px` }) as CSSProperties;
const CLOSED: Record<string, string> = {
  accepted: "You accepted this change. The plan has been updated.",
  declined: "You declined this change. The plan stays as it was.",
  lapsed: "This change lapsed after 48 hours without an answer, so the plan stays as it was.",
  withdrawn: "The customer withdrew or replaced this change.",
};

/**
 * A10: the link in a provider's text when a customer asks to change how often their plan runs.
 * The prices are the API's (re-priced from the pricing engine); this page only shows them.
 * Large type and big buttons, as in the provider area.
 */
export default function PlanChange() {
  const { token = "" } = useParams();
  const qc = useQueryClient();
  const key = ["c", "plan-change", token];
  const { data: c, isLoading, error } = useQuery({
    queryKey: key,
    queryFn: () => call(api.GET("/api/c/plan-changes/{token}", { params: { path: { token } } })),
    retry: false,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (isLoading) return <Loading />;
  if (error || !c) {
    return (
      <div className="c-flow">
        <Notice title="We can't find that change">
          <p className="muted">{errorText(error, "The link may be mistyped.")}</p>
        </Notice>
      </div>
    );
  }
  const answer = async (how: "accept" | "decline") => {
    setBusy(true);
    setErr(null);
    try {
      const out =
        how === "accept"
          ? await call(api.POST("/api/c/plan-changes/{token}/accept", { params: { path: { token } } }))
          : await call(api.POST("/api/c/plan-changes/{token}/decline", { params: { path: { token } } }));
      qc.setQueryData(key, out);
    } catch (e) {
      setErr(errorText(e));
      await qc.invalidateQueries({ queryKey: key });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="c-flow provider-size">
      <div className="stack" style={g(6)}>
        <span className="kicker">
          {c.category_name} in {c.area}
        </span>
        <h1 className="h1">
          {c.customer_first_name} would like visits {c.to_frequency_label}
        </h1>
      </div>
      <div className="card stack" style={g(12)}>
        <dl className="kv">
          <dt>Now</dt>
          <dd>
            {c.from_frequency_label}, {fmt(c.from_price_pence)} a visit
          </dd>
          <dt>Asked for</dt>
          <dd>
            {c.to_frequency_label}, <b>{fmt(c.to_price_pence)} a visit</b>
          </dd>
          <dt>You'd get</dt>
          <dd>{fmt(c.provider_pence)} a visit, after the OneQuickJob fee</dd>
        </dl>
        <p className="small muted">
          The new price comes from our pricing at the new frequency, keeping any price you agreed in proportion. Your next
          visit stays as it is.
        </p>
      </div>
      {c.status === "pending" ? (
        <>
          <p className="small">
            Please answer by{" "}
            {new Date(c.expires_at).toLocaleString("en-GB", {
              weekday: "long",
              day: "numeric",
              month: "long",
              hour: "numeric",
              minute: "2-digit",
              timeZone: "Europe/London",
            })}
            . If you don't, the plan stays as it is.
          </p>
          {err && (
            <p className="field-error" role="alert">
              {err}
            </p>
          )}
          <div className="stack" style={g(10)}>
            <button type="button" className="btn btn-primary btn-lg btn-block" disabled={busy} onClick={() => answer("accept")}>
              Accept {fmt(c.to_price_pence)} a visit
            </button>
            <button type="button" className="btn btn-ghost btn-lg btn-block" disabled={busy} onClick={() => answer("decline")}>
              Keep it as it is
            </button>
          </div>
        </>
      ) : (
        <div className="soft row" style={g(10)} role="status">
          {c.status === "accepted" && <Check size={20} aria-hidden="true" />}
          <span>{CLOSED[c.status]}</span>
        </div>
      )}
    </div>
  );
}
