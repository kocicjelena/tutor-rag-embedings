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
  /** Which embedding model indexed it. Null while it is still pending. */
  indexed_with: string | null;
  /**
   * False when a different embedding model indexed it. Vectors from two models
   * are not comparable, so search genuinely cannot reach it — the list says so
   * rather than quietly returning nothing. Fixed by
   * `uv run python -m app.scripts.reembed`.
   */
  searchable: boolean;
}

/**
 * What the app can do, as the app itself reports it.
 *
 * `running` is measured, not declared: a probe succeeded moments ago. The
 * fourth status is the interesting one — `exploring` means examined and
 * deliberately refused, because building it would have made the rest mean less.
 */
export type CapabilityStatus = "running" | "built" | "building" | "exploring";

export type CapabilityArea = "llm" | "rag" | "mcp" | "identity" | "deploy";

export interface Capability {
  key: string;
  name: string;
  area: CapabilityArea;
  status: CapabilityStatus;
  summary: string;
  detail: string | null;
  doc: string | null;
  /** What the probe observed. Null when the status is declared, not measured. */
  evidence: string | null;
  probed: boolean;
}

export interface CapabilityReport {
  data: Capability[];
  generated_at: string;
  totals: Partial<Record<CapabilityStatus, number>>;
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
