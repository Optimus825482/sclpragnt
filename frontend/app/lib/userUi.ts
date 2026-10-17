/** Kullanıcı arayüzü için saf yardımcılar (node'da test edilir). */

export type Tone = "good" | "warn" | "bad" | "wait" | "mute";

export function pctChange(base: number | null | undefined, live: number | null | undefined): number | null {
  const b = Number(base);
  const l = Number(live);
  if (!Number.isFinite(b) || b <= 0) return null;
  if (!Number.isFinite(l) || l <= 0) return null;
  return ((l - b) / b) * 100;
}

export function statusLabel(status: string): { label: string; tone: Tone } {
  switch (status) {
    case "TAMAMEN BAŞARILI": return { label: "Hedefe ulaştı", tone: "good" };
    case "KISMİ": return { label: "Kısmen", tone: "warn" };
    case "BAŞARISIZ": return { label: "Ulaşmadı", tone: "bad" };
    case "ÖLÇÜLEMEDİ": return { label: "Ölçülemedi", tone: "mute" };
    default: return { label: "Bekliyor", tone: "wait" };
  }
}

const DEFAULT_WINDOW_MIN = 60;

/** Ölçüm penceresinin bitişi (epoch saniye). Ufuk yoksa 60 dk varsayılır. */
export function windowEnd(detectedAt: number, horizonMin: number): number {
  const h = Number(horizonMin);
  const minutes = Number.isFinite(h) && h > 0 ? h : DEFAULT_WINDOW_MIN;
  return Number(detectedAt) + minutes * 60;
}

export function confidenceBadge(score: number | null | undefined): "Yüksek" | "Orta" | "Düşük" {
  const s = Number(score);
  if (!Number.isFinite(s)) return "Düşük";
  if (s >= 80) return "Yüksek";
  if (s >= 60) return "Orta";
  return "Düşük";
}

// 2026-10-17 (basit arayüz): `legacy` = menüde GÖSTERİLMEZ ama kimlik backend MENU_IDS'te kalır ve
// rota doğrudan bağlantıyla çalışır (Bildirimler içeriği Raporlar'da; Profil, Ayarlar sekmesi).
export type MenuItem = { id: string; href: string; label: string; icon: string; locked?: boolean; legacy?: boolean };

/** Kimlikler backend `app/ui_prefs.py` MENU_IDS ile AYNIDIR. */
export const MENU_ITEMS: readonly MenuItem[] = [
  { id: "home", href: "/", label: "Ana sayfa", icon: "🏠", locked: true },
  { id: "notifications", href: "/notifications", label: "Bildirimler", icon: "🔔", legacy: true },
  { id: "radar", href: "/monitoring", label: "Radar", icon: "📡" },
  { id: "binance", href: "/binance-tr", label: "Binance TR", icon: "💱" },
  { id: "risk", href: "/risk", label: "Risk Merkezi", icon: "🛡️" },
  { id: "charts", href: "/charts", label: "Grafik", icon: "📈" },
  { id: "reports", href: "/reports", label: "Raporlar", icon: "📋" },
  { id: "profile", href: "/profile", label: "Profil", icon: "👤", legacy: true },
  { id: "settings", href: "/settings", label: "Ayarlar", icon: "⚙️", locked: true },
];

// 2026-10-17 (basit arayüz): Ayarlar sayfası sekmeleri (Profil artık burada).
export type SettingsTabId = "genel" | "bildirim" | "profil";
export const SETTINGS_TABS: readonly { id: SettingsTabId; label: string }[] = [
  { id: "genel", label: "Genel" },
  { id: "bildirim", label: "Bildirim" },
  { id: "profil", label: "Profil" },
];

/** ?tab= veya localStorage değerini sekme kimliğine çevirir; tanınmazsa null. "profile" takma adı desteklenir. */
export function parseSettingsTab(v: string | null | undefined): SettingsTabId | null {
  if (v === "profile") return "profil";
  return SETTINGS_TABS.some((t) => t.id === v) ? (v as SettingsTabId) : null;
}

export function visibleMenu(hidden: string[]): MenuItem[] {
  const set = new Set(hidden);
  return MENU_ITEMS.filter((m) => !m.legacy && (m.locked || !set.has(m.id)));
}

export function isUserRole(role: string | null): boolean {
  return !!role && role !== "admin";
}

export type AdminView = "advanced" | "simple";

/** Kullanıcı arayüzü mü gösterilecek? Normal kullanıcı her zaman; admin yalnız "Basit" seçtiyse. */
export function isUserView(role: string | null, adminView: AdminView): boolean {
  if (isUserRole(role)) return true;
  return role === "admin" && adminView === "simple";
}

// 2026-10-18: `regimeNotice` / rejim bandı kaldırıldı — kalkan rozet modunda bildirimler durmaz; bkz. `isRegimeTitle`.

// 2026-10-17 (basit arayüz): ana sayfa bildirim kartları için saf yardımcılar.

const MODE_LABELS: Record<string, string> = {
  trend_devam: "Trend devam",
  unified: "Birleşik radar",
  v_donusu: "V dönüşü",
  global_lead_lag: "Öncü-takipçi",
};

/** Bildirim `mode` değerini sade Türkçe etikete çevirir; tanınmazsa ham değer, boşsa "". */
export function modeLabel(mode: string | null | undefined): string {
  const m = String(mode ?? "").trim();
  if (!m) return "";
  return MODE_LABELS[m] ?? m;
}

/** Bildirim fiyatının bu kadar (%) altına inen canlı fiyat = "yükseliş ihtimali ortadan kalktı". */
export const GONE_DROP_PCT = 1.5;

export type NotificationStatus =
  | { kind: "hit"; icon: "✅"; label: string; tone: "good" }
  | { kind: "active"; icon: "⏳"; label: string; tone: "info"; remainingMin: number }
  | { kind: "weak"; icon: "⚠️"; label: string; tone: "warn"; remainingMin: number }
  | { kind: "gone"; icon: "❌"; label: string; tone: "bad" }
  | { kind: "ended"; icon: "⌛"; label: string; tone: "mute" };

/**
 * Bildirim kartının durum satırı (yükseliş ihtimali hâlâ geçerli mi?). Öncelik sırası:
 * 1. "hit": canlı >= beklenen fiyat (pencere kapalı olsa da).
 * 2. "gone": canlı, bildirim fiyatının %1,5 veya daha fazla altında (pencereden bağımsız).
 * 3. pencere (detected_at + ufuk) sürüyorsa: canlı < bildirim fiyatı ise "weak" (zayıfladı), değilse "active" (sürüyor).
 *    Kalan dakika yukarı yuvarlanır, en az 1.
 * 4. "ended": pencere kapandı, hedef yok, iptal de değil.
 * `live` yoksa hit/gone/weak üretilmez (pencere sürüyorsa "active"). `expected_price` <= 0 ise "hit" yok.
 */
export function notificationStatus(
  row: { expected_price?: number | null; price?: number | null; detected_at: number; horizon_minutes?: number | null },
  live: number | null | undefined,
  nowSec: number,
): NotificationStatus {
  const target = Number(row.expected_price);
  const base = Number(row.price);
  const l = Number(live);
  const hasLive = Number.isFinite(l) && l > 0;
  if (Number.isFinite(target) && target > 0 && hasLive && l >= target) {
    return { kind: "hit", icon: "✅", label: "Hedefe ulaştı", tone: "good" };
  }
  const hasBase = Number.isFinite(base) && base > 0;
  if (hasLive && hasBase && ((l - base) / base) * 100 <= -GONE_DROP_PCT + 1e-9) {
    return { kind: "gone", icon: "❌", label: "Yükseliş ihtimali ortadan kalktı", tone: "bad" };
  }
  const end = windowEnd(row.detected_at, Number(row.horizon_minutes));
  if (nowSec < end) {
    const remainingMin = Math.max(1, Math.ceil((end - nowSec) / 60));
    if (hasLive && hasBase && l < base) {
      return { kind: "weak", icon: "⚠️", label: "Yükseliş ihtimali zayıfladı", tone: "warn", remainingMin };
    }
    return { kind: "active", icon: "⏳", label: `Yükseliş ihtimali sürüyor · kalan ${remainingMin} dk`, tone: "info", remainingMin };
  }
  return { kind: "ended", icon: "⌛", label: "Yükseliş penceresi kapandı", tone: "mute" };
}

/** Başlığı "⚠ BTC REJİM" ile başlayan bildirim, BTC düşüş rejiminde (kalkan rozet modunda) gönderilmiştir. */
export function isRegimeTitle(title: string | null | undefined): boolean {
  return String(title ?? "").trimStart().startsWith("⚠ BTC REJİM");
}

/** "STRAXTRY" -> "STRAX" (TRY soneki atılır; sonek yoksa olduğu gibi). */
export function baseSymbol(symbol: string | null | undefined): string {
  const s = String(symbol ?? "").replace(/_/g, "").toUpperCase();
  return s.length > 3 && s.endsWith("TRY") ? s.slice(0, -3) : s;
}
