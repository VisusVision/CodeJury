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
  replaceAssignmentTestCases: vi.fn(async (_assignmentId, rows) => rows),
  suggestAssignmentTestCases: vi.fn(async () => [
    {
      name: "AI sample",
      stdin: "3\n",
      expected_stdout: "9\n",
      visibility: "public",
      source: "ai",
    },
  ]),
}));

describe("RubricModal assignment tests tab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test("shows manual and AI assignment test controls", async () => {
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
    fireEvent.click(screen.getByText("Manuel Test Ekle"));
    expect(screen.getByPlaceholderText("Girdi (stdin)")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Beklenen cikti")).toBeInTheDocument();
  });
});
