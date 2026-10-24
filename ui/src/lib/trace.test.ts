import { guardrailNames, isBlocking, summarize, toolTone } from "./trace";
import type { ToolStep, TraceStep } from "../types";

const tool = (over: Partial<ToolStep> = {}): ToolStep => ({
  type: "tool",
  step: 1,
  name: "initiate_refund",
  arguments: { order_id: "HO-10021" },
  status: "ok",
  result: { status: "approved" },
  duration_ms: 1.2,
  guardrails: [{ guardrail: "refund_policy", action: "approve" }],
  ...over,
});

describe("trace helpers", () => {
  it("collects top-level and per-tool guardrails in order", () => {
    const trace: TraceStep[] = [{ type: "guardrail", name: "input_injection" }, tool()];
    expect(guardrailNames(trace)).toEqual(["input_injection", "refund_policy"]);
  });

  it("distinguishes blocking guardrails from policy checks", () => {
    expect(isBlocking("ownership_check")).toBe(true);
    expect(isBlocking("refund_policy")).toBe(false);
  });

  it("maps tool outcomes to tones", () => {
    expect(toolTone(tool())).toBe("ok");
    expect(toolTone(tool({ result: { status: "pending_review" } }))).toBe("warn");
    expect(toolTone(tool({ status: "error", result: { error: "order_not_found" } }))).toBe("bad");
  });

  it("summarizes a turn", () => {
    expect(summarize([tool(), tool()])).toBe("2 tool calls");
    expect(summarize([{ type: "guardrail", name: "input_injection" }])).toBe("no tools · 1 guardrail");
  });
});
