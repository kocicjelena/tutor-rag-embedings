/**
 * Local persistence for the learner's *dashboard* only.
 *
 * Ported from ollama8jul/components/tutor/lib/storage.ts, with the artifact
 * `window.storage` fallback removed — that existed for the Claude-artifact
 * sandbox and has no meaning here.
 *
 * Note what this no longer carries the weight of. In the source, `sessionHistory`
 * in localStorage *was* the trained model — recall searched it directly. Here the
 * corpus lives server-side in sqlite-vec, so this is just the progress panel:
 * counts, mastery, and the growth chart. Losing it costs you the dashboard, not
 * the model.
 */

import { DEFAULT_LEARNING_MODEL, LEARNING_MODEL_STORAGE_KEY } from "./constants";
import { analyzeProficiency } from "./modelAnalysis";
import type {
  LearningModel,
  SessionHistoryItem,
  VocabularyGrowthPoint,
} from "./types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function toVocabularyGrowth(value: unknown): VocabularyGrowthPoint[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord).map((item) => ({
    session: typeof item.session === "number" ? item.session : 0,
    terms: typeof item.terms === "number" ? item.terms : 0,
  }));
}

function toTopicMastery(value: unknown): Record<string, number> {
  if (!isRecord(value)) return {};
  return Object.entries(value).reduce<Record<string, number>>(
    (mastery, [key, score]) => {
      if (typeof score === "number") mastery[key] = score;
      return mastery;
    },
    {},
  );
}

function toSessionHistory(value: unknown): SessionHistoryItem[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord).map((item) => ({
    term: typeof item.term === "string" ? item.term : "",
    timestamp: typeof item.timestamp === "number" ? item.timestamp : Date.now(),
    userMsg: typeof item.userMsg === "string" ? item.userMsg : "",
    aiResponse: typeof item.aiResponse === "string" ? item.aiResponse : "",
  }));
}

function normalize(value: unknown): LearningModel | null {
  if (!isRecord(value)) return null;

  const interactions =
    typeof value.interactions === "number"
      ? value.interactions
      : DEFAULT_LEARNING_MODEL.interactions;
  const topicMastery = toTopicMastery(value.topicMastery);

  return {
    interactions,
    proficiencyLevel: analyzeProficiency(interactions, topicMastery),
    vocabularyGrowth: toVocabularyGrowth(value.vocabularyGrowth),
    topicMastery,
    commonErrors: [],
    sessionHistory: toSessionHistory(value.sessionHistory),
  };
}

export function loadLearningModel(): LearningModel {
  if (typeof window === "undefined") return DEFAULT_LEARNING_MODEL;

  try {
    const raw = window.localStorage.getItem(LEARNING_MODEL_STORAGE_KEY);
    if (!raw) return DEFAULT_LEARNING_MODEL;
    return normalize(JSON.parse(raw)) ?? DEFAULT_LEARNING_MODEL;
  } catch (error) {
    console.error("Could not read the saved learning model:", error);
    return DEFAULT_LEARNING_MODEL;
  }
}

export function saveLearningModel(model: LearningModel): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      LEARNING_MODEL_STORAGE_KEY,
      JSON.stringify(model),
    );
  } catch (error) {
    console.error("Could not save the learning model:", error);
  }
}
