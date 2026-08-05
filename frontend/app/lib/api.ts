const browserOrigin = typeof window !== "undefined"
  ? (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
    ? "http://localhost:8004"
    : window.location.origin)
  : "http://localhost:8004";
export const API_BASE = process.env.NEXT_PUBLIC_API_URL || browserOrigin;
export const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || API_BASE.replace(/^http/, "ws");

export async function apiFetch(path: string, init?: RequestInit) {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init });
  if (!response.ok) throw new Error(`API ${response.status}`);
  return response.json();
}
