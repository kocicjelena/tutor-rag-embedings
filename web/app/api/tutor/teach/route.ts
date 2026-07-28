/**
 * SSE proxy for the tutor's explanation stream.
 *
 * This is the route that replaces the ported `lib/claudeTutor.ts`, which
 * constructed `new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY,
 * dangerouslyAllowBrowser: true })` inside a module reachable from a
 * "use client" hook. That never actually worked — Next only inlines
 * NEXT_PUBLIC_* vars, so the key was undefined in the browser — but the
 * tempting "fix" (renaming it NEXT_PUBLIC_) would have shipped the key to
 * every visitor. Here the key stays on the FastAPI side and is never in a
 * bundle at all.
 */

import { apiFetch, Unauthenticated, unauthenticatedResponse } from "@/lib/api";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(request: Request) {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return Response.json({ detail: "Invalid JSON body" }, { status: 400 });
  }

  try {
    const upstream = await apiFetch("/api/v1/tutor/teach", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!upstream.ok || !upstream.body) {
      const text = await upstream.text();
      return new Response(text || '{"detail":"Upstream error"}', {
        status: upstream.status,
        headers: { "Content-Type": "application/json" },
      });
    }

    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
      },
    });
  } catch (error) {
    if (error instanceof Unauthenticated) return unauthenticatedResponse();
    return Response.json(
      { detail: "Could not reach the API. Is FastAPI running?" },
      { status: 502 },
    );
  }
}
