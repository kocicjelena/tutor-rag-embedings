/**
 * Export the learner's model as JSON.
 *
 * Ported from ollama8jul/components/tutor/lib/downloadModel.ts. Now includes the
 * server-side corpus stats alongside the local dashboard, so the export reflects
 * what the model actually contains rather than only what the browser remembers.
 */

import type { LearningModel, TutorStats } from "./types";

export function downloadLearningModel(
  model: LearningModel,
  stats: TutorStats | null,
): void {
  const payload = {
    exportedAt: new Date().toISOString(),
    proficiencyLevel: model.proficiencyLevel,
    interactions: model.interactions,
    topicMastery: model.topicMastery,
    vocabularyGrowth: model.vocabularyGrowth,
    sessionHistory: model.sessionHistory,
    corpus: stats
      ? {
          indexedLessons: stats.interactions,
          indexedChunks: stats.indexed_chunks,
          topics: stats.topics,
          embeddingModel: stats.embedding_model,
        }
      : null,
  };

  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);

  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `learning-model-${Date.now()}.json`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
