import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import TestCaseEditor from "./TestCaseEditor";

const toastError = vi.fn();
const toastSuccess = vi.fn();

vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

const getAssignmentTestCasesMock = vi.fn();
const replaceAssignmentTestCasesMock = vi.fn();
const suggestAssignmentTestCasesMock = vi.fn();
const getActiveGeneratedTestSetMock = vi.fn();
const promoteGeneratedTestsMock = vi.fn();

vi.mock("@/services/api", () => ({
  getAssignmentTestCases: (...args: unknown[]) => getAssignmentTestCasesMock(...args),
  replaceAssignmentTestCases: (...args: unknown[]) => replaceAssignmentTestCasesMock(...args),
  suggestAssignmentTestCases: (...args: unknown[]) => suggestAssignmentTestCasesMock(...args),
  getActiveGeneratedTestSet: (...args: unknown[]) => getActiveGeneratedTestSetMock(...args),
  promoteGeneratedTests: (...args: unknown[]) => promoteGeneratedTestsMock(...args),
}));

const assignment = { id: "assignment-1", name: "Kare", description: "Sayinin karesini yazdir." };

const facultyCase = {
  id: "tc-1",
  name: "Temel",
  stdin: "2\n",
  expected_stdout: "4\n",
  expected_exit_code: 0,
  visibility: "public" as const,
  files: [] as { name: string; content: string }[],
  source: "manual" as const,
  oracle: "teacher" as const,
};

const generatedSet = {
  id: "set-1",
  assignment_id: "assignment-1",
  cache_key: "abc",
  version: 1,
  difficulty: "medium" as const,
  cases: [
    {
      id: "gen-1",
      name: "Uretilen test",
      stdin: "3\n",
      expected_stdout: "9\n",
      expected_exit_code: 0,
      visibility: "hidden" as const,
      files: [],
      source: "auto_generated" as const,
      oracle: "llm_verified" as const,
    },
  ],
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
};

describe("TestCaseEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getAssignmentTestCasesMock.mockResolvedValue([facultyCase]);
    getActiveGeneratedTestSetMock.mockResolvedValue(generatedSet);
    replaceAssignmentTestCasesMock.mockImplementation(async (_id, rows) => rows);
    promoteGeneratedTestsMock.mockResolvedValue([facultyCase]);
    suggestAssignmentTestCasesMock.mockResolvedValue({
      suggestions: [
        {
          id: "draft-1",
          name: "AI taslak",
          stdin: "5\n",
          expected_stdout: "25\n",
          expected_exit_code: 0,
          visibility: "public",
          files: [],
          source: "auto_generated",
          oracle: "llm_verified",
        },
      ],
      verified_count: 1,
      difficulty: "medium",
      persisted: false,
    });
  });

  test("loads faculty tests and active generated set", async () => {
    render(<TestCaseEditor assignment={assignment} language="tr" onSaved={() => undefined} />);

    await waitFor(() => expect(screen.getByDisplayValue("Temel")).toBeInTheDocument());
    expect(getAssignmentTestCasesMock).toHaveBeenCalledWith("assignment-1");
    expect(getActiveGeneratedTestSetMock).toHaveBeenCalledWith("assignment-1");
    expect(screen.getByText("Uretilen test")).toBeInTheDocument();
  });

  test("adds and removes manual cases", async () => {
    render(<TestCaseEditor assignment={assignment} language="tr" onSaved={() => undefined} />);
    await waitFor(() => expect(screen.getByDisplayValue("Temel")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Manuel Test Ekle"));
    expect(screen.getAllByPlaceholderText("Test adi")).toHaveLength(2);

    const deleteButtons = screen.getAllByRole("button", { name: "Testi sil" });
    fireEvent.click(deleteButtons[deleteButtons.length - 1]);
    expect(screen.getAllByPlaceholderText("Test adi")).toHaveLength(1);
  });

  test("rejects unsafe fixture paths client-side", async () => {
    render(<TestCaseEditor assignment={assignment} language="tr" onSaved={() => undefined} />);
    await waitFor(() => expect(screen.getByDisplayValue("Temel")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Fixture Ekle"));
    const nameInput = screen.getByPlaceholderText("ornek: data/input.csv");
    fireEvent.change(nameInput, { target: { value: "../secret.txt" } });
    fireEvent.change(screen.getByPlaceholderText("Fixture icerigi"), { target: { value: "x" } });
    fireEvent.click(screen.getByText("Fixture Kaydet"));

    expect(toastError).toHaveBeenCalledWith(expect.stringMatching(/guvenli|izin/i));
  });

  test("keeps AI suggestions as drafts until explicitly added", async () => {
    render(<TestCaseEditor assignment={assignment} language="tr" onSaved={() => undefined} />);
    await waitFor(() => expect(screen.getByDisplayValue("Temel")).toBeInTheDocument());

    fireEvent.click(screen.getByText("AI Test Oner"));
    await waitFor(() => expect(screen.getByText("AI taslak")).toBeInTheDocument());
    expect(screen.getAllByPlaceholderText("Test adi")).toHaveLength(1);

    fireEvent.click(screen.getByLabelText("AI taslak"));
    fireEvent.click(screen.getByText("Secili Taslaklari Ekle"));
    expect(screen.getAllByPlaceholderText("Test adi")).toHaveLength(2);
    expect(screen.getByDisplayValue("AI taslak")).toBeInTheDocument();
  });

  test("promote append requires selected generated cases", async () => {
    render(<TestCaseEditor assignment={assignment} language="tr" onSaved={() => undefined} />);
    await waitFor(() => expect(screen.getByText("Uretilen test")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Uretilen Testleri Ekle"));
    expect(toastError).toHaveBeenCalledWith(expect.stringMatching(/sec/i));
    expect(promoteGeneratedTestsMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByLabelText("Uretilen test"));
    fireEvent.click(screen.getByText("Uretilen Testleri Ekle"));
    await waitFor(() =>
      expect(promoteGeneratedTestsMock).toHaveBeenCalledWith("assignment-1", "set-1", {
        case_ids: ["gen-1"],
        mode: "append",
      }),
    );
  });

  test("promote replace requires confirmation", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<TestCaseEditor assignment={assignment} language="tr" onSaved={() => undefined} />);
    await waitFor(() => expect(screen.getByText("Uretilen test")).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText("Degistir modu"));
    fireEvent.click(screen.getByLabelText("Uretilen test"));
    fireEvent.click(screen.getByText("Uretilen Testleri Degistir"));
    expect(confirmSpy).toHaveBeenCalled();
    expect(promoteGeneratedTestsMock).not.toHaveBeenCalled();

    confirmSpy.mockReturnValue(true);
    fireEvent.click(screen.getByText("Uretilen Testleri Degistir"));
    await waitFor(() =>
      expect(promoteGeneratedTestsMock).toHaveBeenCalledWith("assignment-1", "set-1", {
        case_ids: ["gen-1"],
        mode: "replace",
      }),
    );
    confirmSpy.mockRestore();
  });

  test("disables duplicate requests while loading", async () => {
    let resolveSuggest: (value: unknown) => void = () => undefined;
    suggestAssignmentTestCasesMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveSuggest = resolve;
        }),
    );

    render(<TestCaseEditor assignment={assignment} language="tr" onSaved={() => undefined} />);
    await waitFor(() => expect(screen.getByDisplayValue("Temel")).toBeInTheDocument());

    const aiButton = screen.getByText("AI Test Oner");
    fireEvent.click(aiButton);
    expect(aiButton).toBeDisabled();
    fireEvent.click(aiButton);
    expect(suggestAssignmentTestCasesMock).toHaveBeenCalledTimes(1);

    resolveSuggest({
      suggestions: [],
      verified_count: 0,
      difficulty: "medium",
      persisted: false,
    });
    await waitFor(() => expect(aiButton).not.toBeDisabled());
  });

  test("shows backend detail on 503 suggestion failure", async () => {
    suggestAssignmentTestCasesMock.mockRejectedValue(new Error("Test onerisi su an uretilemiyor."));
    render(<TestCaseEditor assignment={assignment} language="tr" onSaved={() => undefined} />);
    await waitFor(() => expect(screen.getByDisplayValue("Temel")).toBeInTheDocument());

    fireEvent.click(screen.getByText("AI Test Oner"));
    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith("Test onerisi su an uretilemiyor."),
    );
  });
});
