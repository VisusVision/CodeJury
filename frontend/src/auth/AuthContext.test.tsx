import { render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { UNAUTHORIZED_EVENT } from "../services/http";
import { AuthProvider, useAuth } from "./AuthContext";

function AuthHarness() {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="status">{auth.status}</span>
      <span data-testid="role">{auth.role ?? "none"}</span>
      <span data-testid="user">{auth.user ? JSON.stringify(auth.user) : "none"}</span>
    </div>
  );
}

describe("AuthProvider", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("starts in loading state then restores authenticated session from /api/auth/me", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        role: "student",
        user: { student_no: "12345", first_name: "Ali" },
      }),
    });

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    expect(screen.getByTestId("status").textContent).toBe("loading");

    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("authenticated");
    });
    expect(screen.getByTestId("role").textContent).toBe("student");
    expect(screen.getByTestId("user").textContent).toContain("12345");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/me",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  test("restores to anonymous state when /api/auth/me returns 401", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
    });

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("anonymous");
    });
    expect(screen.getByTestId("role").textContent).toBe("none");
    expect(screen.getByTestId("user").textContent).toBe("none");
  });

  test("loginStudent sets authenticated student state on success", async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: false, status: 401 })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ student_no: "99999", first_name: "Ayse" }),
      });

    function LoginHarness() {
      const auth = useAuth();
      return (
        <div>
          <span data-testid="status">{auth.status}</span>
          <button
            type="button"
            onClick={() => {
              void auth.loginStudent("99999", "secret");
            }}
          >
            login
          </button>
        </div>
      );
    }

    render(
      <AuthProvider>
        <LoginHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("anonymous");
    });

    screen.getByRole("button", { name: "login" }).click();

    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("authenticated");
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/student/login",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: JSON.stringify({ student_no: "99999", password: "secret" }),
      }),
    );
  });

  test("loginTeacher sets authenticated teacher state on success", async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: false, status: 401 })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ email: "teacher@example.com", first_name: "Mehmet" }),
      });

    function LoginHarness() {
      const auth = useAuth();
      return (
        <div>
          <span data-testid="status">{auth.status}</span>
          <button
            type="button"
            onClick={() => {
              void auth.loginTeacher("teacher@example.com", "secret");
            }}
          >
            login
          </button>
        </div>
      );
    }

    render(
      <AuthProvider>
        <LoginHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("anonymous");
    });

    screen.getByRole("button", { name: "login" }).click();

    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("authenticated");
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/teacher/login",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: JSON.stringify({ email: "teacher@example.com", password: "secret" }),
      }),
    );
  });

  test("login failure throws and does not change auth state", async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: false, status: 401 })
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        text: async () => JSON.stringify({ detail: "Invalid credentials" }),
      });

    const { result } = renderHook(() => useAuth(), {
      wrapper: AuthProvider,
    });

    await waitFor(() => {
      expect(result.current.status).toBe("anonymous");
    });

    await expect(result.current.loginStudent("bad", "bad")).rejects.toThrow("Invalid credentials");
    expect(result.current.status).toBe("anonymous");
  });

  test("logout clears state to anonymous even if the network call fails", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ role: "teacher", user: { email: "t@example.com" } }),
      })
      .mockRejectedValueOnce(new Error("network down"));

    const { result } = renderHook(() => useAuth(), {
      wrapper: AuthProvider,
    });

    await waitFor(() => {
      expect(result.current.status).toBe("authenticated");
    });

    await result.current.logout();

    expect(result.current.status).toBe("anonymous");
    expect(result.current.role).toBeNull();
    expect(result.current.user).toBeNull();
  });

  test("useAuth throws when used outside AuthProvider", () => {
    expect(() => renderHook(() => useAuth())).toThrow("useAuth must be used within an AuthProvider");
  });

  test("clears auth state to anonymous when UNAUTHORIZED_EVENT fires, without a new /api/auth/me call", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        role: "teacher",
        user: { email: "teacher@example.com", first_name: "Mehmet" },
      }),
    });

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("authenticated");
    });

    const fetchCallsAfterRestore = fetchMock.mock.calls.length;

    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));

    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("anonymous");
    });
    expect(screen.getByTestId("role").textContent).toBe("none");
    expect(screen.getByTestId("user").textContent).toBe("none");
    expect(fetchMock.mock.calls.length).toBe(fetchCallsAfterRestore);
  });
});
