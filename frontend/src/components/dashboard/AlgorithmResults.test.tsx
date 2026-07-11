import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import AlgorithmResults from "./AlgorithmResults";
import type { ApiAlgorithmResult } from "@/services/api";

const baseResult: ApiAlgorithmResult = {
  detectedAlgorithms: ["ikili arama"],
  dataStructures: ["dizi"],
  timeComplexity: "O(log n)",
  spaceComplexity: "O(1)",
  actualFamily: "binary_search",
  actualConfidence: 0.92,
  expectedComplexity: "O(log n)",
  expectedApproach: "ikili arama",
  expectedFamilies: ["binary_search"],
  expectedSource: "llm_verified",
  expectedConfidence: 0.88,
  expectationVersion: 3,
  complexityGap: "worse_than_expected",
  gapSteps: 1,
  gapExplanation: "Gercek karmasiklik O(n log n), beklenen O(log n).",
  recommendedApproach: "Siralanmis dizide ikili arama kullanin.",
  evidence: [{ line: 12, kind: "loop", detail: "Ic ice dongu tespit edildi." }],
};

describe("AlgorithmResults student audience", () => {
  test("renders gap evidence without private provenance fields", () => {
    render(<AlgorithmResults audience="student" result={baseResult} />);

    expect(screen.getAllByText("ikili arama").length).toBeGreaterThan(0);
    expect(screen.getAllByText("O(log n)").length).toBeGreaterThan(0);
    expect(screen.getByText(/Gercek karmasiklik/i)).toBeInTheDocument();
    expect(screen.getByText(/Siralanmis dizide ikili arama/i)).toBeInTheDocument();
    expect(screen.getByText(/Ic ice dongu tespit edildi/i)).toBeInTheDocument();
    expect(screen.getByText(/:12/)).toBeInTheDocument();

    expect(screen.queryByText("llm_verified")).not.toBeInTheDocument();
    expect(screen.queryByText(/provider/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/model/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/cache/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/verifier/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/pseudo/i)).not.toBeInTheDocument();
    expect(screen.queryByText("binary_search")).not.toBeInTheDocument();
  });

  test("unknown gap avoids penalty claim", () => {
    render(
      <AlgorithmResults
        audience="student"
        result={{
          ...baseResult,
          complexityGap: "unknown",
          actualConfidence: 0.2,
          gapExplanation: "Karmasiklik guvenli karsilastirilamadi.",
        }}
      />,
    );

    expect(screen.getByText("Belirsiz")).toBeInTheDocument();
    expect(screen.getByText(/skor cezası uygulanmadı/i)).toBeInTheDocument();
    expect(screen.queryByText(/ceza uygulandi/i)).not.toBeInTheDocument();
  });
});

describe("AlgorithmResults teacher audience", () => {
  test("renders confidence source version and verifier status", () => {
    render(<AlgorithmResults audience="teacher" result={baseResult} />);

    expect(screen.getByText(/LLM doğrulamalı/i)).toBeInTheDocument();
    expect(screen.getByText(/Beklenti Sürümü/i)).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText(/Güven/i)).toBeInTheDocument();
    expect(screen.getAllByText(/binary_search/i).length).toBeGreaterThan(0);
  });
});
