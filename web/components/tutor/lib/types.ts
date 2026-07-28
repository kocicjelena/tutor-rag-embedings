/**
 * Ported from ollama8jul/components/tutor/lib/types.ts.
 *
 * Unchanged except `ModelSource`, which now names what actually happens:
 *   "tutor"  — a fresh explanation generated for you
 *   "recall" — an answer retrieved from lessons you have already had
 * The source called these "claude" and "trained"; both are now provider-agnostic
 * (either can run on Ollama or Claude), so naming them after the provider would
 * have been misleading.
 */

export type ProficiencyLevel = "beginner" | "intermediate" | "advanced";
export type TutorMode = "casual" | "structured";
export type ModelSource = "tutor" | "recall";
export type ChatRole = "user" | "assistant";

export type AITerm = {
  id: string;
  label: string;
  desc: string;
};

export type SourceChunk = {
  chunk_id: string;
  document_id: string;
  document_title: string;
  content: string;
  score: number;
};

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  timestamp: number;
  source?: ModelSource;
  /** Lessons this answer was recalled from. Only set for source === "recall". */
  sources?: SourceChunk[];
  /** False when recall found nothing — rendered as an honest gap, not an answer. */
  grounded?: boolean;
  provider?: string;
  model?: string;
};

export type VocabularyGrowthPoint = {
  session: number;
  terms: number;
};

export type SessionHistoryItem = {
  term: string;
  timestamp: number;
  userMsg: string;
  aiResponse: string;
};

export type LearningModel = {
  interactions: number;
  proficiencyLevel: ProficiencyLevel;
  vocabularyGrowth: VocabularyGrowthPoint[];
  topicMastery: Record<string, number>;
  commonErrors: string[];
  sessionHistory: SessionHistoryItem[];
};

export type InteractionFeedback = {
  termsUsed: string[];
  complexity: "brief" | "moderate" | "detailed";
  engagement: "high";
  timestamp: string;
};

/** Corpus-derived counts from GET /api/v1/tutor/stats. */
export type TutorStats = {
  interactions: number;
  topics: string[];
  indexed_chunks: number;
  embedding_model: string;
};
