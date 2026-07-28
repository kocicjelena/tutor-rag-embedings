"use client";

/**
 * Agent / tool execution display.
 *
 * Milestone 1 emits no tool events, so this renders its empty state and
 * explains why. Milestone 2 (MCP) starts producing `tool_call` / `tool_result`
 * frames and this panel lights up with no changes here.
 */

import { useState } from "react";
import type { ToolRun } from "@/lib/types";

function TraceRow({ run }: { run: ToolRun }) {
  const [open, setOpen] = useState(false);
  const pending = run.ok === undefined;

  return (
    <div className="trace-item">
      <div className="trace-head" onClick={() => setOpen((v) => !v)}>
        {pending ? (
          <span className="spinner" aria-label="running" />
        ) : (
          <span className={`badge ${run.ok ? "ok" : "err"}`}>
            {run.ok ? "ok" : "fail"}
          </span>
        )}
        <strong className="grow">{run.name}</strong>
        {run.durationMs != null && (
          <span className="hint">{run.durationMs}ms</span>
        )}
        <span className="hint">{open ? "▾" : "▸"}</span>
      </div>
      {open && (
        <div className="trace-body">
          <div style={{ marginBottom: 6 }}>
            <span className="hint">input</span>
            {"\n"}
            {JSON.stringify(run.input, null, 2)}
          </div>
          {run.preview !== undefined && (
            <div>
              <span className="hint">result</span>
              {"\n"}
              {run.preview}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ToolTrace({ runs }: { runs: ToolRun[] }) {
  return (
    <div className="panel">
      <h2>Tool execution</h2>
      {runs.length === 0 ? (
        <p className="empty">
          No tools invoked. Tool calling arrives with the MCP layer in Milestone
          2 — this panel is already wired to the event stream.
        </p>
      ) : (
        runs.map((run) => <TraceRow key={run.id} run={run} />)
      )}
    </div>
  );
}
