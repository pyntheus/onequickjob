import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { routes } from "../App";
import { config, jsonResponse, mockApi } from "../test/utils";

const me = {
  user_id: "u1", name: "Dave Hughes", phone: "07700 900201", email: null, roles: ["provider"],
  customer_id: null, provider_id: "p1", helper_of: null, home_path: "/p",
};
const limit = { on: true, period: "week", amount_pence: 25000, earned_pence: 21250, remaining_pence: 3750, reached: false, resumes_on: "2026-10-05", used_percent: 85 };
const card = {
  request_ref: "R-2292", category_id: "cleaning", category_name: "Regular cleaning", area: "Hazlemere", district: "HP15",
  miles: 1.2, mins: 120, frequency_label: "Every 2 weeks", guide_pence: 6600, provider_pence: 5610, unit: "a clean",
  posted_at: new Date().toISOString(), route_hint: "0.4 miles from your 9:00 on Tuesday", state: null, over_limit: true,
  is_cover: false, cover_date: null,
};
const offer = {
  card, approx: { lat: 51.65, lng: -0.71 },
  facts: [{ label: "Bedrooms", value: "3 bedrooms" }, { label: "Estimate", value: "About 2 hours" }],
  note: "The side gate sticks.", customer: { initials: "SW", name: "Sarah W.", meta: "3 past bookings, pays by card" },
  fee_percent: 15, my_counter: null, can_take: true, missing_documents: [], over_limit_by_pence: 1860, booked_by_me: false,
  first_visit_text: null, request_status: "open", unit: "a clean", first_pence: 8800, first_provider_pence: 7480,
  first_reason: "The first clean takes longer.", is_cover: false, cover_text: null, can_counter: true,
  counter_min_pence: 5300, counter_max_pence: 19800, counter_start_pence: 7900,
  counter_reasons: ["Bigger job than described", "Further than I usually go"], counter_note: null,
  not_eligible_reasons: [], address_line: null, first_visit_date: null,
};

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("the provider app", () => {
  it("lists jobs near you with the limit strip and over-limit marking", async () => {
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": () => me,
      "GET /api/p/home": () => ({
        greeting: "Morning, Dave", today_text: "Saturday 3 October", week_earned_pence: 21250, week_jobs: 7,
        rating_avg: 4.9, rating_count: 38, limit, new_jobs: [card], coming_up: [], status: "active", helper: false,
        unread_messages: 0,
      }),
    });
    renderAt("/p");
    expect(await screen.findByRole("heading", { name: "Morning, Dave" })).toBeInTheDocument();
    expect(screen.getByText("£212.50")).toBeInTheDocument();
    expect(screen.getByText("£37.50 left")).toBeInTheDocument();
    const job = screen.getByRole("link", { name: "Regular cleaning in Hazlemere, guide price £66" });
    expect(job).toHaveAttribute("href", "/p/j/R-2292");
    expect(within(job).getByText("Over your weekly limit")).toBeInTheDocument();
    expect(within(job).getByText("you get £56.10")).toBeInTheDocument();
  });

  it("sends a new provider to sign-up", async () => {
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": () => me,
      "GET /api/p/home": () => ({
        greeting: "Morning, Ken", today_text: "", week_earned_pence: 0, week_jobs: 0, rating_avg: null, rating_count: 0,
        limit: { ...limit, on: false }, new_jobs: [], coming_up: [], status: "signing_up", helper: false, unread_messages: 0,
      }),
      "GET /api/p/signup": () => ({
        steps: [{ key: "details", title: "Your details", detail: "Name, home and phone", state: "done" },
          { key: "identity", title: "Check your ID", detail: "", state: "now" }],
        done_count: 1, provider_id: "p1", status: "signing_up", payment_account_status: "none", limit_on: false,
      }),
      "GET /api/p/documents": () => [],
    });
    const router = renderAt("/p");
    expect(await screen.findByRole("heading", { name: "Let's get you set up" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/p/signup");
    expect(screen.getByRole("link", { name: /Set an earnings limit/ })).toHaveAttribute("href", "/p/limit");
  });

  it("shows a counter's first-visit price from the API, never its own maths (A1)", async () => {
    const posts: unknown[] = [];
    const previews: string[] = [];
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": () => me,
      "GET /api/p/limit": () => limit,
      "GET /api/p/requests/R-2292": () => offer,
      "GET /api/p/requests/R-2292/counter-preview": (url) => {
        const p = Number(url.searchParams.get("price_pence"));
        previews.push(String(p));
        return {
          price_pence: p, first_price_pence: p === 7900 ? 10500 : 99999, provider_pence: 1, first_provider_pence: 2,
          fee_percent: 15, text: `API SAYS ${p}`, valid: true, problem: null,
        };
      },
      "POST /api/p/requests/R-2292/counter": async (_url, req) => {
        posts.push(await req.json());
        return { id: "o1", price_pence: 7900, status: "pending" };
      },
    });
    renderAt("/p/j/R-2292");
    expect(await screen.findByRole("heading", { name: "Regular cleaning" })).toBeInTheDocument();
    expect(screen.getByText("Fits your round")).toBeInTheDocument();
    expect(screen.getByText(/Taking this would put you £18.60 over your weekly limit/)).toBeInTheDocument();
    expect(screen.getByText(/First visit £88, you get £74.80/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Suggest a different price" }));
    expect(await screen.findByText("API SAYS 7900")).toBeInTheDocument();
    expect(screen.getByText("£0.01")).toBeInTheDocument(); // "You'd get" is the API's figure, whatever it is
    await userEvent.click(screen.getByRole("button", { name: "Bigger job than described" }));
    await userEvent.click(screen.getByRole("button", { name: "Send £79 to Sarah" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toEqual({ price_pence: 7900, reasons: ["Bigger job than described"], message: "" });
    expect(previews).toContain("7900");
  });

  it("says when someone else got there first", async () => {
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": () => me,
      "GET /api/p/limit": () => limit,
      "GET /api/p/requests/R-2292": () => ({ ...offer, over_limit_by_pence: null }),
      "POST /api/p/requests/R-2292/accept": () =>
        jsonResponse(409, { detail: { code: "already_taken", message: "Sorry, someone else took this job first." } }),
    });
    renderAt("/p/j/R-2292");
    await userEvent.click(await screen.findByRole("button", { name: "Accept at £66" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Sorry, someone else took this job first.");
  });

  it("saves only the limit, never the benefits answer", async () => {
    const puts: unknown[] = [];
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": () => me,
      "GET /api/p/limit": () => ({ ...limit, on: false }),
      "GET /api/p/limit/preview": (url) => ({
        ...limit, period: url.searchParams.get("period"), amount_pence: Number(url.searchParams.get("amount_pence")),
      }),
      "PUT /api/p/limit": async (_url, req) => {
        const body = await req.json();
        puts.push(body);
        return { ...limit, ...(body as object) };
      },
      "GET /api/p/home": () => ({ greeting: "", today_text: "", week_earned_pence: 0, week_jobs: 0, rating_avg: null, rating_count: 0, limit, new_jobs: [], coming_up: [], status: "active", helper: false, unread_messages: 0 }),
    });
    renderAt("/p/limit");
    await userEvent.click(await screen.findByRole("switch", { name: /Use an earnings limit/ }));
    await userEvent.click(screen.getByRole("button", { name: "Universal Credit" }));
    expect(screen.getByText(/assessed monthly/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Month" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toEqual({ on: true, period: "month", amount_pence: 25000 });
    expect(JSON.stringify(puts[0])).not.toMatch(/universal|benefit|uc/i);
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toMatch(/universal|benefit/i);
  });

  it("finishes a job with exclusive flags and shows what's on its way", async () => {
    const posts: unknown[] = [];
    const visit = {
      id: "v1", booking_id: "b1", category_id: "mowing", category_name: "Lawn mowing", customer_name: "Sarah W.",
      address_line: "12 Orchard Way, Hazlemere", directions_url: "https://maps", local_date: "2026-10-03",
      scheduled_start: "2026-10-03T08:00:00Z", status: "in_progress", est_mins: 38, started_at: "2026-10-03T08:00:00Z",
      finished_at: null, minutes_actual: null, before_photos: [], after_photos: [], note: "", thread_id: "t1",
      price_pence: 3000, provider_pence: 2550, charge_status: "none", performer_name: "Dave H.",
      category_name_lower: "lawn mowing", customer_first: "Sarah", summary: "", window_text: "", is_first: false,
      performer: "provider", elapsed_seconds: 2940, can_start: false, start_note: null, early_start_demo: false, flags: [],
      flags_none: false, minutes_from_timer: false, overrun: null, fee_percent: 15,
    };
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": () => me,
      "GET /api/p/visits/v1": () => visit,
      "POST /api/p/visits/v1/finish": async (_url, req) => {
        posts.push(await req.json());
        return {
          visit_id: "v1", minutes_actual: 49, est_mins: 38, overrun: true, charge_status: "succeeded", price_pence: 3000,
          fee_pence: 450, provider_pence: 2550, payout_date: "2026-10-09",
          charge_message: "It'll reach your bank with the next payout.", customer_first: "Sarah",
        };
      },
    });
    renderAt("/p/visits/v1/finish");
    expect(await screen.findByText(/From your timer\. The estimate was 38 minutes, so 11 minutes over\./)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Grass was longer than described" }));
    await userEvent.click(screen.getByRole("button", { name: "Nothing, it was as described" }));
    expect(screen.getByRole("button", { name: "Grass was longer than described" })).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(screen.getByRole("button", { name: "Access was harder" }));
    await userEvent.click(screen.getByRole("button", { name: "Send and get paid" }));
    expect(await screen.findByRole("heading", { name: "£25.50 is on its way" })).toBeInTheDocument();
    expect(posts[0]).toEqual({ minutes: 49, from_timer: true, flags: ["Access was harder"], nothing_different: false, note: "" });
  });

  it("starts today's job from the round", async () => {
    let started = false;
    const item = {
      visit_id: "v1", start_time: "10:30", status: "scheduled", is_now: true, category_name: "Lawn mowing",
      address_line: "12 Orchard Way, Hazlemere", area: "Hazlemere", customer_name: "Sarah W.", est_mins: 38,
      minutes_actual: null, summary: "", note: "", miles_from_previous: 0.4, performer: "provider", category_id: "mowing",
      performer_name: "Dave H.", cover_state: "none", cover_allowed: true, charge_status: "none", is_first: false,
    };
    const visit = (status: string) => ({
      id: "v1", booking_id: "b1", category_id: "mowing", category_name: "Lawn mowing", customer_name: "Sarah W.",
      address_line: "12 Orchard Way, Hazlemere, HP15 7QT", directions_url: "https://www.google.com/maps/dir/?api=1",
      local_date: "2026-10-03", scheduled_start: "2026-10-03T09:30:00Z", status, est_mins: 38,
      started_at: status === "in_progress" ? new Date().toISOString() : null, finished_at: null, minutes_actual: null,
      before_photos: [], after_photos: [], note: "The dog's out.", thread_id: "t1", price_pence: 3000, provider_pence: 2550,
      charge_status: "none", performer_name: "Dave H.", category_name_lower: "lawn mowing", customer_first: "Sarah",
      summary: "Side gate", window_text: "", is_first: false, performer: "provider",
      elapsed_seconds: status === "in_progress" ? 0 : null, can_start: status === "scheduled", start_note: null,
      early_start_demo: false, flags: [], flags_none: false, minutes_from_timer: false, overrun: null, fee_percent: 15,
    });
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": () => me,
      "GET /api/p/today": () => ({ local_date: "2026-10-03", day_text: "Saturday 3 October", items: [item], helpers: [], is_today: true, upcoming_days: [] }),
      "GET /api/p/visits/v1": () => visit(started ? "in_progress" : "scheduled"),
      "POST /api/p/visits/v1/start": () => {
        started = true;
        return visit("in_progress");
      },
    });
    renderAt("/p/today");
    expect(await screen.findByRole("heading", { name: "Today's round" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: /Directions/ })).toHaveAttribute("href", "https://www.google.com/maps/dir/?api=1");
    expect(screen.getByRole("link", { name: /Message/ })).toHaveAttribute("href", "/p/messages/t1");
    await userEvent.click(screen.getByRole("button", { name: /I've arrived, start the job/ }));
    expect(await screen.findByRole("timer")).toHaveTextContent("0:0");
    expect(screen.getByRole("button", { name: "Finish job" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Demo: add 10 min/ })).not.toBeInTheDocument();
  });

  it("ignores stored demo minutes when demo mode is off", async () => {
    sessionStorage.setItem("oqj.p.demoExtraMins.v1", "50");
    const item = {
      visit_id: "v1", start_time: "10:30", status: "in_progress", is_now: true, category_name: "Lawn mowing",
      address_line: "12 Orchard Way, Hazlemere", area: "Hazlemere", customer_name: "Sarah W.", est_mins: 38,
      minutes_actual: null, summary: "", note: "", miles_from_previous: 0.4, performer: "provider", category_id: "mowing",
      performer_name: "Dave H.", cover_state: "none", cover_allowed: true, charge_status: "none", is_first: false,
    };
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": () => me,
      "GET /api/p/today": () => ({ local_date: "2026-10-03", day_text: "Saturday 3 October", items: [item], helpers: [], is_today: true, upcoming_days: [] }),
      "GET /api/p/visits/v1": () => ({
        id: "v1", booking_id: "b1", category_id: "mowing", category_name: "Lawn mowing", customer_name: "Sarah W.",
        address_line: "12 Orchard Way", directions_url: "https://maps", local_date: "2026-10-03",
        scheduled_start: "2026-10-03T09:30:00Z", status: "in_progress", est_mins: 38, started_at: new Date().toISOString(),
        finished_at: null, minutes_actual: null, before_photos: [], after_photos: [], note: "", thread_id: null,
        price_pence: 3000, provider_pence: 2550, charge_status: "none", performer_name: "Dave H.",
        category_name_lower: "lawn mowing", customer_first: "Sarah", summary: "", window_text: "", is_first: false,
        performer: "provider", elapsed_seconds: 600, can_start: false, start_note: null, early_start_demo: false,
        flags: [], flags_none: false, minutes_from_timer: false, overrun: null, fee_percent: 15,
      }),
    });
    renderAt("/p/today");
    expect(await screen.findByRole("timer")).toHaveTextContent(/^10:0\d$/);
    expect(screen.getByText("Estimate 38 minutes")).toBeInTheDocument();
    sessionStorage.clear();
  });

  it("lets a helper added in the app in, as a helper", async () => {
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": () => ({ ...me, name: "Tom Hughes", roles: [], provider_id: null, helper_of: null }),
      "GET /api/p/home": () => ({
        greeting: "Morning, Tom", today_text: "Saturday 3 October", week_earned_pence: 0, week_jobs: 0, rating_avg: null,
        rating_count: 0, limit, new_jobs: [], coming_up: [], status: "active", helper: true, unread_messages: 0,
      }),
    });
    renderAt("/p");
    expect(await screen.findByRole("heading", { name: "Morning, Tom" })).toBeInTheDocument();
    expect(screen.getByText(/the visits you've been sent to/)).toBeInTheDocument();
    expect(screen.queryByText("New jobs near you")).not.toBeInTheDocument();
  });
});


describe("a link that signs in someone else", () => {
  it("drops the last user's figures, even when the new user's refetch is refused", async () => {
    let who: "dave" | "tom" = "dave";
    const tom = { ...me, user_id: "u2", name: "Tom Hughes", roles: [], provider_id: null, helper_of: "p1" };
    const earnings = {
      week_net_pence: 21250, week_jobs: 7, weekly: [], payouts: [], next_payout_date: null, limit,
      own_customers_active: 0, bank_last4: "4321", pending_pence: 0,
    };
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": () => (who === "dave" ? me : tom),
      "GET /api/p/earnings": () =>
        who === "dave"
          ? earnings
          : jsonResponse(403, { detail: { code: "helpers_cant", message: "This part of the app is for Dave. You can see your visits on Today." } }),
      "POST /api/auth/magic": () => ((who = "tom"), { me: tom, next: "/p/earnings" }),
    });
    const router = renderAt("/p/earnings");
    expect(await screen.findByText("£212.50")).toBeInTheDocument();
    await act(() => router.navigate("/p/earnings?t=tok"));
    expect(await screen.findByText(/This part of the app is for Dave/)).toBeInTheDocument();
    expect(screen.queryByText("£212.50")).not.toBeInTheDocument();
    expect(router.state.location.search).toBe("");
  });
});

describe("a photo reply that arrives after someone else signed in", () => {
  it("is dropped: the last user's visit never comes back into the cache", async () => {
    let who: "dave" | "mike" = "dave";
    const mike = { ...me, user_id: "u3", name: "Mike Reynolds", provider_id: "p3" };
    const item = {
      visit_id: "v1", start_time: "10:30", status: "in_progress", is_now: true, category_name: "Lawn mowing",
      address_line: "12 Orchard Way, Hazlemere", area: "Hazlemere", customer_name: "Sarah W.", est_mins: 38,
      minutes_actual: null, summary: "", note: "", miles_from_previous: 0.4, performer: "provider", category_id: "mowing",
      performer_name: "Dave H.", cover_state: "none", cover_allowed: true, charge_status: "none", is_first: false,
    };
    const visit = (after: string[]) => ({
      id: "v1", booking_id: "b1", category_id: "mowing", category_name: "Lawn mowing", customer_name: "Sarah W.",
      address_line: "12 Orchard Way, Hazlemere, HP15 7QT", directions_url: "https://www.google.com/maps/dir/?api=1",
      local_date: "2026-10-03", scheduled_start: "2026-10-03T09:30:00Z", status: "in_progress", est_mins: 38,
      started_at: new Date().toISOString(), finished_at: null, minutes_actual: null, before_photos: [], after_photos: after,
      note: "The dog's out.", thread_id: "t1", price_pence: 3000, provider_pence: 2550, charge_status: "none",
      performer_name: "Dave H.", category_name_lower: "lawn mowing", customer_first: "Sarah", summary: "Side gate",
      window_text: "", is_first: false, performer: "provider", elapsed_seconds: 0, can_start: false, start_note: null,
      early_start_demo: false, flags: [], flags_none: false, minutes_from_timer: false, overrun: null, fee_percent: 15,
    });
    let release: (v: unknown) => void = () => undefined;
    const photoSent = vi.fn();
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": () => (who === "dave" ? me : mike),
      "GET /api/p/today": () => ({
        local_date: "2026-10-03", day_text: "Saturday 3 October", items: who === "dave" ? [item] : [], helpers: [],
        is_today: true, upcoming_days: [],
      }),
      "GET /api/p/visits/v1": () =>
        who === "dave" ? visit([]) : jsonResponse(404, { detail: { code: "not_found", message: "That visit isn't on your round." } }),
      "POST /api/files": () => ({ id: "f1", url: "/files/f1.png", kind: "visit_after", content_type: "image/png", size: 8 }),
      "POST /api/p/visits/v1/photos": () => (photoSent(), new Promise((resolve) => (release = resolve))),
      "POST /api/auth/magic": () => ((who = "mike"), { me: mike, next: "/p/today" }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const router = createMemoryRouter(routes, { initialEntries: ["/p/today"] });
    render(
      <QueryClientProvider client={qc}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    await userEvent.upload(await screen.findByLabelText(/After photo/), new File(["png"], "after.png", { type: "image/png" }));
    await waitFor(() => expect(photoSent).toHaveBeenCalled());
    await act(() => router.navigate("/p/today?t=tok"));
    expect(await screen.findByText(/Nothing booked today/)).toBeInTheDocument();
    await act(async () => release(visit(["/files/f1.png"])));
    await waitFor(() => expect(qc.isMutating()).toBe(0));
    const cached = qc.getQueryData(["p", "visit", "v1"]) as { address_line?: string } | undefined;
    expect(cached?.address_line).toBeUndefined();
    expect(screen.queryByText(/12 Orchard Way/)).not.toBeInTheDocument();
  });
});

describe("a plan change, answered in the provider app (A10)", () => {
  const change = {
    status: "pending", customer_first_name: "Sarah", provider_first_name: "Dave", category_name: "Lawn mowing",
    area: "Hazlemere", from_frequency_label: "every 2 weeks", to_frequency_label: "every week", from_price_pence: 3100,
    to_price_pence: 2800, provider_pence: 2380, expires_at: "2026-10-05T09:00:00Z",
  };
  const unauthorised = () => jsonResponse(401, { detail: { code: "not_signed_in", message: "Please sign in." } });

  it("needs no sign-in: the link's token is the authority, and declining keeps the plan", async () => {
    let declined = false;
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": unauthorised,
      "GET /api/c/plan-changes/tok9": () => change,
      "POST /api/c/plan-changes/tok9/decline": () => ((declined = true), { ...change, status: "declined" }),
    });
    renderAt("/p/plan-change/tok9");
    expect(await screen.findByRole("heading", { name: "Sarah would like visits every week" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Send code/ })).not.toBeInTheDocument();
    expect(screen.getByText("£23.80 a visit, after the OneQuickJob fee")).toBeInTheDocument();
    expect(screen.getByText(/Please answer by Monday 5 October at 10:00/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Keep it as it is" }));
    expect(await screen.findByText("You declined this change. The plan stays as it was.")).toBeInTheDocument();
    expect(declined).toBe(true);
  });

  it("sends the old customer-web address on to the provider app", async () => {
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": unauthorised,
      "GET /api/c/plan-changes/tok9": () => change,
    });
    const router = renderAt("/plan-change/tok9");
    expect(await screen.findByRole("heading", { name: "Sarah would like visits every week" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/p/plan-change/tok9");
  });

  it("shows the change as it is now when it closed meanwhile (409)", async () => {
    let answered = false;
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": () => me,
      "GET /api/p/home": () => ({ greeting: "", today_text: "", week_earned_pence: 0, week_jobs: 0, rating_avg: null,
        rating_count: 0, limit, new_jobs: [], coming_up: [], status: "active", helper: false, unread_messages: 0 }),
      "GET /api/c/plan-changes/tok9": () => (answered ? { ...change, status: "withdrawn" } : change),
      "POST /api/c/plan-changes/tok9/accept": () => (
        (answered = true),
        jsonResponse(409, { detail: { code: "not_pending", message: "Sarah has withdrawn this change." } })
      ),
    });
    renderAt("/p/plan-change/tok9");
    await userEvent.click(await screen.findByRole("button", { name: "Accept £28 a visit" }));
    expect(await screen.findByText("The customer withdrew or replaced this change.")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Provider" })).toBeInTheDocument();
  });
});
