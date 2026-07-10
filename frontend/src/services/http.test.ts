import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import {
  CSRF_COOKIE_NAME,
  CSRF_HEADER_NAME,
  apiFetch,
  readCookie,
} from "./http";

function setDocumentCookie(value: string) {
  Object.defineProperty(document, "cookie", {
    writable: true,
    configurable: true,
    value,
  });
}

describe("apiFetch", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    setDocumentCookie("");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("adds credentials include to every request", async () => {
    await apiFetch("/api/health");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/health",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  test("adds csrf header on POST when csrf cookie present", async () => {
    setDocumentCookie(`${CSRF_COOKIE_NAME}=csrf-token-abc`);

    await apiFetch("/api/student/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ student_no: "1", password: "x" }),
    });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Headers;
    expect(headers.get(CSRF_HEADER_NAME)).toBe("csrf-token-abc");
    expect(init.credentials).toBe("include");
  });

  test("adds csrf header on PUT/PATCH/DELETE too", async () => {
    setDocumentCookie(`${CSRF_COOKIE_NAME}=csrf-token-xyz`);

    for (const method of ["PUT", "PATCH", "DELETE"] as const) {
      fetchMock.mockClear();
      await apiFetch("/api/resource", { method });
      const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Headers;
      expect(headers.get(CSRF_HEADER_NAME)).toBe("csrf-token-xyz");
    }
  });

  test("does not add csrf header on GET/HEAD/OPTIONS", async () => {
    setDocumentCookie(`${CSRF_COOKIE_NAME}=csrf-token-abc`);

    for (const method of ["GET", "HEAD", "OPTIONS"] as const) {
      fetchMock.mockClear();
      await apiFetch("/api/resource", { method });
      const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Headers;
      expect(headers.get(CSRF_HEADER_NAME)).toBeNull();
    }
  });

  test("does not add csrf header when csrf cookie is absent", async () => {
    setDocumentCookie("other=value");

    await apiFetch("/api/student/login", { method: "POST" });

    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Headers;
    expect(headers.get(CSRF_HEADER_NAME)).toBeNull();
  });

  test("preserves caller-provided headers like Content-Type", async () => {
    setDocumentCookie(`${CSRF_COOKIE_NAME}=csrf-token-abc`);

    await apiFetch("/api/student/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });

    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Headers;
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get(CSRF_HEADER_NAME)).toBe("csrf-token-abc");
  });

  test("preserves caller-provided signal and body", async () => {
    const controller = new AbortController();
    const body = JSON.stringify({ foo: "bar" });

    await apiFetch("/api/analyze", {
      method: "POST",
      body,
      signal: controller.signal,
      cache: "no-store",
    });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.signal).toBe(controller.signal);
    expect(init.body).toBe(body);
    expect(init.cache).toBe("no-store");
  });
});

describe("readCookie", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("readCookie returns null when cookie absent", () => {
    setDocumentCookie("other=value");
    expect(readCookie(CSRF_COOKIE_NAME)).toBeNull();
  });

  test("readCookie returns decoded value when cookie present among multiple cookies", () => {
    setDocumentCookie(
      `session=abc; ${CSRF_COOKIE_NAME}=${encodeURIComponent("token+value")}; ${CSRF_COOKIE_NAME}_extra=wrong`,
    );
    expect(readCookie(CSRF_COOKIE_NAME)).toBe("token+value");
    expect(readCookie(`${CSRF_COOKIE_NAME}_extra`)).toBe("wrong");
  });
});
