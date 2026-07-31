"use client";

import { createContext, useCallback, useContext, useMemo, useReducer, useRef } from "react";
import actionTypes from "@/types/interfaces/actionTypes";
import type { IContextAction, IContextState } from "@/types/interfaces/ContextType";
import type { LearningPiece } from "@/types/interfaces/ModelType";
import type { StreamKind } from "@/types/interfaces/StreamType";
import type { StreamEvent } from "@/lib/types";
import { readEventStream } from "@/lib/stream";
import { initialModel, modelReducer } from "@/reducers/ModelReducer";
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
  model: initialModel,
};

// Manual root reducer — each slice sees every action and ignores what isn't its own.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function rootReducer(state: IContextState, action: any): IContextState {
  return {
    stream: streamReducer(state.stream, action),
    model: modelReducer(state.model, action),
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

  // ── model actions: the channel from the browser to the backend ──
  //
  // Refs, not state, for the three things the *pipeline* needs: they must be readable and
  // writable inside an in-flight async action without re-creating it, and a stale closure
  // here would send the same piece twice or lose one. What the UI reads still comes from
  // the reducer; these are the pipeline's own bookkeeping.
  const sessionRef = useRef<string | null>(null);
  const queueRef = useRef<LearningPiece[]>([]);
  const seqRef = useRef(0);
  const drainingRef = useRef<Promise<void> | null>(null);

  const startLearning = useCallback((sessionId?: string) => {
    const id = sessionId ?? crypto.randomUUID();
    sessionRef.current = id;
    queueRef.current = [];
    seqRef.current = 0;
    dispatch({ type: actionTypes.MODEL_SESSION_START, payload: { sessionId: id } });
    return id;
  }, []);

  const syncModel = useCallback(async (sessionId: string) => {
    dispatch({ type: actionTypes.MODEL_SESSION_START, payload: { sessionId } });
    sessionRef.current = sessionId;
    queueRef.current = [];

    try {
      const response = await fetch(
        `/api/tutor/learn?session_id=${encodeURIComponent(sessionId)}`,
      );
      if (!response.ok) throw new Error(`Could not read the model (${response.status})`);
      const state = await response.json();
      // Continue where the database left off. Starting at zero after a reload would
      // collide with rows already stored, and every one of them would come back as
      // `skipped` — correct, and silently useless.
      seqRef.current = (state.last_seq ?? -1) + 1;
      dispatch({
        type: actionTypes.MODEL_SYNCED,
        payload: { accepted: [], state },
      });
    } catch (err) {
      dispatch({
        type: actionTypes.MODEL_ERROR,
        payload: {
          error: err instanceof Error ? err.message : "Could not read the model",
          pieces: [],
        },
      });
    }
  }, []);

  const clearModel = useCallback(() => {
    sessionRef.current = null;
    queueRef.current = [];
    seqRef.current = 0;
    dispatch({ type: actionTypes.CLEAR_MODEL });
  }, []);

  /**
   * Drain the queue, one request at a time.
   *
   * This is the backpressure. While a batch is on the wire, new pieces accumulate in the
   * queue rather than opening a second request — so the browser never runs ahead of the
   * embedder, and SQLite (one writer) never sees two pushes for the same session at once.
   * The loop continues until the queue is empty, which is why a caller can `await learn()`
   * and know the model is up to date.
   */
  const drain = useCallback(async (sessionId: string, term?: string) => {
    while (queueRef.current.length > 0) {
      const batch = queueRef.current;
      queueRef.current = [];
      dispatch({ type: actionTypes.MODEL_SENDING, payload: { count: batch.length } });

      try {
        const response = await fetch("/api/tutor/learn", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, term, pieces: batch }),
        });
        if (!response.ok) {
          const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
          throw new Error(
            typeof body.detail === "string" ? body.detail : `Learn failed (${response.status})`,
          );
        }
        const payload = await response.json();
        dispatch({
          type: actionTypes.MODEL_SYNCED,
          payload: { accepted: payload.accepted, state: payload.state },
        });
      } catch (err) {
        dispatch({
          type: actionTypes.MODEL_ERROR,
          payload: {
            error: err instanceof Error ? err.message : "Could not reach the model",
            pieces: batch,
          },
        });
        // Stop draining rather than spin: the pieces are back in the reducer's queue and
        // the next `learn()` retries them. Retrying here would hammer a server that is
        // already failing, and every piece carries its own seq, so nothing duplicates.
        queueRef.current = [...batch, ...queueRef.current];
        return;
      }
    }
  }, []);

  const learn = useCallback(
    async (text: string, term?: string) => {
      if (!text.trim()) return;
      const sessionId = sessionRef.current ?? startLearning();

      const piece: LearningPiece = { seq: seqRef.current++, text };
      queueRef.current = [...queueRef.current, piece];
      dispatch({ type: actionTypes.MODEL_QUEUE, payload: { piece } });

      // One drain at a time. A second caller joins the promise already running instead of
      // starting a rival loop — the queue it just added to will be picked up by that loop.
      if (!drainingRef.current) {
        drainingRef.current = drain(sessionId, term).finally(() => {
          drainingRef.current = null;
        });
      }
      await drainingRef.current;
    },
    [drain, startLearning],
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
      startLearning,
      learn,
      syncModel,
      clearModel,
    }),
    [
      runStream,
      beginStream,
      appendChunk,
      setStreamProvider,
      endStream,
      failStream,
      clearStream,
      startLearning,
      learn,
      syncModel,
      clearModel,
    ],
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
