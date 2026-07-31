import actionTypes from "@/types/interfaces/actionTypes";
import type { StreamAction } from "@/types/interfaces/ContextType";
import type { StreamKind, StreamType } from "@/types/interfaces/StreamType";
import { initialStream } from "@/types/interfaces/StreamType";

export { initialStream };

/**
 * Pure, synchronous, and the only place the stream slice changes shape.
 *
 * Two rules worth keeping:
 *   - STREAM_BEGIN resets. A new question never shows the tail of the last one.
 *   - STREAM_ERROR keeps whatever text arrived. A half answer plus the reason it stopped is more
 *     useful than an empty box, and it is what the user was already reading.
 */
export const streamReducer = (
  state: StreamType = initialStream,
  action: StreamAction,
): StreamType => {
  const { type, payload } = action as { type: string; payload?: Record<string, unknown> };

  switch (type) {
    case actionTypes.STREAM_BEGIN:
      return {
        ...initialStream,
        status: "streaming",
        kind: (payload?.kind as StreamKind | undefined) ?? null,
        streamId: (payload?.streamId as string | undefined) ?? null,
        startedAt: Date.now(),
      };

    case actionTypes.STREAM_PROVIDER:
      return {
        ...state,
        provider: (payload?.provider as string | undefined) ?? state.provider,
        model: (payload?.model as string | undefined) ?? state.model,
      };

    case actionTypes.STREAM_CHUNK: {
      const text = (payload?.text as string | undefined) ?? "";
      return {
        ...state,
        lastChunk: text,
        text: state.text + text,
        chunkCount: state.chunkCount + 1,
      };
    }

    case actionTypes.STREAM_END:
      // A stream that already failed stays failed — `done` after `error` would erase the reason.
      return state.status === "error"
        ? state
        : { ...state, status: "done", endedAt: Date.now() };

    case actionTypes.STREAM_ERROR:
      return {
        ...state,
        status: "error",
        error: (payload?.error as string | undefined) ?? "Unknown stream error",
        endedAt: Date.now(),
      };

    case actionTypes.CLEAR_STREAM:
      return { ...initialStream };

    default:
      return state;
  }
};
