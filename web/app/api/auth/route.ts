/**
 * Sign in / sign out.
 *
 * Exchanges credentials for a JWT and stores it in an httpOnly cookie. The
 * token is never returned to the browser.
 */

import { API_BASE_URL, TOKEN_COOKIE } from "@/lib/api";
import { cookies } from "next/headers";

export async function POST(request: Request) {
  const { email, password } = (await request.json()) as {
    email?: string;
    password?: string;
  };

  if (!email || !password) {
    return Response.json({ detail: "Email and password are required" }, { status: 400 });
  }

  // FastAPI's OAuth2 password flow expects form encoding, with the email as
  // `username`.
  const body = new URLSearchParams({ username: email, password });
  const upstream = await fetch(`${API_BASE_URL}/api/v1/login/access-token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
    cache: "no-store",
  });

  if (!upstream.ok) {
    const detail = await upstream.text();
    return Response.json(
      { detail: detail || "Sign-in failed" },
      { status: upstream.status },
    );
  }

  const { access_token } = (await upstream.json()) as { access_token: string };

  // Derive `secure` from the actual request protocol, not from NODE_ENV.
  // Keying it to NODE_ENV means a local `npm run build && npm run start` sets
  // Secure on an http://localhost cookie, the browser never sends it back, and
  // sign-in appears to succeed while every subsequent request 401s.
  const forwardedProto = request.headers.get("x-forwarded-proto");
  const isHttps =
    forwardedProto === "https" || new URL(request.url).protocol === "https:";

  const store = await cookies();
  store.set(TOKEN_COOKIE, access_token, {
    httpOnly: true,
    sameSite: "lax",
    secure: isHttps,
    path: "/",
    maxAge: 60 * 60 * 24 * 8, // matches ACCESS_TOKEN_EXPIRE_MINUTES
  });

  return Response.json({ ok: true });
}

export async function DELETE() {
  const store = await cookies();
  store.delete(TOKEN_COOKIE);
  return Response.json({ ok: true });
}

export async function GET() {
  const store = await cookies();
  return Response.json({ signedIn: store.has(TOKEN_COOKIE) });
}
