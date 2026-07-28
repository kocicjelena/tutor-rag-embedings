"use client";

import { getTopicLabel } from "./lib/terms";
import type { LearningModel } from "./lib/types";
import { BarsIcon } from "./Icons";

export function TopicMasteryCard({
  learningModel,
}: {
  learningModel: LearningModel;
}) {
  const entries = Object.entries(learningModel.topicMastery);

  return (
    <div className="panel">
      <h2>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <BarsIcon size={13} /> Topic mastery
        </span>
      </h2>

      {entries.length === 0 ? (
        <p className="empty">No topics yet.</p>
      ) : (
        entries.map(([topic, mastery]) => (
          <div key={topic} style={{ marginBottom: 9 }}>
            <div className="meter-label">
              <span>{getTopicLabel(topic)}</span>
              <span className="mono">{Math.round(mastery * 100)}%</span>
            </div>
            <div className="meter">
              <i style={{ width: `${mastery * 100}%` }} />
            </div>
          </div>
        ))
      )}
    </div>
  );
}
