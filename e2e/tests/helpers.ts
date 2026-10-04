// Shared steps for the journeys. People sign in the way the demo does: the Switch user endpoint
// (DEMO_MODE), which sets the session cookie in the browser context; or, for someone who isn't
// seeded yet (Mary), with the code from the Outbox drawer. API calls go through the same
// browser context (page.request), so they carry the same session and basic auth.
import { expect, type APIRequestContext, type Page } from "@playwright/test";

export type DemoUser = { user_id: string; demo_key: string; name: string; home_path: string };

export async function demoUsers(request: APIRequestContext): Promise<DemoUser[]> {
  const r = await request.get("/api/demo/users");
  expect(r.ok(), await r.text()).toBeTruthy();
  return r.json();
}

/** Sign in as a seeded person (Switch user) and open their home page. */
export async function signInAs(page: Page, key: string, path?: string): Promise<DemoUser> {
  const users = await demoUsers(page.request);
  const user = users.find((u) => u.demo_key === key);
  if (!user) throw new Error(`no demo user ${key}`);
  const r = await page.request.post("/api/demo/switch", { data: { user_id: user.user_id } });
  expect(r.ok(), await r.text()).toBeTruthy();
  await page.goto(path ?? user.home_path);
  return user;
}

/** GET or POST the API as the signed-in person; fails the test unless it answers 2xx. */
export async function api<T = any>(page: Page, method: "GET" | "POST" | "PATCH", path: string, data?: unknown): Promise<T> {
  const r = await page.request.fetch(path, { method, data });
  expect(r.ok(), `${method} ${path}: ${r.status()} ${await r.text()}`).toBeTruthy();
  return r.status() === 204 ? (undefined as T) : r.json();
}

export type OutboxItem = { id: string; template_id: string; body: string; recipient: { name?: string; phone?: string } };

/** The latest outbox messages (the demo drawer's feed), newest first. */
export async function outbox(page: Page): Promise<OutboxItem[]> {
  return api(page, "GET", "/api/demo/outbox?limit=100");
}

/** The newest message of a template (optionally to a phone number), waiting for it to arrive. */
export async function message(page: Page, template: string, phone?: string): Promise<OutboxItem> {
  let found: OutboxItem | undefined;
  await expect
    .poll(async () => {
      found = (await outbox(page)).find((m) => m.template_id === template && (!phone || m.recipient.phone === phone));
      return !!found;
    }, { message: `outbox message ${template}` })
    .toBe(true);
  return found!;
}

/** The path of the link in a message (texts carry full URLs on the public name). */
export function linkIn(body: string): string {
  const m = body.match(/https?:\/\/[^\s]+/);
  if (!m) throw new Error(`no link in: ${body}`);
  return new URL(m[0]).pathname + new URL(m[0]).search;
}

export const PHONES = {
  sarah: "+447700900123",
  dave: "+447700900201",
  mary: "+447700900140",
  pat: "+447700900137",
} as const;

/** Pounds as the app shows them: £31, £22.50. */
export function pounds(pence: number): string {
  return pence % 100 ? `£${(pence / 100).toFixed(2)}` : `£${pence / 100}`;
}

const FIXTURES = new URL("../fixtures/", import.meta.url).pathname;

/** The provider's Today round for a day: work through it until the visit for `customer` (their
 * first name, e.g. "Sarah") is the one on, start it (DEMO_MODE lets a future visit start now),
 * add before and after photos, and finish it, with an overrun and a flag if asked. Earlier visits
 * that day are finished plainly first. Returns the finish screen's heading ("£26.35 is on its way"). */
export async function finishVisit(
  page: Page,
  opts: { day: string; customer: string; overrun?: boolean; photos?: boolean },
): Promise<string> {
  await page.goto(`/p/today?date=${opts.day}`);
  for (let i = 0; i < 8; i++) {
    const card = page.locator(".round-item.now");
    // The card shows "Loading…" until the visit's details arrive with its start button: only then
    // does it say whose visit it is.
    const start = card.getByRole("button", { name: /start it now|start the job/ });
    await expect(start).toBeVisible();
    const mine = (await card.innerText()).includes(`for ${opts.customer}`);
    await start.click();
    await expect(card.getByRole("timer")).toBeVisible();
    if (mine && opts.photos !== false) {
      await page.getByLabel("Before photo").setInputFiles(FIXTURES + "lawn-before.png");
      await expect(card.getByText(/Before photo/).first()).toBeVisible();
      await page.getByLabel("After photo").setInputFiles(FIXTURES + "lawn-after.png");
      await expect(page.getByLabel("After photo")).toBeEnabled();
    }
    await card.getByRole("button", { name: "Finish job" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    if (mine && opts.overrun) {
      const est = Number((await page.getByText(/The estimate was \d+ minutes/).innerText()).match(/estimate was (\d+)/)![1]);
      const minutes = page.getByRole("group", { name: "Minutes taken" });
      while (Number((await minutes.innerText()).match(/(\d+) min/)![1]) <= est * 1.1) {
        await page.getByRole("button", { name: "More: Minutes taken" }).click();
      }
      await page.getByRole("button", { name: /longer than described|bigger than described|Access was harder/ }).first().click();
    } else {
      await page.getByRole("button", { name: "Nothing, it was as described" }).click();
    }
    await page.getByRole("button", { name: "Send and get paid" }).click();
    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toHaveText(/is on its way|Job recorded|Done, thank you/);
    if (mine) return heading.innerText();
    await page.goto(`/p/today?date=${opts.day}`);
  }
  throw new Error(`never reached ${opts.customer}'s visit on ${opts.day}`);
}

/** Accept a job at its guide on the provider's job page; returns the booking's first visit day. */
export async function acceptAtGuide(page: Page, ref: string, guide: string): Promise<string> {
  await page.goto(`/p/j/${ref}`);
  const accepted = page.waitForResponse((r) => r.url().endsWith(`/api/p/requests/${ref}/accept`) && r.request().method() === "POST");
  await page.getByRole("button", { name: `Accept at ${guide}` }).click();
  const res = await accepted;
  expect(res.ok(), await res.text()).toBeTruthy();
  return (await res.json()).first_visit.local_date;
}

/** The standard fee (15%) on a price, half-up to the penny, as money.py works it out. */
export const standardFee = (pence: number) => Math.floor((pence * 15 + 50) / 100);
/** The own-customer fee: 5%, at least £1. */
export const ownFee = (pence: number) => Math.max(100, Math.floor((pence * 5 + 50) / 100));

/** Sarah's quote flow for lawn mowing at 12 Orchard Way (Large band), ending on "Finding someone
 * local"; `grass` is the grass question's answer. Returns the new request's reference. */
export async function requestMowing(page: Page, grass = "Recently cut", frequency = "Every 2 weeks"): Promise<string> {
  await page.goto("/");
  await page.getByRole("button", { name: /Lawn mowing/ }).click();
  await page.getByRole("combobox", { name: "Your address" }).fill("Orchard");
  await page.getByRole("option", { name: /12 Orchard Way/ }).click();
  await page.getByRole("button", { name: "See my price" }).click();
  await page.getByRole("button", { name: /^Large/ }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "A few quick questions" })).toBeVisible();
  const starts = (label: string) => new RegExp(`^${label}`);
  await page.getByRole("group", { name: "How long is the grass right now?" }).getByRole("button", { name: starts(grass) }).click();
  await page.getByRole("group", { name: "How often?" }).getByRole("button", { name: starts(frequency) }).click();
  await page.getByRole("button", { name: "See my price" }).click();
  await page.getByRole("button", { name: "Request this job" }).click();
  await page.getByRole("checkbox", { name: /I agree to the customer terms/ }).click();
  await page.getByRole("button", { name: "Send my request" }).click();
  await expect(page.getByRole("heading", { name: "Finding someone local" })).toBeVisible();
  return page.url().split("/requests/")[1];
}

/** Confirm a phone number the way a new person does: the code from the Outbox (DEMO_MODE). */
export async function confirmNumber(page: Page, phone: string, national: string) {
  await page.getByLabel(/mobile number/i).fill(national);
  await page.getByRole("button", { name: /code/i }).first().click();
  const sent = await message(page, "login_code", phone);
  const code = sent.body.match(/\b(\d{6})\b/)![1];
  await page.getByLabel("Your code").fill(code);
  await page.getByRole("button", { name: "Confirm my number" }).click();
}
