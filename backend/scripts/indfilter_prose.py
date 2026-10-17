"""İndikatör filtresi / hedef çalışması — rapor için SAYILARDAN üretilen hüküm metni (2026-10-17). Saf işlev: özet sözlüklerinden Türkçe markdown.

`scripts/indfilter_report.py` çağırır. Hiçbir sayı elle yazılmaz; kural geçişi `rule_passes` / `model_vs_fixed` ile aynı ölçütlerle belirlenir.
"""
from __future__ import annotations

import numpy as np

NL = chr(10)


def f2(x, nd: int = 2) -> str:
    return "–" if x is None or not np.isfinite(x) else ("%+." + str(nd) + "f") % x


def rule_rows(rows: list[dict], name: str) -> dict:
    out = {"blocks": {}, "comb": None}
    for x in rows:
        if x["name"] != name:
            continue
        if x["block"] == -1:
            out["comb"] = x
        else:
            out["blocks"][x["block"]] = x
    return out


def passes(rows: list[dict], name: str, nb: int, min_n: int = 50) -> bool:
    r = rule_rows(rows, name)
    comb = r["comb"] if r["comb"] is not None else r["blocks"].get(1)
    oos = [r["blocks"].get(b) for b in range(1, nb)]
    if comb is None or any(x is None for x in oos):
        return False
    return all(x["delta"] > 0 and x["net"] > x["net_all"] and x["n"] >= min_n for x in oos) and comb["lo"] > 0


def filter_prose(A: dict, nb_by_pop: dict) -> list[str]:
    out = []
    for pop, title in (("ha", "Hız Avcısı (90 gün, 3 blok)"), ("notif", "Push bildirimleri (17.09–17.10; seçim/değerlendirme)")):
        s = A.get(pop)
        if not s:
            continue
        nb = nb_by_pop[pop]
        n_exn, n_hit, n_rawnet, n_tot = s.get("nsig_tümü", (0, 0, 0, 0))
        both, opp = s.get("opp_tümü", (0, 0))
        out.append("- **%s.** %d özellikten ATR-kontrollü net−taban'da BH q<0,05: %d (tüm bloklarda aynı işaretli: %d); ATR-kontrollü hit'te q<0,05: %d; "
                   "ham net'te q<0,05: %d. Hem hit'te hem net−taban'da anlamlı %d özelliğin %d'sinde işaret TERS (hit'i artıran özellik net'i düşürüyor)."
                   % (title, n_tot, n_exn, s.get("cons_tümü", 0), n_hit, n_rawnet, both, opp))
        top = s.get("top_tümü", [])[:4]
        if top:
            out.append("  En güçlü ATR-kontrollü özellikler (r, t, q, blok uyumu): " + "; ".join(
                "`%s` (%+.3f, %+.1f, %.3f, %d/%d)" % (n, r, t, q, a, nb) for n, r, t, q, a in top) + ".")
        for sc in [k for k in s if k.startswith("rules_")]:
            rows = s[sc]
            names = sorted({x["name"] for x in rows})
            okn = [n for n in names if passes(rows, n, nb)]
            out.append("  Kural kapsamı `%s`: seçim döneminde seçilen %d kuraldan seçim-dışı her blokta Δ(net−taban) > 0, net(tutulan) > net(hepsi) ve birleşik %%95 alt sınır > 0 olan: **%d**."
                       % (sc[6:], len(names), len(okn)))
            for n in okn:
                r = rule_rows(rows, n)
                comb = r["comb"] if r["comb"] is not None else r["blocks"][1]
                per = ", ".join("blok %d: Δ %s, net %s (hepsi %s), n=%d" % (b + 1, f2(r["blocks"][b]["delta"]), f2(r["blocks"][b]["net"]), f2(r["blocks"][b]["net_all"]),
                                                                         r["blocks"][b]["n"]) for b in sorted(r["blocks"]) if b >= 1)
                out.append("  - GEÇEN KURAL `%s`: seçim-dışı birleşik n=%d (%.0f/gün), net %s (hepsi %s), net−taban %s, Δ(net−taban) %s [alt sınır %s]; %s. %s"
                           % (n, comb["n"], comb["per_day"], f2(comb["net"]), f2(comb["net_all"]), f2(comb["ex"]), f2(comb["delta"]), f2(comb["lo"]), per,
                              "Mutlak net hâlâ NEGATİF." if comb["net"] < 0 else "Mutlak net pozitif."))
        cl = [c for c in s.get("classic", []) if c[1]]
        sig = sorted(s.get("classic", []), key=lambda c: -abs(c[3]) if np.isfinite(c[3]) else 0)[:3]
        out.append("  Klasik fikirler (%d önceden belirlenmiş koşul): her blokta tutulan−düşen > 0 ve %%95 alt sınır > 0 olan: **%d**. "
                   "|t| en büyük üç fikir: %s." % (len(s.get("classic", [])), len(cl), "; ".join("`%s` (Δ %s, t %+.1f)" % (n[5:], f2(d), t) for n, ok, d, t in sig)))
        ne, nn = s.get("noise_ex", {}), s.get("noise_net", {})
        if ne:
            out.append("  Aşırı-uyum tanısı: seçimde en iyi 50 adayın seçim-dışı ortalama Δ(net−taban) = %s (pozitif pay %.0f%%); tüm adaylar %s." % (
                f2(ne.get("top_mean_oos")), 100 * ne.get("top_pos", float("nan")), f2(ne.get("all_mean_oos"))))
    return out


def target_prose(B: dict, nb_by_pop: dict) -> list[str]:
    out = []
    fixed = "M0 sabit (sinyalin hedefi)"
    for pop, title in (("ha", "Hız Avcısı"), ("notif", "Push bildirimleri")):
        s = B.get(pop)
        if not s:
            continue
        nb = nb_by_pop[pop]
        for sc, res in s["res"].items():
            oosb = -1 if nb > 2 else 1
            oos = {x["name"]: x for x in res if x["block"] == oosb}
            if fixed not in oos:
                continue
            m0 = oos[fixed]
            ranked = sorted((x for k, x in oos.items() if k != fixed), key=lambda x: -x["net"])[:3]
            out.append("- **%s / %s.** Seçim-dışı: sabit (sinyalin) hedef net %s, hit %.1f%%, ort. hedef %.2f%%. En iyi 3 model (ham net): " % (
                title, sc, f2(m0["net"]), 100 * m0["hit"], m0["tp"]) + "; ".join(
                "`%s` net %s (Δ vs sabit %s [%s; %s]), hit %.1f%%, ort. hedef %.2f%%" % (x["name"], f2(x["net"]), f2(x["dnet"]), f2(x["dnet_lo"]), f2(x["dnet_hi"]),
                                                                                    100 * x["hit"], x["tp"]) for x in ranked) + ".")
            pos = [k for k, x in oos.items() if x["net"] > 0]
            out.append("  Seçim-dışı mutlak net > 0 olan model: **%d**." % len(pos))
        acc = s.get("acc", [])
        imps = [(x["name"], x["block"], x["pin_imp_pct"], x["partial"]) for x in acc if np.isfinite(x["pin_imp_pct"]) and x["block"] >= 1]
        if imps:
            out.append("  Hedef doğruluğu (pinball, aynı q'lu ATR-yalnız referansa göre iyileşme; seçim-dışı bloklar): " + "; ".join(
                "`%s` blok %d: %+.1f%% (kısmi Spearman | ATR %+.3f)" % (n, b + 1, i, pa) for n, b, i, pa in imps[:6]) + ".")
        for sc, at in s.get("attr", {}).items():
            oosa = [x for x in at if x["block"] == (-1 if nb > 2 else 1)]
            if oosa:
                out.append("  İndikatör katkısı (%s; özellikli model − ATR-yalnız referans, seçim-dışı Δnet): " % sc + "; ".join(
                    "`%s` %s [alt %s]" % (x["name"], f2(x["dnet"]), f2(x["dnet_lo"])) for x in oosa) + ".")
    return out


def verdict_line(A: dict, B: dict, nb_by_pop: dict) -> str:
    """Tek cümlelik net hüküm."""
    ok_f = []
    for pop in ("ha", "notif"):
        s = A.get(pop)
        if not s:
            continue
        for sc in [k for k in s if k.startswith("rules_")]:
            rows = s[sc]
            for n in sorted({x["name"] for x in rows}):
                if passes(rows, n, nb_by_pop[pop]):
                    r = rule_rows(rows, n)
                    comb = r["comb"] if r["comb"] is not None else r["blocks"][1]
                    ok_f.append((pop, sc[6:], n, comb))
    pos_net = [x for x in ok_f if x[3]["net"] > 0]
    if not ok_f:
        return "HAYIR: seçim dönemiyle seçilen hiçbir indikatör filtresi, seçim-dışı her blokta net−taban'ı iyileştirmedi; mutlak net hiçbirinde pozitif değil."
    if not pos_net:
        return ("KISMEN: %d kural seçim-dışı her blokta net−taban'ı küçük ölçüde iyileştirdi (ayrıntılar yukarıda) ama mutlak net her birinde NEGATİF kaldı; "
                "yani zararı azaltıyor, kâra çevirmiyor." % len(ok_f))
    return "EVET: %d kural seçim-dışı her blokta net−taban'ı iyileştirdi ve mutlak neti pozitif." % len(pos_net)
