"""Rapor üretici: Limit giriş + StochRSI ön sinyali çalışması → work/limitstoch/report.md (Türkçe).

Girdiler: a1_results.pkl (A-1/A-2), a3_daily.pkl (A-3), b_res_<kaynak>_<P|O>.pkl (B). Hepsi bu dizindeki betiklerle üretilir (limitstoch_*.py)."""
from __future__ import annotations

import gc
import os
import pickle
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import limitstoch_b as B  # noqa: E402
import limitstoch_lib as L  # noqa: E402
import limitstoch_rep_a as RA  # noqa: E402
import limitstoch_rep_a3 as RA3  # noqa: E402
import limitstoch_rep_b2 as RB2  # noqa: E402
from app.rescan import exit_sim as X  # noqa: E402
from limitstoch_rep_b import BRes, best_j, ci1, dtxt  # noqa: E402

f2 = L.f2


def pct(x, nd=1):
    return "—" if x is None or not np.isfinite(x) else ("%." + str(nd) + "f") % (100 * x)


def lunatry_b() -> list[str]:
    """LUNATRY 17 Ekim: HA adayı (01:15:30, 2,212) ve bildirim (02:03:29, 2,31) için limit girişler (doğrudan 1 dk yolundan)."""
    import psycopg
    out = []
    P = out.append
    sym = "LUNATRY"
    a = L.load_arr("1m", sym)
    ot = a[:, 0].astype(np.int64)
    mm = {sym: (ot, a[:, 1], a[:, 2], a[:, 3], a[:, 4])}
    tz = L.TZ
    day0 = datetime(2026, 10, 17, tzinfo=tz)
    sigs = [("HA adayı 01:15:30 (fiyat 2,212; P0'ın +%1,7 üstü)", datetime(2026, 10, 17, 1, 15, 30, tzinfo=tz), 2.212),
            ("bildirim trend_devam 02:03:29 (fiyat 2,31; P0'ın +%6,2 üstü)", datetime(2026, 10, 17, 2, 3, 29, tzinfo=tz), 2.31)]
    specs = [X.ExitSpec("fixed TP1.5 SL3 T120", "fixed", sl=3.0, time_min=120, tp=1.5),
             X.ExitSpec("trail act0.5 gap0.8 SL3 T120", "trail", sl=3.0, time_min=120, act=0.5, gap=0.8),
             X.ExitSpec("fixed TP1 SL1.5 T60", "fixed", sl=1.5, time_min=60, tp=1.0)]
    P("| sinyal | giriş | doldu mu (dk sonra) | fiyat 60 dk sonra / giriş | " + " | ".join("net %% (%s)" % s.name for s in specs) + " |")
    P("|---|---|---|---|---|---|---|")
    for label, dtm, price in sigs:
        t = int(dtm.timestamp() * 1000)
        i0, ok = X.entry_index(ot, np.array([t]), 60)
        i0 = int(i0[0])
        # piyasa girişi
        e = {"row": np.array([0]), "ie": np.array([i0]), "lim": np.array([np.nan]), "sym": np.array([0])}
        res_m = [B.sim_entries(e, [sym], mm, [s], 0.15, limit=False)[0, 0] for s in specs]
        c60 = a[min(i0 + 59, len(a) - 1), 4]
        P("| %s | piyasa (60 sn + %%0,15 kayma) | giriş | %+.2f%% | %s |" % (label, (c60 / a[i0, 1] - 1) * 100, " | ".join(f2(float(x)) for x in res_m)))
        for d in B.D_LIST:
            for V in (15, 60):
                lim = price * (1 - d / 100.0)
                low = a[i0:i0 + V, 3]
                hit = np.flatnonzero(low < lim)
                if len(hit) == 0:
                    P("| | limit d%g%% V%d | dolmadı | | %s |" % (d, V, " | ".join("0 (işlem yok)" for _ in specs)))
                    continue
                ie = i0 + int(hit[0])
                e = {"row": np.array([0]), "ie": np.array([ie]), "lim": np.array([lim]), "sym": np.array([0])}
                res_l = [B.sim_entries(e, [sym], mm, [s], 0.15, limit=True)[0, 0] for s in specs]
                c60l = a[min(ie + 59, len(a) - 1), 4]
                P("| | limit d%g%% V%d | %d dk | %+.2f%% | %s |" % (d, V, int(hit[0]) + 1, (c60l / lim - 1) * 100, " | ".join(f2(float(x)) for x in res_l)))
    P("")
    return out


def main():
    gen = datetime.now(L.TZ).strftime("%Y-%m-%d %H:%M")
    L_ = []
    A = L_.append
    res_a1 = pickle.load(open(L.WORK / "a1_results.pkl", "rb"))
    a1 = res_a1["a1"]
    A3 = RA3.A3(L.WORK / "a3_daily.pkl")
    a1_txt = RA.sect_a1(res_a1)
    a2_txt = RA.sect_a2(res_a1, RA.lunatry_lines())
    a3_txt, a3s = RA3.sect_a3(A3)

    # ---------------------------------------------------------------- B
    bs, Ss, bO, SO = {}, {}, {}, {}
    for name in B.SRC_NAMES:
        b = BRes(name, "P")
        Ss[name] = b.all_stats()
        b.res = None
        bs[name] = b
        gc.collect()
        f = L.WORK / ("b_res_%s_O.pkl" % name)
        if f.exists():
            o = BRes(name, "O")
            SO[name] = o.all_stats()
            o.res = None
            bO[name] = o
            gc.collect()
    b_txt = []
    BA = b_txt.append
    BA("## 5. Çalışma B — Bildirim fiyatının ALTINDA limit giriş (+ StochRSI desteği), 30 günlük geriye dönük test\n")
    BA("### 5.0 Kurulum\n")
    BA("- **Kaynaklar:** (1) **HA** = Hız Avcısı canlı-benzeri adaylar (rescan, rank ≤ 10, aşırı alımda değil, 60 dk bölümler; `work/rescan_90g_nogate.jsonl`) — 30 günlük birincil pencere W30 (17 Eyl–16 Eki) + 90 günlük bloklar B1/B2/B3; "
       "(2) **canlı bildirimler** (`monitoring_notifications`, W30; hepsi ve yalnız `trend_devam`; aynı sembolde 60 dk tekilleştirme); (3) **canlı journal adayları** (`velocity_candidates`, non-rescan, passes, rank ≤ 10, 60 dk bölüm; 18 Eyl–16 Eki) = ileri çizgi. "
       "Sinyal fiyatı P0 = kaynağın fiyatı (yoksa son kapanmış 1 dk kapanışı).")
    BA("- **Limit emri:** sinyal + 60 sn sonra yerleşir (gecikme); geçerlilik V ∈ {15, 30, 60} dk; limit = P0 × (1 − d%), d ∈ {0,3; 0,6; 1,0; 1,5}; ilk 1 dk barının DÜŞÜĞÜ limitin KESİNLİKLE altına inerse dolar; dolum fiyatı = limit (açılış daha düşük olsa bile; kötümser). "
       "Dolum barında yalnız düşük kullanılır (yüksek = limit; TP/iz o barda tetiklenmez; stop kontrolü düşükle yapılır) → kötümser. Giriş kayması 0 (maker), çıkışlarda stop/zaman kayması %0,15. Dolmayan = işlem yok, net/sinyal'e 0 girer.")
    BA("- **Ücret:** `config.py` COMMISSION_PCT = 0,0015 (Binance TR maker = taker = %0,15/bacak, satır 584 yorumu), COMMISSION_BNB_MODE varsayılan açık, indirim %25 → **%0,1125/bacak** (`paper_ledger.commission_pct()`); maker için ayrı (daha düşük) bir oran YOK, bu yüzden limit girişin tek maliyet avantajı kaymanın olmamasıdır.")
    BA("- **StochRSI destekli varyantlar:** (LK) limit yalnız sinyal anında son kapanmış 5 dk StochRSI K < 50 ise yerleşir; (C) geçerlilik penceresi içinde 1 dk ya da 5 dk **ön sinyal** (seviye 20 / 30; çekirdek kırmızı şartı dâhil) gelirse o barın kapanışından +60 sn sonraki ilk 1 dk açılışında PİYASA girişi (%0,15 kayma), isteğe bağlı fiyat kapısı: giriş açılışı ≤ P0 × (1 − d%) (d = 0 → kapı yok); "
       "(LC) limit dolar ve dolum barının kapanışından sonraki 5 dk içinde ön sinyal gelirse giriş dolumda değil ön sinyalde (piyasa). (M) referans: sinyal + 60 sn piyasa girişi.")
    BA("- **Çıkışlar:** 24 hücre (Çalışma A ile aynı). **Rastgele taban:** AYNI giriş kuralı rastgele anlarda: (1) istenen — aynı sembol + saat dilimi + çerçeve, kaynağın HİÇBİR tick'inden ≥ 2 sa uzak; (2) oynaklık eşleşmeli ≥ 2 sa; (3) saat dilimi eşleşmeli, dışlamasız; (4) oynaklık (son 30 dk aralığı ±%25) eşleşmeli, dışlamasız. Her sinyal için 2'şer rastgele an. "
       "Tabanlarda likit-sembol filtresi YOK (aynı sembol eşleşmesi likiditeyi taşır; HA havuzu 5M TRY altını da içeriyor).")
    BA("- **Not (limit + oynaklık karıştırıcısı):** sinyaller yüksek oynaklık anlarında gelir; oynak anlarda limit daha sık dolar (aşağıda sinyal dolum % ≫ rastgele-1 dolum %). Bu yüzden 'sinyal − rastgele-1' fark tablosu oynaklık etkisini de taşır; oynaklık eşleşmeli rastgele-4 asıl kıyastır. "
       "Ayrıca rastgele-1/-2'nin 'sinyalden ≥ 2 sa uzak' koşulu GELECEĞE de bakar (ileride sinyal olmayan anlar) — bu yanlılık A bölümünde ölçüldü.\n")
    # tablo 5.1
    BA("### 5.1 Düz limit\n")
    for name, win, title in (("HA", "W30", "HA (rescan) — W30"), ("NOTIF_all", "W30", "Canlı bildirimler (hepsi) — W30"), ("NOTIF_trend", "W30", "Canlı bildirimler (trend_devam) — W30")):
        b = bs[name]; S = Ss[name]
        st0 = S["L d0.3 V15"][(win, 0)]
        BA("**%s** — sinyal n = %d (rastgele-4: %d)\n" % (title, st0["n"], S["L d0.3 V15"][(win, 4)]["n"]))
        b_txt.extend(RB2.plain_table(b, S, win, "%s: düz limit tablosu (net/sinyal: dolmayan = 0)" % title))
    BA("**Dayanıklılık — HA 90 gün (07-20 → 10-16) ve canlı journal adayları (ileri, 18 Eyl–16 Eki):**\n")
    for name, win, title in (("HA", "ALL", "HA (rescan) — 90 gün"), ("LIVE", "B3", "Canlı journal adayları — 18 Eyl–16 Eki")):
        b_txt.extend(RB2.plain_table(bs[name], Ss[name], win, title))
    BA("### 5.2 Seçim yanlılığı: dolan ve dolmayan sinyallerden sonra fiyat\n")
    for name, win, title in (("HA", "W30", "HA — W30"), ("NOTIF_all", "W30", "Canlı bildirimler (hepsi) — W30"), ("NOTIF_trend", "W30", "Canlı bildirimler (trend_devam) — W30")):
        b_txt.extend(RB2.adverse_table(bs[name], win, title))
    BA("### 5.3 StochRSI destekli varyantlar (aile başına en iyi bileşim)\n")
    for name, win, title in (("HA", "W30", "HA — W30"), ("NOTIF_all", "W30", "Canlı bildirimler (hepsi) — W30"), ("NOTIF_trend", "W30", "Canlı bildirimler (trend_devam) — W30"),
                             ("HA", "ALL", "HA — 90 gün"), ("LIVE", "B3", "Canlı journal adayları — 18 Eyl–16 Eki")):
        b_txt.extend(RB2.variants_table(bs[name], Ss[name], win, title))
    BA("### 5.4 Tüm bileşimlerin taraması (73 giriş × 24 çıkış = 1 752; işlem ≥ 100 olanlar)\n")
    BA("| kaynak / pencere | bileşim sayısı | net/sinyal > 0 | net/işlem > 0 | sinyal−rastgele-4 alt sınırı > 0 |")
    BA("|---|---|---|---|---|")
    scan = {}
    for name, wins in (("HA", ["W30", "B1", "B2", "B3", "ALL"]), ("NOTIF_all", ["W30"]), ("NOTIF_trend", ["W30"]), ("LIVE", ["B3"])):
        for w in wins:
            n, npos, nd, npt = RB2.scan_counts(bs[name], Ss[name], w)
            scan[(name, w)] = (n, npos, nd, npt)
            BA("| %s %s | %d | %d | %d | %d |" % (name, w, n, npos, npt, nd))
    BA("")
    BA("**HA W30 — net/sinyal'e göre ilk 10 bileşim (iç-örneklem; tümü ≤ 0 ise 'en az kötü'):**\n")
    t10, _, _ = RB2.top_table(bs["HA"], Ss["HA"], "W30")
    b_txt.extend(t10)
    BA("### 5.5 Yürüyen-ileri ve ileri çizgi\n")
    wtxt, wsum = RB2.walk_table(bs, Ss, bO, SO)
    b_txt.extend(wtxt)
    BA("### 5.6 LUNATRY 17 Ekim sağlaması (B)\n")
    BA("LUNATRY için kayıtlı ilk HA adayı 01:15:30'da (fiyat 2,212; t0 01:00'daki P0 = 2,176 → yükselişin %1,7'si geçmişti) ve tek canlı bildirim 02:03:29'da (fiyat 2,31, trend_devam) idi. Aşağıda bu iki sinyal için limit girişler (doğrudan 1 dk yolundan; net % 60 sn gecikme / %0,15 çıkış kayması / %0,1125 ücret):\n")
    b_txt.extend(lunatry_b())

    # ---------------------------------------------------------------- özet
    s5 = a1[("turn")][("5m", "W30", 20, "pre")]
    T = a1["turn"]

    def tp(tf, lv, q):
        pre = T[(tf, "W30", lv, "pre")]; b1 = T[(tf, "W30", lv, "base_red")]
        return pre[:, 1 + q].sum() / pre[:, 0].sum(), b1[:, 1 + q].sum() / b1[:, 0].sum()

    p5 = [tp("5m", 20, q) for q in range(4)]
    p1m = [tp("1m", 20, q) for q in range(4)]
    wf_tot = a3s["wf_total"]
    ev5 = RA.event_rates(res_a1, "5m", 20, "pre", "b", False)
    ev5a = RA.event_rates(res_a1, "5m", 20, "pre", "a", False)
    ev1 = RA.event_rates(res_a1, "1m", 20, "pre", "b", False)
    # A-3 W30 pozitif hücre sayısı
    npos_a3 = 0; npos_a3_o = 0
    for sid in range(len(A3.sets)):
        for scn in ("P", "O"):
            m = A3.means(sid, 0, scn, "W30")
            if scn == "P":
                npos_a3 += int((m > 0).sum())
            else:
                npos_a3_o += int((m > 0).sum())
    best_a3 = max(((np.nanmax(A3.means(sid, 0, "P", "W30")), A3.sets[sid]) for sid in range(len(A3.sets))), key=lambda x: x[0])
    best_a3o = max(((np.nanmax(A3.means(sid, 0, "O", "W30")), A3.sets[sid]) for sid in range(len(A3.sets))), key=lambda x: x[0])
    ha_scan = scan[("HA", "W30")]
    top_b = RB2.pick(bs["HA"], Ss["HA"], "W30", "net")
    summary = []
    S_ = summary.append
    S_("## 0. Özet ve kararlar\n")
    S_("**(1) StochRSI ön sinyali çekirdeğin AL dönüşünü güvenilir biçimde önceden haber veriyor mu? — HAYIR (zayıf, işe yaramaz).**")
    S_("- 5m (birincil, seviye 20, W30, ön sinyal %d/gün, tüm likit semboller, tekilleştirmeden önce): çekirdek 1 bar (5 dk) içinde dönme olasılığı %s%% (kırmızı bar tabanı %s%% → **daha düşük**), 3 bar içinde %s%% (taban %s%%), 6 bar (30 dk) içinde %s%% (taban %s%%, **+%.1f pp, 1,12×**), 12 bar (60 dk) içinde %s%% (taban %s%%, 1,02×). "
       "Yani kısa ufukta (1–3 bar) tabanın ALTINDA; 30 dk'da küçük bir üstünlük; 60 dk'da fark yok. Öncülük (12 bar içinde dönenlerde) medyan 4 bar = 20 dk, ama dönüşün kendisi zaten çok sık (tabanın %s%%'i 60 dk'da döner). Dönüşlerin %s%%'inden önce ön sinyal var, rastgele bir kırmızı barın önünde %s%% (1,06×)." % (
           round(a1["turn"][("5m", "W30", 20, "pre")][:, 0].sum() / 30), pct(p5[0][0]), pct(p5[0][1]), pct(p5[1][0]), pct(p5[1][1]), pct(p5[2][0]), pct(p5[2][1]),
           100 * (p5[2][0] - p5[2][1]), pct(p5[3][0]), pct(p5[3][1]), pct(p5[3][1]),
           pct(a1["prec"][("5m", "W30", 20, "flip")].sum(0)[1] / a1["prec"][("5m", "W30", 20, "flip")].sum(0)[0]),
           pct(a1["prec"][("5m", "W30", 20, "base")].sum(0)[1] / a1["prec"][("5m", "W30", 20, "base")].sum(0)[0])))
    S_("- 1m: 3 bar içinde %s%% (taban %s%%, 1,18×), 6 bar içinde %s%% (taban %s%%, 1,29×); lift daha büyük ama 1 dk çekirdek her ~8 dk'da döndüğü ve 1m ön sinyal günde ≈ %d kez çaldığı için pratik değeri yok; öncülük medyan 4 dk." % (
        pct(p1m[1][0]), pct(p1m[1][1]), pct(p1m[2][0]), pct(p1m[2][1]), round(T[("1m", "W30", 20, "pre")][:, 0].sum() / 30)))
    S_("- LUNA tipi olaylar (4 552 olay, t0'dan önceki 30 dk, nedensel): 5m ön sinyal olaylarda %s%%, rastgele anlarda %s%% (**%.2f× — daha az**); 1m: %s%% vs %s%% (1,08×, ama her ~dakika çalıyor). Çekirdek AL dönüşü de aynı (5m 0,86×). "
       "LUNATRY 17 Ekim: 5m ön sinyal ilk kez 02:30'da (t0 + 90 dk, fiyat P0'ın +%%4,3 üstünde); 1m'de 00:58'de (t0 − 2 dk, fiyat P0 civarında) çaldı ve çekirdek 01:02'de döndü — ama 1m 00:44'te de çalmıştı (−16 dk, yanlış) ve gün boyu gürültü üretiyor." % (
           pct(ev5["pe"]), pct(ev5["pr"]), ev5["ratio"], pct(ev1["pe"]), pct(ev1["pr"])))
    S_("")
    S_("**(2) Ön sinyal örneklem dışında KÂRLI bir giriş mi? — HAYIR.**")
    S_("- 12 sinyal kümesi (5m/1m/15m × seviye 20/30 × ön sinyal/onaylı) × 24 çıkış = 288 hücre: W30'da net > 0 olan hücre sayısı **%d** (birincil 60 sn/%%0,15), iyimser senaryoda (0 sn/%%0,05) **%d**; en iyi hücre neti %s (birincil, %s) ve %s (iyimser, %s). "
       "Yürüyen-ileri (bloğta seç → diğer iki blokta ölç): %d/%d satırda OOS net > 0, alt sınır > 0 olan %d. Sinyal oynaklık-eşleşmeli koşulsuz rastgeleden (taban 4) ayırt edilemiyor: sinyal−taban farkı 72 satırın hiçbirinde anlamlı pozitif değil (%d); hit60@1,5 şans yükselişi 5m ön sinyalde 0,88×, onaylıda 1,02×, 1m'de 1,02–1,03×, 15m'de 0,97–1,01×." % (
           npos_a3, npos_a3_o, f2(best_a3[0]), best_a3[1], f2(best_a3o[0]), best_a3o[1], wf_tot[0], wf_tot[3], wf_tot[1], wf_tot[2]))
    S_("- Not: istenen rastgele taban (aynı sembol/saat, herhangi bir sinyalden ≥ 2 sa uzak) 5m ön sinyalde POZİTİF çıkıyor (≈ +0,1 net): bu, 'ileride 2 saat ön sinyal olmaması' koşulunun geleceğe bakması yüzünden bir seçim yanlılığıdır (sinyalsiz saatler = yükseliş trendi). Dışlamasız tabanlar (3/4) ≈ −0,49 (maliyet tabanı) ve sinyal onlardan farksız.")
    S_("")
    # --- (3) için hesaplanan sayılar
    SH = Ss["HA"]
    fills = {d: [SH["L d%g V%d" % (d, v)][("W30", 0)]["fill"] for v in B.V_LIST] for d in B.D_LIST}
    best_trade = max(((SH[c][("W30", 0)]["mean_t"][j], c, bs["HA"].specs[j]) for c in bs["HA"].cells for j in range(24)
                      if SH[c][("W30", 0)].get("n") and SH[c][("W30", 0)]["ntr"] >= 100), key=lambda x: x[0])
    adv = []
    bH = bs["HA"]
    r60 = bH.extra["ret60"]; okx = bH.extra["ok"]; mw = bH.in_win("W30")
    for d in B.D_LIST:
        for v in B.V_LIST:
            fi = bH.fi["L d%g V%d" % (d, v)]
            sg = mw & okx & (bH.kind == 0) & np.isfinite(r60)
            k4 = mw & okx & (bH.kind == 4) & np.isfinite(r60)
            adv.append((r60[sg & (fi >= 0)].mean(), r60[sg & (fi < 0)].mean(), r60[k4 & (fi >= 0)].mean(), r60[k4 & (fi < 0)].mean()))
    adv = np.array(adv)
    stm = Ss["NOTIF_trend"]["M"][("W30", 0)]; jm = best_j(stm)
    b4m = Ss["NOTIF_trend"]["M"][("W30", 4)]
    S_("**(3) Limit / StochRSI girişi örneklem dışında net-pozitif VE rastgeleden iyi mi? — HAYIR (net-pozitif hiçbiri yok; küçük 'rastgeleden az kötü' farkları var).**")
    S_("- **Net-pozitif:** HA W30'da 73 giriş hücresi × 24 çıkış (işlem ≥ 100 olan %d bileşim) içinde net/sinyal > 0 olan **%d**, net/işlem > 0 olan **%d**; en iyi net/işlem %s (%s / %s). "
       "HA B1, B2, B3, 90 gün, canlı bildirimler (hepsi / trend_devam) ve canlı journal adayları (ileri) için de pozitif bileşim sayısı sıfır (bölüm 5.4). 'En iyi' net/sinyal bileşimleri (≈ −0,05) zaten yalnızca %%10 dolan, neredeyse hiç işlem yapmayan hücrelerdir; işlem başına net hep −0,4…−0,5." % (
           ha_scan[0], ha_scan[1], ha_scan[3], f2(best_trade[0]), best_trade[1], best_trade[2]))
    S_("- **Dolum ve seçim yanlılığı:** HA W30'da düz limit dolum oranı d = %%0,3 için %%%.0f–%.0f, d = %%0,6 için %%%.0f–%.0f, d = %%1,0 için %%%.0f–%.0f, d = %%1,5 için %%%.0f–%.0f (V = 15…60 dk); oynaklık eşleşmeli rastgele giriş de benzer oranda doluyor (limit oynak anda zaten dolar). "
       "Dolan sinyallerden sonra P0'a göre 60 dk getirisi %+.2f…%+.2f%%, DOLMAYANLARDAN sonra %+.2f…%+.2f%% (limit en iyi koşuları kaçırıyor: dolmayanlar sonra ortalama yükseliyor); rastgele-4'te aynı ayrım daha küçük (dolan %+.2f…%+.2f%%, dolmayan %+.2f…%+.2f%%), yani bu ayrımın bir kısmı mekanik, ama sinyallerde daha belirgin. "
       "Limit fiyatından 60 dk sonraki getiri hep negatif (−0,17…−0,37%%): dipten alım ortalamada geri toparlama vermiyor." % (
           100 * min(fills[0.3]), 100 * max(fills[0.3]), 100 * min(fills[0.6]), 100 * max(fills[0.6]), 100 * min(fills[1.0]), 100 * max(fills[1.0]), 100 * min(fills[1.5]), 100 * max(fills[1.5]),
           adv[:, 0].min(), adv[:, 0].max(), adv[:, 1].min(), adv[:, 1].max(), adv[:, 2].min(), adv[:, 2].max(), adv[:, 3].min(), adv[:, 3].max()))
    S_("- **StochRSI desteği:** (a) K5 < 50 kapısı dolumu yaklaşık üçte bire indirir (ör. d = %%0,3, V = 60: %%28 vs %%89) ve net/işlemi düzeltmez (−0,4…−0,5); (b) dip + ön sinyal teyidi ve (c) dolum + 5 dk içinde ön sinyal, düz limitten ve piyasa girişinden daha iyi değil — rastgele-4'e göre en iyi farklar −0,04…+0,02 (anlamlı pozitif yok), net hep < 0. "
       "'Rastgeleden az kötü' sonuçlar çıkıyor (ör. LK d0,3 V60: HA B3'te net/sinyal −0,15 vs rastgele-4 −0,20, fark +0,05 [+0,03; +0,08]; trend_devam bildirimlerinde +0,16), ama (i) net hâlâ −0,15, (ii) canlı journal ileri çizgisinde fark +0,01 [−0,02; +0,04] (anlamsız), (iii) 1 752 bileşim içinde seçilmiş. "
       "Piyasa girişi (referans M) trend_devam bildirimlerinde %s net/sinyal (rastgele-4 %s; fark %s) — önceki çalışmadaki 'trend_devam rastgeleyi +0,2…0,3 geçer ama net −0,3' bulgusuyla tutarlı." % (
           ci1(stm["mean"][jm], stm["se"][jm]), f2(b4m["mean"][jm]), dtxt(stm, b4m, jm)))
    S_("- **Yürüyen-ileri (HA blokları):** %d satırdan OOS net/sinyal > 0 olan %d, %%95 alt sınırı > 0 olan %d. Ölçüt B (rastgele-4'e göre en iyi) satırlarında sinyal−rastgele-4 alt sınırı > 0: %d/7 (hepsi LK d0,3 V60 türü) ama net negatif. **Önerilen limit/StochRSI parametresi yok.**" % (
        wsum["rows"], wsum["pos"], wsum["lo_pos"], wsum["dpos"]))
    S_("- **LUNATRY 17 Ekim:** ilk HA adayı (01:15:30, P0'ın +%1,7 üstü) için yalnız d = %0,3 limit doldu (1 dk içinde; net +0,77…+6,02), d ≥ %0,6 limitler HİÇ dolmadı ve +%8'lik koşuyu kaçırdı; tek bildirim (02:03:29, P0'ın +%6,2 üstü) için limitler doldu ama fiyat sonra düştü (net −1,87…+0,14). Yani limit, kazanan koşuyu kaçırıp kaybedeni dolduruyor.")
    S_("")

    # ---------------------------------------------------------------- yöntem + sınırlar
    meth = []
    M = meth.append
    M("## 1. Yöntem\n")
    M("- **Veri:** `historical_candles` 1m/5m/15m, 19 Tem → 17 Eki 2026 06:00 (306 sembol; taker sütunları kullanılmadı). Zaman dilimi İstanbul (UTC+3). Pencereler (İstanbul günü): **W30** = 17 Eyl–16 Eki (birincil), **B1** 20 Tem–18 Ağu, **B2** 19 Ağu–17 Eyl, **B3** 18 Eyl–16 Eki (önceki çalışmalarla aynı 30 günlük bloklar).")
    M("- **StochRSI** (`app/rescan/stochrsi.py`, testli: `tests/test_stochrsi.py`): Wilder RSI(14) (ilk 14 değişimin ortalaması tohum, RMA); stoch = 100·(RSI − min14)/(max14 − min14), aralık 0 → 0; K = SMA3(stoch); D = SMA3(K). "
      "Grafik tarafında (frontend `IndicatorPicker.tsx`) StochRSI parametreleri (14/14/3/3, seviye 20) tanımlanmış, hesap kodu bu çalışmanın başlangıcında depoda henüz yoktu — tanım isteğe göre yazıldı; aralık 0 durumunda `technical_analysis._stoch_rsi` 50 döndürür, burada 0 (istenen tanım). "
      "**Ön sinyal** bar i'nin kapanışında: K[i−1] ≤ D[i−1], K[i] > D[i], K[i−1] < seviye (20 | 30) ve çekirdek i'de kırmızı (bearish & valid).")
    M("- **Çekirdek (RQK):** `app/rescan/rqk.py` varyant A (uygulama birebir; h = 8, r = 2, smoothColors = false, uygulama renk kuralı); ham mumlar (boşluk doldurulmadı). Bar i kapanışında renk bilinir; 'AL dönüşü' = kırmızı → yeşil.")
    M("- **Likit sembol filtresi (Çalışma A):** son kapanmış 5 dk barına göre 24 sa quote hacmi ≥ 5M TRY (olay tanımıyla aynı). Not: TRY değer kaybı yüzünden likit sembol sayısı zamanla artıyor (sinyal/gün B1 534 → B3 1 565 gibi artışlar kısmen bundandır). Çalışma B'de filtre yok (HA havuzu kendi seçimi).")
    M("- **Simülatör:** `app/rescan/exit_sim.py` (gerçekçi doluş; bu çalışmada geriye uyumlu `entry_slip_pct` eklendi, `tests/test_exit_sim.py`'de test). Giriş = sinyal + 60 sn sonraki ilk 1 dk açılışı × (1 + %0,15) (birincil) veya 0 sn / %0,05 (iyimser); stop: min(stop, bar açılışı) × (1 − kayma); TP tam seviye; aynı barda stop + TP → stop; zaman stopu kapanış × (1 − kayma); bacak başına %0,1125. Pencere 120 dk 1 dk barı.")
    M("- **İstatistik:** gün-kümeli standart hata; farkların SE'si bağımsız kabulle karekök toplamı (muhafazakâr). Walk-forward: seçim bloğunda, ölçüm diğer bloklarda.")
    M("- **Tekrarlanabilirlik:** `scripts/limitstoch_*.py` (ind → a1 → a3 → b rows/sim → report); `python scripts/limitstoch_report.py`. Çıktı: `work/limitstoch/report.md`.\n")
    lim = []
    Z = lim.append
    Z("## 6. Sınırlar\n")
    Z("- **Veri:** 90 gün, tek piyasa rejimi (TRY pariteleri, Temmuz–Ekim 2026); W30 yalnız bir ay. Notification kaynakları küçük (W30'da hepsi %d, trend_devam %d bölüm) → güç düşük; kararlar HA (≈ 20 bin bölüm) ve Çalışma A (yüz binlerce sinyal) üzerinde ağırlıklı." % (bs["NOTIF_all"].kind.tolist().count(0), bs["NOTIF_trend"].kind.tolist().count(0)))
    Z("- **Limit dolumu varsayımı:** düşük limitin KESİNLİKLE altına inince dolar ve dolum fiyatı limit; kuyruk önceliği, kısmi dolum, defter derinliği ve emrin gerçekte bar içi önce/sonra sırası modellenmedi. Dolum barında yükselişler yok sayıldı (kötümser). Gerçekte dolum oranı bu sayıdan düşük olabilir (fiyat limite değer ama emir sıranın arkasında kalır) — bu yalnız sonuçları KÖTÜLEŞTİRİR; yani 'hayır' kararını güçlendirir.")
    Z("- **Rastgele taban yanlılıkları:** (1) ve (2) 'herhangi bir sinyalden ≥ 2 sa uzak' koşulu geleceğe bakar: ön sinyal (düşüş dibi) olmayan anlar yükselişte olur → taban yukarı yanlı (5m ön sinyalde taban ≈ +0,1 net). (3)/(4) dışlamasızdır ama sinyallerin kendisini az miktarda içerir (sinyal oranı ≈ %2–4); (4) oynaklık eşleşmesi son 30 dk aralığıyla yaklaşıktır, yönü/momentumu eşleştirmez. "
      "Sinyal − taban farkları bu yüzden taban türüne duyarlıdır; ana kararlar mutlak net'e (< 0) dayanır, tabana bağlı değil.")
    Z("- **Çoklu karşılaştırma:** 12 küme × 24 çıkış; 73 giriş × 24 çıkış; 'en iyi hücre' tabloları iç-örneklem ve iyimser. Pozitif bir hücre olsaydı bile walk-forward gerekirdi; hiç pozitif yok.")
    Z("- **Kayma/gecikme:** sabit %0,15 ve 60 sn; düşük likit sembollerde gerçek kayma daha büyük olabilir (özellikle 1m ön sinyaller), yüksek likitlerde daha düşük. İyimser (0 sn/%0,05) senaryo da raporlandı: sonuç aynı.")
    Z("- **Çekirdek tanımı:** uygulamadaki kesik pencereli (son 8 bar) RQK; kanonik 25 bar pencere değil. 1m çekirdekte düz (hacimsiz) mumlar çekirdeği 'kırmızı' tutuyor (1m yeşil oranı %35). Frontend StochRSI kodu henüz yoktu → grafikteki ile BİREBİR eşleşme doğrulanamadı (yalnız isteğe göre tanım ve birim testleri).")
    Z("- **Hacim/uç durumlar:** 1 dk çıkış yolunda bar-içi sıra kötümser (stop önce). Sinyal sonrası 120 dk veri gerektiği için veri sonuna yakın sinyaller atıldı (yanlılık yaratmaz, sayıyı azaltır).")
    Z("- **Canlı koda dokunulmadı:** yalnız `app/rescan/stochrsi.py` (yeni), `app/rescan/exit_sim.py` (geriye uyumlu `entry_slip_pct`), testler ve `scripts/limitstoch_*.py` eklendi.\n")

    head = ["# Limit giriş + StochRSI ön sinyali — çekirdek dönüşünü önceden görür mü, kârlı giriş verir mi? (2026-10-17)\n",
            "Bu rapor `backend/scripts/limitstoch_report.py` tarafından üretilmiştir (%s). Çalışma çevrimdışıdır; canlı koda bağlanmaz.\n" % gen]
    text = "\n".join(head + summary + meth + a1_txt + a2_txt + a3_txt + b_txt + lim)
    (L.WORK / "report.md").write_text(text, encoding="utf-8")
    print("report.md yazıldı: %d karakter" % len(text))


if __name__ == "__main__":
    main()
