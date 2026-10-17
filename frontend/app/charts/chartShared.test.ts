// 2026-10-17: grafik görünüm ayarları varsayılanı ve sürümlü kayıt çözümlemesi.
import { describe, expect, it } from "vitest";
import { DEFAULT_DISPLAY, DISPLAY_VERSION, resolveDisplay } from "./chartShared";

describe("grafik görünüm varsayılanları", () => {
  it("varsayılan: Pozisyonlar ve basınç açık, SL/TP ve formasyonlar kapalı", () => {
    expect(DEFAULT_DISPLAY).toEqual({
      showPositions: true, showStopTakeProfit: false, showPatterns: false, showPressure: true, showMonitoringLines: true,
    });
  });

  it("kayıt yoksa ya da sürümsüz (eski otomatik) kayıtsa varsayılan uygulanır", () => {
    expect(resolveDisplay(null)).toEqual(DEFAULT_DISPLAY);
    expect(resolveDisplay(undefined)).toEqual(DEFAULT_DISPLAY);
    expect(resolveDisplay({ showStopTakeProfit: true, showPatterns: true })).toEqual(DEFAULT_DISPLAY);
    expect(resolveDisplay({ showStopTakeProfit: true, v: 1 })).toEqual(DEFAULT_DISPLAY);
  });

  it("güncel sürümlü kayıt kullanıcı seçimidir ve korunur; eksik alan varsayılandan gelir", () => {
    const r = resolveDisplay({ showStopTakeProfit: true, showPressure: false, v: DISPLAY_VERSION });
    expect(r).toEqual({ ...DEFAULT_DISPLAY, showStopTakeProfit: true, showPressure: false });
  });

  it("varsayılan nesnesi dışarıdan değiştirilemez (kopya döner)", () => {
    const r = resolveDisplay(null);
    r.showPatterns = true;
    expect(DEFAULT_DISPLAY.showPatterns).toBe(false);
  });
});
