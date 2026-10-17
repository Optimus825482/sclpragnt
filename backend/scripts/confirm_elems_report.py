"""confirm_elems_study.py rapor üretici (Türkçe Markdown). Tüm sayılar events.pkl'den hesaplanır; yorum `work/confirm_elems/narrative_tr.md`
varsa en sona eklenir (sayılar elle yazılmaz, yorum yalnız okuma önerisidir)."""
from __future__ import annotations

import numpy as np

from app.rescan import confirm_elems as C
from scripts import confirm_elems_study as S
from scripts import policy7d_study as P

CAT_GROUPS = ("Kaynak (tekil)", "Kaynak çifti", "Tam kaynak kümesi", "Mod", "Başlık", "BTC rejim", "Ufuk", "Saat", "Hedef")


def _names(res_names) -> str:
    return " ∧ ".join(res_names)


CONF_GROUPS = ("Kaynak (tekil)", "Kaynak çifti", "Tam kaynak kümesi", "Teyit sayısı", "Mod", "Başlık", "BTC rejim")


def pick_worst(res: dict, EL: dict, min_n: int, k: int = 2) -> list[str]:
    """Örneklem-içi ≥2 kümesinde TEYİT ögeleri (kaynak/çift/tam küme/teyit sayısı/mod/başlık/rejim) arasında başarısızlıkta en çok
    öne çıkan (hit lift'i en düşük, n ≥ min_n, BH q < 0.05) k öge — farklı konjonksiyon gruplarından."""
    cand = []
    for nm, r in res.items():
        if r.get("n", 0) < min_n or EL["el"][nm]["grp"] not in CONF_GROUPS or "lift_h" not in r:
            continue
        lf = r["lift_h"]["lift"]
        if np.isfinite(lf) and np.isfinite(r["qA"]) and r["qA"] < 0.05 and lf < 1.0:
            cand.append((lf, nm))
    cand.sort()
    out, used = [], set()
    for lf, nm in cand:
        g = EL["el"][nm]["cgrp"]
        if g in used:
            continue
        used.add(g)
        out.append(nm)
        if len(out) == k:
            break
    return out


def pick_best_single(res: dict, EL: dict, min_n: int) -> str | None:
    """Örneklem-içi ≥2 kümesinde teyit ögeleri arasında hit lift'i en yüksek (n ≥ min_n, BH q < 0.05) tek öge."""
    cand = []
    for nm, r in res.items():
        if r.get("n", 0) < min_n or EL["el"][nm]["grp"] not in CONF_GROUPS or "lift_h" not in r:
            continue
        lf = r["lift_h"]["lift"]
        if np.isfinite(lf) and np.isfinite(r["qA"]) and r["qA"] < 0.05 and lf > 1.0:
            cand.append((-lf, nm))
    cand.sort()
    return cand[0][1] if cand else None


def permutation_null(elems, group_of, d, day, t, n_perm, min_n, seed=5):
    """Örneklem-içi arama boş-dağılımı: `d` değerleri AYNI GÜN içinde karıştırılır (gün etkisi korunur), arama tekrarlanır;
    her seferinde bulunan en iyi (kararlı) LCB kaydedilir (bulunamazsa 0)."""
    rng = np.random.default_rng(seed)
    idx = np.where(np.isfinite(d))[0]
    days = day[idx]
    groups = [idx[days == g] for g in np.unique(days)]
    best = []
    for _ in range(n_perm):
        dp = np.full(len(d), np.nan)
        for gi in groups:
            dp[gi] = d[rng.permutation(gi)]
        res = C.search_conjunctions(elems, group_of, dp, day, t, min_n=min_n, max_k=3, top=1)
        best.append(res[0]["lcb"] if res else 0.0)
    return np.array(best)


def render(E: dict, args, log=print) -> str:
    t = E["t"]
    ok = E["valid"]
    is_m = t < S.SPLIT
    oos_m = ~is_m
    oos_db = oos_m & (E["src"] == "db")
    days_is = (S.SPLIT - P.P_START) / 86400.0
    days_oos = (E["t_hi"] - S.SPLIT) / 86400.0
    days_oosdb = (P.PROD_START - S.SPLIT) / 86400.0
    for k_ in ("net1", "net2"):          # taban: oynaklık-eşleşmiş varsa o, yoksa sembol/saat rastgele tabanı (eşleşik tabanı olmayan olaylar çok oynak)
        E["beff" + k_[-1]] = np.where(np.isfinite(E["b_" + k_]), E["b_" + k_], E["rb_" + k_])
    EL = S.build_elements(E, is_m)
    el = EL["el"]
    ns = np.array([len(s) for s in E["srcs"]])
    two = ns >= 2
    d1 = E["net1"] - E["beff1"]
    out = []
    w = out.append

    # ---------------------------------------------------------------- 0. veri
    n_ev = len(t)
    w("# Teyit ögeleri analizi: ≥ 2 teyit kuralı için hangi öge ayırt ediyor? (2026-10-17, çevrimdışı araştırma)\n")
    w("Üretim: `backend/scripts/confirm_elems_study.py` (+ `confirm_elems_report.py`, `confirm_elems_cache.py`, saf yardımcılar `app/rescan/confirm_elems.py`, "
      "test `tests/test_confirm_elems.py`). Canlı koda bağlanmaz. Önceki çalışma: `docs/BILDIRIM_POLITIKASI_7G_2026-10-17.md`.\n")
    w("## 0. Veri ve yöntem\n")
    w("- Evren: yalnız **push** (panel kaldırıldı), `sources` alanı dolu, ufuk 5/15/30 dk, `global_lead_lag` hariç. Kaynak bilgisi NULL olan satırlar "
      "(`llm_ikinci_goz` modu dahil) kaynak ögesi taşımadığı için evrende YOK. DB 17.09 15:00 → 15.10 22:30 + üretim TSV (83 satır, 15.10 22:30 → 17.10).")
    w("- Olay sayısı: %d (geçerli %d: 60 dk mum penceresi tam); örneklem-içi (17.09 → 09.10): %d; değerlendirme (10.10 → 17.10 14:23): %d "
      "(DB %d + üretim %d)." % (n_ev, int(ok.sum()), int((ok & is_m).sum()), int((ok & oos_m).sum()), int((ok & oos_db).sum()),
                               int((ok & oos_m & (E["src"] == "prod")).sum())))
    p7 = ok & oos_m & two
    w("- Önceki çalışmayla tutarlılık (10.10 → 17.10, ≥2 kaynak, push): n=%d, hit %s, net B1 %s (önceki raporda n=151, %%17,9, −0,46)." % (
        int(p7.sum()), S.f_hit(int(E["hit_h"][p7].sum()), int(p7.sum())), S.f_ci(*C.cluster_bootstrap_mean(E["net1"][p7], E["day"][p7], 500, 1))))
    w("- **Mum önbelleği:** `historical_candles` canlı uygulamanın `retention_loop` (6 saatte bir, 21 gün) tarafından budanıyor; 09.26'dan eski mumlar "
      "DB'den silindi. Eksik aralık Binance genel kline API'sinden yerel önbelleğe (`work/confirm_elems/cache`, DB'ye yazılmadan) yeniden çekildi. "
      "Bu yüzden önceki raporun mum kaynağıyla aynı veri, ama DB'de artık yok.")
    w("- **Başarı tanımı A (kullanıcı):** hedefe dokunuş — ufuk içinde (`hit`) ve 60 dk içinde (`hit 60`); hedef = bildirimdeki eski hedef. "
      "**Başarı tanımı B (gerçekçi net):** giriş = sinyal + 60 sn sonraki ilk 1 dk açılış × (1+%0,15); TP = bildirim hedefi, SL %3, zaman stopu = ufuk "
      "(B1) ya da 60 dk (B2); bacak başına %0,1125 ücret; stop kaymalı. 'kazanan' = net > 0. 'Δ' = olay başına (net − AYNI olayın tabanının ortalama neti) eşleştirilmiş farkı; %95 aralık gün-kümeli. Taban: aynı sembol, aynı saat dilimi, "
      "başka günler, tüm olaylardan ≥2 sa uzak, aynı hedef/çıkış; 'oynaklık-eşleşmiş' tabanda ek olarak son 30 dk aralığı ±25% eşleşen en yakın ≤20 an seçilir.")
    cov = np.isfinite(E["b_net1"][ok])
    w("- **Kapsama sınırı:** olayların yalnız %d%% (%d/%d) oynaklık-eşleşmiş taban bulabiliyor; eşleşmeyenler çok oynak anlar (medyan ATR %%%.2f vs %%%.2f), "
      "sakin günlerde karşılığı yok. Bu yüzden ana 'Δ net − taban' sütununda taban = oynaklık-eşleşmiş (varsa), yoksa sembol/saat rastgele tabanıdır "
      "(tüm olaylar kapsanır); 'yalnız oyn.-eşl. tabanı olan olaylar' sütunu yalnız eşleşebilen alt kümeyi gösterir." % (
          100 * int(cov.sum()) // max(1, int(ok.sum())), int(cov.sum()), int(ok.sum()),
          float(np.nanmedian(E["atr"][ok][~cov])), float(np.nanmedian(E["atr"][ok][cov]))))
    w("- lift = P(öge | başarı) / P(öge | başarısız). q = Benjamini-Hochberg düzeltmeli Fisher p (tablo içi tüm ögeler üzerinden). "
      "Hit için Wilson, net için gün-kümeli bootstrap (500) %95 aralığı. Mum ögeleri (RSI/MFI/taker/zirve/pompa/ATR) ve skor için kova eşikleri YALNIZ "
      "örneklem-içi tersiyllerden.")
    w("- Not: üretim satırlarında `mod`, `başlık` ve `skor` yok; bu ögeler yalnız DB satırlarında ölçülür (n sütunu bunu yansıtır). "
      "'⚠ BTC REJİM' rozeti DB başlıklarında hiç saklanmamış (0 satır) → rejim, BTC 1s EMA200 (kalkan) ile yeniden hesaplandı.\n")

    # ---------------------------------------------------------------- 1. öge tabloları (tüm veri)
    scope_all = ok.copy()
    tA, tB, res_all = S.element_tables(E, EL, scope_all, is_m, oos_m, "tüm")
    w("## 1. Tüm bildirimler (push, kaynaklı) — tek öge tabloları, 17.09 → 17.10\n")
    ref = ok & scope_all
    w("Referans (tüm evren): n=%d, hit %s, hit60 %s, net B1 %s, Δ rastgele %s.\n" % (
        int(ref.sum()), S.f_hit(int(E["hit_h"][ref].sum()), int(ref.sum())), S.f_hit(int(E["hit60"][ref].sum()), int(ref.sum())),
        S.f_ci(*C.cluster_bootstrap_mean(E["net1"][ref], E["day"][ref], 500, 1)),
        S.f_diff(C.paired_diff_stats(E["net1"][ref], E["beff1"][ref], E["day"][ref]))))
    w("### 1A. Tanım A: hedefe dokunuş\n")
    w(tA)
    w("### 1B. Tanım B: gerçekçi net PnL (B1)\n")
    w(tB)

    # ---------------------------------------------------------------- 2. ≥2 alt kümesi
    scope_two = ok & two
    tA2, tB2, res_two = S.element_tables(E, EL, scope_two, is_m, oos_m, "≥2")
    w("## 2. Yalnız ≥ 2 kaynaklı bildirimler — tek öge tabloları, 17.09 → 17.10\n")
    ref = scope_two
    w("Referans (≥2 kaynak): n=%d, hit %s, hit60 %s, net B1 %s, Δ rastgele %s.\n" % (
        int(ref.sum()), S.f_hit(int(E["hit_h"][ref].sum()), int(ref.sum())), S.f_hit(int(E["hit60"][ref].sum()), int(ref.sum())),
        S.f_ci(*C.cluster_bootstrap_mean(E["net1"][ref], E["day"][ref], 500, 1)),
        S.f_diff(C.paired_diff_stats(E["net1"][ref], E["beff1"][ref], E["day"][ref]))))
    w("### 2A. Tanım A: hedefe dokunuş\n")
    w(tA2)
    w("### 2B. Tanım B: gerçekçi net PnL (B1)\n")
    w(tB2)

    w("### 2C. Çoklu karşılaştırma düzeltmesi sonrası güçlü ayrışanlar (≥2 kaynak, q < 0.01 en az bir tanımda, n ≥ 40)\n")
    rows = []
    for nm, r in res_two.items():
        if r.get("n", 0) < 40 or "lift_h" not in r:
            continue
        if (np.isfinite(r["qA"]) and r["qA"] < 0.01) or (np.isfinite(r["qB"]) and r["qB"] < 0.01):
            rows.append([nm, r["n"], "%.2f" % r["lift_h"]["lift"], "%.3f" % r["qA"], "%.2f" % r["lift_w"]["lift"], "%.3f" % r["qB"],
                         S.f_diff(r["d1"])])
    rows.sort(key=lambda x: -float(x[2]))
    w(S.md(["öge", "n", "lift (hit, ufuk)", "q", "lift (net>0)", "q", "Δ net − taban [95]"], rows))
    w("Uyarı: aynı sembolün art arda bildirimleri bağımsız değildir (Fisher p'leri bu yüzden iyimser); net/Δ aralıkları gün-kümelidir.\n")

    # 2D. oynaklık kontrolü: teyit ögelerinin hit lift'i ATR tersiyli içinde de sürüyor mu?
    atr_el = [nm for nm in el if nm.startswith("ATR14(5m)")]
    atr_el.sort(key=lambda x: 0 if "düşük" in x else (1 if "orta" in x else 2))
    ctrl = ["kaynak: Hız", "çift: Hız + Yükseliş eğilimi", "tam küme: Sıçrama+Erken uyarı", "tam küme: Sıçrama+Erken uyarı+Yükseliş eğilimi",
            "teyit sayısı = 4", "mod: trend_devam", "mod: unified", "skor yüksek"]
    rows = []
    for nm in el:
        if not any(nm.startswith(c) for c in ctrl):
            continue
        r_ = [nm]
        for an in atr_el:
            m_ = scope_two & el[nm]["m"] & el[an]["m"]
            nn = int(m_.sum())
            r_.append("%s; net %s" % (S.f_hit(int(E["hit_h"][m_].sum()), nn), ("%+.2f" % float(E["net1"][m_].mean())) if nn else "–") if nn else "–")
        rows.append(r_)
    w("### 2D. Oynaklık kontrolü (≥2 kaynak): aynı ATR tersiyli içinde hit ve ortalama net\n")
    w(S.md(["öge"] + [x.replace("ATR14(5m) % ", "ATR ") for x in atr_el], rows))

    # ---------------------------------------------------------------- 3. kural seçimi (yalnız örneklem-içi)
    w("## 3. Aday kural seçimi — YALNIZ örneklem-içi (17.09 → 09.10)\n")
    sc_is_two = scope_two & is_m
    _, _, res_two_is = S.element_tables(E, EL, sc_is_two, is_m, oos_m, "≥2 IS")
    worst = pick_worst(res_two_is, EL, 50)
    best1 = pick_best_single(res_two_is, EL, 50)
    w("Örneklem-içi ≥2 kaynak alt kümesinde başarısızlıkta en çok öne çıkan 2 teyit ögesi (hit lift'i en düşük, n ≥ 50, q < 0.05, farklı gruplardan) → R3'te dışlanır: %s." % (
        "; ".join("%s (n=%d, hit lift %.2f, hit %s)" % (nm, res_two_is[nm]["n"], res_two_is[nm]["lift_h"]["lift"], S.f_hit(*res_two_is[nm]["hit_h"])) for nm in worst) or "yok"))
    w("Başarıda en çok öne çıkan tek teyit ögesi (hit lift'i en yüksek, n ≥ 50, q < 0.05) → R8'in ek şartı: %s.\n" % (
        ("%s (n=%d, hit lift %.2f, hit %s)" % (best1, res_two_is[best1]["n"], res_two_is[best1]["lift_h"]["lift"], S.f_hit(*res_two_is[best1]["hit_h"]))) if best1 else "yok"))
    elems = {nm: e["m"] for nm, e in el.items()}
    group_of = {nm: e["cgrp"] for nm, e in el.items()}
    d_two = np.where(sc_is_two, d1, np.nan)
    d_all = np.where(ok & is_m, d1, np.nan)
    best_two = C.search_conjunctions(elems, group_of, d_two, E["day"], t, min_n=args.min_n, max_k=3, top=8)
    best_all = C.search_conjunctions(elems, group_of, d_all, E["day"], t, min_n=args.min_n, max_k=3, top=8)

    def conj_table(res, title):
        rows = [[_names(r["names"]), r["n"], "%+.2f" % r["mean"], "%+.2f" % r["lcb"]] for r in res]
        return "**%s**\n\n%s" % (title, S.md(["birleşim (VE)", "n (IS)", "Δ ort. (net − taban)", "Δ %95 alt sınır (gün-kümeli)"], rows) if rows else "kararlı birleşim bulunamadı\n")
    w(conj_table(best_two, "≥2 kaynak alt kümesinde en iyi 2–3 ögeli birleşimler (örneklem-içi, n ≥ %d, her iki zaman yarısında Δ>0, alt sınıra göre)" % args.min_n))
    w(conj_table(best_all, "Tüm push evreninde en iyi 2–3 ögeli birleşimler (aynı koşullar)"))
    nulls = {}
    if args.perm > 0:
        for key, d_, res_ in (("two", d_two, best_two), ("all", d_all, best_all)):
            nl = permutation_null(elems, group_of, d_, E["day"], t, args.perm, args.min_n)
            nulls[key] = nl
            act = res_[0]["lcb"] if res_ else float("nan")
            w("Boş-dağılım (%s, %d permütasyon: Δ aynı gün içinde karıştırıldı, arama tekrarlandı): bulunan en iyi alt sınır medyan %+.2f, %%95 %+.2f, maks %+.2f; "
              "gerçek en iyi %+.2f → permütasyonların %d/%d'si gerçeği geçti.\n" % (
                  "≥2 kaynak" if key == "two" else "tüm push", args.perm, float(np.median(nl)), float(np.quantile(nl, 0.95)), float(nl.max()), act,
                  int((nl >= act).sum()), args.perm))
    pump_med = float(np.nanmedian(E["pump30"][ok & is_m]))
    w("Önceki 30 dk getiri (pompa) örneklem-içi medyanı: %.2f%% (öneri kuralı bu eşiği kullanır). Tersiyl eşikleri: %s.\n" % (
        pump_med, "; ".join("%s: ≤%.3g / >%.3g" % (lab, *EL["edges"][k]) for k, lab in S.FEATS)))

    # ---------------------------------------------------------------- 4. kural tablosu
    m_trend = (E["mode"] == "trend_devam") & ok
    pump = E["pump30"]
    low_pump = np.isfinite(pump) & (pump < pump_med)
    rules = [("R0 referans: tüm push (kaynaklı)", ok.copy()),
             ("R1 ≥2 kaynak", two & ok),
             ("R2 ≥2 kaynak ∧ mod=trend_devam", two & m_trend),
             ("R3 ≥2 kaynak, en kötü ögeler hariç [%s]" % "; ".join(worst), two & ok & ~np.any([el[x]["m"] for x in worst], axis=0) if worst else two & ok),
             ("R4 ≥2 kaynak ∧ [%s]" % (_names(best_two[0]["names"]) if best_two else "yok"),
              (two & ok & np.all([el[x]["m"] for x in best_two[0]["names"]], axis=0)) if best_two else np.zeros(len(t), dtype=bool)),
             ("R5 tüm push ∧ [%s]" % (_names(best_all[0]["names"]) if best_all else "yok"),
              (ok & np.all([el[x]["m"] for x in best_all[0]["names"]], axis=0)) if best_all else np.zeros(len(t), dtype=bool)),
             ("R6 yalnız mod=trend_devam", m_trend),
             ("R7 öneri: (≥2 kaynak ∨ trend_devam) ∧ pompa30 < IS medyanı", ((two & ok) | m_trend) & low_pump & ok),
             ("R8 ≥2 kaynak ∧ [%s]" % (best1 or "yok"), (two & ok & el[best1]["m"]) if best1 else np.zeros(len(t), dtype=bool))]
    periods = [("örneklem-içi 17.09–09.10", is_m, days_is), ("değerlendirme-DB 10.10–15.10", oos_db, days_oosdb),
               ("değerlendirme-tümü 10.10–17.10 (+üretim)", oos_m, days_oos)]
    rows = []
    for nm, mk in rules:
        rows += S.rule_rows(nm, E, mk, periods)
    w("## 4. Aday kurallar: örneklem-içi vs dokunulmamış değerlendirme\n")
    w("Kurallar yalnız 17.09 → 09.10 verisiyle tanımlandı; 10.10 → 17.10'da DOKUNULMADAN ölçüldü. Mod/başlık/skor üretim satırlarında bilinmediği için "
      "'mod=trend_devam' içeren kurallarda üretim satırları 'trend_devam değil' sayılır (bu kurallarda 'değerlendirme-DB' dönemi esas alınmalı). "
      "'rastgele hit' = oynaklık-eşleşmiş tabanın aynı hedefe dokunuş oranı. Son sütun: n/gün × ort. net = bu bildirimlere 1 birim girilseydi günlük toplam % puan.\n")
    hdr = ["Kural", "Dönem", "n", "n/gün", "hit (ufuk) [Wilson95]", "hit 60 dk", "rastgele hit (oyn.-eşl. / sembol-saat)", "net B1 [bootstrap95]",
           "Δ net − taban [95]", "Δ yalnız oyn.-eşl. tabanı olan olaylar", "net B2 (60 dk stop) / iyimser kayma", "toplam net/gün"]
    w(S.md(hdr, rows))

    # 4b. duyarlılık: daha küçük n eşiğiyle (min_n=50) bulunan en iyi birleşim
    sens = []
    for lab, scope_ in (("≥2 kaynak", two), ("tüm push", np.ones(len(t), dtype=bool))):
        dd = np.where(scope_ & ok & is_m, d1, np.nan)
        res_ = C.search_conjunctions(elems, group_of, dd, E["day"], t, min_n=50, max_k=3, top=1)
        if res_:
            mk = scope_ & ok & np.all([el[x]["m"] for x in res_[0]["names"]], axis=0)
            sens += S.rule_rows("[%s, min_n=50] %s" % (lab, _names(res_[0]["names"])), E, mk, periods)
    w("### 4b. Duyarlılık: n ≥ 50 eşiğiyle bulunan en iyi birleşimin değerlendirmesi (aday sayısına dahil değil)\n")
    w(S.md(hdr, sens) if sens else "bulunamadı\n")

    # 4c. haftalık kararlılık
    wk_rows = []
    wk_rules = [r_ for r_ in rules if r_[0].split()[0] in ("R1", "R2", "R3", "R6", "R7", "R8")]
    for nm, mk in wk_rules:
        for lab, lo, hi in reversed(P.WEEKS):
            per = (t >= lo) & (t < hi)
            days = (min(hi, E["t_hi"]) - max(lo, P.P_START)) / 86400.0
            r = S.eval_rule(E, mk, per, days)
            if not r["n"]:
                wk_rows.append([nm, lab, 0, "–", "–", "–", "–"])
                continue
            wk_rows.append([nm, lab, r["n"], "%.1f" % r["per_day"], S.f_hit(*r["hit_h"]), S.f_ci(*r["net1"]), S.f_diff(r["d1"])])
    w("### 4c. Haftalık kararlılık (aynı kurallar, hafta hafta)\n")
    w(S.md(["Kural", "Hafta", "n", "n/gün", "hit (ufuk)", "net B1 [bootstrap95]", "Δ net − taban [95]"], wk_rows))

    # ---------------------------------------------------------------- 5. özet verdict (otomatik)
    w("## 5. Otomatik özet (değerlendirme-tümü dönemi)\n")
    vr = []
    for nm, mk in rules:
        r = S.eval_rule(E, mk, oos_m, days_oos)
        ri = S.eval_rule(E, mk, is_m, days_is)
        if not r["n"]:
            continue
        pos = "net POZİTİF (alt sınır > 0)" if r["net1"][1] > 0 else ("net negatif (üst sınır < 0)" if r["net1"][2] < 0 else "net belirsiz (aralık 0'ı içeriyor)")
        beats = "rastgeleyi geçiyor (Δ alt sınır > 0)" if r["d1"]["lo"] > 0 else ("rastgeleden kötü" if r["d1"]["hi"] < 0 else "rastgeleden ayrışmıyor")
        vr.append("- %s: n/gün %.1f, net %s → %s; %s. Örneklem-içi net %s." % (nm, r["per_day"], S.f_ci(*r["net1"]), pos, beats,
                                                                         S.f_ci(*ri["net1"]) if ri["n"] else "–"))
    w("\n".join(vr) + "\n")

    import pathlib
    nf = pathlib.Path(S.OUT / "narrative_tr.md")
    if nf.exists():
        w("\n" + nf.read_text(encoding="utf-8"))
    return "\n".join(out)
