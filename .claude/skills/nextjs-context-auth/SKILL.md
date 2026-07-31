---
name: nextjs-context-auth
description: Jelena's own Next.js conventions for global state (React Context + useReducer, split `{ state, actions }`, one reducer per slice, types in types/interfaces/) and for authentication (NextAuth v5, lib/auth.ts + app/api/auth/[...nextauth]/route.ts, a Credentials provider that verifies a proof, a session callback that exposes an identifier and never the credential). Use whenever adding global state, a context slice, a streaming/async action, or auth to any of her Next.js apps — before writing a store or an auth route from memory.
---

# How Jelena builds state and auth in Next.js

Derived 2026-07-31 by reading three of her projects, at her request, so a future
session does not re-invent a store she already runs in production shapes.

**Sources (READ-ONLY — never edit them):**

| Project | What it shows |
|---|---|
| `~/multichain-main/my` | the reference store: `context/GlobalContext.tsx`, `reducers/WalletReducer.ts`, `types/interfaces/{actionTypes,ContextType,WalletType}.ts` |
| `~/ollama8jul` | the same shape at scale — 9 slices in `globalx/`, `react-combine-reducers`, async actions that call `/api/*` |
| `~/my-sei-dapp` | NextAuth v5: `lib/auth.ts`, `app/api/auth/[...nextauth]/route.ts`, `app/api/auth/nonce/route.ts` |

Copy the pattern into the repo you are working in. Do not import across
projects, and do not edit the sources.

## The store

Five files, and the same five every time.

```
types/interfaces/actionTypes.ts   one flat map of string constants, typed by an ATypes interface
types/interfaces/XxxType.ts       the slice's shape + `initialXxx`
types/interfaces/ContextType.ts   IContextState, IContextAction, and a XxxAction union
reducers/XxxReducer.ts            pure, switch on `type`, `default: return state`
context/GlobalContext.tsx         useReducer + useCallback actions + two contexts
```

**The value is split.** `StateContext` and `ActionsContext` are separate, with
`useContextState()` / `useContextActions()` hooks that throw outside the
provider. A component that only dispatches does not re-render when unrelated
state moves. This is the part most tutorials get wrong and she does not.

**The root reducer is manual** in the small version:

```ts
function rootReducer(state: IContextState, action: any): IContextState {
  return { wallet: walletReducer(state.wallet, action) };
}
```

At scale (`~/ollama8jul/globalx/`) the same thing is `react-combine-reducers`
with `{ slice: [reducer, initial] }`. Both are the same idea; pick the manual one
until there are four or five slices, and **do not add the dependency just to
have it** — in a repo that builds inside Docker, one more package is one more
thing in `npm ci`.

**Actions are named functions, `useCallback`-wrapped, gathered in a `useMemo`**
whose dependency array lists every one of them. Names say what happened
(`onChainChanged`, `appendChunk`), not which reducer they hit.

**Reducers are boring on purpose.** Each slice sees every action and ignores
what is not its own. Payloads are read defensively
(`(payload?.x as T | undefined) ?? state.x`) because the action union is a
convenience, not a runtime guarantee.

### The rule that actually matters: async work belongs to the provider

Her words, 2026-07-31: *"an async generator passed to a coroutine has to be
async and can be recorded in context — that is what the app has to memoise, and
memoise can be kept in context and it won't hang or disappear."*

What that means in practice, and why it is right:

- A `fetch` + SSE reader is a **coroutine**. Whoever holds it owns the stream.
  Hold it in a component and it dies with the component; hold it in a provider
  action and the chunks keep being recorded whatever is on screen.
- The action is `useCallback(..., [])` — `dispatch` is stable, so the action's
  identity never changes, so putting it in a downstream dependency array
  restarts nothing. **That** is the memoisation, not `useMemo` on data.
- The action **returns** the finished result as well as dispatching, because the
  caller usually still has work to do with the whole answer.
- Give it an `onEvent` escape hatch for events the slice deliberately does not
  model. The store stays about one thing.

`web/context/GlobalContext.tsx` in `mcp-py` (`runStream`) is the worked example.

**Where an external system owns the truth** — a wallet, a service worker, a
socket — the subscription goes in a `useEffect` *inside the provider*, so the
store is correct the moment it mounts, regardless of which components rendered.
See `WalletReducer` + the `chainChanged` effect in `~/multichain-main/my`.

## Auth

**NextAuth v5** (`next-auth@^5.0.0-beta.31`), and only ever through
`app/api/auth/[...nextauth]/route.ts`. Her reason, and it is a good one: it is
the one place Next.js expects the session to live, so nothing downstream has to
invent a session format, and OIDC issuers plug into it without touching the app.

Three files:

```ts
// lib/auth.ts
export const { handlers, auth, signIn, signOut } = NextAuth({
  session: { strategy: "jwt" },
  providers: [Credentials({ /* … */ authorize })],
  callbacks: { session({ session, token }) { /* expose an identifier */ } },
  pages: { signIn: "/" },
});

// app/api/auth/[...nextauth]/route.ts
import { handlers } from "@/lib/auth";
export const { GET, POST } = handlers;
```

The shape to keep, whatever the credential is:

1. **`authorize` verifies a proof, it does not trust an assertion.** In
   `my-sei-dapp` that is a wallet signature over a **server-issued nonce**, held
   in an httpOnly cookie so a captured signature cannot be replayed. In an
   email/password app it is the backend's own login endpoint. Either way,
   `authorize` returns `{ id }` or `null` — never a partially trusted user.
2. **The `session` callback publishes an identifier, never the credential.**
   `session.address = token.sub` there; `session.publicId` here. The address is
   the public handle; the private key never appears. The same reasoning maps
   exactly onto email → the derived id.
3. **Anything secret goes in the JWT, not in the session object.** The v5 JWT
   is an encrypted httpOnly cookie, readable only on the server via `auth()`.
   A backend access token can ride there; it must not be copied into `session`,
   which is sent to the browser.
4. `AUTH_SECRET` is required in production. In a container it must be an
   environment variable, or the app boots and then 500s on the first sign-in.

**When Cognito arrives**, it is a second entry in the same `providers` array —
`next-auth/providers/cognito` with issuer, client id and secret — and the same
`session` callback. Nothing else in the app changes. That is the whole reason
for going through `[...nextauth]` early rather than late.

## Applying this to a repo that already has auth

Do not tear the working path out first. In `mcp-py` the browser session is a
FastAPI JWT in an httpOnly cookie set by a route handler; NextAuth can sit in
front of it, with `authorize` calling that same login endpoint and the FastAPI
token stored in the NextAuth JWT. The backend, its tests and its owner scoping
do not move. Swap the *issuer* later, once the IdP exists — one change, not two.
