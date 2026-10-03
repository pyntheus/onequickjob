import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { useEffect, type CSSProperties } from "react";
import { api, call } from "../../api/client";
import { Chip } from "../../shared/Chip";
import { FlowTop } from "../../shared/FlowTop";
import { fmt } from "../../shared/format";
import { Loading } from "../../app/Status";
import { errorText, useAreaOptions, type QuoteOut } from "../api";
import { FlowGuard } from "../components/FlowGuard";
import { quoteAnswers, type Days, type Time } from "../flow";
import { useQuoteStep } from "../useQuoteStep";

const g = (px: number) => ({ "--g": `${px}px` }) as CSSProperties;
const DAYS: [Days, string][] = [["any", "Any day"], ["weekdays", "Weekdays"], ["weekends", "Weekends"]];
const TIMES: [Time, string][] = [["morning", "Mornings"], ["afternoon", "Afternoons"], ["either", "Either"]];

function Split({ label, fee }: { label?: string; fee: QuoteOut["fee"] }) {
  return (
    <div className="stack" style={g(8)}>
      {label && <span className="small muted">{label}</span>}
      <div className="row between">
        <span className="row" style={g(8)}>
          <span className="dot dot-provider" aria-hidden="true" /> Goes to your provider
        </span>
        <b>{fmt(fee.provider_pence)}</b>
      </div>
      <div className="row between">
        <span className="row" style={g(8)}>
          <span className="dot dot-fee" aria-hidden="true" /> OneQuickJob fee ({fee.rate_percent}%)
        </span>
        <b>{fmt(fee.fee_pence)}</b>
      </div>
    </div>
  );
}

/** The size the customer chose, in their words (A6): never "measured". */
function SizeLine({ m }: { m: QuoteOut["measure"] }) {
  const { data: options } = useAreaOptions();
  if (!m) return null;
  const band = (options?.bands ?? []).find((b) => b.id === m.band);
  const adj = m.adjust === "smaller" ? ", a bit smaller" : m.adjust === "bigger" ? ", a bit bigger" : "";
  return (
    <p className="small">
      For the lawn size you chose: <b>{band ? `${band.label.toLowerCase()}${adj}` : "your lawn"}</b>, about{" "}
      {m.area_m2} m²{band ? ` (${band.comparison.charAt(0).toLowerCase() + band.comparison.slice(1)})` : ""}.
    </p>
  );
}

/** The guide price: price, first visit, range, duration, confidence, note, fee split, when. */
export default function Price() {
  const step = useQuoteStep("price");
  const { flow, update, cat, steps, go, back } = step;
  const body = cat
    ? {
        category_id: cat.id ?? "",
        answers: quoteAnswers(cat, flow),
        lawn: cat.measure ? { band: flow.lawn.band, adjust: flow.lawn.adjust } : null,
        address: flow.address,
      }
    : null;
  const q = useQuery({
    queryKey: ["c", "quote", body],
    queryFn: () => call(api.POST("/api/quotes", { body: body! })),
    enabled: !!body && !!flow.address && (!cat?.measure || !!flow.lawn.band),
    staleTime: Infinity,
    retry: false,
  });
  const quote = q.data;
  useEffect(() => {
    if (quote && flow.quoteId !== quote.id) update({ quoteId: quote.id });
  }, [quote, flow.quoteId, update]);

  return (
    <FlowGuard loading={step.loading} unknown={step.unknown} needsAddress={!flow.address}>
      <div className="c-flow">
        <FlowTop steps={steps} current="price" onBack={back} />
        {cat?.measure && !flow.lawn.band ? (
          <div className="card stack" style={g(12)}>
            <h1 className="h2">Tell us how big the lawn is</h1>
            <button type="button" className="btn btn-primary" onClick={() => go("size")}>
              Choose a size
            </button>
          </div>
        ) : q.isLoading ? (
          <Loading label="Working out your guide price…" />
        ) : q.isError || !quote ? (
          <div className="card stack" style={g(12)}>
            <h1 className="h2">We couldn't price that</h1>
            <p className="muted">{errorText(q.error)}</p>
            <button type="button" className="btn btn-primary" onClick={() => go("details")}>
              Check the answers
            </button>
          </div>
        ) : (
          <>
            <div className="card stack" style={g(16)}>
              <span className="kicker">Your guide price for {cat?.name.toLowerCase()}</span>
              <div className="row wrap" style={{ alignItems: "baseline", ...g(12) }}>
                <span className="price-big">{fmt(quote.result.price_pence)}</span>
                <span className="muted" style={{ fontSize: 18 }}>
                  {quote.result.unit}
                </span>
              </div>
              {quote.result.first_pence != null && (
                <div className="soft small">
                  <b>First visit {fmt(quote.result.first_pence)}.</b> {quote.result.first_reason} After that it's{" "}
                  {fmt(quote.result.price_pence)} {quote.result.unit}.
                </div>
              )}
              <SizeLine m={quote.measure} />
              <p className="muted">
                Jobs like yours usually go for {fmt(quote.result.low_pence)} to {fmt(quote.result.high_pence)}, and take
                about {quote.duration_text}.
              </p>
              {quote.result.note && (
                <p className="small row top" style={g(8)}>
                  <Info size={16} style={{ flex: "none", marginTop: 2 }} aria-hidden="true" /> {quote.result.note}
                </p>
              )}
              <div className="row" style={g(12)}>
                <span className="conf" aria-hidden="true">
                  {[1, 2, 3].map((n) => (
                    <i key={n} className={n <= quote.confidence.bars ? "on" : ""} />
                  ))}
                </span>
                <span className="small">
                  <b>{quote.confidence.label}.</b> <span className="muted">{quote.confidence.note}</span>
                </span>
              </div>
              <hr />
              <Split fee={quote.fee} label={quote.first_fee ? `Each ${quote.result.unit.replace(/^a /, "")} after the first` : undefined} />
              {quote.first_fee && <Split fee={quote.first_fee} label="The first visit" />}
            </div>

            <div className="card flat stack" style={g(14)}>
              <h2 className="h3">How the guide price works</h2>
              {[
                "Checked providers near you see your job and this price.",
                "They can accept it, or suggest a different price with a reason.",
                "If someone accepts the guide price, you're booked. If they suggest another price, you decide.",
              ].map((t, i) => (
                <div key={t} className="num-item">
                  <span className="n">{i + 1}</span>
                  <span>{t}</span>
                </div>
              ))}
            </div>

            <div className="stack" style={g(10)}>
              <span className="label" id="when-label">
                When suits you?
              </span>
              <div className="chips" role="group" aria-labelledby="when-label">
                {DAYS.map(([v, l]) => (
                  <Chip key={v} on={flow.when.days === v} onClick={() => update((f) => ({ when: { ...f.when, days: v } }))}>
                    {l}
                  </Chip>
                ))}
              </div>
              <div className="chips" role="group" aria-label="Time of day">
                {TIMES.map(([v, l]) => (
                  <Chip key={v} on={flow.when.time === v} onClick={() => update((f) => ({ when: { ...f.when, time: v } }))}>
                    {l}
                  </Chip>
                ))}
              </div>
            </div>

            <div className="stack" style={g(10)}>
              <button type="button" className="btn btn-cta btn-lg btn-block" onClick={() => go("contact")}>
                Request this job
              </button>
              <p className="xs muted center">Requesting is free. Nothing is charged until the work is done.</p>
            </div>
          </>
        )}
      </div>
    </FlowGuard>
  );
}
