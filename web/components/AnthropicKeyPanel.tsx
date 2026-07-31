"use client";

/**
 * Bring your own Anthropic key.
 *
 * The copy here is doing real work, so it is worth saying why:
 *
 * Asking someone to paste an API key into a web form is asking for trust, and
 * most apps that do it deserve less than they get. So the panel says exactly
 * what happens to the key — hashed on the server, held for this browser
 * session only, billed to your own account — rather than a reassuring
 * adjective. Everything it claims is true of the code behind it.
 *
 * It also distinguishes two states most apps would collapse into one:
 *
 *   configured  the server has a fingerprint — a key was set at some point
 *   active      this browser session actually holds the key
 *
 * A user who closed their browser is `configured` but not `active`, and will
 * see Claude refuse to work. Saying "add it again for this session" is the
 * difference between an understandable design and an app that looks broken.
 */

import { useCallback, useEffect, useState } from "react";

interface KeyState {
  configured: boolean;
  active: boolean;
  app_key_fallback: boolean;
  key: { fingerprint: string; last_used_at: string | null } | null;
}

interface Props {
  onChanged?: () => void;
}

export default function AnthropicKeyPanel({ onChanged }: Props) {
  const [state, setState] = useState<KeyState | null>(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    const response = await fetch("/api/keys");
    if (response.ok) setState((await response.json()) as KeyState);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!value.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/keys", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: value }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { detail?: string };
        setError(body.detail ?? "That key was not accepted.");
        return;
      }
      // Clear the field the moment it is accepted — no reason for the key to
      // sit in a DOM node afterwards.
      setValue("");
      setOpen(false);
      await load();
      onChanged?.();
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await fetch("/api/keys", { method: "DELETE" });
      await load();
      onChanged?.();
    } finally {
      setBusy(false);
    }
  }

  if (!state) return null;

  const needsReentry = state.configured && !state.active;

  return (
    <div className="panel">
      <h2>Claude access</h2>

      {state.active && state.key && (
        <p className="hint" style={{ marginTop: 0 }}>
          <span className="badge ok">active</span>{" "}
          <span className="mono">{state.key.fingerprint}</span> — your Claude
          usage is billed to your own Anthropic account.
        </p>
      )}

      {needsReentry && (
        <p className="hint" style={{ marginTop: 0 }}>
          <span className="badge warn">not in this session</span> Your key was{" "}
          <span className="mono">{state.key?.fingerprint}</span>, but this app
          never stores it — so it is gone when the browser closes. Add it again
          to use Claude.
        </p>
      )}

      {!state.configured && (
        <p className="hint" style={{ marginTop: 0 }}>
          {state.app_key_fallback
            ? "Claude is available using this app's key. You can add your own instead, and be billed directly."
            : "Claude needs your own Anthropic API key. Ollama works without one."}
        </p>
      )}

      {!open && (
        <div className="row" style={{ marginTop: 10 }}>
          <button type="button" className="secondary" onClick={() => setOpen(true)}>
            {state.configured ? "Replace key" : "Add your key"}
          </button>
          {state.configured && (
            <button
              type="button"
              className="secondary"
              onClick={() => void remove()}
              disabled={busy}
            >
              Remove
            </button>
          )}
        </div>
      )}

      {open && (
        <form onSubmit={save} style={{ marginTop: 10 }}>
          <input
            type="password"
            value={value}
            placeholder="sk-ant-…"
            autoComplete="off"
            spellCheck={false}
            onChange={(e) => setValue(e.target.value)}
            disabled={busy}
          />
          <p className="hint" style={{ marginTop: 6 }}>
            Checked against Anthropic, then stored as a one-way hash plus the
            last four characters. The key itself stays in this browser session
            and is sent with each request — never written to the database.{" "}
            <a
              href="https://console.anthropic.com/settings/keys"
              target="_blank"
              rel="noreferrer"
            >
              Get a key
            </a>
            .
          </p>
          <div className="row" style={{ marginTop: 8 }}>
            <button type="submit" disabled={busy || !value.trim()}>
              {busy ? "Checking…" : "Save"}
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                setOpen(false);
                setValue("");
                setError(null);
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {error && (
        <div className="error-box" style={{ marginTop: 10 }}>
          {error}
        </div>
      )}
    </div>
  );
}
