"use client";

import ProviderPicker from "@/components/ProviderPicker";
import { LatestInteractionCard } from "./LatestInteractionCard";
import { LearningGoalsCard } from "./LearningGoalsCard";
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

      <ModelStatusCard
        stats={stats}
        recallUnlocked={recallUnlocked}
        onDownloadModel={onDownloadModel}
      />
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
