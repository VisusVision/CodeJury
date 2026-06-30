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

  test("formats llm models and pool capacity", () => {
    const label = formatRuntimeHealthLabel({
      status: "ok",
      llm: { enabled: true, general_model: "llama3", coder_model: "qwen-coder" },
      sandbox: { mode: "pool", pool_ready: true, container_count: 3, available_count: 2 },
    });

    expect(label.status).toBe("ok");
    expect(label.llmText).toBe("llama3 / qwen-coder");
    expect(label.sandboxText).toBe("pool (2/3)");
  });

  test("marks degraded when pool mode is not ready", () => {
    const label = formatRuntimeHealthLabel({
      status: "ok",
      llm: { enabled: true, general_model: "a", coder_model: "b" },
      sandbox: { mode: "pool", pool_ready: false },
    });

    expect(label.status).toBe("degraded");
  });
});
