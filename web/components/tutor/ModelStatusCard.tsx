"use client";

import type { TutorStats } from "./lib/types";
import { DownloadIcon, SparkIcon } from "./Icons";

type Props = {
  stats: TutorStats | null;
  recallUnlocked: boolean;
  onDownloadModel: () => void;
};

export function ModelStatusCard({ stats, recallUnlocked, onDownloadModel }: Props) {
  if (!recallUnlocked || !stats) return null;

  const shown = stats.topics.slice(0, 3).join(", ");
  const rest = Math.max(0, stats.topics.length - 3);

  return (
    <div className="panel">
      <h2>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <SparkIcon size={13} /> Your trained model
        </span>
      </h2>

      <div className="row" style={{ justifyContent: "space-between", fontSize: 13 }}>
        <span className="hint">Status</span>
        <span className="badge ok">
          <span className="dot pulse" /> active
        </span>
      </div>
      <div className="row" style={{ justifyContent: "space-between", fontSize: 13, marginTop: 6 }}>
        <span className="hint">Lessons</span>
        <span className="mono">{stats.interactions}</span>
      </div>
      <div className="row" style={{ justifyContent: "space-between", fontSize: 13, marginTop: 6 }}>
        <span className="hint">Searchable chunks</span>
        <span className="mono">{stats.indexed_chunks}</span>
      </div>
      <div className="row" style={{ justifyContent: "space-between", fontSize: 13, marginTop: 6 }}>
        <span className="hint">Embedding</span>
        <span className="mono">{stats.embedding_model}</span>
      </div>

      {stats.topics.length > 0 && (
        <p className="hint" style={{ marginTop: 10 }}>
          Can answer about {shown}
          {rest > 0 ? ` and ${rest} more` : ""}.
        </p>
      )}

      <button
        type="button"
        className="secondary"
        onClick={onDownloadModel}
        style={{ width: "100%", marginTop: 10, display: "inline-flex",
                 alignItems: "center", justifyContent: "center", gap: 7 }}
      >
        <DownloadIcon size={14} />
        Export model
      </button>
    </div>
  );
}
