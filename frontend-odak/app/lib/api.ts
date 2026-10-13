/**
 * Odak UI — merkezî API istemcisi.
 *
 * ANA FARK (mevcut `frontend/lib/api.ts`'ten): istekler MUTLAK backend adresine
 * değil, kendi origin'e (`/api/...`) gider. Next.js `next.config.js` rewrite'ı
 * bunları `BACKEND_ORIGIN`'e proxy'ler. Böylece:
 *   - CORS gerekmez (tarayıcı çapraz köken isteği görmez),
 *   - oturum cookie'si bu origin'de saklanır/gönderilir.
 *
 * Geliştirmede farklı bir backend'e (örn. uzak) bağlanmak istersen
 * `NEXT_PUBLIC_API_URL` ile mutlak taban verebilirsin; boşken same-origin.
 */
const base = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "");

export const API_BASE = base;
export const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL ||
  `${base || (typeof window !== "undefined" ? window.location.origin : "")}`
    .replace(/^http/, "ws")
    .replace(/\/$/, "") + "/ws";

/**
 * Tüm istekler `credentials: "include"` ile gider (oturum cookie'si için) ve
 * 401'de `odak:auth-expired` olayı yayınlanır → kabuk giriş ekranına döner.
 */
export function apiRequest(input: RequestInfo | URL, init?: RequestInit) {
  const method = String(init?.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
  const url = input instanceof Request ? input.url : String(input);
  const merged: RequestInit = { credentials: "include", ...init };
  if ((method === "GET" || method === "HEAD") && merged.cache === undefined) {
    merged.cache = "no-store";
  }
  return fetch(input, merged).then((response) => {
    const isLoginPost = method === "POST" && url.includes("/auth/login");
    if (response.status === 401 && typeof window !== "undefined" && !isLoginPost) {
      window.dispatchEvent(new CustomEvent("odak:auth-expired"));
    }
    return response;
  });
}

/** JSON döndüren uçlar için yardımcı: HTTP hatasını Error olarak fırlatır. */
export async function getJSON<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiRequest(`${API_BASE}${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    let detail = "";
    try {
      const body = await response.json();
      detail = typeof body?.detail === "string" ? body.detail : "";
    } catch {
      /* gövde JSON olmayabilir */
    }
    throw new Error(detail || `API ${response.status}`);
  }
  return response.json() as Promise<T>;
}
