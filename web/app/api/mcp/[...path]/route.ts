/**
 * The MCP surface, proxied.
 *
 * One optional catch-all rather than a file per endpoint. Jelena's convention,
 * `.claude/rules/TODO.md`: *"Everything is done in API with double [[]]"* — and it earns its
 * place here specifically, because the MCP surface is a *catalogue*: the whole point is that
 * a tool registered in `app/mcp/server.py` appears without anything else being edited. A
 * proxy file per route would be the one place that still needed a hand edit.
 *
 * Two paths reach FastAPI today:
 *
 *     GET  /api/mcp/tools   →  GET  /api/v1/mcp/tools
 *     POST /api/mcp/call    →  POST /api/v1/mcp/call
 *
 * The allowlist below is deliberate and is the reason this is not a blanket forwarder. A
 * catch-all that passed anything through would let the browser reach any `/api/v1/mcp/*`
 * route this app ever grows, including ones added for a different caller — so new paths are
 * opened here on purpose, one line each, rather than by default.
 *
 * The JWT stays server-side, as everywhere: `apiFetch` reads the httpOnly cookie and attaches
 * it, and it also attaches `X-Anthropic-Key` — which is why no proxy route should ever call
 * `fetch` directly.
 */

import { apiFetch, Unauthenticated, unauthenticatedResponse } from "@/lib/api";

/** Which MCP paths the browser may reach, and with which method. */
const ALLOWED: Record<string, "GET" | "POST"> = {
  tools: "GET",
  call: "POST",
};

async function proxy(request: Request, path: string[]): Promise<Response> {
  const name = path.join("/");
  const allowedMethod = ALLOWED[name];

  if (!allowedMethod || allowedMethod !== request.method) {
    // Names what does exist, so a caller that guessed can correct itself from the
    // error alone — the same courtesy `UnknownToolError` extends to a model.
    return Response.json(
      {
        detail: `No MCP route ${request.method} /api/mcp/${name}. Available: ${Object.entries(
          ALLOWED,
        )
          .map(([p, m]) => `${m} /api/mcp/${p}`)
          .join(", ")}.`,
      },
      { status: 404 },
    );
  }

  try {
    const upstream = await apiFetch(`/api/v1/mcp/${name}`, {
      method: request.method,
      ...(request.method === "POST"
        ? {
            headers: { "Content-Type": "application/json" },
            body: await request.text(),
          }
        : {}),
    });
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

export async function GET(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  return proxy(request, (await context.params).path);
}

export async function POST(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  return proxy(request, (await context.params).path);
}
