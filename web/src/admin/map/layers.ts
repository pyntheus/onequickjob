/**
 * The admin map's own layers, drawn over the basemap from GET /api/admin/map. The API works
 * everything out (who's covered, the hexagon counts and their legend bands); these only draw it.
 *
 * Colours (validated with the dataviz palette checks, all pairs, on the village background):
 * open requests blue, booked visits green, completed jobs ochre. Each layer's hexagon shading
 * is a light-to-dark ramp of its own colour. Uncovered demand is the danger red with a "!"
 * (a status, never colour alone); providers are labelled white discs, greyed when suspended.
 */
import type { AddLayerObject, ExpressionSpecification } from "maplibre-gl";

export type JobLayer = "open" | "booked" | "completed";
export type Toggle = "open" | "uncovered" | "booked" | "completed" | "providers" | "hexes";

export const INK = "#18261e";
export const SURFACE = "#ffffff";
export const COLOURS: Record<JobLayer, string> = { open: "#2f6fb5", booked: "#2c7549", completed: "#c27a12" };
export const UNCOVERED = "#a2352a";
export const PROVIDER = { active: INK, signing_up: "#8f5b0c", suspended: "#98a39a" } as const;

/** Light to dark, five steps per job layer (ordinal checks pass: the lightest clears 2:1). */
export const RAMPS: Record<JobLayer, string[]> = {
  open: ["#8db0d6", "#5d8fc5", "#2f6fb5", "#22568e", "#163d68"],
  booked: ["#8bb39b", "#5a9371", "#2c7549", "#21583a", "#163a2b"],
  completed: ["#d4a560", "#c98a2e", "#b06d0f", "#8a550c", "#653c07"],
};
export const HEX_OPACITY = 0.55;

/** The ramp steps for a legend of `bands` bands: spread out, always ending on the darkest. */
export function rampFor(layer: JobLayer, bands: number): string[] {
  const ramp = RAMPS[layer];
  const pick: Record<number, number[]> = { 1: [2], 2: [1, 4], 3: [0, 2, 4], 4: [0, 1, 3, 4], 5: [0, 1, 2, 3, 4] };
  return (pick[Math.min(Math.max(bands, 1), 5)] ?? []).map((i) => ramp[i]);
}

export const SOURCES = ["hexes", "reach", "completed", "booked", "open", "providers"] as const;
export type SourceId = (typeof SOURCES)[number];
export const CLUSTERED: SourceId[] = ["completed", "booked", "open"];

/** Map layer ids under each toggle; uncovered demand is drawn as markers (buttons), not a layer. */
export const LAYER_IDS: Record<Exclude<Toggle, "uncovered">, string[]> = {
  hexes: ["hexes-fill", "hexes-line"],
  providers: ["reach-fill", "reach-line", "reach-dash", "providers-disc", "providers-label"],
  completed: ["completed-clusters", "completed-count", "completed-points"],
  booked: ["booked-clusters", "booked-count", "booked-points"],
  open: ["open-clusters", "open-count", "open-points"],
};
/** Points that open the details panel when clicked. */
export const CLICKABLE: Record<string, "request" | "job" | "provider"> = {
  "open-points": "request",
  "booked-points": "job",
  "completed-points": "job",
  "providers-disc": "provider",
};

const covers: ExpressionSpecification = ["==", ["get", "covers"], true];
const status = (s: string): ExpressionSpecification => ["==", ["get", "status"], s];

function points(layer: JobLayer): AddLayerObject[] {
  const colour = COLOURS[layer];
  const waiting = layer === "open";
  return [
    {
      id: `${layer}-clusters`,
      type: "circle",
      source: layer,
      filter: ["has", "point_count"],
      paint: {
        "circle-color": colour,
        "circle-radius": ["step", ["get", "point_count"], 13, 5, 16, 15, 20],
        "circle-stroke-color": waiting ? ["case", [">", ["get", "waiting"], 0], INK, SURFACE] : SURFACE,
        "circle-stroke-width": waiting ? ["case", [">", ["get", "waiting"], 0], 3, 2] : 2,
      },
    },
    {
      id: `${layer}-count`,
      type: "symbol",
      source: layer,
      filter: ["has", "point_count"],
      layout: {
        "text-field": ["get", "point_count_abbreviated"],
        "text-font": ["Noto Sans Medium"],
        "text-size": 12,
        "text-allow-overlap": true,
      },
      paint: { "text-color": SURFACE },
    },
    {
      id: `${layer}-points`,
      type: "circle",
      source: layer,
      filter: ["!", ["has", "point_count"]],
      paint: {
        "circle-color": colour,
        // Open over an hour with nobody taking it: bigger, with an ink ring.
        "circle-radius": waiting ? ["case", ["get", "waiting"], 9, 7] : 7,
        "circle-stroke-color": waiting ? ["case", ["get", "waiting"], INK, SURFACE] : SURFACE,
        "circle-stroke-width": waiting ? ["case", ["get", "waiting"], 3, 2] : 2,
      },
    },
  ];
}

export function hexColour(layer: JobLayer, bands: number): ExpressionSpecification | string {
  const ramp = rampFor(layer, bands);
  if (ramp.length < 2) return ramp[0] ?? COLOURS[layer];
  const match: unknown[] = ["match", ["get", "level"]];
  ramp.forEach((c, level) => match.push(level, c));
  match.push(ramp[ramp.length - 1]);
  return match as ExpressionSpecification;
}

/** Every data layer, bottom to top: providers under the job markers, so a job in a provider's
 * village stays clickable. */
export function dataLayers(): AddLayerObject[] {
  return [
    {
      id: "hexes-fill",
      type: "fill",
      source: "hexes",
      paint: { "fill-color": COLOURS.open, "fill-opacity": HEX_OPACITY },
    },
    {
      id: "hexes-line",
      type: "line",
      source: "hexes",
      paint: { "line-color": SURFACE, "line-width": 1, "line-opacity": 0.8 },
    },
    {
      id: "reach-fill",
      type: "fill",
      source: "reach",
      filter: covers,
      // Faint: radii overlap a lot, and the fills add up.
      paint: { "fill-color": "#1e4b38", "fill-opacity": 0.035 },
    },
    {
      id: "reach-line",
      type: "line",
      source: "reach",
      filter: covers,
      paint: { "line-color": "#1e4b38", "line-width": 1.25, "line-opacity": 0.45 },
    },
    {
      // Signing up or suspended: their radius doesn't cover anyone yet, so dashed, unfilled.
      id: "reach-dash",
      type: "line",
      source: "reach",
      filter: ["!", covers],
      paint: {
        "line-color": ["case", status("signing_up"), PROVIDER.signing_up, PROVIDER.suspended],
        "line-width": 1.5,
        "line-dasharray": ["literal", [2, 2]],
      },
    },
    {
      id: "providers-disc",
      type: "circle",
      source: "providers",
      paint: {
        "circle-radius": 12,
        "circle-color": ["case", status("suspended"), "#e7ebe1", status("signing_up"), "#faeed5", SURFACE],
        "circle-stroke-color": [
          "case",
          status("suspended"),
          PROVIDER.suspended,
          status("signing_up"),
          PROVIDER.signing_up,
          PROVIDER.active,
        ],
        "circle-stroke-width": 2,
      },
    },
    {
      id: "providers-label",
      type: "symbol",
      source: "providers",
      layout: {
        "text-field": ["get", "initials"],
        "text-font": ["Noto Sans Medium"],
        "text-size": 11,
        "text-allow-overlap": true,
        "text-ignore-placement": true,
      },
      paint: { "text-color": ["case", status("suspended"), "#56645b", INK] },
    },
    ...points("completed"),
    ...points("booked"),
    ...points("open"),
  ];
}
