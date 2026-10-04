// Journey E: a raised guide waits for the customer's approval (A12) and is approved; and a raise
// still waiting is withdrawn when a provider books at the original guide first (A16).
import { expect, test } from "@playwright/test";
import { api, message, pounds, signInAs } from "./helpers";

async function raiseFromOverview(page: import("@playwright/test").Page, ref: string): Promise<number> {
  await signInAs(page, "admin_jo", "/admin");
  const row = page.locator(".req").filter({ hasText: `Request ${ref},` });
  const raised = page.waitForResponse((r) => r.url().endsWith(`/api/admin/requests/${ref}/raise-guide`));
  await row.getByRole("button", { name: "Raise guide 10%" }).click();
  const out = await (await raised).json();
  await expect(page.getByText(/sent to the customer to approve/)).toBeVisible();
  return out.proposed_guide_pence;
}

test("E1 (A12): the customer approves a raised guide; the job goes out again at it", async ({ page }) => {
  const proposed = await raiseFromOverview(page, "R-2284");
  await signInAs(page, "martin", "/requests/R-2284");
  const before = await api(page, "GET", "/api/c/requests/R-2284");
  expect(before.guide_pence).toBeLessThan(proposed); // nothing changes until Martin approves
  await expect(page.getByRole("heading", { name: "A higher guide price?" })).toBeVisible();
  await page.getByRole("button", { name: new RegExp(`^Approve ${pounds(proposed)}`) }).click();
  await expect(page.getByText(new RegExp(`You approved a guide price of ${pounds(proposed)}`))).toBeVisible();
  const after = await api(page, "GET", "/api/c/requests/R-2284");
  expect(after.guide_pence).toBe(proposed);
  expect(after.price_change).toBeNull();
});

test("E2 (A16): a provider books at the original guide first, so the waiting raise is withdrawn", async ({ page }) => {
  const proposed = await raiseFromOverview(page, "R-2288");
  await signInAs(page, "mike", "/p/j/R-2288"); // Gary has his own counter waiting here
  await page.getByRole("button", { name: "Accept at £110" }).click();
  await expect(page.getByText(/yours|booked/i).first()).toBeVisible();
  const withdrawn = await message(page, "guide_raise_withdrawn", "+447700900141");
  expect(withdrawn.body).toContain("at your original price, £110");
  await signInAs(page, "denise", "/requests/R-2288");
  await expect(page.getByRole("heading", { name: /You're booked with Mike/ })).toBeVisible();
  await expect(page.getByText(`Booked before you answered, so the suggested ${pounds(proposed)} no longer applies`)).toBeVisible();
  await expect(page.getByRole("heading", { name: "A higher guide price?" })).toHaveCount(0);
});
