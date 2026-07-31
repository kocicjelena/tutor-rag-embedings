"use client";

import type { ModelSource } from "./lib/types";
import { SendIcon, SparkIcon } from "./Icons";

type Props = {
  input: string;
  onInputChange: (value: string) => void;
  loading: boolean;
  modelSource: ModelSource;
  onModelSourceChange: (source: ModelSource) => void;
  indexedLessons: number;
  recallUnlocked: boolean;
  onSend: () => Promise<void>;
};

export function ChatComposer({
  input,
  onInputChange,
  loading,
  modelSource,
  onModelSourceChange,
  indexedLessons,
  recallUnlocked,
  onSend,
}: Props) {
  const recalling = modelSource === "recall";

  return (
    <div className="panel">
      <div className="row" style={{ marginBottom: 10 }}>
        <SparkIcon size={15} />
        <label htmlFor="source" style={{ margin: 0 }}>
          Answer from
        </label>
        <select
          id="source"
          value={modelSource}
          onChange={(e) => onModelSourceChange(e.target.value as ModelSource)}
          disabled={loading}
          style={{ width: "auto", minWidth: 240 }}
        >
          <option value="tutor">The tutor — teach me something new</option>
          <option value="recall" disabled={!recallUnlocked}>
            My model — recall from {indexedLessons} lesson
            {indexedLessons === 1 ? "" : "s"}
            {recallUnlocked ? "" : " (locked)"}
          </option>
        </select>
      </div>

      <p className="hint" style={{ marginTop: 0, marginBottom: 10 }}>
        {recalling ? (
          <>
            <span className="dot pulse" style={{ display: "inline-block", marginRight: 6 }} />
            Answering only from lessons you have already had. If it hasn&apos;t been
            covered, it will say so rather than guess.
          </>
        ) : recallUnlocked ? (
          "Each answer is indexed, so your model can recall it later."
        ) : (
          "Each answer is indexed. Your first lesson is enough to start recalling."
        )}
      </p>

      <textarea
        value={input}
        placeholder={
          recalling
            ? "Ask your own model something you've been taught…"
            : "Ask about the selected topic…"
        }
        onChange={(e) => onInputChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void onSend();
        }}
        disabled={loading}
      />

      <div className="row" style={{ marginTop: 10 }}>
        <button type="button" onClick={() => void onSend()} disabled={loading || !input.trim()}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
            <SendIcon size={14} />
            {loading ? "Thinking…" : recalling ? "Ask my model" : "Ask the tutor"}
          </span>
        </button>
        <span className="grow" />
        <span className="hint">⌘/Ctrl + Enter</span>
      </div>
    </div>
  );
}
