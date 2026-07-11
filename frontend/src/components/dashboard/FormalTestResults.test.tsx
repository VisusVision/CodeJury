import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import FormalTestResults, { type FormalTestResult } from "./FormalTestResults";

const publicFailedCase: FormalTestResult = {
  name: "square two",
  input: "2\n",
  expected: "4\n",
  actual: "5\n",
  passed: false,
  visibility: "public",
  status: "fail",
  source: "auto_generated",
  errorMessageTr: "Cikti beklenen degerle eslesmiyor.",
};

const hiddenErrorCase: FormalTestResult = {
  name: "Hidden test #1",
  visibility: "hidden",
  status: "error",
  passed: false,
};

const teacherHiddenCase: FormalTestResult = {
  id: "hidden-case-id",
  name: "hidden1",
  visibility: "hidden",
  input: "secret input value",
  expected: "secret expected value",
  actual: "wrong output",
  actualStderr: "secret stderr",
  passed: false,
  status: "fail",
  source: "auto_generated",
  diffDetail: "satir 1: beklenen='secret expected' gercek='wrong output'",
  files: [{ name: "secret.csv", content: "secret fixture" }],
  oracleValidation: {
    status: "verified",
    provider: "ollama",
    model: "llama-private",
    schema_version: "v1",
    verified_at: "2026-07-11T00:00:00Z",
    reason: "ok",
  },
};

describe("FormalTestResults student audience", () => {
  test("renders public I/O and Turkish error without hidden details", () => {
    render(
      <FormalTestResults
        audience="student"
        testResults={[publicFailedCase, hiddenErrorCase]}
        hiddenTestSummary={{ passed: 0, failed: 0, error: 1, total: 1 }}
        provenance={{ formalPassed: 0, formalTotal: 2, testSource: "auto_generated", testEvidenceStatus: "available" }}
      />,
    );

    expect(screen.getByText("square two")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("Cikti beklenen degerle eslesmiyor.")).toBeInTheDocument();
    expect(screen.getByText("Hidden test #1")).toBeInTheDocument();
    expect(screen.getByText(/Gizli test ozeti/i)).toBeInTheDocument();
    expect(screen.getByText(/1 hata/i)).toBeInTheDocument();

    expect(screen.queryByText("secret input value")).not.toBeInTheDocument();
    expect(screen.queryByText("secret expected value")).not.toBeInTheDocument();
    expect(screen.queryByText("wrong output")).not.toBeInTheDocument();
    expect(screen.queryByText("secret stderr")).not.toBeInTheDocument();
    expect(screen.getAllByText("Input")).toHaveLength(1);
  });
});

describe("FormalTestResults teacher audience", () => {
  test("renders authorized private hidden fields and provenance", () => {
    render(
      <FormalTestResults
        audience="teacher"
        testResults={[teacherHiddenCase]}
        provenance={{
          testSource: "auto_generated",
          testEvidenceStatus: "available",
          formalPassed: 0,
          formalTotal: 1,
          testSetId: "generated-set-private",
          testSetHash: "cache-key-private",
          cacheVersion: 4,
        }}
      />,
    );

    expect(screen.getByText("secret input value")).toBeInTheDocument();
    expect(screen.getByText("secret expected value")).toBeInTheDocument();
    expect(screen.getByText("wrong output")).toBeInTheDocument();
    expect(screen.getByText("secret stderr")).toBeInTheDocument();
    expect(screen.getByText("secret.csv")).toBeInTheDocument();
    expect(screen.getByText("secret fixture")).toBeInTheDocument();
    expect(screen.getByText(/llama-private/)).toBeInTheDocument();
    expect(screen.getByText("generated-set-private")).toBeInTheDocument();
    expect(screen.getByText("cache-key-private")).toBeInTheDocument();
    expect(screen.getByText(/v4/)).toBeInTheDocument();
    expect(screen.getByText(/available/i)).toBeInTheDocument();
  });
});
