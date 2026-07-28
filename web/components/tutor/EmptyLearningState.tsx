"use client";

import { RECALL_UNLOCK_INTERACTIONS } from "./lib/constants";
import { findTermById } from "./lib/terms";
import type { LearningModel } from "./lib/types";
import { BookIcon, SparkIcon } from "./Icons";

type Props = {
  selectedTerm: string;
  learningModel: LearningModel;
  indexedLessons: number;
  recallUnlocked: boolean;
};

export function EmptyLearningState({
  selectedTerm,
  learningModel,
  indexedLessons,
  recallUnlocked,
}: Props) {
  const term = findTermById(selectedTerm);
  const progress = Math.min(
    100,
    (indexedLessons / RECALL_UNLOCK_INTERACTIONS) * 100,
  );

  return (
    <div style={{ textAlign: "center", padding: "26px 8px" }}>
      <BookIcon size={30} />
      <h2 style={{ fontSize: 17, margin: "10px 0 4px" }}>
        Start learning {term.label}
      </h2>
      <p className="hint" style={{ marginTop: 0 }}>
        {term.desc}
      </p>

      <div className="stat-row" style={{ maxWidth: 420, margin: "20px auto 0" }}>
        <div className="stat">
          <div className="n">{learningModel.interactions}</div>
          <div className="k">Interactions</div>
        </div>
        <div className="stat learn">
          <div className="n">{indexedLessons}</div>
          <div className="k">Lessons indexed</div>
        </div>
        <div className="stat">
          <div className="n">
            {Object.keys(learningModel.topicMastery).length}
          </div>
          <div className="k">Topics</div>
        </div>
      </div>

      <div style={{ maxWidth: 420, margin: "16px auto 0", textAlign: "left" }}>
        {recallUnlocked ? (
          <p className="hint">
            <SparkIcon size={13} /> Your model is ready — switch{" "}
            <strong>Answer from</strong> to <em>My model</em> below to ask it
            directly.
          </p>
        ) : (
          <>
            <div className="meter learn">
              <i style={{ width: `${progress}%` }} />
            </div>
            <p className="hint" style={{ marginTop: 6 }}>
              {indexedLessons}/{RECALL_UNLOCK_INTERACTIONS} lessons before recall
              unlocks. Ask the tutor anything to begin.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
