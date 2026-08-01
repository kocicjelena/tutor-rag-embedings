"use client";

/**
 * The tool catalogue, as a model receives it.
 *
 * `ToolTrace` shows what the agent *did*. This shows what it was *offered* — and the two
 * together are the MCP flow, end to end: here is the catalogue, here is the description text
 * the model reads, and here is the call it chose to make.
 *
 * Two things make it worth a panel rather than a doc page.
 *
 * **It cannot drift.** The catalogue is fetched over a real MCP session (`GET /mcp/tools`
 * goes through `app/mcp/client.py`, not a direct function call), so if `tools/list` would
 * show a tool to Claude, it appears here with the same description and the same JSON Schema.
 * A list maintained by hand in a README is a list that is wrong within a month.
 *
 * **The descriptions are prompt text.** They are the only thing standing between a model and
 * calling `get_document` in a loop. Showing them where they can be read is the difference
 * between "the app has MCP" and being able to see why the agent behaves as it does.
 *
 * Running a tool by hand is included for the same reason: it is one button between a
 * description and the thing it actually returns.
 */

import { useCallback, useEffect, useState } from "react";

type ToolInfo = {
  name: string;
  title: string | null;
  description: string | null;
  input_schema: Record<string, unknown>;
};

type Catalogue = {
  server: string;
  instructions: string | null;
  tools: ToolInfo[];
  count: number;
};

type CallResult = {
  name: string;
  ok: boolean;
  text: string;
  duration_ms: number;
};

/** Property names and whether they are required, read off the JSON Schema a model sees. */
function argumentsOf(schema: Record<string, unknown>): [string, boolean][] {
  const properties = (schema.properties ?? {}) as Record<string, unknown>;
  const required = new Set((schema.required ?? []) as string[]);
  return Object.keys(properties).map((name) => [name, required.has(name)]);
}

function ToolRow({ tool }: { tool: ToolInfo }) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [result, setResult] = useState<CallResult | null>(null);
  const [running, setRunning] = useState(false);

  const args = argumentsOf(tool.input_schema);
  // The first string-ish argument is the one worth a text box. Tools here take a query or a
  // document id or nothing at all, so one field covers every case without building a form
  // generator for a schema that has never been more complicated than this.
  const primary = args[0]?.[0];

  const run = useCallback(async () => {
    setRunning(true);
    setResult(null);
    try {
      const response = await fetch("/api/mcp/call", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: tool.name,
          arguments: primary && input.trim() ? { [primary]: input.trim() } : {},
        }),
      });
      const body = await response.json();
      setResult(
        response.ok
          ? (body as CallResult)
          : { name: tool.name, ok: false, text: body.detail ?? "failed", duration_ms: 0 },
      );
    } catch {
      setResult({ name: tool.name, ok: false, text: "Could not reach the API.", duration_ms: 0 });
    } finally {
      setRunning(false);
    }
  }, [input, primary, tool.name]);

  return (
    <div className="trace-item">
      <div className="trace-head" onClick={() => setOpen((v) => !v)}>
        <strong className="grow">{tool.name}</strong>
        <span className="hint">
          {args.length === 0 ? "no arguments" : args.map(([n, req]) => (req ? n : `${n}?`)).join(", ")}
        </span>
        <span className="hint">{open ? "▾" : "▸"}</span>
      </div>

      {open && (
        <div className="trace-body">
          {/* The description verbatim. It is what the model reads, so it is shown as
              written rather than summarised. */}
          <p style={{ whiteSpace: "pre-wrap", margin: "0 0 10px" }}>{tool.description}</p>

          <div className="row" style={{ gap: 6 }}>
            {primary && (
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={primary}
                className="grow"
                onClick={(e) => e.stopPropagation()}
              />
            )}
            <button type="button" className="secondary" onClick={run} disabled={running}>
              {running ? "running…" : "Run it"}
            </button>
          </div>

          {result && (
            <div style={{ marginTop: 8 }}>
              <span className={`badge ${result.ok ? "ok" : "err"}`}>
                {result.ok ? "ok" : "fail"}
              </span>{" "}
              <span className="hint">{result.duration_ms}ms</span>
              <pre
                style={{
                  whiteSpace: "pre-wrap",
                  marginTop: 6,
                  maxHeight: 220,
                  overflow: "auto",
                }}
              >
                {result.text}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function McpCatalogue() {
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch("/api/mcp/tools");
        if (!response.ok) throw new Error(`Catalogue unavailable (${response.status})`);
        const body = (await response.json()) as Catalogue;
        if (!cancelled) setCatalogue(body);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not read the catalogue");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div className="panel">
        <h2>Tool catalogue</h2>
        <p className="hint">{error}</p>
      </div>
    );
  }

  if (!catalogue) {
    return (
      <div className="panel">
        <h2>Tool catalogue</h2>
        <p className="hint">Opening a session…</p>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2>Tool catalogue</h2>
      <p className="hint" style={{ marginTop: -4 }}>
        {catalogue.count} tool{catalogue.count === 1 ? "" : "s"} from{" "}
        <span className="mono">{catalogue.server}</span>, fetched over a real MCP session —
        so this is exactly what a model is handed, description text and all.
      </p>

      {catalogue.instructions && (
        <p
          className="hint"
          style={{ whiteSpace: "pre-wrap", fontSize: 12, marginTop: 10, marginBottom: 10 }}
        >
          {catalogue.instructions}
        </p>
      )}

      {catalogue.tools.map((tool) => (
        <ToolRow key={tool.name} tool={tool} />
      ))}

      <p className="hint" style={{ fontSize: 12, marginTop: 10 }}>
        No tool takes an owner. Whose material a call reads comes from your sign-in and
        nothing else — a tool&apos;s arguments are chosen by the model, so an owner parameter
        would be untrusted input rather than identity.
      </p>
    </div>
  );
}
