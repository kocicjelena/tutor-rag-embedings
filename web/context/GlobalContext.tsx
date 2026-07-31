"use client";

import { createContext, useCallback, useContext, useMemo, useReducer } from "react";
import actionTypes from "@/types/interfaces/actionTypes";
import type { IContextAction, IContextState } from "@/types/interfaces/ContextType";
import type { StreamKind } from "@/types/interfaces/StreamType";
import type { StreamEvent } from "@/lib/types";
import { readEventStream } from "@/lib/stream";
import { initialStream, streamReducer } from "@/reducers/StreamReducer";

/**
 * The global store: React Context + useReducer, with the value split into `{ state, actions }`.
 *
 * The shape is Jelena's, copied from ~/multichain-main/my/context/GlobalContext.tsx: a manual
 * root reducer, `useCallback` actions, two contexts so a component that only dispatches does not
 * re-render when state moves.
 *
 * Right now it holds one slice, `stream`. Adding another means: a constant in actionTypes, a
 * XxxType + initialXxx, a XxxReducer, one line in `rootReducer`, one line in `initialState`, a
 * useCallback here, and the fn added to the `actions` useMemo and its dependency array.
 *
 * <GlobalProvider> is mounted once in app/layout.tsx, so every page has it.
 */

const initialState: IContextState = {
  stream: initialStream,
};

// Manual root reducer — each slice sees every action and ignores what isn't its own.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function rootReducer(state: IContextState, action: any): IContextState {
  return {
    stream: streamReducer(state.stream, action),
  };
}

const StateContext = createContext<IContextState | null>(null);
const ActionsContext = createContext<IContextAction | null>(null);

export function GlobalProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(rootReducer, initialState);

  // ── stream actions ──

  const beginStream = useCallback((kind: StreamKind, streamId: string) => {
    dispatch({ type: actionTypes.STREAM_BEGIN, payload: { kind, streamId } });
  }, []);

  const appendChunk = useCallback((text: string) => {
    dispatch({ type: actionTypes.STREAM_CHUNK, payload: { text } });
  }, []);

  const setStreamProvider = useCallback((provider: string, model: string) => {
    dispatch({ type: actionTypes.STREAM_PROVIDER, payload: { provider, model } });
  }, []);

  const endStream = useCallback(() => {
    dispatch({ type: actionTypes.STREAM_END });
  }, []);

  const failStream = useCallback((message: string) => {
    dispatch({ type: actionTypes.STREAM_ERROR, payload: { error: message } });
  }, []);

  const clearStream = useCallback(() => {
    dispatch({ type: actionTypes.CLEAR_STREAM });
  }, []);

  /**
   * The async action: an SSE response in, chunks into the store, the finished answer out.
   *
   * Why it lives here rather than in each component. `readEventStream` is an async generator, so
   * consuming it is a coroutine that must be `await`ed — and whoever holds it owns the stream. Put
   * that in a component and the pipe dies with the component; put it in the provider and the
   * chunks are recorded whatever is on screen. The identity is stable (`useCallback` with no
   * dependencies, because `dispatch` never changes), so passing it to a `useCallback` or
   * `useEffect` downstream does not restart anything — that is the memoisation Jelena means by
   * "so it won't hang or disappear".
   *
   * `onEvent` is the escape hatch for events this slice deliberately does not model — `sources`
   * and the tool trace, which belong to the caller's own panels. The store stays about chunks.
   */
  const runStream = useCallback(
    async (
      kind: StreamKind,
      streamId: string,
      response: Response,
      onEvent?: (event: StreamEvent) => void,
    ) => {
      dispatch({ type: actionTypes.STREAM_BEGIN, payload: { kind, streamId } });

      let text = "";
      let provider: string | null = null;
      let model: string | null = null;

      try {
        for await (const event of readEventStream(response)) {
          onEvent?.(event);

          if (event.type === "provider") {
            provider = event.provider;
            model = event.model;
            dispatch({
              type: actionTypes.STREAM_PROVIDER,
              payload: { provider: event.provider, model: event.model },
            });
          } else if (event.type === "token") {
            text += event.text;
            dispatch({ type: actionTypes.STREAM_CHUNK, payload: { text: event.text } });
          } else if (event.type === "error") {
            throw new Error(event.message);
          }
        }
      } catch (err) {
        // A user pressing Stop is not a failure. The fetch was aborted deliberately, so the
        // stream ends where it ends; only the caller needs to know it was cut short.
        if (err instanceof Error && err.name === "AbortError") {
          dispatch({ type: actionTypes.STREAM_END });
          throw err;
        }
        const message = err instanceof Error ? err.message : "Stream failed";
        dispatch({ type: actionTypes.STREAM_ERROR, payload: { error: message } });
        // Rethrown on purpose: the store records the failure, and the caller's own error
        // handling — which knows what to do with a half-written message — still runs.
        throw err;
      }

      dispatch({ type: actionTypes.STREAM_END });
      return { text, provider, model };
    },
    [],
  );

  const actions = useMemo<IContextAction>(
    () => ({
      runStream,
      beginStream,
      appendChunk,
      setStreamProvider,
      endStream,
      failStream,
      clearStream,
    }),
    [runStream, beginStream, appendChunk, setStreamProvider, endStream, failStream, clearStream],
  );

  return (
    <StateContext.Provider value={state}>
      <ActionsContext.Provider value={actions}>{children}</ActionsContext.Provider>
    </StateContext.Provider>
  );
}

export function useContextState(): IContextState {
  const ctx = useContext(StateContext);
  if (!ctx) throw new Error("useContextState must be used inside <GlobalProvider>.");
  return ctx;
}

export function useContextActions(): IContextAction {
  const ctx = useContext(ActionsContext);
  if (!ctx) throw new Error("useContextActions must be used inside <GlobalProvider>.");
  return ctx;
}
