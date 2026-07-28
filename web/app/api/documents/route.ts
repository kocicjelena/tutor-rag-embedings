/** List and upload documents. */

import { apiFetch, Unauthenticated, unauthenticatedResponse } from "@/lib/api";

export async function GET() {
  try {
    const upstream = await apiFetch("/api/v1/documents/");
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    if (error instanceof Unauthenticated) return unauthenticatedResponse();
    return Response.json({ detail: "Could not reach the API." }, { status: 502 });
  }
}

export async function POST(request: Request) {
  try {
    // Forward the multipart body unchanged. Do NOT set Content-Type by hand —
    // the boundary parameter must be preserved from the original request.
    const formData = await request.formData();
    const upstream = await apiFetch("/api/v1/documents/upload", {
      method: "POST",
      body: formData,
    });
    const text = await upstream.text();
    return new Response(text, {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    if (error instanceof Unauthenticated) return unauthenticatedResponse();
    return Response.json({ detail: "Upload failed." }, { status: 502 });
  }
}
