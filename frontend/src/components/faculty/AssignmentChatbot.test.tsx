import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import AssignmentChatbot from "./AssignmentChatbot";

const createAssignmentMock = vi.fn();
const fetchAssignmentSuggestionsMock = vi.fn();
const generateAssignmentExampleMock = vi.fn();

vi.mock("@/i18n/LanguageContext", () => ({
  useTranslation: () => ({
    language: "tr",
    t: (key: string) => key,
  }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/components/ui/calendar", () => ({
  Calendar: ({ onSelect }: { onSelect?: (date: Date | undefined) => void }) => (
    <button type="button" onClick={() => onSelect?.(new Date("2026-12-31T12:00:00"))}>
      pick-date
    </button>
  ),
}));

vi.mock("@/components/ui/popover", () => ({
  Popover: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PopoverTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  PopoverContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/services/api", () => ({
  createAssignment: (...args: unknown[]) => createAssignmentMock(...args),
  fetchAssignmentSuggestions: (...args: unknown[]) => fetchAssignmentSuggestionsMock(...args),
  generateAssignmentExample: (...args: unknown[]) => generateAssignmentExampleMock(...args),
}));

const courses = [
  { id: "course-1", name: "Veri Yapilari", code: "CSE201", class_year: 2 },
];

describe("AssignmentChatbot difficulty persistence", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    HTMLElement.prototype.scrollTo = vi.fn();
    fetchAssignmentSuggestionsMock.mockResolvedValue({
      suggestions: [
        {
          id: "s-1",
          title: "Kare Hesaplayici",
          summary: "Sayinin karesini yazdir.",
          description: "Kullanicidan sayi alip karesini yazdir.",
        },
      ],
    });
    generateAssignmentExampleMock.mockResolvedValue({ example: "4" });
    createAssignmentMock.mockResolvedValue({ id: "assignment-1" });
  });

  test("passes selected difficulty and ai_assistant creation mode on confirm", async () => {
    render(
      <AssignmentChatbot
        open
        onClose={() => undefined}
        courses={courses}
        teacherId="teacher-1"
        onCreated={() => undefined}
      />,
    );

    fireEvent.click(screen.getByText(/Veri Yapilari/));

    const hintInput = screen.getByRole("textbox");
    fireEvent.change(hintInput, { target: { value: "kare hesabi" } });
    fireEvent.keyDown(hintInput, { key: "Enter" });

    await waitFor(() => expect(screen.getByText("chatbot.difficultyTitle")).toBeInTheDocument());
    fireEvent.click(screen.getByText("chatbot.hard"));

    await waitFor(() => expect(fetchAssignmentSuggestionsMock).toHaveBeenCalledWith(
      expect.any(String),
      5,
      "hard",
      false,
      "tr",
    ));

    await waitFor(() => expect(screen.getByText("Kare Hesaplayici")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Kare Hesaplayici"));
    fireEvent.click(screen.getByText("chatbot.approve"));

    fireEvent.click(await screen.findByText("pick-date"));
    fireEvent.click(await screen.findByText("common.continue"));
    fireEvent.click(await screen.findByText("chatbot.yesConfirmBtn"));

    await waitFor(() => expect(createAssignmentMock).toHaveBeenCalled());
    expect(createAssignmentMock).toHaveBeenCalledWith(
      expect.objectContaining({
        course_id: "course-1",
        difficulty: "hard",
        creation_mode: "ai_assistant",
      }),
    );
  });
});
