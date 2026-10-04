/** A change of how often a plan runs (A10): the link in the provider's text. Owned by L2 (moved
 * here from the customer web, which now redirects /plan-change/:token to this page).
 *
 * The single-use token in the address is the authority, as for an invite: no sign-in is needed
 * (the layout lets this page through). The prices are the API's, re-priced by the pricing engine;
 * this page only shows them. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { useParams } from "react-router";
import { api, call } from "../../api/client";
import { Loading, Notice } from "../../app/Status";
import { Button } from "../../shared/Button";
import { fmt } from "../../shared/format";
import { pKeys } from "../api";
import { ErrorNote, Note } from "../components";
import { css, errorText } from "../util";

const CLOSED: Record<string, string> = {
  accepted: "You accepted this change. The plan has been updated.",
  declined: "You declined this change. The plan stays as it was.",
  lapsed: "This change lapsed after 48 hours without an answer, so the plan stays as it was.",
  withdrawn: "The customer withdrew or replaced this change.",
};

function deadline(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "Europe/London",
  });
}

export default function PlanChange() {
  const { token = "" } = useParams();
  const qc = useQueryClient();
  const key = [...pKeys.all, "plan-change", token];
  const { data: c, isLoading, error } = useQuery({
    queryKey: key,
    queryFn: () => call(api.GET("/api/c/plan-changes/{token}", { params: { path: { token } } })),
    retry: false,
  });
  const answer = useMutation({
    mutationFn: (how: "accept" | "decline") =>
      how === "accept"
        ? call(api.POST("/api/c/plan-changes/{token}/accept", { params: { path: { token } } }))
        : call(api.POST("/api/c/plan-changes/{token}/decline", { params: { path: { token } } })),
    onSuccess: (out) => {
      qc.setQueryData(key, out);
      // An accepted change moves the plan's visits and prices: Today and Jobs fetch them again.
      void qc.invalidateQueries({ queryKey: pKeys.all, predicate: (q) => q.queryKey[1] !== "plan-change" });
    },
    onError: () => void qc.invalidateQueries({ queryKey: key }),
  });

  if (isLoading) return <Loading />;
  if (error || !c) {
    return (
      <Notice title="We can't find that change">
        <p className="muted">{errorText(error, "The link may be mistyped.")}</p>
      </Notice>
    );
  }
  return (
    <>
      <div className="stack" style={css(6)}>
        <span className="kicker">
          {c.category_name} in {c.area}
        </span>
        <h1 className="h1">
          {c.customer_first_name} would like visits {c.to_frequency_label}
        </h1>
      </div>
      <div className="card stack" style={css(12)}>
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
          <p className="small">Please answer by {deadline(c.expires_at)}. If you don't, the plan stays as it is.</p>
          <ErrorNote error={answer.error} />
          <div className="stack" style={css(10)}>
            <Button variant="primary" size="lg" block disabled={answer.isPending} onClick={() => answer.mutate("accept")}>
              Accept {fmt(c.to_price_pence)} a visit
            </Button>
            <Button variant="ghost" size="lg" block disabled={answer.isPending} onClick={() => answer.mutate("decline")}>
              Keep it as it is
            </Button>
          </div>
        </>
      ) : (
        <div role="status">
          <Note tone={c.status === "accepted" ? "ok" : "soft"} icon={c.status === "accepted" ? <Check size={20} aria-hidden="true" /> : undefined}>
            {CLOSED[c.status]}
          </Note>
        </div>
      )}
    </>
  );
}
