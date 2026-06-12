import type { ChatEntry, DocumentInfo, LoginUser, Run } from "./types";

const USER_KEY = "plantwise_user_id";

export function getStoredUserId(): string | null {
  return localStorage.getItem(USER_KEY);
}

export function setStoredUserId(userId: string | null) {
  if (userId) localStorage.setItem(USER_KEY, userId);
  else localStorage.removeItem(USER_KEY);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const userId = getStoredUserId();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string>),
  };
  if (userId) headers["X-User-ID"] = userId;
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

export const api = {
  listUsers: () => request<LoginUser[]>("/api/users"),
  listRuns: () => request<Run[]>("/api/runs"),
  listDocuments: () => request<DocumentInfo[]>("/api/documents"),
  createRun: (prompt: string) =>
    request<Run>("/api/runs", { method: "POST", body: JSON.stringify({ prompt }) }),
};

export function documentDownloadUrl(docId: string): string {
  return `/api/documents/${docId}/download?user_id=${encodeURIComponent(getStoredUserId() ?? "")}`;
}

/** Append user_id to agent-emitted download links (plain <a> can't set headers). */
export function withUserParam(url: string): string {
  if (!url.startsWith("/api/")) return url;
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}user_id=${encodeURIComponent(getStoredUserId() ?? "")}`;
}

/**
 * Open the SSE stream for a run. EventSource cannot set headers, so the user
 * id travels as a query parameter (same tenant gate server-side). Calls the
 * handlers as chunks arrive; returns a cleanup function.
 */
export function streamRun(
  runId: string,
  onUpdate: (patch: Partial<ChatEntry>) => void,
  current: () => ChatEntry,
): () => void {
  const userId = getStoredUserId() ?? "";
  const es = new EventSource(
    `/api/runs/${runId}/stream?user_id=${encodeURIComponent(userId)}`,
  );

  es.addEventListener("token", (e) => {
    onUpdate({ liveText: current().liveText + (e as MessageEvent).data });
  });
  es.addEventListener("tool_start", (e) => {
    const d = JSON.parse((e as MessageEvent).data);
    onUpdate({
      tools: [...current().tools, { kind: "tool_start", tool: d.tool, detail: d.input ?? "" }],
    });
  });
  es.addEventListener("tool_end", (e) => {
    const d = JSON.parse((e as MessageEvent).data);
    onUpdate({
      tools: [...current().tools, { kind: "tool_end", tool: d.tool, detail: d.output ?? "" }],
    });
  });
  es.addEventListener("final", (e) => {
    onUpdate({ finalText: (e as MessageEvent).data });
  });
  es.addEventListener("error", (e) => {
    const data = (e as MessageEvent).data;
    if (typeof data === "string" && data) {
      onUpdate({ error: data, status: "failed" });
    }
  });
  es.addEventListener("done", () => {
    if (!current().error) onUpdate({ status: "completed" });
    es.close();
  });

  return () => es.close();
}
