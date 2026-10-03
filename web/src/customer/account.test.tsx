import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import type { Schemas } from "../api/client";
import { config, mockApi, unauthorised } from "../test/utils";
import { address, catalogue, me, mike } from "./test-fixtures";
import { json, renderAt } from "./test-render";

beforeEach(() => sessionStorage.clear());

const dave = { ...mike, provider_id: "p1", short: "Dave H.", first_name: "Dave", initials: "DH" };

function visit(over: Partial<Schemas["CustomerVisit"]> = {}): Schemas["CustomerVisit"] {
  return {
    id: "v1",
    booking_id: "b1",
    category_id: "mowing",
    category_name: "Lawn mowing",
    provider_short: "Dave H.",
    provider_first_name: "Dave",
    recurring: true,
    local_date: "2026-10-13",
    scheduled_start: "2026-10-13T08:00:00Z",
    window: "morning",
    status: "scheduled",
    label: "booked",
    price_pence: 3100,
    minutes_actual: null,
    after_photo_url: null,
    rating_stars: null,
    can_rate: false,
    can_skip: true,
    can_report: false,
    can_change_date: false,
    thread_id: "t1",
    dispute_ref: null,
    tip_pence: 0,
    ...over,
  } as Schemas["CustomerVisit"];
}

const profile = { customer_id: "c1", name: "Sarah Whitfield", phone: "+447700900123", email: null, addresses: [address], card: null };
const plan = {
  series_id: "s1",
  booking_id: "b1",
  category_id: "mowing",
  category_name: "Lawn mowing",
  outside: true,
  provider: dave,
  frequency: "fortnightly",
  frequency_label: "every 2 weeks",
  price_pence: 3100,
  unit: "a visit",
  status: "active",
  pause_winter: false,
  away_from: null,
  away_to: null,
  cover_when_away: true,
  next_visit_date: "2026-10-13",
  pending_change: null,
  frequency_options: [
    { value: "weekly", label: "every week" },
    { value: "fortnightly", label: "every 2 weeks" },
    { value: "threeweekly", label: "every 3 weeks" },
  ],
};
const done = visit({ id: "v0", local_date: "2026-09-29", status: "finished", label: "done", minutes_actual: 38, can_rate: true, can_skip: false, can_report: true });

function accountApi(extra: Record<string, (url: URL, req: Request) => unknown> = {}) {
  return mockApi({
    "GET /api/config": () => config(false),
    "GET /api/auth/me": () => me,
    "GET /api/categories": () => catalogue,
    "GET /api/c/profile": () => profile,
    "GET /api/c/visits": () => ({ next_visit: visit(), upcoming: [visit(), visit({ id: "v2", local_date: "2026-10-27", label: "planned" })], done: [done] }),
    "GET /api/c/plans": () => [plan],
    "GET /api/c/bookings": () => [],
    "GET /api/c/requests": () => [],
    "GET /api/c/threads": () => [{ id: "t1", kind: "booking", title: "Lawn mowing with Dave H.", other_party: "Dave H.", last_message_at: null, preview: "", unread: 1 }],
    "GET /api/c/threads/t1/messages": () => [
      { id: "m1", sender_user_id: "u9", sender_role: "provider", sender_name: "Dave H.", body: "See you Tuesday.", created_at: "2026-10-03T09:00:00Z", mine: false },
    ],
    ...extra,
  });
}

describe("my account", () => {
  it("shows the next visit, upcoming and done visits, and skips a visit", async () => {
    let skipped = "";
    accountApi({ "POST /api/c/visits/v1/skip": (url) => ((skipped = url.pathname), visit({ status: "skipped", label: "skipped" })) });
    renderAt("/account");
    expect(await screen.findByRole("heading", { name: "Hi Sarah" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Tuesday 13 October, morning" })).toBeInTheDocument();
    expect(screen.getByText("Lawn mowing with Dave H., £31")).toBeInTheDocument();
    expect(screen.getByText("Dave H., planned")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Rate" })).toHaveAttribute("href", "/account/visits/v0/rate");
    expect(screen.getByRole("tab", { name: "Messages (1)" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Skip this visit" }));
    await waitFor(() => expect(skipped).toBe("/api/c/visits/v1/skip"));
  });

  it("changes the plan: winter pause, cover, cancel; asks the provider about a new frequency (A10)", async () => {
    const patches: unknown[] = [];
    let cancelled = false;
    let repriced = "";
    window.confirm = () => true;
    accountApi({
      "PATCH /api/c/plans/s1": async (_u, req) => (patches.push(await req.json()), plan),
      "GET /api/c/plans/s1/reprice": (url) => (
        (repriced = url.searchParams.get("frequency") ?? ""),
        { frequency: "weekly", frequency_label: "every week", price_pence: 2800, current_price_pence: 3100 }
      ),
      "POST /api/c/plans/s1/cancel": () => ((cancelled = true), { ...plan, status: "cancelled" }),
    });
    renderAt("/account?tab=plan");
    expect(await screen.findByRole("heading", { name: "Lawn mowing, every 2 weeks" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("switch", { name: /Pause over winter/ }));
    await userEvent.click(screen.getByRole("switch", { name: /Cover when Dave's away/ }));
    await userEvent.click(screen.getByRole("button", { name: "Change how often" }));
    expect(screen.getByRole("button", { name: "Every 2 weeks" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Every week" }));
    expect(await screen.findByText(/the price would be/)).toHaveTextContent(
      "Every week, the price would be £28 a visit (it's £31 now). We'll ask Dave to accept it; your plan stays as it is unless they do.",
    );
    expect(repriced).toBe("weekly");
    await userEvent.click(screen.getByRole("button", { name: "Ask Dave" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel plan" }));
    await waitFor(() => expect(cancelled).toBe(true));
    expect(patches).toEqual([{ pause_winter: true }, { cover_when_away: false }, { frequency: "weekly" }]);
  });

  it("shows a frequency change waiting for the provider", async () => {
    accountApi({
      "GET /api/c/plans": () => [
        { ...plan, pending_change: { to_frequency: "weekly", to_frequency_label: "every week", to_price_pence: 2800, expires_at: "2026-10-05T09:00:00Z" } },
      ],
    });
    renderAt("/account?tab=plan");
    expect(await screen.findByText(/Waiting for Dave to accept every week at/)).toHaveTextContent(
      "Waiting for Dave to accept every week at £28 a visit. Your plan carries on as it is until then.",
    );
  });

  it("messages the provider", async () => {
    let posted: unknown = null;
    accountApi({
      "POST /api/c/threads/t1/messages": async (_u, req) => (
        (posted = await req.json()),
        json(201, { id: "m2", sender_user_id: "u1", sender_role: "customer", sender_name: "Sarah", body: "Thanks", created_at: "", mine: true })
      ),
    });
    renderAt("/account?tab=messages");
    expect(await screen.findByText("See you Tuesday.")).toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox", { name: "Message Dave" }), "The gate sticks{Enter}");
    await waitFor(() => expect(posted).toEqual({ body: "The gate sticks" }));
  });

  it("invites someone who hasn't booked to get a price", async () => {
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": () => me,
      "GET /api/c/profile": () => json(404, { detail: { code: "no_customer_profile", message: "x" } }),
      "GET /api/c/visits": () => json(404, { detail: { code: "no_customer_profile", message: "x" } }),
    });
    renderAt("/account");
    expect(await screen.findByRole("heading", { name: "You haven't booked anything yet" })).toBeInTheDocument();
  });

  it("asks a signed-out visitor to sign in", async () => {
    mockApi({ "GET /api/config": () => config(false), "GET /api/auth/me": unauthorised });
    renderAt("/account");
    expect(await screen.findByRole("heading", { name: "Sign in to your account" })).toBeInTheDocument();
  });
});

describe("rate a visit", () => {
  it("sends stars, tags and a fee-free tip, then confirms", async () => {
    let body: Record<string, unknown> = {};
    accountApi({
      "GET /api/c/visits/v0": () => done,
      "POST /api/c/visits/v0/rating": async (_u, req) => (
        (body = await req.json()),
        json(201, { id: "r1", visit_id: "v0", stars: 5, tags: ["Thorough"], tip_pence: 500, tip_status: "charged", tip_message: null })
      ),
    });
    renderAt("/account/visits/v0/rate");
    expect(await screen.findByRole("heading", { name: "How did Dave do?" })).toBeInTheDocument();
    expect(screen.getByText("All of it goes to Dave.")).toBeInTheDocument();
    const send = screen.getByRole("button", { name: "Send rating" });
    expect(send).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: "5 stars" }));
    await userEvent.click(screen.getByRole("button", { name: "Thorough" }));
    await userEvent.click(screen.getByRole("button", { name: "£5" }));
    await userEvent.click(send);
    expect(await screen.findByRole("heading", { name: "Thanks for rating Dave" })).toBeInTheDocument();
    expect(screen.getByText("Your £5 tip goes straight to Dave.")).toBeInTheDocument();
    expect(body).toEqual({ stars: 5, tags: ["Thorough"], tip_pence: 500, comment: "" });
  });

  it("reports a problem within 48 hours", async () => {
    let body: Record<string, unknown> = {};
    accountApi({
      "GET /api/c/visits/v0": () => done,
      "POST /api/c/visits/v0/problem": async (_u, req) => ((body = await req.json()), json(201, { dispute_id: "d1", ref: "D-016", status_text: "Waiting for Dave's reply" })),
    });
    renderAt("/account/visits/v0/rate?problem=1");
    expect(await screen.findByRole("heading", { name: "Tell us what happened" })).toBeInTheDocument();
    expect(screen.getByText(/usually a free return visit. Please let us know within 48 hours/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("What happened"), "The strip by the shed wasn't cut.");
    await userEvent.click(screen.getByRole("button", { name: "Report the problem" }));
    await waitFor(() => expect(body).toEqual({ description: "The strip by the shed wasn't cut.", photos: [] }));
  });

  it("points to messages after 48 hours", async () => {
    accountApi({ "GET /api/c/visits/v0": () => ({ ...done, can_report: false }) });
    renderAt("/account/visits/v0/rate?problem=1");
    expect(await screen.findByText(/more than 48 hours since the visit, so please message Dave/)).toBeInTheDocument();
  });
});

describe("booking confirmed", () => {
  it("shows the provider's checks, the terms, the split and who the agreement is with", async () => {
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": () => me,
      "GET /api/c/bookings/b1": () => ({
        id: "b1",
        ref: "B-1101",
        source: "platform",
        category_id: "cleaning",
        category_name: "Regular cleaning",
        provider: { ...mike, badges: [...mike.badges.slice(0, 1), { kind: "dbs", label: "Basic DBS checked", tone: "ok" }, ...mike.badges.slice(1)] },
        recurring: true,
        frequency_label: "every 2 weeks",
        price_pence: 6600,
        first_price_pence: 8800,
        unit: "a clean",
        split: { mode: "standard", rate_percent: 15, price_pence: 6600, fee_pence: 990, provider_pence: 5610 },
        charged_after: "each visit",
        first_visit_text: "Tuesday 6 October, morning, 8am to 12pm",
        status: "active",
        thread_id: "t1",
        series_id: "s1",
        address,
        agreement_text: "Your agreement for this job is with Mike. OneQuickJob arranged it, takes payment on their behalf through Stripe, and helps sort things out if anything goes wrong.",
        sms_sent_to: "07700 900123",
      }),
    });
    renderAt("/bookings/b1");
    expect(await screen.findByRole("heading", { name: "You're booked" })).toBeInTheDocument();
    for (const t of ["ID checked", "Basic DBS checked", "Insured until Mar 2027", "Lives 1.4 miles away"]) expect(screen.getByText(t)).toBeInTheDocument();
    expect(screen.getByText("£66 a clean, charged after each visit (first visit £88)")).toBeInTheDocument();
    expect(screen.getByText("£56.10 to Mike, £9.90 OneQuickJob fee")).toBeInTheDocument();
    expect(screen.getByText(/Your agreement for this job is with Mike/)).toBeInTheDocument();
    expect(screen.getByText("We've texted the details to 07700 900123.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Message Mike/ })).toHaveAttribute("href", "/account?tab=messages&thread=t1");
  });
});

describe("the provider's answer to a plan change (A10)", () => {
  const change = {
    status: "pending",
    customer_first_name: "Sarah",
    provider_first_name: "Dave",
    category_name: "Lawn mowing",
    area: "Hazlemere",
    from_frequency_label: "every 2 weeks",
    to_frequency_label: "every week",
    from_price_pence: 3100,
    to_price_pence: 2800,
    provider_pence: 2380,
    expires_at: "2026-10-05T09:00:00Z",
  };

  it("shows the API's prices and accepts", async () => {
    let accepted = false;
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": unauthorised,
      "GET /api/c/plan-changes/tok9": () => change,
      "POST /api/c/plan-changes/tok9/accept": () => ((accepted = true), { ...change, status: "accepted" }),
    });
    renderAt("/plan-change/tok9");
    expect(await screen.findByRole("heading", { name: "Sarah would like visits every week" })).toBeInTheDocument();
    expect(screen.getByText("£23.80 a visit, after the OneQuickJob fee")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Accept £28 a visit" }));
    expect(await screen.findByText("You accepted this change. The plan has been updated.")).toBeInTheDocument();
    expect(accepted).toBe(true);
  });

  it("says when a change has lapsed", async () => {
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": unauthorised,
      "GET /api/c/plan-changes/tok9": () => ({ ...change, status: "lapsed" }),
    });
    renderAt("/plan-change/tok9");
    expect(await screen.findByText(/lapsed after 48 hours/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Accept/ })).not.toBeInTheDocument();
  });
});
