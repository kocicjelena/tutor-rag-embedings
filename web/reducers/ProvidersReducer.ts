import actionTypes from "@/types/interfaces/actionTypes";
import type { ProvidersAction } from "@/types/interfaces/ContextType";
import type { ProvidersType } from "@/types/interfaces/ProvidersType";
import { initialProviders } from "@/types/interfaces/ProvidersType";
import type { ProvidersPayload } from "@/lib/types";

export { initialProviders };

export const providersReducer = (
  state: ProvidersType = initialProviders,
  action: ProvidersAction,
): ProvidersType => {
  const { type, payload } = action as { type: string; payload?: Record<string, unknown> };

  switch (type) {
    case actionTypes.PROVIDERS_LOADING:
      return { ...state, loading: true, error: null };

    case actionTypes.SET_PROVIDERS: {
      const data = (payload?.data as ProvidersPayload | undefined) ?? null;
      return { ...state, data, loading: false, loaded: true, error: null };
    }

    case actionTypes.PROVIDERS_ERROR:
      return {
        ...state,
        loading: false,
        loaded: true,
        error: (payload?.error as string | undefined) ?? "Could not load providers",
      };

    case actionTypes.SET_PROVIDER: {
      // Changing provider clears the model. A model name belongs to one provider, and
      // carrying `llama3.1:8b` into Claude would send a request that cannot be served —
      // the empty string means "this provider's default", which always exists.
      const provider = (payload?.provider as string | undefined) ?? state.provider;
      return {
        ...state,
        provider,
        model: (payload?.model as string | undefined) ?? "",
      };
    }

    case actionTypes.SET_MODEL:
      return { ...state, model: (payload?.model as string | undefined) ?? "" };

    case actionTypes.CLEAR_PROVIDERS:
      return { ...initialProviders };

    default:
      return state;
  }
};
