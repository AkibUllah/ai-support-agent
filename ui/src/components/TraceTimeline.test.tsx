import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TraceTimeline } from "./TraceTimeline";
import type { TraceStep } from "../types";

const trace: TraceStep[] = [
  {
    type: "tool",
    step: 1,
    name: "lookup_order",
    arguments: { order_id: "HO-10041" },
    status: "error",
    result: { error: "order_not_found" },
    duration_ms: 0.8,
    guardrails: [{ guardrail: "ownership_check", order_id: "HO-10041", blocked: true }],
  },
  { type: "reply", step: 2 },
];

describe("TraceTimeline", () => {
  it("shows tool name, status and guardrail chips", () => {
    render(<TraceTimeline trace={trace} />);
    expect(screen.getByText("lookup_order")).toBeInTheDocument();
    expect(screen.getByText("error")).toBeInTheDocument();
    expect(screen.getByText("ownership_check")).toHaveClass("chip-block");
  });

  it("expands to show arguments and result", async () => {
    render(<TraceTimeline trace={trace} />);
    expect(screen.queryByText(/order_not_found/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /lookup_order/ }));
    expect(screen.getByText(/order_not_found/)).toBeInTheDocument();
  });

  it("renders a blocked input as a guardrail banner", () => {
    render(<TraceTimeline trace={[{ type: "guardrail", name: "input_injection", blocked: true }]} />);
    expect(screen.getByText("guardrail: input_injection")).toBeInTheDocument();
  });
});
