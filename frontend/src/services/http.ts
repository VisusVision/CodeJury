export const SESSION_COOKIE_NAME = "agentgrade_session";
export const CSRF_COOKIE_NAME = "agentgrade_csrf";
export const CSRF_HEADER_NAME = "X-CSRF-Token";
export const UNAUTHORIZED_EVENT = "agentgrade:unauthorized";

export function readCookie(name: string): string | null {
  const cookies = document.cookie ? document.cookie.split("; ") : [];
  for (const cookie of cookies) {
    const separatorIndex = cookie.indexOf("=");
    if (separatorIndex === -1) {
      continue;
    }
    const cookieName = cookie.slice(0, separatorIndex);
    if (cookieName === name) {
      return decodeURIComponent(cookie.slice(separatorIndex + 1));
    }
  }
  return null;
}

export async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
  const headers = new Headers(init.headers);
  if (!SAFE_METHODS.has(method)) {
    const csrf = readCookie(CSRF_COOKIE_NAME);
    if (csrf) {
      headers.set(CSRF_HEADER_NAME, csrf);
    }
  }
  const response = await fetch(input, { ...init, method, headers, credentials: "include" });
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
  }
  return response;
}
