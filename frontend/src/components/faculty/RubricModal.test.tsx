import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import RubricModal from "./RubricModal";

const translate = (key: string) => key;

vi.mock("@/i18n/LanguageContext", () => ({
  useTranslation: () => ({
    language: "tr",
    t: translate,
  }),
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock("./TestCaseEditor", () => ({
  default: ({ onSaved }: { onSaved?: () => void }) => (
    <div>
      <button type="button" onClick={() => onSaved?.()}>
        Manuel Test Ekle
      </button>
      <button type="button">AI Test Oner</button>
      <input placeholder="Girdi (stdin)" readOnly />
      <input placeholder="Beklenen cikti" readOnly />
    </div>
  ),
}));

vi.mock("@/services/api", () => ({
  getRubricByAssignment: vi.fn(async () => null),
  suggestRubric: vi.fn(),
  upsertRubric: vi.fn(),
  getQuestions: vi.fn(async () => []),
  createQuestion: vi.fn(),
  deleteQuestion: vi.fn(),
  getAssignmentQuestions: vi.fn(async () => []),
  updateAssignmentQuestions: vi.fn(),
  getAssignmentTestCases: vi.fn(async () => []),
}));

describe("RubricModal assignment tests tab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test("renders TestCaseEditor in the tests tab", async () => {
    render(
      <RubricModal
        assignment={{ id: "assignment-1", name: "Kare", description: "Sayinin karesini yazdir." }}
        open
        onClose={() => undefined}
      />,
    );

    await waitFor(() => expect(screen.getByText(/Testler/)).toBeInTheDocument());
    fireEvent.click(screen.getByText(/Testler/));

    await waitFor(() => expect(screen.getByText("Manuel Test Ekle")).toBeInTheDocument());
    expect(screen.getByText("AI Test Oner")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Girdi (stdin)")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Beklenen cikti")).toBeInTheDocument();
  });
});
