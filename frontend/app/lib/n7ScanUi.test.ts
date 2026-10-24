// `lib/n7ScanUi.ts` — N7 TARAMA sekmesinin saf yardımcıları.

import { describe, it, expect } from "vitest";
import {
  elapsedSeconds,
  fmtPct,
  fmtRatioX,
  fmtScore,
  fmtSignedPct,
  isAlreadyRunning,
  normalizeState,
  pctTone,
  statusLine,
  stripTry,
  summaryLine,
  topPicks,
} from "./n7ScanUi";

const pick = (sym: string, score: number | null) => ({
  sym, px: 1, score, r1: 1, r2: 2, r4: 3, r24: 4, vr: 2, vwap_rel: 0.5, room: 3, base: 40, hl: 1, atr15: 0.4, qv24: 1e6,
});

describe("normalizeState", () => {
  it("eksik/bozuk gövdeyi idle + boş ilerleme olarak okur", () => {
    const s = normalizeState(null);
    expect(s.status).toBe("idle");
    expect(s.progress).toEqual({ done: 0, total: 0 });
    expect(s.result).toBeNull();
    expect(s.top).toBe(3);
  });

  it("bilinmeyen durumu idle'a düşürür, picked satırlarını sayıya çevirir, sembolsüz satırı atar", () => {
    const s = normalizeState({
      status: "weird",
      progress: { done: "12", total: 212 },
      result: { cutoff_ms: 1_700_000_000_000, universe: "212", picked: [{ sym: "abctry", px: "1.5", score: "77.2" }, { px: 2 }] },
    });
    expect(s.status).toBe("idle");
    expect(s.progress).toEqual({ done: 12, total: 212 });
    expect(s.result?.universe).toBe(212);
    expect(s.result?.picked).toHaveLength(1);
    expect(s.result?.picked[0]).toMatchObject({ sym: "ABCTRY", px: 1.5, score: 77.2, r1: null });
  });
});

describe("topPicks", () => {
  it("skora göre azalan sıralar ve 3 ile keser; skoru olmayan sona gider", () => {
    const result = normalizeState({
      status: "done",
      result: { picked: [pick("ATRY", 50), pick("BTRY", null), pick("CTRY", 90), pick("DTRY", 70)] },
    }).result;
    expect(topPicks(result).map((p) => p.sym)).toEqual(["CTRY", "DTRY", "ATRY"]);
    expect(topPicks(null)).toEqual([]);
  });
});

describe("biçimler", () => {
  it("TRY son ekini kırpar", () => {
    expect(stripTry("BTCTRY")).toBe("BTC");
    expect(stripTry("TRY")).toBe("TRY");
    expect(stripTry("BTCUSDT")).toBe("BTCUSDT");
  });

  it("işaretli yüzde / oran / skor — veri yok '—'", () => {
    expect(fmtSignedPct(2.44)).toBe("+2,4%");
    expect(fmtSignedPct(-0.8)).toBe("-0,8%");
    expect(fmtSignedPct(null)).toBe("—");
    expect(fmtPct(3.25)).toBe("3,3%");
    expect(fmtRatioX(4)).toBe("4,0×");
    expect(fmtScore(77.26)).toBe("77,3");
    expect(fmtScore(undefined)).toBe("—");
  });

  it("yüzde tonu: pozitif yeşil, negatif kırmızı, yok nötr", () => {
    expect(pctTone(1)).toBe("text-neon-green");
    expect(pctTone(-1)).toBe("text-neon-red");
    expect(pctTone(null)).toBe("text-bunker-muted");
  });
});

describe("statusLine", () => {
  it("çalışırken ilerleme ve geçen süre", () => {
    const t0 = 1_761_000_000_000; // epoch ms (gerçekçi: >10^10, saniye sanılmaz)
    const s = normalizeState({ status: "running", started_at: t0, progress: { done: 123, total: 212 } });
    const line = statusLine(s, t0 + 10_000);
    expect(line.tone).toBe("running");
    expect(line.text).toBe("TARANIYOR · 123 / 212 sembol · 10 sn");
    expect(elapsedSeconds(s, t0 + 10_000)).toBe(10);
    // Backend saniye gönderse de aynı sonuç
    const sec = normalizeState({ status: "running", started_at: t0 / 1000, progress: { done: 0, total: 0 } });
    expect(elapsedSeconds(sec, t0 + 4_000)).toBe(4);
    expect(statusLine(sec, t0 + 4_000).text).toBe("TARANIYOR · başlatılıyor… · 4 sn");
  });

  it("hata, tamamlandı ve boş durumlar", () => {
    expect(statusLine(normalizeState({ status: "error", error: "kaynak yok" }), 0)).toEqual({ text: "HATA · kaynak yok", tone: "error" });
    const done = normalizeState({ status: "done", result: { picked: [pick("ATRY", 1), pick("BTRY", 2)] } });
    expect(statusLine(done, 0)).toEqual({ text: "TAMAMLANDI · 2 sembol seçildi", tone: "ok" });
    expect(statusLine(normalizeState({}), 0).tone).toBe("muted");
  });
});

describe("summaryLine / isAlreadyRunning", () => {
  it("kesit · evren · aday · sn", () => {
    const r = normalizeState({ status: "done", result: { cutoff_ms: 5, universe: 212, candidates: 40, elapsed_s: 12.6 } }).result;
    expect(summaryLine(r, () => "14:35")).toBe("Kesit 14:35 · evren 212 · aday 40 · 13 sn");
    expect(summaryLine(null, () => "x")).toBe("");
  });

  it("409 'zaten çalışıyor' hatayı tanır", () => {
    expect(isAlreadyRunning(new Error("Tarama zaten çalışıyor"))).toBe(true);
    expect(isAlreadyRunning(new Error("API 409"))).toBe(true);
    expect(isAlreadyRunning(new Error("API 500"))).toBe(false);
  });
});
