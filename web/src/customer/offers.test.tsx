import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { config, mockApi } from "../test/utils";
import { catalogue, counter, me, mike, request } from "./test-fixtures";
import { json, renderAt } from "./test-render";

beforeEach(() => sessionStorage.clear());

const base = (demo: boolean) => ({
  "GET /api/config": () => config(demo),
  "GET /api/auth/me": () => me,
  "GET /api/categories": () => catalogue,
  "GET /api/demo/outbox": () => [],
  "GET /api/demo/users": () => [],
});

function withCounter() {
  const offer = counter();
  return request({
    pending_offers: [offer],
    timeline: [
      ...request().timeline,
      { at: offer.created_at, kind: "counter", text: "Mike R. suggested £72 a clean (first visit £96)", provider: mike, offer },
    ],
  });
}

describe("Finding someone local", () => {
  it("shows a counter with both stored prices and accepts exactly those terms (A1)", async () => {
    let current = withCounter();
    let accepted = "";
    mockApi({
      ...base(false),
      "GET /api/c/requests/R-2301": () => current,
      "POST /api/c/offers/o1/accept": (url) => {
        accepted = url.pathname;
        current = request({
          status: "booked",
          booking_id: "b1",
          booked_with: mike,
          booked_via: "counter",
          booked_price_pence: 7200,
          booked_first_price_pence: 9600,
          pending_offers: [],
        });
        return { booking_id: "b1" };
      },
    });
    renderAt("/requests/R-2301");
    expect(await screen.findByRole("heading", { name: "Finding someone local" })).toBeInTheDocument();
    expect(screen.getByText("Mike R. suggested £72 a clean (first visit £96)")).toBeInTheDocument();
    expect(screen.getByText("instead of £66")).toBeInTheDocument();
    expect(screen.getByText('"It\'s a big kitchen."')).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Accept £72 a clean (first visit £96)" }));
    expect(await screen.findByRole("heading", { name: "You're booked with Mike R." })).toBeInTheDocument();
    expect(screen.getByText("You accepted £72 a clean (first visit £96).")).toBeInTheDocument();
    expect(accepted).toBe("/api/c/offers/o1/accept");
    expect(screen.getByRole("link", { name: "See your booking" })).toHaveAttribute("href", "/bookings/b1");
  });

  it("explains when the provider can no longer take the job, and keeps waiting (ruling A9)", async () => {
    let current = withCounter();
    const message = "Mike can no longer take this job. We're still finding someone local.";
    mockApi({
      ...base(false),
      "GET /api/c/requests/R-2301": () => current,
      "POST /api/c/offers/o1/accept": () => {
        const [sent, countered] = withCounter().timeline;
        current = request({
          timeline: [
            sent,
            { ...countered, offer: counter({ status: "lapsed" }) },
            { at: "2026-10-03T09:09:00Z", kind: "note", text: message, provider: null, offer: null },
          ],
        });
        return json(409, { detail: { code: "provider_unavailable", message } });
      },
    });
    renderAt("/requests/R-2301");
    await userEvent.click(await screen.findByRole("button", { name: /^Accept £72/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("heading", { name: "Finding someone local" })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: /^Accept £72/ })).not.toBeInTheDocument());
    expect(screen.getByText("This price is no longer on offer.")).toBeInTheDocument();
    expect(screen.getAllByText(message).length).toBeGreaterThan(0);
  });

  it("keep waiting declines the counter", async () => {
    let current = withCounter();
    let declined = false;
    mockApi({
      ...base(false),
      "GET /api/c/requests/R-2301": () => current,
      "POST /api/c/offers/o1/decline": () => {
        declined = true;
        const offer = counter({ status: "declined" });
        current = request({ timeline: [...request().timeline, { ...withCounter().timeline[1], offer }] });
        return offer;
      },
    });
    renderAt("/requests/R-2301");
    await userEvent.click(await screen.findByRole("button", { name: "Keep waiting" }));
    expect(await screen.findByText("You're waiting for someone at the guide price.")).toBeInTheDocument();
    expect(declined).toBe(true);
  });

  it("offers Simulate local responses in DEMO_MODE, through the simulate endpoint", async () => {
    let simulated = false;
    mockApi({
      ...base(true),
      "GET /api/c/requests/R-2301": () => request({ simulating: simulated }),
      "POST /api/c/requests/R-2301/demo/simulate": () => {
        simulated = true;
        return json(202, { provider_short: "Mike R.", counter_in_seconds: 4, accept_in_seconds: 15 });
      },
    });
    renderAt("/requests/R-2301");
    await userEvent.click(await screen.findByRole("button", { name: "Simulate local responses" }));
    expect(await screen.findByRole("button", { name: "Local responses on their way…" })).toBeDisabled();
    expect(simulated).toBe(true);
  });

  it("has no simulator when DEMO_MODE is off", async () => {
    const fetchMock = mockApi({ ...base(false), "GET /api/c/requests/R-2301": () => request({ demo_simulator: false }) });
    renderAt("/requests/R-2301");
    expect(await screen.findByRole("heading", { name: "Finding someone local" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Simulate/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/no real providers/)).not.toBeInTheDocument();
    const demo = fetchMock.mock.calls.filter(([r]) => String(r instanceof Request ? r.url : r).includes("/demo/"));
    expect(demo).toHaveLength(0);
  });

  it("asks a signed-out visitor to sign in", async () => {
    mockApi({ ...base(false), "GET /api/auth/me": () => json(401, { detail: { code: "not_signed_in", message: "Please sign in." } }) });
    renderAt("/requests/R-2301");
    expect(await screen.findByRole("heading", { name: "Sign in to see your request" })).toBeInTheDocument();
  });
});
