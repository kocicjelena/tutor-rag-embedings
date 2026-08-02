"use client";

import ProviderPicker from "@/components/ProviderPicker";
import { useContextState } from "@/context/GlobalContext";
import { LatestInteractionCard } from "./LatestInteractionCard";
import { LiveModelCard } from "./LiveModelCard";
import { LearningGoalsCard } from "./LearningGoalsCard";
import { ModelDownloadCard } from "./ModelDownloadCard";
import { ModelStatusCard } from "./ModelStatusCard";
import { TopicMasteryCard } from "./TopicMasteryCard";
import { TrainingProgressCard } from "./TrainingProgressCard";
import { VocabularyGrowthChart } from "./VocabularyGrowthChart";
import type {
  InteractionFeedback,
  LearningModel,
  TutorStats,
  VocabularyGrowthPoint,
} from "./lib/types";
import type { ProvidersPayload } from "@/lib/types";

type Props = {
  learningModel: LearningModel;
  stats: TutorStats | null;
  indexedLessons: number;
  recallUnlocked: boolean;
  feedback: InteractionFeedback | null;
  chartData: VocabularyGrowthPoint[];
  goals: string[];
  newGoal: string;
  onNewGoalChange: (goal: string) => void;
  onAddGoal: () => void;
  onRemoveGoal: (index: number) => void;
  onDownloadModel: () => void;
  providers: ProvidersPayload | null;
  provider: string;
  model: string;
  onProviderChange: (name: string) => void;
  onModelChange: (name: string) => void;
  loading: boolean;
};

export function TutorSidebar({
  learningModel,
  stats,
  indexedLessons,
  recallUnlocked,
  feedback,
  chartData,
  goals,
  newGoal,
  onNewGoalChange,
  onAddGoal,
  onRemoveGoal,
  onDownloadModel,
  providers,
  provider,
  model,
  onProviderChange,
  onModelChange,
  loading,
}: Props) {
  const liveModel = useContextState().model;

  return (
    <aside>
      {/* Reused from the documents page. In the tutor it carries extra meaning:
          it decides who teaches you, and separately who synthesises your recall. */}
      <ProviderPicker
        providers={providers}
        provider={provider}
        model={model}
        onProviderChange={onProviderChange}
        onModelChange={onModelChange}
        disabled={loading}
      />

      {/* Reads the store directly rather than taking a prop. The model slice is global —
          the channel keeps running whatever is on screen — so threading it through here
          would be the same patch shape the other four removed wires were. */}
      <LiveModelCard model={liveModel} />

      <ModelStatusCard
        stats={stats}
        recallUnlocked={recallUnlocked}
        onDownloadModel={onDownloadModel}
      />

      {/* The real artifacts, straight from the corpus on the server. Distinct from
          ModelStatusCard's own download, which exports the browser's dashboard —
          proficiency, topic mastery, the vocabulary chart — and not the lessons. */}
      <ModelDownloadCard stats={stats} />
      <TrainingProgressCard
        learningModel={learningModel}
        stats={stats}
        indexedLessons={indexedLessons}
        recallUnlocked={recallUnlocked}
      />
      <LatestInteractionCard feedback={feedback} />
      <VocabularyGrowthChart chartData={chartData} />
      <TopicMasteryCard learningModel={learningModel} />
      <LearningGoalsCard
        goals={goals}
        newGoal={newGoal}
        onNewGoalChange={onNewGoalChange}
        onAddGoal={onAddGoal}
        onRemoveGoal={onRemoveGoal}
      />
    </aside>
  );
}
