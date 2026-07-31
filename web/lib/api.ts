/**
 * Server-side helpers for talking to FastAPI.
 *
 * The access token lives in an httpOnly cookie and is attached here, in route
 * handlers. It is never sent to the browser, so client components cannot leak
 * it and XSS cannot read it.
 */

import { cookies } from "next/headers";

export const API_BASE_URL = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

export const TOKEN_COOKIE = "rag_token";

/**
 * The user's own Anthropic key, for the life of this browser session.
 *
 * Deliberately a **session cookie** — no maxAge, so it dies when the browser
 * closes. The backend never stores the key (only a hash and a fingerprint), so
 * this cookie is the only copy in existence; giving it a long life would
 * quietly undo the guarantee the backend is built around.
 *
 * That produces two distinct states the UI has to tell apart:
 *   configured — the server holds a fingerprint, so a key was set at some point
 *   active     — this browser session holds the actual key
 * A user who is `configured` but not `active` will find Claude refusing to
 * work, and needs to be told to paste the key again rather than left guessing.
 */
export const ANTHROPIC_KEY_COOKIE = "rag_anthropic_key";

export async function getToken(): Promise<string | null> {
  const store = await cookies();
  return store.get(TOKEN_COOKIE)?.value ?? null;
}

export async function getAnthropicKey(): Promise<string | null> {
  const store = await cookies();
  return store.get(ANTHROPIC_KEY_COOKIE)?.value ?? null;
}

/** Cookie flags shared by both credentials. */
export function cookieOptions(request: Request) {
  // Derive `secure` from the actual request protocol, not NODE_ENV: keying it
  // to NODE_ENV sets Secure on an http://localhost cookie, the browser never
  // sends it back, and everything 401s while appearing to have worked.
  const forwardedProto = request.headers.get("x-forwarded-proto");
  const isHttps =
    forwardedProto === "https" || new URL(request.url).protocol === "https:";
  return { httpOnly: true, sameSite: "lax" as const, secure: isHttps, path: "/" };
}

export class Unauthenticated extends Error {
  constructor() {
    super("Not signed in");
  }
}

/**
 * Fetch from FastAPI with the caller's credentials attached.
 *
 * Both the bearer token and the Anthropic key are added here, in one place, so
 * no route handler has to remember to do it — and so neither can reach the
 * browser. Attaching the key on every call rather than only the generating
 * ones is deliberate: an allowlist is a thing to forget when a route is added,
 * and the backend ignores the header wherever it is irrelevant.
 */
export async function apiFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = await getToken();
  if (!token) throw new Unauthenticated();

  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);

  const anthropicKey = await getAnthropicKey();
  if (anthropicKey) headers.set("X-Anthropic-Key", anthropicKey);

  return fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
}

/** Map a thrown Unauthenticated into a 401 JSON response. */
export function unauthenticatedResponse(): Response {
  return Response.json({ detail: "Not signed in" }, { status: 401 });
}
