"use client";

import { useState } from "react";
import { DownloadIcon } from "./Icons";
import type { TutorStats } from "./lib/types";

type Props = {
  stats: TutorStats | null;
};

const DEFAULT_BASE = "llama3.1:8b";

/**
 * The two things a learner can actually take away.
 *
 * The app made these embeddings out of their lessons, and a model they cannot
 * leave with is not really theirs — so both artifacts are real files, produced
 * by the server from the corpus, not by the browser from its dashboard.
 *
 *   tutor-model.json  the corpus itself: every lesson, verbatim, re-importable
 *   Modelfile         two commands from a model that answers in their material
 *
 * Both are plain `<a download>` against a route handler. No fetch, no blob, no
 * object URL: the session cookie is httpOnly and same-origin, so the browser
 * sends it on a normal navigation and the server streams the file back with
 * the filename it chose. Less code, and it cannot get the encoding wrong.
 *
 * The copy says "prompted, not fine-tuned" in as many words. A button that let
 * someone believe their lessons had been trained into weights would be the
 * kind of overclaim this project spends its status page avoiding — and they
 * would go looking for a difference that is not there.
 */
export function ModelDownloadCard({ stats }: Props) {
  const [base, setBase] = useState(DEFAULT_BASE);

  const lessons = stats?.interactions ?? 0;
  const nothingYet = lessons === 0;

  return (
    <div className="panel">
      <h2>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <DownloadIcon size={13} /> Take your model with you
        </span>
      </h2>

      {nothingYet ? (
        <p className="hint" style={{ fontSize: 12, marginTop: 4 }}>
          Take a lesson first — there is nothing to export yet.
        </p>
      ) : (
        <>
          <p className="hint" style={{ fontSize: 12, marginTop: 4, lineHeight: 1.5 }}>
            {lessons} lesson{lessons === 1 ? "" : "s"}, embedded by{" "}
            <span className="mono">{stats?.embedding_model}</span>. Yours to keep.
          </p>

          <a
            className="btn"
            href="/api/tutor/model/json"
            download
            style={{ display: "block", marginTop: 10, textAlign: "center" }}
          >
            Download the corpus (.json)
          </a>
          <p className="hint" style={{ fontSize: 11, marginTop: 4, lineHeight: 1.45 }}>
            Every lesson, verbatim, with no vectors and nothing identifying you.
            Load it back into any copy of this app.
          </p>

          <label
            className="hint"
            style={{ fontSize: 11, display: "block", marginTop: 12 }}
          >
            Base model
            <input
              type="text"
              className="mono"
              value={base}
              onChange={(event) => setBase(event.target.value)}
              spellCheck={false}
              style={{ marginTop: 4, fontSize: 12 }}
            />
          </label>

          <a
            className="btn"
            href={`/api/tutor/model/modelfile?base_model=${encodeURIComponent(
              base.trim() || DEFAULT_BASE,
            )}`}
            download="Modelfile"
            style={{ display: "block", marginTop: 8, textAlign: "center" }}
          >
            Download a Modelfile
          </a>
          <p className="hint" style={{ fontSize: 11, marginTop: 4, lineHeight: 1.45 }}>
            Then, on any machine with Ollama:
          </p>
          <pre
            className="mono"
            style={{
              fontSize: 11,
              marginTop: 4,
              padding: "6px 8px",
              overflowX: "auto",
              whiteSpace: "pre",
            }}
          >
            {`ollama create my-model -f Modelfile\nollama run my-model`}
          </pre>
          <p className="hint" style={{ fontSize: 11, marginTop: 4, lineHeight: 1.45 }}>
            Your lessons ride in the base model&rsquo;s context — a{" "}
            <strong>prompted</strong> model, not a fine-tuned one. Seconds, and no
            GPU. The base model is resolved on your machine, not downloaded here.
          </p>
        </>
      )}
    </div>
  );
}
