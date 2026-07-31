import actionTypes from "@/types/interfaces/actionTypes";
import type { ModelAction } from "@/types/interfaces/ContextType";
import type {
  LearningEvent,
  LearningModelState,
  LearningPiece,
  ModelType,
} from "@/types/interfaces/ModelType";
import { RECENT_LIMIT, initialModel } from "@/types/interfaces/ModelType";

export { initialModel };

/**
 * The model slice. Pure, and deliberately dull.
 *
 * The one rule worth stating: `MODEL_SYNCED` **replaces** the state with what the server
 * sent rather than merging into it. The database is what is true; a browser that merges is
 * a browser that can drift, and drift in a model is worse than a gap.
 */
export const modelReducer = (
  state: ModelType = initialModel,
  action: ModelAction,
): ModelType => {
  const { type, payload } = action as { type: string; payload?: Record<string, unknown> };

  switch (type) {
    case actionTypes.MODEL_SESSION_START:
      return {
        ...initialModel,
        sessionId: (payload?.sessionId as string | undefined) ?? null,
        status: "idle",
      };

    case actionTypes.MODEL_QUEUE: {
      const piece = payload?.piece as LearningPiece | undefined;
      if (!piece) return state;
      return {
        ...state,
        queued: [...state.queued, piece],
        nextSeq: Math.max(state.nextSeq, piece.seq + 1),
      };
    }

    case actionTypes.MODEL_SENDING: {
      const count = (payload?.count as number | undefined) ?? 0;
      // The batch leaves the queue as it goes on the wire. If the request fails it is
      // re-queued by MODEL_ERROR, so nothing is lost by removing it here.
      return {
        ...state,
        status: "sending",
        inFlight: count,
        queued: state.queued.slice(count),
      };
    }

    case actionTypes.MODEL_SYNCED: {
      const accepted = (payload?.accepted as LearningEvent[] | undefined) ?? [];
      return {
        ...state,
        status: "synced",
        inFlight: 0,
        error: null,
        recent: [...state.recent, ...accepted].slice(-RECENT_LIMIT),
        state: (payload?.state as LearningModelState | undefined) ?? state.state,
      };
    }

    case actionTypes.MODEL_ERROR: {
      const returned = (payload?.pieces as LearningPiece[] | undefined) ?? [];
      return {
        ...state,
        status: "error",
        inFlight: 0,
        // Back to the front of the queue, in order: a failed push is a push to retry,
        // not learning to throw away.
        queued: [...returned, ...state.queued],
        error: (payload?.error as string | undefined) ?? "Could not reach the model",
      };
    }

    case actionTypes.CLEAR_MODEL:
      return { ...initialModel };

    default:
      return state;
  }
};
