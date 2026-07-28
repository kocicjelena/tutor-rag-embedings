/** Provider + model inventory for the picker. */

import { apiFetch, Unauthenticated, unauthenticatedResponse } from "@/lib/api";

export async function GET() {
  try {
    const upstream = await apiFetch("/api/v1/providers/");
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    if (error instanceof Unauthenticated) return unauthenticatedResponse();
    return Response.json(
      { detail: "Could not reach the API. Is FastAPI running?" },
      { status: 502 },
    );
  }
}
