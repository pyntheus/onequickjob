/** Tax and records: turnover against fees against what reached the bank, the trading allowance
 * against actual costs, mileage logged for you, receipts, key dates and the tax pack. Owned by L2.
 * Lifted from the prototype's TaxScreen. Every figure comes from the API (ledger, mileage, expenses). */
import { useMutation } from "@tanstack/react-query";
import { Camera, Car, Download, Printer, Trash } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api, call } from "../../api/client";
import { Loading } from "../../app/Status";
import { Button } from "../../shared/Button";
import { Chip } from "../../shared/Chip";
import { TextField } from "../../shared/Field";
import { fmt } from "../../shared/format";
import { useToast } from "../../shared/toast-context";
import { useInvalidateProvider, useTax } from "../api";
import { BackLink, ErrorNote, UploadButton } from "../components";
import { css, dateText, londonToday, parsePounds } from "../util";

const CATEGORIES = [
  { id: "kit", label: "Kit" },
  { id: "supplies", label: "Supplies" },
  { id: "fuel", label: "Fuel" },
  { id: "other", label: "Other" },
] as const;

function ReceiptForm({ onDone }: { onDone: () => void }) {
  const notify = useToast();
  const [fileId, setFileId] = useState<string | null>(null);
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [day, setDay] = useState(londonToday());
  const [category, setCategory] = useState<(typeof CATEGORIES)[number]["id"]>("kit");
  const pence = parsePounds(amount);
  const valid = description.trim().length > 0 && pence !== null && pence > 0;
  const add = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/p/expenses", {
          body: { local_date: day, description: description.trim(), amount_pence: pence ?? 0, category, receipt_file_id: fileId },
        }),
      ),
    onSuccess: () => {
      notify("Receipt added to your records");
      setFileId(null);
      setDescription("");
      setAmount("");
      onDone();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (valid) add.mutate();
  };
  return (
    <form className="stack" style={css(12)} onSubmit={submit}>
      <UploadButton
        kind="receipt"
        accept="image/*,application/pdf"
        capture="environment"
        label={fileId ? "Photo added. Take another?" : "Snap a receipt"}
        onUploaded={(id) => setFileId(id)}
      />
      <TextField label="What was it?" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={120} placeholder="Mower service" />
      <div className="grid2 narrow-stack">
        <TextField label="Amount" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="£" />
        <TextField label="Date" type="date" value={day} max={londonToday()} onChange={(e) => setDay(e.target.value)} />
      </div>
      <div className="chips" role="group" aria-label="Kind of cost">
        {CATEGORIES.map((c) => (
          <Chip key={c.id} on={category === c.id} onClick={() => setCategory(c.id)}>
            {c.label}
          </Chip>
        ))}
      </div>
      <ErrorNote error={add.error} />
      <Button type="submit" variant="primary" block disabled={!valid || add.isPending}>
        Add to my records
      </Button>
      <p className="xs muted">We don't read the receipt for you yet: type in the amount as it's shown.</p>
    </form>
  );
}

export default function Tax() {
  const [year, setYear] = useState<string | null>(null);
  const [allTrips, setAllTrips] = useState(false);
  const [adding, setAdding] = useState(false);
  const { data: t, isLoading, error } = useTax(year);
  const refresh = useInvalidateProvider();
  const remove = useMutation({
    mutationFn: (id: string) => call(api.DELETE("/api/p/expenses/{expense_id}", { params: { path: { expense_id: id } } })),
    onSuccess: () => void refresh(),
  });
  const q = t ? `?tax_year=${t.tax_year}` : "";
  return (
    <>
      <BackLink to="/p/earnings">Earnings</BackLink>
      <div className="stack" style={css(6)}>
        <h1 className="h1">Tax and records</h1>
        {t && (
          <p className="muted">
            Kept for you as you work. {t.tax_year === t.tax_years[0] ? "This" : "That"} tax year started on {dateText(t.starts_on, { day: "numeric", month: "long", year: "numeric" })}.
          </p>
        )}
      </div>
      {t && t.tax_years.length > 1 && (
        <div className="chips" role="group" aria-label="Tax year">
          {t.tax_years.map((y) => (
            <Chip key={y} on={y === t.tax_year} onClick={() => setYear(y)}>
              {y}
            </Chip>
          ))}
        </div>
      )}
      {isLoading && <Loading />}
      {error && <ErrorNote error={error} />}
      {t && (
        <>
          <div className="card stack" style={css(10)}>
            <div className="row between">
              <span>Customers paid you</span>
              <b>{fmt(t.turnover_pence)}</b>
            </div>
            <div className="row between">
              <span>OneQuickJob fees</span>
              <b>−{fmt(t.fees_pence)}</b>
            </div>
            <hr />
            <div className="row between">
              <span>Reached your bank</span>
              <b>{fmt(t.received_pence)}</b>
            </div>
            <p className="xs muted">
              For tax, your turnover is what customers paid, not what reached your bank. Our fee counts as a business cost.
            </p>
          </div>

          <div className="card stack" style={css(12)}>
            <h2 className="h3">Allowance or costs?</h2>
            <p className="small muted">
              You can take the £1,000 trading allowance or claim your actual costs, but not both. We compare them for you.
            </p>
            <div className={"cmp" + (t.better === "allowance" ? " win" : "")}>
              <div className="stack" style={css(0)}>
                <b>Trading allowance</b>
                <span className="xs muted">{fmt(t.allowance_pence)} off your turnover</span>
              </div>
              <div className="stack" style={{ ...css(0), textAlign: "right" }}>
                <span className="xs muted">Taxable profit</span>
                <b>{fmt(t.allowance_profit_pence)}</b>
              </div>
            </div>
            <div className={"cmp" + (t.better === "costs" ? " win" : "")}>
              <div className="stack" style={css(0)}>
                <b>Actual costs</b>
                <span className="xs muted">Fees, mileage and kit: {fmt(t.costs_pence)}</span>
              </div>
              <div className="stack" style={{ ...css(0), textAlign: "right" }}>
                <span className="xs muted">Taxable profit</span>
                <b>{fmt(t.costs_profit_pence)}</b>
              </div>
            </div>
            <div className="soft small">
              <b>{t.better === "allowance" ? "The allowance" : "Claiming your costs"} works out better so far,</b> by{" "}
              {fmt(t.difference_pence)} of profit. Your costs grow as you work, so it can change.
            </div>
          </div>

          <div className="card stack" style={css(10)}>
            <div className="row between">
              <h2 className="h3">Mileage</h2>
              <span className="badge ok">
                <Car size={13} aria-hidden="true" /> Logged for you
              </span>
            </div>
            <div className="row between wrap" style={{ alignItems: "baseline" }}>
              <span className="big-num">{t.mileage_miles} miles</span>
              <span className="small muted">
                worth {fmt(t.mileage_pence)} at {t.mileage_rate_text}
              </span>
            </div>
            <div>
              {(allTrips ? t.trips : t.trips.slice(0, 3)).map((d) => (
                <div key={d.local_date} className="list-row">
                  <div className="grow stack" style={css(0)}>
                    <b className="small">{dateText(d.local_date, { weekday: "short", day: "numeric", month: "short" })}</b>
                    <span className="xs muted">{d.route_text}</span>
                  </div>
                  <span className="small">{d.miles} mi</span>
                </div>
              ))}
            </div>
            {t.trips.length > 3 && (
              <Button variant="link" onClick={() => setAllTrips((v) => !v)}>
                {allTrips ? "Show fewer" : `Show all ${t.trips.length} days`}
              </Button>
            )}
            <p className="xs muted">
              Worked out from your jobs, starting and ending at home: straight-line distance plus a quarter for the roads. It
              only counts if you claim actual costs.
            </p>
          </div>

          <div className="card flat stack" style={css(8)}>
            <div className="row between">
              <h2 className="h3">Kit and supplies</h2>
              <b>{fmt(t.expenses_pence)}</b>
            </div>
            {t.expenses.map((x) => (
              <div key={x.id} className="row between small" style={css(8)}>
                <span className="grow">
                  {x.description}
                  {x.receipt_url && (
                    <>
                      {" "}
                      <a href={x.receipt_url} target="_blank" rel="noreferrer">
                        (receipt)
                      </a>
                    </>
                  )}
                </span>
                <span>{fmt(x.amount_pence)}</span>
                <button
                  type="button"
                  className="icon-btn"
                  aria-label={`Remove ${x.description}`}
                  onClick={() => remove.mutate(x.id)}
                  disabled={remove.isPending}
                >
                  <Trash size={17} aria-hidden="true" />
                </button>
              </div>
            ))}
            {adding ? (
              <ReceiptForm onDone={() => { setAdding(false); void refresh(); }} />
            ) : (
              <Button variant="ghost" block onClick={() => setAdding(true)}>
                <Camera size={17} aria-hidden="true" /> Snap a receipt
              </Button>
            )}
          </div>

          <div className="card flat stack" style={css(10)}>
            <h2 className="h3">Key dates</h2>
            {t.key_dates.map((k) => (
              <div key={k.on} className="row top" style={css(12)}>
                <DateChipMonth iso={k.on} />
                <span className="small">{k.text}</span>
              </div>
            ))}
            <p className="xs muted">We'll text you a month before each date. {t.mtd_note}</p>
          </div>

          <a className="btn btn-cta btn-lg btn-block" href={`/api/p/tax/pack.csv${q}`} download>
            <Download size={18} aria-hidden="true" /> Download your tax pack
          </a>
          <a className="btn btn-ghost btn-block" href={`/api/p/tax/pack.html${q}`} target="_blank" rel="noreferrer">
            <Printer size={18} aria-hidden="true" /> Print it, or save it as a PDF
          </a>
          <p className="xs muted">
            Laid out in the order of HMRC's self-employment pages. The trading allowance covers all your self-employed income,
            not just OneQuickJob. We're not tax advisers.
          </p>
        </>
      )}
    </>
  );
}

function DateChipMonth({ iso }: { iso: string }) {
  return (
    <div className="date-chip" aria-hidden="true">
      <span>{dateText(iso, { month: "short" })}</span>
      <b>{Number(iso.slice(8, 10))}</b>
    </div>
  );
}
