"""Gerçekçi doluşlu çıkış yapısı simülatörü (2026-10-17, çevrimdışı araştırma; canlı koda BAĞLANMAZ).

Soru: sinyal gerçek (Hız Avcısı şansın +4-6 pp üstünde) ama sabit TP/SL ile net negatif; çıkış YAPISI (trailing, ATR-trailing, başa-baş,
zaman stopu) gerçekçi doluşla sinyali kârlı yapabilir mi? Bu modül tek bir işlemi 1 dk yolunda simüle eder; saf numpy, vektörel (N işlem × W bar).

Doluş modeli (kasıtlı kötümser):
  * Giriş: sinyal anı + gecikmeden sonraki İLK 1 dk barın AÇILIŞI × (1 + kayma). Yüzdeler (TP / SL / tetik / iz) DOLAN giriş fiyatına göredir.
  * Bar içi sıra: önce STOP kontrolü (bir önceki barların durumundan hesaplanan seviye), sonra TP, en son en-yüksek (HWM) güncellemesi ve yeni
    izleyen stop seviyesi (bir sonraki bardan itibaren geçerli). Aynı barda hem stop hem TP görülürse STOP kazanır.
  * Stop doluşu: min(stop, bar açılışı) × (1 − kayma) (boşluk → açılıştan). TP doluşu: tam TP fiyatı (pozitif kayma yok).
  * Zaman stopu: T dk sonunda son barın kapanışı × (1 − kayma).
  * Ücret: bacak başına %0,1125 (BNB taker), iki bacakta da; net = (çıkış·(1−f)) / (giriş·(1+f)) − 1.

Girdi dizileri (N, W): O, H, L, C — sütun 0 = giriş barı. Fiyat ölçeği önemsiz (göreli kullanılır) → float32 normalize dizilerle de çalışır.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

FEE_LEG_PCT = 0.1125
BAR_MS = 60_000

# çıkış nedeni kodları
R_TP, R_SL, R_TRAIL, R_BE, R_TIME = 0, 1, 2, 3, 4
REASON_NAMES = ("TP", "SL", "iz", "başabaş", "zaman")


@dataclass(frozen=True)
class ExitSpec:
    """Tek bir çıkış hücresi.

    family: fixed | trail | atr | be | be_trail
    tp: yüzde (None → TP yok); tp_cand=True → işlem başına aday hedefi (yoksa tp_fallback)
    sl: ilk stop (yüzde, giriş altı)
    time_min: zaman stopu (dk)
    act/gap: izleyen stop tetiği ve mesafesi (yüzde); atr_k: gap = atr_k × ATR14(5m)% (act sabit)
    be: bu kadar yüzde kâra ulaşınca stop = giriş fiyatı
    """
    name: str
    family: str
    sl: float
    time_min: int
    tp: float | None = None
    tp_cand: bool = False
    tp_fallback: float = 4.0
    act: float | None = None
    gap: float | None = None
    atr_k: float | None = None
    be: float | None = None
    meta: dict = field(default_factory=dict, compare=False, hash=False)


def _arr(x, n: int) -> np.ndarray | None:
    if x is None:
        return None
    a = np.asarray(x, dtype=float)
    return np.full(n, float(a)) if a.ndim == 0 else a


def simulate(O: np.ndarray, H: np.ndarray, L: np.ndarray, C: np.ndarray, spec: ExitSpec, *, slip_pct: float,
             fee_leg_pct: float = FEE_LEG_PCT, tp_cand_pct: np.ndarray | None = None,
             atr_pct: np.ndarray | None = None, time_major: bool = False, entry_slip_pct: float | None = None) -> dict:
    """Vektörel simülasyon. Dönüş: net (yüzde), exit_px/entry (göreli), reason (kod), hold (dk), mfe, mae (yüzde; giriş fiyatına göre).
    Girdi (N, W); `time_major=True` ise (W, N) (sütun erişimi bitişik → büyük N'de hızlı).
    `entry_slip_pct`: yalnız GİRİŞ kayması (None → `slip_pct`); çıkış kayması hep `slip_pct`. Limit (maker) dolumu için 0 verilir:
    giriş = O[0] (limit fiyatı), stop/zaman çıkışları yine kaymalı."""
    O = np.asarray(O); H = np.asarray(H); L = np.asarray(L); C = np.asarray(C)
    if not time_major:
        O, H, L, C = O.T, H.T, L.T, C.T
    w, n = O.shape
    nb = int(min(spec.time_min, w))
    if nb < 1:
        raise ValueError("time_min en az 1 bar olmalı")
    s = slip_pct / 100.0
    s_in = s if entry_slip_pct is None else float(entry_slip_pct) / 100.0
    f = fee_leg_pct / 100.0
    entry = O[0].astype(float) * (1.0 + s_in)

    tp_pct = None
    if spec.tp_cand:
        base = _arr(tp_cand_pct, n) if tp_cand_pct is not None else np.full(n, np.nan)
        tp_pct = np.where(np.isfinite(base) & (base > 0), base, spec.tp_fallback)
    elif spec.tp is not None:
        tp_pct = np.full(n, float(spec.tp))
    tp_px = entry * (1.0 + tp_pct / 100.0) if tp_pct is not None else None

    stop = entry * (1.0 - spec.sl / 100.0)
    kind = np.full(n, R_SL, dtype=np.int8)           # aktif stopun türü
    hwm = entry.copy()
    gap_pct = None
    if spec.family in ("trail", "be_trail"):
        gap_pct = np.full(n, float(spec.gap))
    elif spec.family == "atr":
        if atr_pct is None:
            raise ValueError("atr ailesi atr_pct ister")
        a = np.asarray(atr_pct, dtype=float)
        gap_pct = np.where(np.isfinite(a) & (a > 0), spec.atr_k * a, np.nan)
    act_px = entry * (1.0 + spec.act / 100.0) if spec.act is not None else None
    be_px = entry * (1.0 + spec.be / 100.0) if spec.be is not None else None

    alive = np.ones(n, dtype=bool)
    exit_px = np.full(n, np.nan)
    reason = np.full(n, R_TIME, dtype=np.int8)
    hold = np.full(n, float(nb))
    mfe_px = entry.copy()
    mae_px = entry.copy()

    for i in range(nb):
        o = O[i]; h = H[i]; lo = L[i]
        # 1) stop (önceki durumdan); aynı barda TP görülse bile stop kazanır
        hit = alive & (lo <= stop)
        if hit.any():
            exit_px[hit] = np.minimum(stop[hit], o[hit]) * (1.0 - s)
            reason[hit] = kind[hit]
            hold[hit] = i + 1
        # 2) TP (stop vurmayanlar)
        if tp_px is not None:
            hit_tp = alive & ~hit & (h >= tp_px)
            if hit_tp.any():
                exit_px[hit_tp] = tp_px[hit_tp]
                reason[hit_tp] = R_TP
                hold[hit_tp] = i + 1
            done = hit | hit_tp
        else:
            done = hit
        # MFE / MAE: çıkış barı dâhil
        live_now = alive
        mfe_px = np.where(live_now, np.maximum(mfe_px, h), mfe_px)
        mae_px = np.where(live_now, np.minimum(mae_px, lo), mae_px)
        alive = alive & ~done
        if not alive.any():
            break
        # 3) HWM güncelle, yeni stop (bir sonraki bardan geçerli)
        hwm = np.where(alive, np.maximum(hwm, h), hwm)
        if be_px is not None:
            m = alive & (hwm >= be_px) & (entry > stop)
            if m.any():
                stop = np.where(m, entry, stop)
                kind = np.where(m, R_BE, kind).astype(np.int8)
        if gap_pct is not None:
            armed = alive & (hwm >= act_px) & np.isfinite(gap_pct)
            if armed.any():
                new_stop = hwm * (1.0 - gap_pct / 100.0)
                up = armed & (new_stop > stop)
                stop = np.where(up, new_stop, stop)
                kind = np.where(up, R_TRAIL, kind).astype(np.int8)

    if alive.any():
        exit_px[alive] = C[nb - 1][alive] * (1.0 - s)
        reason[alive] = R_TIME
        hold[alive] = nb
    net = (exit_px * (1.0 - f)) / (entry * (1.0 + f)) - 1.0
    return {
        "net": net * 100.0, "exit_rel": exit_px / entry, "reason": reason, "hold": hold,
        "mfe": (mfe_px / entry - 1.0) * 100.0, "mae": (mae_px / entry - 1.0) * 100.0,
    }


# ------------------------------------------------------------------------------------------------ pencere / ATR yardımcıları
def entry_index(open_time: np.ndarray, t_ms: np.ndarray, delay_s: float, max_stale_ms: int = 5 * 60_000) -> tuple[np.ndarray, np.ndarray]:
    """Sinyal + gecikmeden sonraki İLK 1 dk barın indeksi ve geçerlilik maskesi (bar yoksa / çok geç başlıyorsa geçersiz)."""
    tgt = np.asarray(t_ms, dtype=np.int64) + int(round(delay_s * 1000))
    idx = np.searchsorted(open_time, tgt, side="left")
    ok = idx < len(open_time)
    idx_c = np.minimum(idx, len(open_time) - 1)
    ok &= (open_time[idx_c] - tgt) <= max_stale_ms
    return idx_c, ok


def gather_windows(open_time: np.ndarray, o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray, entry_idx: np.ndarray,
                   n_bars: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Giriş barından başlayan n_bars dakikalık pencere (zaman ızgarasında; eksik dakika = önceki kapanışla düz mum).
    Dönüş: O, H, L, C (float32, giriş barı açılışına göre NORMALİZE), ref (giriş barı açılışı), covered (pencere veri sonu içinde)."""
    et = open_time[entry_idx]
    wanted = et[:, None] + BAR_MS * np.arange(n_bars, dtype=np.int64)[None, :]
    pos = np.searchsorted(open_time, wanted.ravel(), side="right") - 1
    pos = np.clip(pos, 0, len(open_time) - 1).reshape(wanted.shape)
    present = open_time[pos] == wanted
    cc = c[pos]
    O = np.where(present, o[pos], cc); H = np.where(present, h[pos], cc)
    L = np.where(present, l[pos], cc); C = np.where(present, c[pos], cc)
    ref = o[entry_idx].astype(float)
    covered = wanted[:, -1] <= open_time[-1]
    inv = 1.0 / ref[:, None]
    return ((O * inv).astype(np.float32), (H * inv).astype(np.float32), (L * inv).astype(np.float32), (C * inv).astype(np.float32),
            ref, covered)


def atr_pct_at(open_time5: np.ndarray, h5: np.ndarray, l5: np.ndarray, c5: np.ndarray, t_ms: np.ndarray, n: int = 14) -> np.ndarray:
    """5 dk ATR(n) / son kapanmış kapanış × 100 (basit ortalama TR); t_ms'den ÖNCE kapanmış son n bar (nedensel). Yetersiz veri → NaN."""
    pc = np.concatenate([[c5[0]], c5[:-1]])
    tr = np.maximum.reduce([h5 - l5, np.abs(h5 - pc), np.abs(l5 - pc)])
    cs = np.concatenate([[0.0], np.cumsum(tr)])
    last = np.searchsorted(open_time5 + 300_000, np.asarray(t_ms, dtype=np.int64), side="right") - 1
    out = np.full(len(last), np.nan)
    ok = last >= n
    li = last[ok]
    out[ok] = (cs[li + 1] - cs[li + 1 - n]) / n / c5[li] * 100.0
    return out


# ------------------------------------------------------------------------------------------------ istatistik
def cluster_se(x: np.ndarray, cluster: np.ndarray) -> float:
    """Ortalamanın küme-dayanıklı (gün kümesi) standart hatası: sqrt(Σ_g (Σ_i∈g (x_i − x̄))²) / n."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 2:
        return float("nan")
    d = x - x.mean()
    _, inv = np.unique(np.asarray(cluster), return_inverse=True)
    s = np.bincount(inv, weights=d)
    return float(np.sqrt((s ** 2).sum()) / n)


def trade_stats(net: np.ndarray, cluster: np.ndarray | None = None, reason: np.ndarray | None = None,
                hold: np.ndarray | None = None, mfe: np.ndarray | None = None, mae: np.ndarray | None = None) -> dict:
    """n, ortalama net, gün-kümeli SE ve t, kazanma oranı, ort. kazanç/kayıp, çıkış nedeni payları, ort. tutma, MFE, MAE."""
    net = np.asarray(net, dtype=float)
    m = np.isfinite(net)
    n = int(m.sum())
    out: dict = {"n": n}
    if n == 0:
        return out
    x = net[m]
    cl = np.asarray(cluster)[m] if cluster is not None else np.arange(n)
    mean = float(x.mean())
    se = cluster_se(x, cl) if n > 1 else float("nan")
    win = x > 0
    out.update({
        "mean": mean, "se": se, "t": (mean / se) if se and np.isfinite(se) and se > 0 else float("nan"),
        "win": float(win.mean()),
        "avg_win": float(x[win].mean()) if win.any() else float("nan"),
        "avg_loss": float(x[~win].mean()) if (~win).any() else float("nan"),
        "median": float(np.median(x)),
    })
    if reason is not None:
        r = np.asarray(reason)[m]
        out["mix"] = [float((r == k).mean()) for k in range(5)]
    if hold is not None:
        out["hold"] = float(np.asarray(hold, dtype=float)[m].mean())
    if mfe is not None:
        out["mfe"] = float(np.asarray(mfe, dtype=float)[m].mean())
    if mae is not None:
        out["mae"] = float(np.asarray(mae, dtype=float)[m].mean())
    return out


def diff_stats(a: dict, b: dict) -> dict:
    """İki grup ortalama farkı (a − b); SE'ler bağımsız kabul edilir (muhafazakâr: ortak gün etkisi iptal sayılmaz)."""
    if not a.get("n") or not b.get("n") or "se" not in a or "se" not in b:
        return {}
    d = a["mean"] - b["mean"]
    se = float(np.sqrt(a["se"] ** 2 + b["se"] ** 2))
    return {"diff": d, "se": se, "t": d / se if se > 0 else float("nan"), "lo": d - 1.96 * se, "hi": d + 1.96 * se}


# ------------------------------------------------------------------------------------------------ hücre ızgarası
def default_grid() -> list[ExitSpec]:
    """60 hücre: sabit (12), izleyen (36), ATR-izleyen (6), başa-baş (4), başa-baş+izleyen (2)."""
    g: list[ExitSpec] = []
    for tpname, tp, cand in (("cand", None, True), ("1.5", 1.5, False)):
        for sl in (1.5, 3.0):
            for T in (30, 60, 120):
                g.append(ExitSpec(f"fixed TP{tpname} SL{sl:g} T{T}", "fixed", sl=sl, time_min=T, tp=tp, tp_cand=cand))
    for sl in (1.5, 3.0):
        for act in (0.5, 1.0, 1.5):
            for gap in (0.4, 0.8, 1.2):
                g.append(ExitSpec(f"trail act{act:g} gap{gap:g} SL{sl:g} T60", "trail", sl=sl, time_min=60, act=act, gap=gap))
    for T in (30, 120):
        for act in (0.5, 1.0, 1.5):
            for gap in (0.4, 0.8, 1.2):
                g.append(ExitSpec(f"trail act{act:g} gap{gap:g} SL3 T{T}", "trail", sl=3.0, time_min=T, act=act, gap=gap))
    for sl in (1.5, 3.0):
        for k in (1.0, 1.5, 2.0):
            g.append(ExitSpec(f"atr k{k:g} act1 SL{sl:g} T60", "atr", sl=sl, time_min=60, act=1.0, atr_k=k))
    for tpname, tp, cand in (("cand", None, True), ("1.5", 1.5, False)):
        for sl in (1.5, 3.0):
            g.append(ExitSpec(f"be0.6 TP{tpname} SL{sl:g} T60", "be", sl=sl, time_min=60, tp=tp, tp_cand=cand, be=0.6))
    for sl in (1.5, 3.0):
        g.append(ExitSpec(f"be0.6+trail act1 gap0.8 SL{sl:g} T60", "be_trail", sl=sl, time_min=60, act=1.0, gap=0.8, be=0.6))
    return g
