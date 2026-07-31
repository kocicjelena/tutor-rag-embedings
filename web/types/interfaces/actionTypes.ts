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
}

const actionTypes: ATypes = {
  STREAM_BEGIN: "STREAM_BEGIN",
  STREAM_PROVIDER: "STREAM_PROVIDER",
  STREAM_CHUNK: "STREAM_CHUNK",
  STREAM_END: "STREAM_END",
  STREAM_ERROR: "STREAM_ERROR",
  CLEAR_STREAM: "CLEAR_STREAM",
};

export default actionTypes;
