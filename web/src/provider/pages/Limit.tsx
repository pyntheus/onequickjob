/** Earnings limit: on or off, the benefits guidance, week or month, amount and progress. Owned by
 * L2. Lifted from the prototype's LimitScreen.
 *
 * The benefits question only suggests a limit. Its answer stays in this screen's memory: it is
 * never sent to the API, stored, or kept in the browser. Only the limit is saved. */
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";
import { api, call } from "../../api/client";
import { Loading } from "../../app/Status";
import { Button } from "../../shared/Button";
import { Chip } from "../../shared/Chip";
import { fmt } from "../../shared/format";
import { Stepper } from "../../shared/Stepper";
import { Toggle } from "../../shared/Toggle";
import { useToast } from "../../shared/toast-context";
import { useInvalidateProvider, useLimit, useLimitPreview, type LimitView } from "../api";
import { BackLink, ErrorNote } from "../components";
import { css, dateText } from "../util";

type Benefit = "state" | "pc" | "uc" | "none";
const BENEFITS: [Benefit, string][] = [
  ["state", "State Pension"],
  ["pc", "Pension Credit"],
  ["uc", "Universal Credit"],
  ["none", "None of these"],
];
const INFO: Record<Benefit, [string, "week" | "month" | null]> = {
  state: ["Your State Pension isn't means-tested, so earning more doesn't reduce it. The money may still be taxable.", null],
  pc: [
    "Pension Credit is worked out weekly. Earnings above a small amount (often £5 a week for a single person) reduce it pound for pound. Speak to the Pension Service or Citizens Advice before choosing a limit.",
    "week",
  ],
  uc: [
    "Universal Credit goes down by 55p for every £1 you earn, after any work allowance you have. It's assessed monthly, so a monthly limit fits best.",
    "month",
  ],
  none: ["You may not need a limit, but some people like one to keep jobs to pocket money.", null],
};

function LimitForm({ saved }: { saved: LimitView }) {
  const navigate = useNavigate();
  const notify = useToast();
  const refresh = useInvalidateProvider();
  const [on, setOn] = useState(saved.on);
  const [period, setPeriod] = useState<"week" | "month">(saved.period);
  const [pounds, setPounds] = useState(Math.round(saved.amount_pence / 100));
  const [benefit, setBenefit] = useState<Benefit | null>(null); // never sent, never stored
  const preview = useLimitPreview(period, pounds * 100, on);
  const save = useMutation({
    mutationFn: () => call(api.PUT("/api/p/limit", { body: { on, period, amount_pence: pounds * 100 } })),
    onSuccess: () => {
      void refresh();
      notify(on ? `Limit saved: ${fmt(pounds * 100)} a ${period}` : "Earnings limit turned off");
      navigate("/p");
    },
  });
  const pick = (b: Benefit) => {
    setBenefit(b);
    const suggested = INFO[b][1];
    if (suggested) setPeriod(suggested);
  };
  const p = preview.data;
  return (
    <>
      <div className="card flat" style={{ padding: "0 16px" }}>
        <Toggle on={on} onChange={setOn} label="Use an earnings limit" />
      </div>
      {on && (
        <>
          <div className="stack" style={css(10)}>
            <span className="label" id="benefits-label">
              Do you get any of these?
            </span>
            <span className="hint">Only so we can suggest a sensible limit. We don't save your answer, just the limit.</span>
            <div className="chips" role="group" aria-labelledby="benefits-label">
              {BENEFITS.map(([k, l]) => (
                <Chip key={k} on={benefit === k} onClick={() => pick(k)}>
                  {l}
                </Chip>
              ))}
            </div>
            {benefit && <div className="soft small">{INFO[benefit][0]}</div>}
          </div>
          <div className="stack" style={css(10)}>
            <span className="label" id="period-label">
              Limit per
            </span>
            <div className="chips" role="group" aria-labelledby="period-label">
              <Chip on={period === "week"} onClick={() => setPeriod("week")}>
                Week
              </Chip>
              <Chip on={period === "month"} onClick={() => setPeriod("month")}>
                Month
              </Chip>
            </div>
          </div>
          <div className="stack" style={css(10)}>
            <span className="label">Your limit</span>
            <Stepper
              value={pounds}
              onChange={setPounds}
              min={5}
              max={5000}
              step={pounds < 100 ? 5 : 25}
              format={(v) => fmt(v * 100)}
              label="Your limit"
            />
            <span className="hint">Counts what you receive after our fee.</span>
          </div>
          {p && (
            <div className="card stack" style={css(10)} aria-live="polite">
              <div className="row between">
                <span className="small">This {period} so far</span>
                <b>
                  {fmt(p.earned_pence)} of {fmt(p.amount_pence)}
                </b>
              </div>
              <div className="progress" aria-hidden="true">
                <i style={{ width: `${p.used_percent}%`, background: p.reached ? "var(--accent)" : undefined }} />
              </div>
              <span className="small muted">
                {p.reached
                  ? `You've reached it. New job alerts are paused until ${dateText(p.resumes_on)}.`
                  : `${fmt(p.remaining_pence ?? 0)} left. Jobs that would take you over are marked, so you can choose.`}
              </span>
            </div>
          )}
          <p className="xs muted">
            This helps you stay within a number you've chosen. It isn't benefits advice. For that, try Citizens Advice or
            the Turn2us benefits calculator.
          </p>
        </>
      )}
      <ErrorNote error={save.error} />
      <Button variant="primary" size="lg" block disabled={save.isPending} onClick={() => save.mutate()}>
        Save
      </Button>
    </>
  );
}

export default function Limit() {
  const { data: saved, isLoading, error } = useLimit();
  return (
    <>
      <BackLink to="/p/earnings">Earnings</BackLink>
      <div className="stack" style={css(6)}>
        <h1 className="h1">Earnings limit</h1>
        <p className="muted">
          Choose a limit and we'll stop offering you new jobs once you reach it. Jobs you've already accepted always go ahead.
        </p>
      </div>
      {isLoading && <Loading />}
      {error && <ErrorNote error={error} />}
      {saved && <LimitForm saved={saved} />}
    </>
  );
}
