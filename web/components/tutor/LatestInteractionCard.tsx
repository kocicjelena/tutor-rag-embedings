"use client";

import type { InteractionFeedback } from "./lib/types";

export function LatestInteractionCard({
  feedback,
}: {
  feedback: InteractionFeedback | null;
}) {
  if (!feedback) return null;

  return (
    <div className="panel">
      <h2>Latest interaction</h2>
      <div className="row" style={{ justifyContent: "space-between", fontSize: 13 }}>
        <span className="hint">Terms used</span>
        <span>{feedback.termsUsed.join(", ") || "none detected"}</span>
      </div>
      <div
        className="row"
        style={{ justifyContent: "space-between", fontSize: 13, marginTop: 6 }}
      >
        <span className="hint">Complexity</span>
        <span className="badge">{feedback.complexity}</span>
      </div>
    </div>
  );
}
