"use client";

/**
 * The model being built, while it is being built.
 *
 * This is the first visible consumer of the `model` slice, and it is the point of the whole
 * channel: until now the pieces travelled up, landed in SQLite and came back into the store,
 * and nothing on screen said so. A pipeline nobody can watch is indistinguishable from one
 * that is not running.
 *
 * Everything here is **mirrored, never counted**. `state` is what SQLite answered on the last
 * push, returned whole rather than as a delta — so a browser that missed a response recovers
 * from the next one instead of drifting. The two numbers that are the browser's own
 * (`queued`, `inFlight`) are labelled as the pipeline's, not the model's, because they
 * describe the wire rather than what is stored.
 *
 * `novelty` is worth reading before it is dismissed as decoration: it is the distance from a
 * piece to the nearest thing the learner already had. Near zero means "you have been told this
 * before". It is the one number here that says something about the *learning* rather than
 * about the plumbing.
 */

import type { ModelType } from "@/types/interfaces/ModelType";
import { SparkIcon } from "./Icons";

type Props = { model: ModelType };

/** Distance → a word. Thresholds are honest guesses and labelled as such in the title. */
function noveltyLabel(distance: number | null): string {
  if (distance === null) return "first";
  if (distance < 0.15) return "familiar";
  if (distance < 0.45) return "related";
  return "new";
}

export function LiveModelCard({ model }: Props) {
  const { state, queued, inFlight, recent, status, error } = model;

  // Nothing has ever been pushed and nothing is queued: say nothing rather than showing an
  // empty frame that looks broken.
  if (!state && queued.length === 0 && inFlight === 0 && !error) return null;

  const mean = state?.mean_novelty;

  return (
    <div className="panel">
      <h2>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <SparkIcon size={13} /> Model, as it is built
        </span>
      </h2>

      <p className="hint" style={{ marginTop: -4, marginBottom: 10 }}>
        Pieces are embedded as they arrive, not after the answer finishes.
      </p>

      <div className="row" style={{ justifyContent: "space-between", fontSize: 13 }}>
        <span className="hint">Pieces stored</span>
        <span className="mono">{state?.events ?? 0}</span>
      </div>
      <div className="row" style={{ justifyContent: "space-between", fontSize: 13, marginTop: 6 }}>
        <span className="hint" title="Across every session, not only this one">
          Vectors in the model
        </span>
        <span className="mono">{state?.vectors ?? 0}</span>
      </div>
      {mean !== null && mean !== undefined && (
        <div className="row" style={{ justifyContent: "space-between", fontSize: 13, marginTop: 6 }}>
          <span
            className="hint"
            title="Mean distance from each piece to the nearest thing you already had. Higher means more of this was new to you."
          >
            How new this was
          </span>
          <span className="mono">{mean.toFixed(3)}</span>
        </div>
      )}
      <div className="row" style={{ justifyContent: "space-between", fontSize: 13, marginTop: 6 }}>
        <span className="hint">Embedded with</span>
        <span className="mono">{state?.embedded_with ?? "—"}</span>
      </div>

      {(inFlight > 0 || queued.length > 0) && (
        <div
          className="row"
          style={{ justifyContent: "space-between", fontSize: 12, marginTop: 10 }}
        >
          <span className="hint">
            {/* The backpressure, made visible. One request is in flight and the rest wait —
                which is what makes this a coroutine rather than a flood of small posts. */}
            {inFlight > 0 ? `${inFlight} on the wire` : "idle"}
          </span>
          <span className="badge">
            {queued.length > 0 ? `${queued.length} queued` : "queue empty"}
          </span>
        </div>
      )}

      {error && (
        <p className="hint" style={{ marginTop: 10, color: "var(--danger, #c0392b)" }}>
          {error} — the pieces are kept and go up with the next answer.
        </p>
      )}

      {recent.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <span className="hint" style={{ fontSize: 12 }}>
            Last pieces in
          </span>
          <ul style={{ listStyle: "none", padding: 0, margin: "6px 0 0" }}>
            {recent.slice(-4).map((event) => (
              <li
                key={event.seq}
                style={{
                  display: "flex",
                  gap: 8,
                  alignItems: "baseline",
                  fontSize: 12,
                  marginTop: 4,
                }}
              >
                <span className="badge" style={{ flexShrink: 0 }}>
                  {noveltyLabel(event.novelty)}
                </span>
                <span
                  className="hint"
                  style={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {event.text}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {status === "synced" && (
        <p className="hint" style={{ marginTop: 10, fontSize: 12 }}>
          Read back from the database, not counted here — so this cannot drift.
        </p>
      )}
    </div>
  );
}
