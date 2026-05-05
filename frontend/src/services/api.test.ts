import { afterEach, describe, expect, test, vi } from "vitest";
import { analyzeCode } from "./api";

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
