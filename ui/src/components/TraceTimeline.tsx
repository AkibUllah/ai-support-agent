import { useState } from "react";

import { guardrailNames, isBlocking, isTool, toolTone } from "../lib/trace";
import type { HandoffStep, ToolStep, TraceStep } from "../types";

function Json({ value }: { value: unknown }) {
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>;
}

function ToolCard({ step }: { step: ToolStep }) {
  const [open, setOpen] = useState(false);
  const tone = toolTone(step);
  return (
    <li className={`tool tone-${tone}`}>
      <button className="tool-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="tool-name">{step.name}</span>
        <span className={`badge badge-${tone}`}>
          {step.status === "ok" ? String(step.result.status ?? "ok") : step.status}
        </span>
        <span className="muted">{step.duration_ms.toFixed(1)} ms</span>
      </button>
      {step.guardrails.length > 0 && (
        <div className="chips">
          {step.guardrails.map((g, i) => (
            <span key={i} className={`chip ${isBlocking(g.guardrail) ? "chip-block" : ""}`}>
              {g.guardrail}
              {typeof g.action === "string" ? `: ${g.action}` : ""}
            </span>
          ))}
        </div>
      )}
      {open && (
        <div className="tool-body">
          <div className="label">arguments</div>
          <Json value={step.arguments} />
          <div className="label">result</div>
          <Json value={step.result} />
        </div>
      )}
    </li>
  );
}

export function TraceTimeline({ trace }: { trace: TraceStep[] }) {
  if (trace.length === 0) return null;
  const blocking = guardrailNames(trace.filter((s) => !isTool(s))).filter(isBlocking);
  return (
    <div className="trace" aria-label="Turn trace">
      {blocking.length > 0 && (
        <div className="chips">
          {blocking.map((g, i) => (
            <span key={i} className="chip chip-block">
              guardrail: {g}
            </span>
          ))}
        </div>
      )}
      <ol className="tools">
        {trace.filter(isTool).map((step, i) => (
          <ToolCard key={i} step={step} />
        ))}
      </ol>
      {trace
        .filter((s): s is HandoffStep => s.type === "handoff")
        .map((s, i) => (
          <div key={i} className="handoff-note">
            handed to a human: {s.reason}
          </div>
        ))}
    </div>
  );
}
