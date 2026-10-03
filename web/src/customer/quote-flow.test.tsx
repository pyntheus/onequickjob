import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { config, mockApi, unauthorised } from "../test/utils";
import { FLOW_KEY, INITIAL_FLOW, type FlowState } from "./flow";
import { address, areaOptions, catalogue, cleaningQuote, me, mowingQuote } from "./test-fixtures";
import { json, renderAt } from "./test-render";

const fees = { split: { mode: "standard", rate_percent: 15, price_pence: 3000, fee_pence: 450, provider_pence: 2550 } };

function withFlow(patch: Partial<FlowState>) {
  sessionStorage.setItem(FLOW_KEY, JSON.stringify({ ...INITIAL_FLOW, ...patch }));
}

beforeEach(() => sessionStorage.clear());

describe("landing", () => {
  it("builds the quote starter from the catalogue and needs a chosen address", async () => {
    const calls: string[] = [];
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": unauthorised,
      "GET /api/categories": () => catalogue,
      "GET /api/c/fees/example": () => fees,
      "GET /api/address/search": (url) => {
        calls.push(url.searchParams.get("q") ?? "");
        return [{ id: "fake_01", label: address.label }];
      },
      "GET /api/address/fake_01": () => address,
    });
    const { router } = renderAt("/");
    expect(await screen.findByRole("heading", { name: /Home and garden jobs/ })).toBeInTheDocument();
    // Tiles come from the categories API, grouped by tab.
    expect(await screen.findByRole("button", { name: /Lawn mowing/ })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("tab", { name: "Indoors" }));
    expect(screen.getByRole("button", { name: /Regular cleaning/ })).toHaveTextContent("from £66");
    expect(screen.queryByRole("button", { name: /Lawn mowing/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Outside" }));

    const see = screen.getByRole("button", { name: "See my price" });
    expect(see).toBeDisabled();
    await userEvent.type(screen.getByRole("combobox", { name: "Your address" }), "orch");
    await userEvent.click(await screen.findByRole("option", { name: address.label }));
    await waitFor(() => expect(see).toBeEnabled());
    expect(calls.at(-1)).toBe("orch");
    await userEvent.click(see);
    await waitFor(() => expect(router.state.location.pathname).toBe("/quote/mowing/size"));
  });

  it("shows the reworded how it works, the fee split from the API and what we don't do; no licence footer", async () => {
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": unauthorised,
      "GET /api/categories": () => catalogue,
      "GET /api/c/fees/example": () => fees,
    });
    renderAt("/");
    expect(await screen.findByText(/For lawns, you pick roughly how big yours is/)).toBeInTheDocument();
    expect(await screen.findByText("£25.50")).toBeInTheDocument();
    expect(screen.getByText("OneQuickJob fee (15%)")).toBeInTheDocument();
    expect(screen.getByText("£4.50")).toBeInTheDocument();
    expect(screen.getByText("Gas boiler work")).toBeInTheDocument();
    expect(screen.getByText("Use a Gas Safe registered engineer.")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/Open Government Licence|survey data|measure your garden|LIDAR/i);
  });
});

describe("lawn size", () => {
  it("offers the four bands with comparisons and the three nudges, and never claims a measurement", async () => {
    withFlow({ address, addressText: address.label });
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": unauthorised,
      "GET /api/categories": () => catalogue,
      "GET /api/area/options": () => areaOptions,
    });
    const { router } = renderAt("/quote/mowing/size");
    expect(await screen.findByRole("heading", { name: "How big is your lawn?" })).toBeInTheDocument();
    for (const t of ["About a double garage", "About a badminton court", "About a singles tennis court", "Bigger than a doubles tennis court"]) {
      expect(await screen.findByText(t)).toBeInTheDocument();
    }
    const go = screen.getByRole("button", { name: "Continue" });
    expect(go).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /Large, about 190 m²/ }));
    for (const l of ["Looks smaller", "About right", "Looks bigger"]) expect(screen.getByRole("button", { name: l })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Looks bigger" }));
    expect(screen.getByRole("button", { name: "Looks bigger" })).toHaveAttribute("aria-pressed", "true");
    expect(document.body).not.toHaveTextContent(/measured|survey data|LIDAR|Environment Agency|Open Government/i);
    await userEvent.click(go);
    await waitFor(() => expect(router.state.location.pathname).toBe("/quote/mowing/details"));
    expect(JSON.parse(sessionStorage.getItem(FLOW_KEY) ?? "{}").lawn).toEqual({ band: "large", adjust: "bigger" });
  });

  it("asks for the address first when there isn't one", async () => {
    mockApi({ "GET /api/config": () => config(false), "GET /api/auth/me": unauthorised, "GET /api/categories": () => catalogue });
    renderAt("/quote/mowing/size");
    expect(await screen.findByRole("heading", { name: "Start with your address" })).toBeInTheDocument();
  });
});

describe("questions", () => {
  it("renders every intake type from the schema (number, multi)", async () => {
    withFlow({ address, categoryId: "cleaning" });
    mockApi({ "GET /api/config": () => config(false), "GET /api/auth/me": unauthorised, "GET /api/categories": () => catalogue });
    renderAt("/quote/cleaning/details");
    expect(await screen.findByRole("heading", { name: "A few quick questions" })).toBeInTheDocument();
    const bedrooms = screen.getAllByRole("group", { name: "Bedrooms" })[0];
    expect(within(bedrooms).getAllByText("3 bedrooms").length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: "Less: Bedrooms" }));
    await userEvent.click(screen.getByRole("button", { name: "Less: Bedrooms" }));
    expect(within(bedrooms).getAllByText("1 bedroom").length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: "Inside the oven" }));
    expect(screen.getByRole("button", { name: "Inside the oven" })).toHaveAttribute("aria-pressed", "true");
    const saved = JSON.parse(sessionStorage.getItem(FLOW_KEY) ?? "{}");
    expect(saved.answers.cleaning).toEqual({ bedrooms: 1, extras: ["oven"] });
  });

  it("renders counts, text and photos, and needs at least one item", async () => {
    withFlow({ address, categoryId: "flatpack" });
    mockApi({ "GET /api/config": () => config(false), "GET /api/auth/me": unauthorised, "GET /api/categories": () => catalogue });
    renderAt("/quote/flatpack/details");
    expect(await screen.findByText("What needs building?")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("For example: IKEA PAX")).toBeInTheDocument();
    expect(screen.getByText("Add photo")).toBeInTheDocument();
    const see = screen.getByRole("button", { name: "See my price" });
    expect(see).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Less: Large items" }));
    expect(see).toBeDisabled();
    expect(screen.getByText("Add at least one item to see a price.")).toBeInTheDocument();
  });
});

describe("guide price", () => {
  it("shows £31 a visit for the Large band, the size chosen, confidence and the fee split", async () => {
    withFlow({ address, lawn: { band: "large", adjust: "right" } });
    let body: Record<string, unknown> = {};
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": unauthorised,
      "GET /api/categories": () => catalogue,
      "GET /api/area/options": () => areaOptions,
      "POST /api/quotes": async (_u, req) => {
        body = await req.json();
        return json(201, mowingQuote);
      },
    });
    renderAt("/quote/mowing/price");
    expect(await screen.findByText("£31")).toBeInTheDocument();
    expect(screen.getByText("a visit")).toBeInTheDocument();
    expect(body).toMatchObject({ category_id: "mowing", lawn: { band: "large", adjust: "right" } });
    expect(await screen.findByText(/For the lawn size you chose/)).toHaveTextContent("large, about 190 m² (about a singles tennis court)");
    expect(screen.getByText(/usually go for £28 to £36, and take about 39 minutes/)).toBeInTheDocument();
    expect(screen.getByText("Fairly close.")).toBeInTheDocument();
    expect(screen.getByText("£26.35")).toBeInTheDocument();
    expect(screen.getByText("£4.65")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/measured|survey/i);
  });

  it("shows the first-visit price, its reason and both splits", async () => {
    withFlow({ address, categoryId: "cleaning" });
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": unauthorised,
      "GET /api/categories": () => catalogue,
      "POST /api/quotes": () => json(201, cleaningQuote),
    });
    renderAt("/quote/cleaning/price");
    expect(await screen.findByText("First visit £88.")).toBeInTheDocument();
    expect(screen.getByText(/The first clean takes longer/)).toBeInTheDocument();
    expect(screen.getByText("Each clean after the first")).toBeInTheDocument();
    expect(screen.getByText("The first visit")).toBeInTheDocument();
    expect(screen.getByText("£56.10")).toBeInTheDocument();
    expect(screen.getByText("£74.80")).toBeInTheDocument();
  });
});

describe("contact", () => {
  it("signs in with the code, saves the card through the gateway, needs the agency box, then sends", async () => {
    withFlow({ address, lawn: { band: "large", adjust: "right" }, quoteId: "q1", notes: "Gate sticks" });
    let signedIn = false;
    let sent: Record<string, unknown> | null = null;
    mockApi({
      "GET /api/config": () => config(true),
      "GET /api/auth/me": () => (signedIn ? me : unauthorised()),
      "GET /api/categories": () => catalogue,
      "GET /api/quotes/q1": () => mowingQuote,
      "GET /api/demo/outbox": () => [],
      "GET /api/c/profile": () => json(404, { detail: { code: "no_customer_profile", message: "You haven't booked anything yet." } }),
      "POST /api/auth/code": () => json(202, { channel: "sms", sent_to: "07700 9•••23", expires_in_seconds: 600 }),
      "POST /api/auth/verify": () => {
        signedIn = true;
        return me;
      },
      "POST /api/c/payment/setup": () => ({ gateway: "fake", gateway_customer_id: "cus", setup_id: "seti_1", status: "succeeded" }),
      "POST /api/c/payment/setup/seti_1/confirm": () => ({ card: { brand: "visa", last4: "4242", exp_month: 12, exp_year: 2028 } }),
      "POST /api/c/requests": async (_u, req) => {
        sent = await req.json();
        return json(201, { ref: "R-2301" });
      },
      "GET /api/c/requests/R-2301": () => json(404, { detail: { code: "not_found", message: "x" } }),
    });
    const { router } = renderAt("/quote/mowing/contact");
    expect(await screen.findByRole("heading", { name: "Where should we send updates?" })).toBeInTheDocument();
    expect(await screen.findByText("£31 a visit")).toBeInTheDocument();
    const send = screen.getByRole("button", { name: "Send my request" });
    expect(send).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Your name"), "Sarah Whitfield");
    await userEvent.type(screen.getByLabelText("Mobile number"), "07700 900123");
    await userEvent.click(screen.getByRole("button", { name: "Text me a code" }));
    expect(await screen.findByText(/your code is in the Outbox/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Your code"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Confirm my number" }));
    expect(await screen.findByText("(confirmed)")).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Use test card 4242" }));
    expect(await screen.findByText("•••• •••• •••• 4242")).toBeInTheDocument();
    expect(send).toBeDisabled();
    const terms = screen.getByRole("checkbox", { name: /My agreement for the work is with the provider who takes the job, and OneQuickJob acts as their booking and payment agent/ });
    await userEvent.click(terms);
    await waitFor(() => expect(send).toBeEnabled());
    await userEvent.click(send);
    await waitFor(() => expect(router.state.location.pathname).toBe("/requests/R-2301"));
    expect(sent).toMatchObject({ quote_id: "q1", notes: "Gate sticks", agree_terms: true, photos: [], when: { days: "weekdays", time: "morning" } });
    expect((sent as unknown as { address: { uprn: string } }).address.uprn).toBe("999000000001");
  });
});
