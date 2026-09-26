// Sayfa bazlı kopyalanan biçimlendirme kurallarının TEK kaynağı.
//
// H-04/H-15/H-16: fiyat biçimi 5 ayrı dosyada kopyalanmıştı (`chartShared`,
// `macd-monitor`, `monitoring`, `RadarAlertModal`, `binance-tr`) ve aynı fiyat
// sayfaya göre `1,5` / `1,5000` / `4250000.00` gibi farklı basılıyordu.
// Artık tüm bileşenler bu modülü kullanır; `app/charts/chartShared.ts` yalnızca
// buradan yeniden dışa aktarır (grafik ekseni de aynı `pricePrecision`'ı alır).
//
// TL biçimi tek (H-15): `₺` ÖNEK, her zaman 2 ondalık, tr-TR gruplama.
//
// Veri yoksa her fonksiyon "—" döner (0 DEĞİL). 0 meşru bir değerdir ama
// "veri yok" değildir; null'u 0'a çevirip yeşile boyamak yasaktır (H-02/H-05).

/**
 * Zaman damgasını milisaniyeye normalize eder. Backend karışık birim
 * gönderir (epoch saniye veya ms); eski `ts < 10_000_000_000 ? ts * 1000 : ts`
 * sezgiseli 8 sayfada kopyalanmıştı — artık burada tek yerde (H-24).
 */
export function toMs(ts: number | string | null | undefined): number {
  const value = Number(ts || 0);
  if (!Number.isFinite(value) || value <= 0) return 0;
  return value < 10_000_000_000 ? value * 1000 : value;
}

/** tr-TR kısa tarih + saat (tarayıcı yerel dilimi). */
export function fmtDateTime(ts: number | string | null | undefined): string {
  const ms = toMs(ts);
  if (!ms) return "—";
  return new Date(ms).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" });
}

/**
 * tr-TR GÜN/SAAT dakika çözünürlüğü: `26/09 14:35`.
 *
 * Neden ayrı bir fonksiyon: raporlar sayfası bu biçimi `toLocaleString("tr-TR",
 * { day, month, hour, minute })` ile kendi içinde yeniden yazıyordu ve
 * `dateStyle:"short"` kullanan `fmtDateTime`'dan FARKLI çıktı veriyordu (sıra
 * ve saat çözünürlüğü farklı). Aynı zaman damgası iki sayfada iki biçimde
 * basılınca hangisinin doğru olduğu belirsizleşiyordu. Artık tek kaynak burada.
 */
export function fmtMinute(ts: number | string | null | undefined): string {
  const ms = toMs(ts);
  if (!ms) return "—";
  return new Date(ms).toLocaleString("tr-TR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Sabit 2 ondalıklı genel sayı (`12.34`). Fiyat olmayan sayılar için
 * (adet, puan, oran tabanı). Eksik/geçersiz → "—" (0 DEĞİL).
 */
export function formatNumber2(value: number | string | null | undefined): string {
  const n = Number(value);
  if (value == null || value === "" || !Number.isFinite(n)) return "—";
  return String(Number(n.toFixed(2)));
}

/**
 * Bölünen (0.1234) girdiden yüzde: `%12.3`.
 *
 * SINIR: backend bazı uçlarda oranı YÜZDE (12.3), bazılarında ondaklık (0.123)
 * döndürür. Bu yardımcı **bölünen** sözleşmesini varsayar; yüzde gelen
 * alanlarda `formatFixed` kullan.
 */
export function formatRatioPct(value: number | string | null | undefined, digits = 1): string {
  const n = Number(value);
  if (value == null || value === "" || !Number.isFinite(n)) return "—";
  return `%${(n * 100).toFixed(digits)}`;
}

/** tr-TR yalnız tarih. */
export function fmtDate(ts: number | string | null | undefined): string {
  const ms = toMs(ts);
  if (!ms) return "—";
  return new Date(ms).toLocaleDateString("tr-TR");
}

/** tr-TR yalnız saat (saniye/ms karışık girdi güvenli). */
export function fmtClockTime(ts: number | string | null | undefined): string {
  const ms = toMs(ts);
  if (!ms) return "—";
  return new Date(ms).toLocaleTimeString("tr-TR");
}

/**
 * Paylaşılan fiyat hassasiyeti: <1 → 6 hane, <100 → 4 hane, <1000 → 3 hane,
 * aksi 2 hane. Grafik ekseni (`chartPriceFormat`) ve tüm fiyat gösterimi bu
 * kuralı kullanır; aynı fiyat farklı sayfalarda farklı yuvarlanmaz.
 *
 * `null`/`undefined` 2 haneye düşer. (Eskiden `Math.abs(Number(null))` = 0
 * olduğu için "veri yok" sessizce EN YÜKSEK kovaya (6 hane) düşüyordu:
 * eksen 0,000000 basıyordu. `formatPrice` zaten "—" döndürüyor, ama grafik
 * ekseni doğrudan bu fonksiyonu çağırıyordu.)
 */
export function pricePrecision(value: number | null | undefined): number {
  if (value == null) return 2;
  const abs = Math.abs(value);
  if (!Number.isFinite(abs)) return 2;
  if (abs < 1) return 6;
  if (abs < 100) return 4;
  if (abs < 1000) return 3;
  return 2;
}

/**
 * Fiyat biçimi (tr-TR, hassasiyet kovası `pricePrecision`).
 * Eksik/geçersiz veya ≤0 fiyat "—" döner: 0 bir fiyat değil, "veri yok"tur.
 */
export function formatPrice(value: number | null | undefined): string {
  const n = Number(value);
  if (value == null || !Number.isFinite(n) || n <= 0) return "—";
  return n.toLocaleString("tr-TR", {
    minimumFractionDigits: 0,
    maximumFractionDigits: pricePrecision(n),
  });
}

/**
 * Türk Lirası: `₺` önek, TAM 2 ondalık, tr-TR gruplama.
 * Küçük tutarlarda 8 ondalık basmak yok (H-15); sembol her zaman önek.
 */
export function formatTL(value: number | null | undefined): string {
  const n = Number(value);
  if (value == null || !Number.isFinite(n)) return "—";
  return `₺${n.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/**
 * İşaretli TL (K/Z): kâr `+₺…`, zarar `-₺…`, tam sıfır `₺0,00`, veri yok "—".
 * Sembol önek, işaret sembolün önünde → `-₺12,00` (H-15 biçim birliği).
 */
export function formatSignedTL(value: number | null | undefined): string {
  const n = Number(value);
  if (value == null || !Number.isFinite(n)) return "—";
  const magnitude = formatTL(Math.abs(n));
  if (n < 0) return `-${magnitude}`;
  if (n > 0) return `+${magnitude}`;
  return magnitude;
}

/**
 * Fiyat olmayan sabit ondalıklı sayılar (miktar/adet/miktar tutarı).
 * Fiyat için `formatPrice` kullanılmalıdır. Eksik/geçersiz → "—".
 */
export function formatFixed(value: number | string | null | undefined, digits = 2): string {
  const n = Number(value);
  if (value == null || value === "" || !Number.isFinite(n)) return "—";
  return n.toLocaleString("tr-TR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Yerel (UTC değil) YYYY-MM-DD — date input default değeri için. */
export function localDateInput(): string {
  const now = new Date();
  const offsetMs = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offsetMs).toISOString().slice(0, 10);
}
