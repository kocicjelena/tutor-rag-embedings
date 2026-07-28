"use client";

import { useState } from "react";

export default function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [email, setEmail] = useState("admin@example.com");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (response.ok) {
        onSignedIn();
      } else {
        setError("Incorrect email or password.");
      }
    } catch {
      setError("Could not reach the API. Is FastAPI running on :8000?");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel" style={{ maxWidth: 420, margin: "40px auto" }}>
      <h2>Sign in</h2>
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
          />
        </div>
        <div style={{ marginBottom: 16 }}>
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </div>
        <button type="submit" disabled={busy || !password}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <p className="hint" style={{ marginTop: 14 }}>
        Use the credentials from <span className="mono">FIRST_SUPERUSER</span> /{" "}
        <span className="mono">FIRST_SUPERUSER_PASSWORD</span> in the backend&apos;s{" "}
        <span className="mono">.env</span>. There is no public signup — accounts
        are created by a superuser.
      </p>
    </div>
  );
}
