// frontend/app/charts/IndicatorPicker.tsx -> SLING_SHOT_ENTRY.calculate (kernelLine kismi) birebir kopya.
// Yalniz tip aciklamalari sokuldu; mantik degismedi. Node ile calistirilir: node rqk_calc.js > ../../tests/fixtures/rqk_parity.json
function calculate(bars, params) {
    const h = Math.max(3, Number(params.h ?? 8));
    const r = Math.max(0.25, Number(params.r ?? 2));
    const smoothColors = params.smoothColors ?? false;
    const closes = bars.map((bar) => Number(bar.close));
    const t = bars.map((bar) => Number(bar.time));
    const calculateYhat = (endIdx) => {
        if (endIdx < 1) return null;
        let currentWeight = 0;
        let cumulativeWeight = 0;
        const lookback = Math.min(h, endIdx + 1);
        for (let i = 0; i < lookback; i++) {
            const price = closes[endIdx - i];
            if (price == null || !Number.isFinite(price)) continue;
            const w = Math.pow(1 + (Math.pow(i, 2) / (Math.pow(h, 2) * 2 * r)), -r);
            currentWeight += price * w;
            cumulativeWeight += w;
        }
        if (cumulativeWeight === 0) return null;
        return currentWeight / cumulativeWeight;
    };
    const yhat1 = [];
    const yhat2 = [];
    for (let i = 0; i < bars.length; i++) {
        yhat1.push(calculateYhat(i));
        yhat2.push(calculateYhat(Math.max(0, i - 2)));
    }
    const kernelLine = [];
    for (let i = 0; i < bars.length; i++) {
        const v = yhat1[i];
        if (v == null || !Number.isFinite(v)) {
            kernelLine.push({ time: t[i], value: null });
            continue;
        }
        const prev1 = i >= 1 ? yhat1[i - 1] : null;
        const prev2 = i >= 2 ? yhat1[i - 2] : null;
        const v2 = yhat2[i];
        let isBullish = false;
        if (smoothColors) {
            isBullish = v2 != null && v2 > v;
        } else {
            if (prev1 != null && prev2 != null) {
                const wasBearish = prev2 > prev1;
                const isBearishNow = prev1 > v;
                const isBullishNow = prev1 < v;
                isBullish = isBullishNow || (wasBearish && !isBearishNow);
            } else if (prev1 != null) {
                isBullish = prev1 < v;
            } else {
                isBullish = true;
            }
        }
        kernelLine.push({ time: t[i], value: v, color: isBullish ? "#3AFF17" : "#FD1707" });
    }
    return { metadata: { overlay: true }, plots: { plot0: kernelLine } };
}

function mulberry32(a) {
    return function () {
        a |= 0; a = (a + 0x6D2B79F5) | 0;
        let t = Math.imul(a ^ (a >>> 15), 1 | a);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

function series(seed, n, tick, flatProb) {
    const rnd = mulberry32(seed);
    let p = 100;
    const out = [];
    for (let i = 0; i < n; i++) {
        if (rnd() > flatProb) p += (rnd() - 0.5) * 2;   // flatProb: yatay (esit kapanis) barlar -> esitlik dallarini zorlar
        out.push(Math.round(p / tick) * tick);
    }
    return out;
}

const combos = [
    { h: 8, r: 2, smoothColors: false }, { h: 8, r: 2, smoothColors: true },
    { h: 16, r: 1, smoothColors: false }, { h: 25, r: 8, smoothColors: false },
    { h: 3, r: 0.25, smoothColors: false }, { h: 5.5, r: 2, smoothColors: false },
    { h: 16, r: 2, smoothColors: true },
];
const cases = [
    { name: "rw150", closes: series(1, 150, 0.01, 0.0) },
    { name: "coarse120", closes: series(2, 120, 0.5, 0.3) },      // kaba tik + yatay -> esitlik
    { name: "flat_runs60", closes: series(3, 60, 1.0, 0.7) },
    { name: "short6", closes: series(4, 6, 0.01, 0.0) },
    { name: "short2", closes: series(5, 2, 0.01, 0.0) },
];
const result = { cases: [] };
for (const c of cases) {
    const bars = c.closes.map((x, i) => ({ time: 1000 + i * 60, close: x }));
    const entry = { name: c.name, closes: c.closes, runs: [] };
    for (const p of combos) {
        const res = calculate(bars, p).plots.plot0;
        entry.runs.push({
            params: p,
            yhat: res.map((x) => x.value),
            bull: res.map((x) => (x.color === undefined ? null : x.color === "#3AFF17")),
        });
    }
    result.cases.push(entry);
}
console.log(JSON.stringify(result));
