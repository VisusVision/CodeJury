import type { ApiHealthResponse } from "@/services/api";

export type AnalysisPreflightResult =
  | { ok: true; warnings: string[] }
  | { ok: false; reason: string };

export function checkAnalysisPreflight(
  health: ApiHealthResponse | null,
  messages: {
    healthUnavailable: string;
    llmDisabled: string;
    sandboxSimulation: string;
    durationHint: string;
  },
): AnalysisPreflightResult {
  if (!health || health.status !== "ok") {
    return { ok: false, reason: messages.healthUnavailable };
  }

  if (health.llm?.enabled === false) {
    return { ok: false, reason: messages.llmDisabled };
  }

  const warnings: string[] = [messages.durationHint];
  const sandbox = health.sandbox;
  if (!sandbox?.pool_ready || sandbox.mode !== "pool") {
    warnings.push(messages.sandboxSimulation);
  }

  return { ok: true, warnings };
}
