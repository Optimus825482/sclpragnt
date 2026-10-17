"""validation90_report.py'nin results.json çıktısından blok karşılaştırma tabloları (markdown) üretir.

Kullanım: python scripts/validation90_tables.py --results work/validation90/results.json --out work/validation90/tables.md
Saf biçimlendirme; DB'ye dokunmaz.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from scripts.radar_shield_rescan_analysis import verdict, welch_t  # noqa: E402
from scripts.validation90_report import ob_verdict  # noqa: E402


def _p(v) -> str:
    return "—" if v is None else "%" + format(100 * v, ".1f")


def _s(v, d=2) -> str:
    return "—" if v is None else format(v, "+." + str(d) + "f")


def _lift(g: dict) -> str:
    return "—" if g.get("lift") is None else format(100 * g["lift"], "+.1f")


def _ci(b) -> str:
    if not b:
        return "—"
    return format(100 * b[0], "+.1f") + " [" + format(100 * b[1], "+.1f") + ", " + format(100 * b[2], "+.1f") + "]"


def _vals(d: dict) -> list[dict]:
    return list(d.values())


def windows(res: dict) -> list[str]:
    return [k for k in res if k not in ("taker", "taker_coarse", "gate")]


def short(label: str) -> str:
    return label.replace("TÜM PENCERE ", "TÜM ")


def build(res: dict, min_n: int = 30) -> str:
    out: list[str] = []
    ws = windows(res)

    out.append("### T1. Kalkan açık vs kapalı (bağımsız bölümler, aşırı alım kapısı canlıdaki gibi; kapı geçenler)")
    out.append("| dönem | kalkan açık payı | n kapalı / açık | hit60 kapalı | hit60 açık | fark pp (gün-küme GA95) | net60 kapalı | net60 açık | net fark Welch t | lift kapalı | lift açık | ön kayıtlı karar |")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for w in ws:
        s = res[w]
        off, on = _vals(s["shield"])[:2]
        wt = welch_t(on, off)
        v = verdict(off, on, min_n)
        out.append("| " + short(w) + " | " + _p(s.get("shield_share")) + " | " + str(off.get("n")) + " / " + str(on.get("n")) + " | "
                   + _p(off.get("hit60")) + " | " + _p(on.get("hit60")) + " | " + _ci(s.get("boot_shield_hit")) + " | "
                   + _s(off.get("net")) + " | " + _s(on.get("net")) + " | " + _s(wt, 1) + " | " + _lift(off) + " | " + _lift(on) + " | **" + v + "** |")

    out.append("\n### T1b. Net60 farkı (açık − kapalı) gün-küme GA95, yüzde puan")
    out.append("| dönem | net60 fark [GA95] |")
    out.append("|---|---|")
    for w in ws:
        b = res[w].get("boot_shield_net")
        out.append("| " + short(w) + " | " + (_s(b[0]) + " [" + _s(b[1]) + ", " + _s(b[2]) + "]" if b else "—") + " |")

    out.append("\n### T2. Kalkan açıkken yumuşak vs sert bölge")
    out.append("| dönem | yumuşak n | yumuşak hit60 | yumuşak net60 | yumuşak lift | sert n | sert hit60 | sert net60 | sert lift |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for w in ws:
        soft, hard = _vals(res[w]["shield_soft"])[:2]
        out.append("| " + short(w) + " | " + str(soft.get("n")) + " | " + _p(soft.get("hit60")) + " | " + _s(soft.get("net")) + " | " + _lift(soft)
                   + " | " + str(hard.get("n")) + " | " + _p(hard.get("hit60")) + " | " + _s(hard.get("net")) + " | " + _lift(hard) + " |")

    out.append("\n### T3. Aşırı alım kapısı (kalkan KAPALI bölümlerde): geçen vs elenen")
    out.append("| dönem | n geçti / elendi | hit60 geçti | hit60 elendi | fark pp (gün-küme GA95) | net60 geçti | net60 elendi | MAE60 geçti / elendi | lift geçti | lift elendi | ön kayıtlı karar |")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for w in ws:
        s = res[w]
        p, e = _vals(s["overbought"])[:2]
        v = ob_verdict(p, e, min_n)
        out.append("| " + short(w) + " | " + str(p.get("n")) + " / " + str(e.get("n")) + " | " + _p(p.get("hit60")) + " | " + _p(e.get("hit60")) + " | "
                   + _ci(s.get("boot_ob_hit")) + " | " + _s(p.get("net")) + " | " + _s(e.get("net")) + " | "
                   + _s(p.get("mae")) + " / " + _s(e.get("mae")) + " | " + _lift(p) + " | " + _lift(e) + " | **" + v + "** |")

    out.append("\n### T3b. Aşırı alım kapısı — yalnız trend_devam modu, kalkan KAPALI")
    out.append("| dönem | n geçti / elendi | hit60 geçti | hit60 elendi | net60 geçti | net60 elendi | lift geçti | lift elendi | karar |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for w in ws:
        p, e = _vals(res[w]["overbought_trend"])[:2]
        out.append("| " + short(w) + " | " + str(p.get("n")) + " / " + str(e.get("n")) + " | " + _p(p.get("hit60")) + " | " + _p(e.get("hit60")) + " | "
                   + _s(p.get("net")) + " | " + _s(e.get("net")) + " | " + _lift(p) + " | " + _lift(e) + " | " + ob_verdict(p, e, min_n) + " |")

    out.append("\n### T4. trend_devam × kalkan (kapı geçen)")
    out.append("| dönem | n kapalı / açık | hit60 kapalı | hit60 açık | net60 kapalı | net60 açık | lift kapalı | lift açık | karar |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for w in ws:
        off, on = _vals(res[w]["trend_shield"])[:2]
        out.append("| " + short(w) + " | " + str(off.get("n")) + " / " + str(on.get("n")) + " | " + _p(off.get("hit60")) + " | " + _p(on.get("hit60")) + " | "
                   + _s(off.get("net")) + " | " + _s(on.get("net")) + " | " + _lift(off) + " | " + _lift(on) + " | " + verdict(off, on, min_n) + " |")

    out.append("\n### T5. 2×2 kalkan × aşırı alım (hit60 / net60 / lift pp, n)")
    out.append("| dönem | kapalı·geçti | kapalı·aşırı alım | açık·geçti | açık·aşırı alım |")
    out.append("|---|---|---|---|---|")
    for w in ws:
        cells = []
        for g in _vals(res[w]["cross"])[:4]:
            cells.append(_p(g.get("hit60")) + " / " + _s(g.get("net")) + " / " + _lift(g) + " (n=" + str(g.get("n")) + ")")
        out.append("| " + short(w) + " | " + " | ".join(cells) + " |")

    out.append("\n### T6. Hız Avcısı temel çizgisi (kapı geçen, rank<=10, bağımsız bölüm)")
    out.append("| dönem | kalkandan bağımsız (badge modu) n | hit60 | net60 (t) | lift pp | yalnız kalkan kapalı (eski canlı) n | hit60 | net60 (t) | lift pp |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for w in ws:
        a, o = res[w]["base_any"], res[w]["base_shield_off"]

        def nt(g):
            return _s(g.get("net")) + (" (t " + _s(g.get("t"), 1) + ")" if g.get("t") is not None else "")
        out.append("| " + short(w) + " | " + str(a.get("n")) + " | " + _p(a.get("hit60")) + " | " + nt(a) + " | " + _lift(a)
                   + " | " + str(o.get("n")) + " | " + _p(o.get("hit60")) + " | " + nt(o) + " | " + _lift(o) + " |")

    tk = res.get("taker") or {}
    if tk:
        out.append("\n### T7. Taker: strong − weak (rank<=10, kapı geçen, bağımsız bölüm)")
        out.append("| dönem | n strong / neutral / weak | hit60 strong | hit60 neutral | hit60 weak | fark pp (z) | net60 strong / weak | Welch t | lift farkı pp |")
        out.append("|---|---|---|---|---|---|---|---|---|")
        for k, v in tk.items():
            if not isinstance(v, dict) or "strong" not in v:
                continue
            s_, n_, w_ = v["strong"], v["neutral"], v["weak"]
            out.append("| " + short(k) + " | " + str(s_["n"]) + " / " + str(n_.get("n")) + " / " + str(w_["n"]) + " | " + _p(s_["hit60"]) + " | " + _p(n_.get("hit60"))
                       + " | " + _p(w_["hit60"]) + " | " + _s(v["diff_pp"], 1) + " (z " + _s(v["z"], 2) + ") | " + _s(s_["net"]) + " / " + _s(w_["net"])
                       + " | " + _s(v["welch_t"], 1) + " | " + (_s(v["lift_diff_pp"], 1) if v.get("lift_diff_pp") is not None else "—") + " |")
        out.append("\nÖn kayıtlı taker kuralı: **" + str(tk.get("rule")) + "**")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", default="work/validation90/results.json")
    ap.add_argument("--out", default="work/validation90/tables.md")
    ap.add_argument("--min-n", type=int, default=30)
    args = ap.parse_args(argv)
    res = json.loads(Path(args.results).read_text(encoding="utf-8"))
    md = build(res, args.min_n)
    Path(args.out).write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
