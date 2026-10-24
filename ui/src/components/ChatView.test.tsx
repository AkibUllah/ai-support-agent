import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ChatView } from "./ChatView";

function mockFetch(routes: Record<string, unknown>) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const key = Object.keys(routes).find((k) => url.endsWith(k));
      if (!key) return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
      return new Response(JSON.stringify(routes[key]), { status: 200 });
    }),
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ChatView", () => {
  it("signs in, sends a message with the bearer token and renders the trace", async () => {
    const calls = mockFetch({
      "/api/customers": [{ id: "C001", name: "Rahim Uddin", district: "Dhaka", phone_masked: "017*****101" }],
      "/api/sessions": {
        session_id: "s1",
        token: "tok",
        state: "active",
        customer: { id: "C001", name: "Rahim Uddin", district: "Dhaka", phone_masked: "017*****101" },
      },
      "/api/sessions/s1/messages": {
        turn_id: 1,
        reply: "Order HO-10024 is with Padma Courier.",
        state: "active",
        trace: [
          {
            type: "tool",
            step: 1,
            name: "track_shipment",
            arguments: { order_id: "HO-10024" },
            status: "ok",
            result: { courier: "Padma Courier" },
            duration_ms: 1,
            guardrails: [],
          },
          { type: "reply", step: 2 },
        ],
      },
    });
    render(<ChatView />);
    await userEvent.click(await screen.findByRole("button", { name: /Rahim Uddin/ }));
    await userEvent.type(screen.getByLabelText("Message"), "Where is HO-10024?");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Order HO-10024 is with Padma Courier.")).toBeInTheDocument();
    expect(screen.getByText("track_shipment")).toBeInTheDocument();
    const send = calls.find((c) => c.url.endsWith("/messages"));
    expect((send?.init?.headers as Record<string, string>).Authorization).toBe("Bearer tok");
  });

  it("shows the handoff badge when the agent hands over", async () => {
    mockFetch({
      "/api/customers": [{ id: "C004", name: "Farzana Akter", district: "Sylhet", phone_masked: "016*****404" }],
      "/api/sessions": {
        session_id: "s2",
        token: "t",
        state: "active",
        customer: { id: "C004", name: "Farzana Akter", district: "Sylhet", phone_masked: "016*****404" },
      },
      "/api/sessions/s2/messages": {
        turn_id: 1,
        reply: "I'm handing this conversation to a human colleague.",
        state: "handoff",
        trace: [{ type: "handoff", reason: "customer asked" }],
      },
    });
    render(<ChatView />);
    await userEvent.click(await screen.findByRole("button", { name: /Farzana/ }));
    await userEvent.click(screen.getByRole("button", { name: "I want to talk to a human" }));
    expect(await screen.findByText("waiting for a human")).toBeInTheDocument();
  });
});
