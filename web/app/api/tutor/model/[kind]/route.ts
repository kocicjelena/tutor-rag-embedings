/**
 * Download the learner's model — the two things they can actually keep.
 *
 *   /api/tutor/model/json       tutor-model.json, the corpus (tier 1)
 *   /api/tutor/model/modelfile  Modelfile, runnable in Ollama (tier 2)
 *
 * One handler with an explicit two-entry allowlist rather than a path
 * passthrough, for the same reason `/api/mcp` has one: a proxy that forwards
 * whatever arrives opens every route this app ever grows under that prefix,
 * including ones added later for a different caller.
 *
 * The body is passed through as text and the upstream `Content-Disposition` is
 * kept, so the browser saves a file with the name FastAPI chose. Nothing is
 * parsed here — a Modelfile is not JSON, and re-encoding a download is how a
 * trailing newline goes missing and `ollama create` complains about a file
 * this app generated.
 */

import { apiFetch, Unauthenticated, unauthenticatedResponse } from "@/lib/api";

export const dynamic = "force-dynamic";

const ARTIFACTS = {
  json: {
    path: "/api/v1/tutor/model/export",
    filename: "tutor-model.json",
    contentType: "application/json",
  },
  modelfile: {
    path: "/api/v1/tutor/model/modelfile",
    filename: "Modelfile",
    contentType: "text/plain; charset=utf-8",
  },
} as const;

type Kind = keyof typeof ARTIFACTS;

function isKind(value: string): value is Kind {
  return Object.hasOwn(ARTIFACTS, value);
}

export async function GET(
  request: Request,
  context: { params: Promise<{ kind: string }> },
) {
  const { kind } = await context.params;
  if (!isKind(kind)) {
    return Response.json(
      { detail: `Unknown model artifact "${kind}".` },
      { status: 404 },
    );
  }
  const artifact = ARTIFACTS[kind];

  // The base model is the learner's choice — it is resolved by `ollama create`
  // on their machine, not here, so this app never has to hold it.
  const base = new URL(request.url).searchParams.get("base_model");
  const path =
    kind === "modelfile" && base
      ? `${artifact.path}?base_model=${encodeURIComponent(base)}`
      : artifact.path;

  try {
    const upstream = await apiFetch(path);
    if (!upstream.ok) {
      return Response.json(
        { detail: "Could not build the download." },
        { status: upstream.status },
      );
    }
    return new Response(await upstream.text(), {
      status: 200,
      headers: {
        "Content-Type": artifact.contentType,
        "Content-Disposition":
          upstream.headers.get("content-disposition") ??
          `attachment; filename="${artifact.filename}"`,
        "Cache-Control": "no-store",
      },
    });
  } catch (error) {
    if (error instanceof Unauthenticated) return unauthenticatedResponse();
    return Response.json(
      { detail: "Could not reach the API." },
      { status: 502 },
    );
  }
}
