"use client";

import type { RefObject } from "react";
import { EmptyLearningState } from "./EmptyLearningState";
import type { ChatMessage, LearningModel } from "./lib/types";
import { BrainIcon, SparkIcon } from "./Icons";

type Props = {
  messages: ChatMessage[];
  loading: boolean;
  selectedTerm: string;
  learningModel: LearningModel;
  indexedLessons: number;
  recallUnlocked: boolean;
  messagesEndRef: RefObject<HTMLDivElement | null>;
};

export function MessageList({
  messages,
  loading,
  selectedTerm,
  learningModel,
  indexedLessons,
  recallUnlocked,
  messagesEndRef,
}: Props) {
  return (
    <div className="panel" style={{ minHeight: 340 }}>
      {messages.length === 0 && (
        <EmptyLearningState
          selectedTerm={selectedTerm}
          learningModel={learningModel}
          indexedLessons={indexedLessons}
          recallUnlocked={recallUnlocked}
        />
      )}

      {messages.map((message) => (
        <div
          key={message.id}
          className={`bubble-row ${message.role === "user" ? "me" : ""}`}
        >
          <div style={{ maxWidth: "88%" }}>
            {message.role === "assistant" && message.source && (
              <div
                className={`bubble-src ${message.source === "recall" ? "recall" : ""}`}
              >
                {message.source === "recall" ? (
                  <>
                    <SparkIcon size={12} />
                    Recalled from your lessons
                  </>
                ) : (
                  <>
                    <BrainIcon size={12} />
                    Tutor
                  </>
                )}
                {message.model && (
                  <span className="mono" style={{ opacity: 0.75 }}>
                    · {message.model}
                  </span>
                )}
                {message.source === "recall" && message.grounded === false && (
                  <span className="badge warn">not learned yet</span>
                )}
              </div>
            )}

            <div
              className={
                message.role === "user"
                  ? "bubble me"
                  : message.source === "recall"
                    ? "bubble recall"
                    : "bubble tutor"
              }
            >
              {message.content || (
                <span className="typing">
                  <i />
                  <i />
                  <i />
                </span>
              )}
            </div>

            {message.sources && message.sources.length > 0 && (
              <details style={{ marginTop: 6 }}>
                <summary className="hint" style={{ cursor: "pointer" }}>
                  {message.sources.length} lesson
                  {message.sources.length === 1 ? "" : "s"} used
                </summary>
                <div style={{ marginTop: 6 }}>
                  {message.sources.map((source, i) => (
                    <div className="source" key={source.chunk_id}>
                      <div className="meta">
                        <span className="mono">
                          [{i + 1}] {source.document_title}
                        </span>
                        <span className="badge">{source.score.toFixed(3)}</span>
                      </div>
                      <div className="body">{source.content}</div>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </div>
        </div>
      ))}

      {loading && messages[messages.length - 1]?.role === "user" && (
        <div className="bubble-row">
          <div className="bubble tutor">
            <span className="typing">
              <i />
              <i />
              <i />
            </span>
          </div>
        </div>
      )}

      <div ref={messagesEndRef} />
    </div>
  );
}
