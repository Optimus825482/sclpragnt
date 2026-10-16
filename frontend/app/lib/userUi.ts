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

export type MacroRegime = {
  shield_enabled?: boolean;
  regime_shield_active?: boolean;
  btc_price?: number | null;
  btc_1h_ema200?: number | null;
};

export type RegimeNotice = { active: boolean; gapPct: number | null; title: string; detail: string };

/**
 * BTC rejim kalkanı açıkken (BTC 1 saatlik EMA200'ün altında) sistem yeni bildirim göndermez.
 * Kullanıcı "sistem bozuk" sanmasın diye nedenini açıkça gösteririz. Veri yoksa uyarı VERMEYİZ.
 */
export function regimeNotice(r: MacroRegime | null | undefined): RegimeNotice {
  const none: RegimeNotice = { active: false, gapPct: null, title: "", detail: "" };
  if (!r || r.shield_enabled === false || r.regime_shield_active !== true) return none;
  const price = Number(r.btc_price);
  const ema = Number(r.btc_1h_ema200);
  const gapPct = Number.isFinite(price) && price > 0 && Number.isFinite(ema) && ema > 0 ? ((price - ema) / ema) * 100 : null;
  const gapText = gapPct != null ? ` BTC, 1 saatlik ortalamanın (EMA200) %${Math.abs(gapPct).toFixed(2).replace(".", ",")} altında.` : "";
  return {
    active: true,
    gapPct,
    title: "Piyasa düşüş rejiminde: yeni bildirimler durduruldu",
    detail: `Risk koruması açık.${gapText} BTC ortalamanın üstüne çıkınca bildirimler kendiliğinden yeniden başlar.`,
  };
}
