import type { ApiHealthResponse } from "@/services/api";

export type AnalysisPreflightResult =
  | { ok: true; warnings: string[] }
  | { ok: false; reason: string };

export function checkAnalysisPreflight(
  health: ApiHealthResponse | null,
  messages: {
    healthUnavailable: string;
    llmDisabled: string;
    sandboxUnavailable: string;
    durationHint: string;
  },
): AnalysisPreflightResult {
  if (!health) {
    return { ok: false, reason: messages.healthUnavailable };
  }
  if (health.llm?.enabled === false) {
    return { ok: false, reason: messages.llmDisabled };
  }
  if (health.analysis_ready !== true) {
    return { ok: false, reason: messages.sandboxUnavailable };
  }
  return { ok: true, warnings: [messages.durationHint] };
}
