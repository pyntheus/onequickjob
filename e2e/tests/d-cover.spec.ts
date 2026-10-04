// Journey D (A4): Dave can't make Pat's next visit and gets local cover. Pat is Dave's own
// customer (5% when Dave or his helper does the visit), but a visit done by a cover provider is
// charged at the standard 15%: on £28 that's £4.20, and the cover provider gets £23.80.
import { expect, test } from "@playwright/test";
import { api, demoUsers, finishVisit, outbox, pounds, signInAs, standardFee } from "./helpers";

type RoundItem = { visit_id: string; customer_name: string; start_time: string; area: string; status: string };

test("D: a covered visit of an own customer is charged at the standard 15%", async ({ page }) => {
  await signInAs(page, "dave", "/p/today");
  // Pat's next visit, from the days on Dave's round.
  const today = await api(page, "GET", "/api/p/today");
  let day = "";
  let pat: RoundItem | undefined;
  for (const d of today.upcoming_days as string[]) {
    const round = await api(page, "GET", `/api/p/today?date=${d}`);
    pat = (round.items as RoundItem[]).find((i) => i.customer_name.startsWith("Pat") && i.status === "scheduled");
    if (pat) {
      day = d;
      break;
    }
  }
  expect(pat, "Pat's next visit on Dave's round").toBeTruthy();

  let ref = "";
  await test.step("Dave gets local cover for it", async () => {
    await page.goto(`/p/today?date=${day}`);
    await expect(page.getByText(/Can't make one of these jobs\?/)).toBeVisible();
    const which = page.getByRole("group", { name: "Which visit" });
    if (await which.count()) {
      const chip = which.getByRole("button", { name: `${pat!.start_time} ${pat!.area}` });
      await chip.click();
      await expect(chip).toHaveAttribute("aria-pressed", "true");
    }
    const before = new Set((await outbox(page)).map((m) => m.id));
    await page.getByRole("button", { name: "Get cover" }).click();
    await expect(page.getByText("Sent out for local cover. We'll text you when someone takes it.")).toBeVisible();
    await expect.poll(async () => (await outbox(page)).some((m) => !before.has(m.id) && m.template_id === "cover_alert")).toBe(true);
    const alert = (await outbox(page)).find((m) => !before.has(m.id) && m.template_id === "cover_alert")!;
    ref = alert.body.match(/\/p\/j\/(R-\d+)/)![1];
    const coverer = (await demoUsers(page)).find((u) => u.name === alert.recipient.name)!;
    expect(coverer, `a seeded provider got the cover alert (${alert.recipient.name})`).toBeTruthy();

    await test.step(`${coverer.name} takes the cover and finishes the visit`, async () => {
      await signInAs(page, coverer.demo_key, `/p/j/${ref}`);
      await expect(page.getByText(/Cover for Dave H\.'s regular customer/).first()).toBeVisible();
      const taxBefore = await api(page, "GET", "/api/p/tax");
      await page.getByRole("button", { name: "Accept at £28" }).click();
      await expect(page.getByText(/yours|booked/i).first()).toBeVisible();
      const heading = await finishVisit(page, { day, customer: "Pat", photos: false });
      expect(heading).toBe(`${pounds(2800 - standardFee(2800))} is on its way`); // £23.80: 15%, not the own-customer 5%
      const tax = await api(page, "GET", "/api/p/tax");
      expect(tax.fees_pence - taxBefore.fees_pence).toBe(420);
    });
  });
});
