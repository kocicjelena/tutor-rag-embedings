"use client";

/**
 * Ported from ollama8jul/components/tutor/TutorPage.tsx — same composition,
 * wired to this app's backend and layout.
 */

import { useEffect } from "react";
import SignIn from "@/components/SignIn";
import { useContextActions, useContextState } from "@/context/GlobalContext";
import { useLearningTutor } from "@/hooks/useLearningTutor";
import { ChatComposer } from "./ChatComposer";
import { MessageList } from "./MessageList";
import { ModelReadyBanner } from "./ModelReadyBanner";
import { TutorHeader } from "./TutorHeader";
import { TutorSidebar } from "./TutorSidebar";

export default function TutorPage() {
  const tutor = useLearningTutor();
  // The same catalogue the home page uses, fetched once for the whole app. It used to be
  // fetched again here, with its own copy of the "prefer the default, fall back to what is
  // available" rule — so choosing Claude on `/` and walking to `/tutor` silently reset it.
  const { providers, session } = useContextState();
  const { loadProviders, setProvider, setModel, checkSession } = useContextActions();

  useEffect(() => {
    if (!providers.loaded) void loadProviders();
  }, [providers.loaded, loadProviders]);

  useEffect(() => {
    void checkSession();
  }, [checkSession]);

  const indexedLessons = tutor.stats?.interactions ?? tutor.learningModel.interactions;

  // Signed out, every request this page makes returns 401 and the page shows
  // an empty tutor with no explanation — which reads as broken rather than as
  // locked. `/` has guarded on this since the store existed; this one never
  // did, because nothing here had a reason to look at the session until
  // registration made signing in something a visitor actually does.
  if (!session.signedIn) {
    return (
      <div className="shell">
        <header className="masthead">
          <div>
            <h1>AI Learning Tutor</h1>
            <div className="sub">Sign in, or create an account, to start learning</div>
          </div>
        </header>
        <SignIn />
      </div>
    );
  }

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
          providers={providers.data}
          provider={providers.provider}
          model={providers.model}
          onProviderChange={setProvider}
          onModelChange={setModel}
          loading={tutor.loading}
        />
      </div>
    </div>
  );
}
