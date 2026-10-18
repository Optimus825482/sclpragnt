// Saf sinyal/gösterge matematiği: frontend-friendly simplification of backend rules, React'ten bağımsız.
// Bu modül yalnızca saf fonksiyon ve tip dışa aktarır; DOM veya state erişimi yoktur.
// Not: Mum formasyonları backend ile aynı formül kullanmaz; görsel işaretleyiciler için basitleştirilmiştir.

import { rqkColors } from "./rqk";

export type Bar = { time: number; open: number; high: number; low: number; close: number; volume: number };

export type PatternMarker = { time: number; type: "buy" | "sell"; text: string };

// Spot yürütme simülasyonu sabitleri (grafik işaretleyicileri için basitleştirilmiş;
// gerçek backend yürütmesiyle birebir aynı değildir).
const SPOT_TARGET_PCT = 0.03; // display simulation only
const SPOT_STOP_PCT = 0.012;  // match backend HARD_STOP_LOSS_PCT

export const patternDescriptions: Record<string, string> = {
    "BOĞA YUTAN": "Önceki ayı gövdesini tamamen saran güçlü boğa mumu; alıcı baskısı artıyor.",
    "AYI YUTAN": "Önceki boğa gövdesini tamamen saran güçlü ayı mumu; satıcı baskısı artıyor.",
    "BOĞA HARAMİ": "Büyük ayı gövdesi içinde küçük boğa gövdesi; düşüş momentumu zayıflıyor.",
    "AYI HARAMİ": "Büyük boğa gövdesi içinde küçük ayı gövdesi; yükseliş momentumu zayıflıyor.",
    "ÇEKİÇ": "Düşüş sonrası uzun alt fitil; aşağı fiyatlar reddedildi.",
    "ASILI ADAM": "Yükseliş sonrası uzun alt fitil; satış riski uyarısı.",
    "KAYAN YILDIZ": "Yükseliş sonrası uzun üst fitil; yukarı fiyatlar reddedildi.",
    "TERS ÇEKİÇ": "Düşüş sonrası uzun üst fitil; boğa dönüşü için teyit gerektirir.",
    "DELİCİ ÇİZGİ": "Ayı mumunun orta noktasını aşan boğa toparlanması.",
    "KARA BULUT": "Boğa mumunun orta noktasının altına inen ayı baskısı.",
    "ÜÇ İÇTE YUKARI": "Boğa haramisi ardından teyit kapanışı; yukarı dönüş yapısı.",
    "ÜÇ İÇTE AŞAĞI": "Ayı haramisi ardından teyit kapanışı; aşağı dönüş yapısı.",
    "SABAH YILDIZI": "Düşüşten sonra üç mumlu boğa dönüşü.",
    "AKŞAM YILDIZI": "Yükselişten sonra üç mumlu ayı dönüşü."
};
export const strongCandlestickPatterns = (bars: Bar[]): PatternMarker[] => {
    const out: PatternMarker[] = [];
    // Frontend-friendly simplification of backend rules.
    // Son mum WebSocket ile hâlâ değişebilir; yalnız tamamlanmış mumlar üzerinde
    // formasyon üretmek repaint ve yanlış pozitifleri engeller.
    const closedBars = bars.slice(0, -1);
    const metrics = (bar: Bar) => {
        const range = bar.high - bar.low;
        const body = Math.abs(bar.close - bar.open);
        return { range, body, upper: bar.high - Math.max(bar.open, bar.close), lower: Math.min(bar.open, bar.close) - bar.low };
    };
    const bullish = (bar: Bar) => bar.close > bar.open;
    const bearish = (bar: Bar) => bar.close < bar.open;
    const add = (bar: Bar, type: PatternMarker["type"], text: string) => out.push({ time: bar.time, type, text });
    const inBody = (value: number, bar: Bar) => value > Math.min(bar.open, bar.close) && value < Math.max(bar.open, bar.close);
    const trends = (index: number) => ({
        down: index >= 3 && closedBars[index - 3].close > closedBars[index - 2].close && closedBars[index - 2].close > closedBars[index - 1].close,
        up: index >= 3 && closedBars[index - 3].close < closedBars[index - 2].close && closedBars[index - 2].close < closedBars[index - 1].close
    });
    for (let i = 0; i < closedBars.length; i++) {
        const current = closedBars[i];
        const currentMetrics = metrics(current);
        if (currentMetrics.range <= Number.EPSILON || currentMetrics.body <= Number.EPSILON) continue;
        const { down, up } = trends(i);
        const material = currentMetrics.body / currentMetrics.range >= 0.10;
        if (!material) continue;

        // Aynı geometri, bağlama göre çekiç veya asılı adamdır.
        const lowerPin = currentMetrics.body / currentMetrics.range <= 0.38
            && currentMetrics.lower >= currentMetrics.body * 2
            && currentMetrics.upper <= currentMetrics.range * 0.20;
        const upperPin = currentMetrics.body / currentMetrics.range <= 0.40
            && currentMetrics.upper >= currentMetrics.body * 2
            && currentMetrics.lower <= currentMetrics.range * 0.20;
        if (lowerPin && down) add(current, "buy", "ÇEKİÇ");
        else if (lowerPin && up) add(current, "sell", "ASILI ADAM");
        else if (upperPin && up) add(current, "sell", "KAYAN YILDIZ");
        else if (upperPin && down) add(current, "buy", "TERS ÇEKİÇ");

        if (i < 1) continue;
        const previous = closedBars[i - 1];
        const previousMetrics = metrics(previous);
        const previousMaterial = previousMetrics.range > Number.EPSILON && previousMetrics.body / previousMetrics.range >= 0.15;
        if (!previousMaterial) continue;
        const previousMid = (previous.open + previous.close) / 2;
        if (down && bearish(previous) && bullish(current) && current.open <= previous.close && current.close >= previous.open) add(current, "buy", "BOĞA YUTAN");
        if (up && bullish(previous) && bearish(current) && current.open >= previous.close && current.close <= previous.open) add(current, "sell", "AYI YUTAN");
        if (down && bearish(previous) && bullish(current) && inBody(current.open, previous) && inBody(current.close, previous) && currentMetrics.body <= previousMetrics.body * .65) add(current, "buy", "BOĞA HARAMİ");
        if (up && bullish(previous) && bearish(current) && inBody(current.open, previous) && inBody(current.close, previous) && currentMetrics.body <= previousMetrics.body * .65) add(current, "sell", "AYI HARAMİ");
        if (down && bearish(previous) && bullish(current) && current.open <= previous.close && current.close > previousMid && current.close < previous.open) add(current, "buy", "DELİCİ ÇİZGİ");
        if (up && bullish(previous) && bearish(current) && current.open >= previous.close && current.close < previousMid && current.close > previous.open) add(current, "sell", "KARA BULUT");

        if (i < 2) continue;
        const first = closedBars[i - 2], middle = previous;
        const firstMetrics = metrics(first), middleMetrics = metrics(middle);
        const smallMiddle = middleMetrics.body <= firstMetrics.body * .45;
        const bullishHarami = bearish(first) && bullish(middle) && inBody(middle.open, first) && inBody(middle.close, first);
        const bearishHarami = bullish(first) && bearish(middle) && inBody(middle.open, first) && inBody(middle.close, first);
        if (down && bullishHarami && bullish(current) && current.close > first.open) add(current, "buy", "ÜÇ İÇTE YUKARI");
        if (up && bearishHarami && bearish(current) && current.close < first.open) add(current, "sell", "ÜÇ İÇTE AŞAĞI");
        if (down && bearish(first) && firstMetrics.body >= firstMetrics.range * .45 && smallMiddle && bullish(current) && current.close > (first.open + first.close) / 2) add(current, "buy", "SABAH YILDIZI");
        if (up && bullish(first) && firstMetrics.body >= firstMetrics.range * .45 && smallMiddle && bearish(current) && current.close < (first.open + first.close) / 2) add(current, "sell", "AKŞAM YILDIZI");
    }
    return out.slice(-80);
};

// EMA hesaplama (backend technical_analysis._ema ile aynı: Wilder smoothing)
export const ema = (values: number[], period: number): number | null => {
    if (values.length < period) return null;
    const alpha = 2 / (period + 1);
    let value = values.slice(0, period).reduce((a, b) => a + b, 0) / period;
    for (let i = period; i < values.length; i++) {
        value = alpha * values[i] + (1 - alpha) * value;
    }
    return value;
};

// RSI hesaplama (backend technical_analysis._rsi ile aynı: Wilder smoothing)
export const rsi = (values: number[], period: number): number | null => {
    if (values.length < period + 1) return null;
    let gain = 0, loss = 0;
    for (let i = 1; i <= period; i++) {
        const d = values[i] - values[i - 1];
        if (d > 0) gain += d; else loss -= d;
    }
    let avgGain = gain / period, avgLoss = loss / period;
    for (let i = period + 1; i < values.length; i++) {
        const d = values[i] - values[i - 1];
        avgGain = (avgGain * (period - 1) + Math.max(d, 0)) / period;
        avgLoss = (avgLoss * (period - 1) + Math.max(-d, 0)) / period;
    }
    if (avgLoss === 0) return avgGain > 0 ? 100 : 50;
    return 100 - 100 / (1 + avgGain / avgLoss);
};

// EMA Pullback sinyalleri: trend + pullback + RSI soğuma → buy; trend bozulması → sell
export const emaPullbackSignals = (bars: Bar[], params: Record<string, any>): { time: number; type: "buy" | "sell" }[] => {
    const emaShort = Math.max(3, Math.round(params.emaShort ?? 9));
    const emaMid = Math.max(5, Math.round(params.emaMid ?? 21));
    const emaTrend = Math.max(10, Math.round(params.emaTrend ?? 50));
    const rsiPeriod = Math.max(2, Math.round(params.rsiPeriod ?? 14));
    if (bars.length < emaTrend + 5) return [];

    const closes = bars.map((b) => b.close);
    const signals: { time: number; type: "buy" | "sell" }[] = [];
    for (let i = emaTrend + 1; i < bars.length; i++) {
        const e9 = ema(closes.slice(0, i + 1), emaShort);
        const e21 = ema(closes.slice(0, i + 1), emaMid);
        const e50 = ema(closes.slice(0, i + 1), emaTrend);
        const r = rsi(closes.slice(0, i + 1), rsiPeriod);
        if (e9 == null || e21 == null || e50 == null || r == null) continue;
        const uptrend = e9 > e21 && e21 > e50;
        const pulledBack = closes[i - 1] <= e21 && closes[i] > e21;
        const cooled = r >= 40 && r <= 55;
        if (uptrend && pulledBack && cooled) signals.push({ time: bars[i].time, type: "buy" });
        else if (e9 < e21) signals.push({ time: bars[i].time, type: "sell" });
    }
    return signals;
};

// VWAP + MACD sinyalleri: fiyat VWAP üstü + MACD pozitif → buy; MACD negatif → sell
export const vwapMacdSignals = (bars: Bar[], params: Record<string, any>): { time: number; type: "buy" | "sell" }[] => {
    const vwapPeriod = Math.max(5, Math.round(params.vwapPeriod ?? 20));
    const fast = Math.max(3, Math.round(params.macdFast ?? 12));
    const slow = Math.max(5, Math.round(params.macdSlow ?? 26));
    const signal = Math.max(2, Math.round(params.macdSignal ?? 9));
    if (bars.length < vwapPeriod + slow + signal) return [];

    const closes = bars.map((b) => b.close);
    const highs = bars.map((b) => b.high);
    const lows = bars.map((b) => b.low);
    const volumes = bars.map((b) => b.volume);

    const macdAt = (i: number): { macd: number; signal: number; hist: number } | null => {
        if (i < slow + signal) return null;
        const slice = closes.slice(0, i + 1);
        const eFast = ema(slice, fast);
        const eSlow = ema(slice, slow);
        if (eFast == null || eSlow == null) return null;
        const macdLine = eFast - eSlow;
        // sinyal çizgisi: macd değerlerinin EMA'sı (basit yaklaşım)
        const macdVals: number[] = [];
        for (let j = slow; j <= i; j++) {
            const ef = ema(closes.slice(0, j + 1), fast);
            const es = ema(closes.slice(0, j + 1), slow);
            if (ef != null && es != null) macdVals.push(ef - es);
        }
        const sig = ema(macdVals, signal);
        if (sig == null) return null;
        return { macd: macdLine, signal: sig, hist: macdLine - sig };
    };

    const signals: { time: number; type: "buy" | "sell" }[] = [];
    for (let i = vwapPeriod + slow + signal; i < bars.length; i++) {
        const tp = highs.slice(i - vwapPeriod + 1, i + 1).map((h, idx) => (h + lows[i - vwapPeriod + 1 + idx] + closes[i - vwapPeriod + 1 + idx]) / 3);
        const vols = volumes.slice(i - vwapPeriod + 1, i + 1);
        const vwap = tp.reduce((a, b, idx) => a + b * vols[idx], 0) / vols.reduce((a, b) => a + b, 0);
        const m = macdAt(i);
        if (!m) continue;
        if (closes[i] > vwap && m.hist > 0 && m.macd > m.signal) signals.push({ time: bars[i].time, type: "buy" });
        else if (m.hist < 0 && m.macd < m.signal) signals.push({ time: bars[i].time, type: "sell" });
    }
    return signals;
};

// CMO hesaplama (backend ile aynı)
export const cmo = (values: number[], period: number): number | null => {
    if (values.length < period + 1) return null;
    let gains = 0, losses = 0;
    for (let i = values.length - period; i < values.length; i++) {
        const d = values[i] - values[i - 1];
        if (d > 0) gains += d; else losses -= d;
    }
    if (gains + losses === 0) return 0;
    return 100 * (gains - losses) / (gains + losses);
};

// Klasik RSI: son kapanışlar üzerinden Wilder yumuşatmalı değer.
export const rsiLast = (bars: Bar[], period = 14): number | null => rsi(bars.map((b) => b.close), period);

// MFI: tipik fiyat × hacim akışıyla 0–100 arası para akışı endeksi.
//
// BACKEND İLE HİZALI (denetim görev 12): `technical_analysis.py:208-222`
//   if neg: 100 - 100/(1 + pos/neg)
//   return 100.0 if pos > 0 else 50.0
//
// Önceki sürüm `if (negative === 0) return 100;` idi: hem `pos == 0 && neg == 0`
// (düz tipik fiyat / sıfır hacim → nötr 50 olmalı, "aşırı alım 100" yanlış
// sinyal) hem de tüm mumların yükseldiği gerçek "aşırı alım" durumunu AYNI
// değerle birleştiriyordu. Artık ayrım korunuyor.
export const mfiLast = (bars: Bar[], period = 14): number | null => {
    if (bars.length < period + 1) return null;
    let positive = 0, negative = 0;
    for (let j = bars.length - period; j < bars.length; j++) {
        const current = (bars[j].high + bars[j].low + bars[j].close) / 3;
        const previous = (bars[j - 1].high + bars[j - 1].low + bars[j - 1].close) / 3;
        const flow = current * bars[j].volume;
        if (current > previous) positive += flow;
        else if (current < previous) negative += flow;
    }
    if (negative) return 100 - 100 / (1 + positive / negative);
    // neg == 0: yalnız `positive > 0` ise gerçek aşırı alım (100). İkisi de 0
    // ise veri nötr → 50 (backend ile aynı).
    return positive > 0 ? 100 : 50;
};

// OBV: kapanış yönüne göre birikimli hacim; mutlak değil değişim hızı anlam taşır.
export const obvLast = (bars: Bar[]): { value: number | null; deltaPct: number | null } => {
    if (bars.length < 2) return { value: null, deltaPct: null };
    let value = 0;
    for (let i = 1; i < bars.length; i++) {
        if (bars[i].close > bars[i - 1].close) value += bars[i].volume;
        else if (bars[i].close < bars[i - 1].close) value -= bars[i].volume;
    }
    // okunabilirlik: büyük değerleri M/K kısaltmasıyla göstermek için ölçek
    const windowBars = Math.min(20, bars.length - 1);
    let windowDelta = 0;
    for (let i = bars.length - windowBars; i < bars.length; i++) {
        if (bars[i].close > bars[i - 1].close) windowDelta += bars[i].volume;
        else if (bars[i].close < bars[i - 1].close) windowDelta -= bars[i].volume;
    }
    const avgVolume = bars.slice(-windowBars).reduce((s, b) => s + b.volume, 0) / windowBars;
    return { value, deltaPct: avgVolume > 0 ? windowDelta / avgVolume : 0 };
};

// CRSI hesaplama = (RSI + StreakRSI + PercentRank) / 3
//
// BACKEND İLE HİZALI (denetim görev 12): `technical_analysis.py:139-143`.
// Önceki sürüm üç yerde sapıyordu:
//
//  1. STREAK RSİ: backend `streak_rsi = 100.0 if down == 0 and up else 50.0 if
//     down == 0 else ...`. Yani hem pozitif hem negatif streak 0 ise NÖTR 50
//     döner. Frontend koşulsuz 100 döndürüyordu → yatay piyasada CRSI ~15
//     pence yukarıda (fiyat hareketi yokken "aşırı alım" izlenimi).
//
//  2. PERCENT RANK: backend FİYAT SEVİYESİ üzerinden hesaplar —
//     `100 * count(closes[-rankPeriod-1:-1] < closes[-1]) / len(window)`.
//     Frontend 1-BAR DEĞİŞİMİ üzerinden `count(Δ_i < Δ_current)` sayıyordu.
//     Bu tamamen farklı bir büyüklük: 1-bar değişim penceresi dar olduğu için
//     yükselen trendde neredeyse daima %100, düşen trendde %0 dönüyordu ve
//     percent rank katkısı sabit bir ofset gibi çalışıyordu.
//
//  3. KABUL KOŞULU: backend `len(closes) < rank_period + rsi_period + 2` ile
//     reddeder. Frontend `rsi_period`'ı hiç saymıyordu → yetersiz veriyle
//     yarım hesaplanmış bir değer üretiyordu.
//
// `values` kapanış serisidir (backend `closes`).
export const crsi = (values: number[], rsiPeriod: number, rankPeriod: number): number | null => {
    if (values.length < rankPeriod + rsiPeriod + 2) return null;
    const r = rsi(values, rsiPeriod);
    if (r == null) return null;
    // streak serisi (backend ile aynı yönlendirme: yukarı pozitif, aşağı negatif)
    const streaks: number[] = [0];
    for (let i = 1; i < values.length; i++) {
        if (values[i] > values[i - 1]) streaks.push(streaks[i - 1] > 0 ? streaks[i - 1] + 1 : 1);
        else if (values[i] < values[i - 1]) streaks.push(streaks[i - 1] < 0 ? streaks[i - 1] - 1 : -1);
        else streaks.push(0);
    }
    // StreakRSI: son `streakPeriod = 2` streak'in pozitif/negatif toplamları
    const recent = streaks.slice(-2);
    const up = recent.reduce((sum, s) => sum + (s > 0 ? s : 0), 0);
    const down = recent.reduce((sum, s) => sum + (s < 0 ? -s : 0), 0);
    const streakRsi = down === 0 ? (up > 0 ? 100 : 50) : 100 - 100 / (1 + up / down);
    // PercentRank: FİYAT SEVİYESİ — son kapanışın, `rankPeriod` geriye
    // (mevcut mum hariç) kaç kapanışın üzerinde olduğu.
    const window = values.slice(-rankPeriod - 1, -1);
    const last = values[values.length - 1];
    const below = window.reduce((count, x) => count + (x < last ? 1 : 0), 0);
    const rank = window.length > 0 ? (below / window.length) * 100 : 0;
    return (r + streakRsi + rank) / 3;
};

// CMO + CRSI Derin Dip sinyalleri: aşırı düşüş → buy; aşırı yükseliş → sell
export const cmoCrsiSignals = (bars: Bar[], params: Record<string, any>): { time: number; type: "buy" | "sell" }[] => {
    const cmoPeriod = Math.max(5, Math.round(params.cmoPeriod ?? 9));
    const rsiPeriod = Math.max(2, Math.round(params.rsiPeriod ?? 3));
    const rankPeriod = Math.max(20, Math.round(params.rankPeriod ?? 100));
    const buyCmo = params.buyCmo ?? -63;
    const buyCrsi = params.buyCrsi ?? 30;
    const sellCmo = params.sellCmo ?? 63;
    const sellCrsi = params.sellCrsi ?? 70;
    if (bars.length < rankPeriod + 2) return [];

    const closes = bars.map((b) => b.close);
    const signals: { time: number; type: "buy" | "sell" }[] = [];
    for (let i = rankPeriod + 1; i < bars.length; i++) {
        const slice = closes.slice(0, i + 1);
        const c = cmo(slice, cmoPeriod);
        const cr = crsi(slice, rsiPeriod, rankPeriod);
        if (c == null || cr == null) continue;
        if (c <= buyCmo && cr <= buyCrsi) signals.push({ time: bars[i].time, type: "buy" });
        else if (c >= sellCmo) signals.push({ time: bars[i].time, type: "sell" });
    }
    return signals;
};

    // ── Rational Quadratic Kernel (id: sling_shot) sinyalleri ────────────────────
    // B/S okları KERNEL RENK DÖNÜŞLERİDİR (rqk.ts tek doğruluk kaynağı):
    //   buy  = çizgi kırmızıdan (düşüş) yeşile (yükseliş) döndüğü bar
    //   sell = çizgi yeşilden kırmızıya döndüğü bar
    // Parametreler indikatör instance'ından gelir (h=8, r=2, smoothColors=false varsayılan);
    // böylece oklar çizgideki renk değişimleriyle birebir örtüşür.
    export type SignalType = "buy" | "sell" | "pre";
    /** 2026-10-18: isteğe bağlı görsel alanlar — verilmezse strateji varsayılanı (ok + "ETİKET BUY/SELL") kullanılır. */
    export type StrategySignal = {
        time: number; type: SignalType;
        text?: string; shape?: "arrowUp" | "arrowDown" | "circle" | "square"; color?: string; size?: number;
        /** true → seri marker'ı yerine sabit piksel boyutlu ROZET (badgeMarkers.ts) çizilir. */
        badge?: boolean;
    };

    export const rqKernelSignals = (bars: Bar[], params: Record<string, any>): { time: number; type: "buy" | "sell" }[] => {
        const { bullish } = rqkColors(bars.map((b) => Number(b.close)), params);
        const out: { time: number; type: "buy" | "sell" }[] = [];
        for (let i = 1; i < bars.length; i++) {
            const cur = bullish[i], prev = bullish[i - 1];
            if (cur == null || prev == null || cur === prev) continue;
            out.push({ time: bars[i].time, type: cur ? "buy" : "sell" });
        }
        return out;
    };

    // Wilder RSI SERİSİ (tohum = ilk `period` değişimin basit ortalaması; son değeri `rsi()` ile aynıdır).
    // İlk `period` bar için null.
    export const rsiSeries = (values: number[], period: number): (number | null)[] => {
        const out: (number | null)[] = values.map(() => null);
        if (values.length < period + 1) return out;
        let gain = 0, loss = 0;
        for (let i = 1; i <= period; i++) {
            const d = values[i] - values[i - 1];
            if (d > 0) gain += d; else loss -= d;
        }
        let avgGain = gain / period, avgLoss = loss / period;
        const toRsi = () => (avgLoss === 0 ? (avgGain > 0 ? 100 : 50) : 100 - 100 / (1 + avgGain / avgLoss));
        out[period] = toRsi();
        for (let i = period + 1; i < values.length; i++) {
            const d = values[i] - values[i - 1];
            avgGain = (avgGain * (period - 1) + Math.max(d, 0)) / period;
            avgLoss = (avgLoss * (period - 1) + Math.max(-d, 0)) / period;
            out[i] = toRsi();
        }
        return out;
    };

    // Stokastik RSI — standart TradingView tanımı (backend araştırması birebir aynalamalı):
    //   rsi[i]   = Wilder RSI(close, rsiLen)            (rsiSeries; ilk rsiLen bar tanımsız)
    //   hi/lo    = rsi'nin son stochLen bardaki (mevcut dahil) en yüksek / en düşük değeri
    //   stoch[i] = 100 * (rsi[i] - lo) / (hi - lo)       (hi == lo ise 0)
    //   K[i]     = SMA(stoch, kLen)[i]                   (kLen bar da tanımlı olmalı)
    //   D[i]     = SMA(K, dLen)[i]
    // Tanımsız barlar null. Pencerede null varsa sonuç null (NaN üretmez).
    export const stochRsi = (
        values: number[], rsiLen = 14, stochLen = 14, kLen = 3, dLen = 3,
    ): { rsi: (number | null)[]; stoch: (number | null)[]; k: (number | null)[]; d: (number | null)[] } => {
        const r = rsiSeries(values, rsiLen);
        const sma = (src: (number | null)[], len: number): (number | null)[] =>
            src.map((_, i) => {
                if (i < len - 1) return null;
                let sum = 0;
                for (let j = i - len + 1; j <= i; j++) {
                    const v = src[j];
                    if (v == null) return null;
                    sum += v;
                }
                return sum / len;
            });
        const stoch: (number | null)[] = r.map((cur, i) => {
            if (cur == null || i < stochLen - 1) return null;
            let hi = -Infinity, lo = Infinity;
            for (let j = i - stochLen + 1; j <= i; j++) {
                const v = r[j];
                if (v == null) return null;
                if (v > hi) hi = v;
                if (v < lo) lo = v;
            }
            return hi === lo ? 0 : (100 * (cur - lo)) / (hi - lo);
        });
        const k = sma(stoch, kLen);
        const d = sma(k, dLen);
        return { rsi: r, stoch, k, d };
    };

    // Ön sinyal ("Ö"): kernel HÂLÂ KIRMIZIYKEN (olası yaklaşan dönüş) StochRSI K, D'yi aşağıdan keser
    // ve kesişimden bir önceki K değeri seviyenin (varsayılan 20, seçilebilir 30) altındadır:
    //   K[i-1] <= D[i-1] && K[i] > D[i] && K[i-1] < level && kernel bearish (bullish[i] === false)
    export const rqKernelPreSignals = (bars: Bar[], params: Record<string, any>): { time: number; type: "pre" }[] => {
        const p = params ?? {};
        const level = Number(p.stochLevel ?? 20);
        const rsiLen = Math.max(2, Math.round(Number(p.stochRsiLen ?? 14)));
        const stochLen = Math.max(2, Math.round(Number(p.stochLen ?? 14)));
        const kLen = Math.max(1, Math.round(Number(p.stochK ?? 3)));
        const dLen = Math.max(1, Math.round(Number(p.stochD ?? 3)));
        const closes = bars.map((b) => Number(b.close));
        const { bullish } = rqkColors(closes, p);
        const { k, d } = stochRsi(closes, rsiLen, stochLen, kLen, dLen);
        const out: { time: number; type: "pre" }[] = [];
        for (let i = 1; i < bars.length; i++) {
            const k0 = k[i - 1], d0 = d[i - 1], k1 = k[i], d1 = d[i];
            if (k0 == null || d0 == null || k1 == null || d1 == null) continue;
            if (bullish[i] !== false) continue;
            if (k0 <= d0 && k1 > d1 && k0 < level) out.push({ time: bars[i].time, type: "pre" });
        }
        return out;
    };

    // Strateji fonksiyonu: kernel B/S okları + (showPreSignals !== false ise) ön sinyaller.
    const rqKernelAllSignals = (bars: Bar[], params: Record<string, any>): StrategySignal[] => {
        const base: StrategySignal[] = rqKernelSignals(bars, params);
        if (params?.showPreSignals === false) return base;
        return base.concat(rqKernelPreSignals(bars, params));
    };


    // ── StochRSI kesişim okları + MA şerit BUY etiketi (id: stoch_ma_signals) ────────────
    // 2026-10-18 (kullanıcı isteği). Yalnız GÖRSEL yardımcı; araştırma (docs/STOCHRSI_LIMIT_GIRIS_2026-10-17.md,
    // docs/GOSTERGE_REHBERI_V2_2026-10-18.md) bu kesişimlerin örneklem dışında net kenar vermediğini ölçtü.
    //   * StochRSI: K, D'yi AŞAĞIDAN keser ve kesişim öncesi K < alt seviye (20) → mumun ALTINA yeşil ok;
    //               K, D'yi YUKARIDAN keser ve kesişim öncesi K > üst seviye (80) → mumun ÜSTÜNE kırmızı ok.
    //   * MA şerit (7/20/99): orta (20) > yavaş (99) iken hızlı (7) ortayı AŞAĞIDAN keser → "BUY" etiketi.
    export const emaSeries = (values: number[], period: number): (number | null)[] => {
        const n = Math.max(1, Math.round(period));
        const out: (number | null)[] = new Array(values.length).fill(null);
        if (values.length < n) return out;
        const alpha = 2 / (n + 1);
        let sum = 0;
        for (let i = 0; i < n; i++) sum += values[i];
        let prev = sum / n;
        out[n - 1] = prev;
        for (let i = n; i < values.length; i++) {
            prev = values[i] * alpha + prev * (1 - alpha);
            out[i] = prev;
        }
        return out;
    };

    export const smaSeries = (values: number[], period: number): (number | null)[] => {
        const n = Math.max(1, Math.round(period));
        const out: (number | null)[] = new Array(values.length).fill(null);
        let sum = 0;
        for (let i = 0; i < values.length; i++) {
            sum += values[i];
            if (i >= n) sum -= values[i - n];
            if (i >= n - 1) out[i] = sum / n;
        }
        return out;
    };

    const crossUp = (a0: number, b0: number, a1: number, b1: number) => a0 <= b0 && a1 > b1;
    const crossDown = (a0: number, b0: number, a1: number, b1: number) => a0 >= b0 && a1 < b1;

    export const stochRsiCrossSignals = (bars: Bar[], params: Record<string, any>): StrategySignal[] => {
        const p = params ?? {};
        const low = Number(p.stochLow ?? 20);
        const high = Number(p.stochHigh ?? 80);
        const rsiLen = Math.max(2, Math.round(Number(p.stochRsiLen ?? 14)));
        const stochLen = Math.max(2, Math.round(Number(p.stochLen ?? 14)));
        const kLen = Math.max(1, Math.round(Number(p.stochK ?? 3)));
        const dLen = Math.max(1, Math.round(Number(p.stochD ?? 3)));
        const closes = bars.map((b) => Number(b.close));
        const { k, d } = stochRsi(closes, rsiLen, stochLen, kLen, dLen);
        const out: StrategySignal[] = [];
        for (let i = 1; i < bars.length; i++) {
            const k0 = k[i - 1], d0 = d[i - 1], k1 = k[i], d1 = d[i];
            if (k0 == null || d0 == null || k1 == null || d1 == null) continue;
            if (crossUp(k0, d0, k1, d1) && k0 < low) {
                out.push({ time: bars[i].time, type: "buy", text: "", shape: "arrowUp", color: "#10b981", size: 0.8 });
            } else if (crossDown(k0, d0, k1, d1) && k0 > high) {
                out.push({ time: bars[i].time, type: "sell", text: "", shape: "arrowDown", color: "#ef4444", size: 0.8 });
            }
        }
        return out;
    };

    export const maRibbonBuySignals = (bars: Bar[], params: Record<string, any>): StrategySignal[] => {
        const p = params ?? {};
        const fastLen = Math.max(1, Math.round(Number(p.maFast ?? 7)));
        const midLen = Math.max(1, Math.round(Number(p.maMid ?? 20)));
        const slowLen = Math.max(1, Math.round(Number(p.maSlow ?? 99)));
        const useSma = p.maUseSma === true || String(p.maType ?? "ema").toLowerCase() === "sma";
        const closes = bars.map((b) => Number(b.close));
        const fn = useSma ? smaSeries : emaSeries;
        const fast = fn(closes, fastLen), mid = fn(closes, midLen), slow = fn(closes, slowLen);
        const out: StrategySignal[] = [];
        for (let i = 1; i < bars.length; i++) {
            const f0 = fast[i - 1], m0 = mid[i - 1], f1 = fast[i], m1 = mid[i], s1 = slow[i];
            if (f0 == null || m0 == null || f1 == null || m1 == null || s1 == null) continue;
            if (m1 > s1 && crossUp(f0, m0, f1, m1)) {
                // 2026-10-18: rozet tarzı (badgeMarkers.ts): zoom'dan bağımsız sabit boyutlu yeşil "BUY" etiketi.
                out.push({ time: bars[i].time, type: "buy", text: "BUY", color: "#16a34a", badge: true });
            }
        }
        return out;
    };

    export const stochMaSignals = (bars: Bar[], params: Record<string, any>): StrategySignal[] => {
        const p = params ?? {};
        const out: StrategySignal[] = [];
        if (p.showStochArrows !== false) out.push(...stochRsiCrossSignals(bars, p));
        if (p.showMaBuy !== false) out.push(...maRibbonBuySignals(bars, p));
        return out.sort((a, b) => a.time - b.time);
    };

    export const strategySignalFns: Record<string, (bars: Bar[], params: Record<string, any>) => StrategySignal[]> = {
        ema_pullback: emaPullbackSignals,
        vwap_macd: vwapMacdSignals,
        cmo_crsi: cmoCrsiSignals,
        sling_shot: rqKernelAllSignals,
        stoch_ma_signals: stochMaSignals,
    };
    export const strategyColors: Record<string, { buy: string; sell: string }> = {
        ema_pullback: { buy: "#38bdf8", sell: "#ef4444" }, vwap_macd: { buy: "#c084fc", sell: "#ef4444" }, cmo_crsi: { buy: "#eab308", sell: "#ef4444" },
        sling_shot: { buy: "#39FF14", sell: "#ef4444" },
        stoch_ma_signals: { buy: "#10b981", sell: "#ef4444" },
    };
    export const strategyLabels: Record<string, string> = {
        ema_pullback: "EMA PB", vwap_macd: "VWAP MACD", cmo_crsi: "CMO CRSI",
        sling_shot: "RQ Kernel",
        stoch_ma_signals: "StochRSI/MA",
    };

    // Grafik sinyallerini spot yürütme modeline dönüştür:
    // alıştan sonra hedef satış veya stop çıkışı üretir; karşıt sinyal çıkış değildir.
    // Bu basitleştirilmiş bir simülasyondur; gerçek backend yürütmesiyle birebir aynı değildir.
    export const spotExecutionSignals = (bars: Bar[], rawAll: StrategySignal[]) => {
        // Ön sinyaller ("pre") işlem değildir; yürütme simülasyonuna girmez.
        const raw = rawAll.filter((s): s is { time: number; type: "buy" | "sell" } => s.type !== "pre");
        const byTime = new Map(bars.map((bar) => [bar.time, bar]));
        let entry: number | null = null;
        const executed: { time: number; type: "buy" | "sell"; reason?: "target" | "stop" }[] = [];
        const signalsByTime = new Map(raw.map((signal) => [signal.time, signal]));
        for (const bar of bars) {
            const signal = signalsByTime.get(bar.time);
            if (entry == null && signal?.type === "buy") {
                entry = bar.close;
                executed.push(signal);
            } else if (entry != null) {
                const target = entry * (1 + SPOT_TARGET_PCT);
                const stop = entry * (1 - SPOT_STOP_PCT);
                if (bar.low <= stop) {
                    executed.push({ time: bar.time, type: "sell", reason: "stop" });
                    entry = null;
                } else if (bar.high >= target) {
                    executed.push({ time: bar.time, type: "sell", reason: "target" });
                    entry = null;
                }
            }
        }
        return executed;
    };
