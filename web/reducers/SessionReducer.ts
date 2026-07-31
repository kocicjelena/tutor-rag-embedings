import actionTypes from "@/types/interfaces/actionTypes";
import type { SessionAction } from "@/types/interfaces/ContextType";
import type { SessionType } from "@/types/interfaces/SessionType";
import { initialSession } from "@/types/interfaces/SessionType";

export { initialSession };

export const sessionReducer = (
  state: SessionType = initialSession,
  action: SessionAction,
): SessionType => {
  const { type, payload } = action as { type: string; payload?: Record<string, unknown> };

  switch (type) {
    case actionTypes.SET_SIGNED_IN:
      return { ...state, signedIn: (payload?.signedIn as boolean | undefined) ?? null };

    default:
      return state;
  }
};
