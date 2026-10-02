import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { config, mockApi, renderWithProviders, unauthorised } from "../test/utils";
import { DemoTools } from "./DemoTools";
import { PrototypeBanner } from "./PrototypeBanner";

const outbox = [
  {
    id: "m2",
    channel: "sms",
    recipient: { user_id: null, name: "Dave Hughes", phone: "+447700900201", email: null },
    template_id: "job_alert",
    subject: null,
    body: "OneQuickJob: New job near you. Take a look: https://dev.onequickjob.co.uk/p/j/R-2301?t=tok",
    related: {},
    created_at: new Date().toISOString(),
    not_before: null,
  },
  {
    id: "m1",
    channel: "sms",
    recipient: { user_id: null, name: "", phone: "+447700900123", email: null },
    template_id: "login_code",
    subject: null,
    body: "OneQuickJob: your sign-in code is 482913. It expires in 10 minutes. Don't share it with anyone.",
    related: {},
    created_at: new Date().toISOString(),
    not_before: null,
  },
];

function App() {
  return (
    <>
      <PrototypeBanner />
      <DemoTools />
    </>
  );
}

describe("DEMO_MODE on", () => {
  it("shows the banner, the Outbox drawer with codes and in-app links, and Switch user", async () => {
    mockApi({
      "GET /api/config": () => config(true),
      "GET /api/auth/me": unauthorised,
      "GET /api/demo/outbox": () => outbox,
      "GET /api/demo/users": () => [
        { user_id: "u1", demo_key: "sarah", name: "Sarah Whitfield", roles: ["customer"], group: "Customers", description: "Customer", home_path: "/account" },
        { user_id: "u2", demo_key: "dave", name: "Dave Hughes", roles: ["provider"], group: "Providers", description: "Provider", home_path: "/p" },
      ],
    });
    renderWithProviders(<App />);
    expect(await screen.findByRole("note")).toHaveTextContent("Prototype: test payments only");

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /outbox/i }));
    const panel = await screen.findByRole("dialog", { name: "Outbox" });
    expect(await screen.findByText("482913")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /R-2301/ });
    expect(link).toHaveAttribute("href", "/p/j/R-2301?t=tok");
    expect(panel).toHaveTextContent("job_alert");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /switch user/i }));
    expect(await screen.findByText("Dave Hughes")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Providers" })).toBeInTheDocument();
  });
});

describe("DEMO_MODE off", () => {
  it("renders none of the demo tools and never calls the demo endpoints", async () => {
    const fetchMock = mockApi({
      "GET /api/config": () => config(false),
      "GET /api/auth/me": unauthorised,
      "GET /api/demo/outbox": () => outbox,
    });
    const { container } = renderWithProviders(<App />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /outbox/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /switch user/i })).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
    const demoCalls = fetchMock.mock.calls.filter(([req]) => String(req instanceof Request ? req.url : req).includes("/api/demo/"));
    expect(demoCalls).toHaveLength(0);
  });
});
