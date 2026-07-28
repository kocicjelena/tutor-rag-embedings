/** Record a completed exchange into the learner's corpus. */

import { apiFetch, Unauthenticated, unauthenticatedResponse } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    const body = await request.text();
    const upstream = await apiFetch("/api/v1/tutor/interactions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    if (error instanceof Unauthenticated) return unauthenticatedResponse();
    return Response.json({ detail: "Could not record the lesson." }, { status: 502 });
  }
}
