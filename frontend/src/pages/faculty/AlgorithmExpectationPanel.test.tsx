import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import AlgorithmExpectationPanel from "./AlgorithmExpectationPanel";

const getAlgorithmExpectationMock = vi.fn();

vi.mock("@/services/api", () => ({
  getAlgorithmExpectation: (...args: unknown[]) => getAlgorithmExpectationMock(...args),
}));

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: React.ComponentProps<"div">) => <div {...props}>{children}</div>,
  },
}));

const assignment = { id: "assignment-1", name: "Ikili Arama" };

describe("AlgorithmExpectationPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test("renders read-only expectation details without inputs", async () => {
    getAlgorithmExpectationMock.mockResolvedValueOnce({
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
    });

    render(<AlgorithmExpectationPanel assignment={assignment} open onClose={() => undefined} />);

    await waitFor(() => {
      expect(screen.getByText("O(log n)")).toBeInTheDocument();
    });
    expect(screen.getAllByText(/ikili arama/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/binary_search/i)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /kaydet|guncelle|olustur/i })).not.toBeInTheDocument();
  });

  test("shows empty state on 404", async () => {
    getAlgorithmExpectationMock.mockRejectedValueOnce(new Error("Henüz doğrulanmış beklenti yok"));

    render(<AlgorithmExpectationPanel assignment={assignment} open onClose={() => undefined} />);

    await waitFor(() => {
      expect(screen.getByText("Henüz doğrulanmış beklenti yok")).toBeInTheDocument();
    });
  });

  test("shows backend detail on 503", async () => {
    getAlgorithmExpectationMock.mockRejectedValueOnce(new Error("Beklenti servisi gecici olarak kullanilamiyor"));

    render(<AlgorithmExpectationPanel assignment={assignment} open onClose={() => undefined} />);

    await waitFor(() => {
      expect(screen.getByText(/Beklenti servisi gecici olarak kullanilamiyor/i)).toBeInTheDocument();
    });
  });
});
