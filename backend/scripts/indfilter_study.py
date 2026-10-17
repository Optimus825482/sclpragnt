"""A. Hassasiyet (filtre) çalışması — indikatör kütüphanesi özellikleri iyi/kötü sinyali ayırıyor mu? (2026-10-17, çevrimdışı; canlı koda BAĞLANMAZ)

Girdi : work/indfilter/{events,prep,feats}_<pop>.* (indfilter_prep.py + indfilter_feats.py üretir)
Çıktı : work/indfilter/section_A.md  (rapor birleşimi: scripts/indfilter_report.py)

Nüfuslar : ha    = Hız Avcısı canlı-benzeri bölümler, 3 blok (B1 20 Tem–18 Ağu, B2 19 Ağu–17 Eyl, B3 18 Eyl–16 Eki)
           notif = push bildirimleri (2007), seçim 17.09–09.10 / değerlendirme 10.10–17.10; alt küme `confirm` = YENİ canlı teyit kuralı
Başarı   : hit (60 dk içinde hedef görüldü) ve net (exit_sim: 60 sn gecikme, %0,15 kayma, %0,1125/bacak, TP=hedef, SL 3, zaman 60);
           "fazla" = olay − oynaklık-eşleşmiş rastgele taban (aynı sembol/blok, ATR ±%25, aynı TP/SL).
Kontrol  : ATR (5 dk ATR14 %) ve hedef/ATR sıralarının 1.+2. derece terimleriyle kısmi Spearman; ATR tersilleri içinde üst−alt yarı farkı.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.rescan import confirm_elems as C  # noqa: E402
from scripts import indfilter_common as K  # noqa: E402

MIN_KEEP_FRAC = 0.10
MAX_KEEP_FRAC = 0.85
Q_THR = (1 / 3, 0.5, 2 / 3)


# ------------------------------------------------------------------------------------------------ yükleme
def load_feats(pop: str) -> tuple[list[str], np.ndarray]:
    z = np.load(K.OUT / ("feats_%s.npz" % pop), allow_pickle=False)
    X = z["X"].astype(np.float32)
    X[~np.isfinite(X)] = np.nan              # float32 taşması (inf) → eksik
    return [str(s) for s in z["names"]], X


def norm_p(t) -> float:
    """t ya da partial_spearman sonucu (dict) → iki yönlü p (Student t, df = gün kümesi − 1)."""
    if isinstance(t, dict):
        return K.t_pvalue(t["t"], t.get("g", 0))
    from scipy.stats import norm
    return float(2.0 * norm.sf(abs(t))) if np.isfinite(t) else float("nan")


def md(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out) + "\n"


def f2(x, nd=2) -> str:
    return "–" if x is None or not np.isfinite(x) else ("%+." + str(nd) + "f") % x


def fp(x) -> str:
    return "–" if x is None or not np.isfinite(x) else "%.1f%%" % (100 * x)


# ------------------------------------------------------------------------------------------------ nüfus özeti
class Study:
    def __init__(self, name: str, blocks_labels: list[str]):
        self.name = name
        self.pop = K.Pop(name)
        p = self.pop
        self.S = p.sim(p.tp)
        self.net, self.hit = self.S["net"], self.S["hit"]
        self.ex_net = self.net - self.S["b_net"]
        self.ex_hit = self.hit - self.S["b_hit"]
        self.atr = p.atr
        self.rel = p.tp / np.maximum(p.atr, 1e-6)
        self.ctrl = np.column_stack([self.atr, self.rel])
        self.blocks_labels = blocks_labels
        self.names, self.X = load_feats(name)
        self.valid = p.valid & np.isfinite(self.net)
        self.confirm = np.asarray(p.ev.get("confirm", np.zeros(p.n, dtype=bool)), dtype=bool)
        _, self.dinv = np.unique(p.day, return_inverse=True)

    def blk(self, b: int) -> np.ndarray:
        return self.valid & (self.pop.block == b)

    def period_mask(self, kind: str) -> np.ndarray:
        """kind: 'sel' (ilk blok), 'oos' (diğer bloklar), 'all'."""
        nb = len(self.blocks_labels)
        if kind == "sel":
            return self.blk(0)
        if kind == "oos":
            m = np.zeros(self.pop.n, dtype=bool)
            for b in range(1, nb):
                m |= self.blk(b)
            return m
        return self.valid


def summarize(st: Study, mask: np.ndarray, days: float | None = None) -> dict:
    p = st.pop
    m = mask & st.valid
    n = int(m.sum())
    if n == 0:
        return {"n": 0}
    out = {"n": n}
    if days:
        out["per_day"] = n / days
    out["hit"] = float(st.hit[m].mean())
    out["b_hit"] = float(np.nanmean(st.S["b_hit"][m])) if np.isfinite(st.S["b_hit"][m]).any() else float("nan")
    out["net"] = C.cluster_bootstrap_mean(st.net[m], p.day[m], 400, 1)
    out["b_net"] = float(np.nanmean(st.S["b_net"][m])) if np.isfinite(st.S["b_net"][m]).any() else float("nan")
    out["ex"] = C.paired_diff_stats(st.net[m], st.S["b_net"][m], p.day[m])
    out["ex_hit"] = C.paired_diff_stats(st.hit[m], st.S["b_hit"][m], p.day[m])
    out["atr"] = float(np.mean(st.atr[m]))
    return out


def block_days(pop: K.Pop, blocks) -> list[float]:
    return [(b - a + 1) / K.DAY_MS for a, b in blocks]


def pop_table(st: Study, blocks, labels) -> str:
    rows = []
    days = block_days(st.pop, blocks)
    scopes = [("tümü", st.valid)]
    if st.confirm.any():
        scopes.append(("teyit kuralı", st.valid & st.confirm))
    for sn, sm in scopes:
        for b, lab in enumerate(labels):
            s = summarize(st, sm & (st.pop.block == b), days[b])
            if not s["n"]:
                continue
            rows.append([sn, lab, s["n"], "%.1f" % s["per_day"], fp(s["hit"]), fp(s["b_hit"]), f2(s["net"][0]), f2(s["b_net"]),
                         "%s [%s; %s]" % (f2(s["ex"]["mean"]), f2(s["ex"]["lo"]), f2(s["ex"]["hi"])), "%.2f" % s["atr"]])
        s = summarize(st, sm, sum(days))
        rows.append([sn, "tümü", s["n"], "%.1f" % s["per_day"], fp(s["hit"]), fp(s["b_hit"]), f2(s["net"][0]), f2(s["b_net"]),
                     "%s [%s; %s]" % (f2(s["ex"]["mean"]), f2(s["ex"]["lo"]), f2(s["ex"]["hi"])), "%.2f" % s["atr"]])
    return md(["kapsam", "dilim", "n", "gün/adet", "hit", "taban hit", "net", "taban net", "net − taban [95]", "ort. ATR%"], rows)


# ------------------------------------------------------------------------------------------------ A1. özellik sıralaması
def rank_features(st: Study, scope: np.ndarray) -> list[dict]:
    p = st.pop
    m0 = scope & st.valid
    rows = []
    nb = len(st.blocks_labels)
    for j, nm in enumerate(st.names):
        x = st.X[:, j].astype(float)
        if not K.support_ok(x[m0], p.day[m0]):
            continue
        r = {"name": nm, "cover": float(np.isfinite(x[m0]).mean())}
        for key, y in (("net", st.net), ("exn", st.ex_net), ("hit", st.hit), ("exh", st.ex_hit)):
            r["raw_" + key] = K.partial_spearman(x[m0], y[m0], None, p.day[m0])
            r["par_" + key] = K.partial_spearman(x[m0], y[m0], st.ctrl[m0], p.day[m0])
        r["auc_net"] = K.auc_score(x[m0], st.net[m0] > 0)
        r["auc_hit"] = K.auc_score(x[m0], st.hit[m0] > 0.5)
        sgn = np.sign(r["par_exn"]["r"]) if np.isfinite(r["par_exn"]["r"]) else 0.0
        agree = 0
        per = []
        for b in range(nb):
            mb = m0 & (p.block == b)
            pb = K.partial_spearman(x[mb], st.ex_net[mb], st.ctrl[mb], p.day[mb])
            per.append(pb["r"])
            agree += int(np.isfinite(pb["r"]) and np.sign(pb["r"]) == sgn and sgn != 0)
        r["blk_r"] = per
        r["agree"] = agree
        rows.append(r)
    for key in ("raw_net", "par_net", "raw_exn", "par_exn", "raw_hit", "par_hit", "par_exh"):
        q = C.bh_adjust([norm_p(r[key]) for r in rows])
        for r, qq in zip(rows, q):
            r["q_" + key] = float(qq)
    return rows


def rank_tables(rows: list[dict], nb: int, top: int = 15) -> str:
    out = []
    cnt = []
    for key, lab in (("raw_net", "net (ham)"), ("par_net", "net (ATR-kontrollü)"), ("raw_exn", "net−taban (ham)"),
                     ("par_exn", "net−taban (ATR-kontrollü)"), ("raw_hit", "hit (ham)"), ("par_hit", "hit (ATR-kontrollü)"),
                     ("par_exh", "hit−taban (ATR-kontrollü)")):
        k5 = sum(1 for r in rows if np.isfinite(r["q_" + key]) and r["q_" + key] < 0.05)
        k1 = sum(1 for r in rows if np.isfinite(r["q_" + key]) and r["q_" + key] < 0.01)
        cnt.append([lab, len(rows), k5, k1])
    out.append("Anlamlı (BH q) özellik sayısı:\n\n" + md(["sonuç", "özellik", "q<0,05", "q<0,01"], cnt))
    both = [r for r in rows if np.isfinite(r["q_par_hit"]) and r["q_par_hit"] < 0.05 and np.isfinite(r["q_par_exn"]) and r["q_par_exn"] < 0.05]
    opp = [r for r in both if np.sign(r["par_hit"]["r"]) != np.sign(r["par_exn"]["r"])]
    out.append("Hem hit'te hem net−taban'da (ATR-kontrollü) anlamlı %d özellikten **%d**'inde işaretler TERS (hit'i artıran özellik net'i azaltıyor): "
               "hit'e bakarak seçilen filtre net'i bozabilir.\n" % (len(both), len(opp)))
    hdr = ["özellik", "kapsam", "ham r(net) [t]", "ATR-kont. r(net) [t]", "ATR-kont. r(net−taban) [t]", "q", "ATR-kont. r(hit) [t]", "q(hit)",
           "AUC net>0", "AUC hit", "blok r(net−taban)", "işaret uyumu"]

    def row(r):
        return [r["name"], "%.0f%%" % (100 * r["cover"]), "%+.3f [%+.1f]" % (r["raw_net"]["r"], r["raw_net"]["t"]),
                "%+.3f [%+.1f]" % (r["par_net"]["r"], r["par_net"]["t"]), "%+.3f [%+.1f]" % (r["par_exn"]["r"], r["par_exn"]["t"]),
                "%.3f" % r["q_par_exn"], "%+.3f [%+.1f]" % (r["par_hit"]["r"], r["par_hit"]["t"]), "%.3f" % r["q_par_hit"],
                "%.3f" % r["auc_net"] if np.isfinite(r["auc_net"]) else "–", "%.3f" % r["auc_hit"] if np.isfinite(r["auc_hit"]) else "–",
                " / ".join("%+.3f" % v if np.isfinite(v) else "–" for v in r["blk_r"]), "%d/%d" % (r["agree"], nb)]
    srt = sorted(rows, key=lambda r: -abs(r["par_exn"]["t"]) if np.isfinite(r["par_exn"]["t"]) else 0)
    out.append("En iyi %d özellik — ATR-kontrollü net−taban |t| sıralı:\n\n" % top + md(hdr, [row(r) for r in srt[:top]]))
    srt2 = sorted(rows, key=lambda r: -abs(r["raw_net"]["t"]) if np.isfinite(r["raw_net"]["t"]) else 0)
    out.append("En iyi %d özellik — HAM net |t| sıralı (ATR'nin etkisi dahil):\n\n" % top + md(hdr, [row(r) for r in srt2[:top]]))
    srt3 = sorted(rows, key=lambda r: -abs(r["par_hit"]["t"]) if np.isfinite(r["par_hit"]["t"]) else 0)
    out.append("En iyi %d özellik — ATR-kontrollü HIT |t| sıralı:\n\n" % top + md(hdr, [row(r) for r in srt3[:top]]))
    return "\n".join(out)


FAM_TR = {"ma": "hareketli ortalamalar (ALMA/HMA/DEMA/KAMA/McGinley/LSMA)", "flow": "hacim/akış (OBV, A/D, CMF, Klinger, CVD, OFI)",
          "osc": "osilatörler (Stoch, TSI, KST, Fisher, CCI, ...)", "trend": "trend/kanal (SuperTrend, PSAR, Ichimoku, Donchian, Keltner, sıkışma, Choppiness)",
          "vol": "oynaklık (ATR oranı, HV, RVI)", "loc": "konum (VWAP, çapalı VWAP, POC)", "smc": "SMC (BOS/CHoCH, eşit tepe/dip, süpürme, FVG, OB, TD)"}


def family_of(name: str) -> str:
    """Özellik adı → aile etiketi (kütüphane FAMILY sözlüğü; öbürleri ön ekten)."""
    if name.startswith("idea:"):
        return "klasik fikir (0/1)"
    if name.startswith("ex:"):
        return "mevcut sistem alanları (jsonl/olay)"
    if name.startswith("dyn:"):
        return "dyn_target bileşenleri"
    if name.startswith("res:"):
        return "direnç mesafesi"
    base = name.split(".", 1)[1] if "." in name else name
    try:
        from app.rescan import indicators_ext as L
        if not L.FAMILY:
            L.feature_names("5m")
        f = L.FAMILY.get(base)
    except Exception:
        f = None
    return FAM_TR.get(f, "mevcut özellik (pattern_study: EMA/RSI/MFI/ATR/BB/MACD/ADX/taker...)")


def family_table(rows: list[dict], nb: int) -> str:
    """Aile bazında: kaç özellik test edildi, kaçı ATR-kontrollü net−taban'da q<0,05 ve bloklar arası işaret uyumlu, en iyi özellik."""
    fams: dict[str, list[dict]] = {}
    for r in rows:
        fams.setdefault(family_of(r["name"]), []).append(r)
    out = []
    for f, rs in sorted(fams.items(), key=lambda kv: -len(kv[1])):
        sig = [r for r in rs if np.isfinite(r["q_par_exn"]) and r["q_par_exn"] < 0.05]
        cons = [r for r in sig if r["agree"] == nb]
        sig_h = [r for r in rs if np.isfinite(r["q_par_exh"]) and r["q_par_exh"] < 0.05]
        rv = np.array([abs(r["par_exn"]["r"]) for r in rs if np.isfinite(r["par_exn"]["r"])])
        best = max(rs, key=lambda r: abs(r["par_exn"]["t"]) if np.isfinite(r["par_exn"]["t"]) else 0)
        out.append([f, len(rs), len(sig), len(cons), len(sig_h), "%.3f" % np.median(rv) if len(rv) else "–",
                    "%s (r %+.3f, t %+.1f)" % (best["name"], best["par_exn"]["r"], best["par_exn"]["t"])])
    return md(["aile", "özellik", "q<0,05 (net−taban, ATR-kont.)", "…ve tüm bloklarda aynı işaret", "q<0,05 (hit−taban)", "medyan |r|", "en güçlü özellik"], out)


def quintile_profile(st: Study, scope: np.ndarray, names: list[str], labels) -> str:
    """Seçilen özellikler için beşlik (kuintil) profili: sınırlar TÜM kapsamdan; her kuintilde n, hit, net, net−taban ve blok netleri."""
    p = st.pop
    m0 = scope & st.valid
    rows = []
    for nm in names:
        if nm not in st.names:
            continue
        x = st.X[:, st.names.index(nm)].astype(float)
        v = x[m0 & np.isfinite(x)]
        if len(v) < 200:
            continue
        edges = np.quantile(v, [0.2, 0.4, 0.6, 0.8])
        q = np.where(np.isfinite(x), np.searchsorted(edges, x, side="right"), -1)
        for k in range(5):
            mk = m0 & (q == k)
            if mk.sum() < 20:
                continue
            blk = " / ".join("%+.2f" % np.mean(st.net[mk & (p.block == b)]) if (mk & (p.block == b)).sum() >= 10 else "–" for b in range(len(labels)))
            rows.append([nm, "K%d" % (k + 1), "%.3g" % (edges[k - 1] if k > 0 else np.min(v)), int(mk.sum()), fp(st.hit[mk].mean()), f2(st.net[mk].mean()),
                         f2(np.nanmean(st.ex_net[mk])), blk])
    return md(["özellik", "kuintil", "alt sınır", "n", "hit", "net", "net−taban", "blok net (" + " / ".join(l.split(" ")[0] for l in labels) + ")"], rows)


def tercile_table(st: Study, scope: np.ndarray, feat_names: list[str]) -> str:
    """ATR tersilleri içinde özelliğin üst yarısı − alt yarısı: Δhit (pp) ve Δ(net−taban) (puan)."""
    p = st.pop
    m0 = scope & st.valid
    stra, _ = K.terciles(np.where(m0, st.atr, np.nan))
    rows = []
    for nm in feat_names:
        if nm not in st.names:
            continue
        x = st.X[:, st.names.index(nm)].astype(float)
        xm = np.where(m0, x, np.nan)
        dh = K.strat_diff(xm, st.hit, stra, p.day)
        de = K.strat_diff(xm, st.ex_net, stra, p.day)
        dn = K.strat_diff(xm, st.net, stra, p.day)
        per_h = " / ".join("%+.1f" % (100 * dh["per"].get(k, np.nan)) for k in range(3))
        per_e = " / ".join("%+.2f" % de["per"].get(k, np.nan) for k in range(3))
        rows.append([nm, "%+.1f [t %+.1f]" % (100 * dh["diff"], dh["t"]), per_h, "%+.2f [t %+.1f]" % (dn["diff"], dn["t"]),
                     "%+.2f [t %+.1f]" % (de["diff"], de["t"]), per_e])
    return md(["özellik (üst yarı − alt yarı)", "Δhit pp (ATR-tersil içi)", "tersil 1/2/3 Δhit pp", "Δnet", "Δ(net−taban)", "tersil 1/2/3 Δ(net−taban)"], rows)


# ------------------------------------------------------------------------------------------------ A2. klasik fikirler
def idea_names(names: list[str]) -> list[str]:
    return [n for n in names if n.startswith("idea:")]


def classic_table(st: Study, scope: np.ndarray, blocks_labels) -> tuple[str, list[dict]]:
    p = st.pop
    nb = len(blocks_labels)
    res = []
    rows = []
    for nm in idea_names(st.names):
        x = st.X[:, st.names.index(nm)].astype(float)
        base = scope & st.valid & np.isfinite(x)
        keep = base & (x > 0.5)
        drop = base & (x <= 0.5)
        r = {"name": nm, "keep_frac": float(keep.sum() / max(base.sum(), 1))}
        per = []
        for b in range(nb):
            mb = p.block == b
            kb, db = keep & mb, drop & mb
            if kb.sum() < 20 or db.sum() < 20:
                per.append((float("nan"),) * 4)
                continue
            dex = st.ex_net[kb].mean() - np.nanmean(st.ex_net[db])
            dh = st.hit[kb].mean() - st.hit[db].mean()
            per.append((dex, dh, float(st.net[kb].mean()), float(np.nanmean(st.ex_net[kb]))))
        r["per"] = per
        s_all = summarize(st, keep)
        s_drop = summarize(st, drop)
        # tutulan − düşen (net−taban), küme SE: iki grubun SE'lerinin karekökü
        dd = float("nan"); se = float("nan")
        if s_all.get("n") and s_drop.get("n"):
            dd = s_all["ex"]["mean"] - s_drop["ex"]["mean"]
            se = float(np.hypot(s_all["ex"]["se"], s_drop["ex"]["se"]))
        r["diff"], r["se"], r["s_keep"], r["s_drop"] = dd, se, s_all, s_drop
        r["t"] = dd / se if se and np.isfinite(se) and se > 0 else float("nan")
        r["pass_all"] = all(np.isfinite(v[0]) and v[0] > 0 for v in per) and np.isfinite(dd) and dd - 1.96 * se > 0
        res.append(r)
    for r in res:
        sk, sd = r["s_keep"], r["s_drop"]
        if not sk.get("n"):
            continue
        rows.append([r["name"][5:], "%.0f%%" % (100 * r["keep_frac"]), sk["n"], fp(sk["hit"]), fp(sd.get("hit", np.nan)),
                     f2(sk["net"][0]), f2(sd["net"][0]) if sd.get("n") else "–", f2(sk["ex"]["mean"]),
                     "%s [t %+.1f]" % (f2(r["diff"]), r["t"]),
                     " / ".join(f2(v[0]) for v in r["per"]), " / ".join(f2(v[2]) for v in r["per"]),
                     "EVET" if r["pass_all"] else "hayır"])
    hdr = ["fikir (koşul sağlanınca al)", "tutulan pay", "n", "hit tutulan", "hit düşen", "net tutulan", "net düşen", "net−taban tutulan",
           "Δ(net−taban) tutulan−düşen", "blok Δ(net−taban)", "blok net (tutulan)", "her blokta + ve %95>0"]
    return md(hdr, rows), res


def idea_tercile_table(st: Study, scope: np.ndarray) -> str:
    """Klasik fikirler için ATR tersilleri İÇİNDE tutulan − düşen: Δhit (pp) ve Δ(net−taban) (puan)."""
    p = st.pop
    m0 = scope & st.valid
    stra, _ = K.terciles(np.where(m0, st.atr, np.nan))
    rows = []
    for nm in idea_names(st.names):
        x = st.X[:, st.names.index(nm)].astype(float)
        cells_h, cells_e, cells_n = [], [], []
        for k in range(3):
            mk = m0 & (stra == k) & np.isfinite(x)
            keep, drop = mk & (x > 0.5), mk & (x <= 0.5)
            if keep.sum() < 15 or drop.sum() < 15:
                cells_h.append("–"); cells_e.append("–"); cells_n.append("%d/%d" % (keep.sum(), drop.sum()))
                continue
            cells_h.append("%+.1f" % (100 * (st.hit[keep].mean() - st.hit[drop].mean())))
            cells_e.append("%+.2f" % (np.nanmean(st.ex_net[keep]) - np.nanmean(st.ex_net[drop])))
            cells_n.append("%d/%d" % (keep.sum(), drop.sum()))
        rows.append([nm[5:], " / ".join(cells_h), " / ".join(cells_e), " / ".join(cells_n)])
    return md(["fikir (tutulan − düşen)", "Δhit pp: ATR tersil 1 / 2 / 3", "Δ(net−taban): tersil 1 / 2 / 3", "n tutulan/düşen"], rows)


# ------------------------------------------------------------------------------------------------ A3. kural arama (blok 1 → diğerleri)
class RuleSearch:
    """Aday kural = (özellik, yön, eşik). Eşikler yalnız SEÇİM döneminin yüzdeliklerinden; sonra donmuş."""

    def __init__(self, st: Study, sel_mask: np.ndarray):
        self.st = st
        self.sel = sel_mask & st.valid
        self.cands = []        # (j, op, thr)
        X = st.X
        for j, nm in enumerate(st.names):
            if nm.startswith("idea:"):
                continue
            x = X[:, j].astype(float)
            v = x[self.sel & np.isfinite(x)]
            if len(v) < 200 or np.ptp(v) == 0:
                continue
            u = np.unique(v)
            if len(u) <= 2:
                self.cands.append((j, ">", float(u[0]) if len(u) == 1 else float(u[0]) + 1e-9))
                self.cands.append((j, "<=", float(u[0])))
                continue
            for q in Q_THR:
                thr = float(np.quantile(v, q))
                self.cands.append((j, ">", thr))
                self.cands.append((j, "<=", thr))

    def mask(self, cand) -> np.ndarray:
        j, op, thr = cand
        x = self.st.X[:, j].astype(float)
        with np.errstate(invalid="ignore"):
            return (x > thr) if op == ">" else (x <= thr)       # NaN → False

    def score_all(self, y: np.ndarray, min_n: int) -> list[tuple]:
        """Seçim döneminde her aday için (t, n, ort, j, op, thr). Skor: tutulanın ortalaması − seçim dönemi genel ortalaması, küme SE."""
        st = self.st
        base = self.sel & np.isfinite(y)
        mu = y[base].mean()
        inv = st.dinv
        ng = inv.max() + 1
        out = []
        for c in self.cands:
            k = self.mask(c) & base
            n = int(k.sum())
            if n < min_n or n > MAX_KEEP_FRAC * base.sum():
                continue
            d = y[k] - mu
            s = np.bincount(inv[k], weights=d, minlength=ng)
            se = np.sqrt((s ** 2).sum()) / n
            out.append((float(d.mean() / se) if se > 0 else 0.0, n, float(y[k].mean()), c))
        out.sort(key=lambda r: -r[0])
        return out


def pick_rules(rs: RuleSearch, scored: list[tuple], k: int, used_feats: set, max_jacc: float = 0.7) -> list[tuple]:
    chosen = []
    masks = []
    for t, n, mean, c in scored:
        if c[0] in used_feats:
            continue
        m = rs.mask(c) & rs.sel
        ok = True
        for m2 in masks:
            inter = (m & m2).sum()
            uni = (m | m2).sum()
            if uni and inter / uni > max_jacc:
                ok = False
                break
        if not ok:
            continue
        chosen.append((t, n, mean, c))
        masks.append(m)
        used_feats.add(c[0])
        if len(chosen) >= k:
            break
    return chosen


def rule_text(st: Study, c) -> str:
    j, op, thr = c
    return "%s %s %.4g" % (st.names[j], op, thr)


def eval_rule_table(st: Study, rules: list[tuple[str, np.ndarray]], blocks, labels, scope: np.ndarray) -> tuple[str, list[dict]]:
    p = st.pop
    days = block_days(p, blocks)
    rows = []
    out = []
    for name, rm in rules:
        for b, lab in list(enumerate(labels)) + [(-1, "OOS (seçim dışı tümü)")]:
            hide = (b == -1 and len(labels) == 2)          # 2 dilimde 'tümü OOS' = tek OOS dilimi (tekrar)
            if b >= 0:
                per = p.block == b
                d = days[b]
            else:
                per = np.zeros(p.n, dtype=bool)
                for bb in range(1, len(labels)):
                    per |= p.block == bb
                d = sum(days[1:])
            allm = scope & st.valid & per
            km = allm & rm
            sa, sk = summarize(st, allm, d), summarize(st, km, d)
            if not sk.get("n"):
                if not hide:
                    rows.append([name, lab, 0] + ["–"] * 8)
                continue
            # Δ(net−taban): tutulan − hepsi (aynı dönem); SE: tutulan SE'si (tutulan ⊂ hepsi → muhafazakâr değil, bilgi amaçlı)
            delta = sk["ex"]["mean"] - sa["ex"]["mean"]
            se = sk["ex"]["se"]
            if not hide:
                rows.append([name, lab, sk["n"], "%.1f" % sk["per_day"], fp(sk["hit"]), fp(sa["hit"]), f2(sk["net"][0]), f2(sa["net"][0]),
                             f2(sk["ex"]["mean"]), "%s [%s; %s]" % (f2(delta), f2(delta - 1.96 * se), f2(delta + 1.96 * se)),
                             "%.2f / %.2f" % (sk["atr"], sa["atr"])])
            out.append({"name": name, "block": b, "n": sk["n"], "per_day": sk["per_day"], "net": sk["net"][0], "net_all": sa["net"][0],
                        "ex": sk["ex"]["mean"], "delta": delta, "lo": delta - 1.96 * se, "hit": sk["hit"], "hit_all": sa["hit"]})
    hdr = ["kural", "dilim", "n", "gün/adet", "hit", "hit (hepsi)", "net", "net (hepsi)", "net−taban", "Δ(net−taban) vs hepsi [95]", "ATR% (tutulan/hepsi)"]
    return md(hdr, rows), out


def noise_diag(st: Study, rs: RuleSearch, oos: np.ndarray, y: np.ndarray, min_n: int, top: int = 50) -> dict:
    """Seçim döneminde en iyi `top` aday kuralın OOS Δ(y) ortalaması ve pozitif pay (ortalamaya dönüş / aşırı uyum tanısı)."""
    scored = rs.score_all(y, min_n)
    base_oos = oos & st.valid & np.isfinite(y)
    mu = y[base_oos].mean()
    d = []
    for t, n, mean, c in scored[:top]:
        k = rs.mask(c) & base_oos
        if k.sum() >= 30:
            d.append(y[k].mean() - mu)
    allv = []
    for t, n, mean, c in scored:
        k = rs.mask(c) & base_oos
        if k.sum() >= 30:
            allv.append(y[k].mean() - mu)
    d, allv = np.array(d), np.array(allv)
    return {"n_cand": len(scored), "top_mean_oos": float(d.mean()) if len(d) else float("nan"),
            "top_pos": float((d > 0).mean()) if len(d) else float("nan"), "all_mean_oos": float(allv.mean()) if len(allv) else float("nan"),
            "all_pos": float((allv > 0).mean()) if len(allv) else float("nan"), "top_sel_mean": float(np.mean([r[2] - 0 for r in scored[:top]])) if scored else float("nan")}


# ------------------------------------------------------------------------------------------------ ana
def run_pop(name: str, blocks, labels, log=print) -> tuple[str, dict]:
    st = Study(name, labels)
    p = st.pop
    nb = len(labels)
    lines = ["### %s" % {"ha": "Nüfus 1 — Hız Avcısı canlı-benzeri bölümler (90 gün)", "notif": "Nüfus 2 — push bildirimleri (17.09–17.10)"}[name]]
    lines.append("Olay %d, geçerli (pencere + ATR + hedef) %d; özellik sayısı %d (klasik-fikir sütunları dahil)." % (p.n, int(st.valid.sum()), len(st.names)))
    lines.append("\n#### Nüfus özeti (mevcut sinyal; taban = oynaklık-eşleşmiş rastgele)\n\n" + pop_table(st, blocks, labels))
    summary = {"name": name}
    scopes = [("tümü", st.valid)]
    if st.confirm.any():
        scopes.append(("teyit kuralı (yeni canlı)", st.valid & st.confirm))
    for sn, sm in scopes:
        t0 = time.time()
        rows = rank_features(st, sm)
        log("[%s/%s] sıralama %.0f sn (%d özellik)" % (name, sn, time.time() - t0, len(rows)))
        lines.append("\n#### A1. Özellik sıralaması — kapsam: %s (n=%d)\n" % (sn, int((sm & st.valid).sum())))
        lines.append("`r` = kısmi Spearman (ATR ve hedef/ATR sıralarının 1.+2. derece terimleri sabit; ham sütunda kontrol yok); `t` küme-dayanıklı (gün); "
                     "q = BH (özellikler arası). 'net−taban' = olay neti − eşleşmiş rastgele taban neti.\n")
        lines.append(rank_tables(rows, nb))
        lines.append("\nAile bazında özet (ATR-kontrollü):\n\n" + family_table(rows, nb))
        top = sorted(rows, key=lambda r: -abs(r["par_exn"]["t"]) if np.isfinite(r["par_exn"]["t"]) else 0)[:8]
        summary["top_" + sn] = [(r["name"], r["par_exn"]["r"], r["par_exn"]["t"], r["q_par_exn"], r["agree"]) for r in top]
        summary["nsig_" + sn] = (sum(1 for r in rows if r["q_par_exn"] < 0.05), sum(1 for r in rows if r["q_par_hit"] < 0.05),
                                 sum(1 for r in rows if r["q_raw_net"] < 0.05), len(rows))
        both = [r for r in rows if np.isfinite(r["q_par_hit"]) and r["q_par_hit"] < 0.05 and np.isfinite(r["q_par_exn"]) and r["q_par_exn"] < 0.05]
        summary["opp_" + sn] = (len(both), sum(1 for r in both if np.sign(r["par_hit"]["r"]) != np.sign(r["par_exn"]["r"])))
        summary["cons_" + sn] = sum(1 for r in rows if np.isfinite(r["q_par_exn"]) and r["q_par_exn"] < 0.05 and r["agree"] == nb)
        lines.append("\nATR tersilleri içinde en iyi 8 özellik (ATR-kontrollü net−taban sıralı):\n\n" + tercile_table(st, sm, [r["name"] for r in top]))
        lines.append("\nEn güçlü 3 özelliğin kuintil profili (kapsam: %s; mutlak net bir kuintilde > 0 oluyor mu?):\n\n" % sn + quintile_profile(st, sm, [r["name"] for r in top[:3]], labels))
    # A2 klasik fikirler
    lines.append("\n#### A2. Klasik fikirler (önceden belirlenmiş koşullar; eşik seçimi YOK)\n")
    ct_all, res_all = classic_table(st, st.valid, labels)
    lines.append("Kapsam: tümü\n\n" + ct_all)
    summary["classic"] = [(r["name"], r["pass_all"], r["diff"], r["t"]) for r in res_all]
    lines.append("\nATR tersilleri içinde klasik fikirler (kapsam: tümü; oynaklık etkisi ayrıştırılmış):\n\n" + idea_tercile_table(st, st.valid))
    if st.confirm.any():
        ct_c, res_c = classic_table(st, st.valid & st.confirm, labels)
        lines.append("\nKapsam: yeni teyit kuralını geçenler\n\n" + ct_c)
    # A3 kural arama
    lines.append("\n#### A3. Filtre kuralları — seçim: %s; sonra DOKUNULMADAN: %s\n" % (labels[0], ", ".join(labels[1:])))
    sel = st.blk(0)
    rs = RuleSearch(st, sel)
    min_n = max(150, int(0.1 * sel.sum()))
    sc_ex = rs.score_all(st.ex_net, min_n)
    sc_net = rs.score_all(st.net, min_n)
    used: set = set()
    r_ex = pick_rules(rs, sc_ex, 3, used)
    r_net = pick_rules(rs, sc_net, 3, used)
    log("[%s] aday kural %d; seçilen %d + %d" % (name, len(rs.cands), len(r_ex), len(r_net)))
    rules = []
    lines.append("Seçim dönemi: n=%d, aday kural %d (özellik × yön × 3 eşik). Hedef işlevi: (a) net−taban [oynaklık kontrollü], (b) ham net. "
                 "Her hedef için en iyi 3 FARKLI özellik (Jaccard ≤ 0,7).\n" % (int(sel.sum()), len(rs.cands)))
    for tag, rr in (("A", r_ex), ("N", r_net)):
        for i, (t, n, mean, c) in enumerate(rr):
            rules.append(("%s%d: %s" % (tag, i + 1, rule_text(st, c)), rs.mask(c)))
            lines.append("- %s%d: `%s` — seçim dönemi t=%.1f, n=%d, ort.=%+.2f" % (tag, i + 1, rule_text(st, c), t, n, mean))
    for scn, scm in scopes:
        tbl, ev_rules = eval_rule_table(st, rules, blocks, labels, scm)
        lines.append("\nKapsam: %s\n\n" % scn + tbl)
        summary["rules_" + scn] = ev_rules
    # gürültü tanısı
    oos = st.period_mask("oos")
    nd_ex = noise_diag(st, rs, oos, st.ex_net, min_n)
    nd_net = noise_diag(st, rs, oos, st.net, min_n)
    lines.append("\n**Aşırı uyum tanısı** (seçim döneminde en iyi 50 aday kuralın seçim dışı performansı; hepsi aynı yönde sistematik bir kenar olsaydı OOS ortalaması > 0 olurdu):\n\n"
                 + md(["hedef", "aday", "OOS: en iyi-50 ort. Δ", "en iyi-50 pozitif pay", "tüm adaylar ort. Δ", "tüm adaylar pozitif pay"],
                      [["net−taban", nd_ex["n_cand"], f2(nd_ex["top_mean_oos"]), fp(nd_ex["top_pos"]), f2(nd_ex["all_mean_oos"]), fp(nd_ex["all_pos"])],
                       ["ham net", nd_net["n_cand"], f2(nd_net["top_mean_oos"]), fp(nd_net["top_pos"]), f2(nd_net["all_mean_oos"]), fp(nd_net["all_pos"])]]))
    summary["noise_ex"], summary["noise_net"] = nd_ex, nd_net
    return "\n".join(lines), summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pop", default="ha,notif")
    args = ap.parse_args(argv)
    import pickle
    sections = []
    summ = {}
    for pop in args.pop.split(","):
        blocks = K.ha_blocks() if pop == "ha" else K.notif_blocks()
        labels = ["B1 (20 Tem–18 Ağu)", "B2 (19 Ağu–17 Eyl)", "B3 (18 Eyl–16 Eki)"] if pop == "ha" else ["seçim 17.09–09.10", "değerlendirme 10.10–17.10"]
        t0 = time.time()
        text, s = run_pop(pop, blocks, labels, log=lambda m: print(m, flush=True))
        sections.append(text)
        summ[pop] = s
        print("[%s] bitti %.0f sn" % (pop, time.time() - t0), flush=True)
    (K.OUT / "section_A.md").write_text("\n\n".join(sections), encoding="utf-8")
    pickle.dump(summ, open(K.OUT / "summary_A.pkl", "wb"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
