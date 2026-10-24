import { ChatView } from "./components/ChatView";
import { ReplayView } from "./components/ReplayView";

export default function App({ mode = import.meta.env.VITE_DEMO_MODE ?? "live" }: { mode?: "live" | "replay" }) {
  return (
    <div className="app">
      <header className="top">
        <div>
          <h1>Haat Online support agent</h1>
          <p className="muted">
            Tool-calling agent with guardrails. Every reply shows the tool calls, results and guardrail events behind it.
          </p>
        </div>
        <a className="link" href="https://github.com/AkibUllah/ai-support-agent">
          Source
        </a>
      </header>
      {mode === "replay" && (
        <p className="banner">
          Recorded run of the offline eval suite (no backend on this page). Open the repo in Codespaces to chat with the live
          agent.
        </p>
      )}
      <main>{mode === "replay" ? <ReplayView baseUrl={import.meta.env.BASE_URL} /> : <ChatView />}</main>
    </div>
  );
}
