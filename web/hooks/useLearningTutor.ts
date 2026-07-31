"use client";

/**
 * Ported from ollama8jul/hooks/useLearningTutor.ts.
 *
 * The dashboard half is unchanged. What changed is what the two model sources
 * actually do:
 *
 *   tutor  → streams from POST /api/tutor/teach, then records the exchange so
 *            the corpus grows. The source called Claude straight from the
 *            browser and awaited the whole answer.
 *   recall → POST /api/tutor/recall, semantic retrieval over the learner's own
 *            lessons. The source ran `answerWithTrainedModel()`, which scored
 *            past questions by shared-word count and replayed the closest
 *            answer verbatim.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AI_TERMS,
  DEFAULT_GOALS,
  DEFAULT_LEARNING_MODEL,
  RECALL_UNLOCK_INTERACTIONS,
} from "@/components/tutor/lib/constants";
import { downloadLearningModel } from "@/components/tutor/lib/downloadModel";
import {
  generateFeedback,
  updateLearningModelAfterInteraction,
} from "@/components/tutor/lib/modelAnalysis";
import { loadLearningModel, saveLearningModel } from "@/components/tutor/lib/storage";
import { findTermById } from "@/components/tutor/lib/terms";
import type {
  ChatMessage,
  InteractionFeedback,
  LearningModel,
  ModelSource,
  SourceChunk,
  TutorMode,
  TutorStats,
} from "@/components/tutor/lib/types";
import { useContextActions } from "@/context/GlobalContext";
import { useStickToBottom } from "@/hooks/useStickToBottom";

let messageSeq = 0;
const nextId = () => `m${++messageSeq}`;

export type LearningTutorState = {
  selectedTerm: string;
  setSelectedTerm: (termId: string) => void;
  messages: ChatMessage[];
  input: string;
  setInput: (value: string) => void;
  loading: boolean;
  error: string | null;
  mode: TutorMode;
  setMode: (mode: TutorMode) => void;
  modelSource: ModelSource;
  setModelSource: (source: ModelSource) => void;
  provider: string;
  setProvider: (name: string) => void;
  model: string;
  setModel: (name: string) => void;
  feedback: InteractionFeedback | null;
  showModelPanel: boolean;
  setShowModelPanel: (show: boolean) => void;
  learningModel: LearningModel;
  stats: TutorStats | null;
  recallUnlocked: boolean;
  goals: string[];
  newGoal: string;
  setNewGoal: (goal: string) => void;
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  chartData: { session: number; terms: number }[];
  handleSend: () => Promise<void>;
  addGoal: () => void;
  removeGoal: (index: number) => void;
  downloadModel: () => void;
};

export function useLearningTutor(): LearningTutorState {
  // The chunk pipe. `runStream` is memoised in the provider, so it is a stable dependency for
  // every useCallback below — it never re-creates `teach`.
  const { runStream } = useContextActions();

  const [selectedTerm, setSelectedTerm] = useState(AI_TERMS[0].id);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<TutorMode>("casual");
  const [modelSource, setModelSource] = useState<ModelSource>("tutor");
  const [provider, setProvider] = useState("ollama");
  const [model, setModel] = useState("");
  const [feedback, setFeedback] = useState<InteractionFeedback | null>(null);
  const [showModelPanel, setShowModelPanel] = useState(false);
  const [learningModel, setLearningModel] = useState<LearningModel>(
    DEFAULT_LEARNING_MODEL,
  );
  const [stats, setStats] = useState<TutorStats | null>(null);
  const [goals, setGoals] = useState<string[]>(DEFAULT_GOALS);
  const [newGoal, setNewGoal] = useState("");
  // Follows the streaming answer down the page. Previously this scrolled with
  // `behavior: "smooth"` on every `messages` change, which cannot keep up with
  // a token stream — each token restarted the animation and the text drifted
  // out of view. See `useStickToBottom`.
  const messagesEndRef = useStickToBottom(messages, loading);

  const refreshStats = useCallback(async () => {
    try {
      const response = await fetch("/api/tutor/stats");
      if (response.ok) setStats((await response.json()) as TutorStats);
    } catch {
      /* the panel just shows local counts until this succeeds */
    }
  }, []);

  useEffect(() => {
    setLearningModel(loadLearningModel());
    void refreshStats();
  }, [refreshStats]);

  /** Unlock from the server's count when we have it — that's the real corpus. */
  const indexedLessons = stats?.interactions ?? learningModel.interactions;
  const recallUnlocked = indexedLessons >= RECALL_UNLOCK_INTERACTIONS;

  const teach = useCallback(
    async (question: string) => {
      const assistantId = nextId();
      setMessages((prev) => [
        ...prev,
        {
          id: assistantId,
          role: "assistant",
          content: "",
          timestamp: Date.now(),
          source: "tutor",
        },
      ]);

      const response = await fetch("/api/tutor/teach", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          term: findTermById(selectedTerm).label,
          mode,
          goals,
          provider,
          model: model || undefined,
        }),
      });

      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as {
          detail?: unknown;
        };
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : `Tutor request failed (${response.status})`,
        );
      }

      // The chunks go through the store, not through this loop. `runStream` owns the async
      // generator, so `state.stream.lastChunk` is readable by anything on the page while the
      // answer is still arriving — including the tutor's own panels. The callback below is only
      // about this message's text; it is the caller's concern, not the store's.
      let answer = "";
      const streamed = await runStream("teach", assistantId, response, (event) => {
        if (event.type !== "token") return;
        answer += event.text;
        const snapshot = answer;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId ? { ...m, content: snapshot } : m,
          ),
        );
      });

      const usedProvider = streamed.provider ?? provider;
      const usedModel = streamed.model ?? model;

      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? { ...m, provider: usedProvider, model: usedModel }
            : m,
        ),
      );

      if (!answer.trim()) return;

      // Record it so the corpus grows. A failure here must not lose the answer
      // the learner is already reading.
      try {
        await fetch("/api/tutor/interactions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            term: findTermById(selectedTerm).label,
            question,
            answer,
          }),
        });
        void refreshStats();
      } catch {
        setError("The answer arrived, but recording it for recall failed.");
      }

      const nextFeedback = generateFeedback(question, answer);
      setFeedback(nextFeedback);
      setLearningModel((current) => {
        const updated = updateLearningModelAfterInteraction({
          model: current,
          selectedTerm,
          userMessage: question,
          aiResponse: answer,
          feedback: nextFeedback,
        });
        saveLearningModel(updated);
        return updated;
      });
    },
    [goals, mode, model, provider, refreshStats, runStream, selectedTerm],
  );

  const recall = useCallback(
    async (question: string) => {
      const response = await fetch("/api/tutor/recall", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          top_k: 5,
          provider,
          model: model || undefined,
        }),
      });

      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as {
          detail?: unknown;
        };
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : `Recall failed (${response.status})`,
        );
      }

      const body = (await response.json()) as {
        answer: string;
        sources: SourceChunk[];
        grounded: boolean;
        provider: string;
        model: string;
      };

      setMessages((prev) => [
        ...prev,
        {
          id: nextId(),
          role: "assistant",
          content: body.answer,
          timestamp: Date.now(),
          source: "recall",
          sources: body.sources,
          grounded: body.grounded,
          provider: body.provider,
          model: body.model,
        },
      ]);
      setFeedback(generateFeedback(question, body.answer));
    },
    [model, provider],
  );

  const handleSend = useCallback(async () => {
    const question = input.trim();
    if (!question || loading) return;

    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: "user", content: question, timestamp: Date.now() },
    ]);
    setInput("");
    setLoading(true);
    setError(null);

    try {
      if (modelSource === "recall") {
        await recall(question);
      } else {
        await teach(question);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }, [input, loading, modelSource, recall, teach]);

  const addGoal = useCallback(() => {
    const trimmed = newGoal.trim();
    if (!trimmed) return;
    setGoals((prev) => [...prev, trimmed]);
    setNewGoal("");
  }, [newGoal]);

  const removeGoal = useCallback((index: number) => {
    setGoals((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const downloadModel = useCallback(() => {
    downloadLearningModel(learningModel, stats);
  }, [learningModel, stats]);

  return {
    selectedTerm,
    setSelectedTerm,
    messages,
    input,
    setInput,
    loading,
    error,
    mode,
    setMode,
    modelSource,
    setModelSource,
    provider,
    setProvider,
    model,
    setModel,
    feedback,
    showModelPanel,
    setShowModelPanel,
    learningModel,
    stats,
    recallUnlocked,
    goals,
    newGoal,
    setNewGoal,
    messagesEndRef,
    chartData: learningModel.vocabularyGrowth.slice(-12),
    handleSend,
    addGoal,
    removeGoal,
    downloadModel,
  };
}
