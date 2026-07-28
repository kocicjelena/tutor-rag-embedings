/** Answer from lessons the learner has already had. */

import { apiFetch, Unauthenticated, unauthenticatedResponse } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    const body = await request.text();
    const upstream = await apiFetch("/api/v1/tutor/recall", {
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
    return Response.json({ detail: "Recall failed." }, { status: 502 });
  }
}
