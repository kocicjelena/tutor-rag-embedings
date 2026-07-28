/**
 * Mirrors app/schemas/events.py and the FastAPI response models.
 *
 * `tool_call` / `tool_result` have no producers in Milestone 1 — the backend
 * defines them and ToolTrace renders them so that adding MCP in Milestone 2 is
 * a backend-only change. See docs/jelena/future4.md.
 */

export interface SourceChunk {
  chunk_id: string;
  document_id: string;
  document_title: string;
  content: string;
  score: number;
}

export type StreamEvent =
  | { type: "provider"; provider: string; model: string }
  | { type: "sources"; chunks: SourceChunk[] }
  | { type: "tool_call"; id: string; name: string; input: Record<string, unknown> }
  | { type: "tool_result"; id: string; ok: boolean; preview: string; duration_ms?: number | null }
  | { type: "token"; text: string }
  | { type: "done"; usage?: Record<string, number> | null }
  | { type: "error"; message: string; code?: string | null };

export interface ModelInfo {
  name: string;
  size?: number | null;
  family?: string | null;
}

export interface ProviderInfo {
  name: string;
  available: boolean;
  default_model: string;
  models: ModelInfo[];
  detail?: string | null;
}

export interface ProvidersPayload {
  data: ProviderInfo[];
  default_provider: string;
  embedding_model: string;
  embedding_dimensions: number;
}

export interface DocumentInfo {
  id: string;
  title: string;
  description: string | null;
  file_type: string | null;
  status: "pending" | "processing" | "ready" | "error";
  chunk_count: number;
  char_count: number;
  error_message: string | null;
  created_at: string;
}

/** A tool invocation paired with its result, for the trace panel. */
export interface ToolRun {
  id: string;
  name: string;
  input: Record<string, unknown>;
  ok?: boolean;
  preview?: string;
  durationMs?: number | null;
}
