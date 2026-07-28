"use client";

import type { ChangeEvent, KeyboardEvent } from "react";
import { TargetIcon } from "./Icons";

type Props = {
  goals: string[];
  newGoal: string;
  onNewGoalChange: (goal: string) => void;
  onAddGoal: () => void;
  onRemoveGoal: (index: number) => void;
};

export function LearningGoalsCard({
  goals,
  newGoal,
  onNewGoalChange,
  onAddGoal,
  onRemoveGoal,
}: Props) {
  return (
    <div className="panel">
      <h2>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <TargetIcon size={13} /> Learning goals
        </span>
      </h2>

      {goals.map((goal, index) => (
        <div className="goal" key={`${goal}-${index}`}>
          <span className="grow">{goal}</span>
          <button
            type="button"
            onClick={() => onRemoveGoal(index)}
            aria-label={`Remove goal: ${goal}`}
            title="Remove"
          >
            ×
          </button>
        </div>
      ))}

      <div className="row" style={{ marginTop: 8 }}>
        <input
          type="text"
          value={newGoal}
          placeholder="Add a goal…"
          onChange={(e: ChangeEvent<HTMLInputElement>) =>
            onNewGoalChange(e.target.value)
          }
          onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
            if (e.key === "Enter") onAddGoal();
          }}
          className="grow"
        />
        <button type="button" className="secondary" onClick={onAddGoal}>
          Add
        </button>
      </div>

      <p className="hint" style={{ marginTop: 8 }}>
        Goals are passed to the tutor so explanations aim at them.
      </p>
    </div>
  );
}
