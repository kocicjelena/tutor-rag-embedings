# Identity and who pays for Claude

Started 2026-07-30. Two separate things that arrived in one conversation and
are easy to confuse, so they are kept apart here:

1. **Who the user is** — a derived public id now, federated login later.
2. **Whose Anthropic key pays** — built and tested, working today.

---

# The plan this serves — read first

Recorded 2026-07-31, at Jelena's correction, because the sessions before it had
started describing the app by its cheapest working part.

## The app is meant to be an identity provider

Not "a RAG demo that is cheap to host". **The app issues identity**, and the
tutor and retrieval are what that identity is *for*. Jelena's plan, in her
words and structure:

- A user **registers with an email**, and the app computes their id from it.
  That is what `app/core/identity.py` already does — `public_id` is not a
  URL-safety detail, it is the first piece of this.
- They get **their own page, by route** — the `/u/[user]` shape from her other
  project.
- They are **tied to this app as their identity provider**, not to Google. They
  keep their Google identity private and hand over only an email; the app
  issues identity onward to their DIDs.
- The **same email yields a wallet**, through another of her apps.

So the identity is the product and the through-line between her projects. The
RAG, the tutor, MCP and the exportable model are what that identity accumulates
and owns.

## The app has to earn, because it costs money to run

BYOK is **a stage, not the destination.** Requiring an Anthropic key works for
someone who already has an account and knows where the console is. Most people
have neither, and will not spend an evening finding out. The direction is that
the user **pays for the app**, and the app pays for its own models.

**Status: not built.** Nothing about billing exists in this codebase.

| | |
|---|---|
| **For** | The app stops being a cost centre. It removes the biggest barrier for a normal visitor — most people will not create an Anthropic account to try a demo. It is the only path where the app can run without either an open invoice or a locked door |
| **Against** | Payments mean an account model, a provider, invoices, refunds, tax, and a support obligation. All of that is real work with no learning value for the LLM/RAG/MCP goals, and none of it can be undone casually once someone has paid |

## What that means for how this app is described

**BYOK is true and useful and it is not the headline.** It solves *who pays for
Claude on a free Space today*. Describing it as the app's main advantage
shrinks an identity product into a hosting trick — which is exactly what the
earlier sessions did, repeatedly, in `DEPLOY-HF.md`, `CONTINUE.md` and the
status page.

The accurate framing, and the one to keep:

> The app issues identity. BYOK is how it currently affords to do that in
> public, until it can charge for itself.

## Built vs planned, plainly

| | |
|---|---|
| `public_id` — one-way HMAC of the email, stable, URL-safe | **built** |
| BYOK — per-user Anthropic keys, nothing usable stored | **built** |
| Registration by email, with the app as the issuer | **not built** — there is no public signup at all |
| A user's own page by route | **not built** |
| Federated login | **not built** — waiting on IdP credentials |
| Issuing identity onward to DIDs | **not built**, and no code assumes it |
| Wallet from the same email, via the other app | **not built here**, and out of this repo's scope |
| Paying for the app itself | **not built** |

Nothing on the "not built" side should be built speculatively. It is written
down so that the next simplification is a **recorded deferral** rather than a
quiet redefinition of what the app is.

## BYOK stays — a standing instruction

Demoting BYOK from *the point of the app* to *a stage* is a change of framing,
**not a plan to remove it.** Jelena's instruction, 2026-07-31:

> Save space for adding an Anthropic key on the Hugging Face Space. That has to
> stay as a feature — distant, an addition, independent, but **live**.

So: *distant* from the identity plan and *independent* of it, and working on the
deployed Space. Do not fold it into billing, do not hide it behind a future
account model, and do not delete it when the app can charge for itself. A user
who already has an Anthropic account should always be able to bring their key
and pay nothing.

What that requires, concretely — check these before calling a deploy good:

| | |
|---|---|
| `USER_ANTHROPIC_KEYS=true` | Set explicitly in the `Dockerfile`, not left to the default. With `ALLOW_APP_KEY_FALLBACK=false` beside it, turning this off leaves the Space with **no route to Claude at all**, and it fails looking like a broken provider rather than a config choice |
| The *Claude access* panel on `/` | The only way a visitor can supply one. It is not admin UI and does not move behind a login wall |
| The session cookie over HTTPS | `cookieOptions` derives `secure` from `x-forwarded-proto`, which Spaces sets. Keyed to `NODE_ENV` instead, the browser would silently drop the cookie and every Claude call would 503 |
| `deploy/space-README.md` | Tells a visitor to bring a key, and why it is safe to |

`tests/test_user_keys.py` asserts the Dockerfile still carries the flag, so
removing it fails the suite rather than the Space.

Patterns were read from `~/my-sei-dapp` (NextAuth v5 credentials provider, the
hash-and-verify shape in `lib/server/apiKeys.ts`) and rewritten here. **Nothing
in that repo was modified** — it is reference material, like `related/`.

---

## The correction worth recording

The original ask was: *store the user's Anthropic API key hashed, so the app
does not know it, but the user is charged for Claude.*

**A hash is one-way.** With only `sha256(key)` the app cannot call Anthropic,
so nobody can be billed. "The app never knows the key" and "the user's account
pays" cannot both be true of a stored hash.

What is built instead keeps almost all of the intent:

| | |
|---|---|
| **In the database** | `sha256(key)` and a fingerprint `sk-ant-…AB12`. Neither can call Anthropic. |
| **In the session** | the real key, held by the browser's httpOnly cookie, server-side only |
| **Per request** | sent as `X-Anthropic-Key`, used once, dropped |

So: a dump of the database is worth nothing, the app holds the key only in
memory for the length of one request, and Anthropic bills the user. The cost is
that the key must be re-entered when the session ends — which is the honest
price of not storing it.

The rejected alternative was encrypting it at rest. Encryption is reversible;
that is its purpose and its problem. An encrypted column means the app *can*
read every user's key, so one server compromise leaks all of them, and Jelena
ends up holding credentials she never wanted to hold.

---

## Why this matters more than it looks

From `.claude/rules/PLAN.md` §6: a public URL with paid Claude calls behind it is an
open invoice. And on Hugging Face Spaces **there is no Ollama**, so Claude is
the only generator. Those two facts together meant the public demo could not
really be public.

Bring-your-own-key removes the problem at the root rather than rationing it.
Rate limiting is still wanted, but it is no longer the only thing standing
between a demo link and a bill.

---

## Built and working

### The derived public id — `app/core/identity.py`

`User.id` stays a random UUID and stays internal. `derive_public_id(email)`
adds a **public** handle for URLs, links and logs:

```
derive_public_id("a@b.com") → "k3m9x2..."   (26 chars, base32, lowercase)
```

- **Deterministic** — the same email always derives the same handle, so links
  keep working and re-registration lands on the same one.
- **One-way** — the email never appears in it. That matters because the handle
  is meant for public, crawlable pages.
- **HMAC, not a plain hash** — with `sha256(email)` anyone could hash a list of
  addresses and ask the app which exist. The server-side pepper closes that.

Exposed as `public_id` on `UserPublic`, computed rather than stored, so it
cannot drift from the email and there is no column to migrate.

> **`IDENTITY_PEPPER` is permanent once anything is published.** It falls back
> to `SECRET_KEY`, which means rotating `SECRET_KEY` after a token leak would
> otherwise change every public id and break every link. Set it before the
> first published URL. A test asserts the dependency so this stays known.

### Per-user Anthropic keys

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/keys/anthropic` | Have I got a key on file? What happens without one? |
| `PUT` | `/api/v1/keys/anthropic` | Hand over a key — verified, hashed, plaintext dropped |
| `DELETE` | `/api/v1/keys/anthropic` | Forget it |

- **No route can return a key.** Not for the owner, not for a superuser. There
  is no read endpoint at all, so no bug in that file can leak one.
- The key is **verified against Anthropic** when set, by listing models — a
  call that costs no tokens. A typo is caught while the user is looking at the
  field, not three screens later as a confusing 503.
- `PUT` rather than `POST`: a second key replaces the first. One key per user,
  because two would leave nobody able to say which is being billed.
- New **table** (`UserApiKey`), not columns on `User` — `create_all` adds
  missing tables but never missing columns, and there are no migrations. Same
  reason as `TutorLesson`.

### Billing routing

`get_chat_provider(name, api_key=...)` builds a **short-lived** Claude provider
bound to the caller's key. Never cached: a cache is precisely where one user's
credential could be handed to another, and the client object is cheap.

`GET /providers/` is now **per user** — Claude reads as available to anyone who
brought a key, even when the app holds none. A single global answer would tell
a visitor with a working key that the feature is off.

Error messages change with who owns the key. "ANTHROPIC_API_KEY is invalid" is
wrong twice over when the bad key is the visitor's: it names a variable they
cannot see and blames the app for something they can fix.

### Tests — 28, all offline

Several assert on *shape* rather than behaviour, because the guarantee fails
silently:

- no field on `UserApiKey` may be named `key` / `encrypted_key` / `secret` /
  `token` — an "encrypted key" column added later for convenience would break
  the whole claim while every functional test still passed;
- nothing in the response schemas may carry a key-shaped field;
- the stored row contains neither the key nor any 20-character run of it;
- the public id contains no fragment of the email.

---

## What has to be done

### Yours — AWS console

You said you would set up federation and bring back the client id and secret.

- [ ] Create the user pool / application, and note **client id**, **client
      secret**, **issuer URL**.
- [ ] Callback `http://localhost:3000/api/auth/callback/<provider>` for dev,
      and the deployed origin for the Space.
- [ ] Send me the three values and I will wire the provider. **Put them in
      `.env`, never in `app/core/config.py`** — that file is committed.

> One thing to check before you spend time in the console: `.claude/rules/AUTH.md` in
> `~/my-sei-dapp` is an **Auth0** setup (it names a live `*.eu.auth0.com`
> tenant — the domain is in that file), not AWS Cognito. They are different
> products with different SDKs and different env variables. If you already have
> the Auth0 tenant working, using it here is less work than starting Cognito
> from scratch — but either is fine, and I only need to know which.

### Mine — backend

- [ ] **Federated login provider** once the credentials exist. The attachment
      point is `app/api/deps.py`: today the caller comes from a bearer token
      this app signs. A federated user arrives with an IdP token instead, and
      the subject claim maps onto `User` — matched by email, the same rule
      `init_db` already uses.
- [ ] **Public signup.** There is deliberately no signup route today. Federation
      makes one unnecessary for the IdP path, but decide whether email+password
      signup also opens. Related: `.claude/rules/TODO.md` "Decide how visitors get
      accounts".
- [ ] **`note_use` is never called.** `last_used_at` will always be null until
      the query and tutor routes call it after a successful Claude answer. Small,
      but it is currently a field that promises something it does not deliver.

### Frontend — done 2026-07-30

- [x] `AnthropicKeyPanel` on `/`: paste a key, see the fingerprint, replace,
      remove.
- [x] The key lives in an **httpOnly session cookie** — never `localStorage`,
      never a `NEXT_PUBLIC_` variable, never returned to a client component.
- [x] `X-Anthropic-Key` is attached in **`apiFetch`**, not per route. Every
      proxy already goes through it, so no route can be forgotten when one is
      added. (Verified: `auth/route.ts` is the only handler that does not use
      `apiFetch`, and it is the sign-in itself.)
- [x] The cookie is dropped on **sign-out and on sign-in**. On a shared machine
      an inherited key would bill the previous user for a stranger's questions.
- [x] The provider picker reloads when a key is added or removed, and shows the
      backend's explanation of why Claude is unavailable.

**`configured` is not `active`.** The server holds a fingerprint that survives
restarts; the browser holds the only real copy and loses it when it closes. So
a returning user is `configured` but not `active`, and Claude will refuse. The
panel says so in as many words — *"this app never stores it, so it is gone when
the browser closes"* — because "you have a key" plus "Claude does not work" is
otherwise indistinguishable from a bug.

### The problems, stated plainly

**1. Re-entry on every browser restart.** The direct cost of not storing the
key. Mitigated by saying so in the panel, not by hiding it. If it becomes
annoying in practice the honest fix is a longer-lived encrypted cookie — *not*
a database column, which would give up the guarantee entirely.

**2. `note_use` is written but never called**, so `last_used_at` is always
null. A field that promises something it does not deliver. Either call it from
the query and tutor routes after a successful Claude answer, or remove it.

**3. Nothing rate-limits key verification.** `PUT /keys/anthropic` makes a live
call to Anthropic on every attempt, so it is an unauthenticated-ish way to
generate outbound traffic (authenticated, but any account can loop it). Small,
but it belongs on the Milestone 4 list.

**4. The key passes through this app's memory.** It has to — that is what
making the call means. "The app does not know your key" is true of the
*database*, and true of everything that persists; it is not true of the request
that uses it. The panel does not overclaim, and neither should any README.

### Before the public deploy

- [ ] `ALLOW_APP_KEY_FALLBACK=false`. Otherwise every visitor spends your
      balance and the whole exercise was decorative.
- [ ] `IDENTITY_PEPPER` set to a real value.
- [ ] Rate limiting — still wanted. Uploads and embedding cost CPU even when
      Claude costs the visitor.
