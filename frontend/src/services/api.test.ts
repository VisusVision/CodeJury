import { afterEach, describe, expect, test, vi } from "vitest";
import * as apiModule from "./api";
import {
  analyzeCode,
  fetchHealth,
  getActiveGeneratedTestSet,
  getAlgorithmExpectation,
  getAssignmentTestCases,
  promoteGeneratedTests,
  replaceAssignmentTestCases,
  suggestAssignmentTestCases,
  updateAssignmentDifficulty,
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
      {
        name: "hidden",
        stdin: "0\n",
        expected_stdout: "0\n",
        visibility: "hidden",
        files: [],
        source: "manual",
      },
    ]);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/assignments/assignment-1/test-cases",
      expect.objectContaining({
        method: "PUT",
        credentials: "include",
        headers: expect.any(Headers),
        body: JSON.stringify({
          test_cases: [
            {
              name: "hidden",
              stdin: "0\n",
              expected_stdout: "0\n",
              visibility: "hidden",
              files: [],
              source: "manual",
            },
          ],
        }),
      }),
    );
  });

  test("fetches AI test case suggestions without persisting them", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        suggestions: [
          {
            id: "tc-ai",
            name: "edge",
            source: "auto_generated",
            oracle: "llm_verified",
            files: [{ name: "data.csv", content: "1,2" }],
          },
        ],
        verified_count: 1,
        difficulty: "medium",
        persisted: false,
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await suggestAssignmentTestCases("assignment-1");

    expect(result.suggestions[0].source).toBe("auto_generated");
    expect(result.suggestions[0].files[0].name).toBe("data.csv");
    expect(result.verified_count).toBe(1);
    expect(result.persisted).toBe(false);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/assignments/assignment-1/test-cases/suggest",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
  });

  test("reads active generated test set", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        id: "set-1",
        assignment_id: "assignment-1",
        cache_key: "abc",
        version: 2,
        difficulty: "hard",
        cases: [{ id: "case-1", name: "gen", source: "auto_generated", visibility: "hidden" }],
        provider: "ollama",
        model: "qwen",
        schema_version: "test-set-v1",
        prompt_version: "test-prompt-v1",
        assignment_hash: "",
        rubric_hash: "",
        oracle_validation: [],
        active: true,
        created_at: "2026-07-11T00:00:00Z",
        deactivated_at: null,
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const testSet = await getActiveGeneratedTestSet("assignment-1");

    expect(testSet?.version).toBe(2);
    expect(testSet?.cases[0].source).toBe("auto_generated");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/assignments/assignment-1/generated-test-set",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  test("returns null when no active generated test set exists", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: false, status: 404, text: async () => "" });
    vi.stubGlobal("fetch", fetchMock);

    await expect(getActiveGeneratedTestSet("assignment-1")).resolves.toBeNull();
  });

  test("promotes generated tests with explicit mode and case ids", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => [{ id: "tc-1", name: "promoted", source: "ai_approved", oracle: "llm_verified" }],
    });
    vi.stubGlobal("fetch", fetchMock);

    await promoteGeneratedTests("assignment-1", "set-1", {
      case_ids: ["case-1"],
      mode: "append",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/assignments/assignment-1/generated-test-sets/set-1/promote",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: JSON.stringify({ case_ids: ["case-1"], mode: "append" }),
      }),
    );
  });

  test("updates assignment difficulty", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        id: "assignment-1",
        course_id: "course-1",
        name: "Kare",
        description: null,
        difficulty: "hard",
        difficulty_source: "teacher",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const updated = await updateAssignmentDifficulty("assignment-1", "hard");

    expect(updated.difficulty).toBe("hard");
    expect(updated.difficulty_source).toBe("teacher");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/assignments/assignment-1/difficulty",
      expect.objectContaining({
        method: "PATCH",
        credentials: "include",
        body: JSON.stringify({ difficulty: "hard" }),
      }),
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

describe("getAlgorithmExpectation", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("fetches active algorithm expectation via apiFetch", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        assignmentId: "assignment-1",
        expectedComplexity: "O(log n)",
        expectedApproach: "ikili arama",
        algorithmFamilies: ["binary_search"],
        confidence: 0.9,
        source: "llm_verified",
        version: 2,
        verificationStatus: "verified",
        extractorProvider: "ollama",
        extractorModel: "qwen",
        verifierProvider: "ollama",
        verifierModel: "llama",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const expectation = await getAlgorithmExpectation("assignment-1");

    expect(expectation?.expectedComplexity).toBe("O(log n)");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/assignments/assignment-1/algorithm-expectation",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  test("maps 404 to Turkish empty-state message", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 404,
      text: async () => JSON.stringify({ detail: "Aktif algoritma beklentisi bulunamadi" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(getAlgorithmExpectation("assignment-1")).rejects.toThrow("Henüz doğrulanmış beklenti yok");
  });

  test("surfaces backend detail on 503", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 503,
      text: async () => JSON.stringify({ detail: "Beklenti servisi gecici olarak kullanilamiyor" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(getAlgorithmExpectation("assignment-1")).rejects.toThrow(
      "Beklenti servisi gecici olarak kullanilamiyor",
    );
  });

  test("does not export algorithm expectation mutation helpers", () => {
    const exportedNames = Object.keys(apiModule);
    const mutationNames = exportedNames.filter((name) =>
      /^(create|update|upsert|delete|replace|promote).*AlgorithmExpectation/i.test(name),
    );
    expect(mutationNames).toEqual([]);
  });
});
