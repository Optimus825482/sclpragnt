"""Bildirim teyit ögeleri analizi için saf yardımcılar (2026-10-17, çevrimdışı araştırma; canlı koda BAĞLANMAZ).

Soru: ≥ 2 teyitli bildirimlerde hangi TEK teyit ögesi başarılı/başarısız bildirimlerde daha sık? Kural bu ögelerle iyileşir mi?
Bu modül yalnız saf sayısal fonksiyonları içerir (Wilder RSI, MFI, taker payı, Wilson, kümeli bootstrap, lift + Fisher, BH düzeltmesi,
eşleştirilmiş fark, tersiyl kovaları, öge birleşimi araması); veri yükleme/simülasyon `scripts/confirm_elems_study.py` içindedir.
"""
from __future__ import annotations

import itertools
import math

import numpy as np


# ------------------------------------------------------------------------------------------------ oranlar
def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson %95 aralığı (oran, 0..1). n=0 → (nan, nan)."""
    if n <= 0:
        return float("nan"), float("nan")
    p = k / n
    d = 1.0 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def bh_adjust(p) -> np.ndarray:
    """Benjamini-Hochberg düzeltilmiş p (q) değerleri; NaN korunur."""
    p = np.asarray(p, dtype=float)
    out = np.full(len(p), np.nan)
    ok = np.where(np.isfinite(p))[0]
    if len(ok) == 0:
        return out
    order = ok[np.argsort(p[ok], kind="stable")]
    m = len(order)
    q = p[order] * m / (np.arange(m) + 1.0)
    q = np.minimum.accumulate(q[::-1])[::-1]
    out[order] = np.minimum(q, 1.0)
    return out


def lift_stats(elem, success) -> dict:
    """elem/success: bool dizileri. P(öge|başarı), P(öge|başarısız), lift = oran/oran, Fisher exact p (iki yönlü).
    Başarısız ya da başarılı yoksa lift NaN."""
    e = np.asarray(elem, dtype=bool)
    s = np.asarray(success, dtype=bool)
    a = int((e & s).sum())          # öge & başarı
    b = int((e & ~s).sum())         # öge & başarısız
    c = int((~e & s).sum())
    d = int((~e & ~s).sum())
    ns, nf = a + c, b + d
    ps = a / ns if ns else float("nan")
    pf = b / nf if nf else float("nan")
    lift = ps / pf if (ns and nf and pf > 0) else float("nan")
    p = float("nan")
    if ns and nf and (a + b) > 0:
        from scipy.stats import fisher_exact
        p = float(fisher_exact([[a, b], [c, d]])[1])
    return {"n_e": a + b, "a": a, "b": b, "p_s": ps, "p_f": pf, "lift": lift, "p": p}


# ------------------------------------------------------------------------------------------------ ortalama / kümeli bootstrap
def cluster_se(x, cluster) -> float:
    """Ortalamanın gün-kümeli standart hatası (sqrt(Σ_g (Σ_i∈g (x_i − x̄))²) / n)."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 2:
        return float("nan")
    d = x - x.mean()
    _, inv = np.unique(np.asarray(cluster), return_inverse=True)
    s = np.bincount(inv, weights=d)
    return float(np.sqrt((s ** 2).sum()) / n)


def cluster_bootstrap_mean(x, cluster, n_boot: int = 1000, seed: int = 0) -> tuple[float, float, float]:
    """Ortalama ve gün-kümeli bootstrap %95 aralığı (kümeler = günler, yerine koyarak çekilir). NaN'lar atılır.
    Dönüş (ortalama, alt, üst); n=0 → NaN'lar."""
    x = np.asarray(x, dtype=float)
    cl = np.asarray(cluster)
    m = np.isfinite(x)
    x, cl = x[m], cl[m]
    if len(x) == 0:
        return float("nan"), float("nan"), float("nan")
    mean = float(x.mean())
    _, inv = np.unique(cl, return_inverse=True)
    g = inv.max() + 1
    if g < 2:
        return mean, float("nan"), float("nan")
    sums = np.bincount(inv, weights=x, minlength=g)
    cnts = np.bincount(inv, minlength=g).astype(float)
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, g, size=(n_boot, g))
    num = sums[pick].sum(axis=1)
    den = cnts[pick].sum(axis=1)
    bm = num / den
    return mean, float(np.quantile(bm, 0.025)), float(np.quantile(bm, 0.975))


def paired_diff_stats(x, base, cluster) -> dict:
    """Olay başına (x_i − base_i) farkı (base NaN olan olaylar dışarıda); ortalama, gün-kümeli SE ve %95 aralık."""
    x = np.asarray(x, dtype=float)
    b = np.asarray(base, dtype=float)
    cl = np.asarray(cluster)
    m = np.isfinite(x) & np.isfinite(b)
    n = int(m.sum())
    if n == 0:
        return {"n": 0, "mean": float("nan"), "se": float("nan"), "lo": float("nan"), "hi": float("nan")}
    d = (x - b)[m]
    se = cluster_se(d, cl[m]) if n > 1 else float("nan")
    mean = float(d.mean())
    return {"n": n, "mean": mean, "se": se, "lo": mean - 1.96 * se, "hi": mean + 1.96 * se}


# ------------------------------------------------------------------------------------------------ göstergeler
def rsi_wilder(close, n: int = 14) -> np.ndarray:
    """Wilder RSI (üstel ortalama alpha=1/n, başlangıç ilk değer); ilk n değer NaN. Her iki ortalama sıfırsa 50."""
    from scipy.signal import lfilter
    c = np.asarray(close, dtype=float)
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return out
    d = np.diff(c, prepend=c[0])
    up = np.maximum(d, 0.0)
    dn = np.maximum(-d, 0.0)
    a = 1.0 / n
    au = lfilter([a], [1.0, -(1.0 - a)], up, zi=[(1.0 - a) * up[0]])[0]
    ad = lfilter([a], [1.0, -(1.0 - a)], dn, zi=[(1.0 - a) * dn[0]])[0]
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = au / ad
        r = 100.0 - 100.0 / (1.0 + rs)
    r = np.where((au == 0) & (ad == 0), 50.0, r)
    r = np.where((ad == 0) & (au > 0), 100.0, r)
    out[n:] = r[n:]
    return out


def mfi(high, low, close, volume, n: int = 14) -> np.ndarray:
    """Para akışı endeksi: tipik fiyat × hacim; son n barda artış/azalış akışı toplamları. İlk n değer NaN; akış yoksa 50."""
    h, l, c, v = (np.asarray(x, dtype=float) for x in (high, low, close, volume))
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return out
    tp = (h + l + c) / 3.0
    flow = tp * v
    dtp = np.diff(tp, prepend=tp[0])
    pos = np.where(dtp > 0, flow, 0.0)
    neg = np.where(dtp < 0, flow, 0.0)
    cp = np.concatenate([[0.0], np.cumsum(pos)])
    cn = np.concatenate([[0.0], np.cumsum(neg)])
    ps = cp[n + 1:] - cp[1:len(c) - n + 1]
    ns = cn[n + 1:] - cn[1:len(c) - n + 1]
    tot = ps + ns
    with np.errstate(divide="ignore", invalid="ignore"):
        res = np.where(tot > 0, 100.0 * ps / tot, 50.0)
    out[n:] = res
    return out


def taker_buy_share(quote_volume, taker_buy_quote, idx, k: int = 3) -> np.ndarray:
    """idx'te biten son k barın taker-alış payı (Σ taker_buy_quote / Σ quote_volume). Yetersiz geçmiş / sıfır hacim → NaN."""
    qv = np.asarray(quote_volume, dtype=float)
    tb = np.asarray(taker_buy_quote, dtype=float)
    idx = np.asarray(idx, dtype=np.int64)
    cq = np.concatenate([[0.0], np.cumsum(np.nan_to_num(qv))])
    ct = np.concatenate([[0.0], np.cumsum(np.nan_to_num(tb))])
    ok = (idx >= k - 1) & (idx < len(qv))
    ii = np.clip(idx, k - 1, max(len(qv) - 1, k - 1))
    den = cq[ii + 1] - cq[ii + 1 - k]
    num = ct[ii + 1] - ct[ii + 1 - k]
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(ok & (den > 0), num / den, np.nan)
    return r


# ------------------------------------------------------------------------------------------------ kovalar / ögeler
def tercile_edges(ref) -> tuple[float, float]:
    """Referans (örneklem-içi) değerlerin 1/3 ve 2/3 yüzdelikleri; NaN'lar atılır."""
    r = np.asarray(ref, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 3:
        return float("nan"), float("nan")
    return float(np.quantile(r, 1 / 3)), float(np.quantile(r, 2 / 3))


def bucket3(x, edges: tuple[float, float]) -> np.ndarray:
    """0: x ≤ e1, 1: e1 < x ≤ e2, 2: x > e2, -1: NaN."""
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), -1, dtype=np.int64)
    ok = np.isfinite(x)
    out[ok] = np.where(x[ok] <= edges[0], 0, np.where(x[ok] <= edges[1], 1, 2))
    return out


def source_flags(srcs, order=("velocity", "jump", "early", "rising")) -> dict[str, bool]:
    """Kaynak kümesinden tekil varlık, çift varlığı ve tam küme bayrakları."""
    s = set(srcs)
    out: dict[str, bool] = {}
    for x in order:
        out["src:" + x] = x in s
    for a, b in itertools.combinations(order, 2):
        out["pair:%s+%s" % (a, b)] = a in s and b in s
    out["exact:" + "+".join(x for x in order if x in s)] = True
    return out


def hour_block(ts_local_hour: int) -> str:
    """İstanbul saatinden 6 saatlik blok etiketi."""
    h = int(ts_local_hour) % 24
    return "gece 00-06" if h < 6 else ("sabah 06-12" if h < 12 else ("öğleden sonra 12-18" if h < 18 else "akşam 18-24"))


# ------------------------------------------------------------------------------------------------ birleşim araması
def search_conjunctions(elems: dict[str, np.ndarray], group_of: dict[str, str], delta, cluster, t, *, min_n: int = 50,
                        max_k: int = 3, top: int = 10) -> list[dict]:
    """Örneklem-içi öge birleşimi (VE) araması. Hedef: eşleştirilmiş fark `delta` (ör. net − eşleşik rastgele net) ortalamasının
    gün-kümeli %95 ALT sınırı (muhafazakâr). Koşullar: n ≥ min_n; AYNI grup (`group_of`) iki ögeden biri birlikte kullanılmaz;
    zaman ikiye bölününce (t medyanı) her iki yarıda da ortalama fark > 0 (kararlılık). Düşük n birleşimleri budanır
    (anti-monoton); aynı satırları seçen birleşimlerden en kısası tutulur. Dönüş: azalan LCB'ye göre ilk `top` sonuç [{names, n, mean, lcb, se}]."""
    delta = np.asarray(delta, dtype=float)
    cl = np.asarray(cluster)
    t = np.asarray(t, dtype=float)
    valid = np.isfinite(delta)
    tmed = float(np.median(t[valid])) if valid.any() else 0.0
    first = valid & (t < tmed)
    second = valid & (t >= tmed)
    names = [k for k in elems if int((elems[k] & valid).sum()) >= min_n]

    def score(mask: np.ndarray):
        m = mask & valid
        n = int(m.sum())
        if n < min_n:
            return None
        d = delta[m]
        se = cluster_se(d, cl[m])
        if not np.isfinite(se):
            return None
        mean = float(d.mean())
        h1 = delta[mask & first]
        h2 = delta[mask & second]
        stable = len(h1) >= 5 and len(h2) >= 5 and float(h1.mean()) > 0 and float(h2.mean()) > 0
        return {"n": n, "mean": mean, "se": se, "lcb": mean - 1.96 * se, "stable": bool(stable), "key": hash(m.tobytes())}

    results: list[dict] = []
    level = [((k,), elems[k]) for k in names]
    for sc_ in level:
        r = score(sc_[1])
        if r:
            r["names"] = sc_[0]
            results.append(r)
    for _k in range(2, max_k + 1):
        nxt = []
        seen = set()
        for combo, mask in level:
            groups = {group_of.get(x, x) for x in combo}
            last = names.index(combo[-1])
            for nm in names[last + 1:]:
                g = group_of.get(nm, nm)
                if g in groups:
                    continue
                key = combo + (nm,)
                if key in seen:
                    continue
                seen.add(key)
                m2 = mask & elems[nm]
                if int((m2 & valid).sum()) < min_n:
                    continue
                r = score(m2)
                if r:
                    r["names"] = key
                    results.append(r)
                nxt.append((key, m2))
        level = nxt
    good = [r for r in results if r["stable"]]
    good.sort(key=lambda r: (-r["lcb"], len(r["names"])))
    out, seen_keys = [], set()
    for r in good:                       # aynı satır kümesini seçen (yedekli) birleşimlerden en kısası kalır
        if r["key"] in seen_keys:
            continue
        seen_keys.add(r["key"])
        out.append(r)
        if len(out) == top:
            break
    return out
