// Journey I (decisions.md A26 to A28): the lawn size step's three ways and the minutes field.
// I1: Sarah paces out a front and a back lawn, sees the area the API worked out beside its
// drawing, is priced for both lawns (the same price the API gives those strides) and books;
// Dave's job page shows both lawns and he accepts. I2: Dave finishes a visit typing an exact
// number of minutes, one the old 5-minute stepper could never reach.
import { expect, test } from "@playwright/test";
import { acceptAtGuide, api, finishVisit, message, PHONES, pounds, requestMowing, signInAs } from "./helpers";

const LAWNS = { method: "paced", adjust: "right", unit: "m", lawns: [{ length: "12", width: "8" }, { length: "14", width: "11" }] };

test("I1: Sarah paces out two lawns, is priced for both, and Dave books it", async ({ page }) => {
  let ref = "";
  let guide = 0;
  await test.step("Sarah paces out her front and back lawns", async () => {
    await signInAs(page, "sarah", "/");
    await page.getByRole("button", { name: /Lawn mowing/ }).click();
    await page.getByRole("combobox", { name: "Your address" }).fill("Orchard");
    await page.getByRole("option", { name: /12 Orchard Way/ }).click();
    await page.getByRole("button", { name: "See my price" }).click();
    await page.getByRole("tab", { name: "Pace it out" }).click();
    await expect(page.getByText("Walk the length of your lawn in big strides, about a metre each, then the width.")).toBeVisible();
    await page.getByRole("textbox", { name: "Strides long" }).fill("12");
    await page.getByRole("textbox", { name: "Strides wide" }).fill("7");
    await page.getByRole("button", { name: "Strides wide: +1" }).click();
    await expect(page.getByText("That's about 12 × 8 metres (96 m²)")).toBeVisible();
    await page.getByRole("button", { name: "Add another lawn" }).click();
    const back = page.getByRole("group", { name: "Lawn 2" });
    await back.getByRole("textbox", { name: "Strides long" }).fill("14");
    await back.getByRole("textbox", { name: "Strides wide" }).fill("11");
    await expect(page.getByText("That's about 250 m² in total across 2 lawns")).toBeVisible();
    await expect(page.getByText("Lawn 2: about 14 × 11 metres (154 m²)")).toBeVisible();
    await expect(page.getByRole("img", { name: "Your lawns drawn to scale, with a car and a person" })).toBeVisible();
    await page.getByRole("button", { name: "Continue" }).click();
  });

  await test.step("the guide price is for both lawns, and is the API's price for those strides", async () => {
    await expect(page.getByRole("heading", { name: "A few quick questions" })).toBeVisible();
    await page.getByRole("group", { name: "How often?" }).getByRole("button", { name: /^Every 2 weeks/ }).click();
    await page.getByRole("button", { name: "See my price" }).click();
    await expect(page.getByText("Priced for 2 lawns paced out, about 250 m² in total.")).toBeVisible();
    const shown = await page.locator(".price-big").innerText();
    const quote = await api(page, "POST", "/api/quotes", { category_id: "mowing", answers: { frequency: "fortnightly" }, lawn: LAWNS });
    expect(quote.measure).toMatchObject({ method: "paced", unit: "strides", area_m2: 250, estimator: "customer_measured_v0" });
    guide = quote.result.price_pence;
    expect(shown).toBe(pounds(guide));
    expect(quote.confidence.label).toBe("Fairly close");
  });

  await test.step("she requests it; the request says what the price is for", async () => {
    await page.getByRole("button", { name: "Request this job" }).click();
    await page.getByRole("checkbox", { name: /I agree to the customer terms/ }).click();
    await page.getByRole("button", { name: "Send my request" }).click();
    await expect(page.getByRole("heading", { name: "Finding someone local" })).toBeVisible();
    ref = page.url().split("/requests/")[1];
    await expect(page.getByText(/for 2 lawns paced out, about 250 m² in total\./)).toBeVisible();
  });

  await test.step("Dave sees both lawns on the job and books it at the guide", async () => {
    await signInAs(page, "dave", "/p");
    const alert = await message(page, "job_alert", PHONES.dave);
    expect(alert.body).toContain(`/p/j/${ref}`);
    await page.goto(`/p/j/${ref}`);
    await expect(page.getByText("About 250 m² across 2 lawns")).toBeVisible();
    const day = await acceptAtGuide(page, ref, pounds(guide));
    expect(day).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    await signInAs(page, "sarah", `/requests/${ref}`);
    const req = await api(page, "GET", `/api/c/requests/${ref}`);
    expect(req.status).toBe("booked");
    expect(req.size_text).toBe("2 lawns paced out, about 250 m² in total");
  });
});

test("I2: Dave finishes a visit typing exactly 47 minutes", async ({ page }) => {
  await signInAs(page, "sarah", "/");
  const ref = await requestMowing(page);
  await signInAs(page, "dave", "/p");
  const day = await acceptAtGuide(page, ref, "£31");
  const finished = page.waitForResponse(
    async (r) => r.url().endsWith("/finish") && r.request().method() === "POST" && (await r.request().postDataJSON()).minutes === 47,
  );
  // Sarah's first visit that day (I1's lawns may come first): whichever it is, it took 47 minutes.
  const heading = await finishVisit(page, { day, customer: "Sarah", minutes: 47 });
  expect(heading).toMatch(/is on its way/);
  const out = await (await finished).json();
  expect(out.minutes_actual).toBe(47);
  const visit = await api(page, "GET", `/api/p/visits/${out.visit_id}`);
  expect(visit.minutes_actual).toBe(47);
});
