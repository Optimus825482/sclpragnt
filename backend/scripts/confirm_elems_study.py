"""Teyit ögeleri analizi (2026-10-17, çevrimdışı araştırma): ≥ 2 teyit kuralı yayına alınmadan önce hangi TEK teyit ögesi başarılı/başarısız
bildirimlerde daha sık, kural bu ögelerle iyileşir mi?

Veri: `monitoring_notifications` (push, kaynağı bilinen, `global_lead_lag` hariç; 17.09 → 15.10 22:30) + `work/prod_notifications_1015_1017.tsv`
(üretim satırları). Mumlar `work/confirm_elems/cache/` (bkz. `scripts/confirm_elems_cache.py`; DB retention'ı 21 günden eskiyi siler).
Başarı tanımları: (A) hedefe dokunuş (ufuk içinde / 60 dk içinde), (B) gerçekçi net PnL (`app/rescan/exit_sim.py`: 60 sn gecikme,
%0,15 kayma, bacak başına %0,1125 ücret; TP = bildirim hedefi, SL %3, zaman stopu = ufuk [B1] ya da 60 dk [B2]) ve oynaklık-eşleşmiş
rastgele tabana göre EŞLEŞTİRİLMİŞ fark. Zaman bölmesi: kural/eşik seçimi YALNIZ 17.09 → 09.10; değerlendirme 10.10 → 17.10 (dokunulmadan).

Kullanım (backend/): DATABASE_URL=... python scripts/confirm_elems_study.py [--reuse] [--perm 20]
Çıktı: work/confirm_elems/report.md (+ events.pkl). Canlı koda bağlanmaz.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import pickle
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.rescan import confirm_elems as C  # noqa: E402
from app.rescan import dyn_target as D  # noqa: E402
from scripts import policy7d_study as P  # noqa: E402

OUT = ROOT / "work" / "confirm_elems"
CACHE = OUT / "cache"
HZ_OK = (5, 15, 30, 60)
SPLIT = P.T7_START                       # seçim (örneklem-içi) < SPLIT <= değerlendirme


# ------------------------------------------------------------------------------------------------ yükleme
class CacheCandles:
    """policy7d_study.Candles ile aynı arayüz; mumlar yerel önbellekten (DB retention'ı eskiyi siler)."""

    def load(self, sym: str):
        p1, p5 = CACHE / (sym + "_1m.npy"), CACHE / (sym + "_5m.npy")
        if not (p1.exists() and p5.exists()):
            return None
        a1, a5 = np.load(p1)[:, :5], np.load(p5)[:, :5]
        if len(a1) == 0 or len(a5) == 0:
            return None
        return a1, a5


def load_db(conn, t0: float, t1: float) -> list[dict]:
    cur = conn.execute(
        "SELECT id, symbol, price, target_pct, horizon_minutes, mode, score, sources, sent_via_push, detected_at, title "
        "FROM monitoring_notifications WHERE detected_at >= %s AND detected_at < %s ORDER BY detected_at", (t0, t1))
    out = []
    for (i, sym, price, tgt, hz, mode, score, srcs, push, ts, title) in cur.fetchall():
        out.append({"src": "db", "id": "db%d" % i, "sym": sym, "t": float(ts), "price": price, "tgt": tgt, "hz": int(hz or 0),
                    "mode": mode or "", "srcs": P.canon_sources(srcs), "push": bool(push), "app_hit": -1,
                    "four": int("4'LÜ TEYİT" in (title or "")), "app_mfe": None,
                    "score": float(score) if score is not None else float("nan")})
    return out


def btc_klines_1h(conn) -> list:
    """work/btc_1h_120d.json + (JSON'dan sonrası) BTCTRY 5m önbelleğinden saatlik bar (open_time, o, h, l, c)."""
    kl = json.load(open(ROOT / "work" / "btc_1h_120d.json", encoding="utf-8"))
    last = int(kl[-1][0])
    a5 = np.load(CACHE / "BTCTRY_5m.npy")
    hr = (a5[:, 0] // 3_600_000).astype(np.int64) * 3_600_000
    for h in np.unique(hr):
        if h <= last:
            continue
        seg = a5[hr == h]
        if len(seg) < 12:                # eksik saat (son, tamamlanmamış) → yine de son kapanışı kullan
            pass
        kl.append([int(h), seg[0, 1], seg[:, 2].max(), seg[:, 3].min(), seg[-1, 4]])
    return kl


def compute_candle_features(T: "P.Table", ev: np.ndarray, log=print) -> dict[str, np.ndarray]:
    """Sinyal anı mum özellikleri (yalnız t'den ÖNCE kapanmış barlar): RSI14/MFI14 (1m, 5m), son 3 adet 5m barın taker-alış payı,
    24 sa zirveye uzaklık %, sinyal öncesi 30 dk getiri % (pompa büyüklüğü)."""
    n = len(ev)
    names = ("rsi1", "mfi1", "rsi5", "mfi5", "taker3", "dist24", "pump30")
    F = {k: np.full(n, np.nan) for k in names}
    syms = T.sym[ev]
    t_all = T.t_ms[ev]
    for s in sorted(set(syms.tolist())):
        sel = np.where(syms == s)[0]
        p1, p5 = CACHE / (s + "_1m.npy"), CACHE / (s + "_5m.npy")
        if not (p1.exists() and p5.exists()):
            continue
        a1, a5 = np.load(p1), np.load(p5)
        if len(a1) < 50 or len(a5) < 50:
            continue
        open1, open5 = a1[:, 0].astype(np.int64), a5[:, 0].astype(np.int64)
        o1, h1, l1, c1, v1 = a1[:, 1], a1[:, 2], a1[:, 3], a1[:, 4], a1[:, 5]
        h5, l5, c5, v5, qv5, tb5 = a5[:, 2], a5[:, 3], a5[:, 4], a5[:, 5], a5[:, 6], a5[:, 7]
        t = t_all[sel]
        l1i = D.last_closed_index(open1, t, D.BAR1)
        l5i = D.last_closed_index(open5, t, D.BAR5)
        ok1 = (l1i >= 0) & ((t - open1[np.clip(l1i, 0, len(open1) - 1)]) <= 4 * D.BAR1)
        ok5 = (l5i >= 0) & ((t - open5[np.clip(l5i, 0, len(open5) - 1)]) <= 3 * D.BAR5)
        r1, m1 = C.rsi_wilder(c1, 14), C.mfi(h1, l1, c1, v1, 14)
        r5, m5 = C.rsi_wilder(c5, 14), C.mfi(h5, l5, c5, v5, 14)
        i1, i5 = np.clip(l1i, 0, len(c1) - 1), np.clip(l5i, 0, len(c5) - 1)
        F["rsi1"][sel] = np.where(ok1, r1[i1], np.nan)
        F["mfi1"][sel] = np.where(ok1, m1[i1], np.nan)
        F["rsi5"][sel] = np.where(ok5, r5[i5], np.nan)
        F["mfi5"][sel] = np.where(ok5, m5[i5], np.nan)
        # taker payı: son 3 bar sürekli olmalı
        cont = ok5 & (l5i >= 2) & ((open5[i5] - open5[np.clip(l5i - 2, 0, len(open5) - 1)]) == 2 * D.BAR5)
        F["taker3"][sel] = np.where(cont, C.taker_buy_share(qv5, tb5, i5, 3), np.nan)
        sc = D.SymbolCandles(open1=open1, h1=h1, open5=open5, h5=h5, l5=l5, c5=c5)
        peak, h24 = D.peak_levels(sc, t)
        px = np.where(ok1, c1[i1], np.nan)
        F["dist24"][sel] = np.maximum((h24 / px - 1.0) * 100.0, 0.0)
        j = l1i - 30
        okp = ok1 & (j >= 0) & ((open1[i1] - open1[np.clip(j, 0, len(open1) - 1)]) == 30 * D.BAR1)
        F["pump30"][sel] = np.where(okp, (px / c1[np.clip(j, 0, len(c1) - 1)] - 1.0) * 100.0, np.nan)
    return F


def build(args, log=print) -> dict:
    import psycopg
    conn = psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=10)
    t_last = float(np.load(CACHE / "BTCTRY_1m.npy")[-1, 0]) / 1000.0 + 60.0      # önbelleğin son kapanmış 1m barı
    t_hi = t_last - (P.W + 10) * 60
    ev = load_db(conn, P.P_START, P.PROD_START) + P.load_prod_tsv(ROOT / "work" / "prod_notifications_1015_1017.tsv")
    n_raw = len(ev)
    ev = [e for e in ev if e["hz"] in HZ_OK and e["tgt"] and e["mode"] != "global_lead_lag" and e["push"] and len(e["srcs"]) >= 1]
    log("[ev] ham %d -> push+kaynaklı %d" % (n_raw, len(ev)))

    def wfn(t):
        return (P.T7_START, t_hi) if t >= P.T7_START else (P.P_START + P.DAY_S, P.T7_START)
    cs = CacheCandles()
    T = P.finish_table(ev, conn, t_hi, args.k_base, args.pool, wfn, args.seed, cs, log)
    R = P.Results(T, P.build_rules(T))
    e = np.where(T.kind == 0)[0]
    n = len(e)
    nets = {}
    for key, ex in (("net1", "sl3_hz"), ("net2", "sl3_60"), ("neto", "sl3_hz_opt")):
        nets[key] = R.ensure("old", ex)
    out = {"t_hi": t_hi, "n_raw": n_raw}
    for key, arr in nets.items():
        out[key] = arr[e]
    for tag, selarr in (("", T.sel_vol), ("r", T.sel_rnd)):          # "" = oynaklık-eşleşmiş taban, "r" = sembol/saat rastgele tabanı
        base_sel = (T.kind == 1) & selarr & T.valid & np.isfinite(R.rules["old"])
        for key, arr in nets.items():
            ok = base_sel & np.isfinite(arr)
            s_ = np.bincount(T.parent[ok], weights=arr[ok], minlength=T.n)
            c_ = np.bincount(T.parent[ok], minlength=T.n)
            out[tag + "b_" + key] = np.where(c_[e] > 0, s_[e] / np.maximum(c_[e], 1), np.nan)
            out[tag + "bn_" + key] = c_[e]
        for key, h in (("hit_h", R.hit_h["old"]), ("hit60", R.hit60["old"])):
            c_ = np.bincount(T.parent[base_sel], minlength=T.n)
            k_ = np.bincount(T.parent[base_sel], weights=h[base_sel].astype(float), minlength=T.n)
            out[tag + "bk_" + key], out[tag + "bn_" + key] = k_[e], c_[e]
    for key, h in (("hit_h", R.hit_h["old"]), ("hit60", R.hit60["old"])):
        out[key] = h[e]
    out["valid"] = T.valid[e] & np.isfinite(T.old_tgt[e])
    out["t"], out["day"], out["hz"], out["tgt"] = T.t[e], T.day[e], T.hz[e], T.old_tgt[e]
    out["sym"], out["src"], out["mode"] = T.sym[e], T.src[e], T.mode[e]
    out["srcs"] = [tuple(T.rows[i]["srcs"]) for i in e]
    out["four"] = T.four[e]
    out["score"] = np.array([T.rows[i].get("score", float("nan")) for i in e], dtype=float)
    out["atr"] = T.feat["atr"][e]
    out["drift60"] = T.feat["drift60"][e]
    F = compute_candle_features(T, e, log)
    out.update(F)
    # BTC rejimi (kalkan açık = BTC 1s EMA200 altında)
    from scripts.radar_shield_rescan_analysis import btc_regime_table
    a5b = np.load(CACHE / "BTCTRY_5m.npy")
    reg = btc_regime_table(btc_klines_1h(conn), (a5b[:, 0].astype(np.int64), a5b[:, 4]), T.t_ms[e].tolist())
    sh = np.full(n, -1, dtype=np.int64)
    for i, ms in enumerate(T.t_ms[e].tolist()):
        r = reg.get(int(ms))
        if r and r["shield"] is not None:
            sh[i] = 1 if r["shield"] else 0
    out["shield"] = sh
    out["base_rows"] = int((T.kind == 1).sum())
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "events.pkl", "wb") as fh:
        pickle.dump(out, fh)
    return out


# ------------------------------------------------------------------------------------------------ biçim
def f_hit(k, n) -> str:
    if n == 0:
        return "–"
    lo, hi = C.wilson_ci(int(k), int(n))
    return "%.1f%% [%.0f–%.0f] (%d/%d)" % (100.0 * k / n, 100 * lo, 100 * hi, k, n)


def f_ci(m, lo, hi) -> str:
    if not np.isfinite(m):
        return "–"
    if not (np.isfinite(lo) and np.isfinite(hi)):
        return "%+.2f" % m
    return "%+.2f [%+.2f; %+.2f]" % (m, lo, hi)


def f_diff(st: dict) -> str:
    if not st["n"]:
        return "–"
    return f_ci(st["mean"], st["lo"], st["hi"])


def md(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------------------------------------ ögeler
FEATS = (("rsi1", "RSI14 (1m)"), ("mfi1", "MFI14 (1m)"), ("rsi5", "RSI14 (5m)"), ("mfi5", "MFI14 (5m)"),
         ("taker3", "taker-alış payı (son 3×5m)"), ("dist24", "24 sa zirveye uzaklık %"), ("pump30", "önceki 30 dk getiri % (pompa)"),
         ("atr", "ATR14(5m) %"))
SRC_LABEL = {"velocity": "Hız", "jump": "Sıçrama", "early": "Erken uyarı", "rising": "Yükseliş eğilimi"}


def short(srcs) -> str:
    return "+".join(SRC_LABEL[x] for x in P.SRC_ORDER if x in srcs)


def build_elements(E: dict, is_mask: np.ndarray) -> dict:
    """Ögeler: ad -> (bool dizisi, grup, evren maskesi, konjonksiyon grubu). Tersiyl eşikleri YALNIZ örneklem-içi satırlardan."""
    n = len(E["t"])
    ok = E["valid"]
    db = E["src"] == "db"
    elems: dict[str, dict] = {}

    def add(name, arr, grp, uni=None, cgrp=None):
        elems[name] = {"m": np.asarray(arr, dtype=bool) & ok, "grp": grp, "uni": ok if uni is None else (np.asarray(uni, dtype=bool) & ok),
                       "cgrp": cgrp or grp}
    srcs = E["srcs"]
    for x in P.SRC_ORDER:
        add("kaynak: " + SRC_LABEL[x], [x in s for s in srcs], "Kaynak (tekil)", cgrp="kaynak")
    for a, b in itertools.combinations(P.SRC_ORDER, 2):
        add("çift: %s + %s" % (SRC_LABEL[a], SRC_LABEL[b]), [a in s and b in s for s in srcs], "Kaynak çifti", cgrp="kaynak")
    keys = sorted({short(s) for s in srcs})
    for k in keys:
        add("tam küme: " + k, [short(s) == k for s in srcs], "Tam kaynak kümesi", cgrp="kaynak")
    ns = np.array([len(s) for s in srcs])
    for k in (1, 2, 3, 4):
        add("teyit sayısı = %d" % k, ns == k, "Teyit sayısı", cgrp="kaynak")
    for md_ in ("trend_devam", "notr", "unified", "v_donusu"):
        add("mod: " + md_, E["mode"] == md_, "Mod", uni=db, cgrp="mod")
    add("başlık: 4'LÜ TEYİT var", E["four"] == 1, "Başlık", uni=db, cgrp="baslik")
    add("başlık: 4'LÜ TEYİT yok", E["four"] == 0, "Başlık", uni=db, cgrp="baslik")
    add("BTC rejim: kalkan AÇIK (BTC < 1s EMA200)", E["shield"] == 1, "BTC rejim", uni=E["shield"] >= 0, cgrp="rejim")
    add("BTC rejim: kalkan KAPALI", E["shield"] == 0, "BTC rejim", uni=E["shield"] >= 0, cgrp="rejim")
    sc_edges = C.tercile_edges(E["score"][is_mask & db & ok])
    sb = C.bucket3(E["score"], sc_edges)
    for b, lab in enumerate(("düşük", "orta", "yüksek")):
        add("skor %s (%s)" % (lab, ["≤%.1f" % sc_edges[0], "%.1f–%.1f" % sc_edges[:2], ">%.1f" % sc_edges[1]][b]), sb == b, "Skor", uni=db & (sb >= 0), cgrp="skor")
    tg = E["tgt"]
    for lab, m in (("<2", tg < 2.0), ("2–3", (tg >= 2.0) & (tg < 3.0)), ("3–<4", (tg >= 3.0) & (tg < 3.99)), ("≥4 (tavan)", tg >= 3.99)):
        add("hedef %s %%" % lab, m, "Hedef", cgrp="hedef")
    for h in (5, 15, 30):
        add("ufuk %d dk" % h, E["hz"] == h, "Ufuk", cgrp="ufuk")
    hr = (((E["t"] + 3 * 3600) % 86400) // 3600).astype(int)
    for lab in ("gece 00-06", "sabah 06-12", "öğleden sonra 12-18", "akşam 18-24"):
        add("saat (TSİ): " + lab, [C.hour_block(h) == lab for h in hr], "Saat", cgrp="saat")
    edges_used = {}
    for key, lab in FEATS:
        x = E[key]
        ed = C.tercile_edges(x[is_mask & ok])
        edges_used[key] = ed
        b3 = C.bucket3(x, ed)
        for b, nm in enumerate(("düşük", "orta", "yüksek")):
            rng = ["≤%.3g" % ed[0], "%.3g–%.3g" % ed, ">%.3g" % ed[1]][b]
            add("%s %s (%s)" % (lab, nm, rng), b3 == b, lab, uni=np.isfinite(x) & (b3 >= 0), cgrp=key)
    return {"el": elems, "edges": edges_used, "score_edges": sc_edges}


# ------------------------------------------------------------------------------------------------ element tabloları
def delta(E, key="net1"):
    return E[key] - E["b_" + key]


def element_tables(E, EL, scope: np.ndarray, is_mask, oos_mask, title: str, only_known_pairs=True):
    """İki tablo: (A) hedefe dokunuş, (B) net PnL; lift = P(öge|başarı)/P(öge|başarısız)."""
    ok = E["valid"] & scope
    rowsA, rowsB, raw = [], [], []
    names = list(EL["el"].keys())
    pA = []
    pB = []
    res = {}
    for nm in names:
        e = EL["el"][nm]
        m = ok & e["uni"]
        N = int(m.sum())
        em = e["m"] & m
        n_e = int(em.sum())
        r = {"name": nm, "grp": e["grp"], "N": N, "n": n_e}
        if N == 0 or n_e == 0:
            res[nm] = r
            pA.append(np.nan)
            pB.append(np.nan)
            continue
        for key, sk in (("h", E["hit_h"]), ("60", E["hit60"]), ("w", E["net1"] > 0)):
            ls = C.lift_stats(e["m"][m], sk[m])
            r["lift_" + key] = ls
            r["hit_" + key] = (int(sk[em].sum()), n_e)
        r["net"] = C.cluster_bootstrap_mean(E["net1"][em], E["day"][em], 500, 1)
        r["d1"] = C.paired_diff_stats(E["net1"][em], E["beff1"][em], E["day"][em])
        r["dv"] = C.paired_diff_stats(E["net1"][em], E["b_net1"][em], E["day"][em])
        r["d_is"] = C.paired_diff_stats(E["net1"][em & is_mask], E["beff1"][em & is_mask], E["day"][em & is_mask])
        r["d_oos"] = C.paired_diff_stats(E["net1"][em & oos_mask], E["beff1"][em & oos_mask], E["day"][em & oos_mask])
        r["hit_is"] = (int(E["hit_h"][em & is_mask].sum()), int((em & is_mask).sum()))
        r["hit_oos"] = (int(E["hit_h"][em & oos_mask].sum()), int((em & oos_mask).sum()))
        res[nm] = r
        pA.append(r["lift_h"]["p"])
        pB.append(r["lift_w"]["p"])
    qA, qB = C.bh_adjust(pA), C.bh_adjust(pB)
    for i, nm in enumerate(names):
        res[nm]["qA"], res[nm]["qB"] = qA[i], qB[i]
    # sırala: grup sırası sabit, grup içinde lift_h azalan
    grp_order = []
    for nm in names:
        if EL["el"][nm]["grp"] not in grp_order:
            grp_order.append(EL["el"][nm]["grp"])
    ordered = []
    for g in grp_order:
        mem = [nm for nm in names if EL["el"][nm]["grp"] == g and res[nm]["n"] > 0]
        mem.sort(key=lambda nm: -(res[nm]["lift_h"]["lift"] if np.isfinite(res[nm]["lift_h"]["lift"]) else -1))
        ordered += mem
    for nm in ordered:
        r = res[nm]

        def lf(x):
            return "%.2f" % x if np.isfinite(x) else "–"
        rowsA.append([nm, r["n"], "%.0f%%" % (100.0 * r["n"] / r["N"]), f_hit(*r["hit_h"]), lf(r["lift_h"]["lift"]),
                      "%.0f%% / %.0f%%" % (100 * r["lift_h"]["p_s"], 100 * r["lift_h"]["p_f"]),
                      "%.3f" % r["qA"] if np.isfinite(r["qA"]) else "–", f_hit(*r["hit_60"]), lf(r["lift_60"]["lift"])])
        rowsB.append([nm, r["n"], "%.0f%%" % (100.0 * r["hit_w"][0] / r["hit_w"][1]), lf(r["lift_w"]["lift"]),
                      "%.3f" % r["qB"] if np.isfinite(r["qB"]) else "–", f_ci(*r["net"]), f_diff(r["d1"]),
                      "%s (n=%d)" % (f_diff(r["dv"]), r["dv"]["n"]),
                      "%s (n=%d)" % (f_diff(r["d_is"]), r["d_is"]["n"]), "%s (n=%d)" % (f_diff(r["d_oos"]), r["d_oos"]["n"])])
    ha = ["Öge", "n", "pay", "hit (ufuk) [Wilson95]", "lift (ufuk)", "P(öge|başarı) / P(öge|başarısız)", "q (BH)", "hit 60 dk [Wilson95]", "lift (60 dk)"]
    hb = ["Öge", "n", "kazanan (net>0)", "lift (net>0)", "q (BH)", "net B1 ort. [bootstrap95]", "Δ net − taban [95]",
          "Δ yalnız oyn.-eşl. tabanı olan olaylar", "Δ örneklem-içi", "Δ değerlendirme"]
    return md(ha, rowsA), md(hb, rowsB), res


# ------------------------------------------------------------------------------------------------ kural değerlendirme
def eval_rule(E, mask, per: np.ndarray, days: float) -> dict:
    m = mask & per & E["valid"]
    n = int(m.sum())
    r = {"n": n, "per_day": n / days if days > 0 else float("nan")}
    if n == 0:
        return r
    r["hit_h"] = (int(E["hit_h"][m].sum()), n)
    r["hit60"] = (int(E["hit60"][m].sum()), n)
    r["b_hit_h"] = (int(E["bk_hit_h"][m].sum()), int(E["bn_hit_h"][m].sum()))
    r["b_hit60"] = (int(E["bk_hit60"][m].sum()), int(E["bn_hit60"][m].sum()))
    r["rb_hit_h"] = (int(E["rbk_hit_h"][m].sum()), int(E["rbn_hit_h"][m].sum()))
    r["net1"] = C.cluster_bootstrap_mean(E["net1"][m], E["day"][m], 1000, 2)
    r["d1"] = C.paired_diff_stats(E["net1"][m], E["beff1"][m], E["day"][m])
    r["dv"] = C.paired_diff_stats(E["net1"][m], E["b_net1"][m], E["day"][m])
    r["net2"] = C.cluster_bootstrap_mean(E["net2"][m], E["day"][m], 500, 3)
    r["d2"] = C.paired_diff_stats(E["net2"][m], E["beff2"][m], E["day"][m])
    r["neto"] = float(np.nanmean(E["neto"][m]))
    r["win"] = float(np.mean(E["net1"][m] > 0))
    r["tot"] = r["net1"][0] * r["per_day"]
    return r


def rule_rows(name, E, mask, periods) -> list[list]:
    rows = []
    for lab, per, days in periods:
        r = eval_rule(E, mask, per, days)
        if not r["n"]:
            rows.append([name, lab, 0, "0.0", "–", "–", "–", "–", "–", "–", "–", "–"])
            continue
        rows.append([name, lab, r["n"], "%.1f" % r["per_day"], f_hit(*r["hit_h"]), f_hit(*r["hit60"]),
                     "%s / %s" % (("%.1f%%" % (100.0 * r["b_hit_h"][0] / r["b_hit_h"][1])) if r["b_hit_h"][1] else "–",
                                  ("%.1f%%" % (100.0 * r["rb_hit_h"][0] / r["rb_hit_h"][1])) if r["rb_hit_h"][1] else "–"),
                     f_ci(*r["net1"]), f_diff(r["d1"]), "%s (n=%d)" % (f_diff(r["dv"]), r["dv"]["n"]),
                     "%+.2f / %+.2f" % (r["net2"][0], r["neto"]), "%+.1f" % r["tot"]])
    return rows


# ------------------------------------------------------------------------------------------------ ana
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--k-base", type=int, default=40)
    ap.add_argument("--pool", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--perm", type=int, default=20)
    ap.add_argument("--min-n", type=int, default=100)
    args = ap.parse_args(argv)

    def log(m):
        print(m, flush=True)
    t0 = time.time()
    if args.reuse and (OUT / "events.pkl").exists():
        E = pickle.load(open(OUT / "events.pkl", "rb"))
    else:
        E = build(args, log)
    log("[hazır] %.0f sn" % (time.time() - t0))
    from scripts import confirm_elems_report as REP
    text = REP.render(E, args, log)
    (OUT / "report.md").write_text(text, encoding="utf-8")
    log("rapor: %s (%.0f sn)" % (OUT / "report.md", time.time() - t0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
