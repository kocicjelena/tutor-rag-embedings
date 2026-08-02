/**
 * Create an account, and sign the new user straight in.
 *
 * Two upstream calls behind one request, deliberately. Registering and then
 * being shown a login form to retype the password you just chose is a small
 * cruelty that every app inflicts and none needs to: the credentials are in
 * hand, so the session is issued here.
 *
 * The signing-in half is the same code path as `/api/auth` — same endpoint,
 * same cookie, same options. If sign-in has a bug, this has it too, which is
 * the right relationship between them.
 */

import {
  ANTHROPIC_KEY_COOKIE,
  API_BASE_URL,
  TOKEN_COOKIE,
  cookieOptions,
} from "@/lib/api";
import { cookies } from "next/headers";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const { email, password, fullName } = (await request.json()) as {
    email?: string;
    password?: string;
    fullName?: string;
  };

  if (!email || !password) {
    return Response.json(
      { detail: "Email and password are required." },
      { status: 400 },
    );
  }

  // 1. Create the account. Only these three fields are forwarded — the backend
  //    would ignore anything else, but there is no reason to relay it.
  const created = await fetch(`${API_BASE_URL}/api/v1/users/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email,
      password,
      full_name: fullName?.trim() || null,
    }),
    cache: "no-store",
  });

  if (!created.ok) {
    // Pass the backend's own words through where they are meant for a person —
    // "that email is already registered" is exactly what the form should say.
    let detail = "Could not create the account.";
    try {
      const body = (await created.json()) as {
        detail?: string | { msg?: string }[];
      };
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body.detail) && body.detail[0]?.msg) {
        // FastAPI validation errors arrive as a list. The first one is enough
        // for a form with two fields.
        detail = body.detail[0].msg ?? detail;
      }
    } catch {
      /* keep the default */
    }
    return Response.json({ detail }, { status: created.status });
  }

  // 2. Sign them in. A failure here is not a failed registration — the account
  //    exists — so say so precisely rather than implying nothing happened.
  const login = await fetch(`${API_BASE_URL}/api/v1/login/access-token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username: email, password }),
    cache: "no-store",
  });

  if (!login.ok) {
    return Response.json(
      { detail: "Account created, but signing in failed. Try signing in." },
      { status: 502 },
    );
  }

  const { access_token } = (await login.json()) as { access_token: string };

  const store = await cookies();
  store.set(TOKEN_COOKIE, access_token, {
    ...cookieOptions(request),
    maxAge: 60 * 60 * 24 * 8,
  });

  // Same rule as sign-in: a previous session's Anthropic key must not survive
  // into this one, or a shared machine bills a stranger's questions to them.
  store.delete(ANTHROPIC_KEY_COOKIE);

  return Response.json({ ok: true });
}
