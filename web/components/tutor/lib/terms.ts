import { AI_TERMS } from "./constants";
import type { AITerm } from "./types";

export function findTermById(termId: string): AITerm {
  return AI_TERMS.find((term) => term.id === termId) ?? AI_TERMS[0];
}

export function getTopicLabel(topicId: string): string {
  return findTermById(topicId).label;
}

export function getKnownTopicLabels(topicIds: string[]): string[] {
  return topicIds.map(getTopicLabel).filter(Boolean);
}
