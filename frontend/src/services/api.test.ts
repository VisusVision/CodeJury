import { afterEach, describe, expect, test, vi } from "vitest";
import {
  analyzeCode,
  fetchHealth,
  getAssignmentTestCases,
  replaceAssignmentTestCases,
  suggestAssignmentTestCases,
} from "./api";

describe("analyzeCode", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  test("polls queued analysis jobs until completion", async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ job_id: "job-123", status: "queued" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ job_id: "job-123", status: "running" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          job_id: "job-123",
          status: "completed",
          result: {
            totalScore: 93,
            maxScore: 100,
            summary: "Genel olarak basarili.",
            strengths: ["Kod calisiyor."],
            weaknesses: [],
            recommendations: ["Test ekleyin."],
            resourceRecommendations: [],
            taskAlignment: {
              factor: 0.95,
              programmatic_factor: 0.9,
              llm_factor: 1,
              llm_off_topic: false,
              reasons: [],
              capability_match: 1,
            },
          },
        }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const promise = analyzeCode("main.py", "print('ok')", "assignment-1", "tr");
    await vi.advanceTimersByTimeAsync(1500);
    await vi.advanceTimersByTimeAsync(1500);
    const result = await promise;

    expect(result.totalScore).toBe(93);
    expect(result.summary).toBe("Genel olarak basarili.");
    expect(result.taskAlignment?.factor).toBe(0.95);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/analyze/jobs/job-123",
      expect.objectContaining({ cache: "no-store", credentials: "include" }),
    );
  });

  test("emits partial analysis results before report generation finishes", async () => {
    vi.useFakeTimers();
    const onProgress = vi.fn();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ job_id: "job-123", status: "queued" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          job_id: "job-123",
          status: "running",
          updated_at: "2026-06-27T18:00:05Z",
          report_status: "preparing",
          result: {
            totalScore: 78,
            maxScore: 100,
            rubric: [],
            agents: [],
            evidence: [],
            fileName: "main.py",
            executionTimeMs: 1234,
            memoryUsageMb: 12,
            peakMemoryMb: 18,
            reportStatus: "preparing",
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          job_id: "job-123",
          status: "completed",
          updated_at: "2026-06-27T18:00:08Z",
          report_status: "ready",
          result: {
            totalScore: 78,
            maxScore: 100,
            rubric: [],
            agents: [],
            evidence: [],
            fileName: "main.py",
            executionTimeMs: 1234,
            memoryUsageMb: 12,
            peakMemoryMb: 18,
            reportStatus: "ready",
            resourceRecommendations: [],
          },
        }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const promise = analyzeCode("main.py", "print('ok')", "assignment-1", "tr", undefined, undefined, onProgress);
    await vi.advanceTimersByTimeAsync(1500);
    await vi.advanceTimersByTimeAsync(1500);
    const result = await promise;

    expect(onProgress).toHaveBeenCalledTimes(2);
    expect(onProgress.mock.calls[0][0].reportStatus).toBe("preparing");
    expect(onProgress.mock.calls[0][1]).toEqual({ status: "running", reportStatus: "preparing" });
    expect(result.reportStatus).toBe("ready");
  });

  test("throws backend error when a queued analysis job fails", async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ job_id: "job-123", status: "queued" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ job_id: "job-123", status: "failed", error: "Analiz tamamlanamadi." }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const promise = expect(analyzeCode("main.py", "bad", "assignment-1", "tr")).rejects.toThrow("Analiz tamamlanamadi.");
    await vi.advanceTimersByTimeAsync(1500);

    await promise;
  });
});

describe("assignment test cases", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("lists assignment test cases", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => [{ id: "tc-1", name: "public", visibility: "public" }],
    });
    vi.stubGlobal("fetch", fetchMock);

    const rows = await getAssignmentTestCases("assignment-1");

    expect(rows[0].name).toBe("public");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/assignments/assignment-1/test-cases",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  test("replaces assignment test cases", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => [{ id: "tc-1", name: "hidden", visibility: "hidden" }],
    });
    vi.stubGlobal("fetch", fetchMock);

    await replaceAssignmentTestCases("assignment-1", [
      { name: "hidden", stdin: "0\n", expected_stdout: "0\n", visibility: "hidden", source: "manual" },
    ]);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/assignments/assignment-1/test-cases",
      expect.objectContaining({
        method: "PUT",
        credentials: "include",
        headers: expect.any(Headers),
        body: JSON.stringify({
          test_cases: [
            { name: "hidden", stdin: "0\n", expected_stdout: "0\n", visibility: "hidden", source: "manual" },
          ],
        }),
      }),
    );
  });

  test("fetches AI test case suggestions without persisting them", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({ suggestions: [{ id: "tc-ai", name: "edge", source: "ai" }] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const rows = await suggestAssignmentTestCases("assignment-1");

    expect(rows[0].source).toBe("ai");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/assignments/assignment-1/test-cases/suggest",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
  });
});

describe("fetchHealth", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("returns llm and sandbox snapshots from /api/health", async () => {
    const payload = {
      status: "ok",
      analysis_ready: true,
      worker_count: 1,
      ready_worker_count: 1,
      llm: { enabled: true, general_model: "llama3", coder_model: "qwen2.5-coder" },
      sandbox: { mode: "pool", pool_ready: true, container_count: 3, available_count: 2 },
    };
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => payload,
    });
    vi.stubGlobal("fetch", fetchMock);

    const health = await fetchHealth();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/health",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(health?.llm?.general_model).toBe("llama3");
    expect(health?.sandbox?.mode).toBe("pool");
    expect(health?.sandbox?.available_count).toBe(2);
    expect(health?.analysis_ready).toBe(true);
    expect(health?.worker_count).toBe(1);
  });

  test("returns null when health endpoint is unavailable", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: false });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchHealth()).resolves.toBeNull();
  });

  test("returns null when fetch throws", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValueOnce(new Error("network down")));

    await expect(fetchHealth()).resolves.toBeNull();
  });
});
