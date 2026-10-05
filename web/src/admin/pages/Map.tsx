/**
 * The admin map (decisions.md A30 to A35): where jobs are concentrated and, above all, where demand
 * is outrunning provider coverage, so the team knows where to recruit. Each layer toggles on and
 * off and only what's on is fetched; the date range applies to completed jobs.
 */
import { MapPin } from "lucide-react";
import { useState, type ReactNode } from "react";
import { fmt } from "../../shared/format";
import { useMapData, type MapData, type MapLayerName, type MapQuery } from "../api";
import { AdminHeader } from "../components";
import { MapCanvas, type LngLat, type Selected } from "../map/MapCanvas";
import { MapPanel } from "../map/MapPanel";
import { COLOURS, HEX_OPACITY, PROVIDER, rampFor, UNCOVERED, type JobLayer, type Toggle } from "../map/layers";
import { errorText, gap } from "../util";

const DAY = 86_400_000;

/** Today in London, "2026-10-04", and n days before a date. */
function londonToday(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Europe/London" });
}
function daysBefore(iso: string, n: number): string {
  return new Date(Date.parse(iso + "T12:00:00Z") - n * DAY).toISOString().slice(0, 10);
}

function plural(n: number, one: string, many = one + "s") {
  return `${n} ${n === 1 ? one : many}`;
}

const LAYERS: MapLayerName[] = ["open", "uncovered", "booked", "completed", "providers"];
const SHADE_LABEL: Record<JobLayer, string> = {
  open: "Open requests",
  booked: "Booked visits",
  completed: "Completed jobs",
};

export function MapPage() {
  const [today] = useState(londonToday);
  const [on, setOn] = useState<Record<Toggle, boolean>>({
    open: true,
    uncovered: true,
    booked: false,
    completed: false,
    providers: true,
    hexes: true,
  });
  const [shadeBy, setShadeBy] = useState<JobLayer>("open");
  const [range, setRange] = useState({ from: daysBefore(today, 29), to: today });
  // What's selected, by identity: its details always come from the latest data (A30).
  const [picked, setPicked] = useState<Picked | null>(null);
  const [focus, setFocus] = useState<{ at: LngLat } | null>(null);

  const query: MapQuery = {
    layers: LAYERS.filter((l) => on[l]),
    shade: on.hexes ? shadeBy : "none",
    from: range.from,
    to: range.to,
  };
  const { data, error, isFetching } = useMapData(query);
  const flip = (t: Toggle) => {
    const next = { ...on, [t]: !on[t] };
    setOn(next);
    // The panel closes with the layer its marker is on.
    if (picked && !shownOn(picked, next)) setPicked(null);
  };
  // Gone from the latest data (booked meanwhile, out of the dates chosen...): no panel.
  const panel = picked && shownOn(picked, on) ? resolve(picked, data) : null;

  const uncovered = data?.uncovered?.features ?? [];
  const count = (t: Toggle): string | null => {
    if (!data || !on[t]) return null;
    if (t === "open") return data.open ? String(data.open.features.length) : null;
    if (t === "uncovered") return data.uncovered ? String(data.uncovered.features.length) : null;
    if (t === "booked") return data.booked ? plural(data.booked.visits, "visit") : null;
    if (t === "completed") return data.completed ? plural(data.completed.visits, "visit") : null;
    if (t === "providers") return data.providers ? String(data.providers.features.length) : null;
    return null;
  };
  const legend = data?.hexes?.shade_by === shadeBy ? data.hexes.legend : [];
  const ramp = rampFor(shadeBy, legend.length);

  return (
    <>
      <AdminHeader
        title="Map"
        sub="Where the jobs are, where providers reach, and where demand is outrunning them."
        right={
          data && (
            <span className="small muted" role="status">
              {isFetching ? "Updating…" : `Updated ${new Date(data.generated_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/London" })}`}
            </span>
          )
        }
      />
      <div className="map-layout">
        <div className="map-stage">
          <MapCanvas
            data={data}
            visible={on}
            shade={on.hexes ? shadeBy : null}
            selected={panel}
            onSelect={(s) => setPicked(s && pickOf(s))}
            focus={focus}
          />
          {panel && <MapPanel selected={panel} onClose={() => setPicked(null)} />}
        </div>

        <aside className="map-side stack" style={gap("14px")}>
          <fieldset className="card map-controls">
            <legend className="h3">Layers</legend>
            <Layer t="open" on={on.open} flip={flip} label="Open requests" count={count("open")}>
              <span aria-hidden="true" className="map-dot" style={{ background: COLOURS.open }} />
              <span className="xs muted">
                <span aria-hidden="true" className="map-dot sm ringed" style={{ background: COLOURS.open }} /> ringed: open over an hour,
                nobody's taken it
              </span>
            </Layer>
            <Layer t="uncovered" on={on.uncovered} flip={flip} label="Uncovered demand" count={count("uncovered")}>
              <span aria-hidden="true" className="map-dot bang" style={{ background: UNCOVERED }}>
                !
              </span>
              <span className="xs muted">Open requests no active provider in reach does that job for</span>
            </Layer>
            <Layer t="booked" on={on.booked} flip={flip} label="Booked visits" count={count("booked")}>
              <span aria-hidden="true" className="map-dot" style={{ background: COLOURS.booked }} />
              <span className="xs muted">Visits still to come, one marker per booking</span>
            </Layer>
            <Layer t="completed" on={on.completed} flip={flip} label="Completed jobs" count={count("completed")}>
              <span aria-hidden="true" className="map-dot" style={{ background: COLOURS.completed }} />
              <span className="xs muted">Visits finished in the dates below</span>
            </Layer>
            <div className="map-dates row wrap" style={gap("8px")}>
              <label className="stack small" style={gap("2px")}>
                From
                <input
                  type="date"
                  className="input"
                  value={range.from}
                  max={range.to}
                  onChange={(e) => e.target.value && setRange((r) => ({ ...r, from: e.target.value }))}
                />
              </label>
              <label className="stack small" style={gap("2px")}>
                To
                <input
                  type="date"
                  className="input"
                  value={range.to}
                  min={range.from}
                  max={today}
                  onChange={(e) => e.target.value && setRange((r) => ({ ...r, to: e.target.value }))}
                />
              </label>
            </div>
            <Layer t="providers" on={on.providers} flip={flip} label="Providers" count={count("providers")}>
              <span aria-hidden="true" className="map-dot provider" style={{ borderColor: PROVIDER.active }} />
              <span className="xs muted">
                At their home postcode, with their travel radius.{" "}
                <span aria-hidden="true" className="map-dot sm provider signing" /> signing up,{" "}
                <span aria-hidden="true" className="map-dot sm provider suspended" /> suspended,{" "}
                <span aria-hidden="true" className="map-dot xs paused" /> payouts paused (still cover)
              </span>
            </Layer>
            <Layer t="hexes" on={on.hexes} flip={flip} label="Concentration" count={null}>
              <span aria-hidden="true" className="map-dot hex" style={{ background: ramp[ramp.length - 1] ?? COLOURS[shadeBy] }} />
              <span className="xs muted">Hexagons about 1 km across, darker where there are more</span>
            </Layer>
            <div className="map-shade" role="radiogroup" aria-label="Concentration counts">
              {(Object.keys(SHADE_LABEL) as JobLayer[]).map((l) => (
                <label key={l} className="row small" style={gap("6px")}>
                  <input
                    type="radio"
                    name="shade"
                    value={l}
                    checked={shadeBy === l}
                    disabled={!on.hexes}
                    onChange={() => setShadeBy(l)}
                  />
                  {SHADE_LABEL[l]}
                </label>
              ))}
            </div>
            {on.hexes && (
              <div className="map-legend" aria-label={`Concentration of ${SHADE_LABEL[shadeBy].toLowerCase()}`}>
                {legend.length === 0 ? (
                  <span className="xs muted">Nothing to count with these settings.</span>
                ) : (
                  <ul>
                    {legend.map((b, i) => (
                      <li key={b.level}>
                        <span aria-hidden="true" className="map-swatch" style={{ background: ramp[i], opacity: HEX_OPACITY + 0.2 }} />
                        {b.label}
                      </li>
                    ))}
                  </ul>
                )}
                <span className="xs muted">
                  {SHADE_LABEL[shadeBy]} per hexagon
                  {shadeBy === "booked" || shadeBy === "completed" ? " (visits)" : ""}
                </span>
              </div>
            )}
            {error ? (
              <p className="small field-error" role="alert">
                {errorText(error)}
              </p>
            ) : null}
          </fieldset>

          {on.uncovered && (
            <section className="card stack map-recruit" style={gap("10px")} aria-labelledby="uncovered-h">
              <h2 className="h3" id="uncovered-h">
                Where to recruit
              </h2>
              {uncovered.length === 0 ? (
                <p className="small muted">Every open request has an active provider in reach who does that job.</p>
              ) : (
                <>
                  <p className="small muted">
                    {plural(uncovered.length, "open request")} that no active provider in reach does the job for.
                  </p>
                  <ul className="map-list">
                    {uncovered.map((f) => {
                      const p = f.properties;
                      const at = f.geometry.coordinates as LngLat;
                      return (
                        <li key={p.request_id}>
                          <div className="stack" style={gap("0px")}>
                            <b className="small">
                              {p.category_name} in {p.area}, {p.district}
                            </b>
                            <span className="xs muted">
                              {p.ref}, open {p.age_text}, {fmt(p.guide_pence)}
                            </span>
                          </div>
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            aria-label={`Show ${p.ref} on the map`}
                            onClick={() => {
                              setFocus({ at });
                              setPicked({ kind: "request", ref: p.ref, uncovered: p.uncovered });
                            }}
                          >
                            <MapPin size={15} aria-hidden="true" /> Show
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </>
              )}
            </section>
          )}
        </aside>
      </div>
    </>
  );
}

type Picked =
  | { kind: "request"; ref: string; uncovered: boolean }
  | { kind: "job"; layer: "booked" | "completed"; id: string }
  | { kind: "provider"; id: string };

function pickOf(s: Selected): Picked {
  if (s.kind === "request") return { kind: "request", ref: s.pin.ref, uncovered: s.pin.uncovered };
  if (s.kind === "job") return { kind: "job", layer: s.layer, id: s.pin.booking_id };
  return { kind: "provider", id: s.pin.provider_id };
}

function shownOn(p: Picked, on: Record<Toggle, boolean>): boolean {
  if (p.kind === "request") return on.open || (p.uncovered && on.uncovered);
  if (p.kind === "job") return on[p.layer];
  return on.providers;
}

/** The picked marker as the latest data has it, or null if it isn't there any more. */
function resolve(p: Picked, data: MapData | undefined): Selected | null {
  if (!data) return null;
  if (p.kind === "request") {
    const f = [...(data.open?.features ?? []), ...(data.uncovered?.features ?? [])].find((g) => g.properties.ref === p.ref);
    return f ? { kind: "request", pin: f.properties, at: f.geometry.coordinates as LngLat } : null;
  }
  if (p.kind === "job") {
    const f = data[p.layer]?.features.find((g) => g.properties.booking_id === p.id);
    return f ? { kind: "job", layer: p.layer, pin: f.properties, at: f.geometry.coordinates as LngLat } : null;
  }
  const f = data.providers?.features.find((g) => g.properties.provider_id === p.id);
  return f ? { kind: "provider", pin: f.properties, at: f.geometry.coordinates as LngLat } : null;
}

function Layer({
  t,
  on,
  flip,
  label,
  count,
  children,
}: {
  t: Toggle;
  on: boolean;
  flip: (t: Toggle) => void;
  label: string;
  count: string | null;
  children: [ReactNode, ReactNode];
}) {
  return (
    <div className="map-layer">
      <label className="row" style={gap("10px")}>
        <input type="checkbox" checked={on} onChange={() => flip(t)} />
        {children[0]}
        <span className="map-layer-name">{label}</span>
        {count !== null && <span className="badge">{count}</span>}
      </label>
      <div className="map-layer-note">{children[1]}</div>
    </div>
  );
}

export default MapPage;
