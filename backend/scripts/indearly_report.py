"""Erken uyarı çalışması — rapor üretimi (Türkçe Markdown) (2026-10-17, çevrimdışı)."""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np

from app.rescan import indicators_ext as I
from scripts import indearly_study as S1
from scripts.pattern90_study import fmt_t

BLOCKS = [("train", "EĞİTİM (2–17 Eki, fold B)"), ("test", "TEST (29 Tem–1 Eki, fold B)"), ("blk1", "Blok1 (19 Tem–17 Ağu)"),
          ("blk2", "Blok2 (18 Ağu–16 Eyl)"), ("blk3o", "Blok3 dışı (17 Eyl–1 Eki)")]
OOS = ["test", "blk1", "blk2", "blk3o"]


def f(x, nd=2, plus=False):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return (f"{x:+.{nd}f}" if plus else f"{x:.{nd}f}").replace(".", ",")


def pc(x, nd=1):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{100 * x:.{nd}f}%".replace(".", ",")


def pp(x, se=None, nd=1):
    if x is None:
        return "—"
    s = f"{100 * x:+.{nd}f}"
    if se is not None:
        s += f" ±{196 * se:.{nd}f}"
    return (s + " pp").replace(".", ",")


def tstr(st):
    if not st or "mean" not in st:
        return "—"
    return f"{st['mean']:+.2f} (t {f(st['t'], 1)})".replace(".", ",")


def qf(q):
    return "<0,001" if q < 0.001 else f"{q:.3f}".replace(".", ",")


def tr(x, nd=2):
    return f(x, nd).replace(".", ",") if x is not None else "—"


# ------------------------------------------------------------------------------------------------ tablolar
def rank_table(rank_recs, ctrl, topn=25) -> str:
    rows = rank_recs[:topn]
    out = ["| # | özellik | aile | AUC | d | q (BH) | FWER p | AUC blok1 / blok2 / blok3 | blok işareti | AUC artık (dip-kontrollü) |", "|---|---|---|---|---|---|---|---|---|---|"]
    for k, r in enumerate(rows, 1):
        sg = [np.sign(r[f"auc_blk{b}"] - 0.5) for b in (1, 2, 3)]
        cons = "3/3 aynı" if abs(sum(sg)) == 3 else "tutarsız"
        out.append(f"| {k} | `{r['feature']}` | {r['family']} | {tr(r['auc'], 3)} | {tr(r['d'])} | {qf(r['q'])} | {qf(r['p_fwer'])} | "
                   f"{tr(r['auc_blk1'], 3)} / {tr(r['auc_blk2'], 3)} / {tr(r['auc_blk3'], 3)} | {cons} | {tr(r['auc_resid'], 3) if r['auc_resid'] is not None else '—'} |")
    return "\n".join(out)


def family_table(res, off) -> str:
    recs = res["rank"][off]
    by = {}
    for r in recs:
        by.setdefault(r["family"], []).append(r)
    out = ["| aile | özellik | q<0,10 | FWER<0,05 | en güçlü (|AUC−½|) |", "|---|---|---|---|---|"]
    for fam, lst in sorted(by.items()):
        best = max(lst, key=lambda r: abs(r["auc"] - 0.5))
        out.append(f"| {fam} | {len(lst)} | {sum(1 for r in lst if r['q'] < 0.10)} | {sum(1 for r in lst if r['p_fwer'] < 0.05)} | `{best['feature']}` ({tr(best['auc'], 3)}) |")
    return "\n".join(out)


def offset_profile(res, off0=0, topn=10) -> str:
    top = [r["feature"] for r in res["rank"][off0][:topn]]
    maps = {o: {r["feature"]: r for r in res["rank"][o]} for o in S1.OFFSETS}
    out = ["| özellik | AUC t0−15 | t0−10 | t0−5 | t0 |", "|---|---|---|---|---|"]
    for nm in top:
        out.append(f"| `{nm}` | " + " | ".join(tr(maps[o][nm]["auc"], 3) + ("*" if maps[o][nm]["p_fwer"] < 0.05 else "") for o in (3, 2, 1, 0)) + " |")
    return "\n".join(out) + "\n\n(* = o kayıtta FWER p < 0,05)"


def ideas_table(res, off, only5m=False, topn=60) -> str:
    recs = res["ideas"][off]
    if only5m:
        recs = [r for r in recs if r["tf"] == "5m"]
    recs = sorted(recs, key=lambda r: (r["q"], -abs(np.log((r["lift"] or 1e-9) + 1e-9))))[:topn]
    out = ["| zaman dilimi | fikir | olaylarda var | tabanda var | lift | AUC | q (BH) |", "|---|---|---|---|---|---|---|"]
    for r in recs:
        out.append(f"| {r['tf']} | {r['idea']} | {pc(r['event_share'])} | {pc(r['base_share'])} | {tr(r['lift'])} | {tr(r['auc'], 3)} | {qf(r['q'])} |")
    return "\n".join(out)


def dsim(a, b):
    """Ortalama fark (a − b) ve bağımsız SE'lerle t."""
    if not a or not b or "mean" not in a or "mean" not in b:
        return None
    d = a["mean"] - b["mean"]
    se = float(np.sqrt(a["se"] ** 2 + b["se"] ** 2))
    return {"mean": d, "se": se, "t": d / se if se > 0 else float("nan")}


def sig_table(ev, key) -> str:
    out = ["| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for pn, pl in BLOCKS:
        r = ev["periods"][key].get(pn)
        if not r or not r.get("n"):
            out.append(f"| {pl} | — | | | | | | | | |")
            continue
        b = ev["base"][pn]
        d0 = dsim(r.get("sim0"), b.get("sim0"))
        out.append(
            f"| {pl} | {f(r['per_day'], 0)} (n {r['n']}) | {pc(r.get('prec_ahead60'))} ({pc(b.get('prec_ahead60'))}) | {pc(r.get('hit15'))} | "
            f"{pp(r.get('lift15'), r.get('lift15_se'))} | {tstr(r.get('sim0'))} | {tstr(d0)} | {tstr(r.get('sim2'))} | "
            f"{pc(r.get('rec_early'))} ({pc(r.get('rec_early_rnd'))}) | "
            f"{pc(r.get('earlier_than_ha'), 0) if r.get('both_n') else '—'} (n {r.get('both_n', 0)}) |")
    return "\n".join(out)


def summary_table(ev, keys, pn="test") -> str:
    b = ev["base"][pn]
    out = [f"| sinyal | sinyal/gün | 60 dk önden kesinlik (taban {pc(b['prec_ahead60'])}) | hit60@1,5 şans farkı | net TP1,5/SL3 (koşulsuz rastgele {tr(b['sim0']['mean'])}) | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |",
           "|---|---|---|---|---|---|---|"]
    for k in keys:
        r = ev["periods"][k].get(pn)
        if not r or not r.get("n"):
            continue
        out.append(f"| {ev['meta'][k][:58]} | {f(r['per_day'], 0)} | {pc(r.get('prec_ahead60'))} (×{tr(r['prec_ahead60'] / b['prec_ahead60'], 1)}) | {pp(r.get('lift15'), r.get('lift15_se'))} | "
                   f"{tstr(r.get('sim0'))} | {pc(r.get('rec_early'))} ({pc(r.get('rec_early_rnd'))}) | {pc(r.get('earlier_than_ha'), 0) if r.get('both_n') else '—'} (n {r.get('both_n', 0)}) |")
    return "\n".join(out)


def verdict_rows(ev, keys) -> str:
    cols = ["şans farkı > 0", "şans farkı > HA'nınki", "net(TP1,5) > 0", "net(TP1,5) > koşulsuz rastgele", "trailing net > 0",
            "t0'dan önce yakalama > sıfır×1,5", "60 dk önden kesinlik ≥ HA'nınki", "HA'dan erken (ortak olayların >%50'si)",
            "KANITLI ERKEN UYARI (6. ve 8. birlikte)"]
    out = ["| sinyal | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    ha = ev["periods"]["HA"]
    for k in keys:
        pr = ev["periods"][k]
        fns = [lambda r, h, b: r["lift15"] > 0,
               lambda r, h, b: r["lift15"] > h["lift15"],
               lambda r, h, b: r["sim0"]["mean"] > 0,
               lambda r, h, b: r["sim0"]["mean"] > b["sim0"]["mean"],
               lambda r, h, b: r["sim2"]["mean"] > 0,
               lambda r, h, b: r["rec_early"] > 1.5 * r["rec_early_rnd"],
               lambda r, h, b: r["prec_ahead60"] >= h["prec_ahead60"],
               lambda r, h, b: r["both_n"] >= 10 and r["earlier_than_ha"] > 0.5,
               lambda r, h, b: r["rec_early"] > 1.5 * r["rec_early_rnd"] and r["both_n"] >= 10 and r["earlier_than_ha"] > 0.5]
        cells = []
        for fn in fns:
            vals = []
            for blk in OOS[1:]:                          # üç bağımsız örneklem-dışı blok: Blok1, Blok2, Blok3-dışı
                r = pr.get(blk)
                if not r or not r.get("n"):
                    vals = None
                    break
                try:
                    vals.append(bool(fn(r, ha[blk], ev["base"][blk])))
                except Exception:
                    vals = None
                    break
            cells.append("—" if vals is None else (f"{sum(vals)}/3" + (" ✓" if all(vals) else "")))
        out.append(f"| {ev['meta'][k][:60]} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def stage_report(args) -> None:
    out = Path(args.out_dir)
    res = pickle.load(open(out / "rank.pkl", "rb"))
    cd = json.loads((out / "cands.json").read_text(encoding="utf-8"))
    ev = pickle.load(open(out / "eval.pkl", "rb"))
    names = res["names"]
    L = []
    A = L.append
    n_feat = len(names)
    fam_cnt = {}
    for nm in names:
        fam_cnt[res["family"][nm]] = fam_cnt.get(res["family"][nm], 0) + 1
    m0, m2 = res["meta"][0], res["meta"][2]
    A("# Erken Uyarı Çalışması — TradingView rehberindeki göstergeler (klasik + smart money) LUNA tipi yükselişten ÖNCE ayırt edici mi? (2026-10-17)\n")
    A("**Soru:** Rehberdeki ~100 klasik + ~20 smart-money göstergesiyle (a) analizin duyarlılığı/hedefi iyileşir mi, (b) Hız Avcısı'ndan (HA) **daha erken** ya da **daha iyi** "
      "bir erken-uyarı öncüsü kurulabilir mi, (c) herhangi biri maliyet sonrası net-pozitif olur mu? Ham çıktılar `backend/work/indearly/`, kütüphane `app/rescan/indicators_ext.py`.\n")
    A("## 0. Kısa cevap\n")
    A("%%VERDICT%%")
    A("\n## 1. Kütüphane (`app/rescan/indicators_ext.py`, 31 birim testi, nedensellik + kesme testleri)\n")
    A(f"`compute_all(arr, tf)` her zaman diliminde **{len(I.feature_names('5m'))}** (1m: {len(I.feature_names('1m'))}) özellik üretir; çalışmada 5m + 1m + 15m = **{n_feat}** sütun. Aileler: "
      + ", ".join(f"{k} {v // 3 if v % 3 == 0 else v}" for k, v in sorted(fam_cnt.items())) + " (zaman dilimi başına).\n")
    A("**Eklenenler:** ALMA, WMA, Hull, DEMA, TEMA, KAMA, McGinley, LSMA + standart hata bandı; OBV, A/D, CMF, Chaikin osilatörü, Klinger, Ease of Movement, Elder Force, PVT, hacim osilatörü, "
      "taker CVD (+eğim), emir akışı dengesizliği z-skoru; CMO, Connors RSI, Stokastik %K/%D, StochRSI (mevcut modül sarmalandı), Williams %R, Ultimate, Awesome, TSI, TRIX, KST, Fisher, RVI, "
      "Balance of Power, CCI, DPO, SMI Ergodic, Coppock; Vortex, Parabolik SAR, SuperTrend (+3'lü küme), Ichimoku (bulut konumu, Tenkan/Kijun kesişimi, Chikou), Donchian (+iç-bar kırılımı), Keltner, "
      "sıkışma (BB/KC), Choppiness, Mass Index, ATR oranı, tarihsel oynaklık, Chaikin oynaklığı, göreli oynaklık endeksi; oturum VWAP uzaklığı, 24 sa dibinden çapalı VWAP, hacim profili POC (24 sa, 50 kutu; 1m hariç); "
      "SMC: fraktal salınımlar (onay gecikmeli), BOS/CHoCH durumu, likidite süpürme + geri alma, eşit dip/tepe, FVG (yeni/açık/temas), order block (mesafe/temas), yer değiştirme (displacement), TD Sequential kurulum sayacı.\n")
    A("**Zaten vardı (tekrarlanmadı):** EMA(7/20/50/99) uzaklık+eğim+fan, RSI14, MFI14, ATR14%, Bollinger genişlik/%B, MACD hist(+eğim), ADX/±DI, Aroon, doğrusal regresyon eğimi, ret1…20, hacim oranı, "
      "24 sa yüksek/alçak uzaklığı, range_pos24, yeşil/higher-low koşuları, drawdown12, 27 taker özelliği; StochRSI modülü (`stochrsi.py`), RQK (`rqk.py`); mum fitil reddi z-skoru (`technical_analysis._wick_rejection_zscore`).\n")
    A("## 2. Yöntem\n")
    A(f"- **Olaylar:** `work/pattern90/events.csv` / `events.pkl` — 90 günde 4 662 olay; birincil kümesiz küme (kept_primary=1) ve özellikleri tam olanlar: **{m0['n_events']} olay**. t0 = koşunun ilk mumu; karar anı = t0'dan hemen önce kapanan bar. "
      "Anlık görüntüler: **t0−15, t0−10, t0−5, t0** (hep o ana dek KAPANMIŞ barlar; 1m ve 15m özellikleri 5m karar anına son kapanmış 1m/15m barından eşlenir).")
    A(f"- **Taban:** eşleşmiş — aynı sembol + aynı gün, olay başına ≤ 40 rastgele geçerli an (toplam {m0['n_base']}), olayla aynı ofsetler. Geçerli an: ısınma ≥ 300 bar, 24 sa quote ≥ 5M TRY, olay koşusu dışı.")
    A(f"- **İstatistik:** her özellik için **grup-içi AUC** (olay, kendi 40 tabanının kaçından büyük; gruplar üzerinde ortalama), standartlaştırılmış fark d (uçlar %1 winsor), **grup-içi permütasyon** (her grupta 'olay' etiketi grubun {S1.M_MAX} üyesinden rastgele seçilir; "
      f"{m0['n_perm']} permütasyon) → çift taraflı p, **FWER** (max-|AUC−½| dağılımına göre, {n_feat} özellik ailesi) ve **Benjamini–Hochberg q**. FWER eşiği t0'da |AUC−½| > {f(m0['fwer_thr'], 3)}. Permütasyon gruplar arası bağımlılığı (aynı gün dalgaları) hesaba katmaz → "
      "blok tutarlılığı (3 ayrı 30 günlük blokta aynı işaret) ve dip-kontrollü artık AUC ayrıca verilir.")
    A("- **Dip kontrolü:** olaylar küçük bir düşüşten sonra başlıyor (90 günlük çalışma). 'AUC artık': özellik, 19 mevcut fiyat/oynaklık/taker özelliğine (ret1…20, ATR, %B, EMA uzaklığı, RSI, taker) taban satırlarında doğrusal regresyonla bağlanıp artığın AUC'si — "
      "0,5'e yakınsa özellik 'dip + oynaklık'tan fazla bilgi taşımıyor demektir.")
    A("- **Aday sinyaller:** fold-B EĞİTİM dönemi (2–17 Ekim) verisinden seçildi (etiket = 'karar anından sonraki 60 dk içinde aynı sembolde olay başlıyor'; eğitimde 13 pozitif bar/olay + geçerli diğer barlardan %12 örnek); "
      "açgözlü AND (olasılık oranı en yüksek; olay-düzeyi geri çağırma ve tahmini sinyal/gün kısıtlı), eşikler pozitif dağılımın kuantillerinde. Sonra diğer tüm dönemlerde **DOKUNULMADAN** değerlendirildi. "
      "Rehberin 13 öncü fikri ayrıca ÖNCEDEN BELİRLENMİŞ koşullarla (veri-seçimsiz; yalnız eşikleri taban kuantilleri) 5m'de süpürüldü.")
    A("- **Süpürme:** 5m karar ızgarasında, sembol başına cooldown 12 bar (60 dk), geçerli an ve ileri sonuç ölçülebilir olmalı (pattern90 süpürmesiyle aynı). **Ölçüler:** sinyal/gün; 60 dk içinde olay başlama payı (taban = tüm geçerli anlarda aynı ölçü); "
      "hit60@1,5 (60 dk MFE ≥ %1,5) ve şans farkı (null3: aynı sembol, ±1 sa dilimi, son 30 dk aralık+getiri benzer; gün-kümeli ±%95); `exit_sim` net (60 sn gecikme, %0,15 kayma, %0,1125/bacak ücret; TP1,5/SL3/T60 ve izleyen 1,0/0,8; "
      "gün-kümeli t) ve KOŞULSUZ rastgele giriş (tüm geçerli anlardan 150 bin tekdüze) ile aynı çıkış (sinyal−rastgele farkı gün-kümeli SE'lerle); olay yakalama = t0'dan ÖNCE (t0−60 dk … t0) ilk sinyal (sıfır = aynı sembolde aynı sayıda serbestçe yerleştirilmiş rastgele sinyal); öncelik = t0 − ilk sinyal; HA karşılaştırması = [t0−60, t0+90 dk] penceresinde ilk HA tıkı (canlı-benzeri: rank ≤ 10, aşırı alımda değil).")
    A("- **Dönemler:** EĞİTİM = 2–17 Eki (seçim burada → örneklem İÇİ); TEST = 29 Tem–1 Eki; Blok1/2 = 19 Tem–17 Ağu / 18 Ağu–16 Eyl; Blok3 dışı = 17 Eyl–1 Eki (Blok3'ün eğitimle örtüşmeyen kısmı). Test/Blok1/Blok2/Blok3-dışı **örneklem dışı**, birbirleriyle örtüşmez (TEST = Blok1 + Blok2 + Blok3-dışı'nın 29 Tem sonrası birleşimi → bağımsız 3 deney: Blok1, Blok2, Blok3-dışı).\n")
    # --- sıralama
    A("## 3. Sıralama: yeni göstergeler olay öncesinde ayırt edici mi?\n")
    for off, lab in ((0, "t0 (karar anı: ilk yeşil mumdan hemen önce)"), (2, "t0−10 dk")):
        mt = res["meta"][off]
        A(f"### {lab} — ilk 25 (|AUC−½|), {n_feat} özellik (5m+1m+15m), eşleşmiş taban\n")
        A(f"FWER p<0,05: **{mt['n_sig_fwer']}** özellik; BH q<0,10: **{mt['n_sig_q10']}** özellik (olay {mt['n_events']}, taban {mt['n_base']}).\n")
        A(rank_table(res["rank"][off], res["ctrl"][off]))
        ref = res["ctrl"][off]
        best_ref = sorted(ref.items(), key=lambda kv: -abs(kv[1] - 0.5))[:5]
        A("\nReferans (MEVCUT fiyat/taker özellikleri, aynı eşleşmiş AUC): " + ", ".join(f"`{k}` {tr(v)}" for k, v in best_ref) + ".\n")
        A("Aile özeti:\n")
        A(family_table(res, off))
        A("")
    A("### En güçlü 10 özelliğin ofset profili (AUC; t0'daki en güçlüler)\n")
    A(offset_profile(res, 0, 10))
    A("")
    A("### Anlamlı özellik sayısı (FWER p<0,05) ofsete göre\n")
    A("| ofset | FWER<0,05 | q<0,10 | FWER eşiği (|AUC−½|) |\n|---|---|---|---|")
    for o in (3, 2, 1, 0):
        mt = res["meta"][o]
        A(f"| {S1.OFF_LABEL[o]} | {mt['n_sig_fwer']} | {mt['n_sig_q10']} | {f(mt['fwer_thr'], 3)} |")
    A("")
    mp = out / "multi.pkl"
    if mp.exists():
        mu = pickle.load(open(mp, "rb"))
        A("## 3b. Çok değişkenli test — kütüphane mevcut 154 özelliğin ÜSTÜNE bilgi ekliyor mu?\n")
        A("HistGradientBoosting (150 ağaç, 15 yaprak), olay vs eşleşmiş taban (olay başına 12), **blok-dışı bırakma** (iki 30 günlük blokla eğit, üçüncüde test; 3 kat). "
          "AUC = test bloğunda tüm satırlar; grup-içi = olay skorunun kendi tabanlarından büyük olma payı. Satırlar: mevcut `pattern_study` 154 özellik / mevcut + kütüphane (401) / yalnız kütüphane.\n")
        A("| an | özellik kümesi | Blok1 | Blok2 | Blok3 | ortalama | grup-içi ortalama |\n|---|---|---|---|---|---|---|")
        for off, lab in ((0, "t0"), (2, "t0−10 dk")):
            for nm, r in mu[off].items():
                A(f"| {lab} | {nm} | " + " | ".join(tr(x["auc"], 3) for x in r) + f" | {tr(np.mean([x['auc'] for x in r]), 3)} | {tr(np.mean([x['auc_group'] for x in r]), 3)} |")
        for off, lab in ((0, "t0"), (2, "t0−10 dk")):
            d = [mu[off]["mevcut + kütüphane"][k]["auc"] - mu[off]["mevcut 154"][k]["auc"] for k in range(3)]
            A(f"\nKatkı ({lab}): kütüphane eklenince AUC farkı blok bazında " + ", ".join(f"{x:+.3f}".replace(".", ",") for x in d) + f" (ortalama {np.mean(d):+.3f}".replace(".", ",") + ").")
        A("")
    # --- öncü fikirler
    A("## 4. Rehberin öncü fikirleri (önceden belirlenmiş koşullar)\n")
    A("Her satır: koşul olay anlarında (t0 ya da t0−10) taban anlarına göre ne sıklıkta sağlanıyor. lift = olay payı / taban payı; q = BH (aile = tüm fikir × zaman dilimi satırları). Eşikler taban kuantilleri (olay bilgisi içermez).\n")
    for off, lab in ((0, "t0"), (2, "t0−10 dk")):
        A(f"### {lab} — en anlamlı 25 (tüm zaman dilimleri)\n")
        A(ideas_table(res, off, topn=25))
        A("")
    A("### 5m — tüm fikirler, t0−10 dk (sinyal olarak süpürülen 13 fikir bölüm 6'dadır)\n")
    A(ideas_table(res, 2, only5m=True, topn=80))
    A("")
    # --- adaylar
    A("## 5. Aday erken-uyarı sinyalleri (fold-B EĞİTİMİNDE seçildi, diğer dönemlerde dokunulmadan ölçüldü)\n")
    sm = cd["summary"]
    A(f"Eğitim: {sm['n_train_rows']} satır, {sm['n_pos']} pozitif bar ({sm['n_events']} olay), geçerli an/gün ≈ {sm['valid_per_day']:.0f}. Tek özellik en iyi eğitim AUC'leri: "
      + ", ".join(f"`{n}` {tr(a)}" for n, a in sm["top_auc"][:8]) + ".\n")
    for c in cd["cands"]:
        k = c["id"]
        cs = " **VE** ".join(f"`{x['feature']}` {x['op']} {x['value']:.4g}" for x in c["conditions"])
        t = c["train"]
        A(f"### {k} — {c['label']}\n")
        A(f"Koşul: {cs}. Eğitim: LR {t['lr']:.1f}, bar-TPR {pc(t['tpr'])}, olay geri çağırma {pc(t['ev_recall'])}, tahmini ≤ {t['spd']:.0f} sinyal/gün.\n")
        A(sig_table(ev, k))
        lun = ev["lunatry"].get(k, [])
        A(f"\nLUNATRY 17 Ekim 01:00 (t0) — bu sinyalin 00:00–04:00 arası tetik saatleri: {', '.join(lun) if lun else 'YOK'}.\n")
    A("### Hız Avcısı (referans, aynı değerlendirme yolu)\n")
    A(sig_table(ev, "HA"))
    A(f"\nLUNATRY 17 Ekim 00:00–04:00 HA tıkları (canlı-benzeri): {', '.join(ev.get('lunatry_ha', [])) or 'YOK'}.\n")
    A("## 6. Rehberin 13 öncü fikri sinyal olarak (5m, önceden belirlenmiş koşul, tüm dönemler örneklem dışı sayılır)\n")
    gkeys = [k for k in ev["periods"] if k.startswith("G:")]
    for k in gkeys:
        A(f"### {ev['meta'][k]}\n")
        A(sig_table(ev, k))
        lun = ev["lunatry"].get(k, [])
        A(f"\nLUNATRY 17 Ekim tetik saatleri (00:00–04:00): {', '.join(lun) if lun else 'YOK'}.\n")
    A("## 7. Özet ve karar tablosu\n")
    A("### 7a. TEST dönemi (29 Tem–1 Eki, örneklem dışı) — tüm sinyaller\n")
    A(summary_table(ev, [c["id"] for c in cd["cands"]] + gkeys + ["HA"], "test"))
    A("\n### 7b. Üç bağımsız örneklem-dışı blokta (Blok1, Blok2, Blok3-dışı) koşulun sağlandığı blok sayısı (3/3 = her blokta)\n")
    A(verdict_rows(ev, [c["id"] for c in cd["cands"]] + gkeys + ["HA"]))
    A("")
    body = "\n".join(L)
    vp = out / "verdict.md"
    body = body.replace("%%VERDICT%%", vp.read_text(encoding="utf-8") if vp.exists() else "(karar metni henüz yazılmadı)")
    lp = out / "limits.md"
    body += "\n" + (lp.read_text(encoding="utf-8") if lp.exists() else "")
    (out / "report.md").write_text(body, encoding="utf-8")
    print("[report] yazıldı:", out / "report.md", flush=True)
