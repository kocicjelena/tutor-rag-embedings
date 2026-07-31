/**
 * The user's own Anthropic key.
 *
 * Two stores, and keeping them straight is the whole job here:
 *
 *   FastAPI  holds a hash and a fingerprint. Survives restarts. Cannot call
 *            Anthropic — that is the point.
 *   Cookie   holds the real key, httpOnly, session-scoped. This is the only
 *            copy in existence, and `lib/api.ts` attaches it to every proxied
 *            request as `X-Anthropic-Key`.
 *
 * So a user can be `configured` (server has the fingerprint) without being
 * `active` (this browser lost the key when it closed). The UI shows both,
 * because "you have a key" plus "Claude does not work" is otherwise baffling.
 *
 * The key never reaches a client component. It arrives in a POST body, goes
 * upstream for verification, becomes a cookie, and is not echoed back.
 */

import {
  ANTHROPIC_KEY_COOKIE,
  Unauthenticated,
  apiFetch,
  cookieOptions,
  getAnthropicKey,
  unauthenticatedResponse,
} from "@/lib/api";
import { cookies } from "next/headers";

interface KeyStatus {
  configured: boolean;
  key: { fingerprint: string; created_at: string; last_used_at: string | null } | null;
  app_key_fallback: boolean;
}

export async function GET() {
  try {
    const upstream = await apiFetch("/api/v1/keys/anthropic");
    if (!upstream.ok) {
      return Response.json(await upstream.json(), { status: upstream.status });
    }
    const status = (await upstream.json()) as KeyStatus;
    return Response.json({
      ...status,
      // Whether THIS browser session can actually make a Claude call.
      active: (await getAnthropicKey()) !== null,
    });
  } catch (err) {
    if (err instanceof Unauthenticated) return unauthenticatedResponse();
    throw err;
  }
}

export async function PUT(request: Request) {
  const { api_key: apiKey } = (await request.json()) as { api_key?: string };
  if (!apiKey?.trim()) {
    return Response.json({ detail: "Paste your Anthropic API key." }, { status: 400 });
  }

  try {
    // Upstream verifies it against Anthropic and stores the hash. Only once it
    // says yes does the key become a cookie — so a typo never leaves this
    // browser holding a credential the server disagrees about.
    const upstream = await apiFetch("/api/v1/keys/anthropic", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: apiKey }),
    });

    if (!upstream.ok) {
      const body = (await upstream.json().catch(() => ({}))) as { detail?: unknown };
      return Response.json(
        { detail: typeof body.detail === "string" ? body.detail : "Key rejected." },
        { status: upstream.status },
      );
    }

    const stored = (await upstream.json()) as { fingerprint: string };

    const store = await cookies();
    // No maxAge: a session cookie. It dies with the browser, which is the
    // behaviour that matches "this app does not keep your key".
    store.set(ANTHROPIC_KEY_COOKIE, apiKey.trim(), cookieOptions(request));

    // Fingerprint only. The key does not travel back to the browser that just
    // sent it — there is no reason to, and every reason not to.
    return Response.json({ ok: true, fingerprint: stored.fingerprint, active: true });
  } catch (err) {
    if (err instanceof Unauthenticated) return unauthenticatedResponse();
    throw err;
  }
}

export async function DELETE() {
  try {
    const upstream = await apiFetch("/api/v1/keys/anthropic", { method: "DELETE" });
    const store = await cookies();
    store.delete(ANTHROPIC_KEY_COOKIE);
    if (!upstream.ok) {
      // The cookie is gone either way — the local copy is what could leak.
      return Response.json({ ok: true, detail: "Key cleared from this browser." });
    }
    return Response.json({ ok: true });
  } catch (err) {
    if (err instanceof Unauthenticated) return unauthenticatedResponse();
    throw err;
  }
}
