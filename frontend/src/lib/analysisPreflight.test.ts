import { describe, expect, test } from "vitest";
import { checkAnalysisPreflight } from "./analysisPreflight";

const messages = {
  healthUnavailable: "health down",
  llmDisabled: "llm off",
  sandboxUnavailable: "sandbox unavailable",
  durationHint: "duration",
};

describe("checkAnalysisPreflight", () => {
  test("blocks when health is unavailable", () => {
    expect(checkAnalysisPreflight(null, messages)).toEqual({ ok: false, reason: "health down" });
  });

  test("blocks when llm is disabled", () => {
    const result = checkAnalysisPreflight(
      { status: "ok", analysis_ready: true, llm: { enabled: false } },
      messages,
    );
    expect(result).toEqual({ ok: false, reason: "llm off" });
  });

  test("blocks when worker sandbox is unavailable", () => {
    expect(checkAnalysisPreflight(
      {
        status: "degraded",
        analysis_ready: false,
        llm: { enabled: true },
        sandbox: { mode: "unavailable", pool_ready: false, container_count: 0 },
      },
      messages,
    )).toEqual({ ok: false, reason: "sandbox unavailable" });
  });

  test("allows degraded partial capacity when analysis is ready", () => {
    const result = checkAnalysisPreflight(
      {
        status: "degraded",
        analysis_ready: true,
        llm: { enabled: true },
        sandbox: { mode: "pool", pool_ready: true, container_count: 1, available_count: 0 },
      },
      messages,
    );
    expect(result).toEqual({ ok: true, warnings: ["duration"] });
  });
});
