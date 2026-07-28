import type { AITerm, LearningModel } from "./types";

export const LEARNING_MODEL_STORAGE_KEY = "mcp-py-learning-model";

/**
 * Interactions before recall mode unlocks.
 *
 * The source had this at 1, which reads like a debug value — the "your model is
 * ready" moment fired on the very first message, before there was anything to
 * recall. Three is enough for retrieval to have something to choose between,
 * which is what makes the unlock feel earned.
 */
export const RECALL_UNLOCK_INTERACTIONS = 3;

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
