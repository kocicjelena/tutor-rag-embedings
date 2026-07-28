"use client";

/**
 * Ask a question and render the streamed answer.
 *
 * Consumes the typed event union from the backend: `provider` → `sources` →
 * `token`* → `done`, with `tool_call` / `tool_result` interleaved once the MCP
 * layer lands.
 */

import { useRef, useState } from "react";
import { readEventStream } from "@/lib/stream";
import type { SourceChunk, ToolRun } from "@/lib/types";

interface Props {
  provider: string;
  model: string;
  onSources: (chunks: SourceChunk[]) => void;
  onToolRuns: (runs: ToolRun[]) => void;
}

export default function ChatStream({
  provider,
  model,
  onSources,
  onToolRuns,
}: Props) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answeredBy, setAnsweredBy] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    if (!question.trim() || streaming) return;

    setStreaming(true);
    setAnswer("");
    setError(null);
    setAnsweredBy(null);
    onSources([]);
    onToolRuns([]);

    const runs: ToolRun[] = [];
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, provider, model, top_k: 5 }),
        signal: controller.signal,
      });

      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as {
          detail?: unknown;
        };
        setError(
          typeof body.detail === "string"
            ? body.detail
            : `Request failed (${response.status})`,
        );
        return;
      }

      for await (const event of readEventStream(response)) {
        switch (event.type) {
          case "provider":
            setAnsweredBy(`${event.provider} · ${event.model}`);
            break;
          case "sources":
            onSources(event.chunks);
            break;
          case "token":
            setAnswer((prev) => prev + event.text);
            break;
          case "tool_call":
            runs.push({ id: event.id, name: event.name, input: event.input });
            onToolRuns([...runs]);
            break;
          case "tool_result": {
            const run = runs.find((r) => r.id === event.id);
            if (run) {
              run.ok = event.ok;
              run.preview = event.preview;
              run.durationMs = event.duration_ms ?? null;
              onToolRuns([...runs]);
            }
            break;
          }
          case "error":
            setError(event.message);
            break;
          case "done":
            break;
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError("Stream failed — is the API running?");
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }

  return (
    <div className="panel">
      <h2>Ask your documents</h2>

      <form onSubmit={ask}>
        <textarea
          value={question}
          placeholder="What does the document say about…?"
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void ask(e);
          }}
          disabled={streaming}
        />
        <div className="row" style={{ marginTop: 10 }}>
          <button type="submit" disabled={streaming || !question.trim()}>
            {streaming ? "Answering…" : "Ask"}
          </button>
          {streaming && (
            <button
              type="button"
              className="secondary"
              onClick={() => abortRef.current?.abort()}
            >
              Stop
            </button>
          )}
          <span className="grow" />
          {answeredBy && <span className="badge ok">{answeredBy}</span>}
        </div>
        <p className="hint" style={{ marginTop: 6 }}>
          ⌘/Ctrl + Enter to send.
        </p>
      </form>

      {error && (
        <div className="error-box" style={{ marginTop: 12 }}>
          {error}
        </div>
      )}

      {(answer || streaming) && (
        <div className="answer" style={{ marginTop: 14 }}>
          {answer}
          {streaming && <span className="cursor" />}
        </div>
      )}
    </div>
  );
}
