/**
 * What the sign-in page needs before anyone has signed in.
 *
 * Unauthenticated on purpose and by necessity — nobody has a token yet. It
 * goes straight to FastAPI rather than through `apiFetch`, because `apiFetch`
 * exists to attach a token and there is none to attach.
 *
 * Whatever the backend chooses to publish is passed through unchanged. The
 * decision about whether a demo password is included lives there, in one
 * place, behind two settings that both have to be true.
 */

import { API_BASE_URL } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const upstream = await fetch(`${API_BASE_URL}/api/v1/public/signin-info`, {
      cache: "no-store",
    });
    if (!upstream.ok) {
      // Not fatal: the sign-in form still works without this. It just cannot
      // offer a demo account or say whether registration is open.
      return Response.json({}, { status: 200 });
    }
    return new Response(await upstream.text(), {
      status: 200,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({}, { status: 200 });
  }
}
