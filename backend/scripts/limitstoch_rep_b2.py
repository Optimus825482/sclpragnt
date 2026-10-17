"""Rapor bölümü: Çalışma B tabloları (limit giriş + StochRSI desteği)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import limitstoch_lib as L  # noqa: E402
import limitstoch_b as B  # noqa: E402
from limitstoch_rep_b import KIND_NAMES, BRes, best_j, ci1, dci, dtxt, pct  # noqa: E402

f2 = L.f2
SRC_LABEL = {"HA": "HA canlı-benzeri (rescan)", "NOTIF_all": "Canlı bildirimler (hepsi)", "NOTIF_trend": "Canlı bildirimler (trend_devam)", "LIVE": "Canlı journal adayları (ileri)"}


def clus_mean(x: np.ndarray, days: np.ndarray):
    n = len(x)
    if n < 2:
        return float("nan"), float("nan")
    m = float(x.mean())
    ud, inv = np.unique(days, return_inverse=True)
    S = np.bincount(inv, weights=x - m)
    return m, float(np.sqrt((S ** 2).sum()) / n)


def plain_table(b: BRes, S: dict, win: str, title: str) -> list[str]:
    out = []
    P = out.append
    P("#### %s\n" % title)
    P("| d % | geçerli (dk) | dolum % sinyal | dolum % rastgele-1 / -4 | en iyi çıkış (iç-örneklem) | net/işlem % | net/sinyal % [%95] | rastgele-1 net/sinyal | rastgele-4 net/sinyal | sinyal−rastgele-1 [%95] | sinyal−rastgele-4 [%95] | net/sinyal>0 çıkış | medyan çıkış net/sinyal |")
    P("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for d in B.D_LIST:
        for v in B.V_LIST:
            cell = "L d%g V%d" % (d, v)
            st = S[cell][(win, 0)]
            if not st.get("n"):
                continue
            j = best_j(st)
            b1 = S[cell][(win, 1)]; b4 = S[cell][(win, 4)]
            if j is None:
                P("| %g | %d | %s | %s / %s | (işlem yok) | | | | | | | | |" % (d, v, pct(st["fill"]), pct(b1["fill"]), pct(b4["fill"])))
                continue
            P("| %g | %d | %s | %s / %s | %s | %s | %s | %s | %s | %s | %s | %d/24 | %s |" % (
                d, v, pct(st["fill"]), pct(b1["fill"]), pct(b4["fill"]), b.specs[j], f2(st["mean_t"][j]), ci1(st["mean"][j], st["se"][j]),
                f2(b1["mean"][j]), f2(b4["mean"][j]), dtxt(st, b1, j), dtxt(st, b4, j), int((st["mean"] > 0).sum()), f2(float(np.median(st["mean"])))))
    P("")
    return out


def adverse_table(b: BRes, win: str, title: str) -> list[str]:
    out = []
    P = out.append
    P("#### %s\n" % title)
    P("Getiri = sinyal fiyatından (P0) sinyal + 60 sn + 59 dk sonraki 1 dk kapanışına brüt % (ücretsiz); 'dolumdan' = limit fiyatından aynı kapanışa. Ortalama [gün-kümeli %95]. "
      "Seçim yanlılığı: dolan sinyallerde fiyat sonra daha mı kötü gidiyor?\n")
    P("| d % | geçerli (dk) | n dolan / dolmayan | P0'dan 60 dk: DOLAN | P0'dan 60 dk: DOLMAYAN | fark (dolan−dolmayan) | rastgele-4 dolan / dolmayan | dolan sinyaller: limit fiyatından 60 dk |")
    P("|---|---|---|---|---|---|---|---|")
    m_win = b.in_win(win)
    ok = b.extra["ok"]
    r60 = b.extra["ret60"]; c59 = b.extra["c59"]
    for d in B.D_LIST:
        for v in B.V_LIST:
            cell = "L d%g V%d" % (d, v)
            fi = b.fi[cell]
            sg = m_win & ok & (b.kind == 0) & np.isfinite(r60)
            filled = sg & (fi >= 0); unf = sg & (fi < 0)
            if filled.sum() < 20 or unf.sum() < 20:
                continue
            mf, sf = clus_mean(r60[filled], b.day[filled]); mu, su = clus_mean(r60[unf], b.day[unf])
            diff = mf - mu; sd = float(np.hypot(sf, su))
            lim = b.p0[filled] * (1.0 - d / 100.0)
            gl = (c59[filled] / lim - 1.0) * 100.0
            mg, sg_ = clus_mean(gl, b.day[filled])
            k4 = m_win & ok & (b.kind == 4) & np.isfinite(r60)
            f4 = k4 & (fi >= 0); u4 = k4 & (fi < 0)
            P("| %g | %d | %d / %d | %s [%s; %s] | %s [%s; %s] | %s [%s; %s] | %s / %s | %s [%s; %s] |" % (
                d, v, filled.sum(), unf.sum(), f2(mf, 3), f2(mf - 1.96 * sf, 3), f2(mf + 1.96 * sf, 3), f2(mu, 3), f2(mu - 1.96 * su, 3), f2(mu + 1.96 * su, 3),
                f2(diff, 3), f2(diff - 1.96 * sd, 3), f2(diff + 1.96 * sd, 3),
                f2(float(r60[f4].mean()), 3) if f4.any() else "—", f2(float(r60[u4].mean()), 3) if u4.any() else "—",
                f2(mg, 3), f2(mg - 1.96 * sg_, 3), f2(mg + 1.96 * sg_, 3)))
    P("")
    return out


def family_of(cell: str) -> str:
    p = cell.split()
    if p[0] in ("C", "LC"):
        return "%s %s" % (p[0], p[1])
    return p[0]


FAM_TEXT = {"M": "piyasa girişi (sinyal + 60 sn; referans)", "L": "düz limit", "LK": "limit + 5 dk StochRSI K<50",
            "C lv20": "(b) dip + ön sinyal teyidi, seviye 20", "C lv30": "(b) dip + ön sinyal teyidi, seviye 30",
            "LC lv20": "(c) limit dolumu + 5 dk içinde ön sinyal, seviye 20", "LC lv30": "(c) limit dolumu + 5 dk içinde ön sinyal, seviye 30"}


def variants_table(b: BRes, S: dict, win: str, title: str) -> list[str]:
    out = []
    P = out.append
    P("#### %s\n" % title)
    P("Her giriş ailesinin W30 net/sinyal'e göre EN İYİ (hücre, çıkış) bileşimi (**iç-örneklem, iyimser**; işlem ≥ 30). Net/sinyal: dolmayan = 0.\n")
    P("| aile | hücre | çıkış | dolum % (sinyal / rastgele-1 / rastgele-4) | işlem n | net/işlem | net/sinyal [%95] | rastgele-1 | rastgele-4 | sinyal−rastgele-4 [%95] | net/sinyal>0 bileşim (hücre×çıkış) |")
    P("|---|---|---|---|---|---|---|---|---|---|---|")
    fams = ["M", "L", "LK", "C lv20", "C lv30", "LC lv20", "LC lv30"]
    for fam in fams:
        best = None
        npos = 0; ntot = 0
        for c in b.cells:
            if family_of(c) != fam:
                continue
            st = S[c][(win, 0)]
            if not st.get("n") or st["ntr"] < 30:
                continue
            ntot += 24
            npos += int((st["mean"] > 0).sum())
            j = int(np.argmax(st["mean"]))
            if best is None or st["mean"][j] > best[0]:
                best = (st["mean"][j], c, j)
        if best is None:
            P("| %s | (yeterli işlem yok) | | | | | | | | | |" % FAM_TEXT[fam])
            continue
        _, c, j = best
        st = S[c][(win, 0)]; b1 = S[c][(win, 1)]; b4 = S[c][(win, 4)]
        P("| %s | %s | %s | %s / %s / %s | %d | %s | %s | %s | %s | %s | %d/%d |" % (
            FAM_TEXT[fam], c, b.specs[j], pct(st["fill"]), pct(b1["fill"]), pct(b4["fill"]), st["ntr"], f2(st["mean_t"][j]), ci1(st["mean"][j], st["se"][j]),
            f2(b1["mean"][j]), f2(b4["mean"][j]), dtxt(st, b4, j), npos, ntot))
    P("")
    return out


def top_table(b: BRes, S: dict, win: str, k: int = 10) -> list[str]:
    rows = []
    for c in b.cells:
        st = S[c][(win, 0)]
        if not st.get("n") or st["ntr"] < 100:
            continue
        b1 = S[c][(win, 1)]; b4 = S[c][(win, 4)]
        for j in range(24):
            rows.append((st["mean"][j], c, j))
    rows.sort(reverse=True)
    out = []
    P = out.append
    P("| sıra | hücre | çıkış | dolum % | işlem n | net/işlem | net/sinyal [%95] | rastgele-4 net/sinyal | sinyal−rastgele-4 [%95] |")
    P("|---|---|---|---|---|---|---|---|---|")
    for i, (m, c, j) in enumerate(rows[:k]):
        st = S[c][(win, 0)]; b4 = S[c][(win, 4)]
        P("| %d | %s | %s | %s | %d | %s | %s | %s | %s |" % (i + 1, c, b.specs[j], pct(st["fill"]), st["ntr"], f2(st["mean_t"][j]), ci1(st["mean"][j], st["se"][j]), f2(b4["mean"][j]), dtxt(st, b4, j)))
    P("")
    npos = sum(1 for r in rows if r[0] > 0)
    return out, len(rows), npos


def scan_counts(b: BRes, S: dict, win: str):
    """(işlem ≥ 100 bileşim sayısı, net/sinyal>0 sayısı, sinyal−rastgele-4 alt sınırı>0 sayısı, net/işlem>0 sayısı)."""
    n = npos = nd = npt = 0
    for c in b.cells:
        st = S[c][(win, 0)]
        if not st.get("n") or st["ntr"] < 100:
            continue
        b4 = S[c][(win, 4)]
        for j in range(24):
            n += 1
            if st["mean"][j] > 0:
                npos += 1
            if st["mean_t"][j] > 0:
                npt += 1
            d, lo, hi = dci(st, b4, j)
            if np.isfinite(lo) and lo > 0:
                nd += 1
    return n, npos, nd, npt


def pick(b: BRes, S: dict, win: str, crit: str, min_ntr: int = 100):
    best = None
    for c in b.cells:
        st = S[c][(win, 0)]
        if not st.get("n") or st["ntr"] < min_ntr:
            continue
        b4 = S[c][(win, 4)]
        for j in range(24):
            v = st["mean"][j] if crit == "net" else (st["mean"][j] - b4["mean"][j])
            if best is None or v > best[0]:
                best = (v, c, j)
    return best


def combo_txt(b: BRes, S: dict, cell: str, j: int, win: str):
    st = S[cell][(win, 0)]
    if not st.get("n"):
        return None
    b1 = S[cell][(win, 1)]; b4 = S[cell][(win, 4)]
    return st, b1, b4


def walk_table(bs: dict, Ss: dict, bO: dict, SO: dict) -> list[str]:
    out = []
    P = out.append
    b = bs["HA"]; S = Ss["HA"]
    P("#### HA 90 gün: yürüyen-ileri (eğitim penceresinde bileşim seç → diğer pencerede DOKUNMADAN ölç), senaryo P\n")
    P("Evren: 73 giriş hücresi × 24 çıkış = 1 752 bileşim (işlem ≥ 100). Ölçüt A = eğitim net/sinyal; ölçüt B = eğitim (net/sinyal − rastgele-4 net/sinyal).\n")
    P("| ölçüt | eğitim → test | seçilen bileşim | eğitim net/sinyal | OOS dolum % | OOS işlem n | OOS net/işlem | OOS net/sinyal [%95] | rastgele-1 | rastgele-4 | sinyal−rastgele-4 [%95] | OOS iyimser (0 sn/%0,05) net/sinyal |")
    P("|---|---|---|---|---|---|---|---|---|---|---|---|")
    pairs = [("B1", "B2"), ("B1", "B3"), ("B2", "B1"), ("B2", "B3"), ("B3", "B1"), ("B3", "B2"), ("B12", "B3")]
    summ = {"rows": 0, "pos": 0, "lo_pos": 0, "dpos": 0}
    for crit, cname in (("net", "A"), ("diff", "B")):
        for tr, te in pairs:
            pk = pick(b, S, tr, crit)
            if pk is None:
                continue
            _, c, j = pk
            st = S[c][(te, 0)]
            if not st.get("n"):
                continue
            b1 = S[c][(te, 1)]; b4 = S[c][(te, 4)]
            trs = S[c][(tr, 0)]
            o = ""
            if "HA" in SO:
                so = SO["HA"][c][(te, 0)]
                if so.get("n"):
                    o = f2(so["mean"][j])
            d, lo, hi = dci(st, b4, j)
            summ["rows"] += 1
            summ["pos"] += int(st["mean"][j] > 0)
            summ["lo_pos"] += int(st["mean"][j] - 1.96 * st["se"][j] > 0)
            summ["dpos"] += int(lo > 0)
            P("| %s | %s → %s | %s / %s | %s | %s | %d | %s | %s | %s | %s | %s | %s |" % (
                cname, tr, te, c, b.specs[j], f2(trs["mean"][j]), pct(st["fill"]), st["ntr"], f2(st["mean_t"][j]), ci1(st["mean"][j], st["se"][j]),
                f2(b1["mean"][j]), f2(b4["mean"][j]), dtxt(st, b4, j), o))
    P("")
    P("Yürüyen-ileri özeti: %d satır; OOS net/sinyal > 0: %d; %%95 alt sınırı > 0: %d; sinyal−rastgele-4 alt sınırı > 0: %d.\n" % (summ["rows"], summ["pos"], summ["lo_pos"], summ["dpos"]))
    # donmuş seçimin diğer kaynaklara uygulanması
    P("#### Donmuş seçim (HA B1+B2'de seçildi) → HA B3, canlı journal adayları (ileri, 18 Eyl–16 Eki), canlı bildirimler\n")
    P("| ölçüt | seçilen bileşim | kaynak / pencere | dolum % | işlem n | net/işlem | net/sinyal [%95] | rastgele-1 | rastgele-4 | sinyal−rastgele-4 [%95] | iyimser (0 sn/%0,05) net/sinyal |")
    P("|---|---|---|---|---|---|---|---|---|---|---|")
    targets = [("HA", "B3"), ("LIVE", "B3"), ("NOTIF_all", "W30"), ("NOTIF_trend", "W30")]
    for crit, cname in (("net", "A"), ("diff", "B")):
        pk = pick(b, S, "B12", crit)
        if pk is None:
            continue
        _, c, j = pk
        for src, w in targets:
            S2 = Ss[src]; b2 = bs[src]
            st = S2[c][(w, 0)]
            if not st.get("n"):
                continue
            b1 = S2[c][(w, 1)]; b4 = S2[c][(w, 4)]
            o = ""
            if src in SO:
                so = SO[src][c][(w, 0)]
                if so.get("n"):
                    o = f2(so["mean"][j])
            P("| %s | %s / %s | %s %s | %s | %d | %s | %s | %s | %s | %s | %s |" % (
                cname, c, b.specs[j], src, w, pct(st["fill"]), st["ntr"], f2(st["mean_t"][j]), ci1(st["mean"][j], st["se"][j]), f2(b1["mean"][j]), f2(b4["mean"][j]),
                dtxt(st, b4, j), o))
    P("")
    return out, summ
