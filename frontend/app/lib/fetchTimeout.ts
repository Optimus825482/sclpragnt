/**
 * Zaman aşımlı fetch. Mobilde "lie-fi" (bağlantı var, veri yok) durumunda istek sonsuza dek
 * asılı kalabilir; arayüz yükleniyor halinde takılır. Zamanlayıcı yalnız YANIT BAŞLIKLARI
 * gelene kadar işler (gövde okuması/akış etkilenmez).
 */

/** GET/HEAD okumaları için varsayılan üst sınır. Yavaş okuma uçlarını (tarama/rapor) kesmeyecek kadar cömert. */
export const DEFAULT_GET_TIMEOUT_MS = 45_000;

export function makeTimeoutError(timeoutMs: number): Error {
  const error = new Error(`İstek zaman aşımına uğradı (${Math.round(timeoutMs / 1000)} sn)`);
  error.name = "TimeoutError";
  return error;
}

export function isTimeoutError(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as { name?: unknown }).name === "TimeoutError";
}

export function fetchWithTimeout(
  fetchImpl: typeof fetch,
  input: RequestInfo | URL,
  init: RequestInit | undefined,
  timeoutMs: number | undefined,
): Promise<Response> {
  if (!timeoutMs || timeoutMs <= 0 || typeof AbortController === "undefined") return fetchImpl(input, init);
  const controller = new AbortController();
  const outer = init?.signal ?? null;
  const onOuterAbort = () => controller.abort();
  if (outer) {
    if (outer.aborted) controller.abort();
    else outer.addEventListener("abort", onOuterAbort, { once: true });
  }
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  const cleanup = () => {
    clearTimeout(timer);
    outer?.removeEventListener("abort", onOuterAbort);
  };
  return fetchImpl(input, { ...init, signal: controller.signal }).then(
    (response) => { cleanup(); return response; },
    (error) => {
      cleanup();
      // Çağıranın kendi iptali AbortError olarak kalır; zaman aşımı ayırt edilebilir olsun.
      throw timedOut ? makeTimeoutError(timeoutMs) : error;
    },
  );
}
