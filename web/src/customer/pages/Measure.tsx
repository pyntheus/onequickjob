import { Check, MapPin, Plus } from "lucide-react";
import { useEffect, useId, useMemo, useState, type CSSProperties } from "react";
import { ApiError } from "../../api/client";
import { Chip } from "../../shared/Chip";
import { FlowTop } from "../../shared/FlowTop";
import { NumberField } from "../../shared/NumberField";
import { tabId } from "../../shared/tab-id";
import { Tabs } from "../../shared/Tabs";
import { errorText, useAreaEstimate, useAreaOptions, type AreaBand, type AreaInput, type AreaOptions } from "../api";
import { LawnScene } from "../components/LawnDrawing";
import { sceneFactor } from "../components/lawn-scene";
import { FlowGuard } from "../components/FlowGuard";
import { EMPTY_LAWN, badSide, lawnFilled, lawnInput, lawnsOf, type Adjust, type LawnMethod, type LawnSides, type LawnState, type LengthUnit } from "../flow";
import { useQuoteStep } from "../useQuoteStep";

const g = (px: number) => ({ "--g": `${px}px` }) as CSSProperties;

const METHODS: Record<LawnMethod, string> = { band: "Pick a size", paced: "Pace it out", measured: "I know the size" };
const INTRO: Record<LawnMethod, string> = {
  band: "Pick the size that's closest. If you have a front and a back lawn, count them together.",
  paced: "Walk the length of your lawn in big strides, about a metre each, then the width.",
  measured: "Give the length and width in metres or feet. Decimals are fine.",
};
const UNITS: [LengthUnit, string][] = [["m", "Metres"], ["ft", "Feet"]];

/** The estimate's input, settled for a moment so typing "12" doesn't ask about "1" first. */
function useSettled(input: AreaInput | null, ms = 300): [AreaInput | null, boolean] {
  const key = input ? JSON.stringify(input) : "";
  const [settled, setSettled] = useState(key);
  useEffect(() => {
    const t = setTimeout(() => setSettled(key), ms);
    return () => clearTimeout(t);
  }, [key, ms]);
  const value = useMemo(() => (settled ? (JSON.parse(settled) as AreaInput) : null), [settled]);
  return [value, settled === key];
}

function BandCard({ b, on, onPick }: { b: AreaBand; on: boolean; onPick: () => void }) {
  const id = useId();
  return (
    <button
      type="button"
      className={"choice band-card lawn-cell" + (on ? " on" : "")}
      aria-pressed={on}
      aria-labelledby={`${id}-name`}
      aria-describedby={`${id}-words`}
      onClick={onPick}
    >
      <span className="row" style={g(10)}>
        <span className="tick">{on && <Check size={14} strokeWidth={3} aria-hidden="true" />}</span>
        <span className="band-name" id={`${id}-name`}>
          {b.label}
        </span>
      </span>
      <span className="band-words" id={`${id}-words`}>
        {b.comparison}
      </span>
      <LawnScene lawns={[{ length_m: b.length_m, width_m: b.width_m, text: `${b.width_m} × ${b.length_m} m` }]} house={b.house} />
    </button>
  );
}

function Bands({ options, lawn, setLawn }: { options: AreaOptions | undefined; lawn: LawnState; setLawn: (p: Partial<LawnState>) => void }) {
  const band = (options?.bands ?? []).find((b) => b.id === lawn.band) ?? null;
  return (
    <>
      <div className="lawn-grid" role="group" aria-label="Lawn size">
        {(options?.bands ?? []).map((b) => (
          <BandCard key={b.id} b={b} on={lawn.band === b.id} onPick={() => setLawn({ band: b.id })} />
        ))}
      </div>
      {band && (
        <div className="card stack" style={g(14)}>
          <div className="stack" style={g(4)}>
            <span className="small muted">You chose</span>
            <span className="h2">
              {band.label}, about {band.area_m2} m²
            </span>
          </div>
          <span className="label" id="adjust-label">
            Does that look about right?
          </span>
          <div className="chips" role="group" aria-labelledby="adjust-label">
            {(options?.adjustments ?? []).map((a) => (
              <Chip key={a.id} on={lawn.adjust === a.id} onClick={() => setLawn({ adjust: a.id as Adjust })}>
                {a.label}
              </Chip>
            ))}
          </div>
          <p className="small muted">It's only used to estimate how long the job takes. {options?.tolerance_note}</p>
        </div>
      )}
    </>
  );
}

/** Each lawn's two sides, with "Add another lawn" (up to the API's limit) and "Remove". */
function LawnList({
  lawn,
  lawns,
  maxLawns,
  maxSide,
  onChange,
  bad,
}: {
  lawn: LawnState;
  lawns: LawnSides[];
  maxLawns: number;
  maxSide: number;
  onChange: (lawns: LawnSides[]) => void;
  bad: { lawn?: number; side?: string; errorId?: string };
}) {
  const base = useId();
  const paced = lawn.method === "paced";
  const many = lawns.length > 1;
  const unitText = lawn.unit === "ft" ? "ft" : "m";
  const set = (i: number, side: keyof LawnSides, v: string) => onChange(lawns.map((l, j) => (j === i ? { ...l, [side]: v } : l)));
  const add = () => {
    onChange([...lawns, EMPTY_LAWN]);
    const first = `${base}-${lawns.length}-length`;
    requestAnimationFrame(() => document.getElementById(first)?.focus());
  };
  return (
    <div className="stack" style={g(14)}>
      {lawns.map((l, i) => {
        const legend = `${base}-${i}-legend`;
        return (
          <div key={i} className="lawn-sides" role={many ? "group" : undefined} aria-labelledby={many ? legend : undefined}>
            {many && (
              <div className="row between">
                <span className="label" id={legend}>
                  Lawn {i + 1}
                </span>
                <button type="button" className="btn btn-link small" onClick={() => onChange(lawns.filter((_, j) => j !== i))}>
                  Remove lawn {i + 1}
                </button>
              </div>
            )}
            <div className="sides">
              {(["length", "width"] as const).map((side) => {
                const id = `${base}-${i}-${side}`;
                const label = paced ? (side === "length" ? "Strides long" : "Strides wide") : side === "length" ? "Length" : "Width";
                const invalid = bad.lawn === i && bad.side === side;
                return (
                  <div className="field" key={side}>
                    <label className="label" htmlFor={id}>
                      {label}
                    </label>
                    <NumberField
                      id={id}
                      label={many ? `Lawn ${i + 1}, ${label.toLowerCase()}` : label}
                      value={l[side]}
                      onChange={(v) => set(i, side, v)}
                      min={1}
                      max={maxSide}
                      decimals={!paced}
                      unit={paced ? undefined : unitText}
                      invalid={invalid}
                      describedBy={invalid ? bad.errorId : undefined}
                    />
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
      {lawns.length < maxLawns && (
        <button type="button" className="btn btn-ghost add-lawn" onClick={add}>
          <Plus size={18} aria-hidden="true" /> Add another lawn
        </button>
      )}
    </div>
  );
}

/**
 * The lawn size step (decisions.md A6, A26): three ways to one area, all priced the same way.
 * Pick a size band (with the nudges), pace the lawn out, or give its length and width. The area
 * is always worked out by the API (POST /api/area/estimate), never here. Nothing here says we
 * measured the garden: there is no survey data behind it.
 */
export default function Measure() {
  const step = useQuoteStep("size");
  const { flow, update, cat, steps, go, back } = step;
  const { data: options } = useAreaOptions();
  const lawn = flow.lawn;
  const setLawn = (patch: Partial<LawnState>) => update((f) => ({ lawn: { ...f.lawn, ...patch }, quoteId: null }));
  const panelId = useId();
  const errorId = useId();
  const methods = (options?.methods ?? ["band"]) as LawnMethod[];
  const limits = options?.limits;

  const own = lawn.method !== "band";
  const filled = lawnFilled(lawn);
  // A side that isn't a number this way takes is never sent: it's pointed out here.
  const typo = badSide(lawn);
  const asking = own && filled && !typo;
  const [input, settled] = useSettled(asking ? lawnInput(lawn) : null);
  const est = useAreaEstimate(input);
  // The API's reason (naming the lawn and side), or a failure to reach it, with a retry.
  const apiError = est.error instanceof ApiError ? est.error : null;
  const failure = typo
    ? { message: typo.message, lawn: typo.lawn, side: typo.side, retry: false }
    : asking && est.isError && !est.isFetching
      ? {
          message: errorText(est.error, "We couldn't work out the size just now. Check your connection and try again."),
          lawn: typeof apiError?.extra?.lawn === "number" ? apiError.extra.lawn : undefined,
          side: typeof apiError?.extra?.side === "string" ? apiError.extra.side : undefined,
          retry: !apiError || apiError.status >= 500,
        }
      : null;
  const bad = { lawn: failure?.lawn, side: failure?.side, errorId };
  const result = asking && est.data ? est.data : null;
  const resultLawns = result?.measure.lawns ?? [];
  const ready = own ? asking && settled && est.isSuccess && !est.isFetching : !!lawn.band;
  const lawns = lawnsOf(lawn);
  const setLawns = (next: LawnSides[]) => setLawn(lawn.method === "measured" ? { measured: next } : { paced: next });

  return (
    <FlowGuard loading={step.loading} unknown={step.unknown} needsAddress={!flow.address}>
      <div className="c-flow wide">
        <FlowTop steps={steps} current="size" onBack={back} />
        <div className="stack" style={g(8)}>
          <span className="kicker">{cat?.name}</span>
          <h1 className="h1">How big is your lawn?</h1>
          <p className="muted">Choose whichever way is easiest.</p>
        </div>
        <div className="row small soft">
          <MapPin size={16} aria-hidden="true" />
          <span className="grow">{flow.address?.label || flow.addressText}</span>
          <button type="button" className="btn btn-link small" onClick={() => go("landing")}>
            Change
          </button>
        </div>
        {methods.length > 1 && (
          <Tabs
            items={methods.map((m) => ({ id: m, label: METHODS[m] }))}
            value={lawn.method}
            onChange={(m) => setLawn({ method: m })}
            label="How to size your lawn"
            panelId={panelId}
          />
        )}
        <div
          className="stack"
          style={g(18)}
          id={panelId}
          role={methods.length > 1 ? "tabpanel" : undefined}
          aria-labelledby={methods.length > 1 ? tabId(panelId, lawn.method) : undefined}
        >
          <p>{INTRO[lawn.method]}</p>
          {lawn.method === "band" ? (
            <Bands options={options} lawn={lawn} setLawn={setLawn} />
          ) : (
            <>
              {lawn.method === "measured" && (
                <div className="chips" role="group" aria-label="Units">
                  {UNITS.map(([u, label]) => (
                    <Chip key={u} on={lawn.unit === u} onClick={() => setLawn({ unit: u })}>
                      {label}
                    </Chip>
                  ))}
                </div>
              )}
              <LawnList
                lawn={lawn}
                lawns={lawns}
                maxLawns={limits?.max_lawns ?? 4}
                maxSide={limits?.side_max_m ?? 100}
                onChange={setLawns}
                bad={bad}
              />
              <div aria-live="polite" className="stack" style={g(12)}>
                {failure ? (
                  <div className="stack" style={g(10)}>
                    <p className="field-error" id={errorId}>
                      {failure.message}
                    </p>
                    {failure.retry && (
                      <button type="button" className="btn btn-ghost add-lawn" onClick={() => void est.refetch()}>
                        Try again
                      </button>
                    )}
                  </div>
                ) : result ? (
                  <div className="lawn-grid">
                    <div className="lawn-cell stack" style={g(10)}>
                      <span className="small muted">{resultLawns.length > 1 ? "Your lawns" : "Your lawn"}</span>
                      <span className="h2 lawn-result">{result.text}</span>
                      {result.lawn_texts.length > 1 && (
                        <ul className="lawn-list small">
                          {result.lawn_texts.map((t, i) => (
                            <li key={i}>
                              Lawn {i + 1}: {t}
                            </li>
                          ))}
                        </ul>
                      )}
                      <p className="small muted">It's only used to estimate how long the job takes. {options?.tolerance_note}</p>
                    </div>
                    <div className="lawn-cell stack" style={g(6)}>
                      <LawnScene
                        lawns={resultLawns}
                        names
                        label={`${resultLawns.length > 1 ? "Your lawns" : "Your lawn"} drawn to scale, with a car and a person`}
                      />
                      {sceneFactor(resultLawns) < 1 && (
                        <span className="xs muted">Drawn smaller to fit, with the car and person shrunk to match.</span>
                      )}
                    </div>
                  </div>
                ) : null}
              </div>
            </>
          )}
        </div>
        <button type="button" className="btn btn-cta btn-lg btn-block" disabled={!ready} onClick={() => go("details")}>
          Continue
        </button>
        {!ready && !failure && (
          <p className="small center muted">
            {lawn.method === "band"
              ? "Choose the size that's closest to continue."
              : filled
                ? "Working out the size…"
                : "Fill in the length and width to continue."}
          </p>
        )}
      </div>
    </FlowGuard>
  );
}
