"""90 günlük çıkış deseni çalışması — rapor tabloları (markdown parçaları) üretir. `work/pattern90/tables/*.md`.

`pattern90_analysis.py` çıktıları (analysis.json, patterns.json, backtest.json) + events.pkl okunur. Ondalık nokta → virgül.
"""
from __future__ import annotations

import argparse
import collections
import json
import pickle
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from scripts.pattern90_study import TZ, fmt_t  # noqa: E402

SET_ORDER = ["A", "B", "C1", "C2", "C3"]
TF_ORDER = ("5m", "3m", "1m")


def dec(txt: str) -> str:
    return re.sub(r"(?<=\d)\.(?=\d)", ",", txt)


def g(x, nd=3):
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{nd}g}"


def pc(x, nd=1):
    return "—" if x is None else f"%{100 * x:.{nd}f}"


def pp(x, nd=1):
    return "—" if x is None else f"{100 * x:+.{nd}f} pp"


def nr(x, fmt="{:+.2f}"):
    return "—" if x is None else fmt.format(x)


def table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def iso_week_start(ms: int) -> str:
    d = datetime.fromtimestamp(ms / 1000, TZ)
    ds = d.date().toordinal() - d.weekday()
    return datetime.fromordinal(ds).strftime("%d.%m")


# ------------------------------------------------------------------------------------------------ olaylar
def events_tables(E: dict) -> dict[str, str]:
    ev = E["events"]; dc = E["decluster"]
    T: dict[str, str] = {}
    wk = collections.OrderedDict()
    for e in ev:
        k = iso_week_start(e["t0"])
        w = wk.setdefault(k, {"n": 0, "keep": 0, "cl": set(), "maxb": 0, "syms": set(), "gain": []})
        w["n"] += 1; w["keep"] += int(e["keep"]); w["syms"].add(e["sym"]); w["gain"].append(e["gain"])
        w["maxb"] = max(w["maxb"], e["bucket_n"])
        if e["cluster"]:
            w["cl"].add(e["t0"])
    rows = []
    for k, w in wk.items():
        rows.append([k, str(w["n"]), str(w["keep"]), str(len(w["syms"])), str(len(w["cl"])), str(w["maxb"]), f"%{np.median(w['gain']):.1f}"])
    rows.append(["**toplam**", str(len(ev)), str(sum(int(e['keep']) for e in ev)), str(len({e['sym'] for e in ev})),
                 str(dc["n_cluster_buckets"]), str(max(e["bucket_n"] for e in ev)), f"%{np.median([e['gain'] for e in ev]):.1f}"])
    T["events_weekly"] = table(["hafta (Pzt)", "olay", "kümesiz (birincil)", "sembol", "küme kovası (>8)", "en kalabalık 5 dk kovası", "kazanç medyan"], rows)
    rows = [[fmt_t(t, "%d.%m %H:%M"), str(n)] for t, n in dc["cluster_buckets"]]
    T["cluster_buckets"] = table(["5 dk kovası (t0)", "aynı kovadaki olay"], rows)
    bs = collections.Counter(e["bucket_n"] for e in ev)
    cnt_b = collections.Counter()
    for t in {e["t0"] for e in ev}:
        pass
    by_t = collections.Counter(e["t0"] for e in ev)
    hist = collections.Counter(by_t.values())
    T["bucket_hist"] = table(["kovadaki olay sayısı", "kova sayısı"], [[str(k), str(v)] for k, v in sorted(hist.items())])
    days = collections.Counter(datetime.fromtimestamp(e["t0"] / 1000, TZ).strftime("%d.%m") for e in ev)
    n_days = len(days); med = float(np.median(list(days.values())))
    top = sorted(days.items(), key=lambda x: -x[1])[:6]
    T["events_days"] = f"{n_days} gün; günlük olay medyanı {med:.0f}; en yoğun günler: " + ", ".join(f"{d} ({n})" for d, n in top) + "."
    T["decluster_counts"] = table(["kümesizleştirme", "olay"], [
        ["hiçbiri (tüm olaylar)", str(len(ev))],
        ["**birincil**: >8 olaylı kovalarda tek olay (5 kova)", str(dc["keep_a"])],
        ["±15 dk pencerede >8 olay olan kovalarda tek olay", str(dc["keep_c"])],
        ["her 5 dk kovada tek olay (en sıkı)", str(dc["keep_b"])]])
    return T


# ------------------------------------------------------------------------------------------------ özellik tabloları
def stack_tables(A: dict) -> dict[str, str]:
    names = A["names"]
    m = {r["feature"]: r for r in A["rank"]["B|t0|matched"]}
    p = {r["feature"]: r for r in A["rank"]["B|t0|pooled"]}
    T = {}
    for tf in TF_ORDER:
        rows = []
        for nm in [n for n in names if n.startswith(tf + ".")]:
            r, q = m[nm], p[nm]
            lab = nm.split(".", 1)[1]
            tk = r["tk"]
            cells = [lab, f"{g(r['ev'][1])} [{g(r['ev'][0])}; {g(r['ev'][2])}]", f"{g(r['ba'][1])} [{g(r['ba'][0])}; {g(r['ba'][2])}]",
                     f"{r['auc']:.2f}", f"{r['d']:+.2f}", f"{r['iqr_ratio']:.2f}", f"{q['auc']:.2f}",
                     ("✓" if r["sig_all"] else "") + ("" if tk else (" (taker'sız ✓)" if r["sig_base"] else ""))]
            rows.append([("**" + c + "**") if (tk and c) else c for c in cells])
        T[f"stack_{tf}"] = table([f"özellik ({tf})", "olay medyan [Ç1; Ç3]", "taban medyan [Ç1; Ç3]", "AUC (eşleşmiş)", "d", "IQR oranı",
                                  "AUC (havuz)", "FWER"], rows)
    return T


def rank_tables(A: dict) -> dict[str, str]:
    T = {}
    for sk in SET_ORDER:
        for t in ("t0", "t15"):
            for base in ("matched", "pooled"):
                key = f"{sk}|{t}|{base}"
                recs = A["rank"][key]; mt = A["meta"][key]
                rows = []
                for r in recs[:12]:
                    rows.append([str(r["rank_all"]), ("**" + r["feature"] + "**") if r["tk"] else r["feature"], f"{r['auc']:.3f}", f"{r['d']:+.2f}",
                                 f"{r['iqr_ratio']:.2f}", "✓" if r["sig_all"] else "", "—" if r["tk"] else str(r["rank_base"])])
                T[f"rank_{sk}_{t}_{base}"] = (table(["# (taker'lı)", "özellik", "AUC", "d", "IQR oranı", "FWER", "# (taker'sız)"], rows)
                                              + f"\n\nolay {mt['n_events']}, taban {mt['n_base']}; FWER eşiği |AUC−0,5| > {mt['thr_all']:.3f} (taker'lı aile, {mt['n_features']} özellik) / "
                                              f"{mt['thr_base']:.3f} (taker'sız aile, {mt['n_features'] - mt['n_taker']} özellik); eşiği geçen: "
                                              f"{sum(r['sig_all'] for r in recs)} / {sum(bool(r['sig_base']) for r in recs if not r['tk'])} (taker'sız).")
    # özet: her hücre
    rows = []
    for sk in SET_ORDER:
        for t in ("t0", "t15"):
            for base in ("matched", "pooled"):
                key = f"{sk}|{t}|{base}"; recs = A["rank"][key]; mt = A["meta"][key]
                tks = [r for r in recs if r["tk"]]
                best = tks[0]
                top10 = sum(r["tk"] for r in recs[:10])
                top1 = recs[0]; top1b = next(r for r in recs if not r["tk"])
                rows.append([sk, t, base, str(mt["n_events"]), f"{top1['feature']} ({top1['auc']:.2f})", str(top10),
                             f"{best['feature']} #{best['rank_all']} ({best['auc']:.2f})", f"{sum(r['sig_all'] for r in tks)}/{len(tks)}",
                             f"{top1b['feature']} ({top1b['auc']:.2f})"])
    T["rank_summary"] = table(["bölme", "an", "taban", "olay", "1. özellik (taker'lı)", "ilk 10'da taker", "en iyi taker (sıra, AUC)", "anlamlı taker",
                               "1. özellik (taker'sız)"], rows)
    # taker özellikleri × bölme (AUC, eşleşmiş t0)
    names = [r["feature"] for r in A["rank"]["B|t0|matched"] if r["tk"]]
    names.sort(key=lambda n: (n.split(".", 1)[0] != "5m", n.split(".", 1)[0] != "3m", n))
    for t, base in (("t0", "matched"), ("t0", "pooled"), ("t15", "matched"), ("t15", "pooled")):
        rows = []
        for nm in names:
            cells = [nm]
            aucs = []
            for sk in SET_ORDER:
                r = next(x for x in A["rank"][f"{sk}|{t}|{base}"] if x["feature"] == nm)
                aucs.append(r["auc"])
                cells.append(f"{r['auc']:.3f}" + (" ✓" if r["sig_all"] else "") + f" (#{r['rank_all']})")
            sign = "aynı yön" if (all(a > .5 for a in aucs) or all(a < .5 for a in aucs)) else "yön değişiyor"
            cells.append(sign)
            rows.append(cells)
        T[f"taker_auc_{t}_{base}"] = table(["taker özelliği"] + [f"{s} AUC (#sıra)" for s in SET_ORDER] + ["işaret tutarlılığı"], rows)
    return T


# ------------------------------------------------------------------------------------------------ desenler / arka test
def cond_text(p: dict) -> str:
    return " ∧ ".join(f"`{c['feature']} {c['op']} {c['value']:.4g}`" for c in p["conditions"])


def patterns_table(pats: list[dict]) -> str:
    rows = []
    for p in pats:
        tm, tp = p["train_matched"], p["train_pooled"]
        rows.append([p["set"], p["pool"], p["pid"], p["label"], cond_text(p), "evet" if p["uses_taker"] else "hayır", pc(tm["recall"]),
                     pc(tm["fpr"], 2), pc(tp["fpr"], 2)])
    return table(["bölme", "havuz", "desen", "tür", "koşullar (VE)", "taker koşulu var", "recall (eğitim)", "YA eşleşmiş", "YA havuz"], rows)


def bt_row(label, r):
    if r is None or not r.get("n"):
        return [label] + ["—"] * 13
    h15 = r["hit15"]; n15 = r["net15"]; n2 = r["net2"]; tr = r["trail"]
    lift = r.get("lift15")
    se = r.get("lift15_se")
    return [label, f"{r['n']} ({r['per_day']:.0f})", pc(h15.get("mean")), pc(r.get("null15")), "**" + pp(lift) + "**" + (f" ±{100 * 1.96 * se:.1f}" if se else ""),
            nr(n15.get("mean")) + (f" (t {n15['t']:+.0f})" if n15.get("t") is not None else ""), nr(n2.get("mean")),
            nr(tr.get("mean")) + (f" (t {tr['t']:+.1f})" if tr.get("t") is not None else ""),
            pc(r["hit4"].get("mean")) + " / " + pc(r.get("null4")), pp(r.get("lift4")),
            nr(r.get("liftnet")) + (f" ±{1.96 * r['se_net']:.2f}" if r.get("se_net") else ""),
            nr(r.get("lifttr")) + (f" ±{1.96 * r['se_tr']:.2f}" if r.get("se_tr") else ""),
            pc(r.get("events_caught")) + " / " + pc(r.get("events_caught_null")),
            (nr(r.get("ha_lead_med"), "{:.0f}") + " dk") if r.get("ha_lead_med") is not None else "—"]


BT_HEAD = ["ölçüt", "sinyal (/gün)", "hit60@1,5", "şans (null3)", "**hit−şans** (±%95)", "net60@1,5 (t)", "net60@2,0", "trailing net (t)",
           "≥+%4/60dk pay / şans", "+%4 şans farkı", "net60 şans farkı", "trailing şans farkı", "olay yakalama / şans", "HA'nın gelişi (med., sinyalden sonra)"]


def bt_tables(B: dict, pats: list[dict]) -> dict[str, str]:
    T = {}
    for sk in SET_ORDER:
        for per, lab in (("test", "OOS (test)"), ("train", "eğitim (in-sample)")):
            rows = [bt_row(f"**Hız Avcısı** ({lab})", B["ha"][f"{sk}_{per}"])]
            for p in pats:
                if p["set"] != sk:
                    continue
                rows.append(bt_row(f"{p['pool']}/{p['pid']}" + (" ⚑" if p["uses_taker"] else ""), B["patterns"][p["key"]][per]))
            T[f"bt_{sk}_{per}"] = table(BT_HEAD, rows)
    return T


def verdict_tables(B: dict, pats: list[dict]) -> dict[str, str]:
    """Her desen için OOS şans farkı − aynı test döneminde Hız Avcısı şans farkı; net / trailing işareti."""
    T = {}
    rows = []
    stat = {}
    for p in pats:
        sk = p["set"]
        r = B["patterns"][p["key"]]["test"]; rt = B["patterns"][p["key"]]["train"]; h = B["ha"][f"{sk}_test"]
        if not r.get("n") or r.get("lift15") is None:
            continue
        d = r["lift15"] - (h.get("lift15") or 0.0)
        stat[p["key"]] = {"lift": r["lift15"], "ha": h.get("lift15"), "diff": d, "net": r["net15"].get("mean"), "trail": r["trail"].get("mean"), "lifttr": r.get("lifttr"), "se_tr": r.get("se_tr"),
                          "n": r["n"], "per_day": r["per_day"], "taker": p["uses_taker"], "set": sk, "pool": p["pool"], "pid": p["pid"],
                          "train_lift": rt.get("lift15")}
        rows.append([sk, p["pool"], p["pid"], "⚑" if p["uses_taker"] else "", f"{r['per_day']:.0f}", pp(rt.get("lift15")), pp(r["lift15"]),
                     pp(h.get("lift15")), pp(d), nr(r["net15"].get("mean")), nr(r["trail"].get("mean")),
                     nr(r.get("lifttr")) + (f" ±{1.96 * r['se_tr']:.2f}" if r.get("se_tr") else ""),
                     "evet" if d > 0 else "hayır", "evet" if (r["trail"].get("mean") or -9) > 0 else "hayır"])
    T["verdict_rows"] = table(["bölme", "havuz", "desen", "taker", "sinyal/gün", "eğitim lift", "OOS lift", "HA OOS lift", "OOS − HA", "net60@1,5", "trailing", "trailing şans farkı",
                               "HA'yı geçti", "trailing>0"], rows)
    # desen kimliği × havuz: tüm bölmelerde HA'yı geçen sayısı
    rows = []
    for pid in ["A", "B", "C", "D", "E", "F", "G", "H", "I"]:
        for pool in ("base", "all"):
            ks = [s for s in stat.values() if s["pid"] == pid and s["pool"] == pool]
            if not ks:
                continue
            beat = [s["set"] for s in ks if s["diff"] > 0]
            trp = [s["set"] for s in ks if (s["trail"] or -9) > 0]
            rows.append([pid, pool, str(len(ks)), f"{len(beat)} ({', '.join(beat) if beat else '—'})", pp(float(np.mean([s["train_lift"] for s in ks if s["train_lift"] is not None]))),
                         pp(float(np.mean([s["lift"] for s in ks]))), pp(float(np.mean([s["diff"] for s in ks]))),
                         nr(float(np.mean([s["net"] for s in ks]))), nr(float(np.mean([s["trail"] for s in ks if s["trail"] is not None]))),
                         f"{len(trp)} ({', '.join(trp) if trp else '—'})"])
    T["verdict_by_pattern"] = table(["desen", "havuz", "bölme sayısı", "HA'yı geçen bölmeler", "ort. eğitim lift", "ort. OOS lift", "ort. (OOS−HA)",
                                     "ort. net60@1,5", "ort. trailing", "trailing>0 bölmeler"], rows)
    # taker katkısı: aynı bölme + aynı desen kimliğinde taker'lı havuz ile taker'sız havuz farklı koşul çıkardıysa
    rows = []
    for p in pats:
        if p["pool"] != "all":
            continue
        q = next((x for x in pats if x["key"] == f"{p['set']}|base|{p['pid']}"), None)
        if q is None:
            continue
        same = [(c["feature"], c["op"], round(c["value"], 6)) for c in p["conditions"]] == [(c["feature"], c["op"], round(c["value"], 6)) for c in q["conditions"]]
        if same:
            continue
        a, b = stat.get(p["key"]), stat.get(q["key"])
        if a is None or b is None:
            continue
        rows.append([p["set"], p["pid"], "evet" if p["uses_taker"] else "hayır", pp(b["lift"]), pp(a["lift"]), pp(a["lift"] - b["lift"]),
                     nr(b["trail"]), nr(a["trail"]), nr(b["net"]), nr(a["net"])])
    T["taker_delta"] = table(["bölme", "desen", "taker koşulu var", "OOS lift (taker'sız)", "OOS lift (taker'lı)", "fark", "trailing (taker'sız)", "trailing (taker'lı)",
                              "net60 (taker'sız)", "net60 (taker'lı)"], rows)
    json.dump(stat, open(Path("work/pattern90/verdict_stat.json"), "w"), ensure_ascii=False)
    return T


def stability_table(B: dict, pats: list[dict]) -> str:
    rows = []
    for p in pats:
        res = B["patterns"][p["key"]]
        cells = [p["set"], p["pool"], p["pid"] + (" ⚑" if p["uses_taker"] else "")]
        for bk in ("blk1", "blk2", "blk3"):
            r = res[bk]
            cells.append("—" if not r.get("n") or r.get("lift15") is None else f"{pp(r['lift15'])} / {nr(r['net15'].get('mean'))} / {nr(r['trail'].get('mean'))}")
        rows.append(cells)
    ha = B["ha"]
    rows.insert(0, ["", "", "**Hız Avcısı**"] + [f"{pp(ha[b].get('lift15'))} / {nr(ha[b]['net15'].get('mean'))} / {nr(ha[b]['trail'].get('mean'))}" for b in ("blk1", "blk2", "blk3")])
    return table(["bölme", "havuz", "desen", "blok1 19Tem–17Ağu (lift / net1,5 / trailing)", "blok2 18Ağu–16Eyl", "blok3 17Eyl–17Eki"], rows)


def lunatry_table(B: dict, pats: list[dict]) -> str:
    rows = []
    for p in pats:
        l = B["lunatry"].get(p["key"], [])
        rows.append([p["set"], p["pool"], p["pid"] + (" ⚑" if p["uses_taker"] else ""), ", ".join(l[:6]) + ("…" if len(l) > 6 else "") if l else "ateşlemedi"])
    return table(["bölme", "havuz", "desen", "LUNATRY 17 Eki 00:00–04:00 ateşleme"], rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", required=True)
    ap.add_argument("--out-dir", default="work/pattern90")
    args = ap.parse_args(argv)
    out = Path(args.out_dir); tdir = out / "tables"; tdir.mkdir(parents=True, exist_ok=True)
    E = pickle.load(open(Path(args.cache_dir) / "events.pkl", "rb"))
    T: dict[str, str] = {}
    T.update(events_tables(E))
    if (out / "analysis.json").exists():
        A = json.loads((out / "analysis.json").read_text(encoding="utf-8"))
        T.update(stack_tables(A)); T.update(rank_tables(A))
        rb = A.get("robust_decluster", {})
        rows = []
        for sk, d in rb.items():
            for var, v in d.items():
                rows.append([sk, {"keep": "birincil", "keep_b": "her kovada tek", "keep_c": "±15 dk pencere", "none": "kümesizleştirme yok"}[var], str(v["n_events"]),
                             f"{v['spearman_vs_primary']:.3f}", str(v["top15_overlap"])])
        T["robust_decluster"] = table(["bölme", "olay kümesi", "olay", "AUC sıra korelasyonu (Spearman, birincile karşı)", "ilk 15 ortak"], rows)
    if (out / "patterns.json").exists():
        pats = json.loads((out / "patterns.json").read_text(encoding="utf-8"))
        T["patterns"] = patterns_table(pats)
        if (out / "backtest.json").exists():
            B = json.loads((out / "backtest.json").read_text(encoding="utf-8"))
            T.update(bt_tables(B, pats)); T.update(verdict_tables(B, pats))
            T["stability"] = stability_table(B, pats); T["lunatry"] = lunatry_table(B, pats)
    for k, v in T.items():
        (tdir / f"{k}.md").write_text(dec(v), encoding="utf-8")
    print(f"[report] {len(T)} tablo -> {tdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
