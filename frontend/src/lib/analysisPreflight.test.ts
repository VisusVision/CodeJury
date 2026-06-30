import { describe, expect, test } from "vitest";
import { checkAnalysisPreflight } from "./analysisPreflight";

const messages = {
  healthUnavailable: "health down",
  llmDisabled: "llm off",
  sandboxSimulation: "simulation",
  durationHint: "duration",
};

describe("checkAnalysisPreflight", () => {
  test("blocks when health is unavailable", () => {
    expect(checkAnalysisPreflight(null, messages)).toEqual({ ok: false, reason: "health down" });
  });

  test("blocks when llm is disabled", () => {
    const result = checkAnalysisPreflight(
      { status: "ok", llm: { enabled: false } },
      messages,
    );
    expect(result).toEqual({ ok: false, reason: "llm off" });
  });

  test("warns on simulation sandbox but allows analysis", () => {
    const result = checkAnalysisPreflight(
      {
        status: "ok",
        llm: { enabled: true },
        sandbox: { mode: "simulation", pool_ready: false },
      },
      messages,
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.warnings).toContain("simulation");
      expect(result.warnings).toContain("duration");
    }
  });
});
