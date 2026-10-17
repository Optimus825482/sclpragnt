"""İndikatör filtresi çalışması — sinyal anı özellik matrisi (2026-10-17, çevrimdışı; canlı koda BAĞLANMAZ).

Her olay için yalnız sinyal anından ÖNCE kapanmış 5 dk / 15 dk barlarının özellikleri:
  ex:*   mevcut sistem özellikleri (jsonl/event alanları + 5m RSI/MFI/taker/ATR/hacim oranı/getiri)
  5m:*, 15m:*  indikatör kütüphanesi (app/rescan/indicators_ext.py) çıktıları, kapanmış son bar
  dyn:*  app/rescan/dyn_target.py bileşenleri (ampirik yüzdelikler, 60 dk / 24 sa zirve mesafesi)
  res:*  üst direnç mesafeleri (%; direnç yoksa 99) — hedef boyutlandırma için
  idea:* klasik fikirler (0/1; NaN = hesaplanamadı)
Çıktı: work/indfilter/feats_<pop>.npz (names, X float32). Nedensellik testi: --verify N (kesilmiş serilerle yeniden hesap, aynı sonuç).

Kullanım (backend/): DATABASE_URL=... python scripts/indfilter_feats.py --pop notif,ha [--verify 150]
"""
from __future__ import annotations

import argparse
import pickle
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.rescan import confirm_elems as CE  # noqa: E402
from app.rescan import dyn_target as D  # noqa: E402
from app.rescan import exit_sim as X  # noqa: E402
from scripts import indfilter_common as K  # noqa: E402

BAR5, BAR15 = 300_000, 900_000
STALE_BARS = 3          # kapanmış son bar sinyalden en çok 3 bar önce açılmış olmalı


def lib_module():
    """Kütüphane yüklüyse modül, değilse None (yalnız mevcut özelliklerle çalışılır)."""
    try:
        import importlib
        return importlib.import_module("app.rescan.indicators_ext")
    except Exception as e:      # pragma: no cover
        print("[feats] kütüphane yok: %r" % (e,), flush=True)
        return None


def last_idx(ot: np.ndarray, t_ms: np.ndarray, bar_ms: int) -> tuple[np.ndarray, np.ndarray]:
    """t'den önce kapanmış son barın indeksi ve 'taze' maskesi."""
    i = D.last_closed_index(ot, t_ms, bar_ms)
    ok = (i >= 0) & ((np.asarray(t_ms) - ot[np.clip(i, 0, len(ot) - 1)]) <= (STALE_BARS + 1) * bar_ms)
    return np.clip(i, 0, len(ot) - 1), ok


def take(arr: np.ndarray, i: np.ndarray, ok: np.ndarray) -> np.ndarray:
    return np.where(ok, np.asarray(arr, dtype=float)[i], np.nan)


# ------------------------------------------------------------------------------------------------ dyn + direnç
def dyn_and_res(sym_series: dict, t_ms: np.ndarray, price: np.ndarray, atr_pct: np.ndarray) -> dict[str, np.ndarray]:
    s1, s5 = sym_series["1m"], sym_series["5m"]
    sc = D.SymbolCandles(open1=s1["ot"], h1=s1["h"], open5=s5["ot"], h5=s5["h"], l5=s5["l"], c5=s5["c"])
    out = {}
    peak, h24 = D.peak_levels(sc, t_ms)
    room = D.room_to_resistance_pct(price, peak, h24, 0.3, "both")
    out["dyn:room"] = np.where(np.isfinite(room), room, 99.0)
    out["dyn:peak60dist"] = (peak / price - 1.0) * 100.0
    out["dyn:high24dist"] = (h24 / price - 1.0) * 100.0
    for q in (0.5, 0.6, 0.7):
        out["dyn:emp%02d" % int(round(q * 100))] = D.empirical_upside_pct(sc, t_ms, 60, 14, q)
    res = {}
    res["res:h60"] = np.where(out["dyn:peak60dist"] >= 0.3, out["dyn:peak60dist"], 99.0)
    res["res:h24"] = np.where(out["dyn:high24dist"] >= 0.3, out["dyn:high24dist"], 99.0)
    res["res:near"] = out["dyn:room"]
    out.update(res)
    return out


# ------------------------------------------------------------------------------------------------ ana döngü
def to_arr(sd: dict) -> np.ndarray:
    """pattern_study dizi düzeni: open_time, o, h, l, c, v, quote_v, taker_base, taker_quote."""
    return np.column_stack([sd["ot"].astype(float), sd["o"], sd["h"], sd["l"], sd["c"], sd["v"], sd["qv"], sd["tbv"], sd["tqv"]])


def tf_block(lib, PS, sd: dict, tf: str, bar_ms: int, t_ms: np.ndarray, max_stale: int) -> dict[str, np.ndarray]:
    """Bir zaman dilimi için: boşlukları doldur → mevcut (pattern_study.features_matrix) + kütüphane (compute_all) özellikleri →
    sinyal anından önce kapanmış son barda oku. Ek: yukarı direnç mesafeleri (res:*) ve süpürme penceresi."""
    arr = PS.fill_gaps(to_arr(sd), bar_ms)
    idx = PS.snapshot_index(arr[:, 0].astype(np.int64), bar_ms, t_ms, max_stale)
    ok = idx >= 0
    ii = np.clip(idx, 0, len(arr) - 1)
    out: dict[str, np.ndarray] = {}
    names, Xm = PS.features_matrix(arr, tf)
    for j, nm in enumerate(names):
        out[nm] = np.where(ok, Xm[ii, j], np.nan)
    if lib is not None:
        names2, X2 = lib.compute_all(arr, tf)
        col = {nm: X2[:, j] for j, nm in enumerate(names2)}
        for nm, v in col.items():
            out[nm] = np.where(ok, v[ii], np.nan)
        sw = col[tf + ".ms_sweep_low"].astype(float)
        out[tf + ".sweep_low_recent12"] = np.where(ok, lib.rolling_max(np.nan_to_num(sw), 12)[ii], np.nan)
        # yukarı direnç mesafeleri (% ; seviye fiyatın üstünde değilse 99)
        dsh = out[tf + ".ms_dist_sh"]                         # kapanışın son onaylı tepeye % uzaklığı (negatif: tepe üstte)
        up_sh = np.where(np.isfinite(dsh) & (dsh < 0), (100.0 / (100.0 + dsh) - 1.0) * 100.0, 99.0)
        out["res:swing_" + tf] = np.where(np.isfinite(dsh), up_sh, np.nan)
        out["res:eqh_" + tf] = np.where(np.isfinite(dsh), np.where(out[tf + ".ms_eqh"] > 0.5, up_sh, 99.0), np.nan)
        pd_ = out.get(tf + ".poc_dist", np.full(len(t_ms), np.nan))
        out["res:poc_" + tf] = np.where(np.isfinite(pd_), np.where(pd_ < 0, (100.0 / (100.0 + pd_) - 1.0) * 100.0, 99.0), np.nan)
        # son tepe/dip salınım fiyatlarından türeyen ek: 24 sa pencere zirvesine uzaklık zaten 5m.dist_high24_pct
    return out


def compute_symbol(lib, sym: str, series: dict, t_ms: np.ndarray, with_lib: bool = True) -> dict[str, np.ndarray]:
    """Bir sembolün olayları için özellik sözlüğü. series: {'1m','5m','15m'} → mum dict'leri."""
    from app.rescan import pattern_study as PS
    PS.TF_BARS_PER_DAY.setdefault("15m", 96)          # çalışma zamanı; dosya değişmez
    s1 = series["1m"]
    F: dict[str, np.ndarray] = {}
    F.update(tf_block(lib if with_lib else None, PS, series["5m"], "5m", BAR5, t_ms, STALE_BARS))
    F.update(tf_block(lib if with_lib else None, PS, series["15m"], "15m", BAR15, t_ms, 2))
    i1 = D.last_closed_index(s1["ot"], t_ms, D.BAR1)
    px = np.where(i1 >= 0, s1["c"][np.clip(i1, 0, len(s1["c"]) - 1)], np.nan)
    F.update(dyn_and_res(series, t_ms, px, F["5m.atr14_pct"]))
    return F


def derive_ideas(c: dict, tp: np.ndarray) -> dict[str, np.ndarray]:
    """Kılavuzdaki klasik fikirler → 0/1 sütunlar (NaN: girdi yok). Koşul sağlanınca AL. Eşikler literatürdeki varsayılanlar (ayarlanmadı)."""
    out: dict[str, np.ndarray] = {}

    def g(n):
        return c[n].astype(float) if n in c else np.full(len(tp), np.nan)

    def put(name, cond, *srcs):
        ok = np.ones(len(tp), dtype=bool)
        for sname in srcs:
            ok &= np.isfinite(g(sname))
        out["idea:" + name] = np.where(ok, cond.astype(np.float32), np.nan)
    for tf in ("5m", "15m"):
        sfx = "" if tf == "5m" else "_15m"
        put("adx25_di_up" + sfx, (g(tf + ".adx14") > 25) & (g(tf + ".plus_di14") > g(tf + ".minus_di14")), tf + ".adx14", tf + ".plus_di14")
        put("chop_trending" + sfx, g(tf + ".chop14") < 38.2, tf + ".chop14")
        put("cmf_pos" + sfx, g(tf + ".cmf20") > 0, tf + ".cmf20")
        put("obv_up" + sfx, g(tf + ".obv_slope12") > 0, tf + ".obv_slope12")
        put("cvd_up" + sfx, g(tf + ".cvd_slope12") > 0, tf + ".cvd_slope12")
        put("above_vwap" + sfx, g(tf + ".vwap_dist") > 0, tf + ".vwap_dist")
        put("above_avwap" + sfx, g(tf + ".avwap_dist") > 0, tf + ".avwap_dist")
        put("above_poc" + sfx, g(tf + ".poc_dist") > 0, tf + ".poc_dist")
        put("supertrend_all_green" + sfx, g(tf + ".st_cluster_sum") == 3, tf + ".st_cluster_sum")
        put("ichimoku_above_cloud" + sfx, g(tf + ".ichi_cloud_pos") == 1, tf + ".ichi_cloud_pos")
        put("ms_bullish" + sfx, g(tf + ".ms_trend") > 0, tf + ".ms_trend")
        # direnç: hedefe (tp) varmadan üstte eşit tepe / salınım tepesi YOK
        put("no_equal_highs_in_target" + sfx, ~(g("res:eqh_" + tf) <= tp), "res:eqh_" + tf)
        put("no_swing_high_in_target" + sfx, ~(g("res:swing_" + tf) <= tp), "res:swing_" + tf)
    put("after_sweep_3bar", g("5m.ms_sweep_low_recent3") > 0, "5m.ms_sweep_low_recent3")
    put("after_sweep_12bar", g("5m.sweep_low_recent12") > 0, "5m.sweep_low_recent12")
    put("in_bull_fvg_tap", g("5m.fvg_bull_tap") > 0, "5m.fvg_bull_tap")
    put("bull_fvg_open", g("5m.fvg_bull_open") > 0, "5m.fvg_bull_open")
    put("in_bull_order_block_tap", g("5m.ob_tap") > 0, "5m.ob_tap")
    put("bull_order_block_active", g("5m.ob_active") > 0, "5m.ob_active")
    return out


def build(pop: str, with_lib: bool = True, log=print) -> Path:
    ev = pickle.load(open(K.OUT / ("events_%s.pkl" % pop), "rb"))
    P = K.load_prep(pop)
    n = len(ev["t_ms"])
    ok_ev = P["ev_ok"].astype(bool)
    lib = lib_module() if with_lib else None
    conn = K.get_conn()
    cols: dict[str, np.ndarray] = {}
    syms = sorted(set(ev["sym"][ok_ev].tolist()))
    t0 = time.time()
    for si, s in enumerate(syms):
        series = {tf: K.load_series(conn, s, tf) for tf in ("1m", "5m", "15m")}
        if any(v is None or len(v["ot"]) < 60 for v in series.values()):
            continue
        idx = np.flatnonzero((ev["sym"] == s) & ok_ev)
        F = compute_symbol(lib, s, series, ev["t_ms"][idx], with_lib)
        for k, v in F.items():
            if k not in cols:
                cols[k] = np.full(n, np.nan, dtype=np.float32)
            cols[k][idx] = v.astype(np.float32)
        if (si + 1) % 25 == 0:
            log("[feats %s] %d/%d sembol (%.0f sn)" % (pop, si + 1, len(syms), time.time() - t0))
    conn.close()
    # olay kaynaklı mevcut özellikler (jsonl / events.pkl)
    for k, v in ev.items():
        if k.startswith("x_"):
            cols["ex:" + k[2:]] = np.asarray(v, dtype=np.float32)
    if pop == "ha":
        cols["ex:mode_trend"] = (ev["mode"] == "trend_devam").astype(np.float32)
        cols["ex:mode_notr"] = (ev["mode"] == "notr").astype(np.float32)
    else:
        cols["ex:n_src"] = np.array([len(set(s_)) for s_ in ev["srcs"]], dtype=np.float32)
        for nm in ("velocity", "jump", "early", "rising"):
            cols["ex:src_" + nm] = np.array([nm in s_ for s_ in ev["srcs"]], dtype=np.float32)
        cols["ex:mode_trend"] = (ev["mode"] == "trend_devam").astype(np.float32)
        cols["ex:mode_unified"] = (ev["mode"] == "unified").astype(np.float32)
    cols["ex:tp"] = np.asarray(ev["tp"], dtype=np.float32)
    cols.update(derive_ideas(cols, np.asarray(ev["tp"], dtype=float)))
    names = sorted(cols)
    X_ = np.column_stack([cols[k] for k in names])
    path = K.OUT / ("feats_%s.npz" % pop)
    np.savez_compressed(path, names=np.array(names), X=X_)
    log("[feats %s] %d özellik × %d olay -> %s (%.0f sn)" % (pop, len(names), n, path.name, time.time() - t0))
    return path


def truncate_series(series: dict, t_ms: int) -> dict:
    """t anında bilinen mumlar: yalnız open_time + süre ≤ t olan barlar (1m için 60 sn, 5m 300 sn, 15m 900 sn)."""
    out = {}
    for tf, bar in (("1m", 60_000), ("5m", BAR5), ("15m", BAR15)):
        sd = series[tf]
        m = sd["ot"] + bar <= t_ms
        out[tf] = {k: v[m] for k, v in sd.items()}
    return out


def verify(pop: str, n: int, seed: int = 5, log=print) -> int:
    """Nedensellik testi: n rastgele olay için özellikleri (a) tam seri, (b) t anında kesilmiş seri ile hesapla; farklılar raporlanır."""
    ev = pickle.load(open(K.OUT / ("events_%s.pkl" % pop), "rb"))
    P = K.load_prep(pop)
    ok_ev = np.flatnonzero(P["ev_ok"].astype(bool))
    rng = np.random.default_rng(seed)
    pick = rng.choice(ok_ev, size=min(n, len(ok_ev)), replace=False)
    lib = lib_module()
    conn = K.get_conn()
    bad: dict[str, int] = {}
    tot = 0
    cache: dict[str, tuple] = {}
    for i in pick:
        s = str(ev["sym"][i])
        t = int(ev["t_ms"][i])
        if s not in cache:
            series = {tf: K.load_series(conn, s, tf) for tf in ("1m", "5m", "15m")}
            cache = {s: (series, compute_symbol(lib, s, series, ev["t_ms"][ev["sym"] == s]))}
        series, Ffull = cache[s]
        pos = int(np.flatnonzero(ev["t_ms"][ev["sym"] == s] == t)[0])
        Ftr = compute_symbol(lib, s, truncate_series(series, t), np.array([t], dtype=np.int64))
        for k, v in Ftr.items():
            a, b = float(Ffull[k][pos]), float(v[0])
            tot += 1
            same = (np.isnan(a) and np.isnan(b)) or abs(a - b) <= 1e-4 * max(1.0, abs(a))
            if not same:
                bad[k] = bad.get(k, 0) + 1
    conn.close()
    log("[verify %s] %d olay, %d karşılaştırma; farklı özellik sayısı %d" % (pop, len(pick), tot, len(bad)))
    for k, c in sorted(bad.items(), key=lambda kv: -kv[1])[:40]:
        log("   FARKLI: %s (%d/%d olay)" % (k, c, len(pick)))
    (K.OUT / ("verify_%s.txt" % pop)).write_text("olay %d; karsilastirma %d; farkli ozellik %d" % (len(pick), tot, len(bad)) + chr(10) + chr(10).join("%s %d" % kv for kv in sorted(bad.items())), encoding="utf-8")
    return len(bad)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pop", default="notif,ha")
    ap.add_argument("--no-lib", action="store_true")
    ap.add_argument("--verify", type=int, default=0, help="nedensellik testi: bu kadar olay için kesilmiş seriyle karşılaştır (özellik üretmez)")
    args = ap.parse_args(argv)
    if args.verify:
        for pop in args.pop.split(","):
            verify(pop, args.verify, log=lambda m: print(m, flush=True))
        return 0
    for pop in args.pop.split(","):
        build(pop, with_lib=not args.no_lib, log=lambda m: print(m, flush=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
