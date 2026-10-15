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

export type MenuItem = { id: string; href: string; label: string; icon: string; locked?: boolean };

/** Kimlikler backend `app/ui_prefs.py` MENU_IDS ile AYNIDIR. */
export const MENU_ITEMS: readonly MenuItem[] = [
  { id: "home", href: "/", label: "Ana sayfa", icon: "🏠", locked: true },
  { id: "notifications", href: "/notifications", label: "Bildirimler", icon: "🔔" },
  { id: "radar", href: "/monitoring", label: "Radar", icon: "📡" },
  { id: "portfolio", href: "/portfolio", label: "Portföy", icon: "💼" },
  { id: "charts", href: "/charts", label: "Grafik", icon: "📈" },
  { id: "reports", href: "/reports", label: "Raporlar", icon: "📋" },
  { id: "profile", href: "/profile", label: "Profil", icon: "👤" },
  { id: "settings", href: "/settings", label: "Ayarlar", icon: "⚙️", locked: true },
];

export function visibleMenu(hidden: string[]): MenuItem[] {
  const set = new Set(hidden);
  return MENU_ITEMS.filter((m) => m.locked || !set.has(m.id));
}

export function isUserRole(role: string | null): boolean {
  return !!role && role !== "admin";
}
