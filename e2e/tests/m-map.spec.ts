// The admin map (decisions.md A30 to A35): Jo opens Map, switches each layer off and on again,
// picks the dates for completed jobs, clicks a request no active provider reaches and follows its
// link to the dispatch list. All the while, nothing may leave the site: every request the page
// makes (the map's worker's included) must go to the site's own origin, or the test fails, and
// any that tries is stopped. The basemap is read by HTTP range from /basemap.
import { expect, test, type Page, type Request } from "@playwright/test";
import { signInAs } from "./helpers";

// MapLibre draws with WebGL: headless Chromium has it through SwiftShader when allowed to.
test.use({ launchOptions: { args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] } });

const TOGGLES: [label: RegExp, shown: string][] = [
  [/^Open requests/, "open"],
  [/^Uncovered demand/, "uncovered"],
  [/^Booked visits/, "booked"],
  [/^Completed jobs/, "completed"],
  [/^Providers/, "providers"],
  [/^Concentration/, "hexes"],
];

/** Requests the uncovered-demand buttons stand for: "!" is one, a group shows how many. */
async function onMap(page: Page): Promise<number> {
  const texts = await page.locator(".map-uncovered").allInnerTexts();
  return texts.reduce((n, t) => n + (t.trim() === "!" ? 1 : Number(t)), 0);
}

async function shown(page: Page): Promise<string[]> {
  const attr = await page.getByRole("region", { name: /Map of requests/ }).getAttribute("data-shown");
  return (attr ?? "").split(" ").filter(Boolean).sort();
}

test("Jo finds where demand outruns coverage and follows it to dispatch, all from the site", async ({ page, baseURL }) => {
  const origin = new URL(baseURL!).origin;
  const local = (url: string) => url.startsWith("data:") || url.startsWith("blob:") || new URL(url).origin === origin;
  const offsite: string[] = [];
  const watch = (r: Request) => {
    if (!local(r.url())) offsite.push(r.url());
  };
  page.context().on("request", watch);
  page.on("worker", (w) => {
    if (!local(w.url())) offsite.push(`worker ${w.url()}`);
  });
  await page.context().route((url) => !local(url.href), (route) => route.abort("blockedbyclient"));

  const ranged = page.waitForResponse((r) => r.url() === `${origin}/basemap/oqj.pmtiles` && r.status() === 206);
  const glyphs = page.waitForResponse((r) => r.url().startsWith(`${origin}/basemap/fonts/`) && r.ok());
  const sprite = page.waitForResponse((r) => r.url().startsWith(`${origin}/basemap/sprites/v4/light`) && r.ok());

  await signInAs(page, "admin_jo", "/admin");
  await page.getByRole("navigation", { name: "Admin" }).getByRole("link", { name: "Map" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Map" })).toBeVisible();
  const map = page.getByRole("region", { name: /Map of requests/ });
  await expect(map).toHaveAttribute("data-ready", "true");
  const range = await ranged;
  expect(range.headers()["content-range"]).toMatch(/^bytes 0-\d+\/\d+$/);
  await glyphs;
  await sprite;
  await expect(map.getByText("OpenStreetMap contributors")).toBeVisible();
  expect(await shown(page)).toEqual(["hexes", "open", "providers", "uncovered"]);

  // The thin areas: Princes Risborough, Longwick and Stokenchurch.
  const recruit = page.getByRole("region", { name: "Where to recruit" });
  await expect(recruit).toContainText("5 open requests that no active provider in reach does the job for.");
  await expect.poll(() => onMap(page)).toBe(5);

  // Each layer off and on again: the map and what's asked of the API follow.
  for (const [label, name] of TOGGLES) {
    const box = page.getByRole("checkbox", { name: label });
    const was = await box.isChecked();
    for (const want of [!was, was]) {
      const asked = page.waitForResponse((r) => r.url().includes("/api/admin/map?"));
      await box.setChecked(want);
      const url = new URL((await asked).url());
      if (name === "hexes") expect(url.searchParams.get("shade") === "none", "shade").toBe(!want);
      else expect(url.searchParams.getAll("layers").includes(name), name).toBe(want);
      await expect.poll(() => shown(page), { message: `${name} ${want ? "on" : "off"}` }).toEqual(
        want ? expect.arrayContaining([name]) : expect.not.arrayContaining([name]),
      );
    }
  }
  await expect.poll(() => onMap(page)).toBe(5);

  // Completed jobs over the last two months, shaded by where they were.
  await page.getByRole("checkbox", { name: /^Completed jobs/ }).check();
  await page.getByRole("radio", { name: "Completed jobs" }).check();
  const today = new Date().toLocaleDateString("en-CA", { timeZone: "Europe/London" });
  const from = new Date(Date.parse(today + "T12:00:00Z") - 60 * 86_400_000).toISOString().slice(0, 10);
  const asked = page.waitForResponse((r) => r.url().includes(`from=${from}`));
  await page.getByLabel("From").fill(from);
  const data = await (await asked).json();
  expect(data.completed.visits).toBeGreaterThan(30);
  expect(data.hexes.shade_by).toBe("completed");
  await expect(page.getByLabel("Concentration of completed jobs")).toBeVisible();

  // Stokenchurch: nobody reaches it. Find it from the list, then click it on the map.
  await recruit.getByRole("button", { name: "Show R-2297 on the map" }).click();
  await page.getByRole("button", { name: "Close details" }).click();
  await page.getByRole("button", { name: "Uncovered: Regular cleaning in Stokenchurch, HP14 (R-2297)" }).click();
  const panel = page.getByRole("region", { name: "Details" });
  await expect(panel.getByRole("heading", { name: "Regular cleaning in Stokenchurch, HP14" })).toBeVisible();
  await expect(panel).toContainText("Open 2 days, nobody's taken it yet");
  await expect(panel).toContainText("£66");
  await expect(panel).toContainText("No active provider in reach does regular cleaning");
  await panel.getByRole("link", { name: "Open R-2297" }).click();

  // Its own page (A38). Software WebGL (SwiftShader) on a phone-sized canvas can hold the page for
  // a while after the map has flown somewhere, so the move gets longer than the usual 15 seconds.
  await expect(page).toHaveURL(/\/admin\/requests\/[0-9a-f]{24}$/, { timeout: 60_000 });
  const title = page.getByRole("heading", { level: 1, name: "Regular cleaning in Stokenchurch, HP14" });
  await expect(title).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/^Request R-2297, made /)).toBeVisible();
  const request = page.locator(".card", { has: page.getByRole("heading", { name: "What the customer asked for" }) });
  await expect(request).toContainText("Olivia Hart, 07700 900162");
  await expect(request).toContainText("40 Wycombe Road, Stokenchurch, High Wycombe, HP14 3RR");
  await expect(request).toContainText("£66 a clean");
  const standing = page.locator(".card", { has: page.getByRole("heading", { name: "Where it stands" }) });
  await expect(standing).toContainText("Open 2 days, nobody's taken it yet. It's on the dispatch list.");
  await expect(standing).toContainText("No active provider in reach does regular cleaning.");
  const timeline = page.locator(".card", { has: page.getByRole("heading", { name: "What's happened" }) });
  await expect(timeline).toContainText("No provider was alerted");
  await expect(page.getByRole("button", { name: "Raise guide 10%" })).toBeVisible();

  // Overview's dispatch list links to the same pages.
  await page.getByRole("link", { name: "Overview and dispatch" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "This week" })).toBeVisible();
  await page.getByRole("link", { name: "Gutter clearing in Longwick, HP27" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Gutter clearing in Longwick, HP27" })).toBeVisible();
  await expect(page.getByText(/^Request R-2296, made /)).toBeVisible();

  page.context().off("request", watch);
  expect(offsite, "requests that left the site").toEqual([]);
});
