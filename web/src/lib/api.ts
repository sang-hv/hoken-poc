export class ApiError extends Error {
  status: number;
  code: string;
  detail: Record<string, unknown>;

  constructor(status: number, detail: Record<string, unknown>) {
    super(String(detail.code ?? `http_${status}`));
    this.status = status;
    this.code = String(detail.code ?? `http_${status}`);
    this.detail = detail;
  }
}

type Body = Record<string, unknown> | unknown[] | FormData | undefined;

async function request<T>(method: string, path: string, body?: Body): Promise<T> {
  const headers: Record<string, string> = { "X-Requested-With": "hoken" };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(`/api${path}`, { method, headers, body: payload, credentials: "same-origin" });
  if (!res.ok) {
    let detail: Record<string, unknown> = {};
    try {
      const j = await res.json();
      detail = typeof j.detail === "object" && j.detail ? j.detail : { code: String(j.detail ?? "") };
    } catch {
      detail = {};
    }
    if (res.status === 401 && !location.pathname.startsWith("/login") && !location.pathname.startsWith("/setup")) {
      window.dispatchEvent(new CustomEvent("hoken:unauthorized"));
    }
    throw new ApiError(res.status, detail);
  }
  const ct = res.headers.get("content-type") ?? "";
  return (ct.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: Body) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body?: Body) => request<T>("PUT", path, body ?? {}),
  patch: <T>(path: string, body?: Body) => request<T>("PATCH", path, body ?? {}),
  del: <T>(path: string) => request<T>("DELETE", path),
};
