import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { config, jsonResponse, mockApi, renderWithProviders } from "../test/utils";
import { CardCapture } from "./CardCapture";

const card = { brand: "visa", last4: "4242", exp_month: 12, exp_year: 2028 };

afterEach(() => {
  vi.restoreAllMocks();
});

describe("CardCapture", () => {
  it("saves the fake test card straight away", async () => {
    mockApi({
      "GET /api/config": () => config(true),
      "POST /api/c/payment/setup": () => ({ gateway: "fake", gateway_customer_id: "cus_fake_1", setup_id: "seti_fake_1", status: "succeeded" }),
      "POST /api/c/payment/setup/seti_fake_1/confirm": () => ({ card }),
    });
    const onSaved = vi.fn();
    renderWithProviders(<CardCapture onSaved={onSaved} />);
    await userEvent.click(await screen.findByRole("button", { name: "Use test card 4242" }));
    expect(await screen.findByText("•••• •••• •••• 4242")).toBeInTheDocument();
    expect(onSaved).toHaveBeenCalledWith(card);
  });

  it("follows its saved prop when the customer's card loads after it mounts", async () => {
    mockApi({ "GET /api/config": () => config(true) });
    function Harness() {
      const [saved, setSaved] = useState<typeof card | null>(null);
      return (
        <>
          <button type="button" onClick={() => setSaved(card)}>
            Profile loaded
          </button>
          <button type="button" onClick={() => setSaved({ ...card, last4: "1881" })}>
            Card changed
          </button>
          <CardCapture onSaved={() => {}} saved={saved} />
        </>
      );
    }
    renderWithProviders(<Harness />);
    expect(await screen.findByRole("button", { name: "Use test card 4242" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Profile loaded" }));
    expect(await screen.findByText("•••• •••• •••• 4242")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Card changed" }));
    expect(await screen.findByText("•••• •••• •••• 1881")).toBeInTheDocument();
  });

  it("with Stripe, says so when card entry isn't configured rather than failing silently", async () => {
    const stripe = { ...config(true), payments: { gateway: "stripe", publishable_key: null } };
    mockApi({
      "GET /api/config": () => stripe,
      "POST /api/c/payment/setup": () => ({
        gateway: "stripe",
        gateway_customer_id: "cus_1",
        setup_id: "seti_1",
        client_secret: "seti_1_secret_x",
        publishable_key: null,
        status: "requires_confirmation",
      }),
    });
    renderWithProviders(<CardCapture onSaved={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Add card" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("the Stripe publishable key is missing");
  });

  it("explains a missing endpoint while L1 builds it", async () => {
    mockApi({
      "GET /api/config": () => config(true),
      "POST /api/c/payment/setup": () =>
        jsonResponse(501, { detail: { code: "not_implemented", message: "Not built yet.", lane: "L1" } }),
    });
    renderWithProviders(<CardCapture onSaved={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Use test card 4242" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Card saving isn't built yet (lane L1 adds the endpoint).");
  });
});
