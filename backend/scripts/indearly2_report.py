"""Erken uyarı v2 — ham sonuç dosyalarından (rank2.pkl, multi2.pkl, eval.pkl, filter2.pkl) Markdown ayrıntı tabloları üretir (work/indearly2/details.md).

Rapor metni (karar/yöntem) elle yazılır; bu betik yalnız sayıları tabloya döker. Kullanım (backend/): python scripts/indearly2_report.py\n"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
from scripts.indearly2_study import SIGNALS  # noqa: E402

OUTD = _ROOT / "work" / "indearly2"
OFFL = {0: "t0", 1: "t0−5", 2: "t0−10", 3: "t0−15"}
BLK = ["blk1", "blk2", "blk3"]
BLKL = {"blk1": "B1", "blk2": "B2", "blk3": "B3"}
FAML = {"x2_basic": "temel", "x2_day": "gün/seans", "x2_pivot": "pivot (Fib/trend/dip)", "x2_smc": "SMC", "x2_pattern": "formasyon", "x2_comm": "topluluk", "x2_adv": "ileri"}


def md(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out) + "\n"


def f3(x, nd=3):
    return "–" if x is None or not np.isfinite(x) else ("%." + str(nd) + "f") % x


def fs(x, nd=2):
    return "–" if x is None or not np.isfinite(x) else ("%+." + str(nd) + "f") % x


def fp(x, nd=1):
    return "–" if x is None or not np.isfinite(x) else ("%." + str(nd) + "f%%") % (100 * x)


def short_name(nm: str) -> str:
    return nm.replace(".x2.", ".")


# ------------------------------------------------------------------------------------------------ A. sıralama
def section_rank() -> str:
    R = pickle.load(open(OUTD / "rank2.pkl", "rb"))
    try:
        old = pickle.load(open(OUTD / "rank2_old.pkl", "rb"))
    except Exception:
        old = None
    out = []
    for off in sorted(R["rank"], reverse=True):
        recs = R["rank"][off]
        m = R["meta"][off]
        out.append("#### %s — olay %d, taban %d, permütasyon %d\n" % (OFFL[off], m["n_events"], m["n_base"], m["n_perm"]))
        out.append("Ham (kontrolsüz) eşleşmiş AUC: FWER<0,05 **%d**, BH q<0,10 **%d** özellik (FWER eşiği |AUC−½|>%.3f). **Kısmi korelasyon** (olay göstergesi ile özellik arasında, aynı eşleşme kümesi içinde, "
                   "düşüş+oynaklık kontrolleri doğrusal sabitlenerek): FWER<0,05 **%d**, BH q<0,05 **%d**, q<0,10 **%d** özellik (FWER eşiği |r|>%.4f). Kısmi r, seyrek 0/1 bayraklarda da yanlı değildir; "
                   "AUC'nin artığı yalnız sürekli özelliklerde (%d) anlamlıdır.\n" % (m["n_sig_fwer"], m["n_sig_q10"], m["fwer_thr"], m["n_sig_fwer_pr"], m["n_sig_q05_pr"], m["n_sig_q10_pr"], m["fwer_thr_pr"], m["n_cont"]))
        rows = []
        for r in sorted(recs, key=lambda r: -abs(r["pr"]))[:25]:
            rows.append([short_name(r["feature"]), FAML.get(r["family"], r["family"]), f3(r["auc"]), ("%+.4f" % r["pr"]), "%.3f" % r["q_pr"], " / ".join("%+.3f" % x for x in r["blk_pr"]),
                         "%d/3" % r["consist_pr"], f3(r["auc_resid"]) if r["cont"] else "– (seyrek/ayrık)", fp(r["nan_share"], 0)])
        out.append("Kısmi |r| ile en güçlü 25 yeni özellik (AUC ½ = bilgi yok; kısmi r > 0: olayda yüksek):\n\n"
                   + md(["özellik", "aile", "AUC ham", "kısmi r", "q", "blok r B1 / B2 / B3", "işaret tutarlılığı", "AUC artık (kontrol sonrası)", "NaN payı"], rows))
        sig = [r for r in recs if r["q_pr"] < 0.05 and r["consist_pr"] == 3]
        out.append("q<0,05 **ve** üç blokta aynı işaret: **%d** özellik; bunlardan |r| > FWER eşiği olan: %d.\n" % (len(sig), sum(1 for r in sig if abs(r["pr"]) > m["fwer_thr_pr"])))
        fam = {}
        for r in recs:
            fam.setdefault(r["family"], []).append(r)
        rows = []
        for f, rs in sorted(fam.items(), key=lambda kv: -len(kv[1])):
            best = max(rs, key=lambda r: abs(r["pr"]))
            rows.append([FAML.get(f, f), len(rs), sum(1 for r in rs if r["q_pr"] < 0.05), sum(1 for r in rs if r["q_pr"] < 0.05 and r["consist_pr"] == 3),
                         "%s (r %+.3f)" % (short_name(best["feature"]), best["pr"])])
        out.append("Aile bazında:\n\n" + md(["aile", "özellik", "q<0,05", "…ve 3/3 blok", "en güçlü"], rows))
        if old and off in old["rank"]:
            ro = old["rank"][off]
            top = sorted(ro, key=lambda r: -abs(r["pr"]))[:6]
            nq = sum(1 for r in ro if r["q_pr"] < 0.05)
            out.append("Karşılaştırma — ESKİ kütüphane (aynı yöntem, %d özellik): q<0,05 **%d**; en güçlü |r|: %s. Yeni kütüphanenin en güçlü |r|: %s.\n" % (
                len(ro), nq, "; ".join("%s %+.3f" % (short_name(r["feature"]), r["pr"]) for r in top),
                "; ".join("%s %+.3f" % (short_name(r["feature"]), r["pr"]) for r in sorted(recs, key=lambda r: -abs(r["pr"]))[:6])))
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------ B. çok değişkenli
def section_multi() -> str:
    M = pickle.load(open(OUTD / "multi2.pkl", "rb"))
    out = []
    for off in sorted(M, reverse=False):
        res = M[off]
        base = res["mevcut 154"]
        rows = []
        for nm, r in res.items():
            a = [x["auc"] for x in r]
            g = [x["auc_group"] for x in r]
            d = [a[i] - base[i]["auc"] for i in range(3)]
            rows.append([nm, " / ".join(f3(x) for x in a), f3(float(np.mean(a))), " / ".join(f3(x) for x in g), "%s (%s)" % (fs(float(np.mean(d)), 3), " / ".join(fs(x, 3) for x in d))])
        out.append("#### %s\n\n" % OFFL[off] + md(["özellik kümesi", "AUC blok-dışı B1 / B2 / B3", "ort.", "grup-içi AUC", "Δ vs mevcut154 ort. (blok bazlı)"], rows))
    try:
        A = pickle.load(open(OUTD / "multi_abl.pkl", "rb"))
        for off in sorted(A):
            base = A[off]["mevcut 154"]
            rows = [[nm, " / ".join(f3(x) for x in r), f3(float(np.mean(r))), fs(float(np.mean(r)) - float(np.mean(base)), 3)] for nm, r in A[off].items()]
            out.append("#### %s — kesit (kazanç saat/seans özelliklerinden mi?)\n\n" % OFFL[off] + md(["özellik kümesi", "AUC B1 / B2 / B3", "ort.", "Δ vs mevcut154"], rows))
    except FileNotFoundError:
        pass
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------ C. sinyaller
def _sim(r, key):
    s = r.get(key) or {}
    return s.get("mean") if s.get("n") else None


def section_signals() -> str:
    E = pickle.load(open(OUTD / "eval.pkl", "rb"))
    P = E["periods"]
    out = []
    keys = ["G:" + k for k in SIGNALS] + ["HA"]
    rows = []
    for k in keys:
        short = k[2:] if k.startswith("G:") else "HA"
        for b in BLK:
            r = P[k].get(b, {})
            if not r.get("n"):
                rows.append([short, BLKL[b], 0] + ["–"] * 12)
                continue
            base = E["base"][b]
            rows.append([short, BLKL[b], r["n"], "%.1f" % r["per_day"], fp(r["prec_ahead60"]), fp(base["prec_ahead60"]), fp(r.get("hit15")), fp(r.get("null15")),
                         ("%s ± %s" % (fs(100 * r["lift15"], 1), f3(100 * r.get("lift15_se", float("nan")), 1))) if "lift15" in r else "–",
                         fs(_sim(r, "sim0")), fs(_sim(r, "simr0")), fs(_sim(E["base"][b], "sim0")), fs(_sim(r, "sim2")), fs(_sim(r, "simr2")), fs(_sim(base, "sim2"))])
    hdr = ["sinyal", "blok", "n", "sinyal/gün", "60 dk önden kesinlik", "taban", "hit60@1,5", "şans (null3)", "lift pp ± SE", "net TP1,5", "rastgele (≥2 sa uzak)", "koşulsuz", "net izleyen", "rastg.", "koşulsuz"]
    out.append("Net = exit_sim (60 sn gecikme, %0,15 kayma, %0,1125/bacak) ortalaması, % cinsinden. 'rastgele' = aynı sembollerde sinyal sayısı kadar, sinyalden ≥2 sa uzak rastgele giriş; "
               "'koşulsuz' = tüm geçerli anlardan tekdüze örnek.\n\n" + md(hdr, rows))
    rows = []
    for k in keys:
        short = k[2:] if k.startswith("G:") else "HA"
        for b in BLK:
            r = P[k].get(b, {})
            if not r.get("n") or "rec_early" not in r:
                rows.append([short, BLKL[b]] + ["–"] * 8)
                continue
            rows.append([short, BLKL[b], r.get("events_n"), fp(r["rec_early"]), fp(r.get("rec_early_rnd")), fp(r["rec_any"]), fp(r.get("ha_rec_early")),
                         ("%.0f" % r["lead_med_min"]) if r.get("lead_med_min") is not None else "–", r.get("both_n"), fp(r.get("earlier_than_ha")),
                         ("%+.0f" % r["adv_vs_ha_med"]) if r.get("adv_vs_ha_med") is not None else "–"])
    out.append("\nOlay yakalama ve Hız Avcısı'na (HA) göre öncelik:\n\n" + md(
        ["sinyal", "blok", "olay", "t0 öncesi yakalama", "sayı-eşleşmiş sıfır", "t0 sonrası dâhil", "HA t0 öncesi", "ort. öncelik (dk, medyan)", "ortak olay", "HA'dan önce gelme payı", "medyan fark dk"], rows))
    # özet
    rows = []
    for k in keys:
        short = k[2:] if k.startswith("G:") else "HA"
        pos = 0
        pos_tr = 0
        lifts = []
        for b in BLK:
            r = P[k].get(b, {})
            s0, s2 = _sim(r, "sim0"), _sim(r, "sim2")
            pos += int(s0 is not None and s0 > 0)
            pos_tr += int(s2 is not None and s2 > 0)
            if "lift15" in r:
                lifts.append(100 * r["lift15"])
        nets = [_sim(P[k].get(b, {}), "sim0") for b in BLK]
        npass = 0
        for b in BLK:
            r = P[k].get(b, {})
            if r.get("rec_early") is not None and r.get("rec_early_rnd") and r.get("earlier_than_ha") is not None:
                npass += int(r["rec_early"] > 1.5 * r["rec_early_rnd"] and r["earlier_than_ha"] > 0.5)
        rows.append([short, SIGNALS.get(short, ("", "Hız Avcısı"))[1], "%d/3" % pos, "%d/3" % pos_tr, " / ".join(fs(x) for x in nets),
                     " / ".join(fs(x, 1) for x in lifts) if lifts else "–", "%d/3" % npass])
    out.append("\nÖzet:\n\n" + md(["sinyal", "tanım", "net>0 (TP1,5) blok", "net>0 (izleyen) blok", "net TP1,5 B1 / B2 / B3", "hit lift pp B1 / B2 / B3", "erken-uyarı ölçütü (t0 öncesi yakalama > sıfır x1,5 VE HA'dan önce > %50)"], rows))
    lun = E.get("lunatry", {})
    rows = [[k[2:], ", ".join(v[:8]) if v else "–"] for k, v in lun.items() if k.startswith("G:")]
    out.append("\nLUNATRY 17.10 01:00–05:00 (TR) 5m sinyal anları (cooldown öncesi ilk 8):\n\n" + md(["sinyal", "tetik saatleri"], rows))
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------ D. HA süzgeci
def section_filter() -> str:
    F = pickle.load(open(OUTD / "filter2.pkl", "rb"))
    out = []
    rows = F["rank"]
    nb = 3
    out.append("HA olayı %d, geçerli %d, yeni özellik %d.\n" % (F["n_events"], F["n_valid"], len(rows)))
    cnt = []
    for key, lab in (("raw_net", "net (ham)"), ("par_net", "net (ATR-kontrollü)"), ("par_exn", "net−taban (ATR-kontrollü)"), ("par_hit", "hit (ATR-kontrollü)"), ("par_exh", "hit−taban (ATR-kontrollü)")):
        cnt.append([lab, len(rows), sum(1 for r in rows if np.isfinite(r["q_" + key]) and r["q_" + key] < 0.05), sum(1 for r in rows if np.isfinite(r["q_" + key]) and r["q_" + key] < 0.01)])
    out.append(md(["sonuç", "özellik", "q<0,05", "q<0,01"], cnt))
    srt = sorted(rows, key=lambda r: -abs(r["par_exn"]["t"]) if np.isfinite(r["par_exn"]["t"]) else 0)
    hdr = ["özellik", "aile", "kapsam", "ATR-kont. r(net−taban) [t]", "q", "ATR-kont. r(net) [t]", "ATR-kont. r(hit) [t]", "blok r(net−taban)", "işaret uyumu"]

    def row(r):
        return [short_name(r["name"]), FAML.get(r["family"], r["family"]), "%.0f%%" % (100 * r["cover"]), "%+.3f [%+.1f]" % (r["par_exn"]["r"], r["par_exn"]["t"]), "%.3f" % r["q_par_exn"],
                "%+.3f [%+.1f]" % (r["par_net"]["r"], r["par_net"]["t"]), "%+.3f [%+.1f]" % (r["par_hit"]["r"], r["par_hit"]["t"]),
                " / ".join("%+.3f" % v if np.isfinite(v) else "–" for v in r["blk_r"]), "%d/%d" % (r["agree"], nb)]
    out.append("\nEn güçlü 15 yeni özellik (ATR-kontrollü net−taban |t|):\n\n" + md(hdr, [row(r) for r in srt[:15]]))
    cons = [r for r in rows if np.isfinite(r["q_par_exn"]) and r["q_par_exn"] < 0.05 and r["agree"] == nb]
    out.append("q<0,05 ve 3/3 blokta aynı işaret: **%d** özellik; en güçlüleri: %s\n" % (len(cons), "; ".join("%s (r %+.3f)" % (short_name(r["name"]), r["par_exn"]["r"]) for r in sorted(cons, key=lambda r: -abs(r["par_exn"]["t"]))[:8])))
    # sinyal bayrakları
    rows2 = []
    for fr in F["flags"]:
        bl = fr["blocks"]
        rows2.append([short_name(fr["name"]), fp(fr["share"]), " / ".join(str(b.get("n", 0)) for b in bl), " / ".join(fs(b.get("d_ex")) if b.get("n") else "–" for b in bl),
                      " / ".join(fs(b.get("d_net")) if b.get("n") else "–" for b in bl)])
    out.append("\nÖnceden belirlenmiş sinyal bayrakları HA süzgeci olarak (tutulan = bayrak 1; Δ = tutulan − hepsi, aynı blok; %):\n\n"
               + md(["bayrak", "tutulan pay", "n B1 / B2 / B3", "Δ(net−taban) B1 / B2 / B3", "Δ(net) B1 / B2 / B3"], rows2))
    # kurallar
    rows3 = []
    for r in F["rules"]:
        bl = r["blocks"]
        rows3.append([r["id"], "`%s`" % short_name(r["text"]), "%.1f (n %d)" % (r["sel_t"], r["sel_n"]), " / ".join(str(b.get("n", 0)) for b in bl),
                      " / ".join(fs(b.get("net")) if b.get("n") else "–" for b in bl), " / ".join(fs(b.get("net_all")) if b.get("n") else "–" for b in bl),
                      " / ".join(fs(b.get("d_net")) if b.get("n") else "–" for b in bl), " / ".join(fs(b.get("d_ex")) if b.get("n") else "–" for b in bl)])
    out.append("\nKural arama — B1'de seçildi (hedef A: net−taban, N: ham net), B2/B3 DOKUNULMADAN:\n\n"
               + md(["kural", "koşul", "seçim t", "n B1 / B2 / B3", "net tutulan", "net hepsi", "Δ net", "Δ(net−taban)"], rows3))
    ne, nn = F["noise_ex"], F["noise_net"]
    out.append("\nAşırı uyum tanısı (B1'de en iyi 50 aday kuralın seçim-dışı ortalama Δ'sı):\n\n" + md(
        ["hedef", "aday", "OOS en iyi-50 ort. Δ", "pozitif pay", "tüm adaylar ort. Δ", "pozitif pay"],
        [["net−taban", ne["n_cand"], fs(ne["top_mean_oos"]), fp(ne["top_pos"]), fs(ne["all_mean_oos"]), fp(ne["all_pos"])],
         ["ham net", nn["n_cand"], fs(nn["top_mean_oos"]), fp(nn["top_pos"]), fs(nn["all_mean_oos"]), fp(nn["all_pos"])]]))
    tr = F["top_rules_all_blocks"]
    allpos = [x for x in tr if all(d > 0 for d in x["d_net"])]
    allpos_abs = [x for x in tr if all(n > 0 for n in x["net"])]
    out.append("\nB1'de en yüksek skorlu %d aday kuraldan (her blokta n≥30): **tüm üç blokta** HA net'ini (hepsine göre) artıran %d; üç blokta mutlak net>0 olan %d. "
               "(Bağımsız yazı-tura beklentisi ≈ %.0f%%.)\n" % (len(tr), len(allpos), len(allpos_abs), 12.5))
    if allpos:
        rr = []
        for x in sorted(allpos, key=lambda x: -min(x["d_net"]))[:10]:
            rr.append(["`%s`" % short_name(x["rule"]), " / ".join(str(n) for n in x["n"]), " / ".join(fs(v) for v in x["net"]), " / ".join(fs(v) for v in x["d_net"])])
        out.append(md(["kural", "n", "net B1 / B2 / B3", "Δ net B1 / B2 / B3"], rr))
    return "\n".join(out)


def main() -> int:
    parts = []
    for fn, title in ((section_rank, "A. Özellik sıralaması"), (section_multi, "B. Çok değişkenli artış"), (section_signals, "C. Önceden belirlenmiş sinyaller"), (section_filter, "D. HA süzgeci")):
        try:
            parts.append("### %s\n\n%s" % (title, fn()))
        except Exception as e:  # noqa: BLE001
            parts.append("### %s\n\n(henüz üretilmedi: %s)\n" % (title, e))
    (OUTD / "details.md").write_text("\n\n".join(parts), encoding="utf-8")
    print("details.md yazıldı")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
