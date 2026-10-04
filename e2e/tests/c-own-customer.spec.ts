// Journey C: Mary accepts Dave's own-customer invite (the link in his text, her number confirmed
// with the code from the Outbox), and her visit is charged at the own-customer rate: 5%, at least
// £1. On her £25 a visit that's £1.25, and Dave gets £23.75.
import { expect, test } from "@playwright/test";
import { api, confirmNumber, finishVisit, linkIn, message, ownFee, PHONES, pounds, signInAs } from "./helpers";

test("C: Mary accepts Dave's own-customer invite and her visit is charged at 5% (at least £1)", async ({ page }) => {
  let day = "";
  await test.step("Mary opens the link in Dave's text and accepts", async () => {
    await page.goto("/"); // signed out: the invite link is all she has
    const invite = await message(page, "own_customer_invite", PHONES.mary);
    await page.goto(linkIn(invite.body));
    await expect(page.getByText(/£25 a visit/).first()).toBeVisible();
    await confirmNumber(page, PHONES.mary, "07700 900140");
    await page.getByRole("combobox", { name: "Your address" }).fill("Cockpit");
    await page.getByRole("option", { name: /5 Cockpit Road/ }).click();
    await page.getByRole("button", { name: "Use test card 4242" }).click();
    await expect(page.getByText("•••• •••• •••• 4242")).toBeVisible();
    await page.getByRole("checkbox", { name: /I agree to the customer terms/ }).click();
    const accepted = page.waitForResponse((r) => /\/api\/c\/invites\/[^/]+\/accept$/.test(r.url()));
    await page.getByRole("button", { name: "Accept Dave's invite" }).click();
    const card = await (await accepted).json();
    expect(card.source).toBe("own_customer");
    expect(card.split).toMatchObject({ mode: "own_customer", fee_pence: ownFee(2500), provider_pence: 2500 - ownFee(2500) });
    const visits = await api(page, "GET", "/api/c/visits");
    day = visits.next_visit.local_date;
  });

  await test.step("Dave finishes her first visit: 5% fee", async () => {
    await signInAs(page, "dave", "/p");
    const before = await api(page, "GET", "/api/p/tax");
    const heading = await finishVisit(page, { day, customer: "Mary", photos: false });
    expect(heading).toBe(`${pounds(2500 - ownFee(2500))} is on its way`);
    const after = await api(page, "GET", "/api/p/tax");
    expect(after.turnover_pence - before.turnover_pence).toBe(2500);
    expect(after.fees_pence - before.fees_pence).toBe(125);
  });
});
