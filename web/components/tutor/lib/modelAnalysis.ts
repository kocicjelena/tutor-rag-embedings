/**
 * Ported from ollama8jul/components/tutor/lib/modelAnalysis.ts.
 *
 * Logic unchanged. `getProficiencyClassName` now returns one of this app's
 * badge classes instead of Tailwind colour utilities.
 */

import { AI_TERMS, RECALL_UNLOCK_INTERACTIONS } from "./constants";
import type {
  InteractionFeedback,
  LearningModel,
  ProficiencyLevel,
} from "./types";

export function analyzeProficiency(
  interactions: number,
  topicMastery: Record<string, number>,
): ProficiencyLevel {
  if (interactions < RECALL_UNLOCK_INTERACTIONS) return "beginner";
  if (interactions < 15) return "intermediate";

  const masteryValues = Object.values(topicMastery);
  if (masteryValues.length === 0) return "intermediate";

  const avgMastery =
    masteryValues.reduce((total, mastery) => total + mastery, 0) /
    masteryValues.length;

  return avgMastery > 0.7 ? "advanced" : "intermediate";
}

export function extractKeyTerms(text: string): string[] {
  const lowerText = text.toLowerCase();
  return AI_TERMS.filter((term) =>
    lowerText.includes(term.label.toLowerCase()),
  ).map((term) => term.label);
}

export function generateFeedback(
  userMsg: string,
  aiResponse: string,
): InteractionFeedback {
  const keyTerms = extractKeyTerms(`${userMsg} ${aiResponse}`);
  const msgLength = userMsg.split(" ").length;

  return {
    termsUsed: keyTerms,
    complexity:
      msgLength > 20 ? "detailed" : msgLength > 10 ? "moderate" : "brief",
    engagement: "high",
    timestamp: new Date().toISOString(),
  };
}

export function updateLearningModelAfterInteraction({
  model,
  selectedTerm,
  userMessage,
  aiResponse,
  feedback,
}: {
  model: LearningModel;
  selectedTerm: string;
  userMessage: string;
  aiResponse: string;
  feedback: InteractionFeedback;
}): LearningModel {
  const interactions = model.interactions + 1;
  const topicMastery = {
    ...model.topicMastery,
    [selectedTerm]: Math.min(1, (model.topicMastery[selectedTerm] ?? 0) + 0.1),
  };

  return {
    ...model,
    interactions,
    proficiencyLevel: analyzeProficiency(interactions, topicMastery),
    vocabularyGrowth: [
      ...model.vocabularyGrowth,
      { session: interactions, terms: feedback.termsUsed.length },
    ],
    topicMastery,
    sessionHistory: [
      ...model.sessionHistory,
      {
        term: selectedTerm,
        timestamp: Date.now(),
        userMsg: userMessage,
        aiResponse,
      },
    ],
  };
}

export function getProficiencyClassName(level: ProficiencyLevel): string {
  switch (level) {
    case "beginner":
      return "badge";
    case "intermediate":
      return "badge warn";
    case "advanced":
      return "badge ok";
    default:
      return "badge";
  }
}
