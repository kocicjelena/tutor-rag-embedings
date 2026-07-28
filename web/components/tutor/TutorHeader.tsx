"use client";

import Link from "next/link";
import { AI_TERMS } from "./lib/constants";
import { getProficiencyClassName } from "./lib/modelAnalysis";
import type { LearningModel, TutorMode } from "./lib/types";
import { BrainIcon, DownloadIcon } from "./Icons";

type Props = {
  selectedTerm: string;
  onSelectedTermChange: (termId: string) => void;
  mode: TutorMode;
  onModeChange: (mode: TutorMode) => void;
  learningModel: LearningModel;
  indexedLessons: number;
  onDownloadModel: () => void;
};

export function TutorHeader({
  selectedTerm,
  onSelectedTermChange,
  mode,
  onModeChange,
  learningModel,
  indexedLessons,
  onDownloadModel,
}: Props) {
  return (
    <header className="masthead">
      <div>
        <h1 style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <BrainIcon size={19} />
          AI Learning Tutor
        </h1>
        <div className="sub">
          Claude teaches · your lessons are indexed · your model recalls them
        </div>
      </div>

      <nav className="tutor-nav">
        <Link href="/">Documents</Link>
        <Link href="/tutor" className="active">
          Tutor
        </Link>
      </nav>

      <div className="row">
        <select
          value={selectedTerm}
          onChange={(e) => onSelectedTermChange(e.target.value)}
          style={{ width: "auto", minWidth: 190 }}
          aria-label="Topic"
        >
          {AI_TERMS.map((term) => (
            <option key={term.id} value={term.id}>
              {term.label}
            </option>
          ))}
        </select>

        <div className="seg" role="group" aria-label="Teaching style">
          <button
            type="button"
            className={mode === "casual" ? "on" : ""}
            onClick={() => onModeChange("casual")}
          >
            Casual
          </button>
          <button
            type="button"
            className={mode === "structured" ? "on" : ""}
            onClick={() => onModeChange("structured")}
          >
            Structured
          </button>
        </div>

        <span className={getProficiencyClassName(learningModel.proficiencyLevel)}>
          {learningModel.proficiencyLevel}
        </span>

        {indexedLessons > 0 && (
          <button
            type="button"
            className="secondary"
            onClick={onDownloadModel}
            title="Export your learning model as JSON"
            style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
          >
            <DownloadIcon size={14} />
            Export
          </button>
        )}
      </div>
    </header>
  );
}
