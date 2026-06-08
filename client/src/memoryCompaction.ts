import {
  buildAppliedPlansSummaryFromLog,
  type AgentTurn,
  type AppliedPlanEntry
} from "./workspaceMemory";

export const MAX_CHAT_TURNS = 24;

const EARLIER_PREFIX = "Earlier in this workspace:\n";

function buildEarlierSummary(
  appliedPlansSummary: string,
  applyLog: AppliedPlanEntry[],
  droppedTurnCount: number
): string {
  const summary =
    appliedPlansSummary.trim() ||
    buildAppliedPlansSummaryFromLog(applyLog).trim();
  const header =
    droppedTurnCount > 0
      ? `(${droppedTurnCount} earlier turn(s) omitted)\n`
      : "";
  const body = summary || "(no prior context recorded)";
  return `${EARLIER_PREFIX}${header}${body}`;
}

/** Middle-out compaction for Agent request history (mirrors server policy). */
export function compactAgentTranscript(
  transcript: AgentTurn[],
  applyLog: AppliedPlanEntry[],
  appliedPlansSummary: string,
  maxTurns = MAX_CHAT_TURNS
): AgentTurn[] {
  if (transcript.length <= maxTurns) {
    return transcript;
  }
  const dropped = transcript.length - maxTurns;
  const kept = transcript.slice(-maxTurns);
  return [
    {
      role: "user",
      content: buildEarlierSummary(appliedPlansSummary, applyLog, dropped)
    },
    ...kept
  ];
}
