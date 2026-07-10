import type { ApiHealthResponse } from "@/services/api";

export type RuntimeHealthStatus = "unknown" | "ok" | "degraded";

export interface RuntimeHealthLabel {
  status: RuntimeHealthStatus;
  llmText: string;
  sandboxText: string;
}

export function formatRuntimeHealthLabel(health: ApiHealthResponse | null): RuntimeHealthLabel {
  if (!health) {
    return { status: "unknown", llmText: "—", sandboxText: "—" };
  }

  const llm = health.llm;
  const sandbox = health.sandbox;
  const llmEnabled = llm?.enabled !== false;
  const llmText = llmEnabled
    ? `${llm?.general_model ?? "?"} / ${llm?.coder_model ?? "?"}`
    : "off";

  const analysisReady = health.analysis_ready === true;
  const workerCount = health.worker_count ?? 0;
  const readyWorkerCount = health.ready_worker_count ?? 0;

  const sandboxText = analysisReady
    ? `${sandbox?.mode ?? "pool"} (${sandbox?.available_count ?? 0}/${sandbox?.container_count ?? 0}), workers ${readyWorkerCount}/${workerCount}`
    : "unavailable";

  const status: RuntimeHealthStatus =
    !llmEnabled || !analysisReady || readyWorkerCount < workerCount
      ? "degraded"
      : "ok";

  return { status, llmText, sandboxText };
}
