import { describe, expect, it } from "vitest";
import { MENU_ITEMS, baseSymbol, isRegimeTitle, modeLabel, notificationStatus, SETTINGS_TABS, parseSettingsTab, confidenceBadge, hitProbLabel, netTargetText, SCORE_LABEL, SCORE_TOOLTIP, isUserRole, isUserView, pctChange, statusLabel, visibleMenu, windowEnd } from "./userUi";

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

describe("confidenceBadge (şiddet kelimesi)", () => {
  it("eşikler", () => {
    expect(confidenceBadge(85)).toBe("Çok hızlı");
    expect(confidenceBadge(70)).toBe("Hızlı");
    expect(confidenceBadge(40)).toBe("Ilımlı");
    expect(confidenceBadge(null)).toBe("Ilımlı");
  });
  it("yüksek skor 'iyi/güçlü/yüksek güven' DEMEZ", () => {
    for (const s of [95, 70, 10, null]) expect(confidenceBadge(s)).not.toMatch(/yüksek|güçlü|iyi|güven/i);
  });
  it("etiket ve ipucu", () => {
    expect(SCORE_LABEL).toBe("HAREKET ŞİDDETİ");
    expect(SCORE_TOOLTIP).toContain("isabet garantisi değildir");
  });
});

describe("hitProbLabel", () => {
  it("p > başabaş → good, yuvarlanmış yüzde ve ipucu", () => {
    const r = hitProbLabel(0.624, 0.55);
    expect(r.text).toBe("%62");
    expect(r.tone).toBe("good");
    expect(r.title).toBe("Ölçülmüş isabet tahmini · başabaş %55");
  });
  it("p == başabaş veya altı → warn", () => {
    expect(hitProbLabel(0.55, 0.55).tone).toBe("warn");
    expect(hitProbLabel(0.4, 0.55).tone).toBe("warn");
  });
  it("başabaş yoksa asla good değil", () => {
    const r = hitProbLabel(0.9, null);
    expect(r.tone).toBe("warn");
    expect(r.text).toBe("%90");
    expect(r.title).not.toContain("başabaş");
  });
  it("p yoksa em dash ve nötr ton", () => {
    expect(hitProbLabel(null, 0.5)).toMatchObject({ text: "—", tone: "mute" });
    expect(hitProbLabel(undefined, undefined).text).toBe("—");
    expect(hitProbLabel(Number.NaN, 0.5).text).toBe("—");
  });
  it("p = 0 geçerli bir değerdir", () => expect(hitProbLabel(0, 0.5).text).toBe("%0"));
});

describe("netTargetText", () => {
  it("biçim", () => {
    expect(netTargetText(1.8)).toBe("net +1,80%");
    expect(netTargetText(-0.1)).toBe("net -0,10%");
  });
  it("yok → boş", () => {
    expect(netTargetText(null)).toBe("");
    expect(netTargetText(undefined)).toBe("");
    expect(netTargetText(Number.NaN)).toBe("");
  });
});

describe("visibleMenu / isUserRole", () => {
  it("varsayılan menü", () =>
    expect(visibleMenu([]).map((m) => m.id)).toEqual(
      ["home", "radar", "binance", "risk", "charts", "reports", "settings"]));
  it("Bildirimler ve Profil menüde yok ama kimlikleri korunur", () => {
    // 2026-10-17 (basit arayüz): içerikleri Raporlar / Ayarlar sekmesine taşındı.
    const ids = visibleMenu([]).map((m) => m.id);
    expect(ids).not.toContain("notifications");
    expect(ids).not.toContain("profile");
    expect(MENU_ITEMS.map((m) => m.id)).toEqual(expect.arrayContaining(["notifications", "profile"]));
  });
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

describe("parseSettingsTab", () => {
  // 2026-10-17 (basit arayüz): Ayarlar sekmeleri; ?tab= ve localStorage değeri doğrulanır.
  it("geçerli değerler", () => {
    expect(parseSettingsTab("profil")).toBe("profil");
    expect(parseSettingsTab("genel")).toBe("genel");
    expect(parseSettingsTab("bildirim")).toBe("bildirim");
  });
  it("?tab=profile (İngilizce) profil sekmesine eşlenir", () => expect(parseSettingsTab("profile")).toBe("profil"));
  it("geçersiz/boş → null", () => {
    expect(parseSettingsTab("x")).toBeNull();
    expect(parseSettingsTab(null)).toBeNull();
    expect(parseSettingsTab(undefined)).toBeNull();
  });
  it("sekme listesi", () => expect(SETTINGS_TABS.map((t) => t.id)).toEqual(["genel", "bildirim", "profil"]));
});

describe("modeLabel", () => {
  it("eşler", () => {
    expect(modeLabel("trend_devam")).toBe("Trend devam");
    expect(modeLabel("unified")).toBe("Birleşik radar");
    expect(modeLabel("v_donusu")).toBe("V dönüşü");
    expect(modeLabel("global_lead_lag")).toBe("Öncü-takipçi");
  });
  it("bilinmeyen ham, boş boş", () => {
    expect(modeLabel("xyz")).toBe("xyz");
    expect(modeLabel(null)).toBe("");
    expect(modeLabel("  ")).toBe("");
  });
});

describe("notificationStatus", () => {
  // Bildirim fiyatı 100, hedef 110, pencere 1000..1900 sn.
  const row = { price: 100, expected_price: 110, detected_at: 1000, horizon_minutes: 15 };
  it("hedefe ulaştı (pencere kapalı olsa da)", () => {
    expect(notificationStatus(row, 110, 1100).kind).toBe("hit");
    expect(notificationStatus(row, 120, 999999)).toMatchObject({ kind: "hit", icon: "✅", label: "Hedefe ulaştı", tone: "good" });
  });
  it("pencere açık, canlı >= bildirim fiyatı: sürüyor, kalan dakika yukarı yuvarlanır", () => {
    const s = notificationStatus(row, 105, 1000 + 60);
    expect(s).toMatchObject({ kind: "active", icon: "⏳", tone: "info", remainingMin: 14 });
    expect(s.label).toBe("Yükseliş ihtimali sürüyor · kalan 14 dk");
    expect(notificationStatus(row, 100, 1000 + 899)).toMatchObject({ kind: "active", remainingMin: 1 });
  });
  it("pencere açık, canlı bildirim fiyatının altında (ama -%1,5 üstünde): zayıfladı", () => {
    expect(notificationStatus(row, 99.5, 1100)).toMatchObject({
      kind: "weak", icon: "⚠️", tone: "warn", label: "Yükseliş ihtimali zayıfladı",
    });
    expect(notificationStatus(row, 98.6, 1100).kind).toBe("weak");
  });
  it("%1,5 veya daha fazla düştü: ortadan kalktı (pencere açık ya da kapalı)", () => {
    expect(notificationStatus(row, 98.5, 1100)).toMatchObject({
      kind: "gone", icon: "❌", tone: "bad", label: "Yükseliş ihtimali ortadan kalktı",
    });
    expect(notificationStatus(row, 90, 1100).kind).toBe("gone");
    expect(notificationStatus(row, 90, 999999).kind).toBe("gone");
  });
  it("pencere kapandı: ended (hedef yok, düşüş %1,5'ten az)", () => {
    expect(notificationStatus(row, 105, 1900)).toMatchObject({ kind: "ended", icon: "⌛", tone: "mute", label: "Yükseliş penceresi kapandı" });
    expect(notificationStatus(row, 99, 1900).kind).toBe("ended");
  });
  it("canlı fiyat yok / hedef yok → hit/gone/weak olmaz", () => {
    expect(notificationStatus(row, null, 1100).kind).toBe("active");
    expect(notificationStatus(row, null, 99999).kind).toBe("ended");
    expect(notificationStatus({ ...row, expected_price: 0 }, 105, 99999).kind).toBe("ended");
  });
  it("bildirim fiyatı yoksa gone/weak üretilmez", () => {
    expect(notificationStatus({ expected_price: 110, detected_at: 1000, horizon_minutes: 15 }, 50, 1100).kind).toBe("active");
  });
  it("hedef bildirim fiyatının altındaysa bile hit önceliklidir", () => {
    expect(notificationStatus({ ...row, expected_price: 95 }, 96, 1100).kind).toBe("hit");
  });
  it("ufuk yoksa 60 dk", () => {
    expect(notificationStatus({ expected_price: 0, detected_at: 0, horizon_minutes: null }, null, 3599).kind).toBe("active");
  });
});

describe("isRegimeTitle", () => {
  it("rozetli başlık", () => {
    expect(isRegimeTitle("⚠ BTC REJİM · STRAX yükseliş adayı")).toBe(true);
    expect(isRegimeTitle("  ⚠ BTC REJİM")).toBe(true);
  });
  it("normal/boş başlık", () => {
    expect(isRegimeTitle("STRAX yükseliş adayı")).toBe(false);
    expect(isRegimeTitle(null)).toBe(false);
    expect(isRegimeTitle(undefined)).toBe(false);
  });
});

describe("baseSymbol", () => {
  it("TRY atar", () => {
    expect(baseSymbol("STRAXTRY")).toBe("STRAX");
    expect(baseSymbol("btc_try")).toBe("BTC");
    expect(baseSymbol("TRY")).toBe("TRY");
    expect(baseSymbol(null)).toBe("");
  });
});
