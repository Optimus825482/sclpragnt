// Açık pozisyon K/Z matematiğinin TEK kaynağı.
//
// Neden var
// ---------
// Portföy / Ana Sayfa / Grafik sayfaları açık pozisyon kârını kendi içinde
// `(current - entry) * quantity` ile **brüt** hesaplıyordu; backend ise
// komisyonlu (net) hesaplıyor (`routers/runtime.py`, `analyzer.py`). Aynı
// pozisyon için iki farklı tutar görünüyordu ve Grafik sayfasındaki "AÇIK
// POZİSYONLAR" tablosunda ana pozisyonlar net, otonomlar brüt olarak **aynı
// kolonda** karışıyordu.
//
// Kanonik kural (backend `config.min_net_exit_pct` ile aynı):
//   gidiş-dönüş maliyeti = komisyon_pct × (giriş_değeri + çıkış_değeri)
//   net = brüt − gidiş-dönüş maliyeti
// Yani İKİ bacak da düşülür (yalnız giriş bacağını düşmek D-01'in kök
// hatasıydı: kâr kilidi çıkışı zarar yazıyordu).
//
// `null` sözleşmesi
// -----------------
// Girdi eksik/geçersizse (current_price gelmedi, quantity 0, entry ≤ 0) sonuç
// `null`'dur — 0 DEĞİL. 0 dönersek UI bunu "başabaş" sanıp yeşile boyar
// (H-02). Tüketiciler `null`'u nötr (`text-bunker-muted`) göstermelidir.

/** Backend `config.COMMISSION_PCT` varsayılanı (tek bacağın oranı). */
export const COMMISSION_PCT_FALLBACK = 0.0015;

let _commissionPct = COMMISSION_PCT_FALLBACK;

/**
 * Backend'den gelen gerçek komisyon oranını uygular (WS `portfolio` mesajı ve
 * `GET /api/config` bu alanı taşır). Geçersiz değer yok sayılır → varsayılan
 * korunur. Böylece oran env ile değişse bile frontend sessizce sapmaz.
 */
export function applyCommissionPct(value: unknown): void {
  const n = Number(value);
  if (Number.isFinite(n) && n > 0 && n < 0.05) _commissionPct = n;
}

/** Aktif komisyon oranı (tek bacak). */
export function commissionPct(): number {
  return _commissionPct;
}

function positive(value: unknown): number | null {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** Brüt açık pozisyon K/Z (₺). Girdi eksikse `null`. */
export function grossOpenPnlTry(
  entry: unknown, current: unknown, quantity: unknown,
): number | null {
  const e = positive(entry);
  const c = positive(current);
  const q = positive(quantity);
  if (e === null || c === null || q === null) return null;
  return (c - e) * q;
}

/** Net açık pozisyon K/Z (₺) — gidiş-dönüş komisyonu düşülmüş. Girdi eksikse `null`. */
export function netOpenPnlTry(
  entry: unknown, current: unknown, quantity: unknown,
): number | null {
  const e = positive(entry);
  const c = positive(current);
  const q = positive(quantity);
  if (e === null || c === null || q === null) return null;
  const gross = (c - e) * q;
  const roundTripFees = _commissionPct * q * (e + c);
  return gross - roundTripFees;
}

/** Net açık pozisyon getirisi (%). Maliyet tabanı giriş değeridir. Girdi eksikse `null`. */
export function netOpenPnlPct(
  entry: unknown, current: unknown, quantity: unknown,
): number | null {
  const e = positive(entry);
  const q = positive(quantity);
  const net = netOpenPnlTry(entry, current, quantity);
  if (e === null || q === null || net === null) return null;
  return (net / (e * q)) * 100;
}

/** Kapalı işlem K/Z'si (backend zaten komisyonlu yazar) — yalnız null-korumalı okuma. */
export function closedPnlTry(value: unknown): number | null {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}
