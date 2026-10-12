"""MALİYET-DUYARLILIK ANALİZİ (2026-10-12).

BEŞ TURUN ORTAK TEŞHİSİ: Motor sinyalleri hep negatif EV verdi; en iyi hücreler
0'a yakın ama pozitif değil. Hipotez: **sinyaller komisyon eşiğinin altında.**
Tüm simülasyonlar ~%0.15/bacak TAKER komisyonu varsaydı (round-trip ~%0.30).

BU SCRIPT: Her sinyal için BRÜT getiri serisini (komisyonsuz) hesaplar, sonra
komisyonu 0 → 0.15% süpürerek:
    1. Sinyalin başabaş (EV=0) komisyonunu bulur,
    2. Taker (%0.15), maker-benzeri (%0.02) ve sıfır senaryolarında net EV verir.
AMAÇ: "Maker mimarisine geçmeye değer mi?" sorusunu veriyle cevaplamak.

DÜRÜSTLÜK NOTU (marker-fill gerçekliği):
    Maker (limit) emir yalnız DOLDUĞUNDA maker komisyonu verir; piyasa maker
    limitini es geçerse (adverse selection) emir doldolmaz ve SİNYAL KAÇAR. Bu
    yüzden maker senaryosu bir ÜST SINIRDIR — sinyalin %100'ünün maker ile
    dolacağını varsayar. Raporda bu açıkça belirtilir.

KULLANIM:
    python backend/scripts/research_cost_sensitivity.py
"""
from __future__ import annotations

import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WORK = os.path.join(_HERE, "..", "work")


def _gross_5m_channel():
    """5m kanal (taker-buy/oflow) sinyalleri için BRÜT getiri serileri."""
    import bisect
    import psycopg
    from app.paper_sim import simulate_exit, tp_pct_for
    cache = json.load(open(os.path.join(_WORK, "channel_cache.json"), encoding="utf-8"))
    trb = {s: {k: b.get(k, []) for k in ("t", "o", "h", "l", "c", "v", "tb")}
           for s, b in cache["tr"].items()}
    # adaylar
    import time
    since = time.time() - 340 * 3600.0
    cands = []
    with psycopg.connect("postgresql://postgres:518518Erkan@localhost:5432/scalper",
                         connect_timeout=8) as conn:
        for ts, sym, px, tgt in conn.execute(
            "SELECT created_at, symbol, price, target_pct FROM velocity_candidates "
            "WHERE passes=true AND created_at>=%s AND price>0 ORDER BY created_at", (since,)):
            try:
                cands.append({"ts": float(ts), "symbol": str(sym).upper(),
                              "price": float(px), "target_pct": float(tgt or 3.0)})
            except (TypeError, ValueError):
                pass
    # feature'lar: order-flow (kanal1) + fiyat/mum (scan) + global lead-lag (kanal2)
    sys.path.insert(0, os.path.join(_HERE, "scripts"))
    import research_data_channels as R
    import scan_entry_features as S
    glb = {s: {k: b.get(k, []) for k in ("t", "o", "h", "l", "c", "v", "tb")}
           for s, b in cache.get("gl", {}).items()}
    series = {"all": [], "vol_r_high": [], "r1_high": [], "tbr_low": [], "g_ret1_high": []}
    recs = []
    for cd in cands:
        b = trb.get(cd["symbol"])
        if not b or not b["t"]:
            continue
        fo = R._tr_features(b, cd["ts"])
        ff = S._features(b, cd["ts"])
        if fo is None or ff is None:
            continue
        gl = glb.get(cd["symbol"])
        gf = R._gl_features(b, gl, cd["ts"]) if gl and gl["t"] else {}
        f = {**fo, **ff, **(gf or {})}
        lo = bisect.bisect_left(b["t"], cd["ts"])
        win = [{"open_time": b["t"][j], "high": b["h"][j], "low": b["l"][j], "close": b["c"][j]}
               for j in range(lo, len(b["t"])) if b["t"][j] <= cd["ts"] + 125 * 60]
        if not win:
            continue
        # BRÜT (komisyon 0, kayma 0)
        o = simulate_exit(win, cd["price"], entry_time=cd["ts"],
                          tp_pct=tp_pct_for(cd["target_pct"], 3.0), sl_pct=1.0,
                          trail_trigger_pct=2.0, trail_gap_pct=1.0, no_profit_min=30,
                          max_hold_min=120, commission_pct=0.0, slippage_pct=0.0,
                          bar_seconds=300.0)
        if o.get("sim_pct") is None:
            continue
        recs.append({"ts": cd["ts"], "sym": cd["symbol"], "f": f, "gross": o["sim_pct"]})
    recs.sort(key=lambda r: r["ts"])
    tr = recs[:int(len(recs) * 0.6)]
    te = recs[int(len(recs) * 0.6):]

    def pct(vals, p):
        s = sorted(vals); return s[min(len(s) - 1, int(len(s) * p))]
    v_hi = pct([r["f"]["vol_r"] for r in tr], 0.7)
    r1_hi = pct([r["f"]["r1"] for r in tr], 0.7)
    tb_lo = pct([r["f"]["tbr"] for r in tr], 0.3)
    series["vol_r_high"] = [r["gross"] for r in te if r["f"]["vol_r"] >= v_hi]
    series["r1_high"] = [r["gross"] for r in te if r["f"]["r1"] >= r1_hi]
    series["tbr_low"] = [r["gross"] for r in te if r["f"]["tbr"] <= tb_lo]
    if any("g_ret1" in r["f"] for r in te):
        g_hi = pct([r["f"]["g_ret1"] for r in tr if "g_ret1" in r["f"]], 0.7)
        series["g_ret1_high"] = [r["gross"] for r in te if r["f"].get("g_ret1", -99) >= g_hi]
    series["all"] = [r["gross"] for r in te]
    return series


def _gross_1h_regime():
    """1h rejim sinyalleri (aralik_dip vb.) için BRÜT getiri serileri."""
    import pickle
    cache = json.load(open(os.path.join(_WORK, "regime_cache.json"), encoding="utf-8"))
    sig = pickle.load(open(os.path.join(_WORK, "sig_cache.pkl"), "rb"))
    series = {"aralik_dip": [], "aralik_kirilim": [], "trend_kirilim": []}
    k_sl, k_tp, mh = 1.5, 3.0, 24
    for rec in sig:
        name = None
        for k in series:
            if k in rec["sig"]:
                name = k; break
        if name is None:
            continue
        b = cache["h1"][rec["s"]]; i = rec["i"]; atr = rec["atr"]; entry = b["c"][i]
        if entry <= 0:
            continue
        sl = entry - k_sl * atr; tp = entry + k_tp * atr; n = len(b["c"]); exitp = None
        for j in range(i + 1, min(i + 1 + mh, n)):
            if b["l"][j] <= sl:
                exitp = sl; break
            if b["h"][j] >= tp:
                exitp = tp; break
        if exitp is None:
            exitp = b["c"][min(i + mh, n - 1)]
        series[name].append((exitp / entry - 1) * 100)     # BRÜT, kayma yok
    return series


def _breakeven(grosses: list[float], slip_pct: float = 0.0) -> dict:
    """Başabaş komisyon: EV=0 yapan per-leg komisyon."""
    if not grosses:
        return {"n": 0}
    m = statistics.mean(grosses)
    # net ≈ brüt - (1+~1)*comm*100 - slip*100 (dönüş kayması yaklaşık)
    # tam model: net = (fill/entry-1)*100 - (1+fill/entry)*comm*100 ; fill=exit*(1-slip)
    # basitleştirme: ortalama brüt m; başabaş comm* ≈ m / 200
    return {"n": len(grosses), "gross_ev": round(m, 4),
            "breakeven_comm_pct": round(m / 200.0 * 100, 4) if m > 0 else 0.0,
            "breakeven_note": "per-leg; pozitifse maker (<0.02%) altında kar var"}


def _net_at(grosses: list[float], comm: float, slip: float = 0.0) -> dict:
    if not grosses:
        return {"n": 0, "ev": None}
    # Her işlem için net = brüt - maliyet ; maliyet tam modelle
    nets = []
    for g in grosses:
        # brüt = (exit/entry-1)*100 varsayımıyla exit/entry = 1+g/100
        r = 1 + g / 100.0
        fill = r * (1 - slip)
        net = (fill - 1) * 100 - (1 + fill) * comm * 100
        nets.append(net)
    w = [x for x in nets if x > 0]
    return {"n": len(nets), "ev": round(statistics.mean(nets), 3),
            "wr": round(100 * len(w) / len(nets), 1)}


def main() -> int:
    print("=== MALİYET-DUYARLILIK ANALİZİ ===")
    print("Soru: sinyaller komisyon eşiğinin altında mı? Maker mimarisi kâra çevirir mi?\n")
    series5 = _gross_5m_channel()
    series1 = _gross_1h_regime()

    rows = []
    for name, g in series5.items():
        rows.append(("5m:" + name, g))
    for name, g in series1.items():
        rows.append(("1h:" + name, g))

    print(f"{'sinyal':18s}{'n':>7}{'brüt EV':>9}{'başabaş':>10}{'taker':>9}{'maker':>9}{'sıfır':>9}")
    print(f"{'':18s}{'':>7}{'(%)':>9}{'comm%':>10}{'0.15%':>9}{'0.02%':>9}{'0.00%':>9}")
    out = {}
    for name, g in rows:
        if not g:
            continue
        be = _breakeven(g)
        nk = _net_at(g, 0.0015)     # taker
        mk = _net_at(g, 0.0002)     # maker-benzeri
        zk = _net_at(g, 0.0)        # sıfır
        print(f"{name:18s}{be['n']:>7}{be['gross_ev']:>9}{be['breakeven_comm_pct']:>10}"
              f"{nk['ev']:>9}{mk['ev']:>9}{zk['ev']:>9}")
        out[name] = {"n": be["n"], "gross_ev": be["gross_ev"],
                     "breakeven_comm_pct": be["breakeven_comm_pct"],
                     "net_taker": nk["ev"], "net_maker": mk["ev"], "net_zero": zk["ev"]}

    positives = {k: v for k, v in out.items() if (v["net_maker"] or -9) > 0}
    print(f"\nMAKER (%0.02) senaryosunda POZİTİF sinyal: {len(positives)}/{len(out)}")
    for k, v in sorted(positives.items(), key=lambda x: -x[1]["net_maker"]):
        print(f"  {k}: maker EV {v['net_maker']}% (brüt {v['gross_ev']}%, başabaş comm {v['breakeven_comm_pct']}%)")

    report = {"series": out, "maker_positive": list(positives.keys()),
              "note": "maker senaryosu ÜST SINIR — limit dolgu varsayımı; adverse selection yok."}

    # ADVERSE-SELECTION TESTİ (2026-10-12 — maker varsayımını çürüten test):
    # Gerçek limit giriş simülasyonu: limiti sinyal fiyatının altına koy, yalnız
    # bekleyen bar içinde fiyat o seviyeye inerse gir. Görünüşteki "maker edge"i
    # dolgu (adverse selection) ile yok oluyorsa maker mimarisi aldatıcıdır.
    try:
        adv = _adverse_selection_test()
        report["adverse_selection"] = adv
        print("\n== ADVERSE-SELECTION (gerçek limit dolgu) ==")
        print("  Taker-giriş (referans) maker-comm EV:", adv["taker_entry_maker_comm_ev"])
        print("  Limit-giriş (dolmazsa işlem yok) EV:", adv["limit_entry_ev"])
        print("  YORUM:", adv["verdict"])
    except Exception as exc:
        print(f"  (adverse-selection testi atlandı: {type(exc).__name__})")

    with open(os.path.join(_WORK, "cost_sensitivity.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("\nrapor: work/cost_sensitivity.json")
    return 0


def _adverse_selection_test() -> dict:
    """En güçlü sinyal (vol_r_high) için gerçek limit-dolgu senaryosu."""
    import bisect
    import time
    import psycopg
    from app.paper_sim import simulate_exit, tp_pct_for
    sys.path.insert(0, os.path.join(_HERE, "scripts"))
    import scan_entry_features as S
    cache = json.load(open(os.path.join(_WORK, "channel_cache.json"), encoding="utf-8"))
    trb = {s: {k: b.get(k, []) for k in ("t", "o", "h", "l", "c", "v", "tb")}
           for s, b in cache["tr"].items()}
    since = time.time() - 340 * 3600.0
    recs = []
    with psycopg.connect("postgresql://postgres:518518Erkan@localhost:5432/scalper",
                         connect_timeout=8) as conn:
        for ts, sym, px, tgt in conn.execute(
            "SELECT created_at, symbol, price, target_pct FROM velocity_candidates "
            "WHERE passes=true AND created_at>=%s AND price>0 ORDER BY created_at", (since,)):
            try:
                sym = str(sym).upper(); b = trb.get(sym)
                if not b or not b["t"]:
                    continue
                ff = S._features(b, float(ts))
                if ff is None:
                    continue
                recs.append({"ts": float(ts), "sym": sym, "price": float(px),
                             "tgt": float(tgt or 3.0), "vol_r": ff["vol_r"], "bars": b})
            except (TypeError, ValueError):
                pass
    recs.sort(key=lambda r: r["ts"])
    tr = recs[:int(len(recs) * 0.6)]; te = recs[int(len(recs) * 0.6):]
    v_hi = sorted([r["vol_r"] for r in tr])[int(len(tr) * 0.7)]
    sel = [r for r in te if r["vol_r"] >= v_hi]

    def _win(r, start_t):
        b = r["bars"]; lo = bisect.bisect_left(b["t"], start_t)
        return [{"open_time": b["t"][j], "high": b["h"][j], "low": b["l"][j], "close": b["c"][j]}
                for j in range(lo, len(b["t"])) if b["t"][j] <= start_t + 125 * 60]

    def taker(comm):
        nets = []
        for r in sel:
            win = _win(r, r["ts"])
            if not win:
                continue
            o = simulate_exit(win, r["price"], entry_time=r["ts"], tp_pct=tp_pct_for(r["tgt"], 3.0),
                              sl_pct=1.0, trail_trigger_pct=2.0, trail_gap_pct=1.0,
                              no_profit_min=30, max_hold_min=120, commission_pct=comm,
                              slippage_pct=0.00025, bar_seconds=300.0)
            if o.get("sim_pct") is not None:
                nets.append(o["sim_pct"])
        return round(statistics.mean(nets), 3) if nets else None

    def limit(comm, drop_pct, wait_bars=3):
        nets = 0; total = 0.0; nofill = 0
        for r in sel:
            b = r["bars"]; lo = bisect.bisect_left(b["t"], r["ts"])
            if lo >= len(b["t"]):
                continue
            limit_px = r["price"] * (1 - drop_pct / 100.0)
            fill_j = None
            for j in range(lo, min(lo + wait_bars, len(b["t"]))):
                if b["l"][j] <= limit_px:
                    fill_j = j; break
            if fill_j is None:
                nofill += 1; continue
            win = [{"open_time": b["t"][j], "high": b["h"][j], "low": b["l"][j], "close": b["c"][j]}
                   for j in range(fill_j, len(b["t"])) if b["t"][j] <= b["t"][fill_j] + 120 * 60]
            if not win:
                continue
            o = simulate_exit(win, limit_px, entry_time=b["t"][fill_j],
                              tp_pct=tp_pct_for(r["tgt"], 3.0), sl_pct=1.0, trail_trigger_pct=2.0,
                              trail_gap_pct=1.0, no_profit_min=30, max_hold_min=120,
                              commission_pct=comm, slippage_pct=0.0, bar_seconds=300.0)
            if o.get("sim_pct") is not None:
                nets += 1; total += o["sim_pct"]
        return {"n_filled": nets, "nofill": nofill,
                "ev": round(total / nets, 3) if nets else None}

    taker_ev = taker(0.0002)
    lim = limit(0.0002, 0.3)
    verdict = ("MAKER EDGE ADVERSE-SELECTION İLE ÇÖKÜYOR — limit dolgusunda EV negatife döner"
               if (lim["ev"] is not None and lim["ev"] < 0 and (taker_ev or 0) > 0)
               else "maker dolgu senaryosu tutarlı")
    return {"signal": "vol_r_high", "n_selected": len(sel),
            "taker_entry_maker_comm_ev": taker_ev, "limit_entry_ev": lim["ev"],
            "limit_filled": lim["n_filled"], "limit_nofill": lim["nofill"],
            "verdict": verdict}


if __name__ == "__main__":
    raise SystemExit(main())
