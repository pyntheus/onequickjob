// End-to-end journeys and accessibility checks against the production-style stack at
// E2E_BASE_URL (default https://dev.onequickjob.co.uk), behind its basic auth. Run them with
// `make e2e`: it re-seeds the demo before each project, because the journeys use seeded people
// (Sarah, Dave, Mary's invite...). One worker: the journeys share one database.
import { defineConfig } from "@playwright/test";

const user = process.env.E2E_USER;
const pass = process.env.E2E_PASS;
if (!user || !pass) throw new Error("E2E_USER and E2E_PASS (the site's basic auth) must be set: run make e2e");
const baseURL = process.env.E2E_BASE_URL ?? "https://dev.onequickjob.co.uk";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 15_000 },
  // The console list only. Playwright records every failed API call as a step error, headers
  // and all, before send() can redact it, and the HTML report keeps those step errors (in a
  // compressed blob, even for passing tests): it would hold the site password.
  reporter: [["list"]],
  outputDir: "results",
  use: {
    baseURL,
    // Sent to the site only (origin), never to anything else a page or test might reach.
    httpCredentials: { username: user, password: pass, send: "always", origin: new URL(baseURL).origin },
    locale: "en-GB",
    timezoneId: "Europe/London",
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
    // No traces: they record the context's httpCredentials and every request's Authorization
    // header, so a failure would leave the site password on disk. A failure keeps a screenshot
    // and error-context.md (the test's own errors: API calls go through helpers.ts's send(),
    // which takes the password out of a failed request's error before rethrowing it).
    trace: "off",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "phone",
      use: { browserName: "chromium", viewport: { width: 375, height: 812 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
    },
    { name: "desktop", use: { browserName: "chromium", viewport: { width: 1280, height: 860 } } },
  ],
});
