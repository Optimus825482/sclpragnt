// ML olasılık gösterimi — TEK KAYNAK (2026-09-14).
//
// Kanıt: `ml_hit_probability` gerçekleşen sonucu GÜVENİLİR biçimde sıralamıyor.
//   * 104 tespit tablosu (13–14.09): olasılık vs MFE  r = -0.050, t = -0.50
//   * 370 kayıtlık DB örneklemi     : olasılık vs MFE  r = +0.095, t = +1.83
//     (vs "hedefe dokundu" r = +0.111, t = +2.13 — sınırda, çoklu karşılaştırmada
//      sağlam değil)
// İki bağımsız örneklem de ayırt edicilik göstermiyor.
//
// Sonuç: olasılık NE skora NE hedefe girer (bkz. `ml_oalasilik` kilidi), yalnızca
// gözlem olarak gösterilir. Bu yüzden yeşil/sarı/kırmızı "güven" renklendirmesi
// KALDIRILDI: kalibre edilmemiş bir sayıya kesinlik görüntüsü veriyordu ve
// proje kuralıyla çakışıyordu (YEŞİL=kâr, KIRMIZI=zarar; nötr = `bunker-muted`).

/** Nötr (renksiz) gösterim — olasılık kalibre değil, güven sinyali DEĞİL. */
export const ML_PROB_CLASS =
  "rounded border border-bunker-700 bg-bunker-800/40 px-1.5 py-0.5 font-mono text-[10px] text-bunker-muted";

/** Ekranda gösterilen yüzde metni; `null`/NaN -> "—" (nötr, asla boyanmaz). */
export function formatMlProbability(value: unknown): string {
  if (value == null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `%${Math.round(n * 100)}`;
}

/** Ham değerin geçerli olup olmadığı (0 dahil — 0 da bilgidir, null değil). */
export function hasMlProbability(value: unknown): boolean {
  if (value == null) return false;
  return Number.isFinite(Number(value));
}

export const ML_PROB_TITLE =
  "ML olasılığı: kalibre edilmemiş gözlem değeri. Skoru ve hedefi ETKİLEMEZ " +
  "(13–14.09 örneklemi: r=-0.05, anlamsız).";
