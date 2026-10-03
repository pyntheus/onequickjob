import { MapPin } from "lucide-react";
import type { CSSProperties } from "react";
import { Chip } from "../../shared/Chip";
import { Choice } from "../../shared/Choice";
import { FlowTop } from "../../shared/FlowTop";
import { useAreaOptions } from "../api";
import { FlowGuard } from "../components/FlowGuard";
import type { Adjust } from "../flow";
import { useQuoteStep } from "../useQuoteStep";

const g = (px: number) => ({ "--g": `${px}px` }) as CSSProperties;

/**
 * The lawn size step (decisions.md A6): the customer chooses one of the manual size bands and
 * nudges it. Nothing here says we measured the garden: there is no survey data behind it.
 */
export default function Measure() {
  const step = useQuoteStep("size");
  const { flow, update, cat, steps, go, back } = step;
  const { data: options } = useAreaOptions();
  const band = (options?.bands ?? []).find((b) => b.id === flow.lawn.band) ?? null;

  return (
    <FlowGuard loading={step.loading} unknown={step.unknown} needsAddress={!flow.address}>
      <div className="c-flow">
        <FlowTop steps={steps} current="size" onBack={back} />
        <div className="stack" style={g(8)}>
          <span className="kicker">{cat?.name}</span>
          <h1 className="h1">How big is your lawn?</h1>
          <p className="muted">Pick the size that's closest. If you have a front and a back lawn, count them together.</p>
        </div>
        <div className="row small soft">
          <MapPin size={16} aria-hidden="true" />
          <span className="grow">{flow.address?.label || flow.addressText}</span>
          <button type="button" className="btn btn-link small" onClick={() => go("landing")}>
            Change
          </button>
        </div>
        <div className="field" role="group" aria-labelledby="size-label">
          <span className="label" id="size-label">
            Lawn size
          </span>
          <div className="stack" style={g(8)}>
            {(options?.bands ?? []).map((b) => (
              <Choice
                key={b.id}
                on={flow.lawn.band === b.id}
                onClick={() => update((f) => ({ lawn: { ...f.lawn, band: b.id }, quoteId: null }))}
                label={`${b.label}, about ${b.area_m2} m²`}
                hint={b.comparison}
              />
            ))}
          </div>
        </div>
        {band && (
          <div className="card stack" style={g(14)}>
            <div className="stack" style={g(4)}>
              <span className="small muted">You chose</span>
              <span className="h2">
                {band.label}: {band.comparison.charAt(0).toLowerCase() + band.comparison.slice(1)}
              </span>
            </div>
            <span className="label" id="adjust-label">
              Does that look about right?
            </span>
            <div className="chips" role="group" aria-labelledby="adjust-label">
              {(options?.adjustments ?? []).map((a) => (
                <Chip
                  key={a.id}
                  on={flow.lawn.adjust === a.id}
                  onClick={() => update((f) => ({ lawn: { ...f.lawn, adjust: a.id as Adjust }, quoteId: null }))}
                >
                  {a.label}
                </Chip>
              ))}
            </div>
            <p className="small muted">
              It's only used to estimate how long the job takes. {options?.tolerance_note}
            </p>
          </div>
        )}
        <button type="button" className="btn btn-cta btn-lg btn-block" disabled={!band} onClick={() => go("details")}>
          Continue
        </button>
        {!band && <p className="small center muted">Choose the size that's closest to continue.</p>}
      </div>
    </FlowGuard>
  );
}
