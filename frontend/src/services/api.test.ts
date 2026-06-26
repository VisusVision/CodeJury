import { afterEach, describe, expect, test, vi } from "vitest";
import { analyzeCode, getAssignmentTestCases, replaceAssignmentTestCases, suggestAssignmentTestCases } from "./api";

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
        json: async () => ({ job_id: "job-123", status: "completed", result: { totalScore: 93, maxScore: 100 } }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const promise = analyzeCode("main.py", "print('ok')", "assignment-1", "tr");
    await vi.advanceTimersByTimeAsync(1500);
    await vi.advanceTimersByTimeAsync(1500);
    const result = await promise;

    expect(result.totalScore).toBe(93);
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/analyze/jobs/job-123", { cache: "no-store" });
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
    expect(fetchMock).toHaveBeenCalledWith("/api/assignments/assignment-1/test-cases");
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

    expect(fetchMock).toHaveBeenCalledWith("/api/assignments/assignment-1/test-cases", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        test_cases: [
          { name: "hidden", stdin: "0\n", expected_stdout: "0\n", visibility: "hidden", source: "manual" },
        ],
      }),
    });
  });

  test("fetches AI test case suggestions without persisting them", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({ suggestions: [{ id: "tc-ai", name: "edge", source: "ai" }] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const rows = await suggestAssignmentTestCases("assignment-1");

    expect(rows[0].source).toBe("ai");
    expect(fetchMock).toHaveBeenCalledWith("/api/assignments/assignment-1/test-cases/suggest", { method: "POST" });
  });
});
