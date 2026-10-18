// `lib/radarLogUi.ts` — Radar tarama logları penceresinin saf yardımcıları.

import { describe, it, expect } from "vitest";
import {
  DEFAULT_STATUS_CATALOG,
  MAX_RENDER_ROWS,
  buildQuery,
  deriveReasonCode,
  errorMessage,
  filterRows,
  fmtHorizon,
  fmtPctValue,
  fmtRatio,
  fmtRsiMfi,
  fmtScore,
  limitRows,
  normalizeResponse,
  normalizeRow,
  poolLine,
  reasonMeta,
  riskBadge,
  scanLabel,
  selectedIndex,
  sortRows,
  statusMeta,
  statusSummary,
  stepIndex,
  thresholdLabel,
  toneBadgeClass,
  type RadarLogRow,
} from "./radarLogUi";

const RAW_ROW = {
  symbol: "abc_try",
  status: "gated",
  tone: "warn",
  label: "Kapıya takıldı",
  reason: "skor tabanı altı (65.0 < 70)",
  reason_code: "skor_tabani",
  panel_score: 78.4,
  horizon: 5,
  price: 1.234,
  atr_pct: 0.41,
  rsi: 58.2,
  mfi: 61.0,
  ret3_pct: 0.9,
  volume_ratio: 1.8,
  mode: "trend",
  target_pct: 1.7,
  notified: false,
  horizons: {
    "15": { passes: false, reason: "atr_yetersiz:0.20%<0.25%", reason_code: "atr_yetersiz" },
    "5": { passes: true, reason: null, reason_code: null },
  },
};

const RAW = {
  ok: true,
  keep: 60,
  total_scans: 37,
  status_catalog: [{ status: "notified", label: "Bildirildi", tone: "success" }],
  scans: [
    {
      scan_no: 1233, scan_at: 1_792_289_700, risk_off: false, risk_off_unknown: false, min_panel_score: 70,
      pool: { "5": 100 }, counts: { rejected: 1 }, rows: [{ symbol: "OLDTRY", status: "rejected" }],
    },
    {
      scan_no: 1234, scan_at: 1_792_290_000.5, risk_off: true, risk_off_unknown: false, min_panel_score: 71.5,
      pool: { "15": 105, "5": 105 }, counts: { notified: 1, gated: 1 }, rows: [RAW_ROW, { symbol: "NEWTRY", status: "notified" }],
    },
  ],
};

function row(over: Partial<RadarLogRow> = {}): RadarLogRow {
  return { ...(normalizeRow({ symbol: "AAATRY", status: "rejected" }) as RadarLogRow), ...over };
}

describe("normalizeResponse", () => {
  it("sözleşmeyi okur, sembolü temizler, ufukları sıralar, taramaları en yeni önce dizer", () => {
    const r = normalizeResponse(RAW);
    expect(r.ok).toBe(true);
    expect(r.keep).toBe(60);
    expect(r.totalScans).toBe(37);
    expect(r.scans.map((s) => s.scanNo)).toEqual([1234, 1233]);
    const s = r.scans[0];
    expect(s.riskOff).toBe(true);
    expect(s.minPanelScore).toBe(71.5);
    expect(s.pool).toEqual([{ horizon: 5, count: 105 }, { horizon: 15, count: 105 }]);
    const x = s.rows[0];
    expect(x.symbol).toBe("ABCTRY");
    expect(x.reasonCode).toBe("skor_tabani");
    expect(x.panelScore).toBe(78.4);
    expect(x.horizons.map((h) => h.horizon)).toEqual([5, 15]);
    expect(x.horizons[0].passes).toBe(true);
    expect(x.horizons[1].reasonCode).toBe("atr_yetersiz");
  });

  it("boş / bozuk girdide hata fırlatmaz", () => {
    for (const bad of [null, undefined, 42, "x", [], {}, { scans: "yok" }, { scans: [null, 3, {}, { rows: 5 }] }]) {
      const r = normalizeResponse(bad);
      expect(Array.isArray(r.scans)).toBe(true);
      expect(r.totalScans).toBeGreaterThanOrEqual(0);
    }
    expect(normalizeResponse(null).scans).toEqual([]);
    expect(normalizeResponse({ scans: [{ rows: [{ symbol: "" }, null, 5] }] }).scans[0].rows).toEqual([]);
  });

  it("null sayısal alanlar 0'a dönmez", () => {
    const x = normalizeRow({ symbol: "A", status: "watch", panel_score: null, atr_pct: "", rsi: undefined, price: true }) as RadarLogRow;
    expect(x.panelScore).toBeNull();
    expect(x.atrPct).toBeNull();
    expect(x.rsi).toBeNull();
    expect(x.price).toBeNull();
  });

  it("counts yoksa satırlardan sayar; ton/etiket yoksa katalog ve yerleşik eşlemeye düşer", () => {
    const r = normalizeResponse({ scans: [{ scan_no: 1, rows: [{ symbol: "A", status: "watch" }, { symbol: "B", status: "watch" }, { symbol: "C", status: "notified" }] }] });
    expect(r.scans[0].counts).toEqual({ watch: 2, notified: 1 });
    expect(r.scans[0].rows[0].tone).toBe("caution");
    expect(r.scans[0].rows[2].label).toBe("Bildirildi");
    expect(r.scans[0].rows[2].notified).toBe(true);
  });

  it("scan_no eksikse benzersiz negatif numara verir", () => {
    const r = normalizeResponse({ scans: [{ scan_at: 2 }, { scan_at: 1 }] });
    expect(new Set(r.scans.map((s) => s.scanNo)).size).toBe(2);
    expect(scanLabel(r.scans[0])).toContain("tarama");
  });
});

describe("rozet eşleme", () => {
  it("ton -> mevcut rozet sınıfı; bilinmeyen ton nötr", () => {
    expect(toneBadgeClass("success")).toBe("ui-badge-positive");
    expect(toneBadgeClass("info")).toBe("ui-badge-info");
    expect(toneBadgeClass("warn")).toBe("ui-badge-orange");
    expect(toneBadgeClass("muted")).toBe("ui-badge-muted");
    expect(toneBadgeClass("caution")).toBe("ui-badge-warning");
    expect(toneBadgeClass("danger")).toBe("ui-badge-negative");
    expect(toneBadgeClass("neutral")).toBe("ui-badge-neutral");
    expect(toneBadgeClass("garip")).toBe("ui-badge-neutral");
    expect(toneBadgeClass(null)).toBe("ui-badge-neutral");
  });

  it("durum meta: katalog > yerleşik > ham değer", () => {
    expect(statusMeta("gated")).toEqual({ label: "Kapıya takıldı", tone: "warn" });
    expect(statusMeta("gated", [{ status: "gated", label: "Kapı", tone: "danger" }])).toEqual({ label: "Kapı", tone: "danger" });
    expect(statusMeta("yeni_durum")).toEqual({ label: "yeni_durum", tone: "neutral" });
    expect(statusMeta("")).toEqual({ label: "Bilinmiyor", tone: "neutral" });
    expect(DEFAULT_STATUS_CATALOG).toHaveLength(8);
  });

  it("neden kodları Türkçe etiket + ton; bilinmeyen kod ham metin + nötr", () => {
    expect(reasonMeta("atr_yetersiz")).toMatchObject({ label: "ATR yetersiz", known: true });
    expect(reasonMeta("ust_fitil_tuzagi")?.tone).toBe("danger");
    expect(reasonMeta("rsi_asiri_alim")?.label).toContain("tükenme");
    expect(reasonMeta("mfi_asiri_alim")?.label).toContain("tükenme");
    expect(reasonMeta("baska_bir_sey")).toEqual({ label: "baska_bir_sey", tone: "neutral", known: false });
    expect(reasonMeta("")).toBeNull();
    expect(reasonMeta(null)).toBeNull();
  });

  it("kod gelmezse ham metnin ön ekinden türetir; cümleyi kod saymaz", () => {
    expect(deriveReasonCode(null, "atr_yetersiz:0.20%<0.25%")).toBe("atr_yetersiz");
    expect(deriveReasonCode(null, "skor tabanı altı (65 < 70)")).toBeNull();
    expect(deriveReasonCode("diger", "x")).toBe("diger");
    expect(deriveReasonCode(null, null)).toBeNull();
  });
});

describe("süzme / sıralama / sınırlama", () => {
  const rows = [
    row({ symbol: "AAATRY", status: "rejected", panelScore: 90 }),
    row({ symbol: "BBBTRY", status: "gated", panelScore: 60 }),
    row({ symbol: "CCCTRY", status: "gated", panelScore: 75 }),
    row({ symbol: "DDDTRY", status: "notified", panelScore: null }),
    row({ symbol: "EEETRY", status: "detected", panelScore: 70 }),
    row({ symbol: "FFFTRY", status: "watch", panelScore: null }),
  ];

  it("duruma ve sembole göre süzer (büyük/küçük harf, _ ve boşluk yok sayılır)", () => {
    expect(filterRows(rows, { status: "gated" }).map((r) => r.symbol)).toEqual(["BBBTRY", "CCCTRY"]);
    expect(filterRows(rows, { query: " cc_c " }).map((r) => r.symbol)).toEqual(["CCCTRY"]);
    expect(filterRows(rows, { status: "gated", query: "bbb" }).map((r) => r.symbol)).toEqual(["BBBTRY"]);
    expect(filterRows(rows, {})).toHaveLength(6);
    expect(filterRows(rows, { query: "ZZZ" })).toEqual([]);
    expect(filterRows([], { status: "gated" })).toEqual([]);
  });

  it("önce bildirildi/tespit/kapıya takıldı, sonra skora göre azalan; skorsuz sona; girdiyi bozmaz", () => {
    const sorted = sortRows(rows).map((r) => r.symbol);
    expect(sorted).toEqual(["DDDTRY", "EEETRY", "CCCTRY", "BBBTRY", "AAATRY", "FFFTRY"]);
    expect(rows[0].symbol).toBe("AAATRY");
  });

  it("en çok N satır çizer ve gizlenen sayıyı bildirir", () => {
    const many = Array.from({ length: 200 }, (_, i) => i);
    expect(MAX_RENDER_ROWS).toBe(150);
    const { shown, hidden } = limitRows(many);
    expect(shown).toHaveLength(150);
    expect(hidden).toBe(50);
    expect(limitRows([1, 2, 3])).toEqual({ shown: [1, 2, 3], hidden: 0 });
    expect(limitRows([1, 2, 3], 0)).toEqual({ shown: [], hidden: 3 });
  });
});

describe("sayaç özeti ve tarama gezinme", () => {
  it("katalog/yerleşik sıraya göre, yalnız sayısı > 0 olanları verir; bilinmeyen durum sonda", () => {
    const scan = normalizeResponse({
      scans: [{ scan_no: 1, counts: { rejected: 80, notified: 1, yeni: 2, watch: 0, detected: 2 }, rows: [] }],
    }).scans[0];
    const s = statusSummary(scan);
    expect(s.map((x) => x.status)).toEqual(["notified", "detected", "rejected", "yeni"]);
    expect(s[0]).toMatchObject({ label: "Bildirildi", tone: "success", count: 1 });
    expect(s[3]).toMatchObject({ label: "yeni", tone: "neutral", count: 2 });
    expect(statusSummary(null)).toEqual([]);
  });

  it("seçili dizin ve adım: null = en yeni, bulunamazsa 0, sınırlarda kenetlenir", () => {
    const scans = normalizeResponse(RAW).scans; // [1234, 1233]
    expect(selectedIndex(scans, null)).toBe(0);
    expect(selectedIndex(scans, 1233)).toBe(1);
    expect(selectedIndex(scans, 9999)).toBe(0);
    expect(selectedIndex([], 1)).toBe(-1);
    expect(stepIndex(0, 1, 2)).toBe(1);
    expect(stepIndex(1, 1, 2)).toBe(1);
    expect(stepIndex(0, -1, 2)).toBe(0);
    expect(stepIndex(0, 1, 0)).toBe(-1);
  });

  it("tarama etiketi Türkiye saatiyle", () => {
    // 1_792_290_000 = 2026-10-18 02:20:00 UTC -> 05:20 Europe/Istanbul (UTC+3)
    const s = normalizeResponse(RAW).scans[0];
    expect(scanLabel(s)).toBe("#1234 · 18.10 05:20");
  });
});

describe("biçimleyiciler", () => {
  it("null/geçersiz için '—', 0 meşru değer", () => {
    expect(fmtScore(null)).toBe("—");
    expect(fmtScore(0)).toBe("0,0");
    expect(fmtScore(71.5)).toBe("71,5");
    expect(fmtPctValue(null)).toBe("—");
    expect(fmtPctValue(0.41)).toBe("0,41%");
    expect(fmtPctValue(0.9, 2, true)).toBe("+0,90%");
    expect(fmtPctValue(-0.6, 2, true)).toBe("-0,60%");
    expect(fmtPctValue(-0.0001, 2, true)).toBe("0,00%");
    expect(fmtRatio(1.84)).toBe("1,8×");
    expect(fmtRatio(undefined)).toBe("—");
    expect(fmtHorizon(5)).toBe("5 dk");
    expect(fmtHorizon(null)).toBe("—");
    expect(fmtRsiMfi(58.2, 61)).toBe("58 / 61");
    expect(fmtRsiMfi(null, 61)).toBe("— / 61");
    expect(fmtRsiMfi(null, null)).toBe("—");
  });

  it("havuz, eşik ve risk-off özetleri", () => {
    expect(poolLine([])).toBe("—");
    expect(poolLine([{ horizon: 5, count: 105 }, { horizon: 15, count: 99 }])).toBe("5 dk · 105 sembol, 15 dk · 99 sembol");
    expect(thresholdLabel(71.5)).toBe("Panel eşiği 71,5");
    expect(thresholdLabel(null)).toBe("Panel eşiği —");
    expect(riskBadge({ riskOff: true, riskOffUnknown: false }).tone).toBe("danger");
    expect(riskBadge({ riskOff: false, riskOffUnknown: true }).tone).toBe("caution");
    expect(riskBadge({ riskOff: true, riskOffUnknown: true }).tone).toBe("caution");
    expect(riskBadge({ riskOff: false, riskOffUnknown: false }).tone).toBe("success");
  });

  it("sorgu dizesi ve hata metinleri", () => {
    expect(buildQuery()).toBe("limit=10");
    expect(buildQuery({ limit: 5, symbol: "ABC", status: "gated" })).toBe("limit=5&symbol=ABC&status=gated");
    expect(errorMessage(403)).toBe("Bu pencere yalnızca yönetici içindir.");
    expect(errorMessage(401)).toContain("yalnızca yönetici");
    expect(errorMessage(500, "Sunucu hatası")).toBe("Sunucu hatası");
    expect(errorMessage(null, "  ")).toBe("Radar tarama logları alınamadı");
  });
});
