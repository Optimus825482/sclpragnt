// Rational Quadratic Kernel (Nadaraya-Watson, non-repainting) — TEK DOĞRULUK KAYNAĞI.
// Hem grafik çizgisi (IndicatorPicker.SLING_SHOT_ENTRY.calculate) hem de B/S ve ön sinyaller
// (signals.ts) bu modülü kullanır; böylece oklar çizgi renk değişimleriyle birebir örtüşür.
// Saf fonksiyonlar: DOM/React erişimi yok.

/**
 * Bar başına kernel tahmini (yhat).
 * yhat[i] = Σ close[i-k]·w(k) / Σ w(k),  k = 0..min(h, i+1)-1,
 * w(k) = (1 + k² / (h²·2·r))^(−r).
 * i < 1 için null (tek bar ile regresyon anlamsız); sonlu olmayan kapanışlar atlanır.
 */
export function rqkSeries(closes: number[], h: number, r: number): (number | null)[] {
    const out: (number | null)[] = [];
    for (let endIdx = 0; endIdx < closes.length; endIdx++) {
        if (endIdx < 1) { out.push(null); continue; }
        let currentWeight = 0;
        let cumulativeWeight = 0;
        const lookback = Math.min(h, endIdx + 1);
        for (let k = 0; k < lookback; k++) {
            const price = closes[endIdx - k];
            if (price == null || !Number.isFinite(price)) continue;
            const w = Math.pow(1 + (Math.pow(k, 2) / (Math.pow(h, 2) * 2 * r)), -r);
            currentWeight += price * w;
            cumulativeWeight += w;
        }
        out.push(cumulativeWeight === 0 ? null : currentWeight / cumulativeWeight);
    }
    return out;
}

/** 2 bar lag'li yhat: yhatLag2[i] = yhat[max(0, i-2)] (smoothColors için). */
export function rqkLag2(yhat: (number | null)[]): (number | null)[] {
    return yhat.map((_, i) => yhat[Math.max(0, i - 2)]);
}

/**
 * Bar başına kernel rengi: true = yükseliş (yeşil), false = düşüş (kırmızı),
 * null = yhat yok/sonlu değil (çizgide nokta yok).
 * smoothColors=false: yhat[i-1] < yhat[i]  veya  (yhat[i-2] > yhat[i-1] ve !(yhat[i-1] > yhat[i]))
 *   (i=1: yhat[i-1] yok → true; i=2: yhat[i-2] yok → yalnız yhat[i-1] < yhat[i]).
 * smoothColors=true: yhatLag2[i] > yhat[i]  (mevcut kodun semantiği olduğu gibi korunur).
 */
export function rqkBullish(
    yhat: (number | null)[],
    yhatLag2: (number | null)[],
    smoothColors: boolean,
): (boolean | null)[] {
    const out: (boolean | null)[] = [];
    for (let i = 0; i < yhat.length; i++) {
        const v = yhat[i];
        if (v == null || !Number.isFinite(v)) { out.push(null); continue; }
        const prev1 = i >= 1 ? yhat[i - 1] : null;
        const prev2 = i >= 2 ? yhat[i - 2] : null;
        const v2 = yhatLag2[i];
        let isBullish = false;
        if (smoothColors) {
            isBullish = v2 != null && v2 > v;
        } else if (prev1 != null && prev2 != null) {
            const wasBearish = prev2 > prev1;
            const isBearishNow = prev1 > v;
            const isBullishNow = prev1 < v;
            isBullish = isBullishNow || (wasBearish && !isBearishNow);
        } else if (prev1 != null) {
            isBullish = prev1 < v;
        } else {
            isBullish = true;
        }
        out.push(isBullish);
    }
    return out;
}

/** Parametre normalizasyonu: indikatör instance params'ından (h, r, smoothColors) — calculate ile aynı kurallar. */
export function rqkParams(params: Record<string, any> | undefined | null): { h: number; r: number; smoothColors: boolean } {
    const p = params ?? {};
    return {
        h: Math.max(3, Number(p.h ?? 8)),
        r: Math.max(0.25, Number(p.r ?? 2)),
        smoothColors: p.smoothColors ?? false,
    };
}

/** Kısayol: kapanışlardan doğrudan renk dizisi. */
export function rqkColors(closes: number[], params: Record<string, any> | undefined | null): { yhat: (number | null)[]; bullish: (boolean | null)[] } {
    const { h, r, smoothColors } = rqkParams(params);
    const yhat = rqkSeries(closes, h, r);
    return { yhat, bullish: rqkBullish(yhat, rqkLag2(yhat), smoothColors) };
}
