import type { AITerm, LearningModel } from "./types";

export const LEARNING_MODEL_STORAGE_KEY = "mcp-py-learning-model";

/**
 * Lessons before "My model" can be selected.
 *
 * **One — the corpus is the gate, not a counter.** This was 3 for a while, on
 * the theory that an unlock feels earned if retrieval has something to choose
 * between. In use that was just a lockout: a learner with two lessons indexed
 * has a working model and was told they could not use it.
 *
 * There was never anything to protect them from. `POST /tutor/recall` answers
 * honestly on a thin corpus — it says what it has not been taught and names
 * what it has — so the backend already handles the case the gate was guarding.
 * A frontend counter on top of that only withholds a feature that works.
 *
 * Zero is still a gate: with nothing indexed there is genuinely nothing to
 * recall, and the empty state says so.
 */
export const RECALL_UNLOCK_INTERACTIONS = 1;

/**
 * Interactions before a learner stops being a "beginner".
 *
 * Was the same constant as the unlock above, which coupled two unrelated
 * ideas — dropping the unlock to 1 would otherwise have promoted everyone to
 * intermediate after a single message.
 */
export const BEGINNER_INTERACTIONS = 3;

export const AI_TERMS: AITerm[] = [
  { id: "generative", label: "Generative AI", desc: "AI that creates new content" },
  { id: "embedding", label: "Embeddings", desc: "Vector representations of data" },
  { id: "ml", label: "Machine Learning", desc: "Systems that learn from data" },
  { id: "nlp", label: "Natural Language Processing", desc: "Understanding human language" },
  { id: "transformer", label: "Transformers", desc: "Attention-based neural networks" },
  { id: "finetuning", label: "Fine-tuning", desc: "Adapting pre-trained models" },
  { id: "rag", label: "RAG", desc: "Retrieval-Augmented Generation" },
  { id: "llm", label: "Large Language Models", desc: "Large-scale language AI" },
  { id: "cnn", label: "CNN", desc: "Convolutional Neural Networks" },
  { id: "rnn", label: "RNN", desc: "Recurrent Neural Networks" },
];

export const DEFAULT_GOALS = [
  "Understand basic AI concepts",
  "Learn about embeddings",
];

export const DEFAULT_LEARNING_MODEL: LearningModel = {
  interactions: 0,
  proficiencyLevel: "beginner",
  vocabularyGrowth: [],
  topicMastery: {},
  commonErrors: [],
  sessionHistory: [],
};
