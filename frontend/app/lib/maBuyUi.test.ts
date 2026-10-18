// `lib/maBuyUi.ts` — MA BUY sinyal kaydı sayfasının saf yardımcıları.

import { describe, it, expect } from "vitest";
import {
  buildQuery,
  countdownLabel,
  errorMessage,
  filterBySymbol,
  fmtPct,
  fmtShare,
  fmtThreshold,
  fmtTrTime,
  hitsGrossFloor,
  normalizeResponse,
  normalizeSignal,
  num,
  openCountdown,
  ruleLabel,
  signalTimeSec,
  sortSignals,
  statusChip,
  timeframeLabel,
  trackerLine,
  type MaBuySignal,
} from "./maBuyUi";

function sig(over: Partial<MaBuySignal> = {}): MaBuySignal {
  return {
    id: 1,
    symbol: "SANDTRY",
    timeframe: "5m",
    rules: ["fast_cross_mid"],
    barCloseMs: 1_792_290_000_000,
    detectedAt: 1_792_290_003.2,
    signalPrice: 3.004,
    emaFast: 3.01,
    emaMid: 3.0,
    emaSlow: 2.95,
    status: "done",
    maxRise5: 0.4,
    maxRise10: 0.9,
    maxRise15: 1.3,
    maxDrop15: -0.6,
    close15: 0.5,
    peakBarMinutes: 10,
    evaluatedAt: 1_792_290_900.1,
    ...over,
  };
}

describe("maBuyUi — num / biçimleyiciler", () => {
  it("num: null/boş/NaN/boolean null döner, 0 korunur", () => {
    expect(num(null)).toBeNull();
    expect(num(undefined)).toBeNull();
    expect(num("")).toBeNull();
    expect(num("abc")).toBeNull();
    expect(num(true)).toBeNull();
    expect(num(NaN)).toBeNull();
    expect(num(0)).toBe(0);
    expect(num("1.5")).toBe(1.5);
  });

  it("fmtPct: TR ondalık, işaret, veri yoksa tire", () => {
    expect(fmtPct(1.3)).toBe("+1,30%");
    expect(fmtPct(-0.6)).toBe("-0,60%");
    expect(fmtPct(0)).toBe("0,00%");
    expect(fmtPct(-0.0001)).toBe("0,00%");
    expect(fmtPct(1.705, 3)).toBe("+1,705%");
    expect(fmtPct(0.92, 2, false)).toBe("0,92%");
    expect(fmtPct(null)).toBe("—");
    expect(fmtPct(undefined)).toBe("—");
  });

  it("fmtShare ve fmtThreshold", () => {
    expect(fmtShare(0.18)).toBe("%18");
    expect(fmtShare(0.1234, 1)).toBe("%12,3");
    expect(fmtShare(null)).toBe("—");
    expect(fmtThreshold(1.705)).toBe("%1,705");
    expect(fmtThreshold(2)).toBe("%2");
    expect(fmtThreshold(1)).toBe("%1");
  });

  it("fmtTrTime: Europe/Istanbul (UTC+3), gün.ay ss:dd", () => {
    const utc = Date.UTC(2026, 9, 17, 23, 20) / 1000; // 17.10 23:20 UTC -> 18.10 02:20 TR
    expect(fmtTrTime(utc)).toBe("18.10 02:20");
    expect(fmtTrTime(utc * 1000)).toBe("18.10 02:20"); // ms de kabul
    expect(fmtTrTime(null)).toBe("—");
    expect(fmtTrTime(0)).toBe("—");
    expect(fmtTrTime(NaN)).toBe("—");
  });
});

describe("maBuyUi — kural etiketi, eşik, geri sayım", () => {
  it("ruleLabel", () => {
    expect(ruleLabel("fast_cross_mid")).toBe("Turuncu maviyi yukarı kesti");
    expect(ruleLabel("mid_cross_slow")).toBe("Mavi morun üstüne çıktı");
    expect(ruleLabel("yeni_kural")).toBe("yeni_kural");
    expect(ruleLabel(null)).toBe("");
  });

  it("hitsGrossFloor: eşik dahil, veri yoksa false", () => {
    expect(hitsGrossFloor({ maxRise15: 1.705 }, 1.705)).toBe(true);
    expect(hitsGrossFloor({ maxRise15: 2.4 }, 1.705)).toBe(true);
    expect(hitsGrossFloor({ maxRise15: 1.7 }, 1.705)).toBe(false);
    expect(hitsGrossFloor({ maxRise15: null }, 1.705)).toBe(false);
    expect(hitsGrossFloor({ maxRise15: 5 }, null)).toBe(false);
    expect(hitsGrossFloor({ maxRise15: 0 }, 0)).toBe(true);
  });

  it("openCountdown: 15 dk - geçen süre, 0'a kenetlenir", () => {
    const closeMs = 1_792_290_000_000;
    const c0 = openCountdown({ barCloseMs: closeMs }, 1_792_290_000 + 300);
    expect(c0?.remainingSec).toBe(600);
    expect(c0?.label).toBe("10 dk 00 sn");
    expect(openCountdown({ barCloseMs: closeMs }, 1_792_290_000)?.remainingSec).toBe(900);
    expect(openCountdown({ barCloseMs: closeMs }, 1_792_290_000 + 2000)?.remainingSec).toBe(0);
    expect(openCountdown({ barCloseMs: closeMs }, 1_792_290_000 + 2000)?.label).toBe("birazdan");
    expect(openCountdown({ barCloseMs: null }, 1_792_290_000)).toBeNull();
  });

  it("countdownLabel", () => {
    expect(countdownLabel(725)).toBe("12 dk 05 sn");
    expect(countdownLabel(45)).toBe("45 sn");
    expect(countdownLabel(0)).toBe("birazdan");
    expect(countdownLabel(-5)).toBe("birazdan");
  });

  it("statusChip", () => {
    const now = 1_792_290_000 + 120;
    expect(statusChip(sig({ status: "open" }), now)).toEqual({ label: "ölçülüyor · 13 dk 00 sn", tone: "wait" });
    expect(statusChip(sig({ status: "open", barCloseMs: null }), now).label).toBe("ölçülüyor");
    expect(statusChip(sig({ status: "no_data" }), now)).toEqual({ label: "veri yok", tone: "mute" });
    expect(statusChip(sig({ status: "done" }), now).label).toBe("ölçüldü");
  });
});

describe("maBuyUi — sıralama ve süzme", () => {
  const a = sig({ id: 1, symbol: "AAATRY", barCloseMs: 1_000_000, maxRise15: 0.5 });
  const b = sig({ id: 2, symbol: "BBBTRY", barCloseMs: 3_000_000, maxRise15: 2.0 });
  const c = sig({ id: 3, symbol: "CCCTRY", barCloseMs: 2_000_000, maxRise15: null, status: "open" });

  it("zamana göre: yeni önce / eski önce", () => {
    expect(sortSignals([a, b, c], "time", "desc").map((x) => x.id)).toEqual([2, 3, 1]);
    expect(sortSignals([a, b, c], "time", "asc").map((x) => x.id)).toEqual([1, 3, 2]);
  });

  it("15 dk yükselişe göre: boşlar her iki yönde sonda", () => {
    expect(sortSignals([a, b, c], "rise15", "desc").map((x) => x.id)).toEqual([2, 1, 3]);
    expect(sortSignals([a, b, c], "rise15", "asc").map((x) => x.id)).toEqual([1, 2, 3]);
  });

  it("girdi dizisini değiştirmez", () => {
    const input = [a, b, c];
    sortSignals(input, "time", "desc");
    expect(input.map((x) => x.id)).toEqual([1, 2, 3]);
  });

  it("filterBySymbol: büyük/küçük harf ve alt çizgi duyarsız", () => {
    expect(filterBySymbol([a, b, c], "bb").map((x) => x.id)).toEqual([2]);
    expect(filterBySymbol([a, b, c], "  ").length).toBe(3);
    expect(filterBySymbol([a, b, c], "a_a").map((x) => x.id)).toEqual([1]);
    expect(filterBySymbol([a, b, c], "zzz")).toEqual([]);
  });

  it("buildQuery", () => {
    expect(buildQuery({ days: 7 })).toBe("days=7&limit=500");
    expect(buildQuery({ days: 3, rule: "mid_cross_slow", status: "done", limit: 100 })).toBe(
      "days=3&rule=mid_cross_slow&status=done&limit=100",
    );
  });
});

describe("maBuyUi — normalizeResponse", () => {
  it("tam yanıtı çevirir", () => {
    const r = normalizeResponse({
      ok: true,
      days: 7,
      total: 2,
      items: [
        {
          id: 1, symbol: "sand_try", timeframe: "5m", rules: ["fast_cross_mid", "mid_cross_slow"],
          bar_close_ms: 1792290000000, detected_at: 1792290003.2, signal_price: 3.004,
          status: "done", max_rise_5m_pct: 0.4, max_rise_10m_pct: 0.9, max_rise_15m_pct: 1.3,
          max_drop_15m_pct: -0.6, close_15m_pct: 0.5, peak_bar_minutes: 10,
        },
      ],
      summary: {
        count: 123, evaluated: 100, pending: 20, avg_max_rise_15m_pct: 0.92, median_max_rise_15m_pct: 0.7,
        avg_max_drop_15m_pct: -0.8, avg_close_15m_pct: 0.1, gross_floor_pct: 1.705,
        thresholds: [{ min_pct: 1.0, n: 40, share: 0.4 }, { min_pct: "x" }, "bozuk"],
        by_rule: { fast_cross_mid: { count: 70, evaluated: 60, avg_max_rise_15m_pct: 0.8, median_max_rise_15m_pct: 0.6 } },
      },
      tracker: { enabled: true, timeframes: ["5m"], scope: "active", last_scan_at: 1792290003, last_scan_symbols: 7, last_error: null },
    });
    expect(r.total).toBe(2);
    expect(r.items).toHaveLength(1);
    expect(r.items[0].symbol).toBe("SANDTRY");
    expect(r.items[0].rules).toEqual(["fast_cross_mid", "mid_cross_slow"]);
    expect(r.items[0].maxRise15).toBe(1.3);
    expect(r.items[0].emaFast).toBeNull();
    expect(r.summary.count).toBe(123);
    expect(r.summary.grossFloorPct).toBe(1.705);
    expect(r.summary.thresholds).toEqual([{ minPct: 1, n: 40, share: 0.4 }]);
    expect(r.summary.byRule.fast_cross_mid.avgMaxRise15).toBe(0.8);
    expect(r.tracker.lastScanSymbols).toBe(7);
    expect(r.tracker.lastError).toBeNull();
  });

  it("boş / bozuk girdide patlamaz, null'ı 0'a çevirmez", () => {
    for (const bad of [null, undefined, 5, "x", [], {}]) {
      const r = normalizeResponse(bad);
      expect(r.items).toEqual([]);
      expect(r.summary.count).toBe(0);
      expect(r.summary.avgMaxRise15).toBeNull();
      expect(r.summary.thresholds).toEqual([]);
      expect(r.tracker.lastScanAt).toBeNull();
      expect(r.tracker.enabled).toBeNull();
    }
  });

  it("sinyal: eksik alan null, bilinmeyen durum no_data, sembolsüz satır atlanır", () => {
    const s = normalizeSignal({ id: 9, symbol: "ABCTRY", status: "weird", max_rise_15m_pct: null });
    expect(s?.status).toBe("no_data");
    expect(s?.maxRise15).toBeNull();
    expect(s?.rules).toEqual([]);
    expect(normalizeSignal({ id: 1 })).toBeNull();
    expect(normalizeSignal("x")).toBeNull();
    const r = normalizeResponse({ items: [{ id: 1 }, { id: 2, symbol: "XTRY", status: "open" }] });
    expect(r.items.map((x) => x.id)).toEqual([2]);
    expect(r.summary.pending).toBe(1); // summary yoksa kalemlerden türetilir
  });

  it("trackerLine ve errorMessage", () => {
    const t = normalizeResponse({ tracker: { last_scan_at: Date.UTC(2026, 9, 17, 23, 20) / 1000, last_scan_symbols: 7, last_error: "boom" } }).tracker;
    expect(trackerLine(t)).toBe("Son tarama: 18.10 02:20 · 7 sembol · hata: boom");
    expect(trackerLine(normalizeResponse({}).tracker)).toBe("Son tarama: henüz yok");
    expect(errorMessage(403)).toBe("Bu sayfa yalnızca yönetici içindir.");
    expect(errorMessage(401)).toContain("giriş");
    expect(errorMessage(500, "sunucu hatası")).toBe("sunucu hatası");
    expect(errorMessage(500)).toBe("MA BUY sinyalleri alınamadı");
  });
});

describe("maBuyUi — mum zamanı", () => {
  it("gösterilen zaman yakalanma anı değil, sinyal mumunun açılışıdır", () => {
    // mum 05:40-05:45 (kapanış 05:45); tarayıcı 05:49'da yakaladı
    const close = 1_792_290_000_000;
    const t = signalTimeSec({ barCloseMs: close, detectedAt: close / 1000 + 240, timeframe: "5m" });
    expect(t).toBe(close / 1000 - 300);
    expect(signalTimeSec({ barCloseMs: close, detectedAt: null, timeframe: "15m" })).toBe(close / 1000 - 900);
    expect(signalTimeSec({ barCloseMs: null, detectedAt: 123, timeframe: "5m" })).toBe(123);
  });
});

describe("maBuyUi — zaman dilimi", () => {
  it("etiket ve sorgu", () => {
    expect(timeframeLabel("1m")).toBe("M1");
    expect(timeframeLabel("5m")).toBe("M5");
    expect(timeframeLabel("15m")).toBe("M15");
    expect(timeframeLabel("")).toBe("—");
    expect(buildQuery({ days: 7, timeframe: "15m" })).toContain("timeframe=15m");
    expect(buildQuery({ days: 7 })).not.toContain("timeframe");
  });
});

import { formatTargetPct, formatTfList, parseTargetPct, parseTfList } from "./maBuyUi";

describe("Ayarlar > MA BUY yardımcıları", () => {
  it("TF listesi geçersizleri atar ve sabit sırayla yazar", () => {
    const s = parseTfList("5m, 4h,1m");
    expect([...s].sort()).toEqual(["1m", "5m"]);
    expect(formatTfList(new Set(["5m", "1m"]))).toBe("1m,5m");
    expect(formatTfList(new Set())).toBe("");
  });
  it("hedef % dizesi gidiş-dönüş korunur, boş değer yazılmaz", () => {
    const m = parseTargetPct("1m:1,5m:1.5,15m:x");
    expect(m).toEqual({ "1m": 1, "5m": 1.5 });
    expect(formatTargetPct({ ...m, "15m": 2 })).toBe("1m:1,5m:1.5,15m:2");
    expect(formatTargetPct({ "1m": NaN, "5m": 0 })).toBe("");
  });
});

import { changeSinceSignal, paperStatusChip, parseRecent } from "./maBuyUi";

describe("gönderilen MA BUY bildirimleri listesi", () => {
  it("yanıtı ayrıştırır, bozuk satırı atar", () => {
    const items = parseRecent({ items: [
      { id: 1, symbol: "senttry", timeframe: "5m", rules: ["fast_cross_mid"], signal_price: "1.06", notified_at: 100, paper_status: "acildi" },
      { id: null, symbol: "X" },
      { id: 2, symbol: "", timeframe: "1m" },
    ] });
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ symbol: "SENTTRY", signalPrice: 1.06, paperStatus: "acildi" });
    expect(parseRecent(null)).toEqual([]);
  });
  it("paper durumu ve değişim", () => {
    expect(paperStatusChip("acildi")?.tone).toBe("good");
    expect(paperStatusChip("symbol_dedup")?.text).toBe("Paper açılmadı");
    expect(paperStatusChip(null)).toBeNull();
    expect(changeSinceSignal(100, 101)).toBeCloseTo(1);
    expect(changeSinceSignal(null, 101)).toBeNull();
  });
});
