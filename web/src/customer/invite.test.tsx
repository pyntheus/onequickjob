import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { config, mockApi, unauthorised } from "../test/utils";
import { address, me } from "./test-fixtures";
import { json, renderAt } from "./test-render";

beforeEach(() => sessionStorage.clear());

const dave = {
  provider_id: "p1",
  short: "Dave H.",
  first_name: "Dave",
  initials: "DH",
  rating_avg: 4.9,
  rating_count: 112,
  miles: null,
  badges: [{ kind: "identity", label: "ID checked", tone: "ok" }],
};
const preview = {
  invite_id: "i1",
  status: "invited",
  customer_first_name: "Mary",
  provider: dave,
  category_id: "mowing",
  category_name: "Lawn mowing",
  frequency_label: "every 2 weeks",
  price_pence: 2500,
  provider_fee_pence: 125,
  next_visit_text: "Tuesday 6 October",
  phone_hint: "07700 9•••40",
};
const mary = { ...me, name: "Mary Bishop", phone: "07700 900140" };

describe("own-customer invite", () => {
  it("shows the provider's price, says the fee isn't added, and needs sign-in with the invited number", async () => {
    mockApi({ "GET /api/config": () => config(false), "GET /api/auth/me": unauthorised, "GET /api/c/invites/tok123": () => preview });
    renderAt("/invite/tok123");
    expect(await screen.findByRole("heading", { name: "Dave has invited you to OneQuickJob" })).toBeInTheDocument();
    expect(screen.getByText("Hi Mary. Dave would like to arrange your visits through OneQuickJob from now on.")).toBeInTheDocument();
    expect(screen.getByText("£25 a visit, set by Dave")).toBeInTheDocument();
    expect(screen.getByText(/Dave pays us a small fee of £1.25 a visit. It isn't added to your price./)).toBeInTheDocument();
    expect(screen.getByText("The number Dave texted: 07700 9•••40")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept Dave's invite" })).toBeDisabled();
  });

  it("accepts once signed in with an address, a card and the agency box", async () => {
    let body: Record<string, unknown> | null = null;
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": () => mary,
      "GET /api/c/invites/tok123": () => preview,
      "GET /api/c/profile": () => ({ customer_id: "c9", name: "Mary Bishop", phone: "+447700900140", email: null, addresses: [], card: { brand: "visa", last4: "4242", exp_month: 12, exp_year: 2028 } }),
      "GET /api/address/search": () => [{ id: "fake_05", label: address.label }],
      "GET /api/address/fake_05": () => address,
      "POST /api/c/invites/tok123/accept": async (_u, req) => {
        body = await req.json();
        return json(201, { first_visit_text: "Tuesday 6 October, time confirmed the day before" });
      },
    });
    renderAt("/invite/tok123");
    expect(await screen.findByText("•••• •••• •••• 4242")).toBeInTheDocument();
    const accept = screen.getByRole("button", { name: "Accept Dave's invite" });
    await userEvent.click(screen.getByRole("checkbox", { name: /My agreement for the work is with Dave, and OneQuickJob acts as Dave's booking and payment agent/ }));
    expect(accept).toBeDisabled();
    await userEvent.type(screen.getByRole("combobox", { name: "Your address" }), "orch");
    await userEvent.click(await screen.findByRole("option", { name: address.label }));
    await waitFor(() => expect(accept).toBeEnabled());
    await userEvent.click(accept);
    expect(await screen.findByRole("heading", { name: "You're all set, Mary" })).toBeInTheDocument();
    expect(screen.getByText("Dave's next visit is Tuesday 6 October. You'll pay by card after each visit.")).toBeInTheDocument();
    expect(body).toMatchObject({ agree_terms: true, address: { uprn: "999000000001" } });
  });

  it("explains a closed invite", async () => {
    mockApi({ "GET /api/config": () => config(false), "GET /api/auth/me": unauthorised, "GET /api/c/invites/tok123": () => ({ ...preview, status: "expired" }) });
    renderAt("/invite/tok123");
    expect(await screen.findByRole("heading", { name: "This invite has closed" })).toBeInTheDocument();
  });
});
