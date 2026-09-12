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

/** Yüzeysel (bir seviye) derin karşılaştırma: JSON benzeri değerler yeterli. */
const sameValue = (a: unknown, b: unknown): boolean => {
  if (a === b) return true;
  if (a == null || b == null) return false;
  if (typeof a !== "object" || typeof b !== "object") return false;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((value, index) => sameValue(value, b[index]));
  }
  const left = a as Record<string, unknown>;
  const right = b as Record<string, unknown>;
  const keys = Object.keys(left);
  if (keys.length !== Object.keys(right).length) return false;
  return keys.every((key) => sameValue(left[key], right[key]));
};

const sameArray = (a: unknown, b: unknown): boolean =>
  Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((value, index) => value === b[index]);

/**
 * Delta yayınını mevcut snapshot'ın üzerine birleştir.
 *
 * SÖZLEŞME (R1-05) — referans kararlılığı:
 *   - Taban (prev) yoksa ya da delta boşsa `prev` AYNEN döner (`null` dahil).
 *   - Delta'nın sembol satırları ile mevcut satırlar İÇERİK olarak aynıysa ve
 *     `universe`/`timeframes`/`jump_min` değişmediyse YİNE `prev` döner. Böylece
 *     tüketici (bkz. monitoring sayfası `useMemo(..., [macdData])`) aynı veri için
 *     boşuna yeniden hesaplamaz; backend her ~1 sn'de tetiklediği delta turu,
 *     "değişiklik yok" durumunda istemcide TAM evren yeniden hesabı üretmez.
 *   - Yalnız gerçekten bir alan değiştiğinde yeni bir üst-düzey nesne üretilir;
 *     DEĞİŞMEYEN sembol satırları yeni nesneye AYNI referansla taşınır (satır
 *     bazlı memo/`React.memo` alt bileşenleri gereksiz render etmez).
 *   - `generated_at` yalnız bir değişiklik tespit edildiğinde taşınır; tek başına
 *     zaman damgası artışı "değişiklik" SAYILMAZ (aksi halde her delta yeni nesne
 *     üretir ve memoizasyon ölürdü).
 */
export const mergeMacdDelta = <T extends MacdSnapshotLike>(
  prev: T | null,
  incoming: unknown,
): T | null => {
  const patch = incoming as (MacdSnapshotLike & { symbols?: Record<string, unknown> }) | null | undefined;
  if (!patch?.symbols) return prev;
  if (!prev) return prev;

  const prevSymbols = prev.symbols || {};
  const nextSymbols: Record<string, unknown> = { ...prevSymbols };
  let changed = false;
  for (const [symbol, row] of Object.entries(patch.symbols)) {
    if (!sameValue(prevSymbols[symbol], row)) {
      nextSymbols[symbol] = row;
      changed = true;
    }
  }

  const nextUniverse = patch.universe?.length ? patch.universe : prev.universe;
  const nextTimeframes = patch.timeframes?.length ? patch.timeframes : prev.timeframes;
  const nextJumpMin = patch.jump_min ?? prev.jump_min;
  const metaChanged =
    !sameArray(nextUniverse, prev.universe) ||
    !sameArray(nextTimeframes, prev.timeframes) ||
    !Object.is(nextJumpMin, prev.jump_min);

  if (!changed && !metaChanged) return prev;

  return {
    ...prev,
    symbols: nextSymbols,
    universe: nextUniverse,
    timeframes: nextTimeframes,
    jump_min: nextJumpMin,
    generated_at: patch.generated_at ?? prev.generated_at,
  };
};
