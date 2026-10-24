import type { GuardrailStep, ToolStep, TraceStep } from "../types";

export const isTool = (s: TraceStep): s is ToolStep => s.type === "tool";
export const isGuardrail = (s: TraceStep): s is GuardrailStep => s.type === "guardrail";

/** Every guardrail or policy event in a turn, in order: top-level steps and per-tool events. */
export function guardrailNames(trace: TraceStep[]): string[] {
  const names: string[] = [];
  for (const step of trace) {
    if (isGuardrail(step)) names.push(step.name);
    if (isTool(step)) step.guardrails.forEach((g) => names.push(g.guardrail));
  }
  return names;
}

/** Guardrails that stopped something (as opposed to policy checks that merely ran). */
const BLOCKING = new Set([
  "input_injection",
  "tool_output_injection",
  "ownership_check",
  "argument_validation",
  "handoff_active",
  "max_steps",
  "tool_budget",
]);

export function isBlocking(name: string): boolean {
  return BLOCKING.has(name);
}

export type Tone = "ok" | "warn" | "bad";

export function toolTone(step: ToolStep): Tone {
  if (step.status !== "ok") return "bad";
  const decision = step.result.status;
  if (decision === "denied") return "warn";
  if (decision === "pending_review") return "warn";
  return "ok";
}

export function summarize(trace: TraceStep[]): string {
  const tools = trace.filter(isTool).map((s) => s.name);
  const guards = guardrailNames(trace).filter(isBlocking);
  const parts = [tools.length ? `${tools.length} tool call${tools.length > 1 ? "s" : ""}` : "no tools"];
  if (guards.length) parts.push(`${guards.length} guardrail${guards.length > 1 ? "s" : ""}`);
  return parts.join(" · ");
}
