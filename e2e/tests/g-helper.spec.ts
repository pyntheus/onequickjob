// Journey G (A17): helpers only carry out visits. Tom, Dave's helper, signs in to the provider app:
// he sees his visits, not the jobs list, and the offer endpoints refuse him (accept and counter).
import { expect, test } from "@playwright/test";
import { send, signInAs } from "./helpers";

test("G (A17): a helper is refused on the offer endpoints and sees no jobs", async ({ page }) => {
  await signInAs(page, "tom", "/p");
  await expect(page.getByText("These are the visits you've been sent to.")).toBeVisible();
  // Loaded, so the nav is drawn: his tabs, with no jobs list and no money.
  await expect(page.getByRole("navigation", { name: "Provider" }).getByRole("link")).toHaveText(["Home", "Today", "Me"]);
  for (const [path, data] of [
    ["/api/p/requests/R-2292/accept", undefined],
    ["/api/p/requests/R-2292/counter", { price_pence: 9000, reasons: [] }],
  ] as const) {
    const r = await send(page, "POST", path, data);
    expect(r.status(), path).toBe(403);
    const body = await r.json();
    expect(body.detail.code).toBe("helpers_cant");
    expect(body.detail.message).toBe("Dave takes on jobs and sets the prices. You can see the visits you're doing on Today.");
  }
  await page.goto("/p/today");
  await expect(page.getByRole("heading", { name: /round/ })).toBeVisible();
  const jobs = await send(page, "GET", "/api/p/jobs");
  expect(jobs.status()).toBe(403);
});
