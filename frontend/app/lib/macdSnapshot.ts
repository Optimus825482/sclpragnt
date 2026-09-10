// MACD MONITOR snapshot birleştirme (tek kaynak).
//
// Backend iki modda yayın yapar (B9):
//   - `macd_monitor`       → TAM snapshot (evren/ayar değişimi + her 5. pass)
//   - `macd_monitor_delta` → yalnızca DEĞİŞEN sembol satırları (küçük gövde)
//
// Delta mesajı tam snapshot DEĞİLDİR; tek başına kullanılırsa evrenin geri
// kalanı kaybolur. Tüketen her sayfa `mergeMacdDelta` ile mevcut görünümün
// üzerine yazmalıdır — aksi halde panel yalnızca her 5. saniyede tazelenir.

export type MacdSnapshotLike = {
  universe?: string[];
  symbols?: Record<string, unknown>;
  timeframes?: string[];
  jump_min?: number;
  generated_at?: number;
};

/**
 * Delta yayınını mevcut snapshot'ın üzerine birleştir.
 *
 * Taban (prev) yoksa `null` döner: delta tek başına anlamlı değildir, tam
 * yayın ya da REST poll beklenmelidir. `null` dönüşü çağıranda "değişiklik
 * yok" olarak ele alınmalıdır.
 */
export const mergeMacdDelta = <T extends MacdSnapshotLike>(
  prev: T | null,
  incoming: unknown,
): T | null => {
  const patch = incoming as (MacdSnapshotLike & { symbols?: Record<string, unknown> }) | null | undefined;
  if (!patch?.symbols) return prev;
  if (!prev) return prev;
  return {
    ...prev,
    symbols: { ...(prev.symbols || {}), ...patch.symbols },
    universe: patch.universe?.length ? patch.universe : prev.universe,
    timeframes: patch.timeframes?.length ? patch.timeframes : prev.timeframes,
    jump_min: patch.jump_min ?? prev.jump_min,
    generated_at: patch.generated_at ?? prev.generated_at,
  };
};
