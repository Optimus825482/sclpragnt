/**
 * Kurulu uygulamanın (açık sekmenin) derleme kimliği ile sunucudaki güncel kimliği kıyaslar.
 * Saf yardımcılar: "Yeni sürüm var" şeridi ve testler bunları kullanır.
 */
export const CURRENT_BUILD = process.env.NEXT_PUBLIC_BUILD_ID || "dev";

/** Geliştirmede ("dev") ve boş kimliklerde şerit gösterilmez. */
export function shouldOfferUpdate(current: string, remote: string | null | undefined): boolean {
  if (!remote || !current) return false;
  if (current === "dev" || remote === "dev") return false;
  return current !== remote;
}

/**
 * Sunucudaki derleme kimliğini okur. Ağ hatası/zaman aşımı/bozuk yanıt → null
 * (şerit bu durumda gösterilmez; yanlış alarm vermek yerine sessiz kalır).
 */
export async function fetchRemoteBuild(
  fetchImpl: typeof fetch = fetch,
  timeoutMs = 8000,
): Promise<string | null> {
  const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
  try {
    const response = await fetchImpl("/build-id.json", {
      cache: "no-store",
      credentials: "same-origin",
      signal: controller?.signal,
    });
    if (!response.ok) return null;
    const body = (await response.json()) as { build?: unknown };
    return typeof body?.build === "string" && body.build ? body.build : null;
  } catch {
    return null;
  } finally {
    if (timer) clearTimeout(timer);
  }
}
