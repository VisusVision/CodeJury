import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import SettingsPanel from "./SettingsPanel";

const translate = (key: string) => key;
const logoutMock = vi.fn(async () => undefined);
const navigateMock = vi.fn();

vi.mock("@/i18n/LanguageContext", () => ({
  useTranslation: () => ({
    language: "tr",
    t: translate,
  }),
}));

vi.mock("../../auth/AuthContext", () => ({
  useAuth: () => ({
    refreshSession: vi.fn(),
    logout: logoutMock,
  }),
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateMock,
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const updateTeacherPasswordMock = vi.fn();

vi.mock("@/services/api", () => ({
  updateTeacherEmail: vi.fn(),
  updateTeacherPassword: (...args: unknown[]) => updateTeacherPasswordMock(...args),
}));

const teacher = {
  id: "teacher-1",
  first_name: "Ayse",
  last_name: "Yilmaz",
  email: "ayse@example.com",
};

describe("SettingsPanel password change", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    updateTeacherPasswordMock.mockResolvedValue(undefined);
  });

  test("password change success calls logout and navigates to /login", async () => {
    render(<SettingsPanel teacher={teacher} onTeacherUpdate={() => undefined} />);

    fireEvent.change(screen.getByPlaceholderText("faculty.settings.currentPasswordPlaceholder"), {
      target: { value: "old-pass" },
    });
    fireEvent.change(screen.getByPlaceholderText("faculty.settings.newPasswordPlaceholder"), {
      target: { value: "new-pass" },
    });
    fireEvent.change(screen.getByPlaceholderText("faculty.settings.confirmPasswordPlaceholder"), {
      target: { value: "new-pass" },
    });
    fireEvent.click(screen.getByText("faculty.settings.updatePasswordBtn"));

    await waitFor(() => {
      expect(updateTeacherPasswordMock).toHaveBeenCalledWith("teacher-1", {
        current_password: "old-pass",
        new_password: "new-pass",
      });
    });
    await waitFor(() => {
      expect(logoutMock).toHaveBeenCalledTimes(1);
    });
    expect(navigateMock).toHaveBeenCalledWith("/login");
  });

  test("password change failure does not call logout or navigate", async () => {
    updateTeacherPasswordMock.mockRejectedValue(new Error("Wrong password"));

    render(<SettingsPanel teacher={teacher} onTeacherUpdate={() => undefined} />);

    fireEvent.change(screen.getByPlaceholderText("faculty.settings.currentPasswordPlaceholder"), {
      target: { value: "old-pass" },
    });
    fireEvent.change(screen.getByPlaceholderText("faculty.settings.newPasswordPlaceholder"), {
      target: { value: "new-pass" },
    });
    fireEvent.change(screen.getByPlaceholderText("faculty.settings.confirmPasswordPlaceholder"), {
      target: { value: "new-pass" },
    });
    fireEvent.click(screen.getByText("faculty.settings.updatePasswordBtn"));

    await waitFor(() => {
      expect(updateTeacherPasswordMock).toHaveBeenCalled();
    });
    expect(logoutMock).not.toHaveBeenCalled();
    expect(navigateMock).not.toHaveBeenCalled();
  });
});
