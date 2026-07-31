/** Capability report — what works, probed rather than claimed. */

import { apiFetch, Unauthenticated, unauthenticatedResponse } from "@/lib/api";

export async function GET() {
  try {
    const upstream = await apiFetch("/api/v1/status/");
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": "application/json",
        // Every value here is measured at request time. A cached status page
        // is a status page that lies, and it lies most exactly when something
        // has just broken.
        "Cache-Control": "no-store",
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
