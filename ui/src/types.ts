export type SessionState = "active" | "handoff" | "closed";

export interface Customer {
  id: string;
  name: string;
  district: string;
  phone_masked: string;
}

export interface GuardrailEvent {
  guardrail: string;
  [key: string]: unknown;
}

export interface ToolStep {
  type: "tool";
  step: number;
  name: string;
  arguments: Record<string, unknown>;
  status: "ok" | "error" | "invalid_arguments" | "unknown_tool" | "blocked";
  result: Record<string, unknown>;
  duration_ms: number;
  guardrails: GuardrailEvent[];
}

export interface GuardrailStep {
  type: "guardrail";
  name: string;
  [key: string]: unknown;
}

export interface ReplyStep {
  type: "reply";
  step: number;
}

export interface HandoffStep {
  type: "handoff";
  reason: string;
}

export interface ErrorStep {
  type: "error";
  name: string;
  step: number;
}

export type TraceStep = ToolStep | GuardrailStep | ReplyStep | HandoffStep | ErrorStep;

export interface Turn {
  user: string;
  reply: string;
  state: SessionState;
  trace: TraceStep[];
}

export interface SessionInfo {
  session_id: string;
  token: string;
  customer: Customer;
  state: SessionState;
}

export interface TurnResponse {
  turn_id: number;
  reply: string;
  state: SessionState;
  trace: TraceStep[];
}

export interface Transcript {
  id: string;
  category: string;
  customer: string;
  passed: boolean;
  failures: string[];
  turns: Turn[];
}
