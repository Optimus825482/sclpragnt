// Saf sinyal/gösterge matematiği: backend ile aynı formüller, React'ten bağımsız.
// Bu modül yalnızca saf fonksiyon ve tip dışa aktarır; DOM veya state erişimi yoktur.

export type Bar = { time: number; open: number; high: number; low: number; close: number; volume: number };

export type PatternMarker = { time: number; type: "buy" | "sell"; text: string };

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

// UT Bot sinyalleri: Pine Script'teki xATRTrailingStop + crossover mantığı
// Döner: { time, type: "buy"|"sell" }[] — marker olarak çizilir
export const utBotSignals = (bars: Bar[], params: Record<string, any>): { time: number; type: "buy" | "sell" }[] => {
    if (bars.length < 20) return [];
    const keyValue = params.keyValue ?? 1;
    const atrPeriod = Math.max(2, Math.round(params.atrPeriod ?? 11));
    const useHA = !!params.heikinAshi;

    // ATR hesapla (Wilder değil, basit ortalama — backend ile uyumlu)
    const closes = bars.map((b) => b.close);
    const highs = bars.map((b) => b.high);
    const lows = bars.map((b) => b.low);
    const atr = (i: number): number => {
        if (i < atrPeriod) return 0;
        let sum = 0;
        for (let j = i - atrPeriod + 1; j <= i; j++) {
            const tr = Math.max(
                highs[j] - lows[j],
                Math.abs(highs[j] - closes[j - 1]),
                Math.abs(lows[j] - closes[j - 1])
            );
            sum += tr;
        }
        return sum / atrPeriod;
    };

    // Heikin Ashi mumları (opsiyonel)
    let src = closes;
    if (useHA) {
        const haClose = bars.map((b) => (b.open + b.high + b.low + b.close) / 4);
        src = haClose;
    }

    const nLoss = keyValue * atr(bars.length - 1);
    const stop: number[] = [];
    const pos: number[] = [];
    for (let i = 0; i < bars.length; i++) {
        const s = src[i];
        const prevStop = i > 0 ? stop[i - 1] : 0;
        const prevSrc = i > 0 ? src[i - 1] : 0;
        if (i === 0) {
            stop.push(s - nLoss);
            pos.push(0);
            continue;
        }
        let st: number;
        if (s > prevStop && prevSrc > prevStop) st = Math.max(prevStop, s - nLoss);
        else if (s < prevStop && prevSrc < prevStop) st = Math.min(prevStop, s + nLoss);
        else if (s > prevStop) st = s - nLoss;
        else st = s + nLoss;
        stop.push(st);
        let p: number;
        if (prevSrc < stop[i - 1] && s > stop[i - 1]) p = 1;
        else if (prevSrc > stop[i - 1] && s < stop[i - 1]) p = -1;
        else p = pos[i - 1];
        pos.push(p);
    }

    // crossover: ema(src,1) = src — buy/sell sadece stop kırılımında
    const signals: { time: number; type: "buy" | "sell" }[] = [];
    for (let i = 1; i < bars.length; i++) {
        const above = src[i] > stop[i] && src[i - 1] <= stop[i - 1];
        const below = src[i] < stop[i] && src[i - 1] >= stop[i - 1];
        if (above) signals.push({ time: bars[i].time, type: "buy" });
        else if (below) signals.push({ time: bars[i].time, type: "sell" });
    }
    return signals;
};

// BB Squeeze sinyalleri: band daralması + hacim patlaması → kırılım yönünde buy/sell
export const bbSqueezeSignals = (bars: Bar[], params: Record<string, any>): { time: number; type: "buy" | "sell" }[] => {
    const lookback = Math.max(10, Math.round(params.lookback ?? 20));
    const period = Math.max(5, Math.round(params.period ?? 20));
    const stdDev = params.stdDev ?? 2;
    const volMult = params.volMult ?? 1.5;
    if (bars.length < lookback + period) return [];

    const closes = bars.map((b) => b.close);
    const volumes = bars.map((b) => b.volume);
    const bb = (i: number) => {
        const slice = closes.slice(i - period + 1, i + 1);
        const sma = slice.reduce((a, b) => a + b, 0) / period;
        const std = Math.sqrt(slice.reduce((a, b) => a + (b - sma) ** 2, 0) / period);
        return { upper: sma + std * stdDev, lower: sma - std * stdDev, bandwidth: (2 * std * stdDev) / sma };
    };

    const signals: { time: number; type: "buy" | "sell" }[] = [];
    for (let i = lookback; i < bars.length; i++) {
        const cur = bb(i);
        // geçmiş bandwidth'lerin minimumu
        let minBw = Infinity;
        for (let j = i - lookback + 1; j < i; j++) {
            if (j >= period) minBw = Math.min(minBw, bb(j).bandwidth);
        }
        if (minBw === Infinity) continue;
        const isSqueeze = cur.bandwidth <= minBw * 1.1;
        const avgVol = volumes.slice(i - 10, i).reduce((a, b) => a + b, 0) / Math.min(10, i);
        const volSpike = volumes[i] > avgVol * volMult;
        if (isSqueeze && volSpike && closes[i] > cur.upper) signals.push({ time: bars[i].time, type: "buy" });
        else if (isSqueeze && volSpike && closes[i] < cur.lower) signals.push({ time: bars[i].time, type: "sell" });
    }
    return signals;
};

// EMA hesaplama (backend ile aynı: ağırlıklı konvolüsyon)
export const ema = (values: number[], period: number): number | null => {
    if (values.length < period) return null;
    const weights = Array.from({ length: period }, (_, i) => Math.exp(-1 + (i / (period - 1)) * 1));
    const wSum = weights.reduce((a, b) => a + b, 0);
    let sum = 0;
    for (let i = 0; i < period; i++) sum += values[values.length - period + i] * weights[i];
    return sum / wSum;
};

// RSI hesaplama (backend ile aynı)
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
    if (avgLoss === 0) return 100;
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
    if (positive + negative === 0) return 50;
    if (negative === 0) return 100;
    return 100 - 100 / (1 + positive / negative);
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
    return { value, deltaPct: avgVolume ? (windowDelta / avgVolume) * 100 : null };
};

// CRSI hesaplama (backend ile aynı: RSI3 + Streak RSI2 + PercentRank50)
export const crsi = (values: number[], rsiPeriod: number, rankPeriod: number): number | null => {
    if (values.length < rankPeriod + 2) return null;
    const r = rsi(values, rsiPeriod);
    if (r == null) return null;
    // streak serisi
    const streaks: number[] = [0];
    for (let i = 1; i < values.length; i++) {
        if (values[i] > values[i - 1]) streaks.push(streaks[i - 1] > 0 ? Math.max(1, streaks[i - 1] + 1) : 1);
        else if (values[i] < values[i - 1]) streaks.push(streaks[i - 1] < 0 ? Math.min(-1, streaks[i - 1] - 1) : -1);
        else streaks.push(0);
    }
    const up = streaks.slice(-2).filter((s) => s > 0);
    const down = streaks.slice(-2).filter((s) => s < 0).map((s) => Math.abs(s));
    const avgUp = up.length ? up.reduce((a, b) => a + b, 0) / up.length : 0;
    const avgDown = down.length ? down.reduce((a, b) => a + b, 0) / down.length : 0;
    const streakRsi = avgDown === 0 ? 100 : 100 - 100 / (1 + avgUp / avgDown);
    // percent rank
    const currentChange = values[values.length - 1] - values[values.length - 2];
    const lookback = values.slice(-rankPeriod - 1, -1);
    let below = 0;
    for (let i = 1; i < lookback.length; i++) {
        if (lookback[i] - lookback[i - 1] < currentChange) below++;
    }
    const percentRank = lookback.length > 1 ? (below / (lookback.length - 1)) * 100 : 0;
    return (r + streakRsi + percentRank) / 3;
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

    // SlingShot System: EMA50/EMA11 trend takip sistemi
    // Conservative Entry: trend yönünde EMA11'e dönüş sonrası kırılım
    // Aggressive Entry: trend yönünde EMA11'e pullback (potansiyel giriş)
    const slingShotSignals = (bars: Bar[], params: Record<string, any>) => {
        const slowPeriod = Math.max(5, Math.round(params.slowPeriod ?? 50));
        const fastPeriod = Math.max(2, Math.round(params.fastPeriod ?? 11));
        const useConservative = params.conservative ?? true;
        const signals: { time: number; type: "buy" | "sell" }[] = [];
        if (bars.length < slowPeriod + 2) return signals;
        const closes = bars.map((bar) => bar.close);
        const ema = (values: number[], period: number) => {
            const k = 2 / (period + 1);
            let ema = values[0];
            for (let i = 1; i < values.length; i++) {
                ema = values[i] * k + ema * (1 - k);
            }
            return ema;
        };
        for (let i = slowPeriod; i < bars.length; i++) {
            const slice = closes.slice(0, i + 1);
            const prevSlice = closes.slice(0, i);
            const emaSlow = ema(slice, slowPeriod);
            const emaFast = ema(slice, fastPeriod);
            const prevEmaFast = ema(prevSlice, fastPeriod);
            const close = closes[i];
            const prevClose = closes[i - 1];
            if (useConservative) {
                // Conservative: önceki bar EMA11 altı/üstü, şimdi kırılım
                if (emaFast > emaSlow && prevClose <= prevEmaFast && close > emaFast) {
                    signals.push({ time: bars[i].time, type: "buy" });
                } else if (emaFast < emaSlow && prevClose >= prevEmaFast && close < emaFast) {
                    signals.push({ time: bars[i].time, type: "sell" });
                }
            } else {
                // Aggressive: trend yönünde EMA11'e pullback
                if (emaFast > emaSlow && close < emaFast) {
                    signals.push({ time: bars[i].time, type: "buy" });
                } else if (emaFast < emaSlow && close > emaFast) {
                    signals.push({ time: bars[i].time, type: "sell" });
                }
            }
        }
        return signals;
    };

    const bbMfiSignals = (bars: Bar[], params: Record<string, any>) => {
        const bbPeriod = Math.max(5, Math.round(params.bbPeriod ?? 21));
        const bbStdDev = Number(params.bbStdDev ?? 2);
        const mfiPeriod = Math.max(2, Math.round(params.mfiPeriod ?? 16));
        const mfiThreshold = Number(params.mfiThreshold ?? 59);
        const signals: { time: number; type: "buy" | "sell" }[] = [];
        for (let i = Math.max(bbPeriod - 1, mfiPeriod); i < bars.length; i++) {
            const closeWindow = bars.slice(i - bbPeriod + 1, i + 1).map((bar) => bar.close);
            const mean = closeWindow.reduce((sum, value) => sum + value, 0) / closeWindow.length;
            const variance = closeWindow.reduce((sum, value) => sum + (value - mean) ** 2, 0) / closeWindow.length;
            const lower = mean - Math.sqrt(variance) * bbStdDev;
            const upper = mean + Math.sqrt(variance) * bbStdDev;
            let positive = 0;
            let negative = 0;
            for (let j = i - mfiPeriod + 1; j <= i; j++) {
                const current = (bars[j].high + bars[j].low + bars[j].close) / 3;
                const previous = (bars[j - 1].high + bars[j - 1].low + bars[j - 1].close) / 3;
                const flow = current * bars[j].volume;
                if (current > previous) positive += flow;
                else if (current < previous) negative += flow;
            }
            const mfi = negative ? 100 - 100 / (1 + positive / negative) : 100;
            const rsiChanges = bars.slice(i - 13, i + 1).map((bar, index, window) => index ? bar.close - window[index - 1].close : 0).slice(1);
            const gains = rsiChanges.reduce((sum, value) => sum + Math.max(value, 0), 0);
            const losses = rsiChanges.reduce((sum, value) => sum + Math.max(-value, 0), 0);
            const rsi = losses ? 100 - 100 / (1 + gains / losses) : 100;
            if (bars[i].close < lower && mfi < mfiThreshold) signals.push({ time: bars[i].time, type: "buy" });
            else if (bars[i].close > upper && rsi > 69 && mfi > 69) signals.push({ time: bars[i].time, type: "sell" });
        }
        return signals;
    };

    // Strateji buy/sell marker'ları: instances'ta strateji indikatörü varsa seçili TF'ye göre hesapla ve çiz
    const extendedStrategySignals = (bars: Bar[], kind: string) => {
        const out: { time: number; type: "buy" | "sell" }[] = [];
        for (let i = 50; i < bars.length; i++) {
            const c = bars[i].close;
            const mean = bars.slice(i - 20, i).reduce((s, b) => s + b.close, 0) / 20;
            const high = Math.max(...bars.slice(i - 20, i).map((b) => b.high));
            const low = Math.min(...bars.slice(i - 20, i).map((b) => b.low));
            const ret5 = c / bars[i - 5].close - 1;
            const volAvg = bars.slice(i - 20, i).reduce((s, b) => s + b.volume, 0) / 20;
            // Her strateji için benzersiz sinyal mantığı
            const buy = kind === "ema_vwap" ? c > mean && bars[i - 1].close <= mean
                : kind === "bb_squeeze_orderflow" ? c > high && bars[i].volume > volAvg * 1.5 && bars[i - 1].close < c
                : kind === "orderflow" ? bars[i - 2].close < bars[i - 1].close && bars[i - 1].close < c
                : kind === "momentum" ? ret5 > 0.003 && c > mean
                : kind === "keltner_breakout" ? c > high && ret5 > 0.002
                : kind === "chop_trend" ? ret5 > 0.004 && c > mean && bars[i].volume > volAvg * 1.2
                : kind === "donchian_breakout" ? c > high && bars[i].volume > volAvg * 1.3
                : kind === "mean_reversion" ? c < low && ret5 < -0.001
                : c < low;
            if (buy) out.push({ time: bars[i].time, type: "buy" });
        }
        return out;
    };
    export const strategySignalFns: Record<string, (bars: Bar[], params: Record<string, any>) => { time: number; type: "buy" | "sell" }[]> = {
        ut_bot: utBotSignals,
        bb_squeeze: bbSqueezeSignals,
        ema_pullback: emaPullbackSignals,
        vwap_macd: vwapMacdSignals,
        cmo_crsi: cmoCrsiSignals,
        bb_mfi_mean_reversion: bbMfiSignals,
        ema_vwap_pullback: (bars) => extendedStrategySignals(bars, "ema_vwap"),
        bb_squeeze_orderflow: (bars) => extendedStrategySignals(bars, "bb_squeeze_orderflow"),
        orderflow: (bars) => extendedStrategySignals(bars, "orderflow"),
        momentum: (bars) => extendedStrategySignals(bars, "momentum"),
        vwap_mean_reversion: (bars) => extendedStrategySignals(bars, "mean_reversion"),
        keltner_breakout: (bars) => extendedStrategySignals(bars, "keltner_breakout"),
        chop_trend_filter: (bars) => extendedStrategySignals(bars, "chop_trend"),
        donchian_breakout: (bars) => extendedStrategySignals(bars, "donchian_breakout"),
        sling_shot: slingShotSignals,
    };
    export const strategyColors: Record<string, { buy: string; sell: string }> = {
        ut_bot: { buy: "#22c55e", sell: "#ef4444" }, bb_squeeze: { buy: "#f97316", sell: "#ef4444" }, ema_pullback: { buy: "#38bdf8", sell: "#ef4444" }, vwap_macd: { buy: "#c084fc", sell: "#ef4444" }, cmo_crsi: { buy: "#eab308", sell: "#ef4444" },
        bb_mfi_mean_reversion: { buy: "#10b981", sell: "#ef4444" },
        ema_vwap_pullback: { buy: "#22c55e", sell: "#ef4444" }, bb_squeeze_orderflow: { buy: "#f97316", sell: "#ef4444" }, orderflow: { buy: "#38bdf8", sell: "#ef4444" }, momentum: { buy: "#eab308", sell: "#ef4444" }, vwap_mean_reversion: { buy: "#c084fc", sell: "#ef4444" },
        keltner_breakout: { buy: "#fb7185", sell: "#ef4444" }, chop_trend_filter: { buy: "#a3e635", sell: "#ef4444" }, donchian_breakout: { buy: "#60a5fa", sell: "#ef4444" },
        sling_shot: { buy: "#39FF14", sell: "#ef4444" },
    };
    export const strategyLabels: Record<string, string> = {
        ut_bot: "UT", bb_squeeze: "BB SQ", ema_pullback: "EMA PB", vwap_macd: "VWAP MACD", cmo_crsi: "CMO CRSI",
        bb_mfi_mean_reversion: "BB+MFI",
        ema_vwap_pullback: "EMA+VWAP", bb_squeeze_orderflow: "BB+FLOW", orderflow: "FLOW", momentum: "MTF MOM", vwap_mean_reversion: "VWAP MR",
        keltner_breakout: "KELT", chop_trend_filter: "CHOP", donchian_breakout: "DONCH",
        sling_shot: "SlingShot",
    };

    // Grafik sinyallerini spot yürütme modeline dönüştür:
    // alıştan sonra yalnızca +2% hedef satış üretir; karşıt sinyal çıkış değildir.
    export const spotExecutionSignals = (bars: Bar[], raw: { time: number; type: "buy" | "sell" }[]) => {
        const byTime = new Map(bars.map((bar) => [bar.time, bar]));
        let entry: number | null = null;
        const executed: { time: number; type: "buy" | "sell" }[] = [];
        const signalsByTime = new Map(raw.map((signal) => [signal.time, signal]));
        for (const bar of bars) {
            const signal = signalsByTime.get(bar.time);
            if (entry == null && signal?.type === "buy") {
                entry = bar.close;
                executed.push(signal);
            } else if (entry != null) {
                const target = entry * 1.02;
                if (bar.high >= target) {
                    executed.push({ time: bar.time, type: "sell" });
                    entry = null;
                }
            }
        }
        return executed;
    };
