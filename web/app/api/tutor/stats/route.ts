/** Corpus-derived progress counts. */

import { apiFetch, Unauthenticated, unauthenticatedResponse } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const upstream = await apiFetch("/api/v1/tutor/stats");
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    if (error instanceof Unauthenticated) return unauthenticatedResponse();
    return Response.json({ detail: "Could not load stats." }, { status: 502 });
  }
}
