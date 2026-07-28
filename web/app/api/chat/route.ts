/**
 * SSE proxy for the streaming RAG endpoint.
 *
 * The upstream body is passed straight through rather than buffered, so tokens
 * reach the browser as FastAPI produces them. Two details matter:
 *
 *  - `Content-Type: text/event-stream` and `Cache-Control: no-cache` must be
 *    set on the response, or the browser (and any proxy) may buffer it.
 *  - Node's fetch will not stream a request body without `duplex: "half"`, and
 *    Next needs `dynamic = "force-dynamic"` so the route is never cached.
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
    const upstream = await apiFetch("/api/v1/query/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    // A provider misconfiguration comes back as a JSON 503 before the stream
    // opens — forward it as-is so the UI can show the real reason.
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
