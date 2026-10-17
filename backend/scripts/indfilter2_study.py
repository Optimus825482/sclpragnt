"""İndikatör filtresi v2 — YENİ kütüphane özellikleri Hız Avcısı (HA) sinyalini filtreliyor mu? (2026-10-17, çevrimdışı; canlı koda BAĞLANMAZ)

`indfilter_study.py` yöntemini YENİDEN KULLANIR: Study (net / hit / eşleşmiş taban), kısmi Spearman (ATR + hedef/ATR kontrollü, gün-küme-dayanıklı t), BH q,
kural arama (B1'de seç, B2/B3'te DOKUNMADAN değerlendir) ve aşırı uyum tanısı. Özellik matrisi: work/indfilter/feats2_ha.npz (indfilter2_feats.py).

Çıktı: work/indearly2/filter2.pkl (+ filter2.md ham tablolar).
Kullanım (backend/): python scripts/indfilter2_study.py
"""
from __future__ import annotations

import pickle
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.rescan import indicators_ext2 as I2  # noqa: E402
from scripts import indfilter_common as K  # noqa: E402
from scripts import indfilter_study as S  # noqa: E402
from scripts.indearly2_study import SIGNALS  # noqa: E402

OUTD = Path(__file__).resolve().parents[1] / "work" / "indearly2"
LABELS = ["B1 (20 Tem–18 Ağu)", "B2 (19 Ağu–17 Eyl)", "B3 (18 Eyl–16 Eki)"]


def load_new(st: S.Study) -> None:
    z = np.load(K.OUT / "feats2_ha.npz", allow_pickle=False)
    X = z["X"].astype(np.float32)
    X[~np.isfinite(X)] = np.nan
    st.names = [str(s) for s in z["names"]]
    st.X = X


def fam_of(nm: str) -> str:
    return I2.FAMILY.get(nm.split(".", 1)[1], "?")


def block_stats(st: S.Study, keep: np.ndarray, blocks) -> list[dict]:
    """Kural tutulan alt kümesi için blok bazında: n, net, net−taban, ve TÜM olaylara göre Δ (net ve net−taban)."""
    days = S.block_days(st.pop, blocks)
    out = []
    for b in range(len(blocks)):
        per = st.pop.block == b
        allm = st.valid & per
        km = allm & keep
        sa, sk = S.summarize(st, allm, days[b]), S.summarize(st, km, days[b])
        if not sk.get("n"):
            out.append({"block": b, "n": 0})
            continue
        out.append({"block": b, "n": sk["n"], "per_day": sk["per_day"], "net": sk["net"][0], "net_all": sa["net"][0], "ex": sk["ex"]["mean"], "ex_all": sa["ex"]["mean"],
                    "d_net": sk["net"][0] - sa["net"][0], "d_ex": sk["ex"]["mean"] - sa["ex"]["mean"], "se_ex": sk["ex"]["se"],
                    "hit": sk["hit"], "hit_all": sa["hit"], "n_all": sa["n"]})
    return out


def main() -> int:
    t0 = time.time()
    I2.feature_names("5m")                      # FAMILY sözlüğünü doldurur
    blocks = K.ha_blocks()
    st = S.Study("ha", LABELS)
    n_old = len(st.names)
    load_new(st)
    p = st.pop
    print("[filter2] HA olay %d, geçerli %d; yeni özellik %d (eski %d)" % (p.n, int(st.valid.sum()), len(st.names), n_old), flush=True)
    res = {"names": st.names, "n_events": int(p.n), "n_valid": int(st.valid.sum()), "labels": LABELS}
    days = S.block_days(p, blocks)
    res["pop"] = {"all": block_stats(st, np.ones(p.n, bool), blocks)}
    # --- 1. sıralama (kısmi Spearman, ATR-kontrollü net−taban; BH q)
    rows = S.rank_features(st, st.valid)
    for r in rows:
        r["family"] = fam_of(r["name"])
    res["rank"] = rows
    print("[filter2] sıralama %d özellik (%.0f sn)" % (len(rows), time.time() - t0), flush=True)
    for key in ("par_exn", "par_net", "par_hit", "raw_net"):
        k5 = sum(1 for r in rows if np.isfinite(r["q_" + key]) and r["q_" + key] < 0.05)
        print("   q<0,05 %s: %d / %d" % (key, k5, len(rows)), flush=True)
    # --- 2. önceden belirlenmiş sinyal bayrakları (+ son-k-bar sürümleri) HA süzgeci olarak
    cand_flags = []
    base = {v[0] for v in SIGNALS.values()}
    for nm in st.names:
        b = nm.split(".x2.")[-1]
        if nm in base or any(nm == bb + "" for bb in base) or any(b == bb.split(".x2.")[-1] + suf for bb in base for suf in ("_r3", "_r6", "_r12")):
            cand_flags.append(nm)
    flag_rows = []
    for nm in cand_flags:
        j = st.names.index(nm)
        x = st.X[:, j].astype(float)
        keep = np.nan_to_num(x, nan=0.0) == 1.0
        bs = block_stats(st, keep, blocks)
        flag_rows.append({"name": nm, "share": float(keep[st.valid].mean()), "blocks": bs})
    res["flags"] = flag_rows
    # --- 3. kural arama: B1'de seç, B2/B3'te DOKUNMADAN (hedef: net−taban ve ham net)
    sel = st.blk(0)
    rs = S.RuleSearch(st, sel)
    min_n = max(150, int(0.1 * sel.sum()))
    sc_ex = rs.score_all(st.ex_net, min_n)
    sc_net = rs.score_all(st.net, min_n)
    used: set = set()
    r_ex = S.pick_rules(rs, sc_ex, 5, used)
    r_net = S.pick_rules(rs, sc_net, 5, used)
    rules = []
    for tag, rr in (("A", r_ex), ("N", r_net)):
        for i, (t, n, mean, c) in enumerate(rr):
            keep = rs.mask(c)
            rules.append({"id": "%s%d" % (tag, i + 1), "text": S.rule_text(st, c), "sel_t": t, "sel_n": n, "sel_mean": mean, "blocks": block_stats(st, keep, blocks)})
    res["rules"] = rules
    oos = st.period_mask("oos")
    res["noise_ex"] = S.noise_diag(st, rs, oos, st.ex_net, min_n)
    res["noise_net"] = S.noise_diag(st, rs, oos, st.net, min_n)
    # tüm aday kurallar için: B1'de skor>0 olup B2 ve B3'te de ham net ortalamasını (tüm olay ortalamasının) üzerine çıkaranların payı
    allc = []
    for t, n, mean, c in sc_net[:300]:
        keep = rs.mask(c)
        bl = [block_stats(st, keep, blocks)[b] for b in range(3)]
        if all(x.get("n", 0) >= 30 for x in bl):
            allc.append({"rule": S.rule_text(st, c), "sel_t": t, "d_net": [x["d_net"] for x in bl], "net": [x["net"] for x in bl], "n": [x["n"] for x in bl], "d_ex": [x["d_ex"] for x in bl]})
    res["top_rules_all_blocks"] = allc
    res["n_cand"] = len(rs.cands)
    pickle.dump(res, open(OUTD / "filter2.pkl", "wb"))
    print("[filter2] bitti (%.0f sn); kural adayı %d" % (time.time() - t0, len(rs.cands)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
