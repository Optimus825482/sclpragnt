"""policy7d_study.py sonuçlarından Türkçe rapor üretir (work/policy7d/report.md). Veri hesabı yapmaz; yalnız biçimlendirme + karar cümleleri.

Kullanım: render(res, args) — policy7d_study.main() çağırır. Tek başına: `python scripts/policy7d_report.py` (work/policy7d/parts.pkl okur).
"""
from __future__ import annotations

import math
import pickle
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=3))
ROOT = Path(__file__).resolve().parents[1]


def find(raw: list, prefix: str):
    for item in raw:
        if item[0].split(".")[0].strip() == prefix.split(".")[0].strip() and item[0].startswith(prefix):
            return item
    for item in raw:
        if item[0].startswith(prefix):
            return item
    return None


def netv(s: dict, key: str = "net_sl3_hz") -> tuple[float, float, int]:
    return s.get(key, (float("nan"), float("nan"), 0))


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return 100 * max(0.0, c - h), 100 * min(1.0, c + h)


def stage_line(raw: list, prefix: str, days: float) -> str:
    it = find(raw, prefix)
    if not it:
        return "n/a"
    label, s, sv, share = it
    if s["n"] == 0:
        return "%s: 0 bildirim" % label
    m, se, n = netv(s)
    h = s["hit_h"]
    return "%s: n=%d (%.1f/gün), isabet %.1f%% (%d/%d), net %+.2f%% ±%.2f, eski 'ulaştı'nın %d/%d'si kalır" % (
        label, s["n"], s["n"] / days, 100.0 * h[0] / max(1, h[1]), h[0], h[1], m, 1.96 * se if se == se else float("nan"), share[0], share[1])


def positives(raw: list, nmin: int = 100) -> list[str]:
    out = []
    for label, s, sv, share in raw:
        if s["n"] < nmin:
            continue
        for key, nm in (("net_sl3_hz", "H1"), ("net_slatr_60", "H2"), ("net_sl3_hz_opt", "H1-iyimser")):
            m, se, n = s[key]
            if m == m and m > 0:
                out.append("%s [%s]: net %+.2f (±%.2f), n=%d" % (label, nm, m, 1.96 * se, n))
    return out


def best_stage(raw: list, nmin: int = 100) -> str:
    best = None
    for label, s, sv, share in raw:
        if s["n"] < nmin:
            continue
        m, se, n = s["net_sl3_hz"]
        if m == m and (best is None or m > best[1]):
            best = (label, m, se, s["n"])
    if not best:
        return "–"
    return "%s (net %+.2f ±%.2f, n=%d)" % (best[0], best[1], 1.96 * best[2], best[3])


def render(res: dict, args) -> str:
    P = res["parts"]
    days7 = res["days7"]
    daysp = res["days_prev"]
    t_hi = res["t_hi"]
    t_last = res["t_last"]
    raw7 = res.get("raw7", [])
    rawp = res.get("rawp", [])
    rawh7 = res.get("rawh7", [])
    rawhp = res.get("rawhp", [])
    rawj = res.get("rawj", [])
    now = datetime.fromtimestamp(t_last, TZ).strftime("%d.%m.%Y %H:%M")
    hi = datetime.fromtimestamp(t_hi, TZ).strftime("%d.%m.%Y %H:%M")
    nv = res.get("n_valid", (0, 0))
    L: list[str] = []
    A = L.append
    A("# Bildirim politikası testi: push-only + ≥2 teyit + dinamik hedef + net ≥ %2 (7 gün + dayanıklılık)\n")
    A("Üretim: `backend/scripts/policy7d_study.py` (+ `app/rescan/dyn_target.py`, `tests/test_dyn_target.py`); veri son mum: %s (TRT); "
      "olay kesiti: %s (60 dk + pay sonuçlanabilsin diye). Çalışma çevrimdışıdır, canlı koda bağlanmaz.\n" % (now, hi))

    # ------------------------------------------------------------------ özet
    A("## 0. Özet ve karar\n")
    s0 = find(raw7, "0.")
    s1 = find(raw7, "1.")
    s2 = find(raw7, "2.")
    if s0 and s0[1]["n"]:
        pos7 = positives(raw7)
        posp = positives(rawp)
        posh = positives(rawh7) + positives(rawhp)
        n_cfg = sum(1 for x in raw7 if x[1]["n"] >= 100) + sum(1 for x in rawp if x[1]["n"] >= 100)
        A("- **Kısa cevap: HAYIR — önerilen politika bildirimleri kârlı yapmıyor, yalnızca sayıyı (ve dolayısıyla toplam zararı) azaltıyor.** "
          "Hiçbir aşamada (n ≥ 100) maliyet sonrası ortalama net pozitif çıkmadı: son 7 gün huni aşamalarında net-pozitif (n≥100) "
          "yapılandırma sayısı %d, önceki dönemde %d, Hız Avcısı aday setlerinde %d (toplam %d+ yapılandırma; çoklu karşılaştırma uyarısı geçerli)."
          % (len(pos7), len(posp), len(posh), n_cfg))
        A("- Mevcut sistem 7 günde: %s." % stage_line(raw7, "0.", days7))
        A("- Yalnız push: %s." % stage_line(raw7, "1.", days7))
        A("- Push + ≥2 kaynak: %s." % stage_line(raw7, "2.", days7))
        A("- En az kötü aşama (n≥100, H1): %s. Rastgele-giriş tabanı aynı çıkışlarla ≈ −0,52 / −0,53 (maliyet tabanı 0,525)." % (
            best_stage(raw7)))
        A("- **Neden:** (i) ölçülen şey 'hedefe dokunuş' = oynaklık; ATR/dinamik hedef büyüklüğü öngörür, yönü değil, ve sinyal sonrası ücretsiz brüt 60 dk getiri "
          "pozitif değil (son 7 günde −0,68 ±0,44 [rastgele −0,10], önceki dönemde −0,29 ±0,35 — bildirim yönlü avantaj taşımıyor, "
          "pompa sonrası geri çekilme eğilimi var; tablo C); (ii) başabaş için gereken isabet %45–60 iken gözlenen %5–40; (iii) hedefi küçülten her kural isabeti "
          "şişiriyor ('başarı' artıyor) ama net hedef %2'nin altına düştüğü için zaten gönderilmeyecek, gönderilen kısmın net hedefi ≥ %2 "
          "olunca isabet düşüyor (%5–15).")
    else:
        A("- (7 günlük bildirim seti oluşturulamadı.)")
    if raw7:
        def _n(prefix):
            it = find(raw7, prefix)
            return it[1]["n"] if it else 0
        A("- Net ≥ %%2 filtresi sonrası kalan bildirim (7 gün): push+eski hedef %d/%d, push+(a) %d, push+(b) %d, push+(c) %d (ampirik 60 dk MFE q60 hedefi ≈ %%0,8 olduğundan net ≥ %%2'yi hiç geçemez); "
          "≥2 kaynakla birlikte: eski hedef %d, (a) %d, (b) %d, (c) %d. Kalanların hiçbirinde ortalama net pozitif değil."
          % (_n("P4o"), _n("1."), _n("P4a"), _n("P4b"), _n("P4c"), _n("4o"), _n("4a"), _n("4b"), _n("4c")))
        A("- Dayanıklılık: 7 günde 'en az kötü' görünen P4a (−0,29) önceki haftalarda −0,77 / −0,89 / −0,60'a geri döner (haftalık tablo, §8); yani 7 günlük en iyi hücre şans eseri. "
          "Net ≥ %2'yi eski hedefle geçen bildirimler (4o/P4o) tüm haftalarda rastgeleden +0,05…+0,25 daha iyi ama net −0,27…−0,48 ile negatif.")
    A("- Yan fayda: ≥2 kaynak ve net ≥ %2 filtreleri günlük bildirim sayısını ve 'toplam net/gün' zararını belirgin biçimde düşürür (tablo B son sütun); "
      "bu 'yanlış alarm' azaltmasıdır, kârlılık değil. Ayrıntı ve rakamlar aşağıda.\n")
    A("- Veri notu: olay doğrulama oranı %d/%d (mum kapsamı/eksik); uygulamanın kendi 'Hedefe ulaştı' etiketi ile bizim ölçümümüz: %s.\n"
      % (nv[0], nv[1], res.get("app_vs_mine", "–")))

    # ------------------------------------------------------------------ yöntem
    A("## 1. Yöntem\n")
    A("""- **Olay kümeleri.** (i) *Gönderilen bildirimler*: `monitoring_notifications` (DB, 10.10 → 15.10 22:30; legacy `global_lead_lag` modu dışarıda) + üretim Raporlar sayfasından kopyalanan 83 satır (15.10 22:30 → 17.10; push/panel, kaynaklar Türkçe→İngilizce eşlenir). (ii) *Aday kümeleri*: `velocity_candidates` (Hız Avcısı, sıra ≤ 10, 60 dk soğuma) 7 gün + önceki dönem; `unified_candidate_outcomes` (birleşik tarama journal'ı; **yalnız 14.10 05:30 → 16.10 01:55 dolu**, sonrası test kirliliği) — 30 gün geriye journal YOK, dayanıklılık bildirim tablosu ve Hız Avcısı adaylarıyla ölçüldü.
- **Teyit sayısı.** `sources` alanındaki farklı kaynak sayısı (velocity=Hız, jump=Sıçrama, early=Erken uyarı, rising=Yükseliş eğilimi). *Aile* sayısı: jump+early tek dedektör çifti sayılır (neredeyse hep birlikte gelirler) → bağımsız teyit = {velocity, jump/early, rising}. Kaynak bilgisi NULL olan satırlar (özellikle 26.09–11.10 arası ve `llm_ikinci_goz`) ≥2 aşamasında dışarıda kalır; önceki dönem hunisi yalnız kaynak bilgisi olan satırlarla kurulmuştur.
- **Dinamik hedef (yalnız sinyal anı bilgisi, `app/rescan/dyn_target.py`).** (a) k × ATR14(5m)% × √(ufuk/5), k=1,5 (k=1 ve 2 varyant tablosunda); (b) min((a), 0,9 × en yakın direnç mesafesi), direnç = son 60 dk en yüksek ve 24 sa en yüksek (fiyatın ≥ %0,3 üstündekiler; fiyat hepsinin üstündeyse direnç yok → (a)); (c) sembolün kendi **60 dk MFE**'sinin ÖNCEKİ 14 günlük %60'lık yüzdeliği (ufuk-eşlemeli (c') varyant tablosunda). Nedensellik birim testle doğrulandı (t'den sonraki bar bozulunca hedef değişmiyor). **Net hedef = brüt − (2×%0,1125 ücret + %0,15 giriş + %0,15 çıkış kayması) = brüt − 0,525** (iyimser kayma %0,05 için 0,325). Net ≥ %2 ⇔ brüt ≥ %2,525.
- **Simülatör (`app/rescan/exit_sim.py`).** Giriş = sinyal + 60 sn sonraki ilk 1 dk barın açılışı × (1 + %0,15); TP = o aşamanın hedefi (dolan girişe göre, tam TP fiyatından dolar), aynı barda stop ve TP görülürse stop kazanır, zaman stopu/stop dolumları %0,15 kaymalı, bacak başına %0,1125 ücret. **H1** = SL %3, süre = bildirim ufku (5/15 dk); **H2** = SL 1,5×ATR (0,25'e yuvarlı, [0,75; 3]), süre 60 dk. Tablo C ayrıca iyimser kayma (%0,05) ve ücretsiz brüt 60 dk getiriyi verir.
- **İsabet (kullanıcının ölçütü).** İlk tam 1 dk bar sinyalden sonra açılır; fiyat referansı o barın açılışı; isabet = ufuk (veya 60 dk) içinde en yüksek ≥ hedef. Bu ölçüm uygulamanınkinden daha sıkıdır (uygulama etiketi ~%25, bizimki ~%18; ikisi %86 uyumlu).
- **Rastgele-giriş tabanı.** Her olay için 40 rastgele an: aynı sembol, aynı İstanbul saati dilimi, başka günler (o dönem penceresi içinde), sembolün TÜM olaylarından ≥ 2 sa uzak; aynı hedef kuralı (dinamik kuralda KENDİ anının hedefi, net ≥ 2 filtresi uygulanıyorsa o da) ve aynı çıkışlar. 'rastgele' = tüm havuz; 'oyn.-eşl.' = son 30 dk yüksek-düşük aralığı ±%25'e (en az 0,15 puan) eşleşen en yakın ≤ 20 an (sinyal bir pompa anıdır; sıradan rastgele an daha sakin olduğundan isabet farkını şişirir — **fark sütunlarını 'oyn.-eşl.' ile yorumlayın**).
- **İstatistik.** Net ortalama ±%95 (gün-kümeli standart hata); fark = sinyal − taban, SE'ler bağımsız kabul (muhafazakâr). İsabet için Wilson %95. Aynı sembolün art arda bildirimleri bağımsız değildir (gün-kümeleme kısmen telafi eder).\n""")

    # ------------------------------------------------------------------ başabaş
    A("## 2. 'Hedefe ulaştı' neden kâr ölçütü değil — başabaş aritmetiği\n")
    A("Yalnız TP/SL ile kapanan bir işlemde başabaş isabet oranı (maliyetler dâhil):\n")
    A(P.get("breakeven", ""))
    A("Gözlenen isabet (7 gün, push): aşağıdaki huni tablosunda. Net ≥ %2 koşulu hedefi ≥ %2,5'e iter; başabaş için SL %3 iken ≈ %60, SL %1,5 iken ≈ %45–48 isabet "
      "gerekir; gözlenen ufuk içi isabet %5–15, 60 dk içi %25–45 civarındadır (ve 60 dk içinde SL de vurulur). Hedefi küçültmek isabeti yükseltir ama "
      "kazancı da küçültür (hedef %0,8 → kazanç ≈ +0,6), kayıp ise ~%0,4+SL'dir.\n")
    A("### Sinyal anı bilgisi neyi öngörüyor? (Spearman, olay satırları)\n")
    A("7 gün, push bildirimleri:\n")
    A(P.get("info7", ""))
    A("Önceki dönem:\n")
    A(P.get("infop", ""))
    A("Okuma: ATR/dinamik hedef **büyüklüğü** (MFE ve |MAE| birlikte) öngörür, **yönü** (brüt 60 dk getiri) öngörmez. Dinamik hedef bu yüzden 'ne kadar "
      "oynayabilir'i iyi tahmin eder, 'yukarı mı gidecek'i değil; bu da hedefe ulaşma olasılığını ayarlar ama beklenen getiriyi pozitif yapmaz.\n")

    # ------------------------------------------------------------------ huni 7 gün
    A("## 3. Politika hunisi — son 7 gün (%s → %s), gönderilen bildirimler\n" % ("10.10", hi))
    A("A) Sayım ve isabet (hit = ufuk/60 dk içinde stage hedefine dokunuş; rastgele = oyn.-eşl. taban, **aynı hedef kuralıyla**):\n")
    A(P.get("huni7A", ""))
    A("B) Net PnL, H1 (SL %3, süre = ufuk; gerçekçi doluş; 'rastgele' = sembol/saat tabanı, 'oyn.-eşl.' = oynaklık eşlemeli; 'toplam net/gün' = n/gün × ort. net, yani bu bildirimlerin her birine 1 birim girilseydi günlük toplam % puan):\n")
    A(P.get("huni7B", ""))
    A("C) H2, iyimser kayma ve ücretsiz brüt 60 dk getiri (yön avantajı var mı?):\n")
    A(P.get("huni7C", ""))
    A("Satır etiketleri: `0` mevcut sistem; `1` panel kaldırıldı; `2/2b/2c/2d` teyit sayısı eşikleri; `3a/b/c` dinamik hedef (≥2 kaynak üzerinde); `4a/b/c` + net hedef ≥ %2; "
      "`4o` eski hedefle net ≥ %2; `P…` aynı kurallar ≥2 kaynak şartı OLMADAN (push üzerinde, n büyük kalsın diye); `T1/T2` yalnız tek filtre (push+panel tabanında).\n")

    # ------------------------------------------------------------------ teyit
    A("## 4. Teyit sayısı — daha büyük kümede (n ve güven aralıklarıyla)\n")
    lo1, hi1 = wilson(1, 1)
    lo2, hi2 = wilson(3, 3)
    A("Üretim ekranındaki '4'lü teyit %%100 (1/1)' **istatistiksel olarak anlamsızdır**: n=1 için Wilson %%95 aralığı [%.0f%%–%.0f%%], 3/3 için bile [%.0f%%–%.0f%%]. "
      "Aşağıda aynı ölçüt 17.09 → 17.10 tüm bildirimlerde (kaynak bilgisi olan satırlar; 'başlıkta 4'LÜ TEYİT' grubu DB satırlarında başlık metninden) ölçüldü. "
      "NOT: başlıktaki '4'LÜ TEYİT' etiketi Master-Surge 4 katman teyididir (`is_4way` = confluence_4way veya ≥4 kaynak); `sources` içindeki dört kaynakla aynı şey DEĞİLDİR.\n"
      % (lo1, hi1, lo2, hi2))
    A("Tüm dönem (17.09 → 17.10):\n")
    A(P.get("confirm_all", ""))
    A("Son 7 gün:\n")
    A(P.get("confirm_7", ""))
    A("Okuma: teyit sayısı arttıkça ufuk içi isabet yükselir (1 kaynak %17, 3 kaynak %10, **4 kaynak %25 [20–31], n=223**) fakat bu, teyitli bildirimlerin daha küçük ortalama hedef taşıması "
      "(7 günde 4 kaynakta ort. hedef %2,35 vs %3,1) ve güçlü pompa anlarında gelmesiyle açıklanır; net PnL'de teyit sayısı bir fark yaratmaz (4 kaynak: −0,61 ±0,24, rastgele farkı "
      "[−0,32; +0,17]). Başlığında '4'LÜ TEYİT' yazan 613 bildirimde isabet %10,1 [8–13], net −0,46 ±0,09 — yani üretimdeki tek '4'lü teyit 1/1' gözleminin büyük kümede karşılığı "
      "yok. Tek anlamlı ayrım **mod**: yalnız `trend_devam` modu tüm dönemde rastgeleden iyi (+0,14 [+0,01; +0,27], isabet %21,5) ama net yine −0,38 ±0,13; `notr` modu belirgin kötü (−0,89).\n")

    # ------------------------------------------------------------------ dinamik varyant
    A("## 5. Dinamik hedef varyantları — karşılaştırma\n")
    A("Her satırda hedef kuralı değişir; 'net≥2 filtre = evet' satırı yalnız net hedefi ≥ %2 olanları bırakır. Hit, kuralın KENDİ hedefine göredir; rastgele sütunu aynı kuralın rastgele anlarda uygulanmışı.\n")
    A("**Push bildirimleri, son 7 gün:**\n")
    A(P.get("variants_push", ""))
    A("**Push + ≥2 kaynak, son 7 gün:**\n")
    A(P.get("variants_two", ""))
    A("**Push bildirimleri, önceki dönem (17.09 → 09.10, kaynak bilgisi aranmadı):**\n")
    A(P.get("variants_push_prev", ""))

    # ------------------------------------------------------------------ net>=2 etkisi
    A("## 6. Net ≥ %2 filtresinin etkisi\n")
    for pref in ("P4o", "P4a", "P4b", "P4c", "4o", "4a", "4b"):
        A("- " + stage_line(raw7, pref, days7))
    A("\nNet hedef ≥ %2 koşulu bildirimlerin ~%40–70'ini eler ama kalanlarda isabet düşer (hedef büyüdüğü için) ve ortalama net (7 günde −0,3…−0,5, önceki dönemde −0,4…−0,7) hâlâ negatiftir; "
      "H2'de (60 dk, ATR stop) filtreli kümelerin net'i daha da kötü ve belirsizdir (n küçük). Filtre 'umut verici görünen ama zaten ulaşılması zor hedefleri' ayıklar; "
      "ulaşılabilir hedeflerin net'i ise %2'nin altındadır — iki koşul birlikte sağlanan örneklerde hit %5–15, başabaş ise %45–60.\n")

    # ------------------------------------------------------------------ adaylar
    A("## 7. Aday kümeleri — politika NE gönderirdi?\n")
    A("**Hız Avcısı adayları (velocity_candidates; tek kaynak = Hız, dolayısıyla teyit şartı uygulanamaz; yalnız dinamik hedef + net ≥ %2 aşamaları).**\n")
    A("Son 7 gün:\n")
    A(P.get("ha7A", ""))
    A(P.get("ha7B", ""))
    A(P.get("ha7C", ""))
    A("Önceki dönem (21.09 → 09.10):\n")
    A(P.get("hapA", ""))
    A(P.get("hapB", ""))
    A("**Birleşik tarama journal'ı** (yalnız 14.10 05:30 → 16.10 01:55, **~1,85 gün**; satırlar çoğunlukla push KARARI almamış gölge adaylardır — "
      "short_squeeze/pulse/snapback kaynakları bildirim kaynağı değildir; 30 dk sembol soğuması uygulandı):\n")
    A(P.get("jrA", ""))
    A(P.get("jrB", ""))

    # ------------------------------------------------------------------ dayanıklılık
    A("## 8. Dayanıklılık — önceki dönem ve haftalık\n")
    A("Önceki dönem (17.09 → 09.10) bildirim hunisi (**yalnız kaynak bilgisi olan satırlar**; ilk hafta 17–25.09 `sources` hep dolu, 26.09–11.10 arası ~%20–35'i NULL):\n")
    A(P.get("hunipA", ""))
    A(P.get("hunipB", ""))
    A(P.get("hunipC", ""))
    A("Haftalık tablo (net H1, aynı aşamalar; H-3 haftası 9 gün ve düşük n):\n")
    A(P.get("weekly", ""))

    # ------------------------------------------------------------------ üretim 83 satır
    A("## 9. Üretimdeki 83 satır (15.10 22:30 → 17.10)\n")
    A(P.get("prod", ""))
    A("Not: Bu satırlardaki 'Hedefe ulaştı' etiketi uygulamanın kendisidir; 'bizim hesap' sütunu yukarıdaki katı ölçümdür. Son saatlerdeki 'Bekliyor' satırlar ve 60+10 dk pencere "
      "dolmayanlar dışarıdadır. Tek başına bu örnekle (n≈80, yalnızca ~8 satır ≥2 kaynaklı) hiçbir politika sonucu çıkarılamaz.\n")

    # ------------------------------------------------------------------ karar
    A("## 10. Karar\n")
    pos_any = positives(raw7) + positives(rawp) + positives(rawh7) + positives(rawhp)
    if pos_any:
        A("Net-pozitif görünen yapılandırmalar (n ≥ 100) — **dikkat: çoklu karşılaştırma ve güven aralıklarına bakılmalı**:\n")
        for x in pos_any:
            A("- " + x)
    else:
        A("**Net-pozitif (n ≥ 100) hiçbir yapılandırma yok; bu yüzden 'kesin parametre' önerilemez.** Önerilen politikanın tüm bileşenleri (push-only, ≥2/≥3/≥4 teyit, "
          "ATR/direnç/ampirik dinamik hedef, net ≥ %2 filtresi, bunların birleşimi) 7 günde ve önceki dönemde, gerçekçi doluşla (60 sn + %0,15 kayma + %0,1125 ücret) "
          "bildirim başına ortalama net **negatif** kalır; rastgele giriş tabanı ile fark çoğunlukla sıfırdan ayırt edilemez.\n")
    A("""
**Hangi parça işe yarıyor (kârlılık değil, yanlış alarm / zarar azaltma):**

1. *Panel bildirimlerini kaldırmak*: panel bildirimleri push'tan daha kötü (net −0,8 vs −0,5; §4 tablosunda `panel` satırı) ve sayıca az; kaldırmak toplam zararı biraz azaltır, ana akışı değiştirmez.
2. *≥2 kaynak teyidi*: günlük bildirim sayısını ~%70 azaltır (≈70 → ≈20/gün), ortalama net −0,52 → −0,46 gibi küçük bir iyileşme (fark güven aralığı sıfırı içerir); 'toplam net/gün' zararı ≈ −36 puandan ≈ −9 puana iner (sadece sayı azaldığı için). Teyit sayısı ile isabet artar ama net değişmez.
3. *Dinamik hedef*: hedefi küçülttüğü için 'başarı' (hit) şişer (örn. (c) %50+), net hedef ≥ %2 koşulu ile birleşince isabet tekrar %5–15'e iner. Hedef büyüklüğü **oynaklığı** iyi öngörür (ρ≈0,3–0,4), yönü öngörmez.
4. *Net ≥ %2*: yalnızca matematiksel tutarlılık sağlar (gösterilen hedef maliyet sonrası anlamlı olur); kârlılığı pozitife çevirmez.

**Önerilen yol:** (a) 'başarı' ölçütünü 'hedefe dokunuş' yerine **maliyet sonrası realize net PnL / beklenen değer** yapın (Raporlar'da bildirim başına net ve rastgele tabana göre fark); (b) bildirimleri 'al' sinyali olarak sunmayın — veri, sinyal sonrası brüt 60 dk sürüklenmenin pozitif olmadığını (son 7 günde belirgin negatif) söylüyor (pompa kovalama); (c) ≥2 teyit + net ≥ %2'yi 'kalite filtresi' olarak (gürültüyü azaltmak için) kullanmak isterseniz bunu kârlılık iddiası olmadan yapın; (d) gerçek bir avantaj için ek, yönü öngören bir girdi (ör. taker alım baskısı, emir defteri derinliği; bu çalışmada ölçülmedi) ve out-of-sample doğrulama gerekir.
""")

    # ------------------------------------------------------------------ sınırlar
    A("## 11. Sınırlar\n")
    A("""- **Örneklem:** 7 günlük pencere ≈ 575 gönderilen bildirim; ≥2 kaynak ≈ 150, ≥4 kaynak ≈ 22 (güven aralıkları geniş); dinamik+net≥2 aşamalarında rastgele taban çok küçük (rastgele anlar nadiren ATR-yüksek) — fark sütunları o satırlarda zayıf, mutlak net yine ölçülmüştür.
- **Aday kümeleri:** birleşik tarama journal'ı yalnız ~1,85 gün dolu (sonrası test kirliliği: LOWTRY/MIDTRY/A/B satırları filtrelendi); 30 gün geriye journal analizi yapılamadı. Hız Avcısı adayları tek kaynaklıdır; çoklu-kaynak teyidi aday düzeyinde yeniden kurulamadı (jump/early/rising dedektörlerinin geçmiş tekrar-oynatması yok).
- **Kaynak alanı:** önceki dönemde (özellikle 26.09–11.10) `sources` NULL olan satırlar ≥2 aşamasından dışarıda; `llm_ikinci_goz` modunun tüm satırları NULL. Legacy `global_lead_lag` modu (28.09–07.10, 717 satır) çıkarıldı.
- **Ölçüm:** olay zamanı DB'de saniye çözünürlüklü, üretim satırlarında dakika çözünürlüklü (+30 sn varsayıldı); isabet ölçümümüz uygulamanınkinden sıkı (başlangıç sonraki dakika barı); dolu bar yok → flat mum doldurma; aynı sembolün art arda bildirimleri bağımsız değil (gün-kümeleme tam telafi etmez; 60 dk tekilleştirme ayrıca uygulanmadı, bildirimlerin kendi soğuması geçerli).
- **Simülatör:** TP tam fiyattan dolar (limit emri varsayımı), stop-önce bar içi sıra, sabit %0,15 kayma; gerçek derinlik/kayma sembole göre değişir (likit olmayan TRY çiftlerinde kötüleşir). 60 sn giriş gecikmesi ölçülmüş-gerçeğe yakın varsayım; 0 sn gecikmenin etkisi ayrıca sınanmadı (yalnız kayma duyarlılığı: tablo C).
- **Dinamik hedef:** k, direnç payı (0,9), tolerans (%0,3), yüzdelik (q60) tek nokta seçimleridir; k∈{1; 1,5; 2} için tablo verildi ama başka parametre ızgarası taranmadı (bu bilinçli: taranırsa çoklu-karşılaştırma yanlılığı artar). (c) için 14 günlük geçmiş en az 500 çapa ister.
- **Gün-kümeli SE:** journal setinde yalnız 2–3 gün olduğundan ±değerleri (özellikle ±0,00–0,02 olanlar) güvenilmezdir; küçük n'li taban satırlarında (n<30) fark sütunları göstermeliktir.
- **Çoklu karşılaştırma:** ~20 aşama × 2 dönem × 3 çıkış yapısı gösterildi; tek tek yorumlanan küçük farklar (+0,1 civarı) anlamlı sayılmamalı.
- **Rejim:** tek 7+23 günlük dönem; farklı piyasa rejimlerinde sonuçlar değişebilir (önceki 90 gün çalışmalarıyla tutarlı: sürüklenme negatif).
""")
    return "\n".join(L)


def main() -> int:
    d = pickle.load(open(ROOT / "work" / "policy7d" / "parts.pkl", "rb"))

    class _A:
        pass
    out = render(d, _A())
    (ROOT / "work" / "policy7d" / "report.md").write_text(out, encoding="utf-8")
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
