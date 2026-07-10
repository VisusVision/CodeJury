import { describe, expect, test } from "vitest";
import { formatRuntimeHealthLabel } from "./runtimeHealthLabel";

describe("formatRuntimeHealthLabel", () => {
  test("returns unknown when health is null", () => {
    expect(formatRuntimeHealthLabel(null)).toEqual({
      status: "unknown",
      llmText: "—",
      sandboxText: "—",
    });
  });

  test("formats llm models, pool capacity, and worker counts when fully ready", () => {
    const label = formatRuntimeHealthLabel({
      status: "ok",
      analysis_ready: true,
      worker_count: 1,
      ready_worker_count: 1,
      llm: { enabled: true, general_model: "llama3", coder_model: "qwen-coder" },
      sandbox: { mode: "pool", pool_ready: true, container_count: 3, available_count: 2 },
    });

    expect(label.status).toBe("ok");
    expect(label.llmText).toBe("llama3 / qwen-coder");
    expect(label.sandboxText).toBe("pool (2/3), workers 1/1");
  });

  test("marks degraded when only partial worker capacity is ready", () => {
    const label = formatRuntimeHealthLabel({
      status: "degraded",
      analysis_ready: true,
      worker_count: 2,
      ready_worker_count: 1,
      llm: { enabled: true, general_model: "a", coder_model: "b" },
      sandbox: { mode: "pool", pool_ready: true, container_count: 1, available_count: 0 },
    });

    expect(label.status).toBe("degraded");
    expect(label.sandboxText).toBe("pool (0/1), workers 1/2");
  });

  test("shows unavailable sandbox text and degraded status when analysis is not ready", () => {
    const label = formatRuntimeHealthLabel({
      status: "degraded",
      analysis_ready: false,
      worker_count: 0,
      ready_worker_count: 0,
      llm: { enabled: true, general_model: "a", coder_model: "b" },
      sandbox: { mode: "unavailable", pool_ready: false },
    });

    expect(label.status).toBe("degraded");
    expect(label.sandboxText).toBe("unavailable");
  });
});
