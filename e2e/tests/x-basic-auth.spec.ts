// The site password is asked for once. A browser keeps it after the sign-in box and sends it with
// every request until one is answered 401: it takes that as the password being refused, forgets
// it, and the next request brings the box back. The other journeys never notice (Playwright sends
// the password with every request), so this one signs in through the box once, as a person does,
// browses for over three minutes (the customer site with the Outbox open, the provider app, signed
// in and out), and fails on a second sign-in box or on any 401 in Caddy's access log for its run
// (make e2e follows the log into CADDY_LOG). Full Chromium, like Chrome, not the headless shell.
// On the way it checks the provider app is installable, which needs the manifest to load with the
// password (and, like Chrome, a real profile: nothing installs from an incognito one).
import { chromium, expect, test, type Page } from "@playwright/test";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const user = process.env.E2E_USER ?? "";
const pass = process.env.E2E_PASS ?? "";
const CADDY_LOG = process.env.CADDY_LOG ?? "";
const MINUTES = 3;

type Access = {
  logger?: string;
  ts: number;
  status: number;
  request: { method: string; uri: string; headers: Record<string, string[]> };
};

/** This run's lines in Caddy's access log (its user agent carries the run's marker). */
function accessLog(marker: string): Access[] {
  return readFileSync(CADDY_LOG, "utf8")
    .split("\n")
    .flatMap((line) => {
      try {
        return [JSON.parse(line) as Access];
      } catch {
        return [];
      }
    })
    .filter((e) => e.logger?.startsWith("http.log.access") && e.request.headers["User-Agent"]?.some((ua) => ua.includes(marker)))
    .sort((a, b) => a.ts - b.ts);
}

async function openOutbox(page: Page) {
  const fab = page.getByRole("button", { name: "Outbox", exact: true });
  if ((await fab.getAttribute("aria-expanded")) !== "true") await fab.click();
  await expect(page.getByRole("dialog", { name: "Outbox" })).toBeVisible();
}

/** Switch user (the demo menu), as someone trying the demo does. */
async function switchTo(page: Page, name: RegExp) {
  await page.getByRole("button", { name: /^Switch user/ }).click();
  await page.getByRole("group", { name: "Switch user" }).getByRole("button", { name }).click();
}

test("the site password is asked for once, however long you browse", async ({ baseURL }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "once is enough: the sign-in box doesn't depend on the width");
  expect(CADDY_LOG, "run it with make e2e, which follows Caddy's access log into CADDY_LOG").not.toBe("");
  test.setTimeout((MINUTES + 4) * 60_000);

  const marker = `oqj-e2e-basic-auth-${Date.now().toString(36)}`;
  const ua = `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 ${marker}`;
  // Its own browser on a fresh profile: the flag gives every request the marker, the service
  // worker's included. No httpCredentials: the password goes in only through the sign-in box below.
  const profile = mkdtempSync(join(tmpdir(), "oqj-basic-auth-"));
  const context = await chromium.launchPersistentContext(profile, {
    channel: "chromium",
    args: [`--user-agent=${ua}`],
    baseURL,
    userAgent: ua,
    viewport: { width: 1280, height: 860 },
    locale: "en-GB",
    timezoneId: "Europe/London",
  });
  try {
    const page = context.pages()[0] ?? (await context.newPage());
    const cdp = await context.newCDPSession(page);

    // The sign-in box: answered with the password the first time, cancelled after that (a person
    // giving up), and every time it appears is recorded.
    const boxes: string[] = [];
    cdp.on("Fetch.requestPaused", (e) => void cdp.send("Fetch.continueRequest", { requestId: e.requestId }).catch(() => undefined));
    cdp.on("Fetch.authRequired", (e) => {
      boxes.push(`${e.request.method} ${new URL(e.request.url).pathname}`);
      const answer = boxes.length === 1 ? { response: "ProvideCredentials" as const, username: user, password: pass } : { response: "CancelAuth" as const };
      void cdp.send("Fetch.continueWithAuth", { requestId: e.requestId, authChallengeResponse: answer }).catch(() => undefined);
    });
    await cdp.send("Fetch.enable", { handleAuthRequests: true, patterns: [{ urlPattern: "*" }] });
    const refused: string[] = [];
    page.on("response", (r) => {
      if (r.status() === 401) refused.push(`${r.request().method()} ${new URL(r.url()).pathname}`);
    });

    const started = Date.now();
    const browse = (seconds: number) => page.waitForTimeout(seconds * 1000);
    const askedOnce = () => expect(boxes, "the sign-in box came back").toEqual(["GET /"]);

    // A box cancelled after the first leaves the page refused, so a later step fails on that:
    // whatever fails, a box that came back is the reason given.
    try {
      await test.step("signed out, with the Outbox open", async () => {
        await page.goto("/");
        await expect(page.getByRole("button", { name: /Lawn mowing/ })).toBeVisible();
        expect(boxes, "signed in through the box").toEqual(["GET /"]);
        await openOutbox(page);
        await browse(25);
        await page.goto("/account");
        await openOutbox(page);
        await browse(20);
        askedOnce();
      });

      await test.step("Sarah, a customer", async () => {
        await switchTo(page, /^Sarah Whitfield/);
        await expect(page.getByRole("button", { name: /signed in as Sarah Whitfield/ })).toBeVisible();
        await openOutbox(page);
        await browse(20);
        await page.goto("/account");
        await openOutbox(page);
        await browse(20);
        askedOnce();
      });

      await test.step("Dave, in the provider app", async () => {
        await switchTo(page, /^Dave Hughes/);
        await expect(page.getByRole("navigation", { name: "Provider" })).toBeVisible();
        await openOutbox(page);
        await browse(15);
        // What Chrome fetches to offer the app for installing (headless Chromium only on request):
        // it loads, with no warnings (start_url /p/ inside scope /p), and the app is installable.
        const manifest = await cdp.send("Page.getAppManifest", {});
        expect(manifest.errors, "the manifest's warnings").toEqual([]);
        expect(manifest.data ?? "", "the manifest loads").toContain("OneQuickJob for providers");
        const { installabilityErrors } = await cdp.send("Page.getInstallabilityErrors");
        expect(installabilityErrors, "why the provider app can't be installed").toEqual([]);
        for (const tab of ["Today", "Earnings", "Me"]) {
          await page.getByRole("navigation", { name: "Provider" }).getByRole("link", { name: tab }).click();
          await browse(10);
        }
        await page.goto("/p/"); // where the installed app starts
        await expect(page.getByRole("navigation", { name: "Provider" })).toBeVisible();
        await page.reload(); // through the service worker, with its update check
        await expect(page.getByRole("navigation", { name: "Provider" })).toBeVisible();
        await browse(10);
        askedOnce();
      });

      await test.step("signed out again, back on the customer site", async () => {
        await page.getByRole("button", { name: /^Switch user/ }).click();
        await page.getByRole("group", { name: "Switch user" }).getByRole("button", { name: /^Sign out/ }).click();
        await expect(page.getByRole("button", { name: /^Switch user$/ })).toBeVisible();
        await openOutbox(page);
        // The rest of the three minutes, and at least 35 seconds of the Outbox's polling.
        await browse(Math.max(35, MINUTES * 60 - (Date.now() - started) / 1000 + 5));
        await page.goto("/");
        await browse(5);
        askedOnce();
      });
    } catch (e) {
      askedOnce();
      throw e;
    }

    expect(Date.now() - started).toBeGreaterThanOrEqual(MINUTES * 60_000);
    expect(refused, "401s the page saw").toEqual([]);

    // Caddy's log: every request the browser made, its own and the service worker's included.
    await page.waitForTimeout(2000); // for the follower to write the last lines
    const log = accessLog(marker);
    expect(log.length, "this run's requests are in Caddy's access log").toBeGreaterThan(100);
    const unauthorised = log
      .filter((e) => e.status === 401)
      .map((e) => `${e.request.method} ${e.request.uri}${e.request.headers.Authorization ? " (with the password)" : ""}`);
    // The first request, before the box was answered, is the only one allowed.
    expect(unauthorised, "401s in Caddy's access log").toEqual(["GET /"]);
    const manifests = log.filter((e) => e.request.uri === "/p/manifest.webmanifest").map((e) => e.status);
    expect(manifests.length, "the manifest was fetched").toBeGreaterThan(0);
    expect(manifests.every((st) => st === 200 || st === 304), `manifest fetches: ${manifests.join(", ")}`).toBe(true);
  } finally {
    await context.close();
    rmSync(profile, { recursive: true, force: true });
  }
});
