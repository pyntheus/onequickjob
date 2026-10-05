/**
 * The admin map's basemap, served entirely from our own server (decisions.md A31): a Protomaps
 * extract read by range from /basemap/oqj.pmtiles, with its label fonts and sprites beside it
 * (make basemap; Caddy serves the folder behind the site's basic auth). The style is built here,
 * in our own bundle, from Protomaps' layer definitions in the village colours. No API keys, no
 * third-party tile servers: nothing on the map is fetched from anywhere but this origin.
 */
import { layers, namedFlavor, type Flavor } from "@protomaps/basemaps";
import type { LayerSpecification, StyleSpecification } from "maplibre-gl";

export const BASEMAP_PATH = "/basemap";
/** Required by the OpenStreetMap licence (ODbL), shown on the map at every size. */
export const ATTRIBUTION =
  '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a>';
/** The area make basemap extracts (scripts/basemap.sh), so the map stays where there are tiles. */
export const EXTRACT_BOUNDS: [[number, number], [number, number]] = [
  [-0.97, 51.5],
  [-0.53, 51.78],
];
export const START_VIEW = { center: [-0.76, 51.645] as [number, number], zoom: 10.4 };

/** Protomaps' light flavour in the village theme's colours (styles/tokens.css): greens for
 * gardens and woods, warm cream for the main roads, ink and muted labels. */
const VILLAGE: Partial<Flavor> = {
  background: "#e7ebe1",
  earth: "#f2f4ee",
  park_a: "#dde8d3",
  park_b: "#c9dcbc",
  wood_a: "#d9e5cf",
  wood_b: "#c3d8b5",
  scrub_a: "#e1e9d7",
  scrub_b: "#d0dfc3",
  hospital: "#ece4dc",
  industrial: "#e4e7e0",
  school: "#ebe7dc",
  pedestrian: "#ece9df",
  sand: "#ece6d4",
  beach: "#efe8d2",
  aerodrome: "#e3e7df",
  zoo: "#dbe6d6",
  military: "#e3e5df",
  water: "#c3d7de",
  buildings: "#e2e7db",
  pier: "#e2e7db",
  other: "#ffffff",
  minor_service: "#ffffff",
  minor_a: "#ffffff",
  minor_b: "#ffffff",
  link: "#fcefcf",
  major: "#fcefcf",
  highway: "#f8e2a9",
  minor_service_casing: "#d3dacb",
  minor_casing: "#d3dacb",
  link_casing: "#e4d3a6",
  major_casing_early: "#e4d3a6",
  major_casing_late: "#e4d3a6",
  highway_casing_early: "#d9bf7d",
  highway_casing_late: "#d9bf7d",
  railway: "#a3ada5",
  boundaries: "#9aa59c",
  roads_label_minor: "#56645b",
  roads_label_minor_halo: "#ffffff",
  roads_label_major: "#56645b",
  roads_label_major_halo: "#ffffff",
  subplace_label: "#56645b",
  subplace_label_halo: "#f2f4ee",
  city_label: "#18261e",
  city_label_halo: "#f2f4ee",
  state_label: "#7d8a80",
  state_label_halo: "#f2f4ee",
  country_label: "#7d8a80",
  address_label: "#56645b",
  address_label_halo: "#ffffff",
  landcover: {
    barren: "rgba(240, 236, 224, 1)",
    farmland: "rgba(234, 239, 225, 1)",
    forest: "rgba(207, 223, 197, 1)",
    glacier: "rgba(255, 255, 255, 1)",
    grassland: "rgba(223, 233, 212, 1)",
    scrub: "rgba(228, 234, 216, 1)",
    urban_area: "rgba(232, 234, 227, 1)",
  },
};

/** Points of interest crowd an operations map; places, roads and water stay. */
const LEFT_OUT = new Set(["pois", "address_label"]);

export function basemapStyle(origin: string): StyleSpecification {
  const base = `${origin}${BASEMAP_PATH}`;
  const flavor: Flavor = { ...namedFlavor("light"), ...VILLAGE };
  return {
    version: 8,
    glyphs: `${base}/fonts/{fontstack}/{range}.pbf`,
    sprite: `${base}/sprites/v4/light`,
    sources: {
      protomaps: { type: "vector", url: `pmtiles://${base}/oqj.pmtiles`, attribution: ATTRIBUTION },
    },
    layers: (layers("protomaps", flavor, { lang: "en" }) as LayerSpecification[]).filter((l) => !LEFT_OUT.has(l.id)),
  };
}
