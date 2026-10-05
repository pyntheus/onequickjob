/** One request's admin page (decisions.md A38): the customer's request and lawn size, where it
 * stands, offers, timeline, messages, a raise waiting for the customer, who could take it, and
 * Overview's actions (the WhatsApp text, raising the guide, which waits for the customer: A12). */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../shared/Toast";
import { mockApi } from "../test/utils";
import RequestDetail from "./pages/RequestDetail";

const detail = {
  request_id: "r1",
  ref: "R-2298",
  status: "open",
  created_at: "2026-10-04T17:00:00Z",
  age_text: "7 hours",
  waiting: true,
  category_id: "mowing",
  category_name: "Lawn mowing",
  customer_name: "Paul Ford",
  customer_phone: "+447700900163",
  address: {
    line1: "9 Poppy Road",
    line2: "",
    locality: "Princes Risborough",
    town: "Princes Risborough",
    postcode: "HP27 0DE",
    district: "HP27",
    uprn: "999001000114",
    lat: 51.719,
    lng: -0.83,
    label: "9 Poppy Road, Princes Risborough, HP27 0DE",
  },
  when_text: "Weekday mornings",
  frequency_text: "Every 2 weeks",
  unit: "a visit",
  guide_pence: 3100,
  first_pence: 4300,
  mins: 40,
  first_mins: 60,
  answers: [
    { question: "How long is the grass right now?", answer: "Recently cut" },
    { question: "What should happen to the clippings?", answer: "Take them away" },
  ],
  notes: "Gate code 1234",
  photos: ["/files/requests/a1b2.jpg", "/files/requests/c3d4.jpg"],
  lawn: {
    area_m2: 250,
    summary: "2 lawns paced out, about 250 m² in total",
    method: "paced",
    method_text: "Paced it out (a big stride counts as a metre)",
    estimator: "customer_measured_v0",
    confidence: "medium",
    lawns: [
      { given: "15 × 10 strides", metres: "15 × 10 metres", area_m2: 150 },
      { given: "10 × 10 strides", metres: "10 × 10 metres", area_m2: 100 },
    ],
  },
  cover: false,
  direct_provider_short: null,
  admin_note: null,
  booked: null,
  offers: [
    {
      id: "o1",
      provider_id: "p-gary",
      provider_short: "Gary T.",
      price_pence: 3600,
      first_price_pence: 5000,
      guide_pence: 3100,
      status: "pending",
      reasons: ["Further than usual"],
      message: "It's a drive for me.",
      created_at: "2026-10-04T18:00:00Z",
      decided_at: null,
    },
  ],
  timeline: [
    { at: "2026-10-04T17:00:00Z", kind: "created", text: "Requested" },
    { at: "2026-10-04T17:00:05Z", kind: "broadcast", text: "No provider was alerted" },
    { at: "2026-10-04T18:00:00Z", kind: "countered", text: "Gary T. suggested £36" },
  ],
  messages: [
    {
      id: "m1",
      channel: "sms",
      recipient: { name: "Paul Ford", phone: "+447700900163" },
      template_id: "request_sent",
      subject: null,
      body: "We've got your request for lawn mowing.",
      related: { request_id: "r1" },
      created_at: "2026-10-04T17:00:06Z",
      not_before: null,
    },
  ],
  price_change: {
    id: "pc1",
    status: "pending",
    guide_pence: 3400,
    first_pence: 4700,
    from_guide_pence: 3100,
    from_first_pence: 4300,
    percent: 10,
    proposed_by: "u-jo",
    proposed_at: "2026-10-04T19:00:00Z",
    decided_at: null,
    note: "",
  },
  coverage: {
    in_reach: 1,
    in_reach_doing_it: 0,
    uncovered: true,
    nearby: [
      { provider_id: "p-kasia", short: "Kasia N.", miles: 3.8, jobs: ["Regular cleaning"], does_it: false, payouts_paused: true },
    ],
  },
};

function open(path = "/admin/requests/r1") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter([{ path: "/admin/requests/:requestId", element: <RequestDetail /> }], { initialEntries: [path] });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("a request's admin page", () => {
  it("shows the request, its lawn size and method, where it stands, offers, timeline and messages", async () => {
    mockApi({ "GET /api/admin/requests/r1": () => detail });
    open();
    expect(await screen.findByRole("heading", { level: 1, name: "Lawn mowing in Princes Risborough, HP27" })).toBeInTheDocument();
    expect(screen.getByText("Open")).toHaveClass("badge");

    const asked = screen.getByRole("heading", { name: "What the customer asked for" }).parentElement!;
    for (const text of [
      "Paul Ford, 07700 900163",
      "9 Poppy Road, Princes Risborough, Princes Risborough, HP27 0DE",
      "Weekday mornings",
      "Every 2 weeks",
      "£31 a visit, first visit £43",
      "40 minutes, first visit 60",
      "How long is the grass right now?Recently cut",
      "Gate code 1234",
      "2 photos",
    ]) {
      expect(asked).toHaveTextContent(text);
    }
    // The photos themselves, each opening full size (Codex review).
    const photos = within(asked).getByRole("list", { name: "The customer's photos" });
    const links = within(photos).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["/files/requests/a1b2.jpg", "/files/requests/c3d4.jpg"]);
    expect(within(links[0]).getByRole("img", { name: "The customer's upload 1 of 2, opens full size" })).toHaveAttribute("src", "/files/requests/a1b2.jpg");

    const lawn = screen.getByRole("heading", { name: "Lawn size" }).parentElement!;
    expect(lawn).toHaveTextContent("250 m²: 2 lawns paced out, about 250 m² in total");
    expect(lawn).toHaveTextContent("Paced it out (a big stride counts as a metre)");
    expect(lawn).toHaveTextContent("customer_measured_v0, confidence medium");
    expect(within(lawn).getAllByRole("row")).toHaveLength(3);
    expect(within(lawn).getByRole("row", { name: /15 × 10 strides/ })).toHaveTextContent("15 × 10 metres150 m²");

    const offers = screen.getByRole("heading", { name: "Offers and counters" }).parentElement!;
    expect(offers).toHaveTextContent("Gary T. suggested £36, first visit £50 (guide then £31)");
    expect(within(offers).getByText("Waiting on the customer")).toHaveClass("badge");
    expect(offers).toHaveTextContent("Further than usual. It's a drive for me.");

    const standing = screen.getByRole("heading", { name: "Where it stands" }).parentElement!;
    expect(standing).toHaveTextContent("Open 7 hours, nobody's taken it yet.");
    expect(within(standing).getByRole("note")).toHaveTextContent(
      "Awaiting the customer: they've been asked to approve £34 (first visit £47), up from £31",
    );
    expect(standing).toHaveTextContent("No active provider in reach does lawn mowing. 1 provider in reach does other jobs.");
    expect(within(standing).getByRole("link", { name: "Kasia N." })).toHaveAttribute("href", "/admin/providers/p-kasia");
    expect(within(standing).getByText("Payouts paused")).toHaveClass("badge");

    const timeline = screen.getByRole("heading", { name: "What's happened" }).parentElement!;
    expect(within(timeline).getAllByRole("listitem").map((li) => li.textContent?.replace(/^.*?\d{2}:\d{2} /, ""))).toEqual([
      "Requested",
      "No provider was alerted",
      "Gary T. suggested £36",
    ]);
    const messages = screen.getByRole("heading", { name: "Messages" }).parentElement!;
    expect(messages).toHaveTextContent("Paul Ford");
    expect(messages).toHaveTextContent("We've got your request for lawn mowing.");
  });

  it("has Overview's actions: the WhatsApp text, and a raise that waits for the customer (A12)", async () => {
    const api = mockApi({
      "GET /api/admin/requests/r1": () => detail,
      "GET /api/admin/requests/R-2298/whatsapp": () => ({ text: "Job going: lawn mowing in Princes Risborough, HP27." }),
      "POST /api/admin/requests/R-2298/raise-guide": () => ({ request_ref: "R-2298", guide_pence: 3100, proposed_guide_pence: 3400 }),
    });
    open();
    await userEvent.click(await screen.findByRole("button", { name: /Copy WhatsApp message/ }));
    expect(await screen.findByLabelText("WhatsApp message for R-2298")).toHaveTextContent("Job going: lawn mowing");
    await userEvent.click(screen.getByRole("button", { name: "Raise guide 10%" }));
    expect(await screen.findByText("Raise to £34 sent to the customer to approve. Logged for review.")).toBeInTheDocument();
    const raise = api.mock.calls.find(([r]) => r instanceof Request && r.url.endsWith("/raise-guide"));
    expect(await (raise![0] as Request).json()).toEqual({ percent: 10, note: "" });
  });

  it("has no actions once it's booked, and says who booked it", async () => {
    mockApi({
      "GET /api/admin/requests/r1": () => ({
        ...detail,
        status: "booked",
        waiting: false,
        price_change: null,
        booked: {
          booking_id: "b1",
          booking_ref: "B-1101",
          provider_id: "p-gary",
          provider_short: "Gary T.",
          price_pence: 3600,
          first_price_pence: 5000,
          via: "counter",
          at: "2026-10-04T20:00:00Z",
        },
      }),
    });
    open();
    expect(await screen.findByText("Booked")).toHaveClass("badge");
    expect(screen.queryByRole("button", { name: "Raise guide 10%" })).not.toBeInTheDocument();
    const standing = screen.getByRole("heading", { name: "Where it stands" }).parentElement!;
    expect(standing).toHaveTextContent("Booked by Gary T. at £36 (first visit £50), their suggested price on");
    expect(standing).toHaveTextContent(": booking B-1101.");
  });

  it("says when there's no such request", async () => {
    mockApi({});
    open("/admin/requests/nope");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
