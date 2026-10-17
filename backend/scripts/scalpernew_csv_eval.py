"""scalpernew uygulamasının bildirim CSV'sini (ve aynı dönemdeki bizim prod bildirimlerimizi) aynı ölçüyle değerlendirir.

Ölçü (önceki çalışmalarla aynı, docs/CIKIS_YAPISI_SIMULASYONU_2026-10-17.md):
  giriş = sinyal + 60 sn sonraki ilk 1 dk barın açılışı × (1 + %0,15), bacak başına %0,1125 ücret, stop/zaman çıkışı
  %0,15 kaymalı, aynı barda stop önce. Hücreler: H = TP aday hedefi, SL %3, süre = bildirim ufku; H60 = aynı, süre 60 dk;
  TR = izleyen (tetik %1, mesafe %0,8), SL %3, 60 dk. İsabet: ufuk / 60 dk içinde en yüksek ≥ hedef (giriş barı açılışına göre).
  Ham 60 dk sürüklenme: 60. dakikanın kapanışı / giriş açılışı − 1 (ücretsiz).
  Rastgele taban: aynı sembol, sinyalin ±3 günü, o sembolün TÜM bildirimlerinden ≥ 2 sa uzak 20 an; aynı hedef ve çıkışlar.

Kullanım (backend/):
  DATABASE_URL=... python scripts/scalpernew_csv_eval.py --csv <yol> [--ours work/prod_notifications_1015_1017.tsv]
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.rescan.exit_sim import ExitSpec, entry_index, gather_windows, simulate  # noqa: E402

TZ = timezone(timedelta(hours=3))
SLIP = 0.15
SPECS = {
    "H": None,  # ufka göre ayrı kurulur
    "H60": ExitSpec("H60", "fixed", sl=3.0, time_min=60, tp_cand=True),
    "TR": ExitSpec("TR", "trail", sl=3.0, time_min=60, act=1.0, gap=0.8),
}
N_RAND = 20


def norm_sources(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    parts = raw.replace(",", "|").split("|")
    tr = {"hız": "velocity", "hiz": "velocity", "sıçrama": "jump", "erken uyarı": "early", "yükseliş eğilimi": "rising"}
    return sorted({tr.get(p.strip().lower(), p.strip().lower()) for p in parts if p.strip()})


DISABLED_MODES = {"notr", "v_donusu", "llm_ikinci_goz"}


def live_policy(sources: list[str], mode: str) -> bool:
    """Bugünkü canlı politika: kapalı modlar (notr, v_donusu, llm_ikinci_goz) + teyit kuralı."""
    return (mode or "").lower() not in DISABLED_MODES and confirm_rule(sources, mode)


def confirm_rule(sources: list[str], mode: str) -> bool:
    """Bizim canlı teyit kuralımız: ≥2 farklı kaynak ∧ velocity ∧ mod ≠ unified."""
    return len(set(sources)) >= 2 and "velocity" in sources and (mode or "").lower() != "unified"


def load_csv(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            try:
                t = float(r["detected_at"])
                price = float(r["price"])
                tp = float(r["target_pct"])
            except (TypeError, ValueError, KeyError):
                continue
            src = norm_sources(r.get("sources") or "")
            rows.append({"src_file": "scalpernew", "t": t, "symbol": r["symbol"].upper(), "mode": (r.get("mode") or "").lower(),
                         "score": float(r.get("score") or "nan"), "tp": tp, "hz": int(float(r.get("horizon_minutes") or 5)),
                         "price": price, "sources": src, "push": (r.get("sent_via_push") or "").strip().lower() == "true",
                         "their_status": r.get("status") or "", "their_net": float(r["net_pct"]) if r.get("net_pct") else float("nan"),
                         "whale_verdict": r.get("whale_verdict") or ""})
    return rows


def load_ours(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            t = datetime.strptime(r["time_local"], "%Y-%m-%d %H:%M").replace(tzinfo=TZ).timestamp()
            src = norm_sources(r["sources"].replace(", ", "|"))
            rows.append({"src_file": "bizim_prod", "t": t, "symbol": r["symbol"].upper(), "mode": "", "score": float("nan"),
                         "tp": float(r["target_pct"]), "hz": int(r["horizon_min"]), "price": float(r["price"]), "sources": src,
                         "push": r["channel"] == "Push", "their_status": r["result"], "their_net": float("nan"), "whale_verdict": ""})
    return rows


def load_candles(db_url: str, symbols: set[str], t0: float, t1: float) -> dict:
    import psycopg
    out = {}
    with psycopg.connect(db_url, connect_timeout=10) as conn:
        for s in sorted(symbols):
            rr = conn.execute("SELECT open_time, open, high, low, close FROM historical_candles WHERE symbol=%s AND timeframe='1m' "
                              "AND open_time >= %s AND open_time <= %s ORDER BY open_time", (s, int(t0 * 1000), int(t1 * 1000))).fetchall()
            if rr:
                a = np.array(rr, dtype=float)
                out[s] = (a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4])
    return out


def eval_points(series, t_s: np.ndarray, tp: np.ndarray, hz: np.ndarray, price: np.ndarray | None = None) -> dict:
    """Tek sembol için noktalar → ölçümler (geçersizler NaN)."""
    ot, o, h, l, c = series
    n = len(t_s)
    res = {k: np.full(n, np.nan) for k in ("H", "H60", "TR", "hit_h", "hit60", "drift60", "hit_sig")}
    idx, ok = entry_index(ot, (t_s * 1000).astype(np.int64), delay_s=60)
    if not ok.any():
        return res
    O, H, L, C, ref, cov = gather_windows(ot, o, h, l, c, idx, 60)
    ok &= cov
    for name in ("H60", "TR"):
        out = simulate(O, H, L, C, SPECS[name], slip_pct=SLIP, tp_cand_pct=tp)
        res[name] = np.where(ok, out["net"], np.nan)
    for hzv in (5, 15):
        m = hz == hzv
        if m.any():
            out = simulate(O[m], H[m], L[m], C[m], ExitSpec("H", "fixed", sl=3.0, time_min=hzv, tp_cand=True), slip_pct=SLIP, tp_cand_pct=tp[m])
            res["H"][m] = np.where(ok[m], out["net"], np.nan)
    hmax_h = np.array([H[i, :max(1, hz[i])].max() for i in range(n)])
    res["hit_h"] = np.where(ok, (hmax_h - 1.0) * 100 >= tp, np.nan)
    res["hit60"] = np.where(ok, (H.max(axis=1) - 1.0) * 100 >= tp, np.nan)
    res["drift60"] = np.where(ok, (C[:, -1] - 1.0) * 100, np.nan)
    # gecikmesiz, bildirim fiyatından ölçülen dokunuş (uygulamaların kendi etiketine yakın, iyimser ölçü)
    if price is not None:
        idx0, ok0 = entry_index(ot, (t_s * 1000).astype(np.int64), delay_s=0)
        O0, H0, L0, C0, ref0, cov0 = gather_windows(ot, o, h, l, c, idx0, 60)
        hm0 = np.array([H0[i, :max(1, hz[i])].max() for i in range(n)]) * ref0
        res["hit_sig"] = np.where(ok0 & cov0, (hm0 / price - 1.0) * 100 >= tp, np.nan)
    return res


def evaluate(rows: list[dict], candles: dict, rng: np.random.Generator) -> None:
    by_sym: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        by_sym.setdefault(r["symbol"], []).append(i)
    for s, ids in by_sym.items():
        ser = candles.get(s)
        if ser is None:
            continue
        t = np.array([rows[i]["t"] for i in ids]); tp = np.array([rows[i]["tp"] for i in ids]); hz = np.array([rows[i]["hz"] for i in ids])
        res = eval_points(ser, t, tp, hz, np.array([rows[i]["price"] for i in ids]))
        for j, i in enumerate(ids):
            for k, v in res.items():
                rows[i][k] = float(v[j])
        # rastgele taban: aynı sembol, ±3 gün, bildirimlerden ≥ 2 sa uzak
        ot = ser[0] / 1000.0
        sig_all = np.array(sorted(t))
        for j, i in enumerate(ids):
            lo, hi = t[j] - 3 * 86400, t[j] + 3 * 86400
            cand = ot[(ot >= lo) & (ot <= hi)]
            if len(cand) == 0:
                continue
            near = np.abs(cand[:, None] - sig_all[None, :]).min(axis=1) < 7200
            pool = cand[~near]
            if len(pool) < 5:
                continue
            pick = rng.choice(pool, size=min(N_RAND, len(pool)), replace=False)
            rr = eval_points(ser, pick, np.full(len(pick), tp[j]), np.full(len(pick), hz[j]))
            for k in ("H", "H60", "TR", "hit_h", "hit60", "drift60"):
                rows[i]["rnd_" + k] = float(np.nanmean(rr[k])) if np.isfinite(rr[k]).any() else float("nan")


def summarize(rows: list[dict], label: str) -> list:
    ok = [r for r in rows if np.isfinite(r.get("H60", np.nan))]
    if not ok:
        return [label, 0] + ["—"] * 8
    def m(k):
        v = np.array([r.get(k, np.nan) for r in ok], dtype=float); return np.nanmean(v)
    def ci(k):
        v = np.array([r.get(k, np.nan) for r in ok], dtype=float); v = v[np.isfinite(v)]
        return 1.96 * v.std(ddof=1) / math.sqrt(len(v)) if len(v) > 1 else float("nan")
    d = np.array([r.get("H60", np.nan) - r.get("rnd_H60", np.nan) for r in ok], dtype=float)
    dd = d[np.isfinite(d)]
    days = max(1e-9, (max(r["t"] for r in ok) - min(r["t"] for r in ok)) / 86400)
    return [label, len(ok), f"{len(ok)/days:.0f}", f"%{100*m('hit_h'):.1f}", f"%{100*m('hit60'):.1f}",
            f"{m('H'):+.2f}", f"{m('H60'):+.2f} ±{ci('H60'):.2f}", f"{m('TR'):+.2f}", f"{m('drift60'):+.2f}",
            f"{np.nanmean(dd):+.2f}" if len(dd) else "—"]


HEAD = ["küme", "n", "/gün", "isabet (ufuk)", "isabet 60 dk", "net ufuk", "net 60 dk [±%95]", "net izleyen", "ham 60 dk sürüklenme", "net60 − rastgele"]


def md(rows: list[list]) -> str:
    out = ["| " + " | ".join(HEAD) + " |", "|" + "---|" * len(HEAD)]
    out += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--ours", default="work/prod_notifications_1015_1017.tsv")
    ap.add_argument("--out", default="work/scalpernew_eval/report.md")
    args = ap.parse_args(argv)
    db = os.environ["DATABASE_URL"]
    sn = load_csv(args.csv)
    ours = load_ours(args.ours) if os.path.exists(args.ours) else []
    allrows = sn + ours
    t0 = min(r["t"] for r in allrows) - 4 * 86400; t1 = max(r["t"] for r in allrows) + 4 * 86400
    candles = load_candles(db, {r["symbol"] for r in allrows}, t0, t1)
    rng = np.random.default_rng(7)
    evaluate(sn, candles, rng); evaluate(ours, candles, rng)
    ov0 = min(r["t"] for r in ours) if ours else 0; ov1 = max(r["t"] for r in ours) if ours else 0
    sn_ov = [r for r in sn if ov0 <= r["t"] <= ov1]
    lines = []
    lines.append(f"# scalpernew bildirimleri — bağımsız ölçüm ({datetime.fromtimestamp(min(r['t'] for r in sn), TZ):%d.%m %H:%M} → "
                 f"{datetime.fromtimestamp(max(r['t'] for r in sn), TZ):%d.%m %H:%M})\n")
    lines.append(f"CSV satırı {len(sn)}; ölçülebilen (60 dk penceresi mum kapsamında) "
                 f"{sum(1 for r in sn if np.isfinite(r.get('H60', np.nan)))}. Ölçü: 60 sn gecikme, %0,15 kayma, %0,1125 ücret/bacak, SL %3.\n")
    t = []
    t.append(summarize(sn, "scalpernew — tümü"))
    t.append(summarize([r for r in sn if r["push"]], "scalpernew — push"))
    t.append(summarize([r for r in sn if not r["push"]], "scalpernew — panel"))
    for mode in sorted({r["mode"] for r in sn}):
        t.append(summarize([r for r in sn if r["mode"] == mode], f"scalpernew — mod {mode or '?'}"))
    for k in (1, 2, 3):
        t.append(summarize([r for r in sn if (len(r["sources"]) >= 3 if k == 3 else len(r["sources"]) == k)], f"scalpernew — {k}{'+' if k == 3 else ''} kaynak"))
    t.append(summarize([r for r in sn if confirm_rule(r["sources"], r["mode"])], "scalpernew — BİZİM TEYİT KURALINDAN GEÇEN"))
    t.append(summarize([r for r in sn if not confirm_rule(r["sources"], r["mode"])], "scalpernew — teyit kuralına takılan"))
    t.append(summarize([r for r in sn if live_policy(r["sources"], r["mode"])], "scalpernew — BİZİM TÜM CANLI POLİTİKAMIZDAN GEÇEN"))
    t.append(summarize([r for r in sn if r["mode"] in DISABLED_MODES], "scalpernew — bizde kapalı modlar (notr, v_donusu)"))
    t.append(summarize([r for r in sn if r["mode"] == "trend_devam" and len(r["sources"]) >= 2], "scalpernew — gölge kural (≥2 ∧ trend_devam)"))
    lines.append("## 1. scalpernew bildirimleri\n\n" + md(t) + "\n")
    if ours:
        t2 = [summarize(sn_ov, "scalpernew — çakışan dönem"), summarize(ours, "bizim prod — aynı dönem"),
              summarize([r for r in sn_ov if confirm_rule(r["sources"], r["mode"])], "scalpernew çakışan — teyit kuralından geçen"),
              summarize([r for r in ours if confirm_rule(r["sources"], "trend_devam")], "bizim prod — teyit kuralından geçen (mod bilinmiyor)")]
        lines.append(f"## 2. Aynı dönemde karşılaştırma ({datetime.fromtimestamp(ov0, TZ):%d.%m %H:%M} → {datetime.fromtimestamp(ov1, TZ):%d.%m %H:%M})\n\n" + md(t2) + "\n")
        sym_sn = {r["symbol"] for r in sn_ov}; sym_us = {r["symbol"] for r in ours}
        lines.append(f"Ortak sembol {len(sym_sn & sym_us)}, yalnız scalpernew {len(sym_sn - sym_us)}, yalnız bizim {len(sym_us - sym_sn)}.\n")
    # uygulamanın kendi etiketiyle uyum
    hs = np.array([r.get("hit_sig", np.nan) for r in sn], dtype=float)
    lines.append(f"Gecikmesiz, bildirim fiyatından ölçülen ufuk-içi dokunuş: %{100*np.nanmean(hs):.1f} (60 sn gecikme + kayma ile: "
                 f"%{100*np.nanmean([r.get('hit_h', np.nan) for r in sn]):.1f}).\n")
    agree = [(r["their_status"], r.get("hit_h")) for r in sn if np.isfinite(r.get("hit_h", np.nan))]
    from collections import Counter
    cnt = Counter((s, "ulaştı" if h else "ulaşmadı") for s, h in agree)
    lines.append("## 3. scalpernew'in kendi sonucu × bizim ölçüm (ufuk içinde hedefe değdi mi)\n\n| scalpernew durumu | bizim: ulaştı | bizim: ulaşmadı |\n|---|---|---|\n" +
                 "\n".join(f"| {s} | {cnt.get((s, 'ulaştı'), 0)} | {cnt.get((s, 'ulaşmadı'), 0)} |" for s in sorted({a for a, _ in agree})) + "\n")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    open(args.out, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
