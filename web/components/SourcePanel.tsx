"use client";

import { useState } from "react";
import type { SourceChunk } from "@/lib/types";

function Source({ chunk, index }: { chunk: SourceChunk; index: number }) {
  const [open, setOpen] = useState(false);
  return (
    <div
      className={`source ${open ? "open" : ""}`}
      onClick={() => setOpen((v) => !v)}
    >
      <div className="meta">
        <span className="mono">
          [{index + 1}] {chunk.document_title}
        </span>
        <span className="badge">{chunk.score.toFixed(3)}</span>
      </div>
      <div className="body">{chunk.content}</div>
    </div>
  );
}

export default function SourcePanel({ chunks }: { chunks: SourceChunk[] }) {
  return (
    <div className="panel">
      <h2>Retrieved context ({chunks.length})</h2>
      {chunks.length === 0 ? (
        <p className="empty">
          Nothing retrieved yet. Ask a question to see which chunks grounded the
          answer.
        </p>
      ) : (
        chunks.map((chunk, i) => (
          <Source key={chunk.chunk_id} chunk={chunk} index={i} />
        ))
      )}
    </div>
  );
}
