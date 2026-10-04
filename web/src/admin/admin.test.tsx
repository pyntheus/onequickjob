import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../shared/Toast";
import { config, jsonResponse, mockApi, renderWithProviders } from "../test/utils";
import { poundsToPence } from "./util";
import Disputes from "./pages/Disputes";
import Overview from "./pages/Overview";
import Pricing from "./pages/Pricing";

const withToasts = (ui: ReactNode) => renderWithProviders(<ToastProvider>{ui}</ToastProvider>);
const jo = { user_id: "jo", name: "Jo Morgan", phone: null, email: null, roles: ["admin"], customer_id: null, provider_id: null, helper_of: null, home_path: "/admin" };

const waiting = {
  request_id: "r1",
  request_ref: "R-2291",
  category_id: "hedges",
  category_name: "Hedge trimming",
  area: "Loudwater",
  district: "HP10",
  waiting_since: "2026-10-02T22:15:00Z",
  age_text: "5 hours",
  guide_pence: 7200,
  brief: "12 m, taller than a person",
  why: "Two providers looked, nobody took it.",
  views: 2,
  pending_counters: 0,
};

const overview = {
  week_label: "Monday 28 September to Sunday 4 October",
  season_note: "Late season: winter pauses start in November",
  kpis: [
    { label: "Requests", value: "6", sub: "5 more than last week" },
    { label: "Our revenue", value: "£66.45", sub: "15% of job value" },
  ],
  waiting: [waiting],
  districts: [
    { code: "HP15", name: "Hazlemere", jobs: 3, providers: 3 },
    { code: "HP9", name: "Beaconsfield", jobs: 1, providers: 0 },
  ],
  own_customers: { active: 2, providers: 1, job_value_pence: 0, revenue_pence: 0, invites_blocked: 2 },
  attention: [{ provider_id: "p1", short: "Alan P.", issue: "Insurance expires on 12 October", tone: "warn", action: "Send reminder" }],
  payments: [
    {
      visit_id: "v1",
      customer_name: "Dee D.",
      provider_short: "Dave H.",
      category_name: "Lawn mowing",
      local_date: "2026-10-02",
      amount_pence: 3000,
      status: "failed",
      failure_reason: "Your card was declined.",
      since: "2026-10-02T10:00:00Z",
    },
  ],
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("overview and dispatch", () => {
  it("shows the week, the waiting jobs and who needs attention", async () => {
    mockApi({ "GET /api/config": () => config(true), "GET /api/admin/overview": () => overview });
    withToasts(<Overview />);
    expect(await screen.findByText("Monday 28 September to Sunday 4 October")).toBeInTheDocument();
    expect(screen.getByText("£66.45")).toBeInTheDocument();
    expect(screen.getByText("Hedge trimming in Loudwater, HP10")).toBeInTheDocument();
    expect(screen.getByText("Request R-2291, waiting 5 hours")).toBeInTheDocument();
    expect(screen.getByText(/HP9 has demand but no active providers/)).toBeInTheDocument();
    expect(screen.getByText("Insurance expires on 12 October")).toBeInTheDocument();
    expect(screen.getByText(/Card declined: Your card was declined\./)).toBeInTheDocument();
  });

  it("brings the request the map linked to into view (/admin#request-R-2291)", async () => {
    mockApi({ "GET /api/config": () => config(true), "GET /api/admin/overview": () => overview });
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    renderWithProviders(<ToastProvider><Overview /></ToastProvider>, { path: "/admin#request-R-2291" });
    const card = (await screen.findByText("Request R-2291, waiting 5 hours")).closest(".req");
    expect(card).toHaveAttribute("id", "request-R-2291");
    expect(card).toHaveClass("linked");
    await waitFor(() => expect(card).toHaveFocus());
    expect(scroll).toHaveBeenCalledWith({ block: "center" });
    expect(screen.getByRole("link", { name: "See where the work is on the map" })).toHaveAttribute("href", "/admin/map");
  });

  it("copies the WhatsApp text, and shows it when the clipboard isn't available", async () => {
    const text = "Job going: hedge trimming in Loudwater, HP10. Take it here: https://dev.onequickjob.co.uk/p/j/R-2291";
    mockApi({
      "GET /api/config": () => config(true),
      "GET /api/admin/overview": () => overview,
      "GET /api/admin/requests/R-2291/whatsapp": () => ({ text }),
    });
    withToasts(<Overview />);
    await userEvent.click(await screen.findByRole("button", { name: /copy whatsapp message/i }));
    expect(await screen.findByLabelText("WhatsApp message for R-2291")).toHaveTextContent(text);
    expect(screen.getByText("Couldn't copy here. The message is shown below the request.")).toBeInTheDocument();
  });

  it("suggests a higher guide price for the customer to approve (A12)", async () => {
    const api = mockApi({
      "GET /api/config": () => config(true),
      "GET /api/admin/overview": () => overview,
      "POST /api/admin/requests/R-2291/raise-guide": () => ({ ...waiting, awaiting_customer: true, proposed_guide_pence: 7900 }),
    });
    withToasts(<Overview />);
    await userEvent.click(await screen.findByRole("button", { name: "Raise guide 10%" }));
    expect(await screen.findByText("Raise to £79 sent to the customer to approve. Logged for review.")).toBeInTheDocument();
    const call = api.mock.calls.find(([r]) => r instanceof Request && r.url.endsWith("/raise-guide"));
    expect(await (call![0] as Request).json()).toEqual({ percent: 10, note: "" });
  });

  it("retries a failed charge", async () => {
    mockApi({
      "GET /api/config": () => config(true),
      "GET /api/admin/overview": () => overview,
      "POST /api/admin/visits/v1/retry-charge": () => ({ visit_id: "v1", status: "succeeded", failure_reason: null }),
    });
    withToasts(<Overview />);
    await userEvent.click(await screen.findByRole("button", { name: "Retry charge" }));
    expect(await screen.findByText("Paid. The ledger and receipts are updated.")).toBeInTheDocument();
  });
});

const calibration = {
  kpis: [{ label: "Median estimate error", value: "+5%", sub: "actual vs estimated time" }],
  points: [{ visit_id: "v1", segment: "first", est_mins: 60, actual_mins: 90 }],
  segments: [{ id: "first", label: "Mowing, first cut", color_token: "--c2" }],
  table: [
    { segment: "first", label: "Mowing, first cut", jobs: 12, taken_at_guide: 0.5, countered: 0.5, median_counter_uplift_pence: 900, median_overrun: 0.35, over_25: 0.75 },
  ],
  suggestions: [
    {
      id: "first:time:growth.overgrown",
      title: "First cuts take much longer than we estimate",
      body: "Across 12 timed jobs...",
      change_text: "Raise the overgrown multiplier from 1.9 to 2.6",
      change: { category_id: "mowing", path: "growth.overgrown", before: 1.9, after: 2.6 },
    },
  ],
  live_version: 1,
};

function version(v: number, status: string, created_by: string, can_approve: boolean) {
  return {
    id: `v${v}`,
    version: v,
    status,
    notes: "",
    changes: v > 1 ? [{ category_id: "mowing", path: "growth.overgrown", before: 1.9, after: 2.6 }] : [],
    created_by,
    created_by_name: created_by === "jo" ? "Jo Morgan" : "Sam Patel",
    created_at: "2026-10-03T09:00:00Z",
    approved_by: null,
    approved_by_name: null,
    approved_at: null,
    can_approve,
  };
}

describe("pricing", () => {
  it("drafts a suggested change from the live version", async () => {
    const api = mockApi({
      "GET /api/config": () => config(true),
      "GET /api/auth/me": () => jo,
      "GET /api/admin/pricing/calibration": () => calibration,
      "GET /api/admin/pricing/versions": () => [version(1, "live", "seed", false)],
      "POST /api/admin/pricing/versions": () => jsonResponse(201, version(2, "draft", "jo", false)),
    });
    withToasts(<Pricing />);
    expect(await screen.findByRole("heading", { name: "Pricing and calibration" })).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Draft this change" }));
    expect(await screen.findByText("Change drafted. It goes live after sign-off.")).toBeInTheDocument();
    expect(screen.getByText("Drafted as version 2")).toBeInTheDocument();
    const post = api.mock.calls.find(([r]) => r instanceof Request && r.method === "POST");
    expect(await (post![0] as Request).json()).toEqual({
      based_on: "v1",
      changes: [{ category_id: "mowing", path: "growth.overgrown", after: 2.6 }],
      notes: "First cuts take much longer than we estimate",
    });
  });

  it("lets only another admin approve a draft", async () => {
    mockApi({
      "GET /api/config": () => config(true),
      "GET /api/auth/me": () => jo,
      "GET /api/admin/pricing/calibration": () => calibration,
      "GET /api/admin/pricing/versions": () => [version(3, "draft", "sam", true), version(2, "draft", "jo", false), version(1, "live", "seed", false)],
      "POST /api/admin/pricing/versions/v3/approve": () => ({ ...version(3, "live", "sam", false), approved_by_name: "Jo Morgan" }),
    });
    withToasts(<Pricing />);
    const approve = await screen.findAllByRole("button", { name: "Approve and make live" });
    expect(approve).toHaveLength(1); // Jo's own draft waits for someone else
    expect(screen.getByText("Waiting for another admin to approve")).toBeInTheDocument();
    await userEvent.click(approve[0]);
    expect(await screen.findByText("Version 3 is live. Version 1 is retired.")).toBeInTheDocument();
  });
});

const dispute = {
  id: "d1",
  ref: "D-014",
  title: "Clippings left on the patio",
  category_id: "mowing",
  area: "Marlow",
  customer_name: "Helen M.",
  provider_short: "Alan P.",
  opened_at: "2026-10-01T11:15:00Z",
  opened_text: "2 days ago",
  stage: 1,
  stages: ["Reported", "Provider replied", "Fix agreed", "Closed"],
  status_text: "Waiting for Alan's reply",
  amount_pence: 3400,
  proposed: null,
  resolution: null,
  events: [],
  thread_id: "t1",
  visit_id: "v1",
  provider_first: "Alan",
  charge_status: "succeeded",
  charged_pence: 3400,
  refunded_pence: 0,
  refundable_pence: 3400,
};

describe("disputes", () => {
  it("closes a dispute with a partial refund paid by the provider", async () => {
    const api = mockApi({
      "GET /api/config": () => config(true),
      "GET /api/admin/disputes": () => [dispute],
      "POST /api/admin/disputes/D-014/close": () => ({
        ...dispute,
        stage: 3,
        resolution: { kind: "partial_refund", amount_pence: 1000, refund_id: "re_1", funded_by: "provider", note: "" },
      }),
    });
    withToasts(<Disputes />);
    expect(await screen.findByText("1 open, 0 closed this month")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    const dialog = screen.getByRole("dialog", { name: "Close D-014" });
    await userEvent.click(within(dialog).getByRole("radio", { name: /a partial refund, paid by the provider/i }));
    await userEvent.type(within(dialog).getByLabelText("Refund (£)"), "10");
    await userEvent.click(within(dialog).getByRole("button", { name: "Refund and close" }));
    expect(await screen.findByText("Closed. £10 refunded, paid by the provider.")).toBeInTheDocument();
    const post = api.mock.calls.find(([r]) => r instanceof Request && r.method === "POST");
    expect(await (post![0] as Request).json()).toEqual({ outcome: "partial_refund", amount_pence: 1000, note: "" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("messages both parties", async () => {
    const api = mockApi({
      "GET /api/config": () => config(true),
      "GET /api/admin/disputes": () => [dispute],
      "POST /api/admin/disputes/D-014/message": () => dispute,
    });
    withToasts(<Disputes />);
    await userEvent.click(await screen.findByRole("button", { name: /message both/i }));
    await userEvent.type(screen.getByLabelText("Message"), "Alan, can you sweep up on Friday?");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Message sent to both")).toBeInTheDocument();
    const post = api.mock.calls.find(([r]) => r instanceof Request && r.method === "POST");
    expect(await (post![0] as Request).json()).toEqual({ to: "both", body: "Alan, can you sweep up on Friday?" });
  });
});

describe("amounts typed in pounds", () => {
  it("become integer pence, exactly", () => {
    expect(poundsToPence("10")).toBe(1000);
    expect(poundsToPence("£12.5")).toBe(1250);
    expect(poundsToPence("0.07")).toBe(7);
    expect(poundsToPence("12.345")).toBeNull();
    expect(poundsToPence("ten")).toBeNull();
  });
});
