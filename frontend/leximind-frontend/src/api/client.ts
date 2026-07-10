// Thin fetch wrapper: injects the auth token, parses JSON, and turns non-2xx responses
// into a typed ApiError carrying the backend's `detail` message so the UI can show it.

export const API_BASE = "http://127.0.0.1:8000";

const TOKEN_KEY = "leximind_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  auth?: boolean; // attach bearer token (default true)
  signal?: AbortSignal;
}

export async function apiRequest<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, auth = true, signal } = opts;
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });

  if (res.status === 204) return undefined as T;

  let data: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!res.ok) {
    const detail =
      (data && typeof data === "object" && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : null) || `Request failed (${res.status})`;
    throw new ApiError(res.status, detail);
  }
  return data as T;
}
