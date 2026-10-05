// Journey A, the core: Sarah requests fortnightly mowing; Dave accepts at the guide; on Today he
// starts, adds photos and finishes with an overrun flag; the visit is charged through the fake
// gateway with the standard split (15%); Sarah rates it with a tip; Dave's ledger and tax pack
// move by exactly those amounts; admin calibration shows the new point.
import { expect, test } from "@playwright/test";
import { acceptAtGuide, api, finishVisit, message, PHONES, signInAs, type Finished } from "./helpers";

test("A: request, accept at guide, finish with an overrun, charged with the right split, rated with a tip", async ({ page }) => {
  // Before: Dave's tax year and the admin's calibration points, to compare afterwards.
  await signInAs(page, "admin_jo", "/admin");
  const calBefore = await api(page, "GET", "/api/admin/pricing/calibration");
  await signInAs(page, "dave", "/p");
  const taxBefore = await api(page, "GET", "/api/p/tax");

  let ref = "";
  await test.step("Sarah gets an instant guide price and requests fortnightly mowing", async () => {
    await signInAs(page, "sarah", "/");
    await page.getByRole("button", { name: /Lawn mowing/ }).click();
    await page.getByRole("combobox", { name: "Your address" }).fill("Orchard");
    await page.getByRole("option", { name: /12 Orchard Way/ }).click();
    await page.getByRole("button", { name: "See my price" }).click();
    await page.getByRole("button", { name: /^Large/ }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByRole("heading", { name: "A few quick questions" })).toBeVisible();
    await page.getByRole("button", { name: "Every 2 weeks" }).click();
    await page.getByRole("button", { name: "See my price" }).click();
    await expect(page.getByText("£31").first()).toBeVisible();
    await page.getByRole("button", { name: "Request this job" }).click();
    await page.getByRole("checkbox", { name: /I agree to the customer terms/ }).click();
    await page.getByRole("button", { name: "Send my request" }).click();
    await expect(page.getByRole("heading", { name: "Finding someone local" })).toBeVisible();
    ref = page.url().split("/requests/")[1];
    expect(ref).toMatch(/^R-\d+$/);
  });

  let day = "";
  await test.step("Dave is alerted by text and accepts at the guide", async () => {
    await signInAs(page, "dave", "/p");
    const alert = await message(page, "job_alert", PHONES.dave);
    expect(alert.body).toContain(`/p/j/${ref}`);
    day = await acceptAtGuide(page, ref, "£31");
    await expect(page.getByText(/It's yours|Booked|yours/).first()).toBeVisible();
  });

  // Dave's other visits that day, if any come first, are finished too: the totals below leave them out.
  const others: Finished[] = [];
  await test.step("on Today he starts, adds photos and finishes with an overrun flag; he's paid 85%", async () => {
    const heading = await finishVisit(page, { day, customer: "Sarah", overrun: true, others });
    expect(heading).toBe("£26.35 is on its way"); // £31 less the 15% fee (£4.65)
    const receipt = await message(page, "visit_done_customer", PHONES.sarah);
    expect(receipt.body).toContain("£31");
  });

  await test.step("Sarah rates the visit and adds a £2 tip", async () => {
    await signInAs(page, "sarah", "/account");
    await page.getByRole("link", { name: "Rate" }).first().click();
    await page.getByRole("radio", { name: "5 stars" }).click();
    await page.getByRole("button", { name: "£2" }).click();
    await page.getByRole("button", { name: "Send rating" }).click();
    await expect(page.getByText("Your £2 tip goes straight to Dave.")).toBeVisible();
  });

  await test.step("Dave's tax pack moves by the charge and the tip; his earnings show it", async () => {
    await signInAs(page, "dave", "/p/earnings");
    const tax = await api(page, "GET", "/api/p/tax");
    const charged = others.filter((o) => o.charge_status === "succeeded");
    const sum = (k: "price_pence" | "fee_pence" | "provider_pence") => charged.reduce((t, o) => t + o[k], 0);
    expect(tax.turnover_pence - taxBefore.turnover_pence - sum("price_pence")).toBe(3100 + 200);
    expect(tax.fees_pence - taxBefore.fees_pence - sum("fee_pence")).toBe(465); // tips carry no fee
    expect(tax.received_pence - taxBefore.received_pence - sum("provider_pence")).toBe(2635 + 200);
    await page.goto("/p/tax");
    await expect(page.getByText(new RegExp(`£${(tax.turnover_pence / 100).toLocaleString("en-GB")}`)).first()).toBeVisible();
    const tip = await message(page, "tip_received", PHONES.dave);
    expect(tip.body).toContain("£2");
  });

  await test.step("admin calibration shows the new, overrunning point", async () => {
    await signInAs(page, "admin_jo", "/admin/pricing");
    const cal = await api(page, "GET", "/api/admin/pricing/calibration");
    expect(cal.points.length).toBe(calBefore.points.length + 1 + others.length);
    const known = new Set([...calBefore.points.map((p: { visit_id: string }) => p.visit_id), ...others.map((o) => o.visit_id)]);
    const point = cal.points.find((p: { visit_id: string }) => !known.has(p.visit_id));
    expect(point.actual_mins).toBeGreaterThan(point.est_mins * 1.1);
    await expect(page.getByRole("img", { name: new RegExp(`for ${cal.points.length} timed jobs`) })).toBeVisible();
  });
});
