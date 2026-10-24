/**
 * Günün ilk bildirimi sekmesi (2026-10-25): tablo satırları, renk tonu, durum rozeti ve boş durum.
 * jsdom yok; `DailyFirstTable` `react-dom/server` ile statik HTML'e çevrilir (vitest node ortamı).
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import {
  DailyFirstTable,
  fmtIstanbulClock,
  maeTone,
  mfeTone,
  pctSigned,
  summaryLine,
  type DailyFirstReport,
} from "./DailyFirstNotificationTab";

// 2026-10-24 00:00 Europe/Istanbul = 2026-10-23 21:00 UTC
const DAY_START = Date.UTC(2026, 9, 23, 21, 0, 0) / 1000;

const report: DailyFirstReport = {
  paper_only: true,
  generated_at: DAY_START + 3600,
  days: 7,
  since_day_key: "2026-10-18",
  today_day_key: "2026-10-24",
  mae_sign: "negative",
  total: 3,
  summary: [
    { day_key: "2026-10-24", count: 2, measured: 2, finalized: 0, avg_mfe_pct: 1.75, avg_mae_pct: -1.5, mfe_ge_1_share_pct: 50 },
    { day_key: "2026-10-23", count: 1, measured: 1, finalized: 1, avg_mfe_pct: 0.8, avg_mae_pct: -4.2, mfe_ge_1_share_pct: 0 },
  ],
  rows: [
    { id: 3, symbol: "BTCTRY", day_key: "2026-10-24", first_notification_id: 9, first_ts: DAY_START + 10 * 3600 + 5 * 60,
      first_price: 100, mfe_pct: 3.0, mfe_ts: DAY_START + 12 * 3600 + 30 * 60, mae_pct: -1.0, mae_ts: DAY_START + 11 * 3600,
      last_tracked_ts: DAY_START + 13 * 3600, finalized: false },
    { id: 4, symbol: "TREE_TRY", day_key: "2026-10-24", first_notification_id: 10, first_ts: DAY_START + 9 * 3600,
      first_price: 0.5, mfe_pct: 0.5, mfe_ts: DAY_START + 9 * 3600 + 60, mae_pct: -2.0, mae_ts: DAY_START + 10 * 3600,
      last_tracked_ts: DAY_START + 13 * 3600, finalized: false },
    { id: 1, symbol: "ETHTRY", day_key: "2026-10-23", first_notification_id: 2, first_ts: DAY_START - 7200,
      first_price: 50, mfe_pct: 0.8, mfe_ts: DAY_START - 7000, mae_pct: -4.2, mae_ts: DAY_START - 7100,
      last_tracked_ts: DAY_START - 60, finalized: true },
  ],
};

describe("biçimleyiciler", () => {
  it("İstanbul saati SS:dd", () => {
    expect(fmtIstanbulClock(DAY_START + 10 * 3600 + 5 * 60)).toBe("10:05");
    expect(fmtIstanbulClock(null)).toBe("—");
    expect(fmtIstanbulClock(0)).toBe("—");
  });

  it("yüzde işareti ve ton: MFE yeşil, düşüş kırmızı", () => {
    expect(pctSigned(3)).toBe("+3.00%");
    expect(pctSigned(-1.234)).toBe("-1.23%");
    expect(pctSigned(0)).toBe("0.00%");
    expect(pctSigned(null)).toBe("—");
    expect(mfeTone(3)).toContain("text-neon-green");
    expect(mfeTone(0)).toBe("text-white");
    expect(mfeTone(null)).toBe("text-bunker-muted");
    expect(maeTone(-1)).toBe("text-neon-red");
    expect(maeTone(0)).toBe("text-white");
  });

  it("gün özeti satırı", () => {
    expect(summaryLine(report.summary[0])).toBe("2 sembol · ort. MFE +1.75% · ort. maks düşüş -1.50% · MFE ≥ %1: %50 (2 ölçülen)");
    expect(summaryLine({ day_key: "2026-10-22", count: 1, measured: 0, finalized: 0, avg_mfe_pct: null, avg_mae_pct: null, mfe_ge_1_share_pct: null }))
      .toBe("1 sembol · henüz ölçüm yok");
    expect(summaryLine(report.summary[1])).toContain("gün kapandı");
  });
});

describe("DailyFirstTable", () => {
  const html = renderToStaticMarkup(<DailyFirstTable report={report} />);

  it("gün başlıkları en yeni önce ve özet satırı", () => {
    const todayIdx = html.indexOf('data-day="2026-10-24"');
    const yesterdayIdx = html.indexOf('data-day="2026-10-23"');
    expect(todayIdx).toBeGreaterThanOrEqual(0);
    expect(yesterdayIdx).toBeGreaterThan(todayIdx);
    expect(html).toContain("BUGÜN");
    expect(html).toContain("2 sembol · ort. MFE +1.75%");
  });

  it("sütun başlıkları", () => {
    for (const h of ["Sembol", "İlk bildirim (saat)", "Fiyat", "MFE %", "MFE saati", "Maks düşüş %", "Durum"]) {
      expect(html).toContain(h);
    }
  });

  it("satırlar: saat, MFE/MAE değer ve tonu, durum rozeti", () => {
    expect(html).toContain("BTCTRY");
    expect(html).toContain("TREETRY"); // SymbolLink alt çizgiyi düşürür
    expect(html).toContain("10:05");  // BTC ilk bildirim saati (İstanbul)
    expect(html).toContain("12:30");  // BTC MFE saati
    expect(html).toContain("+3.00%");
    expect(html).toContain("-1.00%");
    expect(html).toContain("-4.20%");
    expect(html).toMatch(/text-neon-green font-bold[^>]*>\+3\.00%/);
    expect(html).toMatch(/text-neon-red[^>]*>-1\.00%/);
    expect(html).toContain(">izleniyor<");
    expect(html).toContain(">tamamlandı<");
    expect((html.match(/>izleniyor</g) ?? []).length).toBe(2);
    expect((html.match(/>tamamlandı</g) ?? []).length).toBe(1);
  });

  it("boş rapor → 'henüz veri yok'", () => {
    const empty = renderToStaticMarkup(<DailyFirstTable report={{ ...report, rows: [], summary: [], total: 0 }} />);
    expect(empty).toContain("henüz veri yok");
    expect(empty).not.toContain("<table");
  });
});
