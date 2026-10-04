// Journey B (A1): on a job with a dearer first visit, Dave suggests a higher price; the first visit
// goes up by the same share; Sarah sees both prices, accepts, and the first visit is charged at
// its own (scaled) price with the standard 15% fee.
import { expect, test } from "@playwright/test";
import { api, finishVisit, pounds, requestMowing, signInAs, standardFee } from "./helpers";

test("B: a counter on a job with a dearer first visit is accepted, both prices shown and charged", async ({ page }) => {
  await signInAs(page, "sarah", "/");
  const ref = await requestMowing(page, "Getting long");
  const req = await api(page, "GET", `/api/c/requests/${ref}`);
  expect(req.first_pence).toBeGreaterThan(req.guide_pence); // long grass: the first visit takes longer

  let counter = 0;
  let first = 0;
  await test.step("Dave suggests a higher price; the first visit rises by the same share", async () => {
    await signInAs(page, "dave", `/p/j/${ref}`);
    await page.getByRole("button", { name: "Suggest a different price" }).click();
    for (let i = 0; i < 3; i++) await page.getByRole("button", { name: "More: Your price" }).click();
    counter = Number((await page.getByRole("group", { name: "Your price" }).innerText()).match(/£(\d+)/)![1]) * 100;
    expect(counter).toBeGreaterThan(req.guide_pence);
    first = Math.floor((req.first_pence * counter) / req.guide_pence / 100 + 0.5) * 100; // A1: same share, whole pounds
    await expect(page.getByText(`The first visit becomes ${pounds(first)}. You'd get ${pounds(first - standardFee(first))} for the first visit.`)).toBeVisible();
    await page.getByRole("button", { name: "Longer grass than described" }).click();
    await page.getByRole("button", { name: `Send ${pounds(counter)} to Sarah` }).click();
    await expect(page.getByText(/Sarah approves it|sent/i).first()).toBeVisible();
  });

  let day = "";
  await test.step("Sarah sees both prices and accepts", async () => {
    await signInAs(page, "sarah", `/requests/${ref}`);
    const accept = page.getByRole("button", { name: new RegExp(`^Accept ${pounds(counter).replace(".", "\\.")}.*first visit ${pounds(first)}`) });
    await expect(accept).toBeVisible();
    const accepted = page.waitForResponse((r) => r.url().includes("/api/c/offers/") && r.url().endsWith("/accept"));
    await accept.click();
    const out = await (await accepted).json();
    expect(out.price_pence).toBe(counter);
    expect(out.first_visit.price_pence).toBe(first);
    day = out.first_visit.local_date;
    await expect(page.getByRole("heading", { name: /You're booked with Dave/ })).toBeVisible();
    await expect(page.getByText(new RegExp(`first visit ${pounds(first)}`)).first()).toBeVisible();
  });

  await test.step("the first visit is charged at its own price, 15% fee", async () => {
    await signInAs(page, "dave", "/p");
    const before = await api(page, "GET", "/api/p/tax");
    const heading = await finishVisit(page, { day, customer: "Sarah", photos: false });
    expect(heading).toBe(`${pounds(first - standardFee(first))} is on its way`);
    const after = await api(page, "GET", "/api/p/tax");
    expect(after.turnover_pence - before.turnover_pence).toBe(first);
    expect(after.fees_pence - before.fees_pence).toBe(standardFee(first));
  });
});
