/** A change of how often a plan runs: the link in the provider's text. Owned by L2 (moved here
 * from the customer web, which now redirects /plan-change/:token to this page).
 *
 * The single-use token in the address is the authority, as for an invite: no sign-in is needed
 * (the layout lets this page through). A platform plan's new price is the API's, re-priced by the
 * pricing engine (A10): this page only shows it. An own customer's plan is priced by the provider
 * (A22): they name a price here and the customer approves it; what they'd keep comes from the API. */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { useState } from "react";
import { useParams } from "react-router";
import { api, call } from "../../api/client";
import { Loading, Notice } from "../../app/Status";
import { Button } from "../../shared/Button";
import { fmt } from "../../shared/format";
import { Stepper } from "../../shared/Stepper";
import { pKeys } from "../api";
import { ErrorNote, Note } from "../components";
import { css, errorText } from "../util";

const CLOSED: Record<string, string> = {
  accepted: "You accepted this change. The plan has been updated.",
  declined: "You declined this change. The plan stays as it was.",
  lapsed: "This change lapsed after 48 hours without an answer, so the plan stays as it was.",
  withdrawn: "The customer withdrew or replaced this change.",
};

type View = NonNullable<ReturnType<typeof useChange>["data"]>;

function useChange(token: string) {
  return useQuery({
    queryKey: [...pKeys.all, "plan-change", token],
    queryFn: () => call(api.GET("/api/c/plan-changes/{token}", { params: { path: { token } } })),
    retry: false,
  });
}

function closedText(c: View): string {
  if (c.kind === "provider_price" && c.status === "accepted")
    return `${c.customer_first_name} agreed ${fmt(c.to_price_pence ?? 0)} a visit. The plan has been updated.`;
  if (c.status === "declined" && c.declined_by === "customer")
    return `${c.customer_first_name} would rather keep the plan as it is.`;
  return CLOSED[c.status];
}

/** A22: the provider names their price for an own customer's new frequency. */
function NamePrice({ token, c, onDone }: { token: string; c: View; onDone: (out: View) => void }) {
  const [pounds, setPounds] = useState(Math.round(c.from_price_pence / 100));
  const keep = useQuery({
    queryKey: [...pKeys.all, "plan-change-preview", token, pounds],
    queryFn: () =>
      call(api.GET("/api/c/plan-changes/{token}/preview", { params: { path: { token }, query: { price_pence: pounds * 100 } } })),
    placeholderData: keepPreviousData,
  });
  const send = useMutation({
    mutationFn: () => call(api.POST("/api/c/plan-changes/{token}/price", { params: { path: { token } }, body: { price_pence: pounds * 100 } })),
    onSuccess: onDone,
  });
  return (
    <div className="stack" style={css(10)}>
      <span className="label">Your price a visit, {c.to_frequency_label}</span>
      <div className="row wrap between" style={css(12)}>
        <Stepper
          value={pounds}
          onChange={setPounds}
          min={c.price_min_pence / 100}
          max={c.price_max_pence / 100}
          step={1}
          format={(v) => fmt(v * 100)}
          label="Your price a visit"
        />
        <div className="stack" style={{ ...css(0), textAlign: "right" }} aria-live="polite">
          <span className="xs muted">You'd keep</span>
          <b>{keep.data && keep.data.price_pence === pounds * 100 ? fmt(keep.data.provider_pence) : "…"}</b>
        </div>
      </div>
      <span className="hint">{c.customer_first_name} is your own customer, so the price is yours to set. They'll be asked to agree it.</span>
      <ErrorNote error={send.error} />
      <Button variant="primary" size="lg" block disabled={send.isPending} onClick={() => send.mutate()}>
        Send {fmt(pounds * 100)} a visit to {c.customer_first_name}
      </Button>
    </div>
  );
}

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
  const { data: c, isLoading, error } = useChange(token);
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

  const priced = (out: View) => qc.setQueryData(key, out);
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
            {c.to_frequency_label}
            {c.to_price_pence != null && (
              <>
                , <b>{fmt(c.to_price_pence)} a visit</b>
              </>
            )}
          </dd>
          {c.provider_pence != null && (
            <>
              <dt>You'd get</dt>
              <dd>{fmt(c.provider_pence)} a visit, after the OneQuickJob fee</dd>
            </>
          )}
        </dl>
        <p className="small muted">
          {c.kind === "provider_price"
            ? "Your next visit stays as it is. Nothing changes until you've both agreed the price."
            : "The new price comes from our pricing at the new frequency, keeping any price you agreed in proportion. Your next visit stays as it is."}
        </p>
      </div>
      {c.status === "pending" && c.kind === "provider_price" && c.awaiting === "provider" ? (
        <>
          <p className="small">Please answer by {deadline(c.expires_at)}. If you don't, the plan stays as it is.</p>
          <NamePrice token={token} c={c} onDone={priced} />
          <ErrorNote error={answer.error} />
          <Button variant="ghost" size="lg" block disabled={answer.isPending} onClick={() => answer.mutate("decline")}>
            Keep it as it is
          </Button>
        </>
      ) : c.status === "pending" && c.awaiting === "customer" ? (
        <div role="status">
          <Note tone="soft">
            You've asked {fmt(c.to_price_pence ?? 0)} a visit. {c.customer_first_name} has until {deadline(c.expires_at)} to agree
            it; until then the plan stays as it is.
          </Note>
        </div>
      ) : c.status === "pending" ? (
        <>
          <p className="small">Please answer by {deadline(c.expires_at)}. If you don't, the plan stays as it is.</p>
          <ErrorNote error={answer.error} />
          <div className="stack" style={css(10)}>
            <Button variant="primary" size="lg" block disabled={answer.isPending} onClick={() => answer.mutate("accept")}>
              Accept {fmt(c.to_price_pence ?? 0)} a visit
            </Button>
            <Button variant="ghost" size="lg" block disabled={answer.isPending} onClick={() => answer.mutate("decline")}>
              Keep it as it is
            </Button>
          </div>
        </>
      ) : (
        <div role="status">
          <Note tone={c.status === "accepted" ? "ok" : "soft"} icon={c.status === "accepted" ? <Check size={20} aria-hidden="true" /> : undefined}>
            {closedText(c)}
          </Note>
        </div>
      )}
    </>
  );
}
