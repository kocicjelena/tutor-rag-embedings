"use client";

import type { LearningModel, TutorStats } from "./lib/types";

type Props = {
  learningModel: LearningModel;
  stats: TutorStats | null;
  indexedLessons: number;
  recallUnlocked: boolean;
};

export function TrainingProgressCard({
  learningModel,
  stats,
  indexedLessons,
  recallUnlocked,
}: Props) {
  return (
    <div className="panel">
      <h2>Progress</h2>

      <div style={{ marginBottom: 12 }}>
        <div className="meter-label">
          <span className="hint">Interactions</span>
          <span className="mono">{learningModel.interactions}</span>
        </div>
        <div className="meter">
          <i style={{ width: `${Math.min(100, (learningModel.interactions / 20) * 100)}%` }} />
        </div>
      </div>

      <div style={{ marginBottom: 12 }}>
        <div className="meter-label">
          <span className="hint">Lessons indexed</span>
          <span className="mono">{indexedLessons}</span>
        </div>
        <div className="meter learn">
          <i style={{ width: `${Math.min(100, (indexedLessons / 15) * 100)}%` }} />
        </div>
      </div>

      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="hint">Topics covered</span>
        <span className="mono" style={{ fontSize: 17 }}>
          {stats?.topics.length ?? Object.keys(learningModel.topicMastery).length}
        </span>
      </div>

      {!recallUnlocked && (
        <p className="hint" style={{ marginTop: 10 }}>
          One lesson is enough to start recalling.
        </p>
      )}
    </div>
  );
}
