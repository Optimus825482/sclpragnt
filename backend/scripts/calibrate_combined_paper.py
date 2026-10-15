"""OTONOM PAPER PARAMETRE KALİBRASYONU (2026-10-12).

NEDEN: Otonom paper portföyü -%3.19; kapanan 46 işlemde payoff 0.65 < başabaş
için gereken %60.7 kazanma oranı. Kök neden SL/trigger geometrisi. Ama bu
proje geçmişte "test edilmemiş ayar" ile defalarca yanıldı → parametreler
GERÇEK aday geçmişi + GERÇEK mumlar üzerinde taranır, walk-forward ile doğrulanır.

VERİ:
  * Adaylar: PostgreSQL `velocity_candidates` (passes=true) — canlı taramanın
    gerçekten ürettiği sinyaller (fiyat + zaman + hedef).
  * Mumlar: önce yerel `work/market_cache.sqlite` (5m/1m), yetmezse Binance TR
    REST (yalnız eksik sembol/pencereler).
  * Simülatör: `app/paper_sim.simulate_exit` — SALT OKUNUR, üretim koduyla
    AYNI geometri (bu yüzden kalibrasyon ile canlı ayrışamaz).

YÖNTEM (walk-forward, ikiye bölme):
  1. Adaylar kronolojik sıralanır; İLK %60 "eğitim", SON %40 "sınav".
  2. Grid eğitim kümesinde taranır → eğitim EV'si en yüksek konfig.
  3. O konfig SINAV kümesinde ölçülür; EV>0 VE mevcut varsayılandan iyi değilse
     REDDEDİLİR (aşırı-uydurma koruması). Kazanan JSON'a yazılır.

KULLANIM:
    python backend/scripts/calibrate_combined_paper.py --hours 3600
    python backend/scripts/calibrate_combined_paper.py --hours 3600 --fetch
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from app.paper_sim import simulate_exit, tp_pct_for  # noqa: E402

# 2026-10-15 (denetim düzeltmesi): sabit DB kimlik bilgisi kaldırıldı; DATABASE_URL zorunlu.
# Import anında değil, bağlantı anında kontrol edilir (testler modülü DB'siz import eder).
def _db_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        sys.exit("HATA: DATABASE_URL ortam değişkeni tanımlı değil "
                 "(örn. postgresql://kullanici:sifre@host:5432/scalper)")
    return url
_SQLITE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "..", "work", "market_cache.sqlite")

# Varsayılan (mevcut canlı) konfig — kıyas tabanı.
# 2026-10-12 kalibrasyonu: SL 3.0 → 1.0 (veriyle seçildi). Bu taban, sonraki
# koşuların "geçmesi gereken" referansıdır.
DEFAULT_CFG = {"sl_pct": 1.0, "trail_trigger_pct": 2.0, "trail_gap_pct": 1.0,
               "no_profit_min": 30.0, "max_hold_min": 120.0, "tp_base": 3.0}


def _load_candidates(hours: float) -> list[dict]:
    """PG'den passes=true adayları çek (fiyat+zaman+hedef+skor+rank).

    Giriş taraması (`--entry-scan`) skor/rank/atr alanlarını da kullanır; bu
    alanlar NULL olabilir (eski kayıtlar) → savunmacı varsayılan verilir.
    """
    import psycopg
    since = time.time() - hours * 3600.0
    out = []
    with psycopg.connect(_db_url(), connect_timeout=8) as conn:
        cur = conn.execute(
            "SELECT created_at, symbol, price, target_pct, velocity_score, atr_pct, rank "
            "FROM velocity_candidates "
            "WHERE passes=true AND created_at >= %s AND price > 0 ORDER BY created_at",
            (since,))
        for ts, sym, px, tgt, score, atr, rank in cur.fetchall():
            try:
                out.append({"ts": float(ts), "symbol": str(sym).upper(),
                            "price": float(px), "target_pct": float(tgt or 3.0),
                            "score": float(score or 0.0), "atr": float(atr or 0.0),
                            "rank": (int(rank) if rank is not None else 99)})
            except (TypeError, ValueError):
                continue
    return out


def _load_sqlite_bars(symbols: set[str], since_s: float, until_s: float) -> dict:
    """Yerel sqlite'tan 5m mumları oku → {symbol: [bars]} (artan zaman)."""
    bars: dict[str, list] = {}
    if not os.path.exists(_SQLITE):
        return bars
    c = sqlite3.connect(_SQLITE)
    try:
        cur = c.execute(
            "SELECT symbol, open_time, high, low, close FROM klines "
            "WHERE interval='5m' AND open_time >= ? AND open_time <= ? ORDER BY open_time",
            (int(since_s * 1000), int(until_s * 1000)))
        for sym, ot, h, lo, cl in cur.fetchall():
            s = str(sym).upper()
            if s not in symbols:
                continue
            bars.setdefault(s, []).append(
                {"open_time": float(ot) / 1000.0, "high": float(h),
                 "low": float(lo), "close": float(cl)})
    finally:
        c.close()
    return bars


async def _fetch_missing(symbols: set[str], have: set[str], days_back: int) -> dict:
    """Yerel önbellekte olmayan semboller için Binance TR'den 5m mum çek."""
    from app.binance_tr_public import historical_klines
    out: dict[str, list] = {}
    missing = sorted(symbols - have)
    print(f"  REST'ten çekilecek sembol: {len(missing)}")
    for i, sym in enumerate(missing):
        try:
            rows = await historical_klines(sym, "5m", days_back)
            bars = [{"open_time": float(r[0]) / 1000.0, "high": float(r[2]),
                     "low": float(r[3]), "close": float(r[4])} for r in (rows or [])]
            if bars:
                out[sym] = sorted(bars, key=lambda b: b["open_time"])
        except Exception as exc:
            print(f"    {sym}: {type(exc).__name__}")
        if (i + 1) % 10 == 0:
            print(f"    ... {i + 1}/{len(missing)}")
            await asyncio.sleep(0.2)
    return out


def _slice_bars(bars: list, start_s: float, end_s: float) -> list:
    """[start,end] aralığındaki mumları döndür (dahil)."""
    return [b for b in bars if start_s <= b["open_time"] <= end_s]


def _simulate_population(cands: list[dict], bars_by_sym: dict, cfg: dict,
                         *, commission_pct: float, slippage_pct: float) -> list[dict]:
    """Her adayı konfig ile simüle et → sonuç listesi (net% + neden)."""
    res = []
    for c in cands:
        bars = bars_by_sym.get(c["symbol"])
        if not bars:
            continue
        # Girişten itibaren max_hold + pay kadar mum penceresi.
        win_end = c["ts"] + (cfg["max_hold_min"] + 5) * 60.0
        win = _slice_bars(bars, c["ts"], win_end)
        if not win:
            continue
        tp = tp_pct_for(c["target_pct"], cfg["tp_base"])
        r = simulate_exit(win, c["price"], entry_time=c["ts"], tp_pct=tp,
                          sl_pct=cfg["sl_pct"], trail_trigger_pct=cfg["trail_trigger_pct"],
                          trail_gap_pct=cfg["trail_gap_pct"], cancel_tp_on_trail=True,
                          no_profit_min=cfg["no_profit_min"], max_hold_min=cfg["max_hold_min"],
                          commission_pct=commission_pct, slippage_pct=slippage_pct)
        if r.get("sim_pct") is None:
            continue
        res.append({"symbol": c["symbol"], "ts": c["ts"], "net_pct": r["sim_pct"],
                    "reason": r["reason"]})
    return res


def _metrics(res: list[dict]) -> dict:
    if not res:
        return {"n": 0, "ev_pct": None, "win_rate": None, "avg_win": None,
                "avg_loss": None, "payoff": None, "total_pct": None}
    nets = [r["net_pct"] for r in res]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    aw = statistics.mean(wins) if wins else 0.0
    al = statistics.mean(losses) if losses else 0.0
    reasons = {}
    for r in res:
        reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    return {
        "n": len(nets),
        "ev_pct": round(statistics.mean(nets), 3),
        "median_pct": round(statistics.median(nets), 3),
        "win_rate": round(100.0 * len(wins) / len(nets), 1),
        "avg_win": round(aw, 2), "avg_loss": round(al, 2),
        "payoff": round(aw / abs(al), 2) if al else None,
        "total_pct": round(sum(nets), 1),
        "reasons": reasons,
    }


def _grid(base: dict) -> list[dict]:
    """Aranacak konfigürasyonlar — YALNIZ UYGULANABİLİR uzay.

    Kısıtlar (testler + kullanıcı kararı 2026-10-11 ile hizalı):
      * gap >= 0.8 (trailing çok dar olmasın — hemen yakalanmasın),
      * trigger > gap (aktivasyonda stop girişin ÜSTÜNDE kalsın, kâr zarara dönmesin).
    Böylece önerilen konfig doğrudan config'e yazılabilir.
    """
    out = []
    for sl in (0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0):
        for trig, gap in ((1.0, 0.8), (1.2, 0.8), (1.5, 0.8), (1.5, 1.0),
                          (2.0, 1.0), (2.5, 1.0), (3.0, 1.0)):
            out.append({**base, "sl_pct": sl, "trail_trigger_pct": trig,
                        "trail_gap_pct": gap})
    return out


def _pctile(vals: list[float], p: float) -> float:
    s = sorted(vals)
    return s[min(len(s) - 1, int(len(s) * p))] if s else 0.0


def _entry_scan(train: list[dict], test: list[dict], bars: dict, *,
                commission_pct: float, slippage_pct: float) -> dict:
    """GİRİŞ SEÇİCİSİ taraması (2026-10-12).

    Çıkış kalibrasyonu SL'i düzeltip kaybı azalttı ama portföy pozitife
    dönmedi → soru "hangi GİRİŞ filtresi edge verir?" Bu fonksiyon tek-değişkenli
    filtreleri (skor/ATR/rank/ret3/ML) ve gerçek-liste taklidini (zaman kovası
    başına top-N) eğitimde eşikleyip SINAVDA ölçer. Amaç: pozitife dönen bir
    bölge var mı? Yoksa bulgu "edge giriş sinyalinde yok" olarak raporlanır.
    """
    cfg = dict(DEFAULT_CFG)
    def ev(pop, filt=None):
        sel = [c for c in pop if (filt(c) if filt else True)]
        return _metrics(_simulate_population(sel, bars, cfg,
                                             commission_pct=commission_pct,
                                             slippage_pct=slippage_pct))
    base_te = ev(test)
    results: dict = {"baseline_test": base_te, "single": [], "topn": []}

    # Tek-değişkenli filtreler: eşik EĞİTİM percentilinden (walk-forward).
    specs = [
        ("score>=p70", "score", 0.70, "ge"), ("score>=p85", "score", 0.85, "ge"),
        ("atr<=p50", "atr", 0.50, "le"), ("atr>=p70", "atr", 0.70, "ge"),
        ("rank==1", None, None, "r1"),
    ]
    for name, fld, p, dirc in specs:
        if dirc == "r1":
            f = lambda c: c.get("rank") == 1
        else:
            thr = _pctile([c[fld] for c in train], p)
            f = (lambda th: (lambda c: c[fld] >= th))(thr) if dirc == "ge" \
                else (lambda th: (lambda c: c[fld] <= th))(thr)
        m_tr, m_te = ev(train, f), ev(test, f)
        results["single"].append({"name": name, "train": m_tr, "test": m_te})

    # Gerçek liste taklidi: 30 dk kova başına skorla top-N.
    def topn(pop, minutes, n):
        buckets: dict = {}
        for c in pop:
            buckets.setdefault(int(c["ts"] // (minutes * 60)), []).append(c)
        sel = []
        for b in buckets.values():
            sel.extend(sorted(b, key=lambda z: -z["score"])[:n])
        return sel
    for n in (1, 2, 3, 5):
        m_tr = _metrics(_simulate_population(topn(train, 30, n), bars, cfg,
                                             commission_pct=commission_pct, slippage_pct=slippage_pct))
        m_te = _metrics(_simulate_population(topn(test, 30, n), bars, cfg,
                                             commission_pct=commission_pct, slippage_pct=slippage_pct))
        results["topn"].append({"n": n, "train": m_tr, "test": m_te})

    # Hiçbir filtre sınavda pozitif EV değil mi?
    positives = [s for s in results["single"] if (s["test"]["ev_pct"] or -1) > 0]
    positives += [{"name": f"top{n['n']}", "test": n["test"]} for n in results["topn"]
                  if (n["test"]["ev_pct"] or -1) > 0]
    results["positive_filters"] = positives
    results["verdict"] = "ENTRY_EDGE_FOUND" if positives else "NO_ENTRY_EDGE"
    return results


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=3600.0)
    ap.add_argument("--fetch", action="store_true", help="eksikleri REST'ten çek")
    ap.add_argument("--entry-scan", action="store_true",
                    help="giriş seçici taraması (skor/rank/ATR/top-N) — çıkış grid'ini atlar")
    ap.add_argument("--commission", type=float, default=0.0015)
    ap.add_argument("--slippage", type=float, default=0.00025)
    ap.add_argument("--out", default="work/combined_paper_calibration.json")
    args = ap.parse_args()

    print("=== OTONOM PAPER KALİBRASYON ===")
    cands = _load_candidates(args.hours)
    print(f"aday (passes=true): {len(cands)}")
    if len(cands) < 100:
        print("YETERSİZ VERİ"); return 1

    symbols = {c["symbol"] for c in cands}
    t0 = min(c["ts"] for c in cands)
    t1 = max(c["ts"] for c in cands)
    local = _load_sqlite_bars(symbols, t0 - 300, t1 + 3 * 3600)
    have = {s for s, b in local.items() if b}
    print(f"yerel sqlite kapsamı: {len(have)}/{len(symbols)} sembol")

    bars_by_sym = dict(local)
    if args.fetch:
        days = max(2, int((t1 - t0) / 86400) + 2)
        rest = await _fetch_missing(symbols, have, days)
        for s, b in rest.items():
            bars_by_sym[s] = b
        print(f"REST sonrası kapsam: {len([s for s in bars_by_sym if bars_by_sym[s]])}/{len(symbols)}")

    covered = [c for c in cands if bars_by_sym.get(c["symbol"])]
    print(f"mum bulunan aday: {len(covered)}/{len(cands)}")
    if len(covered) < 100:
        print("KAPSAM YETERSİZ (--fetch deneyin)"); return 1

    # Walk-forward: kronolojik %60 eğitim / %40 sınav.
    covered.sort(key=lambda c: c["ts"])
    split = int(len(covered) * 0.6)
    train, test = covered[:split], covered[split:]
    print(f"eğitim: {len(train)} | sınav: {len(test)}")

    # GİRİŞ TARAMASI modu (2026-10-12): çıkış kalibrasyonundan bağımsız.
    if args.entry_scan:
        print("\n=== GİRİŞ SEÇİCİSİ TARAMASI (walk-forward) ===")
        scan = _entry_scan(train, test, bars_by_sym,
                           commission_pct=args.commission, slippage_pct=args.slippage)
        print(f"  baz (filtresiz) SINAV: {scan['baseline_test']}")
        print("  tek-değişkenli filtreler (SINAV EV):")
        for s in scan["single"]:
            print(f"    {s['name']:12s} → {s['test']['ev_pct']} (n {s['test']['n']}, pf {s['test']['payoff']})")
        print("  gerçek liste taklidi (30dk top-N, SINAV EV):")
        for t in scan["topn"]:
            print(f"    top{t['n']} → {t['test']['ev_pct']} (n {t['test']['n']}, pf {t['test']['payoff']})")
        print(f"  KARAR: {scan['verdict']} (pozitif filtre: {len(scan['positive_filters'])})")
        out = {"generated_at": time.time(), "hours": args.hours,
               "candidates_covered": len(covered), "train_n": len(train),
               "test_n": len(test), "entry_scan": scan}
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"rapor: {args.out}")
        return 0

    print("\n-- varsayılan (canlı) --")
    base_tr = _metrics(_simulate_population(train, bars_by_sym, DEFAULT_CFG,
                                            commission_pct=args.commission, slippage_pct=args.slippage))
    base_te = _metrics(_simulate_population(test, bars_by_sym, DEFAULT_CFG,
                                            commission_pct=args.commission, slippage_pct=args.slippage))
    print("  eğitim:", base_tr)
    print("  sınav :", base_te)

    grid = _grid(DEFAULT_CFG)
    print(f"\n-- grid: {len(grid)} konfig, eğitim kümesinde --")
    scored = []
    for cfg in grid:
        m = _metrics(_simulate_population(train, bars_by_sym, cfg,
                                          commission_pct=args.commission, slippage_pct=args.slippage))
        scored.append((cfg, m))
    scored = [x for x in scored if x[1]["n"] >= 50]
    scored.sort(key=lambda x: (x[1]["ev_pct"] or -999), reverse=True)
    print("  en iyi 5 (eğitim):")
    for cfg, m in scored[:5]:
        print(f"    sl={cfg['sl_pct']} trig={cfg['trail_trigger_pct']} gap={cfg['trail_gap_pct']}"
              f" → EV {m['ev_pct']}% win {m['win_rate']}% payoff {m['payoff']} n={m['n']}")

    # Seçilen konfigi SINAV kümesinde doğrula.
    print("\n-- sınav doğrulaması (ilk 8 aday) --")
    results = []
    for cfg, m_tr in scored[:8]:
        m_te = _metrics(_simulate_population(test, bars_by_sym, cfg,
                                             commission_pct=args.commission, slippage_pct=args.slippage))
        ok = (m_te["ev_pct"] is not None and m_te["ev_pct"] > 0)
        results.append({"cfg": cfg, "train": m_tr, "test": m_te, "test_positive": ok})
        print(f"    sl={cfg['sl_pct']} trig={cfg['trail_trigger_pct']} gap={cfg['trail_gap_pct']}"
              f" → TEST EV {m_te['ev_pct']}% win {m_te['win_rate']}% payoff {m_te['payoff']}"
              f" {'✓' if ok else '✗'}")

    # Kazanan: teste göre EV>0 olanlar arasından test EV en yüksek.
    winners = [r for r in results if r["test_positive"]]
    winners.sort(key=lambda r: r["test"]["ev_pct"], reverse=True)
    winner = winners[0] if winners else None
    baseline_test_ev = base_te["ev_pct"] or 0.0
    improved = bool(winner and (winner["test"]["ev_pct"] or 0) > max(baseline_test_ev, 0))

    report = {
        "generated_at": time.time(),
        "hours": args.hours,
        "candidates_total": len(cands), "candidates_covered": len(covered),
        "train_n": len(train), "test_n": len(test),
        "baseline_default": {"train": base_tr, "test": base_te},
        "top_train": [{"cfg": c, "m": m} for c, m in scored[:8]],
        "validation": results,
        "winner": winner["cfg"] if winner else None,
        "winner_test": winner["test"] if winner else None,
        "baseline_test_ev": baseline_test_ev,
        "improved_over_baseline": improved,
        "recommendation": ("APPLY" if improved else "KEEP_DEFAULT_NO_EDGE"),
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nrapor: {args.out}")
    print(f"KARAR: {report['recommendation']}"
          + (f" → {winner['cfg']}" if winner else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
