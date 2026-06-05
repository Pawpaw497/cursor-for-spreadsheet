import type { AgentTurn } from "./workspaceMemory";

export type PendingClarificationSource = "generate" | "preview_revise";

export type PendingClarification = {
  question: string;
  options?: string[] | null;
  context?: string | null;
  originalPrompt: string;
  traceId: string;
  source: PendingClarificationSource;
};

export function formatClarificationAssistantContent(
  question: string,
  context?: string | null
): string {
  let content = `[Clarification] ${question}`;
  const ctx = context?.trim();
  if (ctx) {
    content += `\n${ctx}`;
  }
  return content;
}

export function buildClarificationResumeHistory(
  existingHistory: AgentTurn[],
  question: string,
  context: string | null | undefined,
  answer: string
): AgentTurn[] {
  return [
    ...existingHistory,
    {
      role: "assistant",
      content: formatClarificationAssistantContent(question, context)
    },
    { role: "user", content: answer }
  ];
}

/** When chat already ends with raw clarification assistant + user answer turns. */
export function buildClarificationResumeHistoryFromChat(
  chatHistory: AgentTurn[],
  question: string,
  context: string | null | undefined,
  answer: string
): AgentTurn[] {
  const base = chatHistory.length >= 2 ? chatHistory.slice(0, -2) : [];
  return buildClarificationResumeHistory(base, question, context, answer);
}

export function buildClarificationResumePrompt(originalPrompt: string, answer: string): string {
  return `${originalPrompt}\n\n[Clarification]\n${answer}`;
}

export function truncatePromptAnchor(prompt: string, maxLen = 72): string {
  const trimmed = prompt.trim();
  if (trimmed.length <= maxLen) {
    return trimmed;
  }
  return `${trimmed.slice(0, maxLen - 1)}…`;
}
