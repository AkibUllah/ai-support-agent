import { useEffect, useMemo, useState } from "react";

import { api } from "../api";
import type { Transcript } from "../types";
import { Conversation } from "./Conversation";

export function ReplayView({ baseUrl }: { baseUrl: string }) {
  const [transcripts, setTranscripts] = useState<Transcript[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .transcripts(baseUrl)
      .then((data) => {
        setTranscripts(data);
        setSelected(data[0]?.id ?? null);
      })
      .catch((e: Error) => setError(e.message));
  }, [baseUrl]);

  const byCategory = useMemo(() => {
    const groups = new Map<string, Transcript[]>();
    transcripts.forEach((t) => groups.set(t.category, [...(groups.get(t.category) ?? []), t]));
    return [...groups.entries()];
  }, [transcripts]);

  const current = transcripts.find((t) => t.id === selected);
  const passed = transcripts.filter((t) => t.passed).length;

  if (error) return <p className="error">Could not load transcripts: {error}</p>;

  return (
    <section className="replay">
      <aside className="scenario-list" aria-label="Eval scenarios">
        <p className="muted">
          {passed}/{transcripts.length} scenarios passed in the recorded run
        </p>
        {byCategory.map(([category, items]) => (
          <div key={category}>
            <h3>{category.replace("_", " ")}</h3>
            {items.map((t) => (
              <button
                key={t.id}
                className={`scenario ${t.id === selected ? "active" : ""}`}
                onClick={() => setSelected(t.id)}
              >
                <span className={`dot ${t.passed ? "dot-ok" : "dot-bad"}`} aria-label={t.passed ? "passed" : "failed"} />
                {t.id}
              </button>
            ))}
          </div>
        ))}
      </aside>
      <div className="panel">
        {current ? (
          <>
            <header className="chat-head">
              <div>
                <strong>{current.id}</strong> <span className="muted">customer {current.customer}</span>
              </div>
              <span className={`badge ${current.passed ? "badge-ok" : "badge-bad"}`}>
                {current.passed ? "passed" : "failed"}
              </span>
            </header>
            <Conversation turns={current.turns} />
          </>
        ) : (
          <p className="muted">Loading…</p>
        )}
      </div>
    </section>
  );
}
