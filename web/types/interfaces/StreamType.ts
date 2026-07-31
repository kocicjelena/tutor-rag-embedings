/**
 * The stream slice: the answer that is arriving right now, one chunk at a time.
 *
 * Jelena's requirement, 2026-07-31: *"a chunk is processed, not a document — the tutor will be
 * able to access that last chunk at least"*, and the piping of chunks belongs to a React
 * provider rather than to props.
 *
 * **Current stream only.** `STREAM_BEGIN` wipes the slice, so nothing here outlives the question
 * that produced it. The permanent copy is server-side: every lesson is indexed and kept verbatim
 * in `TutorLesson`. A second, drifting copy in the browser would be a bug, not a feature — which
 * is why there is no localStorage here and no transcript.
 *
 * Nothing in this slice is a mirror of an external system in the wallet sense; it is the app's own
 * output, recorded as it is produced so that any component can read it without being handed it.
 */

/** Which server call is producing the chunks. The tutor cares: `teach` grows the corpus. */
export type StreamKind = "teach" | "recall" | "query" | "agent";

export type StreamStatus = "idle" | "streaming" | "done" | "error";

export interface StreamType {
  status: StreamStatus;
  /** Which producer is running, null when idle. */
  kind: StreamKind | null;
  /**
   * The caller's own id for this stream — the assistant message id in the tutor, so a component
   * can tell "the stream in context is the one I am rendering" from "someone else's".
   */
  streamId: string | null;
  /**
   * The last chunk exactly as it arrived off the wire. Not the answer, not a sentence — the
   * frame. This is the field Jelena asked for, and it is deliberately raw.
   */
  lastChunk: string | null;
  /** Every chunk so far, joined. The answer as it stands. */
  text: string;
  /** How many chunks have arrived. Cheap, and it makes "is anything happening" answerable. */
  chunkCount: number;
  /** Who answered, once the server has said so. */
  provider: string | null;
  model: string | null;
  error: string | null;
  /** `Date.now()` when the stream began / finished. Null while not applicable. */
  startedAt: number | null;
  endedAt: number | null;
}

export const initialStream: StreamType = {
  status: "idle",
  kind: null,
  streamId: null,
  lastChunk: null,
  text: "",
  chunkCount: 0,
  provider: null,
  model: null,
  error: null,
  startedAt: null,
  endedAt: null,
};
