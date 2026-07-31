/**
 * Types for `react-combine-reducers`, which ships none.
 *
 * The package itself is four lines of runtime: it takes `{ slice: [reducer, initialState] }`
 * and returns `[combinedReducer, combinedInitialState]`, the pair `useReducer` wants. Jelena
 * uses it in her other Next.js projects, so this app uses it too rather than a hand-rolled
 * root reducer that does the same thing in a different shape.
 *
 * The reducer in each pair is `any` on purpose: every slice reducer declares its own narrow
 * action union, and TypeScript's contravariance would reject them all against a single
 * combined union. The *state* stays fully typed, which is the part that catches mistakes —
 * a slice missing from the map, or an initial value of the wrong shape.
 */
declare module "react-combine-reducers" {
  import type { Reducer } from "react";

  export default function combineReducers<S>(slices: {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    [K in keyof S]: [any, S[K]];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  }): [Reducer<S, any>, S];
}
