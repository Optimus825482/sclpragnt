"""Limit-giriş + StochRSI ön sinyali çalışmasının ortak yardımcıları (2026-10-17, çevrimdışı; canlı koda BAĞLANMAZ; DB'ye YAZMAZ).

Veri: work/limitstoch/cache/<tf>/<SEMBOL>.npy  (open_time, open, high, low, close; historical_candles dökümü; `dump_candles.py`).
Göstergeler: `app/rescan/stochrsi.py` (StochRSI + ön sinyal), `app/rescan/rqk.py` (çekirdek, uygulama varsayılanı h=8 r=2 renk kuralı).
"""
from __future__ import annotations

import collections
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.rescan import exit_sim as X  # noqa: E402
from app.rescan import rqk as RQK  # noqa: E402
from app.rescan import stochrsi as S  # noqa: E402

TZ = timezone(timedelta(hours=3))
DAY_MS = 86_400_000
TZ_MS = 3 * 3_600_000
TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000}
W = 120                                   # çıkış penceresi (dk) = en uzun zaman stopu
LEVELS = (20, 30)
WORK = _BACKEND_DIR / "work" / "limitstoch"
CACHE = WORK / "cache"


def parse_day(text: str, *, end: bool = False) -> int:
    d = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=TZ)
    ms = int(d.timestamp() * 1000)
    return ms + DAY_MS - 1 if end else ms


def fmt_t(ms, fmt: str = "%d/%m %H:%M") -> str:
    return datetime.fromtimestamp(ms / 1000, TZ).strftime(fmt)


def day_idx(ms) -> np.ndarray:
    return (np.asarray(ms, dtype=np.int64) + TZ_MS) // DAY_MS


def hour_idx(ms) -> np.ndarray:
    return ((np.asarray(ms, dtype=np.int64) + TZ_MS) // 3_600_000) % 24


# pencereler (İstanbul günü): W30 birincil; B1/B2/B3 önceki çalışmalarla aynı 30 günlük bloklar; ALL = 07-20 → 10-16
WINDOWS = {
    "W30": (parse_day("2026-09-17"), parse_day("2026-10-16", end=True)),
    "B1": (parse_day("2026-07-20"), parse_day("2026-08-18", end=True)),
    "B2": (parse_day("2026-08-19"), parse_day("2026-09-17", end=True)),
    "B3": (parse_day("2026-09-18"), parse_day("2026-10-16", end=True)),
    "ALL": (parse_day("2026-07-20"), parse_day("2026-10-16", end=True)),
}
BLOCKS = ("B1", "B2", "B3")


def block_of(t_ms) -> np.ndarray:
    """0/1/2 = B1/B2/B3; -1 = dışı."""
    t = np.asarray(t_ms, dtype=np.int64)
    out = np.full(len(t), -1, dtype=np.int8)
    for i, b in enumerate(BLOCKS):
        a, z = WINDOWS[b]
        out[(t >= a) & (t <= z)] = i
    return out


def window_mask(t_ms, name: str) -> np.ndarray:
    a, z = WINDOWS[name]
    t = np.asarray(t_ms, dtype=np.int64)
    return (t >= a) & (t <= z)


def symbols(tf: str = "5m") -> list[str]:
    return sorted(p.stem for p in (CACHE / tf).glob("*.npy"))


def load_arr(tf: str, sym: str) -> np.ndarray:
    a = np.load(CACHE / tf / (sym + ".npy"))
    a[:, 0] = np.round(a[:, 0])
    return a


# ------------------------------------------------------------------------------------------------ göstergeler
def compute_ind(arr: np.ndarray) -> dict:
    """Bir (sembol, zaman dilimi) için: ot, k, d, bull, valid, ps20, ps30 (ham mumlar; grafikteki gibi)."""
    c = arr[:, 4]
    ot = arr[:, 0].astype(np.int64)
    q = RQK.rqk(c)
    bull, valid = q["bull"], q["valid"]
    sr = S.stoch_rsi(c)
    bear = valid & ~bull
    return {"ot": ot, "k": sr["k"].astype(np.float32), "d": sr["d"].astype(np.float32), "bull": bull, "valid": valid,
            "ps20": S.pre_signal(sr["k"], sr["d"], bear, 20.0), "ps30": S.pre_signal(sr["k"], sr["d"], bear, 30.0)}


def ind_path(tf: str, sym: str) -> Path:
    return CACHE / "ind" / tf / (sym + ".npz")


def load_ind(tf: str, sym: str) -> dict:
    z = np.load(ind_path(tf, sym))
    return {k: z[k] for k in z.files}


def get_ind(tf: str, sym: str) -> dict:
    p = ind_path(tf, sym)
    if p.exists():
        return load_ind(tf, sym)
    p.parent.mkdir(parents=True, exist_ok=True)
    ind = compute_ind(load_arr(tf, sym))
    np.savez(p, **ind)
    return ind


# ------------------------------------------------------------------------------------------------ yardımcılar
def dedupe_gap(t: np.ndarray, gap_ms: int = 3_600_000) -> np.ndarray:
    """Sıralı zamanlarda, kabul edilen son sinyalden gap_ms içindekileri at. Dönüş: korunan indeksler."""
    keep = []
    last = None
    for i, x in enumerate(t):
        if last is None or x - last >= gap_ms:
            keep.append(i)
            last = x
    return np.array(keep, dtype=np.int64)


def kernel_flips_after(ind: dict, idx: np.ndarray, horizon: int) -> np.ndarray:
    """idx[i] barından SONRAKİ ilk yeşil (bull) barın uzaklığı (bar); horizon içinde yoksa 0 (yok). Yalnız valid barlar sayılır."""
    bull = ind["bull"] & ind["valid"]
    n = len(bull)
    nxt = np.full(n + 1, 10 ** 9, dtype=np.int64)
    pos = np.flatnonzero(bull)
    # nxt[j] = j'den (dahil) sonraki ilk bull bar indeksi
    arr = np.full(n + 1, 10 ** 9, dtype=np.int64)
    arr[pos] = pos
    nxt = np.minimum.accumulate(arr[::-1])[::-1]
    j = nxt[np.minimum(idx + 1, n)]
    dist = j - idx
    dist = np.where(j >= 10 ** 9, 10 ** 9, dist)
    return np.where(dist <= horizon, dist, 0)


def f2(x, nd=2) -> str:
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else ("%+." + str(nd) + "f") % x


def p1(x) -> str:
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else "%.1f" % (100 * x)


# ------------------------------------------------------------------------------------------------ çıkış kümesi
def exit_set() -> list[X.ExitSpec]:
    """24 hücre: sabit TP {1,0; 1,5} × SL {1,5; 3} × T {60; 120} (8) + izleyen tetik {0,5; 1,0} × iz {0,4; 0,8} × SL {1,5; 3} × T {60; 120} (16)."""
    g: list[X.ExitSpec] = []
    for tp in (1.0, 1.5):
        for sl in (1.5, 3.0):
            for T in (60, 120):
                g.append(X.ExitSpec("fixed TP%g SL%g T%d" % (tp, sl, T), "fixed", sl=sl, time_min=T, tp=tp))
    for act in (0.5, 1.0):
        for gap in (0.4, 0.8):
            for sl in (1.5, 3.0):
                for T in (60, 120):
                    g.append(X.ExitSpec("trail act%g gap%g SL%g T%d" % (act, gap, sl, T), "trail", sl=sl, time_min=T, act=act, gap=gap))
    return g


SCENARIOS = {"P": (60, 0.15), "O": (0, 0.05)}        # P = birincil (60 sn / %0,15), O = iyimser (0 sn / %0,05)


def sim_all(windows: tuple, specs: list, slip: float, *, entry_slip: float | None = None) -> np.ndarray:
    """windows = (O, H, L, C) zaman-majör (W, N) float32. Dönüş: net (N, len(specs)) float32."""
    O, H, L, C = windows
    out = np.empty((O.shape[1], len(specs)), dtype=np.float32)
    for j, sp in enumerate(specs):
        r = X.simulate(O, H, L, C, sp, slip_pct=slip, entry_slip_pct=entry_slip, time_major=True)
        out[:, j] = r["net"]
    return out


def hit_within(H: np.ndarray, minutes: int, pct: float) -> np.ndarray:
    """Zaman-majör (W, N) normalize yüksek dizisi (giriş barı açılışı = 1): ilk `minutes` barda en yüksek ≥ 1 + pct/100 mü."""
    return H[:minutes].max(axis=0) >= 1.0 + pct / 100.0


# ------------------------------------------------------------------------------------------------ likidite (24 sa TRY cirosu)
MIN_QUOTE_24H = 5_000_000.0


class Liq:
    """Sembol için son KAPANMIŞ 5 dk barına göre 24 sa (288 bar) kayan quote hacmi. liquid(t): t anında ≥ 5M TRY mi."""

    def __init__(self, sym: str):
        a = np.load(CACHE / "q5" / (sym + ".npy"))
        self.ot = np.round(a[:, 0]).astype(np.int64)
        qv = np.nan_to_num(a[:, 1], nan=0.0)
        cs = np.concatenate([[0.0], np.cumsum(qv)])
        n = len(qv)
        lo = np.maximum(np.arange(n) - 287, 0)
        self.roll = cs[np.arange(n) + 1] - cs[lo]
        self.close = self.ot + 300_000

    def roll_at(self, t_ms) -> np.ndarray:
        j = np.searchsorted(self.close, np.asarray(t_ms, dtype=np.int64), side="right") - 1
        out = np.where(j >= 0, self.roll[np.maximum(j, 0)], 0.0)
        return out

    def liquid(self, t_ms) -> np.ndarray:
        return self.roll_at(t_ms) >= MIN_QUOTE_24H


def pre_times(ind: dict, tf: str, level: int) -> np.ndarray:
    """Ön sinyal bar-KAPANIŞ zamanları (ms)."""
    ps = ind["ps%d" % level]
    return ind["ot"][ps] + TF_MS[tf]


def conf_times(ind: dict, tf: str, level: int, within: int = 6) -> np.ndarray:
    """Onaylı sinyal: ön sinyalden sonraki `within` bar içinde çekirdek AL dönüşü; zaman = DÖNÜŞ barının kapanışı (tekil)."""
    idx = np.flatnonzero(ind["ps%d" % level])
    if len(idx) == 0:
        return np.zeros(0, dtype=np.int64)
    dist = kernel_flips_after(ind, idx, within)
    ok = dist > 0
    j = np.unique(idx[ok] + dist[ok])
    return ind["ot"][j] + TF_MS[tf]


# ------------------------------------------------------------------------------------------------ ızgara (dolum araması)
def gather_grid(ot, a_l, a_c, i0, n_bars):
    """i0 barından başlayan n_bars dakikalık ızgarada düşükler (eksik dakika → NaN), kapanış (eksik → önceki kapanış), present maskesi."""
    et = ot[i0]
    wanted = et[:, None] + 60_000 * np.arange(n_bars, dtype=np.int64)[None, :]
    pos = np.searchsorted(ot, wanted.ravel(), side="right") - 1
    pos = np.clip(pos, 0, len(ot) - 1).reshape(wanted.shape)
    present = ot[pos] == wanted
    low = np.where(present, a_l[pos], np.nan)
    close = a_c[pos]
    return low, close, present


def union_sorted(*arrs) -> np.ndarray:
    return np.unique(np.concatenate([np.asarray(a, dtype=np.int64) for a in arrs])) if arrs else np.zeros(0, dtype=np.int64)
