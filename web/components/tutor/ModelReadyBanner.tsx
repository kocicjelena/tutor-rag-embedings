"use client";

import type { LearningModel, TutorStats } from "./lib/types";
import { SparkIcon } from "./Icons";

type Props = {
  learningModel: LearningModel;
  stats: TutorStats | null;
  recallUnlocked: boolean;
  showModelPanel: boolean;
  onToggleModelPanel: () => void;
};

export function ModelReadyBanner({
  learningModel,
  stats,
  recallUnlocked,
  showModelPanel,
  onToggleModelPanel,
}: Props) {
  if (!recallUnlocked) return null;

  return (
    <div className="banner">
      <div className="row">
        <SparkIcon size={17} />
        <div className="grow">
          <h3>Your model is ready</h3>
          <div className="hint">
            {stats?.interactions ?? learningModel.interactions} lessons indexed
            across {stats?.topics.length ?? 0} topics
            {stats ? ` · ${stats.indexed_chunks} searchable chunks` : ""}
          </div>
        </div>
        <button type="button" className="secondary" onClick={onToggleModelPanel}>
          {showModelPanel ? "Hide" : "Details"}
        </button>
      </div>

      {showModelPanel && (
        <div className="stat-row" style={{ marginTop: 12 }}>
          <div className="stat">
            <div className="n">{learningModel.interactions}</div>
            <div className="k">Interactions</div>
          </div>
          <div className="stat learn">
            <div className="n">{stats?.indexed_chunks ?? 0}</div>
            <div className="k">Indexed chunks</div>
          </div>
          <div className="stat">
            <div className="n">{stats?.topics.length ?? 0}</div>
            <div className="k">Topics covered</div>
          </div>
        </div>
      )}
    </div>
  );
}
