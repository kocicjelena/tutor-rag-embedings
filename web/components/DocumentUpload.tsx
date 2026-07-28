"use client";

import { useEffect, useRef, useState } from "react";
import type { DocumentInfo } from "@/lib/types";

const STATUS_CLASS: Record<DocumentInfo["status"], string> = {
  ready: "ok",
  processing: "warn",
  pending: "warn",
  error: "err",
};

export default function DocumentUpload({ signedIn }: { signedIn: boolean }) {
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  async function refresh() {
    if (!signedIn) return;
    try {
      const response = await fetch("/api/documents");
      if (!response.ok) return;
      const body = (await response.json()) as { data: DocumentInfo[] };
      setDocs(body.data);
    } catch {
      /* transient — the poll will retry */
    }
  }

  useEffect(() => {
    void refresh();
    // Ingestion is a background task, so poll while anything is unfinished.
    const timer = setInterval(() => {
      setDocs((current) => {
        if (current.some((d) => d.status === "pending" || d.status === "processing")) {
          void refresh();
        }
        return current;
      });
    }, 2000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signedIn]);

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await fetch("/api/documents", { method: "POST", body: form });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
        setError(
          typeof body.detail === "string" ? body.detail : `Upload failed (${response.status})`,
        );
      } else {
        await refresh();
      }
    } catch {
      setError("Upload failed — is the API running?");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div className="panel">
      <h2>Documents</h2>

      {error && <div className="error-box">{error}</div>}

      <input
        ref={inputRef}
        type="file"
        accept=".txt,.md,.csv,.pdf,text/plain,text/markdown,text/csv,application/pdf"
        disabled={busy || !signedIn}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void upload(file);
        }}
        style={{ fontSize: 13, marginBottom: 12 }}
      />

      {docs.length === 0 ? (
        <p className="empty">No documents yet. Upload a .txt, .md, .csv or .pdf.</p>
      ) : (
        docs.map((doc) => (
          <div className="doc" key={doc.id}>
            <span className="grow" title={doc.error_message ?? undefined}>
              {doc.title}
            </span>
            <span className={`badge ${STATUS_CLASS[doc.status]}`}>
              {doc.status === "ready" ? `${doc.chunk_count} chunks` : doc.status}
            </span>
          </div>
        ))
      )}

      {docs.some((d) => d.status === "error") && (
        <p className="hint" style={{ marginTop: 8 }}>
          Hover a failed document for the reason.
        </p>
      )}
    </div>
  );
}
