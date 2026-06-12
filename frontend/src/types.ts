export interface LoginUser {
  user_id: string;
  company_id: string;
  company_name: string;
  email: string;
  role: string;
  access_scope: string;
}

export interface Run {
  run_id: string;
  prompt: string;
  status: "running" | "completed" | "failed";
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentInfo {
  id: string;
  run_id: string | null;
  filename: string;
  doc_type: string;
  created_at: string;
}

export interface ToolEvent {
  kind: "tool_start" | "tool_end";
  tool: string;
  detail: string;
}

/** One conversation entry = one agent run, streamed or replayed. */
export interface ChatEntry {
  runId: string;
  prompt: string;
  status: "running" | "completed" | "failed";
  liveText: string;       // streamed tokens (reasoning + intermediate output)
  finalText: string;      // the 'final' chunk, rendered as the answer
  tools: ToolEvent[];
  error: string | null;
}
