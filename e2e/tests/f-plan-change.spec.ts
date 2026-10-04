// Journey F: changing how often a plan runs. A platform plan is re-priced by the engine and the
// provider accepts (A10: Margaret's fortnightly £32 becomes weekly £30). An own customer's plan is
// priced by the provider and the customer approves, seeing the commission (A22: Pat's plan).
import { expect, test } from "@playwright/test";
import { api, linkIn, message, PHONES, signInAs } from "./helpers";

type Plan = { series_id: string; frequency: string; price_pence: number; pending_change: unknown };

test("F1 (A10): Margaret asks for weekly at the re-priced £30; Dave accepts from the link in his text", async ({ page }) => {
  await signInAs(page, "margaret", "/account?tab=plan");
  await page.getByRole("button", { name: "Change how often" }).click();
  await page.getByRole("button", { name: "Every week" }).click();
  await expect(page.getByText("Every week, the price would be £30 a visit (it's £32 now).", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Ask Dave" }).click();
  await expect(page.getByText(/Waiting for Dave to accept every week at/)).toBeVisible();

  const text = await message(page, "plan_change_proposed", PHONES.dave);
  await signInAs(page, "dave", linkIn(text.body));
  await expect(page.getByRole("heading", { name: "Margaret would like visits every week" })).toBeVisible();
  await page.getByRole("button", { name: "Accept £30 a visit" }).click();
  await expect(page.getByText("You accepted this change. The plan has been updated.")).toBeVisible();

  await signInAs(page, "margaret", "/account?tab=plan");
  const [plan] = (await api<Plan[]>(page, "GET", "/api/c/plans")).filter((p) => p.frequency === "weekly");
  expect(plan.price_pence).toBe(3000);
  await expect(page.getByRole("heading", { name: /Lawn mowing, every week/ })).toBeVisible();
});

test("F2 (A22): Pat asks Dave for a price at weekly; Dave names £26; Pat agrees, seeing the commission", async ({ page }) => {
  await signInAs(page, "pat", "/account?tab=plan");
  await page.getByRole("button", { name: "Change how often" }).first().click();
  await page.getByRole("button", { name: "Every week" }).click();
  await expect(page.getByText(/Dave sets the price for your plan/)).toBeVisible();
  await page.getByRole("button", { name: "Ask Dave for a price" }).click();
  await expect(page.getByText(/Waiting for Dave's price to have it every week/)).toBeVisible();

  const asked = await message(page, "plan_change_price_asked", PHONES.dave);
  expect(asked.body).toContain("you set the price");
  await signInAs(page, "dave", linkIn(asked.body));
  await expect(page.getByRole("heading", { name: "Pat would like visits every week" })).toBeVisible();
  await page.getByRole("button", { name: "Less: Your price a visit" }).click();
  await page.getByRole("button", { name: "Less: Your price a visit" }).click();
  await expect(page.getByText("£24.70")).toBeVisible(); // what Dave keeps of £26 (5%, at least £1), from the API
  await page.getByRole("button", { name: "Send £26 a visit to Pat" }).click();
  await expect(page.getByText(/You've asked £26 a visit. Pat has until/)).toBeVisible();

  const priced = await message(page, "plan_change_priced", PHONES.pat);
  expect(priced.body).toContain("£26 a visit (it's £28 now)");
  await signInAs(page, "pat", "/account?tab=plan");
  await expect(page.getByText("Dave can do it every week at £26 a visit (it's £28 now).", { exact: false })).toBeVisible();
  await expect(page.getByText(/Dave pays us a small fee of £1.30 a visit \(5%\). It isn't added to your price./)).toBeVisible();
  await page.getByRole("button", { name: "Agree £26 a visit" }).click();
  await expect(page.getByRole("heading", { name: /Lawn mowing, every week/ })).toBeVisible();
  const plans = await api<Plan[]>(page, "GET", "/api/c/plans");
  expect(plans.find((p) => p.frequency === "weekly")?.price_pence).toBe(2600);
  await message(page, "plan_change_approved", PHONES.dave);
});
