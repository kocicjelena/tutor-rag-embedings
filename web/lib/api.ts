/**
 * Server-side helpers for talking to FastAPI.
 *
 * The access token lives in an httpOnly cookie and is attached here, in route
 * handlers. It is never sent to the browser, so client components cannot leak
 * it and XSS cannot read it.
 */

import { cookies } from "next/headers";

export const API_BASE_URL = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

export const TOKEN_COOKIE = "rag_token";

export async function getToken(): Promise<string | null> {
  const store = await cookies();
  return store.get(TOKEN_COOKIE)?.value ?? null;
}

export class Unauthenticated extends Error {
  constructor() {
    super("Not signed in");
  }
}

/** Fetch from FastAPI with the caller's bearer token attached. */
export async function apiFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = await getToken();
  if (!token) throw new Unauthenticated();

  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);

  return fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
}

/** Map a thrown Unauthenticated into a 401 JSON response. */
export function unauthenticatedResponse(): Response {
  return Response.json({ detail: "Not signed in" }, { status: 401 });
}
