/**
 * The map itself: MapLibre GL over the self-hosted basemap (basemap.ts), with the API's layers
 * drawn on top (layers.ts). Uncovered demand is drawn as buttons on the map, so each one can be
 * reached by keyboard and named for screen readers; the page lists them too.
 */
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import {
  addProtocol,
  Map as MapLibreMap,
  Marker,
  NavigationControl,
  setWorkerUrl,
  type GeoJSONSource,
  type MapMouseEvent,
} from "maplibre-gl";
import type { FeatureCollection, Point } from "geojson";
import { Protocol } from "pmtiles";
import { useEffect, useRef, useState } from "react";
import type { JobPin, MapData, ProviderPin, RequestPin } from "../api";
import { basemapStyle, EXTRACT_BOUNDS, START_VIEW } from "./basemap";
import { CLICKABLE, CLUSTERED, dataLayers, hexColour, LAYER_IDS, SOURCES, type JobLayer, type SourceId, type Toggle } from "./layers";

export type LngLat = [number, number];
export type Selected =
  | { kind: "request"; pin: RequestPin; at: LngLat }
  | { kind: "job"; layer: "booked" | "completed"; pin: JobPin; at: LngLat }
  | { kind: "provider"; pin: ProviderPin; at: LngLat };

type Collection = { type: "FeatureCollection"; features: { geometry: unknown; properties: unknown }[] };
const EMPTY: Collection = { type: "FeatureCollection", features: [] };

let setUp = false;
/** Once per page: MapLibre's worker from our own bundle, and PMTiles read by HTTP range. */
function setUpMapLibre() {
  if (setUp) return;
  setWorkerUrl(workerUrl);
  addProtocol("pmtiles", new Protocol().tile);
  setUp = true;
}

function collection(data: MapData | undefined, id: SourceId): Collection {
  if (!data) return EMPTY;
  if (id === "hexes") return (data.hexes?.cells as Collection | undefined) ?? EMPTY;
  return (data[id] as Collection | null | undefined) ?? EMPTY;
}

export function MapCanvas({
  data,
  visible,
  shade,
  selected,
  onSelect,
  focus,
}: {
  data: MapData | undefined;
  visible: Record<Toggle, boolean>;
  shade: JobLayer | null;
  selected: Selected | null;
  onSelect: (s: Selected | null) => void;
  /** Fly here (a new object each time). */
  focus: { at: LngLat } | null;
}) {
  const box = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markers = useRef(new Map<string, Marker>());
  const latest = useRef({ data, onSelect });
  const [loaded, setLoaded] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [shown, setShown] = useState<Toggle[]>([]);

  useEffect(() => {
    latest.current = { data, onSelect };
  });

  // The map, once.
  useEffect(() => {
    if (!box.current) return;
    setUpMapLibre();
    let map: MapLibreMap;
    try {
      map = new MapLibreMap({
        container: box.current,
        style: basemapStyle(window.location.origin),
        center: START_VIEW.center,
        zoom: START_VIEW.zoom,
        minZoom: 8.5,
        maxZoom: 17,
        maxBounds: [
          [EXTRACT_BOUNDS[0][0] - 0.15, EXTRACT_BOUNDS[0][1] - 0.08],
          [EXTRACT_BOUNDS[1][0] + 0.15, EXTRACT_BOUNDS[1][1] + 0.08],
        ],
        attributionControl: { compact: false },
        dragRotate: false,
        pitchWithRotate: false,
      });
    } catch {
      // Said after this effect, not during it.
      void Promise.resolve().then(() => setProblem("This browser can't draw the map: WebGL seems to be switched off."));
      return;
    }
    map.touchZoomRotate.disableRotation();
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");
    map.on("error", (e) => {
      const source = (e as { sourceId?: string }).sourceId;
      if (source === "protomaps") setProblem("The streets aren't showing: the basemap hasn't been built here (make basemap).");
    });
    map.on("load", () => {
      for (const id of SOURCES) {
        map.addSource(id, {
          type: "geojson",
          data: EMPTY as FeatureCollection,
          ...(CLUSTERED.includes(id)
            ? {
                cluster: true,
                clusterRadius: 36,
                clusterMaxZoom: 13,
                ...(id === "open" ? { clusterProperties: { waiting: ["+", ["case", ["get", "waiting"], 1, 0]] } } : {}),
              }
            : {}),
        });
      }
      for (const layer of dataLayers()) map.addLayer(layer);
      setLoaded(true);
    });
    const hitLayers = [...Object.keys(CLICKABLE), ...CLUSTERED.map((l) => `${l}-clusters`)];
    map.on("click", async (e: MapMouseEvent) => {
      const present = hitLayers.filter((id) => map.getLayer(id));
      const [hit] = present.length ? map.queryRenderedFeatures(e.point, { layers: present }) : [];
      if (!hit) {
        latest.current.onSelect(null);
        return;
      }
      const at = (hit.geometry as Point).coordinates as LngLat;
      if (hit.layer.id.endsWith("-clusters")) {
        const source = map.getSource<GeoJSONSource>(hit.layer.source);
        const zoom = await source?.getClusterExpansionZoom(Number(hit.properties.cluster_id));
        map.easeTo({ center: at, zoom: zoom ?? map.getZoom() + 2 });
        return;
      }
      latest.current.onSelect(pick(latest.current.data, hit.layer.id, hit.properties, at));
    });
    for (const id of hitLayers) {
      map.on("mouseenter", id, () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", id, () => (map.getCanvas().style.cursor = ""));
    }
    mapRef.current = map;
    const placed = markers.current;
    return () => {
      placed.clear(); // map.remove() takes their elements with it
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // The data, and on its first arrival a view that takes in every request and provider.
  const fitted = useRef(false);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded) return;
    for (const id of SOURCES) map.getSource<GeoJSONSource>(id)?.setData(collection(data, id) as FeatureCollection);
    if (shade) map.setPaintProperty("hexes-fill", "fill-color", hexColour(shade, data?.hexes?.legend.length ?? 0));
    if (data && !fitted.current) {
      const bounds = extent(data);
      if (bounds) map.fitBounds(bounds, { padding: 36, maxZoom: 12.5, duration: 0 });
      fitted.current = true;
    }
  }, [data, loaded, shade]);

  // Which layers show.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded) return;
    for (const [toggle, ids] of Object.entries(LAYER_IDS) as [Exclude<Toggle, "uncovered">, string[]][]) {
      const on = visible[toggle] && (toggle !== "hexes" || shade !== null);
      for (const id of ids) map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    }
    const now = (Object.keys(LAYER_IDS) as Exclude<Toggle, "uncovered">[]).filter(
      (t) => map.getLayoutProperty(LAYER_IDS[t][0], "visibility") === "visible",
    );
    setShown(visible.uncovered ? [...now, "uncovered"] : now);
  }, [visible, loaded, shade]);

  // Uncovered demand: a button on the map for each. A button stays while its request is still
  // uncovered (refreshes and selections don't rebuild it), so keyboard focus stays on it.
  useEffect(() => {
    const map = mapRef.current;
    const wanted = map && loaded && visible.uncovered ? (data?.uncovered?.features ?? []) : [];
    const refs = new Set(wanted.map((f) => f.properties.ref));
    for (const [ref, marker] of markers.current) {
      if (refs.has(ref)) continue;
      marker.remove();
      markers.current.delete(ref);
    }
    if (!map) return;
    for (const f of wanted) {
      const ref = f.properties.ref;
      const at = f.geometry.coordinates as LngLat;
      const label = `Uncovered: ${f.properties.category_name} in ${f.properties.area}, ${f.properties.district} (${ref})`;
      const kept = markers.current.get(ref);
      if (kept) {
        kept.setLngLat(at);
        kept.getElement().setAttribute("aria-label", label);
        continue;
      }
      const el = document.createElement("button");
      el.type = "button";
      el.className = "map-uncovered";
      el.textContent = "!";
      el.setAttribute("aria-label", label);
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const now = latest.current.data?.uncovered?.features.find((g) => g.properties.ref === ref);
        if (now) latest.current.onSelect({ kind: "request", pin: now.properties, at: now.geometry.coordinates as LngLat });
      });
      markers.current.set(ref, new Marker({ element: el }).setLngLat(at).addTo(map));
    }
  }, [data, loaded, visible.uncovered]);

  // The selected one stands out.
  useEffect(() => {
    const ref = selected?.kind === "request" ? selected.pin.ref : null;
    for (const [r, marker] of markers.current) marker.getElement().classList.toggle("on", r === ref);
  }, [selected, data, loaded, visible.uncovered]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !focus) return;
    map.flyTo({ center: focus.at, zoom: Math.max(map.getZoom(), 12.5), essential: true });
  }, [focus]);

  return (
    <div className="map-canvas-wrap">
      <div
        ref={box}
        className="map-canvas"
        role="region"
        aria-label="Map of requests, jobs and providers"
        data-ready={loaded && !!data ? "true" : "false"}
        data-shown={shown.join(" ")}
      />
      {problem && (
        <p className="map-problem" role="status">
          {problem}
        </p>
      )}
    </div>
  );
}

/** South-west and north-east corners of every point in the data, or null if there are none. */
function extent(data: MapData): [LngLat, LngLat] | null {
  const points = [
    ...(data.open?.features ?? []),
    ...(data.uncovered?.features ?? []),
    ...(data.booked?.features ?? []),
    ...(data.completed?.features ?? []),
    ...(data.providers?.features ?? []),
  ].map((f) => f.geometry.coordinates);
  if (!points.length) return null;
  const lngs = points.map((p) => p[0]);
  const lats = points.map((p) => p[1]);
  return [
    [Math.min(...lngs), Math.min(...lats)],
    [Math.max(...lngs), Math.max(...lats)],
  ];
}

/** The clicked point's full pin, from the data (MapLibre flattens feature properties). */
function pick(data: MapData | undefined, layerId: string, props: Record<string, unknown>, at: LngLat): Selected | null {
  const kind = CLICKABLE[layerId];
  if (kind === "request") {
    const pin = data?.open?.features.find((f) => f.properties.request_id === props.request_id)?.properties;
    return pin ? { kind, pin, at } : null;
  }
  if (kind === "job") {
    const layer = layerId.startsWith("booked") ? "booked" : "completed";
    const pin = data?.[layer]?.features.find((f) => f.properties.booking_id === props.booking_id)?.properties;
    return pin ? { kind, layer, pin, at } : null;
  }
  if (kind === "provider") {
    const pin = data?.providers?.features.find((f) => f.properties.provider_id === props.provider_id)?.properties;
    return pin ? { kind, pin, at } : null;
  }
  return null;
}
