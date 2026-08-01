/**
 * The learner's model, as it is being built.
 *
 * Jelena's design, 2026-07-31: *"State of SQLite goes into GlobalContext.tsx with its own
 * reducers, state and actions."* So this slice is a **mirror**, not a tally. Every field
 * below arrives from the server's answer to a push; nothing here is counted in the browser.
 * A client that misses a response recovers from the next one, because the next one carries
 * the whole state rather than a delta.
 *
 * The distinction that makes the design make sense: embedding here is how learning becomes
 * the material of a model, not how text becomes findable. The search index is a separate
 * thing and this pipeline never writes to it.
 */

/** One piece on its way up the channel, before the server has seen it. */
export interface LearningPiece {
  seq: number;
  text: string;
}

/** One piece as the server stored it. */
export interface LearningEvent {
  seq: number;
  text: string;
  term: string | null;
  /**
   * Distance from the nearest thing the learner already had. Small means "you have met this
   * before", large means "this is new to you". Null when the corpus was empty — with nothing
   * to compare against the question has no answer, and a default would look like a
   * measurement.
   */
  novelty: number | null;
  created_at: string;
}

/** What SQLite holds for this session. Returned whole with every push. */
export interface LearningModelState {
  session_id: string;
  events: number;
  terms: string[];
  mean_novelty: number | null;
  last_seq: number | null;
  embedded_with: string;
  /**
   * How many vectors the model holds, across every session — not just this one.
   *
   * The vectors are the part that makes it a model rather than a transcript, which is why
   * this is reported separately from `events`. Jelena's instruction, overruling an earlier
   * decision to compute novelty and drop the vector: *"Without that it is not worth having
   * embeddings."* They live in their own index (`vec_learning`); the search index is never
   * written to by this pipeline.
   */
  vectors: number;
}

/** One piece of the learner's own material, near another. `POST /tutor/learn/similar`. */
export interface LearningNeighbour {
  seq: number;
  text: string;
  term: string | null;
  session_id: string;
  /** Straight out of the index. Smaller is nearer. */
  distance: number;
}

export interface LearningNeighbours {
  query: string;
  matches: LearningNeighbour[];
  /** How many vectors were available to compare against. 0 means the model is empty. */
  searched: number;
}

export type ModelStatus = "idle" | "sending" | "synced" | "error";

export interface ModelType {
  status: ModelStatus;
  /** Which teaching session these pieces belong to. Null until one starts. */
  sessionId: string | null;
  /** The next sequence number to hand out. Monotonic within a session. */
  nextSeq: number;
  /**
   * Pieces waiting to go up. The channel keeps one request in flight and lets the rest
   * queue here — that is the backpressure, and it is why the action is a coroutine rather
   * than a fire-and-forget.
   */
  queued: LearningPiece[];
  /** How many pieces are in flight right now. 0 or the size of the batch being sent. */
  inFlight: number;
  /** The most recent pieces the server confirmed, newest last. Capped. */
  recent: LearningEvent[];
  /** The server's state, mirrored verbatim. Null before the first response. */
  state: LearningModelState | null;
  error: string | null;
}

/** How many confirmed events to keep for display. The database keeps all of them. */
export const RECENT_LIMIT = 20;

export const initialModel: ModelType = {
  status: "idle",
  sessionId: null,
  nextSeq: 0,
  queued: [],
  inFlight: 0,
  recent: [],
  state: null,
  error: null,
};
