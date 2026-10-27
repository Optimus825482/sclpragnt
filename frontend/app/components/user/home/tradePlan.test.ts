import { describe, expect, it } from "vitest";
import { planDialogDefaults, planSummary, planTiles, planWarningLabels, priceDeviationPct, type TradePlan } from "./tradePlan";

const ist = (y: number, mo: number, d: number, h: number, mi: number) =>
  Date.UTC(y, mo - 1, d, h - 3, mi) / 1000; // Europe/Istanbul = UTC+3 (sabit)

const CREATED = ist(2026, 10, 27, 19, 0);
const PLAN: TradePlan = {
  symbol: "XTRY", bucket: "radar", entry_ref_price: 6.0,
  max_amount_try: 40_000, max_amount_binding: "depth",
  target_net_pct: 3.0, target_gross_pct: 3.6, target_price: 6.2199,
  stop_pct: 4.2, stop_price: 5.82,
  eta_minutes: 35, exit_at: ist(2026, 10, 27, 20, 45), grace_minutes: 90,
  hit_rate: 0.62, sample_n: 50, profile_exit: false, warnings: [], created_at: CREATED,
};
// backend/tests/test_notification_plan.py SAMPLE_PLAN ile aynı
const SAMPLE: TradePlan = { ...PLAN, max_amount_try: 40999.7, target_gross_pct: 3.4 };

describe("planDialogDefaults", () => {
  it("plan varsa tutar min(maks, boş)", () => {
    expect(planDialogDefaults(PLAN, 100_000)).toEqual({ amountTry: 40_000, slPct: 4.2, tpPct: 3.6, oco: true });
    expect(planDialogDefaults(PLAN, 10_000).amountTry).toBe(10_000);
  });
  it("tutar tam TL'ye aşağı yuvarlanır", () => {
    expect(planDialogDefaults(SAMPLE, 100_000).amountTry).toBe(40_999);
  });
  it("stop yoksa OCO kapalı", () => {
    expect(planDialogDefaults({ ...PLAN, stop_pct: null }, 100_000)).toEqual({ amountTry: 40_000, slPct: null, tpPct: 3.6, oco: false });
  });
  it("tpPct gerçek para tabanının (%0,5) altına inmez", () => {
    expect(planDialogDefaults({ ...PLAN, target_gross_pct: 0.2 }, 100_000).tpPct).toBe(0.5);
  });
  it("plan yoksa eski varsayılan", () => {
    expect(planDialogDefaults(null, 1000)).toEqual({ amountTry: 250, slPct: null, tpPct: null, oco: false });
  });
});

describe("planSummary (backend plan_text ile birebir)", () => {
  it("tam metin", () => {
    expect(planSummary(SAMPLE, CREATED)).toBe(
      "Maks: 40.000 TL | Hedef 6,22 (+%3 net) | ~35 dk (geçmişte %62) | Çıkış 20:45'e kadar | Stop 5,82");
    expect(planSummary(PLAN, CREATED)).toContain("Maks: 40.000 TL");
  });
  it("varyantlar", () => {
    let t = planSummary({ ...SAMPLE, eta_minutes: 135, target_price: 0.02316, exit_at: CREATED + 86400 + 3600 }, CREATED);
    expect(t).toContain("Hedef 0,02316");
    expect(t).toContain("~2 sa 15 dk");
    expect(t).toContain("Çıkış 28.10 20:00'e kadar");
    t = planSummary({ ...SAMPLE, profile_exit: true }, CREATED);
    expect(t).toContain("(+%3.4 brüt)");
    t = planSummary({
      ...SAMPLE, eta_minutes: null, exit_at: null, stop_price: null, warnings: ["veri_yetersiz", "hedef_gercekci_degil"],
    }, CREATED);
    expect(t).toBe("⚠ %3 net bu defterde zor · Maks: 40.000 TL | Hedef 6,22 (+%3 net) | Süre: veri yetersiz");
  });
  it("sinyal hedefi kazandıysa etiket brüt (backend test_plan_text_signal_target_shows_gross)", () => {
    const t = planSummary({ ...SAMPLE, target_gross_pct: 9, target_source: "signal" }, CREATED);
    expect(t).toContain("Hedef 6,22 (+%9 brüt)");
    expect(t).not.toContain("net)");
    expect(planSummary({ ...SAMPLE, target_source: "book" }, CREATED)).toContain("(+%3 net)");
  });
  it("profil çıkışı + istatistik yok: süre yetersiz ama çıkış/stop görünür (backend ile aynı)", () => {
    expect(planSummary({ ...SAMPLE, profile_exit: true, eta_minutes: null, hit_rate: null, warnings: ["veri_yetersiz"] }, CREATED))
      .toBe("Maks: 40.000 TL | Hedef 6,22 (+%3.4 brüt) | Süre: veri yetersiz | Çıkış 20:45'e kadar | Stop 5,82");
  });
  it("ETA sınırları ve hit_rate yok", () => {
    expect(planSummary({ ...SAMPLE, eta_minutes: 59.6, hit_rate: null }, CREATED)).toContain("| ~1 sa 0 dk |");
    expect(planSummary({ ...SAMPLE, eta_minutes: 45, hit_rate: null }, CREATED)).toContain("| ~45 dk |");
  });
  it("fiyat biçimi: 4 anlamlı hane, sondaki sıfırlar atılır", () => {
    expect(planSummary({ ...SAMPLE, target_price: 100 }, CREATED)).toContain("Hedef 100 (");
    expect(planSummary({ ...SAMPLE, target_price: 1234.5678 }, CREATED)).toContain("Hedef 1235 (");
  });
});

describe("planTiles", () => {
  it("sinyal hedefi: HEDEF (brüt)", () => {
    expect(planTiles({ ...PLAN, target_source: "signal" })[1].label).toBe("HEDEF (brüt)");
    expect(planTiles(PLAN)[1].label).toBe("HEDEF (+%3 net)");
  });
  it("veri yetersiz: profilsiz planda ÇIKIŞ yok, profil planında var", () => {
    const lacking = { ...PLAN, eta_minutes: null, warnings: ["veri_yetersiz"] };
    expect(planTiles(lacking).map((t) => t.label)).toEqual(["MAKS TUTAR", "HEDEF (+%3 net)", "STOP", "SÜRE"]);
    const prof = planTiles({ ...lacking, profile_exit: true });
    expect(prof.map((t) => t.label)).toEqual(["MAKS TUTAR", "HEDEF (brüt)", "STOP", "SÜRE", "ÇIKIŞ"]);
    expect(prof.find((t) => t.label === "SÜRE")?.value).toBe("veri yetersiz");
    expect(prof.find((t) => t.label === "ÇIKIŞ")?.value).toBe("20:45");
  });
});

describe("yardımcılar", () => {
  it("uyarı etiketleri", () => {
    expect(planWarningLabels(["veri_yetersiz", "hedef_gercekci_degil", "x"])).toEqual(["Veri yetersiz", "Hedef gerçekçi değil"]);
  });
  it("sapma yüzdesi", () => {
    expect(priceDeviationPct(6.0, 6.3)).toBeCloseTo(5, 6);
    expect(priceDeviationPct(6.0, null)).toBeNull();
  });
});
