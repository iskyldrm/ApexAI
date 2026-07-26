/** Single fetch wrapper that talks to the FastAPI backend.
 *  Uses Next.js rewrites so cookies flow through the browser.
 */
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
  }
}

export async function apiFetch<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const url = `${API_BASE}/api/v1${path}`;
  const res = await fetch(url, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      // ignore
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}
