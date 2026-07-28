"use client";

/**
 * Ported from ollama8jul/components/tutor/TutorPage.tsx — same composition,
 * wired to this app's backend and layout.
 */

import { useCallback, useEffect, useState } from "react";
import { useLearningTutor } from "@/hooks/useLearningTutor";
import type { ProvidersPayload } from "@/lib/types";
import { ChatComposer } from "./ChatComposer";
import { MessageList } from "./MessageList";
import { ModelReadyBanner } from "./ModelReadyBanner";
import { TutorHeader } from "./TutorHeader";
import { TutorSidebar } from "./TutorSidebar";

export default function TutorPage() {
  const tutor = useLearningTutor();
  const [providers, setProviders] = useState<ProvidersPayload | null>(null);

  const loadProviders = useCallback(async () => {
    try {
      const response = await fetch("/api/providers");
      if (!response.ok) return;
      const body = (await response.json()) as ProvidersPayload;
      setProviders(body);

      const preferred =
        body.data.find((p) => p.name === body.default_provider && p.available) ??
        body.data.find((p) => p.available);
      if (preferred) {
        tutor.setProvider(preferred.name);
        tutor.setModel(preferred.default_model);
      }
    } catch {
      /* the picker shows its loading state */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void loadProviders();
  }, [loadProviders]);

  const indexedLessons = tutor.stats?.interactions ?? tutor.learningModel.interactions;

  return (
    <div className="shell">
      <TutorHeader
        selectedTerm={tutor.selectedTerm}
        onSelectedTermChange={tutor.setSelectedTerm}
        mode={tutor.mode}
        onModeChange={tutor.setMode}
        learningModel={tutor.learningModel}
        indexedLessons={indexedLessons}
        onDownloadModel={tutor.downloadModel}
      />

      <ModelReadyBanner
        learningModel={tutor.learningModel}
        stats={tutor.stats}
        recallUnlocked={tutor.recallUnlocked}
        showModelPanel={tutor.showModelPanel}
        onToggleModelPanel={() => tutor.setShowModelPanel(!tutor.showModelPanel)}
      />

      {tutor.error && <div className="error-box">{tutor.error}</div>}

      <div className="layout">
        <div>
          <MessageList
            messages={tutor.messages}
            loading={tutor.loading}
            selectedTerm={tutor.selectedTerm}
            learningModel={tutor.learningModel}
            indexedLessons={indexedLessons}
            recallUnlocked={tutor.recallUnlocked}
            messagesEndRef={tutor.messagesEndRef}
          />

          <ChatComposer
            input={tutor.input}
            onInputChange={tutor.setInput}
            loading={tutor.loading}
            modelSource={tutor.modelSource}
            onModelSourceChange={tutor.setModelSource}
            indexedLessons={indexedLessons}
            recallUnlocked={tutor.recallUnlocked}
            onSend={tutor.handleSend}
          />
        </div>

        <TutorSidebar
          learningModel={tutor.learningModel}
          stats={tutor.stats}
          indexedLessons={indexedLessons}
          recallUnlocked={tutor.recallUnlocked}
          feedback={tutor.feedback}
          chartData={tutor.chartData}
          goals={tutor.goals}
          newGoal={tutor.newGoal}
          onNewGoalChange={tutor.setNewGoal}
          onAddGoal={tutor.addGoal}
          onRemoveGoal={tutor.removeGoal}
          onDownloadModel={tutor.downloadModel}
          providers={providers}
          provider={tutor.provider}
          model={tutor.model}
          onProviderChange={tutor.setProvider}
          onModelChange={tutor.setModel}
          loading={tutor.loading}
        />
      </div>
    </div>
  );
}
