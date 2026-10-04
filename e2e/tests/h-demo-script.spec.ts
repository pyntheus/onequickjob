// docs/demo-script.md, click for click (steps 1 to 6), so the script can't drift from the app.
import { expect, test } from "@playwright/test";
import { finishVisit, linkIn, message, PHONES, signInAs } from "./helpers";

test("the demo script's tour works as written", async ({ page }) => {
  await test.step("1. an instant quote, signed out", async () => {
    await page.goto("/");
    await expect(page.getByText("Prototype: test payments only")).toBeVisible();
    await page.getByRole("combobox", { name: "Your address" }).fill("Orchard");
    await page.getByRole("option", { name: /12 Orchard Way/ }).click();
    await page.getByRole("button", { name: "See my price" }).click();
    await page.getByRole("button", { name: /^Large/ }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("button", { name: "See my price" }).click();
    for (const amount of ["£31", "£26.35", "£4.65"]) await expect(page.getByText(amount).first()).toBeVisible();
  });

  let ref = "";
  await test.step("2. a booking, signing in with the code from the Outbox; Dave's text alert", async () => {
    await page.getByRole("button", { name: "Request this job" }).click();
    await page.getByLabel("Your name").fill("Sarah Whitfield");
    await page.getByLabel("Mobile number").fill("07700 900123");
    await page.getByRole("button", { name: "Text me a code" }).click();
    await page.getByRole("button", { name: "Outbox", exact: true }).click();
    const code = (await message(page, "login_code", PHONES.sarah)).body.match(/\b(\d{6})\b/)![1];
    await expect(page.getByLabel(`Sign-in code ${code.split("").join(" ")}`)).toBeVisible();
    await page.getByRole("button", { name: "Close the outbox" }).click();
    await page.getByLabel("Your code").fill(code);
    await page.getByRole("button", { name: "Confirm my number" }).click();
    const card = page.getByRole("button", { name: "Use test card 4242" });
    await expect(page.getByText("•••• •••• •••• 4242").or(card)).toBeVisible();
    if (await card.isVisible()) await card.click();
    await page.getByRole("checkbox", { name: /I agree to the customer terms/ }).click();
    await page.getByRole("button", { name: "Send my request" }).click();
    await expect(page.getByRole("heading", { name: "Finding someone local" })).toBeVisible();
    ref = page.url().split("/requests/")[1];
    const alert = await message(page, "job_alert", PHONES.dave);
    expect(alert.body).toContain(`/p/j/${ref}`);
    await page.goto(linkIn(alert.body)); // the link signs Dave in
    await page.getByRole("button", { name: "Accept at £31" }).click();
    await message(page, "request_booked", PHONES.sarah);
  });

  await test.step("3. finishing the job: £26.35 on its way", async () => {
    const visit = await page.request.get(`/api/p/today`);
    const days: string[] = (await visit.json()).upcoming_days;
    let finished = "";
    for (const day of days) {
      const round = await (await page.request.get(`/api/p/today?date=${day}`)).json();
      if (round.items.some((i: { customer_name: string; status: string }) => i.customer_name.startsWith("Sarah") && i.status === "scheduled")) {
        finished = await finishVisit(page, { day, customer: "Sarah", overrun: true });
        break;
      }
    }
    expect(finished).toBe("£26.35 is on its way");
  });

  await test.step("4. earnings, the tax pack and the earnings limit", async () => {
    await page.getByRole("link", { name: "Earnings" }).click();
    await expect(page.getByRole("heading", { name: "Earnings" })).toBeVisible();
    await page.getByRole("link", { name: /Tax and records/ }).click();
    await expect(page.getByRole("link", { name: "Download your tax pack" })).toBeVisible();
    await page.goto("/p/earnings");
    await page.getByRole("link", { name: /Earnings limit/ }).click();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  });

  await test.step("5. cover and helpers; Tom sees only his visits", async () => {
    const days: string[] = (await (await page.request.get("/api/p/today")).json()).upcoming_days;
    await page.goto(`/p/today?date=${days.at(-1)}`);
    await expect(page.getByText("Can't make one of these jobs?")).toBeVisible();
    await expect(page.getByRole("button", { name: "Send Tom" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Get cover" })).toBeVisible();
    await signInAs(page, "tom", "/p");
    await expect(page.getByText("These are the visits you've been sent to.")).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Provider" }).getByRole("link")).toHaveText(["Home", "Today", "Me"]);
  });

  await test.step("6. pricing and calibration, as Jo", async () => {
    await signInAs(page, "admin_jo", "/admin/pricing");
    await expect(page.getByRole("img", { name: /Estimated minutes against actual minutes/ })).toBeVisible();
  });
});
