// Accessibility and phone pass (runs after the journeys): every screen of the three surfaces, at
// the project's width (375px or desktop), signed in as the right person. On each: axe-core's
// WCAG 2.2 AA rules, no sideways scrolling, and in the provider area every tap target at least
// 44 by 44 px and a visible focus ring on the first few controls reached with Tab.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { api, linkIn, message, PHONES, signInAs } from "./helpers";

type Screen = { who: string | null; path: string; name: string; provider?: boolean };

async function screens(page: Page): Promise<Screen[]> {
  await signInAs(page, "sarah", "/account");
  const requests = await api(page, "GET", "/api/c/requests");
  const bookings = await api(page, "GET", "/api/c/bookings");
  const visits = await api(page, "GET", "/api/c/visits");
  const rateable = visits.done.find((v: { can_rate: boolean }) => v.can_rate);
  await signInAs(page, "admin_jo", "/admin");
  const providers = await api(page, "GET", "/api/admin/providers");
  const dave = providers.find((p: { short: string }) => p.short === "Dave H.");
  const invite = await message(page, "own_customer_invite", PHONES.mary);
  await signInAs(page, "dave", "/p");
  const jobs = await api(page, "GET", "/api/p/jobs");
  const openJob = jobs.find((j: { status?: string; request_ref: string }) => j.request_ref);
  const round = await api(page, "GET", "/api/p/today");
  return [
    { who: null, path: "/", name: "customer: landing (signed out)" },
    { who: null, path: "/signin", name: "sign in" },
    { who: null, path: linkIn(invite.body), name: "customer: own-customer invite" },
    { who: null, path: "/no-such-page", name: "not found" },
    { who: "sarah", path: "/", name: "customer: landing" },
    { who: "sarah", path: `/requests/${requests[0].ref}`, name: "customer: request (Finding someone local)" },
    { who: "sarah", path: `/bookings/${bookings[0].id}`, name: "customer: booking" },
    { who: "sarah", path: "/account", name: "customer: account, visits" },
    { who: "sarah", path: "/account?tab=plan", name: "customer: account, plan" },
    { who: "sarah", path: "/account?tab=messages", name: "customer: account, messages" },
    ...(rateable ? [{ who: "sarah", path: `/account/visits/${rateable.id}/rate`, name: "customer: rate a visit" }] : []),
    { who: "dave", path: "/p", name: "provider: jobs", provider: true },
    { who: "dave", path: `/p/j/${openJob.request_ref}`, name: "provider: a job", provider: true },
    { who: "dave", path: "/p/today", name: "provider: today", provider: true },
    ...(round.upcoming_days.length
      ? [{ who: "dave", path: `/p/today?date=${round.upcoming_days[0]}`, name: "provider: another day", provider: true }]
      : []),
    { who: "dave", path: "/p/earnings", name: "provider: earnings", provider: true },
    { who: "dave", path: "/p/tax", name: "provider: tax pack", provider: true },
    { who: "dave", path: "/p/limit", name: "provider: earnings limit", provider: true },
    { who: "dave", path: "/p/me", name: "provider: me", provider: true },
    { who: "dave", path: "/p/time-off", name: "provider: time off", provider: true },
    { who: "dave", path: "/p/own-customers", name: "provider: own customers", provider: true },
    { who: "dave", path: "/p/messages", name: "provider: messages", provider: true },
    { who: "tom", path: "/p", name: "provider: helper's home", provider: true },
    { who: "sarah", path: "/p/signup", name: "provider: sign-up", provider: true },
    { who: "admin_jo", path: "/admin", name: "admin: overview" },
    { who: "admin_jo", path: "/admin/providers", name: "admin: providers" },
    { who: "admin_jo", path: `/admin/providers/${dave.id}`, name: "admin: a provider" },
    { who: "admin_jo", path: "/admin/pricing", name: "admin: pricing and calibration" },
    { who: "admin_jo", path: "/admin/disputes", name: "admin: disputes" },
    { who: "admin_jo", path: "/admin/categories", name: "admin: categories" },
    { who: "admin_jo", path: "/admin/outbox", name: "admin: outbox" },
  ];
}

/** Interactive elements smaller than 44 x 44 px (inline links in running text are exempt, as in
 * WCAG 2.5.8, and visually hidden inputs whose visible label is the target). */
async function smallTargets(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const out: string[] = [];
    const sel = "a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=checkbox], [role=radio], [role=tab], [role=option], label[for]";
    for (const el of Array.from(document.querySelectorAll<HTMLElement>(sel))) {
      if (el.closest(".demo-fabs, .demo-menu, .demo-drawer, [role=dialog].drawer")) continue; // DEMO_MODE tools
      const r = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      if (r.width === 0 || r.height === 0 || style.visibility === "hidden" || el.classList.contains("sr-only")) continue;
      if (el.classList.contains("skip-link")) continue; // keyboard-only: full size once focused
      if (el.tagName === "LABEL") {
        // A label is the tap target only for a visually hidden control (the photo and file buttons).
        const control = document.getElementById(el.getAttribute("for") ?? "");
        if (!control || !control.classList.contains("sr-only")) continue;
      }
      if (el.tagName === "A" && el.closest("p, li, dd, .small, .xs") && !el.className.includes("btn")) continue;
      if (r.width < 44 || r.height < 44) {
        const name = (el.getAttribute("aria-label") || el.textContent || el.getAttribute("name") || el.tagName).trim().slice(0, 40);
        out.push(`${el.tagName.toLowerCase()} "${name}" ${Math.round(r.width)}x${Math.round(r.height)}`);
      }
    }
    return out;
  });
}

/** Tab through the first controls; each must show a focus indicator (outline or box-shadow). */
async function unfocusable(page: Page, presses = 8): Promise<string[]> {
  const out: string[] = [];
  await page.locator("body").press("Tab"); // the skip link
  for (let i = 0; i < presses; i++) {
    await page.keyboard.press("Tab");
    const info = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const s = getComputedStyle(el);
      const ring = (s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0) || (s.boxShadow && s.boxShadow !== "none");
      const name = el.getAttribute("aria-label") || el.textContent || (el as HTMLInputElement).type || el.tagName;
      return { ring, name: `${name.trim().slice(0, 40)} .${el.className}`, tag: el.tagName };
    });
    if (info && !info.ring) out.push(`${info.tag.toLowerCase()} "${info.name}"`);
  }
  return out;
}

/** Everything wrong with the page as it is now: axe (WCAG 2.2 AA), sideways scrolling, and in the
 * provider area small tap targets and controls with no visible focus. */
async function check(page: Page, provider: boolean): Promise<string[]> {
  await page.waitForTimeout(700); // queries settle (the demo drawer polls, so no networkidle)
  // At the bottom of the page the provider app's sticky nav sits below the content, as when a
  // user scrolls down to a button; at the top it covers whatever is behind it until they do.
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  const problems: string[] = [];
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  for (const v of axe.violations) {
    for (const n of v.nodes) problems.push(`axe ${v.id} (${v.impact}): ${n.target.join(" ")} ${n.failureSummary?.split("\n")[1]?.trim() ?? ""}`);
  }
  const sideways = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  if (sideways > 1) problems.push(`scrolls sideways by ${sideways}px`);
  if (provider) {
    for (const t of await smallTargets(page)) problems.push(`small target: ${t}`);
    for (const f of await unfocusable(page)) problems.push(`no visible focus: ${f}`);
  }
  return problems;
}

test("screens inside flows: the quote steps, the finish screen, the plan-change page", async ({ page }, info) => {
  test.setTimeout(300_000);
  const report: Record<string, string[]> = {};
  const note = async (name: string, provider = false) => {
    const problems = await check(page, provider);
    if (problems.length) report[name] = problems;
  };
  await signInAs(page, "sarah", "/");
  await page.getByRole("button", { name: /Lawn mowing/ }).click();
  await page.getByRole("combobox", { name: "Your address" }).fill("Orchard");
  await page.getByRole("option", { name: /12 Orchard Way/ }).click();
  await note("customer: landing with an address");
  await page.getByRole("button", { name: "See my price" }).click();
  await page.getByRole("button", { name: /^Large/ }).click();
  await note("customer: lawn size");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "A few quick questions" })).toBeVisible();
  await note("customer: questions");
  await page.getByRole("button", { name: "See my price" }).click();
  await expect(page.getByRole("button", { name: "Request this job" })).toBeVisible();
  await note("customer: guide price");
  await page.getByRole("button", { name: "Request this job" }).click();
  await expect(page.getByRole("button", { name: "Send my request" })).toBeVisible();
  await note("customer: contact and card");

  // Margaret asks for a new frequency (journey F1 may already have made her weekly): the
  // plan-change page Dave's text links to.
  await signInAs(page, "margaret", "/account?tab=plan");
  const [plan] = await api(page, "GET", "/api/c/plans");
  const frequency = plan.frequency === "weekly" ? "fortnightly" : "weekly";
  const priced = await api(page, "GET", `/api/c/plans/${plan.series_id}/reprice?frequency=${frequency}`);
  await api(page, "PATCH", `/api/c/plans/${plan.series_id}`, { frequency, expected_price_pence: priced.price_pence });
  const text = await message(page, "plan_change_proposed", PHONES.dave);
  await signInAs(page, "dave", linkIn(text.body));
  await expect(page.getByRole("heading", { name: /would like visits every/ })).toBeVisible();
  await note("provider: plan-change page", true);

  // The finish screen, on a visit started early (DEMO_MODE).
  const round = await api(page, "GET", "/api/p/today");
  await page.goto(`/p/today?date=${round.upcoming_days[0]}`);
  const card = page.locator(".round-item.now");
  await note("provider: a visit, before starting", true);
  await card.getByRole("button", { name: /start it now|start the job/ }).click();
  await expect(card.getByRole("timer")).toBeVisible();
  await note("provider: a visit under way", true);
  await card.getByRole("button", { name: "Finish job" }).click();
  await expect(page.getByRole("button", { name: "Send and get paid" })).toBeVisible();
  await note("provider: finish screen", true);

  console.log(`\n${info.project.name}: flows checked\n` + JSON.stringify(report, null, 2));
  expect(report).toEqual({});
});

test("every screen: WCAG 2.2 AA (axe), no sideways scroll; provider area: 44px targets and visible focus", async ({ page }, info) => {
  test.setTimeout(600_000);
  const list = await screens(page);
  const report: Record<string, string[]> = {};
  let signedInAs: string | null | undefined;
  for (const s of list) {
    if (s.who !== signedInAs) {
      if (s.who) await signInAs(page, s.who, "/");
      else await page.context().clearCookies();
      signedInAs = s.who;
    }
    await page.goto(s.path);
    await page.locator("main").first().waitFor();
    const problems = await check(page, !!s.provider);
    if (problems.length) report[`${s.name} (${s.path})`] = problems;
  }
  console.log(`\n${info.project.name}: ${list.length} screens checked\n` + JSON.stringify(report, null, 2));
  expect(report).toEqual({});
});
