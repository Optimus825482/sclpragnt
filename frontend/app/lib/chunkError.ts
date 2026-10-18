/**
 * Deploy sonrası bayat sayfa: eski HTML'in istediği JS parçası (chunk) artık sunucuda yok.
 * Bu hatada yapılacak en doğru şey sayfayı BİR KEZ yenilemektir.
 */
const CHUNK_PATTERNS = [
  /Loading chunk [\w./-]+ failed/i,
  /Loading CSS chunk [\w./-]+ failed/i,
  /ChunkLoadError/i,
  /Failed to fetch dynamically imported module/i,
  /error loading dynamically imported module/i,
  /Importing a module script failed/i,
];

export function isChunkLoadError(error: unknown): boolean {
  if (!error) return false;
  const name = typeof error === "object" && "name" in error ? String((error as { name?: unknown }).name) : "";
  const message = typeof error === "object" && "message" in error
    ? String((error as { message?: unknown }).message)
    : String(error);
  return name === "ChunkLoadError" || CHUNK_PATTERNS.some((pattern) => pattern.test(message));
}

const RELOAD_KEY = "scalper_chunk_reload_at";
/** Aynı oturumda ikinci otomatik yenilemeye izin verilmeden önceki bekleme (döngü koruması). */
export const CHUNK_RELOAD_COOLDOWN_MS = 60_000;

type StorageLike = Pick<Storage, "getItem" | "setItem">;

/**
 * Otomatik yenileme yapılmalı mı? Son yenilemeden bu yana `CHUNK_RELOAD_COOLDOWN_MS` geçmediyse
 * HAYIR (gerçekten eksik bir parça varsa sonsuz yenileme döngüsüne girmesin). Evet ise zamanı kaydeder.
 */
export function claimChunkReload(storage: StorageLike | null, now = Date.now()): boolean {
  if (!storage) return false;
  try {
    const last = Number(storage.getItem(RELOAD_KEY));
    if (Number.isFinite(last) && last > 0 && now - last < CHUNK_RELOAD_COOLDOWN_MS) return false;
    storage.setItem(RELOAD_KEY, String(now));
    return true;
  } catch {
    return false;
  }
}

/** Chunk hatasıysa ve izin varsa sayfayı yeniler; yenileme başlatıldıysa true. */
export function reloadForChunkError(error: unknown): boolean {
  if (typeof window === "undefined" || !isChunkLoadError(error)) return false;
  let storage: Storage | null = null;
  try { storage = window.sessionStorage; } catch { storage = null; }
  if (!claimChunkReload(storage)) return false;
  window.location.reload();
  return true;
}
