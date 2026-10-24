import type { Customer, SessionInfo, Transcript, TurnResponse } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const api = {
  customers: () => request<Customer[]>("/api/customers"),
  startSession: (customerId: string) =>
    request<SessionInfo>("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ customer_id: customerId }),
    }),
  send: (session: SessionInfo, text: string) =>
    request<TurnResponse>(`/api/sessions/${session.session_id}/messages`, {
      method: "POST",
      headers: { Authorization: `Bearer ${session.token}` },
      body: JSON.stringify({ text }),
    }),
  transcripts: (baseUrl: string) => request<Transcript[]>(`${baseUrl}transcripts.json`),
};
