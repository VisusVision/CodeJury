import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { apiFetch } from "../services/http";

export type AuthRole = "student" | "teacher";

export type AuthUser = Record<string, unknown>;

export type AuthState =
  | { status: "loading"; role: null; user: null }
  | { status: "anonymous"; role: null; user: null }
  | { status: "authenticated"; role: AuthRole; user: Record<string, unknown> };

export interface AuthContextValue extends AuthState {
  loginStudent: (studentNo: string, password: string) => Promise<Record<string, unknown>>;
  loginTeacher: (email: string, password: string) => Promise<Record<string, unknown>>;
  logout: () => Promise<void>;
  refreshSession: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

async function parseErrorDetail(response: Response, fallback: string): Promise<string> {
  const rawText = await response.text();
  if (!rawText.trim()) {
    return fallback;
  }
  try {
    const parsed = JSON.parse(rawText) as { detail?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail.trim()) {
      return parsed.detail.trim();
    }
  } catch {
    // Fall through to the raw text below.
  }
  return rawText.trim() || fallback;
}

export function AuthProvider({ children }: { children: React.ReactNode }): JSX.Element {
  const [state, setState] = useState<AuthState>({
    status: "loading",
    role: null,
    user: null,
  });

  const restoreSession = useCallback(async () => {
    try {
      const response = await apiFetch("/api/auth/me");
      if (response.ok) {
        const body = (await response.json()) as { role?: AuthRole; user?: Record<string, unknown> };
        if (body.role === "student" || body.role === "teacher") {
          setState({
            status: "authenticated",
            role: body.role,
            user: body.user ?? {},
          });
          return;
        }
      }
    } catch {
      // Treat network failures as anonymous.
    }
    setState({ status: "anonymous", role: null, user: null });
  }, []);

  useEffect(() => {
    void restoreSession();
  }, [restoreSession]);

  const loginStudent = useCallback(async (studentNo: string, password: string) => {
    const response = await apiFetch("/api/student/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ student_no: studentNo, password }),
    });
    if (!response.ok) {
      throw new Error(await parseErrorDetail(response, "Öğrenci girişi başarısız"));
    }
    const user = (await response.json()) as Record<string, unknown>;
    setState({ status: "authenticated", role: "student", user });
    return user;
  }, []);

  const loginTeacher = useCallback(async (email: string, password: string) => {
    const response = await apiFetch("/api/teacher/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!response.ok) {
      throw new Error(await parseErrorDetail(response, "Öğretmen girişi başarısız"));
    }
    const user = (await response.json()) as Record<string, unknown>;
    setState({ status: "authenticated", role: "teacher", user });
    return user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiFetch("/api/auth/logout", { method: "POST" });
    } catch {
      // Logout is best-effort from the client's perspective.
    }
    setState({ status: "anonymous", role: null, user: null });
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      ...state,
      loginStudent,
      loginTeacher,
      logout,
      refreshSession: restoreSession,
    }),
    [state, loginStudent, loginTeacher, logout, restoreSession],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
