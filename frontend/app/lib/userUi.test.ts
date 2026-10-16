import { describe, expect, it } from "vitest";
import { confidenceBadge, isUserRole, isUserView, pctChange, regimeNotice, statusLabel, visibleMenu, windowEnd } from "./userUi";

describe("pctChange", () => {
  it("hesaplar", () => expect(pctChange(100, 103)).toBeCloseTo(3, 6));
  it("negatif", () => expect(pctChange(200, 190)).toBeCloseTo(-5, 6));
  it("taban 0/null/NaN → null", () => {
    expect(pctChange(0, 5)).toBeNull();
    expect(pctChange(null, 5)).toBeNull();
    expect(pctChange(NaN, 5)).toBeNull();
  });
  it("canlı yok → null", () => {
    expect(pctChange(100, null)).toBeNull();
    expect(pctChange(100, 0)).toBeNull();
    expect(pctChange(100, Infinity)).toBeNull();
  });
});

describe("statusLabel", () => {
  it("eşler", () => {
    expect(statusLabel("TAMAMEN BAŞARILI")).toEqual({ label: "Hedefe ulaştı", tone: "good" });
    expect(statusLabel("KISMİ").label).toBe("Kısmen");
    expect(statusLabel("BAŞARISIZ").label).toBe("Ulaşmadı");
    expect(statusLabel("BEKLİYOR").tone).toBe("wait");
    expect(statusLabel("ÖLÇÜLEMEDİ").tone).toBe("mute");
  });
  it("bilinmeyen → Bekliyor", () => expect(statusLabel("???").label).toBe("Bekliyor"));
});

describe("windowEnd", () => {
  it("detected + ufuk", () => expect(windowEnd(1000, 15)).toBe(1900));
  it("ufuk 0/negatif → 60 dk varsayılan", () => expect(windowEnd(1000, 0)).toBe(1000 + 3600));
});

describe("confidenceBadge", () => {
  it("eşikler", () => {
    expect(confidenceBadge(85)).toBe("Yüksek");
    expect(confidenceBadge(70)).toBe("Orta");
    expect(confidenceBadge(40)).toBe("Düşük");
    expect(confidenceBadge(null)).toBe("Düşük");
  });
});

describe("visibleMenu / isUserRole", () => {
  it("varsayılan menü", () =>
    expect(visibleMenu([]).map((m) => m.id)).toEqual(
      ["home", "notifications", "radar", "binance", "risk", "charts", "reports", "profile", "settings"]));
  it("otonom paper (portföy) kullanıcı menüsünde yok", () =>
    expect(visibleMenu([]).some((m) => m.id === "portfolio" || m.href === "/portfolio")).toBe(false));
  it("gizlenir", () => expect(visibleMenu(["charts"]).some((m) => m.id === "charts")).toBe(false));
  it("kilitliler gizlenemez", () => {
    const ids = visibleMenu(["home", "settings"]).map((m) => m.id);
    expect(ids).toContain("home");
    expect(ids).toContain("settings");
  });
  it("rol", () => {
    expect(isUserRole("user")).toBe(true);
    expect(isUserRole("admin")).toBe(false);
    expect(isUserRole(null)).toBe(false);
  });
});

describe("isUserView", () => {
  it("kullanıcı her zaman kullanıcı arayüzü", () => {
    expect(isUserView("user", "advanced")).toBe(true);
    expect(isUserView("user", "simple")).toBe(true);
  });
  it("admin yalnız basit seçtiyse", () => {
    expect(isUserView("admin", "advanced")).toBe(false);
    expect(isUserView("admin", "simple")).toBe(true);
  });
  it("rol yok → false", () => expect(isUserView(null, "simple")).toBe(false));
});

describe("regimeNotice", () => {
  it("kalkan aktifken uyarı + yüzde fark", () => {
    const n = regimeNotice({ shield_enabled: true, regime_shield_active: true, btc_price: 4072000, btc_1h_ema200: 4076155 });
    expect(n.active).toBe(true);
    expect(n.gapPct).toBeCloseTo(-0.102, 2);
    expect(n.detail).toContain("%0,10");
  });
  it("kalkan kapalıysa (devre dışı) uyarı yok", () => {
    expect(regimeNotice({ shield_enabled: false, regime_shield_active: true }).active).toBe(false);
  });
  it("kalkan aktif değilse uyarı yok", () => {
    expect(regimeNotice({ shield_enabled: true, regime_shield_active: false }).active).toBe(false);
  });
  it("veri yoksa uyarı yok (yanlış alarm verme)", () => {
    expect(regimeNotice(null).active).toBe(false);
    expect(regimeNotice(undefined).active).toBe(false);
    expect(regimeNotice({}).active).toBe(false);
  });
  it("fiyat/EMA eksikse yüzde yok ama uyarı var", () => {
    const n = regimeNotice({ shield_enabled: true, regime_shield_active: true, btc_price: null, btc_1h_ema200: 0 });
    expect(n.active).toBe(true);
    expect(n.gapPct).toBeNull();
  });
});
