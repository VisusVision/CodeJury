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

  let sandboxText = sandbox?.mode ?? "simulation";
  if (sandbox?.pool_ready && typeof sandbox.available_count === "number" && typeof sandbox.container_count === "number") {
    sandboxText = `${sandboxText} (${sandbox.available_count}/${sandbox.container_count})`;
  }

  const status: RuntimeHealthStatus =
    health.status !== "ok" || !llmEnabled
      ? "degraded"
      : sandbox?.mode === "pool" && !sandbox.pool_ready
        ? "degraded"
        : "ok";

  return { status, llmText, sandboxText };
}
