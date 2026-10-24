import { summarize } from "../lib/trace";
import type { Turn } from "../types";
import { TraceTimeline } from "./TraceTimeline";

export function Conversation({ turns, pending }: { turns: Turn[]; pending?: string | null }) {
  return (
    <div className="conversation">
      {turns.map((turn, i) => (
        <div key={i} className="turn">
          <div className="bubble user">{turn.user}</div>
          <div className="bubble agent">
            <p>{turn.reply}</p>
            <details className="trace-toggle" open={turn.trace.some((s) => s.type !== "reply")}>
              <summary>{summarize(turn.trace)}</summary>
              <TraceTimeline trace={turn.trace} />
            </details>
          </div>
        </div>
      ))}
      {pending && (
        <div className="turn">
          <div className="bubble user">{pending}</div>
          <div className="bubble agent typing">…</div>
        </div>
      )}
    </div>
  );
}
