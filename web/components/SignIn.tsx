"use client";

import { useState } from "react";
import { useContextActions } from "@/context/GlobalContext";

/**
 * Sign in, or create an account.
 *
 * Two modes in one component rather than two pages. They share the same two
 * fields, the same error slot and the same "you are now signed in" ending, and
 * splitting them would mean maintaining that twice for the sake of a route.
 *
 * `onSignedIn` used to be a prop, threaded down so the page could re-check the
 * session. That callback existed only because the answer lived in the page's
 * own `useState`; the store holds it now, so this component tells the store
 * directly and no parent has to remember to pass anything.
 */

type Mode = "signin" | "register";

export default function SignIn() {
  const { checkSession } = useContextActions();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const registering = mode === "register";

  function switchTo(next: Mode) {
    setMode(next);
    setError(null);
    // The password is cleared and the email is not, deliberately. Someone who
    // mistyped a password and switched tabs should not have to retype their
    // address; someone whose password was rejected should not carry it into a
    // registration they did not mean to make.
    setPassword("");
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(registering ? "/api/register" : "/api/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          registering ? { email, password, fullName } : { email, password },
        ),
      });

      if (response.ok) {
        // Both routes end the same way: a session cookie is set, so the store
        // only needs to look again.
        await checkSession();
        return;
      }

      if (registering) {
        // The backend's message is written for a person — "that email is
        // already registered. Try signing in." — so it is shown as-is.
        const body = (await response.json().catch(() => ({}))) as {
          detail?: string;
        };
        setError(body.detail ?? "Could not create the account.");
      } else {
        // Sign-in stays vague on purpose. Registration already reveals whether
        // an address is taken; login should not confirm it a second time to
        // someone working through a list of passwords.
        setError("Incorrect email or password.");
      }
    } catch {
      setError("Could not reach the API. Is FastAPI running on :8000?");
    } finally {
      setBusy(false);
    }
  }

  const tabStyle = (active: boolean): React.CSSProperties => ({
    flex: 1,
    padding: "8px 0",
    background: "transparent",
    color: active ? "var(--text)" : "var(--muted)",
    border: 0,
    borderBottom: `2px solid ${active ? "var(--accent)" : "var(--border)"}`,
    borderRadius: 0,
    fontWeight: active ? 600 : 400,
    cursor: "pointer",
  });

  return (
    <div className="panel" style={{ maxWidth: 420, margin: "40px auto" }}>
      <div style={{ display: "flex", marginBottom: 18 }}>
        <button
          type="button"
          style={tabStyle(!registering)}
          onClick={() => switchTo("signin")}
        >
          Sign in
        </button>
        <button
          type="button"
          style={tabStyle(registering)}
          onClick={() => switchTo("register")}
        >
          Create account
        </button>
      </div>

      {error && <div className="error-box">{error}</div>}

      <form onSubmit={submit}>
        <div style={{ marginBottom: 12 }}>
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
            required
          />
        </div>

        {registering && (
          <div style={{ marginBottom: 12 }}>
            <label htmlFor="fullName">Name (optional)</label>
            <input
              id="fullName"
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              autoComplete="name"
            />
          </div>
        )}

        <div style={{ marginBottom: 16 }}>
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            /* A browser that offers to save the password it just helped choose
               is worth the one-line difference. */
            autoComplete={registering ? "new-password" : "current-password"}
            minLength={registering ? 8 : undefined}
            required
          />
          {registering && (
            <p className="hint" style={{ fontSize: 11, marginTop: 4 }}>
              At least 8 characters.
            </p>
          )}
        </div>

        <button
          type="submit"
          disabled={busy || !password || (registering && password.length < 8)}
        >
          {busy
            ? registering
              ? "Creating…"
              : "Signing in…"
            : registering
              ? "Create account"
              : "Sign in"}
        </button>
      </form>

      <p className="hint" style={{ marginTop: 14, lineHeight: 1.5 }}>
        {registering ? (
          <>
            Your account is yours: the lessons you take, the documents you
            upload and the model you build are scoped to you — and you can
            download the whole thing whenever you like.
          </>
        ) : (
          <>
            No account yet? <strong>Create account</strong> above. The
            administrator account comes from{" "}
            <span className="mono">FIRST_SUPERUSER</span> in the backend&apos;s{" "}
            <span className="mono">.env</span>.
          </>
        )}
      </p>
    </div>
  );
}
