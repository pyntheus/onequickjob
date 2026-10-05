/** The admin map page (decisions.md A30 to A35): it renders, asks only for the layers switched
 * on, toggles each layer on the map, and a click on uncovered demand opens its details with a
 * link to the request on Overview. MapLibre needs WebGL, which jsdom lacks, so it's replaced by a
 * stand-in that records what the page asks of it. */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "../test/utils";
import { basemapStyle } from "./map/basemap";
import { dataLayers, LAYER_IDS } from "./map/layers";
import MapPage from "./pages/Map";

// vi.mock factories are hoisted above the imports, so the stand-ins are too.
const { FakeMap, FakeMarker, maps } = vi.hoisted(() => {
  const maps: FakeMap[] = [];
  type Handler = (...args: unknown[]) => void;

  class FakeMap {
    container: HTMLElement;
    options: Record<string, unknown>;
    sources: Record<string, { data: { features: unknown[] }; options: unknown }> = {};
    layers: Record<string, string> = {};
    paint: Record<string, unknown> = {};
    handlers: Record<string, Handler[]> = {};
    touchZoomRotate = { disableRotation: () => {} };
    constructor(options: { container: HTMLElement } & Record<string, unknown>) {
      this.container = options.container;
      this.options = options;
      maps.push(this);
      setTimeout(() => this.handlers.load?.forEach((h) => h()), 0);
    }
    on(event: string, layerOrHandler: string | Handler, handler?: Handler) {
      const key = typeof layerOrHandler === "string" ? `${event}:${layerOrHandler}` : event;
      (this.handlers[key] ??= []).push(typeof layerOrHandler === "string" ? handler! : layerOrHandler);
      return this;
    }
    addControl() {}
    addSource(id: string, options: { data: { features: unknown[] } }) {
      this.sources[id] = { data: options.data, options };
    }
    addLayer(layer: { id: string; layout?: { visibility?: string } }) {
      this.layers[layer.id] = layer.layout?.visibility ?? "visible";
    }
    getLayer(id: string) {
      return id in this.layers ? { id } : undefined;
    }
    getSource(id: string) {
      const s = this.sources[id];
      return s && { setData: (data: { features: unknown[] }) => (s.data = data), getClusterExpansionZoom: async () => 14 };
    }
    setPaintProperty(id: string, name: string, value: unknown) {
      this.paint[`${id}:${name}`] = value;
    }
    setLayoutProperty(id: string, name: string, value: string) {
      if (name === "visibility") this.layers[id] = value;
    }
    getLayoutProperty(id: string, name: string) {
      return name === "visibility" ? this.layers[id] : undefined;
    }
    hits: unknown[] = [];
    queryRenderedFeatures() {
      return this.hits;
    }
    /** A click on the canvas, landing on whatever `hits` holds. */
    async click() {
      for (const h of this.handlers.click ?? []) await h({ point: { x: 10, y: 10 } });
    }
    getCanvas() {
      return { style: {} };
    }
    getZoom() {
      return 11;
    }
    /** Screen position: 1 px per 0.0001°, so markers 0.003° apart are 30 px apart. */
    scale = 10_000;
    project([lng, lat]: [number, number]) {
      return { x: lng * this.scale, y: -lat * this.scale };
    }
    fitted: unknown[] = [];
    /** Zoom in by `times`, as a wheel or the + button would. */
    zoomIn(times: number) {
      this.scale *= times;
      this.handlers.zoomend?.forEach((h) => h());
    }
    fitBounds(bounds: unknown) {
      this.fitted.push(bounds);
    }
    flyTo() {}
    easeTo() {}
    remove() {}
    visible(id: string) {
      return this.layers[id] === "visible";
    }
  }

  class FakeMarker {
    element: HTMLElement;
    constructor({ element }: { element: HTMLElement }) {
      this.element = element;
    }
    setLngLat() {
      return this;
    }
    getElement() {
      return this.element;
    }
    addTo(map: FakeMap) {
      map.container.appendChild(this.element);
      return this;
    }
    remove() {
      this.element.remove();
    }
  }
  return { FakeMap, FakeMarker, maps };
});
type FakeMap = InstanceType<typeof FakeMap>;

vi.mock("maplibre-gl", () => ({
  Map: FakeMap,
  Marker: FakeMarker,
  NavigationControl: class {},
  addProtocol: () => {},
  setWorkerUrl: () => {},
}));
vi.mock("pmtiles", () => ({ Protocol: class { tile = () => {}; } }));
vi.mock("maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url", () => ({ default: "/assets/worker.js" }));

const point = (lng: number, lat: number) => ({ type: "Point", coordinates: [lng, lat] });
const request = (ref: string, over: Record<string, unknown> = {}) => ({
  type: "Feature",
  id: `id-${ref}`,
  geometry: point(-0.834, 51.7243),
  properties: {
    request_id: `id-${ref}`,
    ref,
    category_id: "mowing",
    category_name: "Lawn mowing",
    area: "Princes Risborough",
    district: "HP27",
    created_at: "2026-10-03T19:00:00Z",
    age_text: "26 hours",
    guide_pence: 2800,
    waiting: true,
    uncovered: true,
    in_reach_doing_it: 0,
    cover: false,
    awaiting_customer: false,
    nearby: [
      { provider_id: "p-kasia", short: "Kasia N.", miles: 3.2, jobs: ["Regular cleaning", "Deep clean"], does_it: false, payouts_paused: false },
    ],
    in_reach: 1,
    ...over,
  },
});
const covered = request("R-2292", {
  area: "Hazlemere",
  district: "HP15",
  age_text: "4 minutes",
  guide_pence: 3100,
  waiting: false,
  uncovered: false,
  in_reach: 8,
  in_reach_doing_it: 4,
});
const provider = {
  type: "Feature",
  id: "p-dave",
  geometry: point(-0.6935, 51.6455),
  properties: {
    provider_id: "p-dave",
    short: "Dave H.",
    initials: "DH",
    status: "active",
    area: "Hazlemere",
    district: "HP15",
    travel_radius_miles: 4,
    placed_at: "postcode",
    covers: true,
    payouts_paused: false,
    status_reason: null,
    jobs: ["Lawn mowing", "Hedge trimming"],
  },
};
const booking = {
  type: "Feature",
  id: "b1",
  geometry: point(-0.7044, 51.6669),
  properties: {
    booking_id: "b1",
    booking_ref: "B-0002",
    category_id: "mowing",
    category_name: "Lawn mowing",
    area: "Holmer Green",
    district: "HP15",
    provider_id: "p-dave",
    provider_short: "Dave H.",
    own_customer: false,
    visits: 3,
    visit_date: "2026-10-06",
    price_pence: 2800,
  },
};
const fc = (features: unknown[], extra: Record<string, unknown> = {}) => ({ type: "FeatureCollection", features, ...extra });
const hexes = (shade: string) => ({
  shade_by: shade,
  resolution: 8,
  total: 2,
  max: 1,
  legend: [{ level: 0, min: 1, max: 1, label: "1" }],
  cells: fc([]),
});

let calls: URLSearchParams[] = [];
/** What the stand-in API answers next: changes made "meanwhile" by others. */
const server = {
  gone: new Set<string>(),
  r2284: {} as Record<string, unknown>,
  daveStatus: "active",
  covered: false,
  neighbour: false, // a second uncovered request 0.0005° from R-2284
};
function serveMap() {
  calls = [];
  return mockApi({
    "GET /api/admin/map": (url) => {
      calls.push(url.searchParams);
      const layers = url.searchParams.getAll("layers");
      const shade = url.searchParams.get("shade") ?? "open";
      const unc = request("R-2284", server.r2284);
      const next = { ...request("R-2295", { category_name: "Window cleaning" }), geometry: point(-0.8335, 51.7245) };
      const uncs = server.neighbour ? [unc, next] : [unc];
      const here = (ref: string) => !server.gone.has(ref);
      const dave = {
        ...provider,
        properties: {
          ...provider.properties,
          status: server.daveStatus,
          covers: ["active", "payouts_paused"].includes(server.daveStatus),
          payouts_paused: server.daveStatus === "payouts_paused",
          status_reason: server.daveStatus === "payouts_paused" ? "Tax details missing" : null,
        },
      };
      const done = { ...booking, id: "b2", properties: { ...booking.properties, booking_id: "b2", visits: 2, visit_date: "2026-09-20" } };
      return {
        generated_at: "2026-10-04T21:45:00Z",
        from_date: url.searchParams.get("from"),
        to_date: url.searchParams.get("to"),
        waiting_after_minutes: 60,
        open: layers.includes("open") ? fc([covered, ...uncs].filter((f) => here(f.properties.ref))) : null,
        uncovered: layers.includes("uncovered") ? fc(uncs.filter((f) => here(f.properties.ref))) : null,
        booked: layers.includes("booked")
          ? fc([server.covered ? { ...booking, properties: { ...booking.properties, provider_id: "p-mike", provider_short: "Mike R.", covering_for: "Dave H." } } : booking], { visits: 3 })
          : null,
        completed: layers.includes("completed") ? fc(here("b2") ? [done] : [], { visits: here("b2") ? 2 : 0 }) : null,
        providers: layers.includes("providers") ? fc([dave]) : null,
        reach: layers.includes("providers") ? fc([]) : null,
        hexes: shade === "none" ? null : hexes(shade),
      };
    },
  });
}

const last = () => calls[calls.length - 1];
const map = () => maps[maps.length - 1];

beforeEach(() => {
  maps.length = 0;
  server.gone.clear();
  server.r2284 = {};
  server.daveStatus = "active";
  server.covered = false;
  server.neighbour = false;
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("the admin map", () => {
  it("asks for the layers that are on and draws them", async () => {
    serveMap();
    renderWithProviders(<MapPage />, { path: "/admin/map" });
    expect(screen.getByRole("heading", { level: 1, name: "Map" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("region", { name: /Map of requests/ })).toHaveAttribute("data-ready", "true"));
    expect(last().getAll("layers")).toEqual(["open", "uncovered", "providers"]);
    expect(last().get("shade")).toBe("open");
    expect(last().get("from")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(map().sources.open.data.features).toHaveLength(2);
    expect(map().sources.providers.data.features).toHaveLength(1);
    for (const id of [...LAYER_IDS.open, ...LAYER_IDS.providers, ...LAYER_IDS.hexes]) expect(map().visible(id), id).toBe(true);
    for (const id of [...LAYER_IDS.booked, ...LAYER_IDS.completed]) expect(map().visible(id), id).toBe(false);
    // Uncovered demand is a button on the map, and listed under "Where to recruit".
    expect(screen.getByRole("button", { name: "Uncovered: Lawn mowing in Princes Risborough, HP27 (R-2284)" })).toBeInTheDocument();
    const recruit = screen.getByRole("region", { name: "Where to recruit" });
    expect(within(recruit).getByText("Lawn mowing in Princes Risborough, HP27")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Open requests/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Booked visits/ })).not.toBeChecked();
  });

  it("toggles each layer on and off, on the map and in what it asks for", async () => {
    const user = userEvent.setup();
    serveMap();
    renderWithProviders(<MapPage />, { path: "/admin/map" });
    await waitFor(() => expect(map()?.sources.open?.data.features).toHaveLength(2));

    await user.click(screen.getByRole("checkbox", { name: /Booked visits/ }));
    await waitFor(() => expect(last().getAll("layers")).toContain("booked"));
    await waitFor(() => expect(map().visible("booked-points")).toBe(true));
    await waitFor(() => expect(map().sources.booked.data.features).toHaveLength(1));

    await user.click(screen.getByRole("checkbox", { name: /Providers/ }));
    await waitFor(() => expect(last().getAll("layers")).not.toContain("providers"));
    expect(map().visible("providers-disc")).toBe(false);
    expect(map().visible("reach-line")).toBe(false);

    await user.click(screen.getByRole("checkbox", { name: /Open requests/ }));
    await waitFor(() => expect(map().visible("open-points")).toBe(false));

    await user.click(screen.getByRole("checkbox", { name: /Uncovered demand/ }));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /^Uncovered: / })).not.toBeInTheDocument(),
    );
    expect(screen.queryByRole("region", { name: "Where to recruit" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: /Completed jobs/ }));
    await waitFor(() => expect(map().visible("completed-points")).toBe(true));

    await user.click(screen.getByRole("radio", { name: "Booked visits" }));
    await waitFor(() => expect(last().get("shade")).toBe("booked"));
    await user.click(screen.getByRole("checkbox", { name: /Concentration/ }));
    await waitFor(() => expect(last().get("shade")).toBe("none"));
    expect(map().visible("hexes-fill")).toBe(false);
    expect(screen.getByRole("radio", { name: "Booked visits" })).toBeDisabled();

    expect(last().getAll("layers")).toEqual(["booked", "completed"]);
    expect(screen.getByRole("region", { name: /Map of requests/ }).getAttribute("data-shown")?.split(" ").sort()).toEqual([
      "booked",
      "completed",
    ]);
  });

  it("sends the date range for completed jobs", async () => {
    serveMap();
    renderWithProviders(<MapPage />, { path: "/admin/map" });
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-08-01" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-08-31" } });
    await waitFor(() => expect([last().get("from"), last().get("to")]).toEqual(["2026-08-01", "2026-08-31"]));
    // An emptied field keeps the last date rather than asking for nothing.
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "" } });
    expect(screen.getByLabelText("From")).toHaveValue("2026-08-01");
  });

  it("opens an uncovered request's details, with its link to dispatch", async () => {
    const user = userEvent.setup();
    serveMap();
    renderWithProviders(<MapPage />, { path: "/admin/map" });
    await user.click(await screen.findByRole("button", { name: "Uncovered: Lawn mowing in Princes Risborough, HP27 (R-2284)" }));
    const panel = screen.getByRole("region", { name: "Details" });
    expect(within(panel).getByRole("heading", { name: "Lawn mowing in Princes Risborough, HP27" })).toBeInTheDocument();
    expect(panel).toHaveTextContent("Open 26 hours, nobody's taken it yet");
    expect(panel).toHaveTextContent("£28");
    expect(panel).toHaveTextContent("No active provider in reach does lawn mowing (1 provider in reach does other jobs)");
    // Who is in reach, and what they do (A36).
    expect(within(panel).getByRole("list", { name: "Active providers in reach" })).toHaveTextContent(
      "Kasia N., 3.2 mi: Regular cleaning, Deep clean",
    );
    expect(within(panel).getByRole("link", { name: "Open R-2284" })).toHaveAttribute("href", "/admin/requests/id-R-2284");

    // The button stays the same one (so keyboard focus stays on it), marked as the one shown.
    const marker = screen.getByRole("button", { name: "Uncovered: Lawn mowing in Princes Risborough, HP27 (R-2284)" });
    expect(marker).toHaveClass("on");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("region", { name: "Details" })).not.toBeInTheDocument();
    expect(marker).not.toHaveClass("on");
    marker.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("region", { name: "Details" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Uncovered: Lawn mowing in Princes Risborough, HP27 (R-2284)" })).toBe(marker);
    expect(marker).toHaveFocus();

    // It closes with its layers.
    await user.click(screen.getByRole("checkbox", { name: /Uncovered demand/ }));
    expect(screen.getByRole("region", { name: "Details" })).toBeInTheDocument(); // still an open request
    await user.click(screen.getByRole("checkbox", { name: /Open requests/ }));
    expect(screen.queryByRole("region", { name: "Details" })).not.toBeInTheDocument();
  });

  it("shows uncovered requests too close to tell apart as one button that zooms in", async () => {
    const user = userEvent.setup();
    server.neighbour = true;
    serveMap();
    renderWithProviders(<MapPage />, { path: "/admin/map" });
    const group = await screen.findByRole("button", { name: "2 uncovered requests close together (R-2284, R-2295): zoom in" });
    expect(group).toHaveTextContent("2");
    expect(screen.queryByRole("button", { name: /^Uncovered: / })).not.toBeInTheDocument();
    await user.click(group);
    expect(map().fitted.at(-1)).toEqual([
      [-0.834, 51.7243],
      [-0.8335, 51.7245],
    ]);
    act(() => map().zoomIn(8));
    expect(await screen.findByRole("button", { name: "Uncovered: Lawn mowing in Princes Risborough, HP27 (R-2284)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Uncovered: Window cleaning in Princes Risborough, HP27 (R-2295)" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /close together/ })).not.toBeInTheDocument();
  });

  it("names who does a covered visit, and links to them", async () => {
    const user = userEvent.setup();
    server.covered = true;
    serveMap();
    renderWithProviders(<MapPage />, { path: "/admin/map" });
    await user.click(await screen.findByRole("checkbox", { name: /Booked visits/ }));
    await waitFor(() => expect(map()?.sources.booked?.data.features).toHaveLength(1));
    map().hits = [{ layer: { id: "booked-points", source: "booked" }, properties: { booking_id: "b1" }, geometry: booking.geometry }];
    await act(() => map().click());
    const panel = screen.getByRole("region", { name: "Details" });
    expect(panel).toHaveTextContent("ProviderMike R., covering for Dave H.");
    expect(panel).toHaveTextContent("Booked: 3 visits to come, the next on 6 Oct 2026");
    expect(within(panel).getByRole("link", { name: "Mike R.'s page" })).toHaveAttribute("href", "/admin/providers/p-mike");
  });

  it("marks a provider whose payouts are paused, who still counts as cover (A37)", async () => {
    server.daveStatus = "payouts_paused";
    serveMap();
    renderWithProviders(<MapPage />, { path: "/admin/map" });
    await waitFor(() => expect(map()?.sources.providers?.data.features).toHaveLength(1));
    const mark = dataLayers().find((l) => l.id === "providers-paused");
    expect(mark && "filter" in mark ? mark.filter : null).toEqual(["==", ["get", "payouts_paused"], true]);
    expect(map().visible("providers-paused")).toBe(true);
    map().hits = [{ layer: { id: "providers-disc", source: "providers" }, properties: { provider_id: "p-dave" }, geometry: provider.geometry }];
    await act(() => map().click());
    const panel = screen.getByRole("region", { name: "Details" });
    expect(within(panel).getByText("Payouts paused")).toHaveClass("badge");
    expect(panel).toHaveTextContent("Active, payouts paused. They still take jobs, so they count as cover. (Tax details missing)");
  });

  it("keeps the details in step with the latest data, and closes them when the marker has gone", async () => {
    const user = userEvent.setup();
    serveMap();
    const { qc } = renderWithProviders(<MapPage />, { path: "/admin/map" });
    const details = () => screen.queryByRole("region", { name: "Details" });
    const refresh = () => act(() => qc.invalidateQueries());

    // A request: its guide is raised, then a provider books it.
    await user.click(await screen.findByRole("button", { name: "Uncovered: Lawn mowing in Princes Risborough, HP27 (R-2284)" }));
    expect(details()).toHaveTextContent("£28");
    server.r2284 = { guide_pence: 3100, age_text: "27 hours" };
    await refresh();
    await waitFor(() => expect(details()).toHaveTextContent("£31"));
    expect(details()).toHaveTextContent("Open 27 hours");
    server.gone.add("R-2284");
    await refresh();
    await waitFor(() => expect(details()).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /\(R-2284\)$/ })).not.toBeInTheDocument();

    // A provider suspended meanwhile shows as suspended.
    await waitFor(() => expect(map()?.sources.providers?.data.features).toHaveLength(1));
    map().hits = [{ layer: { id: "providers-disc", source: "providers" }, properties: { provider_id: "p-dave" }, geometry: provider.geometry }];
    await act(() => map().click());
    expect(details()).toHaveTextContent("StatusActive");
    server.daveStatus = "suspended";
    await refresh();
    await waitFor(() => expect(details()).toHaveTextContent("Suspended: their radius covers no one yet"));

    // A completed job outside newly chosen dates.
    await user.click(screen.getByRole("checkbox", { name: /Completed jobs/ }));
    await waitFor(() => expect(map().sources.completed.data.features).toHaveLength(1));
    map().hits = [{ layer: { id: "completed-points", source: "completed" }, properties: { booking_id: "b2" }, geometry: booking.geometry }];
    await act(() => map().click());
    expect(details()).toHaveTextContent("Completed: 2 visits in the dates chosen");
    server.gone.add("b2");
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-09-25" } });
    await waitFor(() => expect(details()).not.toBeInTheDocument());

    // Switching a layer off closes its panel for good, even when it's switched back on.
    map().hits = [{ layer: { id: "providers-disc", source: "providers" }, properties: { provider_id: "p-dave" }, geometry: provider.geometry }];
    await act(() => map().click());
    expect(details()).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: /Providers/ }));
    expect(details()).not.toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: /Providers/ }));
    await waitFor(() => expect(last().getAll("layers")).toContain("providers"));
    expect(details()).not.toBeInTheDocument();
  });

  it("opens a provider from the map, placed at their postcode, with a link to their page", async () => {
    const user = userEvent.setup();
    serveMap();
    renderWithProviders(<MapPage />, { path: "/admin/map" });
    await waitFor(() => expect(map()?.sources.providers?.data.features).toHaveLength(1));
    map().hits = [{ layer: { id: "providers-disc", source: "providers" }, properties: { provider_id: "p-dave" }, geometry: provider.geometry }];
    await act(() => map().click());
    const panel = screen.getByRole("region", { name: "Details" });
    expect(within(panel).getByRole("heading", { name: "Dave H." })).toBeInTheDocument();
    expect(panel).toHaveTextContent("Travel radius4 miles");
    expect(panel).toHaveTextContent("Shown at the centre of their home postcode, not their address.");
    expect(within(panel).getByRole("link", { name: "Provider page" })).toHaveAttribute("href", "/admin/providers/p-dave");

    // A click on nothing closes it; the recruit list's Show opens a request.
    map().hits = [];
    await act(() => map().click());
    expect(screen.queryByRole("region", { name: "Details" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show R-2284 on the map" }));
    expect(screen.getByRole("region", { name: "Details" })).toHaveTextContent("Princes Risborough");
    await user.click(screen.getByRole("button", { name: "Close details" }));
    expect(screen.queryByRole("region", { name: "Details" })).not.toBeInTheDocument();
  });
});

describe("the basemap", () => {
  it("comes only from this site: tiles, fonts and sprites under /basemap", () => {
    const style = basemapStyle("https://dev.onequickjob.co.uk");
    const urls = [style.glyphs, style.sprite, ...Object.values(style.sources).map((s) => ("url" in s ? s.url : ""))];
    expect(urls).toEqual([
      "https://dev.onequickjob.co.uk/basemap/fonts/{fontstack}/{range}.pbf",
      "https://dev.onequickjob.co.uk/basemap/sprites/v4/light",
      "pmtiles://https://dev.onequickjob.co.uk/basemap/oqj.pmtiles",
    ]);
    expect(JSON.stringify(style)).not.toMatch(/https?:\/\/(?!dev\.onequickjob\.co\.uk|www\.openstreetmap\.org\/copyright)/);
    expect(JSON.stringify(style.sources)).toContain("OpenStreetMap contributors");
    // Every fontstack the style names is one make basemap fetches.
    const fonts = new Set(JSON.stringify(style.layers).match(/Noto Sans[^"]*/g));
    const script = readFileSync(resolve(process.cwd(), "../scripts/basemap.sh"), "utf8");
    const fetched = [...script.match(/^FONTS=\((.*)\)$/m)![1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
    expect([...fonts].sort()).toEqual([...fetched].sort());
  });
});
