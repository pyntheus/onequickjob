import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vitest";
import { routes } from "../App";
import { config, mockApi, unauthorised } from "../test/utils";

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

const me = (roles: string[]) => ({
  user_id: "u1", name: "Sarah Whitfield", phone: "07700 900123", email: null, roles,
  customer_id: "c1", provider_id: null, helper_of: null, home_path: "/account",
});

describe("the shell", () => {
  it("renders the customer layout and the landing page", async () => {
    mockApi({ "GET /api/config": () => config(false), "GET /api/auth/me": unauthorised });
    renderAt("/");
    // L1 built the landing page (contract change L1: this asserted the placeholder).
    expect(
      await screen.findByRole("heading", { name: "Home and garden jobs, done by people who live nearby." }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /my account/i })).toHaveAttribute("href", "/account");
  });

  it("asks a signed-out provider to sign in, and shows the bottom nav once signed in", async () => {
    mockApi({ "GET /api/config": () => config(false), "GET /api/auth/me": unauthorised });
    renderAt("/p/today");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Provider" })).not.toBeInTheDocument();
  });

  it("shows a provider their round with the bottom nav", async () => {
    mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": () => ({ ...me(["provider"]), name: "Dave Hughes", provider_id: "p1", home_path: "/p" }),
    });
    renderAt("/p/today");
    expect(await screen.findByRole("heading", { name: "Today's round" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Provider" });
    expect(nav).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Today" })).toHaveAttribute("aria-current", "page");
  });

  it("keeps customers out of the provider and admin areas", async () => {
    mockApi({ "GET /api/config": () => config(false), "GET /api/auth/me": () => me(["customer"]) });
    renderAt("/p");
    expect(await screen.findByRole("heading", { name: "This is for providers" })).toBeInTheDocument();
  });

  it("guards the admin console", async () => {
    mockApi({ "GET /api/config": () => config(false), "GET /api/auth/me": () => me(["customer"]) });
    renderAt("/admin/providers");
    expect(await screen.findByRole("heading", { name: "This is for the OneQuickJob team only." })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Admin" })).toHaveTextContent("Manual dispatch mode");
  });

  it("shows the admin placeholder to admins", async () => {
    mockApi({ "GET /api/config": () => config(false), "GET /api/auth/me": () => ({ ...me(["admin"]), home_path: "/admin" }) });
    renderAt("/admin/pricing");
    expect(await screen.findByRole("heading", { name: "Pricing and calibration" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /pricing/i })).toHaveAttribute("aria-current", "page");
  });

  it("has a not-found page", async () => {
    mockApi({ "GET /api/config": () => config(false), "GET /api/auth/me": unauthorised });
    renderAt("/nowhere");
    expect(await screen.findByRole("heading", { name: "We can't find that page" })).toBeInTheDocument();
  });
});
