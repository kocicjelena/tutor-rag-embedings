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
  // ── providers: who answers, and with which model ──
  PROVIDERS_LOADING: string;
  SET_PROVIDERS: string;
  PROVIDERS_ERROR: string;
  SET_PROVIDER: string;
  SET_MODEL: string;
  CLEAR_PROVIDERS: string;
  // ── session ──
  SET_SIGNED_IN: string;
}

/**
 * `as const satisfies ATypes` rather than `: ATypes`, and the difference is the whole point.
 *
 * With the annotation, every constant has type `string`, so `actionTypes.STREAM_BEGIN` is
 * indistinguishable from `"STRAEM_BEGIN"` and a dispatch could carry any payload at all —
 * the action unions in ContextType.ts were decoration. `as const` gives each one its literal
 * type; `satisfies` keeps the interface doing its job, which is to fail the build when a
 * slice adds a constant here and forgets to declare it above.
 */
const actionTypes = {
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
  PROVIDERS_LOADING: "PROVIDERS_LOADING",
  SET_PROVIDERS: "SET_PROVIDERS",
  PROVIDERS_ERROR: "PROVIDERS_ERROR",
  SET_PROVIDER: "SET_PROVIDER",
  SET_MODEL: "SET_MODEL",
  CLEAR_PROVIDERS: "CLEAR_PROVIDERS",
  SET_SIGNED_IN: "SET_SIGNED_IN",
} as const satisfies ATypes;

export default actionTypes;
