/** Earnings: this week, the last eight weeks, payouts, and links to tax, the limit and your own
 * customers. Owned by L2. Lifted from the prototype's EarningsScreen. */
import { FileText, HeartHandshake, PiggyBank, Receipt, Wallet } from "lucide-react";
import { Loading } from "../../app/Status";
import { BarChart } from "../../shared/BarChart";
import { fmt } from "../../shared/format";
import { LinkRow } from "../../shared/LinkRow";
import { useEarnings } from "../api";
import { ErrorNote } from "../components";
import { css, dateText } from "../util";

export default function Earnings() {
  const { data: e, isLoading, error } = useEarnings();
  return (
    <>
      <h1 className="h1">Earnings</h1>
      {isLoading && <Loading />}
      {error && <ErrorNote error={error} />}
      {e && (
        <>
          <div className="card stack" style={css(10)}>
            <div className="row between top">
              <div className="stack" style={css(4)}>
                <span className="small muted">This week</span>
                <span className="big-num">{fmt(e.week_net_pence)}</span>
                <span className="xs muted">
                  from {e.week_jobs} {e.week_jobs === 1 ? "job" : "jobs"}, after our fee
                </span>
              </div>
              {e.next_payout_date && (
                <span className="badge ok">Next payout {dateText(e.next_payout_date, { weekday: "short", day: "numeric", month: "short" })}</span>
              )}
            </div>
            <BarChart
              data={e.weekly.map((w) => w.net_pence)}
              labels={e.weekly.map((w) => w.label)}
              label={`Your earnings for each of the last ${e.weekly.length} weeks, after our fee`}
            />
          </div>
          <div className="card flat" style={{ padding: "0 16px" }}>
            <LinkRow icon={Receipt} title="Tax and records" sub="Tax pack, mileage and key dates, kept for you" to="/p/tax" />
            <LinkRow
              icon={PiggyBank}
              title="Earnings limit"
              sub={
                e.limit.on
                  ? `${fmt(e.limit.remaining_pence ?? 0)} left of ${fmt(e.limit.amount_pence)} this ${e.limit.period}`
                  : "Off. Useful if you get means-tested benefits."
              }
              to="/p/limit"
            />
            <LinkRow
              icon={HeartHandshake}
              title="Your own customers"
              sub={e.own_customers_active ? `${e.own_customers_active} paying through us for a much smaller fee` : "Paid through us for a much smaller fee"}
              to="/p/own-customers"
            />
          </div>
          <h2 className="h3">Payouts</h2>
          {e.payouts.length === 0 ? (
            <p className="muted small">No payouts yet. They go to your bank every Friday.</p>
          ) : (
            <div className="card flat" style={{ padding: "4px 16px" }}>
              {e.payouts.map((p) => (
                <div key={p.payout_id} className="list-row">
                  <span className="cat-ico sm" aria-hidden="true">
                    <Wallet size={17} />
                  </span>
                  <div className="grow stack" style={css(0)}>
                    <b>{dateText(p.arrival_date, { weekday: "short", day: "numeric", month: "short" })}</b>
                    <span className="xs muted">To your bank ending {p.bank_last4 ?? e.bank_last4 ?? "••••"}</span>
                  </div>
                  <b>{fmt(p.amount_pence)}</b>
                </div>
              ))}
            </div>
          )}
          {e.pending_pence > 0 && (
            <p className="small muted">
              {fmt(e.pending_pence)} is on its way with the next payout.
            </p>
          )}
          <div className="card flat stack" style={css(8)}>
            <div className="row" style={css(10)}>
              <FileText size={20} aria-hidden="true" />
              <b>We tell HMRC what you earn</b>
            </div>
            <p className="small muted">
              The law requires platforms like OneQuickJob to report what sellers earn to HMRC. That's why we asked for your
              National Insurance number, and why we keep your records tidy for you.
            </p>
          </div>
        </>
      )}
    </>
  );
}
