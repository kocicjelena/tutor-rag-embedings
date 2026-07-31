# Context and `[...nextauth]` — what is built, and the plan for the rest

Written 2026-07-31. Jelena's instruction: the browser state of this app should
be a **React Context store** on the pattern she runs in her other projects, and
authentication should go through **`app/api/auth/[...nextauth]/route.ts`**,
because *"that is the best rule in Next.js and you will not be chasing circles
of issues"*.

The conventions themselves — copied from `~/multichain-main/my`, `~/ollama8jul`
and `~/my-sei-dapp`, all read-only — are written up once as a skill:
**`.claude/skills/nextjs-context-auth/SKILL.md`**. This file is only about
*this* app: what landed, and what has not.

---

## Built ✅ — the store, and the chunk slice

| File | What it is |
|---|---|
| `web/types/interfaces/actionTypes.ts` | the flat map of action constants, typed by an `ATypes` interface |
| `web/types/interfaces/StreamType.ts` | `StreamType` + `initialStream` — the slice's shape |
| `web/types/interfaces/ContextType.ts` | `IContextState`, `IContextAction`, `StreamAction` |
| `web/reducers/StreamReducer.ts` | pure reducer, switch on `type`, `default: return state` |
| `web/context/GlobalContext.tsx` | `GlobalProvider`, `useContextState()`, `useContextActions()` |
| `web/app/layout.tsx` | the provider mounted once, above every page |

Jelena copied `context/GlobalContext.tsx` and `reducers/WalletReducer.ts` in
from `~/multichain-main/my` as the template. The wallet reducer was **deleted**,
not adapted: it imports `viem` and a `WalletType`, neither of which exists here,
and there is no wallet in this app. The file it came from is untouched in her
other project. What was kept is its *shape*, line for line.

### What the slice holds — and what it deliberately does not

Her requirement: *"a chunk is processed, not a document … the tutor will be able
to access that last chunk at least"*, with the piping of chunks solved by a
React provider rather than by props.

```ts
state.stream = {
  status,       // idle | streaming | done | error
  kind,         // teach | recall | query | agent  — which producer is running
  streamId,     // the caller's id, so a component knows the stream is its own
  lastChunk,    // the last frame, exactly as it arrived off the wire
  text,         // every chunk so far, joined
  chunkCount,
  provider, model,
  error,
  startedAt, endedAt,
}
```

**Current stream only.** `STREAM_BEGIN` wipes the slice, so nothing outlives the
question that produced it — Jelena's decision, taken against keeping a
transcript. The permanent copy is server-side: every lesson is indexed *and*
kept verbatim in `TutorLesson`. A second copy in the browser would drift from
it, and drift is worse than absence.

`STREAM_ERROR` keeps the text that already arrived. Half an answer plus the
reason it stopped is what the reader was already looking at; blanking it is a
second failure on top of the first.

### `runStream` — the async action, and why it is the point

```ts
const { runStream } = useContextActions();
await runStream("teach", assistantId, response, (event) => { /* my own panels */ });
```

`readEventStream` is an async generator; consuming it is a coroutine, and
whoever holds it owns the stream. Held in a component, the pipe dies with the
component. Held in the provider, the chunks are recorded whatever is on screen.
That is the "virtual piping of chunks" solved, and it is exactly her point about
memoisation: `runStream` is `useCallback(..., [])` — `dispatch` never changes —
so its identity is stable, and putting it in a downstream dependency array
restarts nothing.

It returns `{ text, provider, model }` as well as dispatching, because the
caller still has work to do with the whole answer: the tutor records the
exchange, which is how the corpus grows.

Two producers use it today, which is what proves the seam rather than asserting
it:

- `web/hooks/useLearningTutor.ts` → `teach`
- `web/components/ChatStream.tsx` → `query` / `agent`

`sources` and the tool trace stay with the caller through the `onEvent` hatch.
They are that page's panels, not part of the stream — the store stays about
chunks.

**Verified:** `npx tsc --noEmit` clean, `npm run build` succeeds (13 routes,
standalone output intact — the Docker build depends on that). **Not verified:**
nothing has been clicked in a browser since the change. The next person to run
`npm run dev` should ask one question and watch a stream finish.

---

## Not built — NextAuth

> **The plan is to have** the browser session issued through
> `web/app/api/auth/[...nextauth]/route.ts`, with a Credentials provider now and
> **Cognito as a second provider** the day the pool exists — so this app becomes
> an identity provider through the route Next.js already expects, rather than
> through a bespoke cookie.
>
> **Not built.** What exists: `web/app/api/auth/route.ts`, a hand-written route
> handler that posts to `POST /api/v1/login/access-token` and puts the FastAPI
> JWT in an httpOnly cookie (`rag_token`). It works, it is what every proxy route
> reads through `web/lib/api.ts`, and it is what the Space will deploy.
>
> **Reasons for:** one session format instead of two; an OIDC issuer plugs in
> without inventing anything; `signIn` / `signOut` / `auth()` are standard, so
> future sessions stop re-deriving the cookie logic.
>
> **Reasons against:** it adds `next-auth` to a frontend that currently has three
> dependencies, and `AUTH_SECRET` becomes a *boot* requirement in the container.
> Landing it before the first Space build has ever succeeded would mean debugging
> two new things at once.

**Decided 2026-07-31 (Jelena):** Credentials → FastAPI first, Cognito later; and
FastAPI keeps issuing and verifying its own JWT behind NextAuth. So the backend,
its tests and `owner_id` scoping do not move at all — this is a frontend change.

### The shape it takes here

```ts
// web/lib/auth.ts
export const { handlers, auth, signIn, signOut } = NextAuth({
  session: { strategy: "jwt" },
  providers: [
    Credentials({
      credentials: { email: {}, password: {} },
      async authorize(credentials) {
        // The proof is FastAPI's own login. `username` is the email — see CLAUDE.md.
        const res = await fetch(`${API_BASE_URL}/api/v1/login/access-token`, { … });
        if (!res.ok) return null;
        const { access_token } = await res.json();
        const me = await fetch(`${API_BASE_URL}/api/v1/users/me`, { … });
        return { id: me.id, publicId: me.public_id, accessToken: access_token };
      },
    }),
  ],
  callbacks: {
    jwt({ token, user }) { /* keep accessToken on the token — encrypted, httpOnly */ },
    session({ session, token }) { session.publicId = token.publicId; return session; },
  },
});

// web/app/api/auth/[...nextauth]/route.ts
import { handlers } from "@/lib/auth";
export const { GET, POST } = handlers;
```

Four things that must not slip:

1. **The FastAPI token lives on the JWT, never on `session`.** The v5 JWT is an
   encrypted httpOnly cookie read only by the server through `auth()`; `session`
   is sent to the browser. Copying the token across would undo the guarantee
   `lib/api.ts` is built on.
2. **`session` publishes `public_id`, not the email.** Three identifiers,
   `CLAUDE.md`: `User.id` is `owner_id` everywhere, `public_id` is the URL
   handle, the email is a credential. In `my-sei-dapp` the session carries the
   *address* and never the key — same rule, different field.
3. **The Anthropic key cookie is untouched.** `rag_anthropic_key` is a separate
   session cookie by design (hard rule 8). NextAuth must not absorb it.
4. **`AUTH_SECRET`** in `.env.local` locally and as a **Space secret** in
   deployment, plus `AUTH_TRUST_HOST=true` behind the Space's proxy. Missing, it
   boots and then fails on the first sign-in.

### Order of work

1. First Space build succeeds — the current cookie path deploys as it is.
2. `npm i next-auth@beta` on a branch; `lib/auth.ts`, the `[...nextauth]` route,
   a `next-auth.d.ts` module augmentation for `session.publicId`.
3. `web/lib/api.ts::getToken()` reads the token from `auth()` instead of the
   cookie; `components/SignIn.tsx` calls `signIn("credentials")`. Delete
   `web/app/api/auth/route.ts` only when nothing reads it.
4. `AUTH_SECRET` into the Space secrets *before* pushing that branch.
5. Cognito as a second provider, when the pool exists (`.claude/rules/AUTH.md`).

Steps 2–4 are one session's work and touch no Python. Step 5 is the one that
needs the AWS console, and it is the only part waiting on anything.
