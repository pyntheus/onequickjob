import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { config, mockApi, unauthorised } from "../test/utils";
import { FLOW_KEY, INITIAL_FLOW, INITIAL_LAWN, type FlowState } from "./flow";
import { address, areaEstimate, areaOptions, catalogue, cleaningQuote, me, mowingQuote } from "./test-fixtures";
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
  const sizeApi = (extra: Record<string, Parameters<typeof mockApi>[0][string]> = {}) =>
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": unauthorised,
      "GET /api/categories": () => catalogue,
      "GET /api/area/options": () => areaOptions,
      ...extra,
    });
  const box = (name: string | RegExp, within_: HTMLElement = document.body) => within(within_).getByRole("textbox", { name });

  it("offers three ways; the bands compare with cars, drawn to one scale, with the nudges", async () => {
    withFlow({ address, addressText: address.label });
    sizeApi();
    const { router } = renderAt("/quote/mowing/size");
    expect(await screen.findByRole("heading", { name: "How big is your lawn?" })).toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Pick a size", "Pace it out", "I know the size"]);
    expect(screen.getByRole("tab", { name: "Pick a size" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveAccessibleName("Pick a size");
    for (const b of areaOptions.bands) expect(await screen.findByText(b.comparison)).toBeInTheDocument();
    // Four drawings, every one the same number of metres across, so their sizes compare truly;
    // the two biggest have a house beside the lawn.
    const figs = [...document.querySelectorAll("svg.lawn-fig")];
    expect(figs).toHaveLength(4);
    expect(new Set(figs.map((f) => f.getAttribute("viewBox")?.split(" ")[2]))).toEqual(new Set(["33"]));
    expect(figs.map((f) => f.textContent?.includes("for scale"))).toEqual([false, false, true, true]);
    expect(document.body).not.toHaveTextContent(/tennis|badminton|garage/i);

    const go = screen.getByRole("button", { name: "Continue" });
    expect(go).toBeDisabled();
    const large = screen.getByRole("button", { name: "Large" });
    expect(large).toHaveAccessibleDescription("About 10 × 19 metres (190 m²). 4 car lengths long and 2 wide.");
    await userEvent.click(large);
    expect(large).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Large, about 190 m²")).toBeInTheDocument();
    for (const l of ["Looks smaller", "About right", "Looks bigger"]) expect(screen.getByRole("button", { name: l })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Looks bigger" }));
    expect(screen.getByRole("button", { name: "Looks bigger" })).toHaveAttribute("aria-pressed", "true");
    expect(document.body).not.toHaveTextContent(/measured|survey data|LIDAR|Environment Agency|Open Government/i);
    await userEvent.click(go);
    await waitFor(() => expect(router.state.location.pathname).toBe("/quote/mowing/details"));
    expect(JSON.parse(sessionStorage.getItem(FLOW_KEY) ?? "{}").lawn).toMatchObject({ method: "band", band: "large", adjust: "bigger" });
  });

  it("paces out a lawn in strides, typed or with −1 and +1; the API works out the area", async () => {
    withFlow({ address, addressText: address.label });
    const asked: unknown[] = [];
    sizeApi({
      "POST /api/area/estimate": async (_u, req) => {
        const body = (await req.json()) as { lawns: { length: string; width: string }[] };
        asked.push(body);
        return areaEstimate("paced", body.lawns.map((l) => [Number(l.length), Number(l.width)]));
      },
    });
    const { router } = renderAt("/quote/mowing/size");
    await userEvent.click(await screen.findByRole("tab", { name: "Pace it out" }));
    expect(screen.getByText("Walk the length of your lawn in big strides, about a metre each, then the width.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Looks bigger" })).not.toBeInTheDocument();
    const go = screen.getByRole("button", { name: "Continue" });
    await userEvent.type(box("Strides long"), "12");
    expect(go).toBeDisabled();
    expect(screen.getByText("Fill in the length and width to continue.")).toBeInTheDocument();
    await userEvent.type(box("Strides wide"), "7");
    await userEvent.click(screen.getByRole("button", { name: "Strides wide: +1" }));
    expect(box("Strides wide")).toHaveValue("8");
    expect(await screen.findByText("That's about 12 × 8 metres (96 m²)")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Your lawn drawn to scale, with a car and a person" })).toBeInTheDocument();
    await waitFor(() => expect(go).toBeEnabled());
    expect(asked.at(-1)).toEqual({ method: "paced", adjust: "right", unit: "m", lawns: [{ length: "12", width: "8" }] });
    // Nothing was asked until both sides were filled, and what's typed is never turned into
    // another number: "12.5" strides is pointed out here, not sent as 125 or 12.
    expect(asked.every((b) => (b as { lawns: { width: string }[] }).lawns[0].width !== "")).toBe(true);
    const before = asked.length;
    await userEvent.type(box("Strides long"), ".5");
    expect(box("Strides long")).toHaveValue("12.5");
    expect(await screen.findByText("The length is a whole number of strides, like 12.")).toBeInTheDocument();
    expect(box("Strides long")).toHaveAttribute("aria-invalid", "true");
    expect(go).toBeDisabled();
    expect(screen.queryByText(/That's about/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Strides long: +1" }));
    expect(box("Strides long")).toHaveValue("14"); // from 12.5, the nearest whole number, 13, plus 1
    await userEvent.clear(box("Strides long"));
    await userEvent.type(box("Strides long"), "12");
    expect(await screen.findByText("That's about 12 × 8 metres (96 m²)")).toBeInTheDocument();
    expect(asked.slice(before).every((b) => (b as { lawns: { length: string }[] }).lawns[0].length !== "12.5")).toBe(true);
    await waitFor(() => expect(go).toBeEnabled());
    await userEvent.click(go);
    await waitFor(() => expect(router.state.location.pathname).toBe("/quote/mowing/details"));
    expect(JSON.parse(sessionStorage.getItem(FLOW_KEY) ?? "{}").lawn).toMatchObject({ method: "paced", paced: [{ length: "12", width: "8" }] });
  });

  it("adds up to four lawns, each named, and can remove one", async () => {
    withFlow({ address, addressText: address.label });
    sizeApi({
      "POST /api/area/estimate": async (_u, req) => {
        const body = (await req.json()) as { lawns: { length: string; width: string }[] };
        return areaEstimate("paced", body.lawns.map((l) => [Number(l.length), Number(l.width)]));
      },
    });
    renderAt("/quote/mowing/size");
    await userEvent.click(await screen.findByRole("tab", { name: "Pace it out" }));
    await userEvent.type(box("Strides long"), "12");
    await userEvent.type(box("Strides wide"), "8");
    await userEvent.click(screen.getByRole("button", { name: "Add another lawn" }));
    const two = screen.getByRole("group", { name: "Lawn 2" });
    await waitFor(() => expect(box("Strides long", two)).toHaveFocus());
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    await userEvent.type(box("Strides long", two), "7");
    await userEvent.type(box("Strides wide", two), "6");
    expect(await screen.findByText("That's about 138 m² in total across 2 lawns")).toBeInTheDocument();
    expect(screen.getByText("Lawn 1: about 12 × 8 metres (96 m²)")).toBeInTheDocument();
    expect(screen.getByText("Lawn 2: about 7 × 6 metres (42 m²)")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Your lawns drawn to scale, with a car and a person" })).toHaveTextContent("Lawn 2");
    await userEvent.click(screen.getByRole("button", { name: "Add another lawn" }));
    await userEvent.click(screen.getByRole("button", { name: "Add another lawn" }));
    expect(screen.getAllByRole("group", { name: /^Lawn \d$/ })).toHaveLength(4);
    expect(screen.queryByRole("button", { name: "Add another lawn" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remove lawn 4" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove lawn 3" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove lawn 1" }));
    expect(screen.queryByRole("group", { name: "Lawn 1" })).not.toBeInTheDocument();
    expect(box("Strides long")).toHaveValue("7");
    expect(await screen.findByText("That's about 7 × 6 metres (42 m²)")).toBeInTheDocument();
  });

  it("takes metres or feet with decimals and shows the API's reason when a size won't do", async () => {
    withFlow({ address, addressText: address.label });
    const asked: { unit: string; lawns: { length: string; width: string }[] }[] = [];
    sizeApi({
      "POST /api/area/estimate": async (_u, req) => {
        const body = (await req.json()) as (typeof asked)[number];
        asked.push(body);
        if (body.lawns[0].length === "400") {
          return json(422, {
            detail: { code: "lawn_size_invalid", message: "The length must be between 3.3 and 328 feet (1 to 100 metres).", extra: { lawn: 0, side: "length" } },
          });
        }
        return { ...areaEstimate("measured", [[9, 6]], "ft"), text: "That's about 9.1 × 6.1 metres (56 m²)" };
      },
    });
    renderAt("/quote/mowing/size");
    await userEvent.click(await screen.findByRole("tab", { name: "I know the size" }));
    expect(screen.getByRole("button", { name: "Metres" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Feet" }));
    await userEvent.type(box("Length"), "30,555");
    expect(box("Length")).toHaveValue("30.555");
    expect(await screen.findByText("The length needs to be a number like 7.5, with up to two decimal places.")).toBeInTheDocument();
    await userEvent.type(box("Length"), "{Backspace}");
    expect(box("Length")).toHaveValue("30.55");
    await userEvent.type(box("Width"), "20");
    expect(await screen.findByText("That's about 9.1 × 6.1 metres (56 m²)")).toBeInTheDocument();
    expect(asked.at(-1)).toEqual({ method: "measured", adjust: "right", unit: "ft", lawns: [{ length: "30.55", width: "20" }] });
    await userEvent.clear(box("Length"));
    await userEvent.type(box("Length"), "400");
    expect(await screen.findByText("The length must be between 3.3 and 328 feet (1 to 100 metres).")).toBeInTheDocument();
    expect(box("Length")).toHaveAttribute("aria-invalid", "true");
    expect(box("Length")).toHaveAccessibleDescription("The length must be between 3.3 and 328 feet (1 to 100 metres).");
    expect(box("Width")).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByText(/That's about/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  });

  it("says so when the size can't be worked out just now, and tries again", async () => {
    withFlow({ address, addressText: address.label });
    let down = true;
    sizeApi({
      "POST /api/area/estimate": () => {
        if (down) throw new TypeError("Failed to fetch");
        return areaEstimate("paced", [[12, 8]]);
      },
    });
    renderAt("/quote/mowing/size");
    await userEvent.click(await screen.findByRole("tab", { name: "Pace it out" }));
    await userEvent.type(box("Strides long"), "12");
    await userEvent.type(box("Strides wide"), "8");
    expect(await screen.findByText("We couldn't work out the size just now. Check your connection and try again.")).toBeInTheDocument();
    expect(screen.queryByText("Working out the size…")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    down = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("That's about 12 × 8 metres (96 m²)")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled());
  });

  it("keeps a flow saved before the three ways", async () => {
    sessionStorage.setItem(FLOW_KEY, JSON.stringify({ ...INITIAL_FLOW, address, lawn: { band: "large", adjust: "right" } }));
    sizeApi();
    renderAt("/quote/mowing/size");
    expect(await screen.findByRole("button", { name: /^Large/ })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("tab", { name: "Pace it out" }));
    expect(box("Strides long")).toHaveValue("");
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
    withFlow({ address, lawn: { ...INITIAL_LAWN, band: "large" } });
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
    expect(body).toMatchObject({ category_id: "mowing", lawn: { method: "band", band: "large", adjust: "right" } });
    expect(screen.getByText(/Priced for/)).toHaveTextContent("Priced for a large lawn (about 190 m²).");
    expect(screen.getByText(/usually go for £28 to £36, and take about 39 minutes/)).toBeInTheDocument();
    expect(screen.getByText("Fairly close.")).toBeInTheDocument();
    expect(screen.getByText("£26.35")).toBeInTheDocument();
    expect(screen.getByText("£4.65")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/measured|survey/i);
  });

  it("prices the lawns the customer paced out, and sends them back to the size step if the API won't", async () => {
    withFlow({ address, lawn: { ...INITIAL_LAWN, method: "paced", paced: [{ length: "12", width: "8" }, { length: "7", width: "6" }] } });
    const bodies: Record<string, unknown>[] = [];
    let refuse = false;
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": unauthorised,
      "GET /api/categories": () => catalogue,
      "POST /api/quotes": async (_u, req) => {
        bodies.push(await req.json());
        if (refuse) return json(422, { detail: { code: "lawn_size_invalid", message: "That's only 4 m². Check the sizes: we can price lawns from 5 m²." } });
        const m = areaEstimate("paced", [[12, 8], [7, 6]]).measure;
        return json(201, { ...mowingQuote, measure: m, size_text: "2 lawns paced out, about 138 m² in total" });
      },
    });
    const first = renderAt("/quote/mowing/price");
    expect(await first.findByText(/Priced for/)).toHaveTextContent("Priced for 2 lawns paced out, about 138 m² in total.");
    expect(bodies[0].lawn).toEqual({ method: "paced", adjust: "right", unit: "m", lawns: [{ length: "12", width: "8" }, { length: "7", width: "6" }] });
    first.unmount();

    refuse = true;
    withFlow({ address, lawn: { ...INITIAL_LAWN, method: "paced", paced: [{ length: "2", width: "2" }] } });
    const { router } = renderAt("/quote/mowing/price");
    expect(await screen.findByText("That's only 4 m². Check the sizes: we can price lawns from 5 m².")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Check the lawn size" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/quote/mowing/size"));
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
    withFlow({ address, lawn: { ...INITIAL_LAWN, band: "large" }, quoteId: "q1", notes: "Gate sticks" });
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
