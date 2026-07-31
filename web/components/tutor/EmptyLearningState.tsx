"use client";

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
          // Nothing indexed. Not a countdown — there is exactly one thing to
          // do, and a progress bar at 0% only makes it look further away.
          <p className="hint">
            Nothing indexed yet, so there is nothing to recall. Ask the tutor
            anything — your first lesson becomes your model.
          </p>
        )}
      </div>
    </div>
  );
}
