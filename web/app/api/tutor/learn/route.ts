/**
 * The upward channel: pieces of learning, as they happen.
 *
 * Deliberately many small requests rather than one long-lived socket. Two reasons, and
 * both are about this stack rather than about taste: `fetch` can only stream a *request*
 * body in Chromium and only over HTTP/2, and nothing here serves HTTP/2 today — uvicorn
 * speaks HTTP/1.1, and so does the Next.js dev server in front of it. A small POST per
 * batch works on both, gets cheaper by itself the day a proxy terminates h2, and keeps the
 * property that matters: nothing waits for the answer to finish.
 *
 * Each piece carries its own `seq`, and the backend treats a repeat as a skip, so a retried
 * request is free.
 */

import { apiFetch, Unauthenticated, unauthenticatedResponse } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    const upstream = await apiFetch("/api/v1/tutor/learn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: await request.text(),
    });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    if (error instanceof Unauthenticated) return unauthenticatedResponse();
    return Response.json(
      { detail: "Could not reach the model." },
      { status: 502 },
    );
  }
}
