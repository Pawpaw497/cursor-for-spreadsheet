import React, { useState } from "react";

type ClarificationBubbleProps = {
  question: string;
  options?: string[] | null;
  context?: string | null;
  onSelectOption: (option: string) => void;
};

export function ClarificationBubble({
  question,
  options,
  context,
  onSelectOption
}: ClarificationBubbleProps) {
  const [contextOpen, setContextOpen] = useState(false);
  const hasContext = Boolean(context?.trim());
  const chipOptions = options?.filter((o) => o.trim()) ?? [];

  return (
    <div className="clarification-bubble">
      <div className="chat-content">{question || "(空)"}</div>
      {hasContext && (
        <div className="clarification-context">
          <button
            type="button"
            className="clarification-context-toggle small"
            onClick={() => setContextOpen((open) => !open)}
            aria-expanded={contextOpen}
          >
            {contextOpen ? "收起详情" : "查看详情"}
          </button>
          {contextOpen && <pre className="clarification-context-body">{context}</pre>}
        </div>
      )}
      {chipOptions.length > 0 && (
        <div className="clarification-chips" role="listbox" aria-label="澄清选项">
          {chipOptions.map((option) => (
            <button
              key={option}
              type="button"
              className="clarification-chip"
              role="option"
              onClick={() => onSelectOption(option)}
            >
              {option}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
