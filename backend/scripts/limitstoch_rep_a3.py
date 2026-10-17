"""Rapor bölümü: Çalışma A-3 (ön sinyal / onaylı sinyal giriş sinyali olarak)."""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import limitstoch_lib as L  # noqa: E402

f2 = L.f2


def pct(x, nd=1):
    return "—" if x is None or not np.isfinite(x) else ("%." + str(nd) + "f") % (100 * x)


KIND_NAMES = {0: "sinyal", 1: "rastgele (saat, ≥2sa)", 2: "rastgele (oynaklık, ≥2sa)", 3: "rastgele (saat, dışlamasız)", 4: "rastgele (oynaklık, dışlamasız)"}


class A3:
    def __init__(self, path):
        d = pickle.load(open(path, "rb"))
        self.agg = d["agg"]; self.specs = d["specs"]; self.sets = d["sets"]; self.D0 = d["D0"]; self.ND = d["ND"]; self.miss = d["miss"]

    def sl(self, win):
        a = int(L.day_idx(L.WINDOWS[win][0])) - self.D0
        b = int(L.day_idx(L.WINDOWS[win][1])) - self.D0 + 1
        return slice(a, b)

    def stats(self, sid, kind, j, scn, win):
        a = self.agg.get((sid, kind))
        if a is None:
            return None
        s = self.sl(win)
        n = a["n"][s]
        N = n.sum()
        if N <= 0:
            return None
        S = a["s" + scn][s, j]; C = a["c" + scn][s, j]; P = a["p" + scn][s, j]
        m = S.sum() / N
        se = float(np.sqrt(((S - n * m) ** 2).sum()) / N)
        npos = C.sum()
        return {"n": N, "mean": m, "se": se, "win": npos / N, "avg_win": P.sum() / npos if npos else float("nan"),
                "avg_loss": (S.sum() - P.sum()) / (N - npos) if N > npos else float("nan")}

    def means(self, sid, kind, scn, win):
        a = self.agg.get((sid, kind))
        if a is None:
            return np.full(len(self.specs), np.nan)
        s = self.sl(win)
        N = a["n"][s].sum()
        return a["s" + scn][s].sum(0) / N if N > 0 else np.full(len(self.specs), np.nan)

    def hit(self, sid, kind, win, key="hit15"):
        a = self.agg.get((sid, kind))
        if a is None:
            return float("nan"), 0
        s = self.sl(win)
        N = a["n"][s].sum()
        return (a[key][s].sum() / N if N > 0 else float("nan")), N

    def ret60(self, sid, kind, win):
        a = self.agg.get((sid, kind))
        if a is None:
            return float("nan")
        s = self.sl(win)
        N = a["n"][s].sum()
        return a["ret60"][s].sum() / N if N > 0 else float("nan")

    def nsig(self, sid, win):
        a = self.agg.get((sid, 0))
        return 0 if a is None else a["n"][self.sl(win)].sum()

    def best(self, sid, scn, win, min_n=100):
        if self.nsig(sid, win) < min_n:
            return None
        m = self.means(sid, 0, scn, win)
        return int(np.nanargmax(m)) if np.isfinite(m).any() else None


def ci(st):
    return "—" if st is None else "%s [%s; %s]" % (f2(st["mean"]), f2(st["mean"] - 1.96 * st["se"]), f2(st["mean"] + 1.96 * st["se"]))


def dci(a, b):
    if a is None or b is None:
        return None, "—"
    d = a["mean"] - b["mean"]
    se = float(np.hypot(a["se"], b["se"]))
    return (d, d - 1.96 * se, d + 1.96 * se), "%s [%s; %s]" % (f2(d), f2(d - 1.96 * se), f2(d + 1.96 * se))


def sect_a3(A: A3) -> tuple[list[str], dict]:
    out = []
    P = out.append
    summ = {}
    P("## 4. Çalışma A-3 — Ön sinyal / onaylı sinyal GİRİŞ sinyali olarak (gerçekçi doluş)\n")
    P("Sinyal: ön sinyal = bar kapanışında (çekirdek kırmızı + K/D yukarı kesişimi, K[i-1] < seviye). **Onaylı** = ön sinyalden sonraki 6 bar içinde çekirdek AL dönüşü; sinyal DÖNÜŞ barının kapanışında. "
      "Aynı sembolde 60 dk tekilleştirme; likit sembol (24 sa ≥ 5M TRY). Giriş: sinyal + 60 sn sonraki ilk 1 dk açılışı × (1 + %0,15) (birincil); bacak başına %0,1125 ücret (maker = taker, bkz. Yöntem). "
      "Çıkış kümesi 24 hücre: sabit TP {1,0; 1,5} × SL {1,5; 3} × zaman {60; 120}; izleyen tetik {0,5; 1,0} × iz {0,4; 0,8} × SL {1,5; 3} × zaman {60; 120}. "
      "Rastgele tabanlar: (1) istenen: aynı sembol + saat dilimi + blok, herhangi bir HAM sinyalden ≥ 2 sa uzak; (2) oynaklık eşleşmeli (son 30 dk aralığı ±%25), ≥ 2 sa; (3) aynı sembol/saat, **dışlamasız**; (4) oynaklık eşleşmeli + dışlamasız. "
      "Tüm net değerler %/işlem (ücret + kayma dâhil); [aralık] = gün-kümeli %95.\n")
    P("**Taban notu:** (1) ve (2)'nin 'herhangi bir sinyalden ≥ 2 sa uzak' koşulu tabanı yukarı yanlılaştırabilir — ön sinyaller düşüşlerin sonunda çaldığı için sinyalsiz saatler çoğunlukla sakin yükseliş / pompa dönemleridir, "
      "bu yüzden rastgele (1) bazı kümelerde sinyalden DAHA iyi çıkar. Adil kıyas için dışlamasız (3)/(4) de verilir; karar her ikisine göre okunmalı.\n")
    sets = A.sets
    P("### 4.1 Sinyal sıklığı ve hit60@1,5 (60 dk içinde en yüksek ≥ giriş açılışı +%1,5) — W30\n")
    P("| küme | sinyal (n) | /gün | hit60@1,5 sinyal | taban 1 | taban 2 | taban 3 | taban 4 | şans yükselişi (sinyal/taban 4) | pp farkı (sinyal−taban 4) | brüt 60 dk getiri: sinyal / taban 4 |")
    P("|---|---|---|---|---|---|---|---|---|---|---|")
    for sid, name in enumerate(sets):
        hs, n = A.hit(sid, 0, "W30")
        if n <= 0:
            continue
        hb = [A.hit(sid, k, "W30")[0] for k in (1, 2, 3, 4)]
        P("| %s | %d | %.0f | %s%% | %s%% | %s%% | %s%% | %s%% | %.2f× | %+.1f | %+.3f%% / %+.3f%% |" % (
            name, n, n / 30.0, pct(hs), pct(hb[0]), pct(hb[1]), pct(hb[2]), pct(hb[3]), hs / hb[3] if hb[3] > 0 else float("nan"), 100 * (hs - hb[3]),
            A.ret60(sid, 0, "W30"), A.ret60(sid, 4, "W30")))
    P("")
    for scn, sname in (("P", "60 sn gecikme / %0,15 kayma (BİRİNCİL)"), ("O", "0 sn / %0,05 kayma (iyimser)")):
        P("### 4.2%s Net sonuç — W30, senaryo %s\n" % ("a" if scn == "P" else "b", sname))
        P("Çıkış hücresi, sinyal kümesinin W30 ortalama neti en yüksek olandır (**iç-örneklem, iyimser**); yanında aynı hücrenin tabanlardaki neti ve fark.\n")
        P("| küme | 24 çıkışın ort. neti | net>0 çıkış sayısı | en iyi çıkış (iç-örneklem) | net sinyal [%95] | kazanma % | taban 1 (aynı çıkış) | taban 4 (aynı çıkış) | fark vs taban 1 | fark vs taban 4 |")
        P("|---|---|---|---|---|---|---|---|---|---|")
        for sid, name in enumerate(sets):
            j = A.best(sid, scn, "W30")
            if j is None:
                continue
            ms = A.means(sid, 0, scn, "W30")
            st = A.stats(sid, 0, j, scn, "W30")
            b1 = A.stats(sid, 1, j, scn, "W30"); b4 = A.stats(sid, 4, j, scn, "W30")
            _, t1 = dci(st, b1); _, t4 = dci(st, b4)
            P("| %s | %s | %d/24 | %s | %s | %s | %s | %s | %s | %s |" % (name, f2(np.nanmean(ms)), int((ms > 0).sum()), A.specs[j], ci(st), pct(st["win"]),
                                                                      f2(b1["mean"]) if b1 else "—", f2(b4["mean"]) if b4 else "—", t1, t4))
            summ[(name, scn)] = (j, st, b1, b4)
        P("")
    P("### 4.3 Üç 30 günlük blok (sağlamlık) — senaryo P; her blokta kümenin EN İYİ çıkışı (iç-blok, iyimser)\n")
    P("| küme | B1 (20 Tem–18 Ağu) | B2 (19 Ağu–17 Eyl) | B3 (18 Eyl–16 Eki) | sinyal/gün B1 / B2 / B3 |")
    P("|---|---|---|---|---|")
    for sid, name in enumerate(sets):
        cells = []; cnts = []
        for w in L.BLOCKS:
            ms = A.means(sid, 0, "P", w)
            n = A.nsig(sid, w)
            cnts.append("%.0f" % (n / 30.0))
            if not np.isfinite(ms).any():
                cells.append("—")
                continue
            j = int(np.nanargmax(ms))
            b4 = A.means(sid, 4, "P", w)[j]
            cells.append("%s (%s; taban 4 %s; >0: %d/24)" % (f2(ms[j]), A.specs[j], f2(b4), int((ms > 0).sum())))
        P("| %s | %s | %s |" % (name, " | ".join(cells), " / ".join(cnts)))
    P("")
    P("### 4.4 Yürüyen-ileri (bir blokta çıkış seç → diğer bloklarda DOKUNMADAN ölç), senaryo P\n")
    P("Seçim: eğitim bloğunda sinyal ortalama neti en yüksek çıkış (n ≥ 100). Sütunlar: OOS net sinyal [%95]; taban 1 / taban 4 aynı çıkış; fark (sinyal − taban 4) [%95].\n")
    P("| küme | eğitim → test | seçilen çıkış | OOS net sinyal [%95] | taban 1 | taban 4 | sinyal−taban 4 [%95] |")
    P("|---|---|---|---|---|---|---|")
    wf = {}
    for sid, name in enumerate(sets):
        rows = []
        for tr in L.BLOCKS:
            j = A.best(sid, "P", tr)
            if j is None:
                continue
            for te in L.BLOCKS:
                if te == tr:
                    continue
                st = A.stats(sid, 0, j, "P", te); b1 = A.stats(sid, 1, j, "P", te); b4 = A.stats(sid, 4, j, "P", te)
                if st is None:
                    continue
                dd, dt = dci(st, b4)
                rows.append((tr, te, j, st, b1, b4, dd, dt))
        wf[name] = rows
        if name.startswith("5m"):
            for tr, te, j, st, b1, b4, dd, dt in rows:
                P("| %s | %s → %s | %s | %s | %s | %s | %s |" % (name, tr, te, A.specs[j], ci(st), f2(b1["mean"]) if b1 else "—", f2(b4["mean"]) if b4 else "—", dt))
    P("")
    P("**Yürüyen-ileri özeti (12 küme × 6 eğitim→test çifti):**\n")
    P("| küme | OOS net>0 satır | OOS net %95 alt sınırı >0 | OOS ort. net | sinyal−taban 4 alt sınırı >0 | sinyal−taban 4 ort. |")
    P("|---|---|---|---|---|---|")
    tot = [0, 0, 0, 0]
    for name, rows in wf.items():
        if not rows:
            continue
        pos = sum(1 for r in rows if r[3]["mean"] > 0)
        lo = sum(1 for r in rows if r[3]["mean"] - 1.96 * r[3]["se"] > 0)
        dpos = sum(1 for r in rows if r[6] is not None and r[6][1] > 0)
        mo = np.mean([r[3]["mean"] for r in rows]); md = np.mean([r[6][0] for r in rows if r[6] is not None])
        tot[0] += pos; tot[1] += lo; tot[2] += dpos; tot[3] += len(rows)
        P("| %s | %d/%d | %d | %s | %d | %s |" % (name, pos, len(rows), lo, f2(mo), dpos, f2(md)))
    P("| **toplam** | %d/%d | %d | | %d | |\n" % (tot[0], tot[3], tot[1], tot[2]))
    summ["wf_total"] = tot
    return out, summ
