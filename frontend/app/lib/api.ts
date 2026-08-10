const browserOrigin = typeof window !== "undefined"
  ? (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
    ? "http://localhost:8004"
    : window.location.origin)
  : "http://localhost:8004";
export const API_BASE = process.env.NEXT_PUBLIC_API_URL || browserOrigin;
export const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || API_BASE.replace(/^http/, "ws");

export const WS_URL = `${WS_BASE.replace(/\/$/, "")}/ws`;

export function apiRequest(input: RequestInfo | URL, init?: RequestInit) {
  return fetch(input, { ...init, credentials: "include" }).then((response) => {
    if (response.status === 401 && typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("scalper:auth-expired"));
    }
    return response;
  });
}

export async function apiFetch(path: string, init?: RequestInit) {
  const response = await apiRequest(`${API_BASE}${path}`, { cache: "no-store", ...init });
  if (!response.ok) throw new Error(`API ${response.status}`);
  return response.json();
}

type PageResponse<T> = Record<string, unknown> & {
  limit?: number;
  offset?: number;
};

export async function fetchAllPages<T>(
  path: string,
  key: string,
  options: { pageSize?: number; maxRows?: number } = {},
): Promise<{ rows: T[]; complete: boolean }> {
  const pageSize = options.pageSize ?? 200;
  const maxRows = options.maxRows ?? 10_000;
  const rows: T[] = [];
  const seenIds = new Set<unknown>();
  let offset = 0;
  while (rows.length < maxRows) {
    const separator = path.includes("?") ? "&" : "?";
    const data = await apiFetch(
      `${path}${separator}limit=${pageSize}&offset=${offset}`,
    ) as PageResponse<T>;
    const page = Array.isArray(data[key]) ? data[key] as T[] : [];
    for (const item of page) {
      const id = typeof item === "object" && item !== null ? (item as Record<string, unknown>).id : undefined;
      if (id !== undefined && seenIds.has(id)) continue;
      if (id !== undefined) seenIds.add(id);
      rows.push(item);
    }
    if (page.length < pageSize) return { rows, complete: true };
    offset += page.length;
  }
  return { rows, complete: false };
}
