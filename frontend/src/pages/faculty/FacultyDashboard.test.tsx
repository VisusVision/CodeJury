import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import FacultyDashboard from "./FacultyDashboard";

const createAssignmentMock = vi.fn();
const updateAssignmentDifficultyMock = vi.fn();
const getAssignmentsMock = vi.fn();
const getCoursesMock = vi.fn();
const getDepartmentsMock = vi.fn();
const getRubricsMock = vi.fn();
const getEvaluationsMock = vi.fn();

const navigateMock = vi.fn();
const logoutMock = vi.fn();
const authUser = {
  id: "teacher-1",
  first_name: "Ayse",
  last_name: "Hoca",
  email: "ayse@example.com",
};

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateMock,
}));

vi.mock("@/i18n/LanguageContext", () => ({
  useTranslation: () => ({
    language: "tr",
    t: (key: string) => key,
  }),
  LanguageToggle: () => null,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/components/faculty/RubricModal", () => ({ default: () => null }));
vi.mock("@/components/faculty/AssignmentChatbot", () => ({ default: () => null }));
vi.mock("@/components/faculty/SettingsPanel", () => ({ default: () => null }));
vi.mock("@/components/faculty/StudentsPanel", () => ({ default: () => null }));
vi.mock("@/components/dashboard/RuntimeHealthBadge", () => ({ default: () => null }));

vi.mock("@/services/api", () => ({
  createAssignment: (...args: unknown[]) => createAssignmentMock(...args),
  updateAssignmentDifficulty: (...args: unknown[]) => updateAssignmentDifficultyMock(...args),
  getAssignments: (...args: unknown[]) => getAssignmentsMock(...args),
  getCourses: (...args: unknown[]) => getCoursesMock(...args),
  getDepartments: (...args: unknown[]) => getDepartmentsMock(...args),
  getRubrics: (...args: unknown[]) => getRubricsMock(...args),
  getEvaluations: (...args: unknown[]) => getEvaluationsMock(...args),
  createCourse: vi.fn(),
  createDepartment: vi.fn(),
  deleteAssignment: vi.fn(),
  deleteCourse: vi.fn(),
  deleteDepartment: vi.fn(),
  generateAssignmentExample: vi.fn(async () => ({ example: "" })),
  updateRubricStatusByAssignment: vi.fn(),
}));

vi.mock("../../auth/AuthContext", () => ({
  useAuth: () => ({
    status: "authenticated",
    role: "teacher",
    user: authUser,
    logout: logoutMock,
  }),
}));

describe("FacultyDashboard difficulty UI", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getDepartmentsMock.mockResolvedValue([]);
    getCoursesMock.mockResolvedValue([
      { id: "course-1", name: "Veri Yapilari", code: "CSE201", class_year: 2 },
    ]);
    getAssignmentsMock.mockResolvedValue([
      {
        id: "assignment-1",
        name: "Kare",
        description: "Sayinin karesini yazdir.",
        course_id: "course-1",
        due_date: null,
        difficulty: "medium",
        difficulty_source: "default",
      },
    ]);
    getRubricsMock.mockResolvedValue([]);
    getEvaluationsMock.mockResolvedValue([]);
    createAssignmentMock.mockResolvedValue({
      id: "assignment-new",
      name: "Fibonacci",
      course_id: "course-1",
      description: null,
      difficulty: "hard",
      difficulty_source: "teacher",
    });
    updateAssignmentDifficultyMock.mockResolvedValue({
      id: "assignment-1",
      name: "Kare",
      course_id: "course-1",
      description: "Sayinin karesini yazdir.",
      difficulty: "hard",
      difficulty_source: "teacher",
    });
  });

  test("manual create defaults to medium and sends explicit teacher difficulty", async () => {
    render(<FacultyDashboard />);

    await waitFor(() => expect(screen.queryByText("common.loading")).not.toBeInTheDocument());
    fireEvent.click(screen.getByText("faculty.tabs.assignments"));
    await waitFor(() => expect(screen.getByText("Kare")).toBeInTheDocument());

    const difficultySelect = screen.getByLabelText("Zorluk");
    expect((difficultySelect as HTMLSelectElement).value).toBe("medium");

    fireEvent.change(screen.getByLabelText("Ders secimi"), { target: { value: "course-1" } });
    fireEvent.change(screen.getByPlaceholderText("chatbot.assignmentTitle"), {
      target: { value: "Fibonacci" },
    });
    fireEvent.change(difficultySelect, { target: { value: "hard" } });

    const createButtons = screen.getAllByText("faculty.assignments.create");
    fireEvent.click(createButtons[createButtons.length - 1]);

    await waitFor(() => expect(createAssignmentMock).toHaveBeenCalled());
    expect(createAssignmentMock).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Fibonacci",
        course_id: "course-1",
        difficulty: "hard",
        creation_mode: "manual",
      }),
    );
  });

  test("shows difficulty source label and owner can update difficulty", async () => {
    render(<FacultyDashboard />);

    await waitFor(() => expect(screen.queryByText("common.loading")).not.toBeInTheDocument());
    fireEvent.click(screen.getByText("faculty.tabs.assignments"));
    await waitFor(() => expect(screen.getByText("Varsayılan")).toBeInTheDocument());

    const editSelect = screen.getByLabelText(/Zorluk duzenle Kare/i);
    fireEvent.change(editSelect, { target: { value: "hard" } });

    await waitFor(() => expect(updateAssignmentDifficultyMock).toHaveBeenCalledWith("assignment-1", "hard"));
    await waitFor(() => expect(screen.getByText("Öğretmen")).toBeInTheDocument());
  });
});
