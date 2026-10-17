"""Rapor bölümleri: Çalışma A (ön sinyal → çekirdek dönüşü, olay zamanlaması, giriş sinyali)."""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import limitstoch_lib as L  # noqa: E402

f2, p1 = L.f2, L.p1
NS = (1, 3, 6, 12)
TFS = ("5m", "1m", "15m")
TFMIN = {"5m": 5, "1m": 1, "15m": 15}
RNG = np.random.default_rng(101)


def pct(x, nd=1):
    return "—" if x is None or not np.isfinite(x) else ("%." + str(nd) + "f") % (100 * x)


def boot_ratio_diff(a: np.ndarray, b: np.ndarray, col: int, reps: int = 800):
    """a, b: (ndays, 1+k) gün başına [n, c...]. P_a − P_b'nin gün-bootstrap %95 aralığı."""
    nd = a.shape[0]
    pa = a[:, col].sum() / max(a[:, 0].sum(), 1)
    pb = b[:, col].sum() / max(b[:, 0].sum(), 1)
    idx = RNG.integers(0, nd, size=(reps, nd))
    na = a[idx, 0].sum(1); ca = a[idx, col].sum(1); nb = b[idx, 0].sum(1); cb = b[idx, col].sum(1)
    ok = (na > 0) & (nb > 0)
    d = ca[ok] / na[ok] - cb[ok] / nb[ok]
    return pa - pb, float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def wilson(k, n, z=1.96):
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (c - h, c + h)


def hist_median(h: np.ndarray) -> float:
    """h[k] = k bar uzaklıkta sayı (k=0..12). Medyan bar."""
    tot = h.sum()
    if tot <= 0:
        return float("nan")
    c = np.cumsum(h)
    return float(np.searchsorted(c, tot / 2.0))


def sect_a1(res: dict) -> list[str]:
    a1 = res["a1"]
    T, P, LH = a1["turn"], a1["prec"], a1["lead_hist"]
    out = []
    A = out.append
    A("## 2. Çalışma A-1 — Ön sinyal çekirdek AL dönüşünü önceden haber veriyor mu?\n")
    A("Tanım: ön sinyal bar i'nin kapanışında verilir (çekirdek i'de KIRMIZI). 'N bar içinde dönüş' = i+1 … i+N barlarından birinde çekirdek yeşil. "
      "Taban 1 (**kırmızı**) = çekirdeğin kırmızı olduğu TÜM barlar; taban 2 (**kırmızı+dip**) = kırmızı ve K[i-1] < seviye ama kesişim şartı YOK (kesişimin kendisinin katkısını ayırır). "
      "Likit sembol (24 sa ≥ 5M TRY). Aralıklar gün-bootstrap %95 (aynı gündeki barlar ilişkili). Fark = ön sinyal − taban (yüzde puan).\n")
    for tf in TFS:
        for lv in L.LEVELS:
            pre = T[(tf, "W30", lv, "pre")]; b1 = T[(tf, "W30", lv, "base_red")]; b2 = T[(tf, "W30", lv, "base_low")]
            npre = pre[:, 0].sum()
            A("### %s çekirdek / StochRSI K seviye %d — W30 (17 Eyl–16 Eki)%s\n" % (tf, lv, "  (BİRİNCİL)" if tf == "5m" and lv == 20 else ""))
            A("Ön sinyal sayısı: **%d** (%.0f/gün); kırmızı bar tabanı: %d bar; kırmızı+dip tabanı: %d bar.\n" % (npre, npre / 30.0, b1[:, 0].sum(), b2[:, 0].sum()))
            A("| N bar (≈ dk) | P(dönüş \\| ön sinyal) | taban 1 kırmızı | fark [%95] | oran | taban 2 kırmızı+dip | fark [%95] | oran |")
            A("|---|---|---|---|---|---|---|---|")
            for q, N in enumerate(NS):
                col = 1 + q
                pp = pre[:, col].sum() / npre
                lo, hi = wilson(pre[:, col].sum(), npre)
                d1, l1, h1 = boot_ratio_diff(pre, b1, col)
                d2, l2, h2 = boot_ratio_diff(pre, b2, col)
                p1v = b1[:, col].sum() / b1[:, 0].sum(); p2v = b2[:, col].sum() / b2[:, 0].sum()
                A("| %d (%d dk) | %s%% [%s; %s] | %s%% | %+.1f [%+.1f; %+.1f] | %.2f× | %s%% | %+.1f [%+.1f; %+.1f] | %.2f× |" % (
                    N, N * TFMIN[tf], pct(pp), pct(lo), pct(hi), pct(p1v), 100 * d1, 100 * l1, 100 * h1, pp / p1v, pct(p2v), 100 * d2, 100 * l2, 100 * h2, pp / p2v))
            h = LH[(tf, "W30", lv, "pre")]
            med = hist_median(h)
            tot = h.sum()
            A("")
            A("12 bar içinde dönüş olan ön sinyallerde **medyan öncülük: %.0f bar = %.0f dk**; dağılım (bar 1…12, %% toplamın): %s." % (
                med, med * TFMIN[tf], " ".join("%.0f" % (100 * x / tot) for x in h[1:13])))
            f = P[(tf, "W30", lv, "flip")].sum(0); b = P[(tf, "W30", lv, "base")].sum(0)
            hf = LH[(tf, "W30", lv, "flip")]
            A("Tersi: kırmızı→yeşil dönüş barlarının **%s%%'inden önceki 12 barda ön sinyal var** (n=%d); dönüşe uygun HERHANGİ bir kırmızı barın önceki 12 barında ön sinyal olma oranı (taban) %s%% → oran %.2f×. "
              "Dönüşten önceki son ön sinyal medyan %.0f bar = %.0f dk önce.\n" % (pct(f[1] / f[0]), f[0], pct(b[1] / b[0]), (f[1] / f[0]) / (b[1] / b[0]), hist_median(hf), hist_median(hf) * TFMIN[tf]))
    A("### Bloklara göre sağlamlık (fark = P(N bar içinde dönüş | ön sinyal) − kırmızı bar tabanı, yüzde puan [%95])\n")
    A("| çekirdek | seviye | N | B1 | B2 | B3 | W30 |")
    A("|---|---|---|---|---|---|---|")
    for tf in TFS:
        for lv in L.LEVELS:
            for q, N in enumerate(NS):
                if N not in (3, 6, 12):
                    continue
                cells = []
                for w in ("B1", "B2", "B3", "W30"):
                    d, lo, hi = boot_ratio_diff(T[(tf, w, lv, "pre")], T[(tf, w, lv, "base_red")], 1 + q)
                    cells.append("%+.1f [%+.1f; %+.1f]" % (100 * d, 100 * lo, 100 * hi))
                A("| %s | %d | %d | %s |" % (tf, lv, N, " | ".join(cells)))
    A("")
    return out


# ------------------------------------------------------------------------------------------------ olay zamanlaması
def event_rates(res: dict, tf: str, lv: int, typ: str, which: str, only_w30: bool, reps: int = 600):
    """Olay (kind 0) vs rastgele (kind 1, olay başına ortalama) oranları + gün-bootstrap farkı."""
    key = ((tf, lv, typ), which)
    ev_hit, rn_hit, days = [], [], []
    for st in res["ev"]["store"]:
        if key not in st["res"]:
            continue
        hit = st["res"][key].astype(float)
        kind = st["kind"]; evi = st["ev"]; t = st["t"]; day = st["day"]
        m0 = kind == 0
        if only_w30:
            keep_ev = L.window_mask(t[m0], "W30")
        else:
            keep_ev = np.ones(m0.sum(), dtype=bool)
        e_ids = evi[m0]
        h0 = hit[m0]
        # rastgele: olay başına ortalama
        r_mean = {}
        for eid in e_ids:
            mm = (evi == eid) & (kind == 1)
            r_mean[eid] = hit[mm].mean() if mm.any() else np.nan
        rm = np.array([r_mean[e] for e in e_ids])
        ok = keep_ev & np.isfinite(rm)
        ev_hit.append(h0[ok]); rn_hit.append(rm[ok]); days.append(day[m0][ok])
    ev_hit = np.concatenate(ev_hit); rn_hit = np.concatenate(rn_hit); days = np.concatenate(days)
    ud, inv = np.unique(days, return_inverse=True)
    nd = len(ud)
    ce = np.bincount(inv, weights=ev_hit, minlength=nd); cr = np.bincount(inv, weights=rn_hit, minlength=nd); cn = np.bincount(inv, minlength=nd)
    idx = RNG.integers(0, nd, size=(reps, nd))
    e_b = ce[idx].sum(1) / cn[idx].sum(1); r_b = cr[idx].sum(1) / cn[idx].sum(1)
    pe = ce.sum() / cn.sum(); pr = cr.sum() / cn.sum()
    return {"n": int(cn.sum()), "pe": pe, "pr": pr, "d": pe - pr, "lo": float(np.percentile(e_b - r_b, 2.5)), "hi": float(np.percentile(e_b - r_b, 97.5)),
            "ratio": pe / pr if pr > 0 else float("nan"), "r_lo": float(np.percentile(e_b / np.maximum(r_b, 1e-9), 2.5)), "r_hi": float(np.percentile(e_b / np.maximum(r_b, 1e-9), 97.5))}


def lead_stats(res: dict, tf: str, lv: int, typ: str, only_w30: bool):
    """Olay kind 0: [t0-30dk, t0+5dk] içinde ilk / t0'a kadar son sinyalin t0'a göre dakikası; t0 sonrası ilk AL dönüşü."""
    first, last, nxt_flip = [], [], []
    for st in res["ev"]["store"]:
        key = (tf, lv, typ)
        if (key, "first") not in st["res"]:
            continue
        m0 = st["kind"] == 0
        if only_w30:
            m0 = m0 & L.window_mask(st["t"], "W30")
        t0 = st["t"][m0]
        f = st["res"][(key, "first")][m0]; la = st["res"][(key, "last_before")][m0]
        nf = st["res"][((tf, 0, "flip"), "next_after")][m0]
        first.append(np.where(f >= 0, (t0 - f) / 60000.0, np.nan))
        last.append(np.where(la >= 0, (t0 - la) / 60000.0, np.nan))
        nxt_flip.append(np.where(nf >= 0, (nf - t0) / 60000.0, np.nan))
    return np.concatenate(first), np.concatenate(last), np.concatenate(nxt_flip)


def sect_a2(res: dict, lunatry: list[str]) -> list[str]:
    out = []
    A = out.append
    ev = res["ev"]
    A("## 3. Çalışma A-2 — LUNA tipi erken yükselişler: ön sinyal [t0 − 30 dk, t0 + 5 dk] içinde çalıyor mu?\n")
    A("Olaylar: `work/pattern90/events.csv` (60 dk içinde ≥ +%%4, ≥ %%70 yeşil mum, geri çekilme ≤ %%1,5; kümesiz birincil **%d** olay; t0 = koşunun ilk mumu). "
      "Rastgele: aynı sembol + aynı İstanbul günü, olay koşularından ±60 dk uzak, olay başına ≤ 40 beş-dakikalık an (olay başına ortalama alınır). "
      "Hit = pencerede en az bir sinyal. **Dikkat:** olay tanımı geleceğe bakar (t0 → +%%4 yükseliş), olaylar küçük bir düşüşün diplerinden başlar; bu yüzden 'dip bölgesinde kesişim' olaylarda doğal olarak sık görünür — "
      "asıl sınav rastgele andan ayrışma + t0'dan ÖNCE (nedensel) pencere.\n" % ev["n_events"])
    for only_w30, label in ((False, "90 gün (07-20 → 10-16)"), (True, "W30 (t0 17 Eyl–16 Eki)")):
        A("### %s\n" % label)
        A("| çekirdek | sinyal | pencere | olay hit % | rastgele hit % | fark [%95] | oran [%95] | n olay |")
        A("|---|---|---|---|---|---|---|---|")
        for tf in TFS:
            for lv in L.LEVELS:
                for typ, tname in (("pre", "ön sinyal"), ("conf", "onaylı (≤6 bar)")):
                    for which, wname in (("a", "t0−30…+5"), ("b", "t0−30…t0 (nedensel)")):
                        r = event_rates(res, tf, lv, typ, which, only_w30)
                        A("| %s | %s %d | %s | %s | %s | %+.1f [%+.1f; %+.1f] | %.2f× [%.2f; %.2f] | %d |" % (
                            tf, tname, lv, wname, pct(r["pe"]), pct(r["pr"]), 100 * r["d"], 100 * r["lo"], 100 * r["hi"], r["ratio"], r["r_lo"], r["r_hi"], r["n"]))
        for tf in TFS:
            for which, wname in (("a", "t0−30…+5"), ("b", "t0−30…t0 (nedensel)")):
                r = event_rates(res, tf, 0, "flip", which, only_w30)
                A("| %s | çekirdek AL dönüşü (referans) | %s | %s | %s | %+.1f [%+.1f; %+.1f] | %.2f× [%.2f; %.2f] | %d |" % (
                    tf, wname, pct(r["pe"]), pct(r["pr"]), 100 * r["d"], 100 * r["lo"], 100 * r["hi"], r["ratio"], r["r_lo"], r["r_hi"], r["n"]))
        A("")
    A("### Öncülük süresi (dk) — 90 gün; yalnız pencerede sinyali olan olaylar\n")
    A("| çekirdek | sinyal | hit olay | t0'a göre İLK sinyal (dk önce) medyan [Q1–Q3] | t0'dan önceki SON sinyal (dk önce) medyan | t0 sonrası ilk çekirdek AL dönüşü (dk sonra) medyan |")
    A("|---|---|---|---|---|---|")
    for tf in TFS:
        for lv in L.LEVELS:
            fi, la, nf = lead_stats(res, tf, lv, "pre", False)
            m = np.isfinite(fi)
            q = np.nanpercentile(fi, [25, 50, 75]) if m.any() else [np.nan] * 3
            A("| %s | ön sinyal %d | %d | %.0f [%.0f–%.0f] | %.0f | %.0f |" % (tf, lv, m.sum(), q[1], q[0], q[2], np.nanmedian(la) if np.isfinite(la).any() else float("nan"),
                                                                         np.nanmedian(nf) if np.isfinite(nf).any() else float("nan")))
    A("")
    A("Okuma: ilk sinyal dk önce > 0 → t0'dan ÖNCE (öncü); negatif → yükseliş başladıktan sonra. Çekirdek AL dönüşü sütunu ölçülen gecikmedir (RQK analizi: yükselişten sonra döner).\n")
    A("### LUNATRY 17 Ekim 01:00 (t0; +%8 / 60 dk) sağlama\n")
    out.extend(lunatry)
    A("")
    return out


def lunatry_lines() -> list[str]:
    out = []
    sym = "LUNATRY"
    t0 = L.parse_day("2026-10-17") + 3_600_000        # 01:00 İstanbul
    lo = t0 - 90 * 60_000; hi = t0 + 120 * 60_000
    a1 = L.load_arr("1m", sym)
    ot1 = a1[:, 0].astype(np.int64)
    j0 = int(np.searchsorted(ot1, t0))
    p0 = float(a1[j0 - 1, 4])
    out.append("t0 = 01:00; P0 (t0 öncesi son 1 dk kapanışı) = %.5g; yükseliş: 60 dk sonra %.5g (%+.2f%%).\n" % (p0, a1[min(j0 + 59, len(a1) - 1), 4], (a1[min(j0 + 59, len(a1) - 1), 4] / p0 - 1) * 100))
    out.append("| çekirdek | sinyal | zaman (İstanbul) | t0'a göre (dk) | kapanış fiyatı / P0 |")
    out.append("|---|---|---|---|---|")
    for tf in TFS:
        ind = L.get_ind(tf, sym)
        a = L.load_arr(tf, sym)
        ct = ind["ot"] + L.TF_MS[tf]
        items = []
        for lv in L.LEVELS:
            for i in np.flatnonzero(ind["ps%d" % lv]):
                if lo <= ct[i] <= hi:
                    items.append((ct[i], "ön sinyal (K<%d)" % lv, a[i, 4]))
        flip = ind["bull"] & ind["valid"] & np.concatenate([[False], (ind["valid"] & ~ind["bull"])[:-1]])
        for i in np.flatnonzero(flip):
            if lo <= ct[i] <= hi:
                items.append((ct[i], "çekirdek AL dönüşü", a[i, 4]))
        items.sort()
        if not items:
            out.append("| %s | (pencerede yok) | | | |" % tf)
        # çok satır olmasın: 1 dk için yalnız t0 − 45 … t0 + 30
        for t, name, px in items:
            if tf == "1m" and not (t0 - 45 * 60_000 <= t <= t0 + 30 * 60_000):
                continue
            out.append("| %s | %s | %s | %+.0f | %.4f |" % (tf, name, L.fmt_t(t, "%H:%M"), (t - t0) / 60000.0, px / p0))
    out.append("")
    return out
