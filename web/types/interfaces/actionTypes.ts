/**
 * String-keyed action constants for the global context.
 *
 * One flat map, one constant per dispatchable action. New slices append their constants here and
 * never remove another slice's — the reducer for each slice ignores everything it doesn't know.
 *
 * Copied convention: ~/multichain-main/my/types/interfaces/actionTypes.ts.
 */
interface ATypes {
  // ── stream ──
  STREAM_BEGIN: string;
  STREAM_PROVIDER: string;
  STREAM_CHUNK: string;
  STREAM_END: string;
  STREAM_ERROR: string;
  CLEAR_STREAM: string;
  // ── model (built while the learning happens) ──
  MODEL_SESSION_START: string;
  MODEL_QUEUE: string;
  MODEL_SENDING: string;
  MODEL_SYNCED: string;
  MODEL_ERROR: string;
  CLEAR_MODEL: string;
}

const actionTypes: ATypes = {
  STREAM_BEGIN: "STREAM_BEGIN",
  STREAM_PROVIDER: "STREAM_PROVIDER",
  STREAM_CHUNK: "STREAM_CHUNK",
  STREAM_END: "STREAM_END",
  STREAM_ERROR: "STREAM_ERROR",
  CLEAR_STREAM: "CLEAR_STREAM",
  MODEL_SESSION_START: "MODEL_SESSION_START",
  MODEL_QUEUE: "MODEL_QUEUE",
  MODEL_SENDING: "MODEL_SENDING",
  MODEL_SYNCED: "MODEL_SYNCED",
  MODEL_ERROR: "MODEL_ERROR",
  CLEAR_MODEL: "CLEAR_MODEL",
};

export default actionTypes;
