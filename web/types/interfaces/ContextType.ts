import type { StreamEvent } from "@/lib/types";
import type {
  LearningEvent,
  LearningModelState,
  LearningPiece,
  ModelType,
} from "./ModelType";
import type { StreamKind, StreamType } from "./StreamType";

/**
 * The split context value: `state` is data, `actions` are the named functions that change it.
 * Consumers take one or the other via useContextState() / useContextActions(), so a component
 * that only dispatches doesn't re-render when unrelated state moves.
 *
 * Copied convention: ~/multichain-main/my/types/interfaces/ContextType.ts.
 */
export interface IContextState {
  stream: StreamType;
  model: ModelType;
}

export interface IContextAction {
  /**
   * Drain an SSE response into the store and return what it produced.
   *
   * This is the async action Jelena described: the async generator is consumed *inside* the
   * provider, so the pipe has one owner and one memoised identity. A component that wants the
   * chunks reads `state.stream`; it never holds the reader, and unmounting it does not sever the
   * stream halfway through.
   *
   * Returns the finished text and who produced it, because the caller usually still has work to
   * do with the whole answer — the tutor records it, which is what makes the corpus grow.
   *
   * Errors are dispatched *and* rethrown: the store shows the failure, and the caller's own
   * try/catch still runs.
   */
  runStream: (
    kind: StreamKind,
    streamId: string,
    response: Response,
    onEvent?: (event: StreamEvent) => void,
  ) => Promise<{ text: string; provider: string | null; model: string | null }>;
  /** Start a stream by hand, when the chunks do not come from `runStream`. */
  beginStream: (kind: StreamKind, streamId: string) => void;
  /** Record one chunk exactly as it arrived. */
  appendChunk: (text: string) => void;
  /** Who is answering — dispatched from the `provider` event. */
  setStreamProvider: (provider: string, model: string) => void;
  /** The stream finished normally. */
  endStream: () => void;
  /** The stream failed. The text already received is kept; it is evidence. */
  failStream: (message: string) => void;
  /** Back to idle. Nothing is preserved. */
  clearStream: () => void;

  // ── the model, built while the learning happens ──

  /**
   * Begin a teaching session. Returns the id, so the caller can correlate without reading
   * state back out of the store.
   */
  startLearning: (sessionId?: string) => string;
  /**
   * Send one piece of learning up the channel.
   *
   * The coroutine, on this side: the piece is queued, and a single request is kept in
   * flight. Everything that arrives while it is in flight waits in the queue and goes in
   * the next batch — that is the backpressure, and it is why this returns a promise that
   * resolves when the queue has drained rather than when the piece was handed over.
   *
   * The response replaces `state.model.state` wholesale, because the server's answer is
   * the state of SQLite and the browser is mirroring it, not counting alongside it.
   */
  learn: (text: string, term?: string) => Promise<void>;
  /** Forget the session. The database keeps everything it was told. */
  clearModel: () => void;
}

export type ModelAction =
  | { type: "MODEL_SESSION_START"; payload: { sessionId: string } }
  | { type: "MODEL_QUEUE"; payload: { piece: LearningPiece } }
  | { type: "MODEL_SENDING"; payload: { count: number } }
  | {
      type: "MODEL_SYNCED";
      payload: { accepted: LearningEvent[]; state: LearningModelState };
    }
  | { type: "MODEL_ERROR"; payload: { error: string; pieces: LearningPiece[] } }
  | { type: "CLEAR_MODEL" };

export type StreamAction =
  | { type: "STREAM_BEGIN"; payload: { kind: StreamKind; streamId: string } }
  | { type: "STREAM_PROVIDER"; payload: { provider: string; model: string } }
  | { type: "STREAM_CHUNK"; payload: { text: string } }
  | { type: "STREAM_END" }
  | { type: "STREAM_ERROR"; payload: { error: string } }
  | { type: "CLEAR_STREAM" };
