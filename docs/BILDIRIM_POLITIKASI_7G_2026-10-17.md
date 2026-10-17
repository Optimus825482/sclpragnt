# Bildirim politikası testi: push-only + ≥2 teyit + dinamik hedef + net ≥ %2 (7 gün + dayanıklılık)

Üretim: `backend/scripts/policy7d_study.py` (+ `app/rescan/dyn_target.py`, `tests/test_dyn_target.py`); veri son mum: 17.10.2026 15:33 (TRT); olay kesiti: 17.10.2026 14:23 (60 dk + pay sonuçlanabilsin diye). Çalışma çevrimdışıdır, canlı koda bağlanmaz.

## 0. Özet ve karar

- **Kısa cevap: HAYIR — önerilen politika bildirimleri kârlı yapmıyor, yalnızca sayıyı (ve dolayısıyla toplam zararı) azaltıyor.** Hiçbir aşamada (n ≥ 100) maliyet sonrası ortalama net pozitif çıkmadı: son 7 gün huni aşamalarında net-pozitif (n≥100) yapılandırma sayısı 0, önceki dönemde 0, Hız Avcısı aday setlerinde 0 (toplam 36+ yapılandırma; çoklu karşılaştırma uyarısı geçerli).
- Mevcut sistem 7 günde: 0. Mevcut: gönderilen tümü (push+panel): n=575 (75.7/gün), isabet 14.4% (83/575), net -0.54% ±0.23, eski 'ulaştı'nın 83/83'si kalır.
- Yalnız push: 1. + yalnız push (panel kaldırıldı): n=527 (69.3/gün), isabet 14.4% (76/527), net -0.52% ±0.23, eski 'ulaştı'nın 76/83'si kalır.
- Push + ≥2 kaynak: 2. + ≥2 farklı kaynak: n=151 (19.9/gün), isabet 17.9% (27/151), net -0.46% ±0.20, eski 'ulaştı'nın 27/83'si kalır.
- En az kötü aşama (n≥100, H1): P4a. push + (a) + net ≥ %2 (net -0.29 ±0.39, n=276). Rastgele-giriş tabanı aynı çıkışlarla ≈ −0,52 / −0,53 (maliyet tabanı 0,525).
- **Neden:** (i) ölçülen şey 'hedefe dokunuş' = oynaklık; ATR/dinamik hedef büyüklüğü öngörür, yönü değil, ve sinyal sonrası ücretsiz brüt 60 dk getiri pozitif değil (son 7 günde −0,68 ±0,44 [rastgele −0,10], önceki dönemde −0,29 ±0,35 — bildirim yönlü avantaj taşımıyor, pompa sonrası geri çekilme eğilimi var; tablo C); (ii) başabaş için gereken isabet %45–60 iken gözlenen %5–40; (iii) hedefi küçülten her kural isabeti şişiriyor ('başarı' artıyor) ama net hedef %2'nin altına düştüğü için zaten gönderilmeyecek, gönderilen kısmın net hedefi ≥ %2 olunca isabet düşüyor (%5–15).
- Net ≥ %2 filtresi sonrası kalan bildirim (7 gün): push+eski hedef 323/527, push+(a) 276, push+(b) 154, push+(c) 0 (ampirik 60 dk MFE q60 hedefi ≈ %0,8 olduğundan net ≥ %2'yi hiç geçemez); ≥2 kaynakla birlikte: eski hedef 78, (a) 77, (b) 40, (c) 0. Kalanların hiçbirinde ortalama net pozitif değil.
- Dayanıklılık: 7 günde 'en az kötü' görünen P4a (−0,29) önceki haftalarda −0,77 / −0,89 / −0,60'a geri döner (haftalık tablo, §8); yani 7 günlük en iyi hücre şans eseri. Net ≥ %2'yi eski hedefle geçen bildirimler (4o/P4o) tüm haftalarda rastgeleden +0,05…+0,25 daha iyi ama net −0,27…−0,48 ile negatif.
- Yan fayda: ≥2 kaynak ve net ≥ %2 filtreleri günlük bildirim sayısını ve 'toplam net/gün' zararını belirgin biçimde düşürür (tablo B son sütun); bu 'yanlış alarm' azaltmasıdır, kârlılık değil. Ayrıntı ve rakamlar aşağıda.

- Veri notu: olay doğrulama oranı 2868/2868 (mum kapsamı/eksik); uygulamanın kendi 'Hedefe ulaştı' etiketi ile bizim ölçümümüz: uygulama=ulaştı & bizim=ulaştı: 96; yalnız uygulama: 79; yalnız bizim: 28; ikisi de ulaşmadı: 575 (n=778, uyum 86.2%).

## 1. Yöntem

- **Olay kümeleri.** (i) *Gönderilen bildirimler*: `monitoring_notifications` (DB, 10.10 → 15.10 22:30; legacy `global_lead_lag` modu dışarıda) + üretim Raporlar sayfasından kopyalanan 83 satır (15.10 22:30 → 17.10; push/panel, kaynaklar Türkçe→İngilizce eşlenir). (ii) *Aday kümeleri*: `velocity_candidates` (Hız Avcısı, sıra ≤ 10, 60 dk soğuma) 7 gün + önceki dönem; `unified_candidate_outcomes` (birleşik tarama journal'ı; **yalnız 14.10 05:30 → 16.10 01:55 dolu**, sonrası test kirliliği) — 30 gün geriye journal YOK, dayanıklılık bildirim tablosu ve Hız Avcısı adaylarıyla ölçüldü.
- **Teyit sayısı.** `sources` alanındaki farklı kaynak sayısı (velocity=Hız, jump=Sıçrama, early=Erken uyarı, rising=Yükseliş eğilimi). *Aile* sayısı: jump+early tek dedektör çifti sayılır (neredeyse hep birlikte gelirler) → bağımsız teyit = {velocity, jump/early, rising}. Kaynak bilgisi NULL olan satırlar (özellikle 26.09–11.10 arası ve `llm_ikinci_goz`) ≥2 aşamasında dışarıda kalır; önceki dönem hunisi yalnız kaynak bilgisi olan satırlarla kurulmuştur.
- **Dinamik hedef (yalnız sinyal anı bilgisi, `app/rescan/dyn_target.py`).** (a) k × ATR14(5m)% × √(ufuk/5), k=1,5 (k=1 ve 2 varyant tablosunda); (b) min((a), 0,9 × en yakın direnç mesafesi), direnç = son 60 dk en yüksek ve 24 sa en yüksek (fiyatın ≥ %0,3 üstündekiler; fiyat hepsinin üstündeyse direnç yok → (a)); (c) sembolün kendi **60 dk MFE**'sinin ÖNCEKİ 14 günlük %60'lık yüzdeliği (ufuk-eşlemeli (c') varyant tablosunda). Nedensellik birim testle doğrulandı (t'den sonraki bar bozulunca hedef değişmiyor). **Net hedef = brüt − (2×%0,1125 ücret + %0,15 giriş + %0,15 çıkış kayması) = brüt − 0,525** (iyimser kayma %0,05 için 0,325). Net ≥ %2 ⇔ brüt ≥ %2,525.
- **Simülatör (`app/rescan/exit_sim.py`).** Giriş = sinyal + 60 sn sonraki ilk 1 dk barın açılışı × (1 + %0,15); TP = o aşamanın hedefi (dolan girişe göre, tam TP fiyatından dolar), aynı barda stop ve TP görülürse stop kazanır, zaman stopu/stop dolumları %0,15 kaymalı, bacak başına %0,1125 ücret. **H1** = SL %3, süre = bildirim ufku (5/15 dk); **H2** = SL 1,5×ATR (0,25'e yuvarlı, [0,75; 3]), süre 60 dk. Tablo C ayrıca iyimser kayma (%0,05) ve ücretsiz brüt 60 dk getiriyi verir.
- **İsabet (kullanıcının ölçütü).** İlk tam 1 dk bar sinyalden sonra açılır; fiyat referansı o barın açılışı; isabet = ufuk (veya 60 dk) içinde en yüksek ≥ hedef. Bu ölçüm uygulamanınkinden daha sıkıdır (uygulama etiketi ~%25, bizimki ~%18; ikisi %86 uyumlu).
- **Rastgele-giriş tabanı.** Her olay için 40 rastgele an: aynı sembol, aynı İstanbul saati dilimi, başka günler (o dönem penceresi içinde), sembolün TÜM olaylarından ≥ 2 sa uzak; aynı hedef kuralı (dinamik kuralda KENDİ anının hedefi, net ≥ 2 filtresi uygulanıyorsa o da) ve aynı çıkışlar. 'rastgele' = tüm havuz; 'oyn.-eşl.' = son 30 dk yüksek-düşük aralığı ±%25'e (en az 0,15 puan) eşleşen en yakın ≤ 20 an (sinyal bir pompa anıdır; sıradan rastgele an daha sakin olduğundan isabet farkını şişirir — **fark sütunlarını 'oyn.-eşl.' ile yorumlayın**).
- **İstatistik.** Net ortalama ±%95 (gün-kümeli standart hata); fark = sinyal − taban, SE'ler bağımsız kabul (muhafazakâr). İsabet için Wilson %95. Aynı sembolün art arda bildirimleri bağımsız değildir (gün-kümeleme kısmen telafi eder).

## 2. 'Hedefe ulaştı' neden kâr ölçütü değil — başabaş aritmetiği

Yalnız TP/SL ile kapanan bir işlemde başabaş isabet oranı (maliyetler dâhil):

| Hedef % (dolan girişe göre) | SL % | kazanç (net) | kayıp (net, stop kaymalı) | başabaş isabet (yalnız TP/SL, zaman stopu yok) |
|---|---|---|---|---|
| 2.0 | 1.5 | +1.77 | 1.88 | 51% |
| 2.0 | 3.0 | +1.77 | 3.38 | 66% |
| 2.5 | 1.5 | +2.27 | 1.88 | 45% |
| 2.5 | 3.0 | +2.27 | 3.38 | 60% |
| 3.0 | 1.5 | +2.77 | 1.88 | 40% |
| 3.0 | 3.0 | +2.77 | 3.38 | 55% |
| 4.0 | 1.5 | +3.77 | 1.88 | 33% |
| 4.0 | 3.0 | +3.77 | 3.38 | 47% |

Gözlenen isabet (7 gün, push): aşağıdaki huni tablosunda. Net ≥ %2 koşulu hedefi ≥ %2,5'e iter; başabaş için SL %3 iken ≈ %60, SL %1,5 iken ≈ %45–48 isabet gerekir; gözlenen ufuk içi isabet %5–15, 60 dk içi %25–45 civarındadır (ve 60 dk içinde SL de vurulur). Hedefi küçültmek isabeti yükseltir ama kazancı da küçültür (hedef %0,8 → kazanç ≈ +0,6), kayıp ise ~%0,4+SL'dir.

### Sinyal anı bilgisi neyi öngörüyor? (Spearman, olay satırları)

7 gün, push bildirimleri:

| Sinyal anı özelliği (n=527) | MFE ufuk % | MFE 60 dk % | |MAE| 60 dk % | brüt 60 dk getiri % (yön) |
|---|---|---|---|---|
| ATR14(5m) % | +0.35 | +0.32 | +0.44 | -0.14 |
| hedef (a) k=1.5 | +0.40 | +0.32 | +0.43 | -0.13 |
| hedef (b) k=1.5 | +0.17 | +0.14 | +0.33 | -0.12 |
| hedef (c) ampirik | +0.00 | +0.06 | -0.11 | +0.11 |
| eski hedef (sabit) | -0.22 | -0.19 | -0.18 | +0.04 |
| direnç payı % | -0.06 | -0.09 | +0.06 | -0.06 |

Önceki dönem:

| Sinyal anı özelliği (n=1531) | MFE ufuk % | MFE 60 dk % | |MAE| 60 dk % | brüt 60 dk getiri % (yön) |
|---|---|---|---|---|
| ATR14(5m) % | +0.42 | +0.39 | +0.57 | -0.12 |
| hedef (a) k=1.5 | +0.43 | +0.39 | +0.57 | -0.13 |
| hedef (b) k=1.5 | +0.20 | +0.22 | +0.30 | -0.05 |
| hedef (c) ampirik | -0.03 | -0.04 | -0.12 | +0.11 |
| eski hedef (sabit) | +0.00 | -0.03 | +0.01 | -0.00 |
| direnç payı % | -0.16 | -0.10 | -0.21 | +0.10 |

Okuma: ATR/dinamik hedef **büyüklüğü** (MFE ve |MAE| birlikte) öngörür, **yönü** (brüt 60 dk getiri) öngörmez. Dinamik hedef bu yüzden 'ne kadar oynayabilir'i iyi tahmin eder, 'yukarı mı gidecek'i değil; bu da hedefe ulaşma olasılığını ayarlar ama beklenen getiriyi pozitif yapmaz.

## 3. Politika hunisi — son 7 gün (10.10 → 17.10.2026 14:23), gönderilen bildirimler

A) Sayım ve isabet (hit = ufuk/60 dk içinde stage hedefine dokunuş; rastgele = oyn.-eşl. taban, **aynı hedef kuralıyla**):

| Aşama | n | n/gün | ort. hedef % | hit (ufuk) [Wilson95] | rastgele hit (oyn.-eşl.) | hit 60 dk | rastgele hit60 (oyn.-eşl.) | eski 'ulaştı' payı |
|---|---|---|---|---|---|---|---|---|
| 0. Mevcut: gönderilen tümü (push+panel) | 575 | 75.7 | 3.13 | 14.4% [12–18] (83/575) | 0.5% [0–1] (5/939) | 40.5% [37–45] (233/575) | 5.5% [4–7] (52/939) | 83/83 (100%) |
| 1. + yalnız push (panel kaldırıldı) | 527 | 69.3 | 3.15 | 14.4% [12–18] (76/527) | 0.3% [0–1] (3/890) | 41.6% [37–46] (219/527) | 5.1% [4–7] (45/890) | 76/83 (92%) |
| 2. + ≥2 farklı kaynak | 151 | 19.9 | 3.07 | 17.9% [13–25] (27/151) | 0.2% [0–1] (1/421) | 43.7% [36–52] (66/151) | 2.4% [1–4] (10/421) | 27/83 (33%) |
| 2b. + ≥3 kaynak | 129 | 17.0 | 2.94 | 20.2% [14–28] (26/129) | 0.3% [0–2] (1/286) | 48.1% [40–57] (62/129) | 2.4% [1–5] (7/286) | 26/83 (31%) |
| 2c. + ≥4 kaynak | 22 | 2.9 | 2.35 | 36.4% [20–57] (8/22) | 0.0% [0–56] (0/3) | 63.6% [43–80] (14/22) | 0.0% [0–56] (0/3) | 8/83 (10%) |
| 2d. + ≥2 aile (jump+early tek sayılır) | 129 | 17.0 | 2.94 | 20.2% [14–28] (26/129) | 0.3% [0–2] (1/286) | 48.1% [40–57] (62/129) | 2.4% [1–5] (7/286) | 26/83 (31%) |
| 3a. 2 + dinamik hedef (a: ATR) | 151 | 19.9 | 3.12 | 18.5% [13–25] (28/151) | 7.8% [6–11] (33/421) | 44.4% [37–52] (67/151) | 48.5% [44–53] (204/421) | 27/83 (33%) |
| 3b. 2 + dinamik hedef (b: direnç) | 151 | 19.9 | 1.88 | 35.8% [29–44] (54/151) | 10.7% [8–14] (45/421) | 58.9% [51–66] (89/151) | 52.3% [47–57] (220/421) | 27/83 (33%) |
| 3c. 2 + dinamik hedef (c: ampirik) | 148 | 19.5 | 0.80 | 54.7% [47–63] (81/148) | 6.7% [5–9] (28/421) | 73.0% [65–79] (108/148) | 47.3% [43–52] (199/421) | 26/83 (31%) |
| 4a. 3a + net hedef ≥ %2 | 77 | 10.1 | 4.89 | 15.6% [9–25] (12/77) | 0.0% [0–22] (0/14) | 39.0% [29–50] (30/77) | 21.4% [8–48] (3/14) | 26/83 (31%) |
| 4b. 3b + net hedef ≥ %2 | 40 | 5.3 | 4.16 | 7.5% [3–20] (3/40) | 0.0% [0–24] (0/12) | 32.5% [20–48] (13/40) | 16.7% [5–45] (2/12) | 11/83 (13%) |
| 4c. 3c + net hedef ≥ %2 | 0 | 0.0 | – | – | – | – | – | 0/83 (0%) |
| 4o. 2 + net ≥ %2 (eski hedefle) | 78 | 10.3 | 3.87 | 5.1% [2–12] (4/78) | 0.2% [0–1] (1/400) | 26.9% [18–38] (21/78) | 1.2% [1–3] (5/400) | 4/83 (5%) |
| P3a. push + dinamik (a) | 527 | 69.3 | 3.14 | 15.7% [13–19] (83/527) | 6.7% [5–9] (60/890) | 43.8% [40–48] (231/527) | 42.5% [39–46] (378/890) | 76/83 (92%) |
| P3b. push + dinamik (b) | 527 | 69.3 | 2.12 | 31.3% [27–35] (165/527) | 10.8% [9–13] (96/890) | 58.3% [54–62] (307/527) | 47.4% [44–51] (422/890) | 76/83 (92%) |
| P3c. push + dinamik (c) | 514 | 67.6 | 0.80 | 52.1% [48–56] (268/514) | 13.4% [11–16] (119/890) | 74.9% [71–78] (385/514) | 52.2% [49–56] (465/890) | 73/83 (88%) |
| P4a. push + (a) + net ≥ %2 | 276 | 36.3 | 4.69 | 12.7% [9–17] (35/276) | 0.0% [0–4] (0/102) | 38.8% [33–45] (107/276) | 22.5% [16–32] (23/102) | 64/83 (77%) |
| P4b. push + (b) + net ≥ %2 | 154 | 20.3 | 4.42 | 11.7% [8–18] (18/154) | 0.0% [0–6] (0/63) | 40.9% [33–49] (63/154) | 22.2% [14–34] (14/63) | 31/83 (37%) |
| P4c. push + (c) + net ≥ %2 | 0 | 0.0 | – | – | – | – | – | 0/83 (0%) |
| P4o. push + net ≥ %2 (eski hedefle) | 323 | 42.5 | 3.72 | 6.5% [4–10] (21/323) | 0.1% [0–1] (1/722) | 30.3% [26–36] (98/323) | 3.9% [3–6] (28/722) | 21/83 (25%) |
| T1. yalnız ≥2 kaynak (panel dahil) | 189 | 24.9 | 3.04 | 16.9% [12–23] (32/189) | 0.4% [0–2] (2/462) | 40.2% [33–47] (76/189) | 3.5% [2–6] (16/462) | 32/83 (39%) |
| T2. yalnız net ≥ %2 (eski hedef, hepsi) | 347 | 45.7 | 3.69 | 6.6% [4–10] (23/347) | 0.1% [0–1] (1/762) | 29.7% [25–35] (103/347) | 3.9% [3–6] (30/762) | 23/83 (28%) |

B) Net PnL, H1 (SL %3, süre = ufuk; gerçekçi doluş; 'rastgele' = sembol/saat tabanı, 'oyn.-eşl.' = oynaklık eşlemeli; 'toplam net/gün' = n/gün × ort. net, yani bu bildirimlerin her birine 1 birim girilseydi günlük toplam % puan):

| Aşama | n | net H1 [%95] | kazanan % | rastgele H1 | fark H1 (rast.) [%95] | oyn.-eşl. H1 | fark H1 (oyn.) [%95] | toplam net/gün (puan) |
|---|---|---|---|---|---|---|---|---|
| 0. Mevcut: gönderilen tümü (push+panel) | 575 | -0.54 ±0.23 | 31% | -0.53 ±0.01 | -0.01 [-0.24; +0.21] | -0.55 ±0.04 | +0.00 [-0.23; +0.23] | -41.2 |
| 1. + yalnız push (panel kaldırıldı) | 527 | -0.52 ±0.23 | 31% | -0.53 ±0.02 | +0.01 [-0.22; +0.24] | -0.55 ±0.04 | +0.03 [-0.20; +0.27] | -36.0 |
| 2. + ≥2 farklı kaynak | 151 | -0.46 ±0.20 | 31% | -0.52 ±0.02 | +0.07 [-0.13; +0.27] | -0.52 ±0.04 | +0.06 [-0.15; +0.26] | -9.1 |
| 2b. + ≥3 kaynak | 129 | -0.48 ±0.21 | 34% | -0.52 ±0.01 | +0.04 [-0.17; +0.25] | -0.53 ±0.07 | +0.04 [-0.18; +0.27] | -8.2 |
| 2c. + ≥4 kaynak | 22 | -0.55 ±0.63 | 41% | -0.53 ±0.03 | -0.02 [-0.65; +0.61] | -0.23 ±0.00 | -0.32 [-0.95; +0.31] | -1.6 |
| 2d. + ≥2 aile (jump+early tek sayılır) | 129 | -0.48 ±0.21 | 34% | -0.52 ±0.01 | +0.04 [-0.17; +0.25] | -0.53 ±0.07 | +0.04 [-0.18; +0.27] | -8.2 |
| 3a. 2 + dinamik hedef (a: ATR) | 151 | -0.45 ±0.16 | 28% | -0.52 ±0.02 | +0.07 [-0.09; +0.24] | -0.52 ±0.04 | +0.07 [-0.10; +0.24] | -8.9 |
| 3b. 2 + dinamik hedef (b: direnç) | 151 | -0.47 ±0.22 | 36% | -0.52 ±0.02 | +0.05 [-0.16; +0.27] | -0.51 ±0.04 | +0.05 [-0.18; +0.27] | -9.3 |
| 3c. 2 + dinamik hedef (c: ampirik) | 148 | -0.35 ±0.07 | 51% | -0.52 ±0.01 | +0.17 [+0.10; +0.24] | -0.52 ±0.04 | +0.16 [+0.08; +0.24] | -6.9 |
| 4a. 3a + net hedef ≥ %2 | 77 | -0.29 ±0.28 | 35% | -0.47 ±0.35 | +0.18 [-0.27; +0.63] | -1.19 ±0.67 | +0.90 [+0.18; +1.63] | -2.9 |
| 4b. 3b + net hedef ≥ %2 | 40 | -0.47 ±0.63 | 32% | -0.58 ±0.46 | +0.11 [-0.68; +0.89] | -1.03 ±0.65 | +0.56 [-0.35; +1.47] | -2.5 |
| 4o. 2 + net ≥ %2 (eski hedefle) | 78 | -0.38 ±0.26 | 28% | -0.53 ±0.03 | +0.15 [-0.11; +0.41] | -0.48 ±0.04 | +0.10 [-0.16; +0.36] | -3.9 |
| P3a. push + dinamik (a) | 527 | -0.46 ±0.25 | 31% | -0.53 ±0.02 | +0.08 [-0.17; +0.32] | -0.54 ±0.04 | +0.09 [-0.16; +0.34] | -31.6 |
| P3b. push + dinamik (b) | 527 | -0.52 ±0.22 | 36% | -0.53 ±0.01 | +0.01 [-0.21; +0.23] | -0.53 ±0.03 | +0.02 [-0.21; +0.24] | -35.9 |
| P3c. push + dinamik (c) | 514 | -0.46 ±0.10 | 49% | -0.53 ±0.01 | +0.07 [-0.03; +0.16] | -0.53 ±0.04 | +0.07 [-0.03; +0.17] | -31.1 |
| P4a. push + (a) + net ≥ %2 | 276 | -0.29 ±0.39 | 37% | -0.58 ±0.16 | +0.29 [-0.13; +0.71] | -0.77 ±0.21 | +0.48 [+0.04; +0.92] | -10.6 |
| P4b. push + (b) + net ≥ %2 | 154 | -0.35 ±0.48 | 39% | -0.52 ±0.20 | +0.17 [-0.36; +0.69] | -0.59 ±0.27 | +0.24 [-0.32; +0.79] | -7.1 |
| P4o. push + net ≥ %2 (eski hedefle) | 323 | -0.48 ±0.25 | 29% | -0.54 ±0.02 | +0.05 [-0.20; +0.30] | -0.52 ±0.05 | +0.04 [-0.22; +0.29] | -20.6 |
| T1. yalnız ≥2 kaynak (panel dahil) | 189 | -0.53 ±0.23 | 29% | -0.53 ±0.01 | -0.00 [-0.23; +0.23] | -0.50 ±0.04 | -0.02 [-0.25; +0.21] | -13.1 |
| T2. yalnız net ≥ %2 (eski hedef, hepsi) | 347 | -0.53 ±0.25 | 28% | -0.54 ±0.02 | +0.00 [-0.25; +0.25] | -0.53 ±0.05 | -0.01 [-0.26; +0.25] | -24.4 |

C) H2, iyimser kayma ve ücretsiz brüt 60 dk getiri (yön avantajı var mı?):

| Aşama | n | net H2 | rastgele H2 | fark H2 (rast.) | net H1, iyimser kayma %0,05 | rastgele (iyimser) | brüt 60 dk getiri (ücretsiz) | rastgele brüt 60 dk | fark brüt 60 dk |
|---|---|---|---|---|---|---|---|---|---|
| 0. Mevcut: gönderilen tümü (push+panel) | 575 | -0.59 ±0.38 | -0.56 ±0.08 | -0.03 [-0.41; +0.36] | -0.35 ±0.20 | -0.33 ±0.01 | -0.68 ±0.44 | -0.10 ±0.11 | -0.57 [-1.03; -0.12] |
| 1. + yalnız push (panel kaldırıldı) | 527 | -0.56 ±0.39 | -0.56 ±0.08 | +0.01 [-0.39; +0.40] | -0.34 ±0.21 | -0.33 ±0.02 | -0.71 ±0.45 | -0.11 ±0.11 | -0.60 [-1.07; -0.13] |
| 2. + ≥2 farklı kaynak | 151 | -0.54 ±0.18 | -0.52 ±0.09 | -0.02 [-0.22; +0.18] | -0.25 ±0.15 | -0.32 ±0.02 | -0.83 ±0.85 | -0.09 ±0.13 | -0.74 [-1.59; +0.12] |
| 2b. + ≥3 kaynak | 129 | -0.56 ±0.13 | -0.52 ±0.08 | -0.03 [-0.19; +0.12] | -0.27 ±0.16 | -0.33 ±0.01 | -0.85 ±0.97 | -0.10 ±0.12 | -0.76 [-1.74; +0.22] |
| 2c. + ≥4 kaynak | 22 | -0.26 ±1.08 | -0.46 ±0.23 | +0.20 [-0.90; +1.31] | -0.12 ±0.84 | -0.33 ±0.03 | -2.92 ±4.79 | +0.04 ±0.26 | -2.96 [-7.76; +1.84] |
| 2d. + ≥2 aile (jump+early tek sayılır) | 129 | -0.56 ±0.13 | -0.52 ±0.08 | -0.03 [-0.19; +0.12] | -0.27 ±0.16 | -0.33 ±0.01 | -0.85 ±0.97 | -0.10 ±0.12 | -0.76 [-1.74; +0.22] |
| 3a. 2 + dinamik hedef (a: ATR) | 151 | -0.79 ±0.21 | -0.50 ±0.06 | -0.29 [-0.51; -0.07] | -0.27 ±0.16 | -0.33 ±0.01 | -0.83 ±0.85 | -0.09 ±0.13 | -0.74 [-1.59; +0.12] |
| 3b. 2 + dinamik hedef (b: direnç) | 151 | -0.55 ±0.14 | -0.50 ±0.06 | -0.05 [-0.20; +0.10] | -0.31 ±0.18 | -0.33 ±0.02 | -0.83 ±0.85 | -0.09 ±0.13 | -0.74 [-1.59; +0.12] |
| 3c. 2 + dinamik hedef (c: ampirik) | 148 | -0.30 ±0.09 | -0.50 ±0.05 | +0.19 [+0.09; +0.30] | -0.16 ±0.06 | -0.33 ±0.01 | -0.93 ±0.82 | -0.09 ±0.13 | -0.84 [-1.67; -0.02] |
| 4a. 3a + net hedef ≥ %2 | 77 | -0.84 ±0.45 | -0.81 ±0.57 | -0.03 [-0.75; +0.70] | -0.13 ±0.28 | -0.28 ±0.35 | -1.31 ±1.42 | -0.37 ±1.10 | -0.94 [-2.74; +0.85] |
| 4b. 3b + net hedef ≥ %2 | 40 | -1.19 ±0.39 | -0.67 ±0.93 | -0.52 [-1.53; +0.49] | -0.30 ±0.61 | -0.39 ±0.47 | -2.21 ±1.81 | -0.37 ±1.64 | -1.83 [-4.28; +0.61] |
| 4o. 2 + net ≥ %2 (eski hedefle) | 78 | -0.39 ±0.44 | -0.52 ±0.09 | +0.13 [-0.32; +0.58] | -0.19 ±0.25 | -0.33 ±0.03 | -0.63 ±0.35 | -0.09 ±0.16 | -0.53 [-0.91; -0.15] |
| P3a. push + dinamik (a) | 527 | -0.66 ±0.26 | -0.54 ±0.06 | -0.11 [-0.38; +0.15] | -0.27 ±0.25 | -0.34 ±0.01 | -0.71 ±0.45 | -0.11 ±0.11 | -0.60 [-1.07; -0.13] |
| P3b. push + dinamik (b) | 527 | -0.60 ±0.22 | -0.54 ±0.06 | -0.06 [-0.29; +0.17] | -0.35 ±0.21 | -0.34 ±0.01 | -0.71 ±0.45 | -0.11 ±0.11 | -0.60 [-1.07; -0.13] |
| P3c. push + dinamik (c) | 514 | -0.46 ±0.12 | -0.54 ±0.06 | +0.08 [-0.06; +0.21] | -0.31 ±0.08 | -0.34 ±0.01 | -0.74 ±0.43 | -0.10 ±0.11 | -0.63 [-1.07; -0.19] |
| P4a. push + (a) + net ≥ %2 | 276 | -0.56 ±0.25 | -0.77 ±0.59 | +0.21 [-0.44; +0.86] | -0.11 ±0.41 | -0.39 ±0.16 | -1.02 ±0.45 | -0.27 ±0.96 | -0.75 [-1.81; +0.31] |
| P4b. push + (b) + net ≥ %2 | 154 | -0.75 ±0.34 | -0.64 ±0.88 | -0.12 [-1.07; +0.83] | -0.18 ±0.48 | -0.33 ±0.20 | -1.22 ±0.54 | -0.07 ±1.17 | -1.16 [-2.44; +0.13] |
| P4o. push + net ≥ %2 (eski hedefle) | 323 | -0.61 ±0.56 | -0.57 ±0.07 | -0.05 [-0.61; +0.52] | -0.30 ±0.24 | -0.34 ±0.02 | -0.64 ±0.51 | -0.09 ±0.10 | -0.55 [-1.07; -0.02] |
| T1. yalnız ≥2 kaynak (panel dahil) | 189 | -0.65 ±0.22 | -0.54 ±0.09 | -0.11 [-0.35; +0.12] | -0.28 ±0.18 | -0.33 ±0.01 | -0.78 ±0.89 | -0.09 ±0.13 | -0.69 [-1.59; +0.22] |
| T2. yalnız net ≥ %2 (eski hedef, hepsi) | 347 | -0.64 ±0.54 | -0.57 ±0.07 | -0.07 [-0.62; +0.47] | -0.33 ±0.23 | -0.34 ±0.02 | -0.59 ±0.50 | -0.09 ±0.10 | -0.50 [-1.01; +0.00] |

Satır etiketleri: `0` mevcut sistem; `1` panel kaldırıldı; `2/2b/2c/2d` teyit sayısı eşikleri; `3a/b/c` dinamik hedef (≥2 kaynak üzerinde); `4a/b/c` + net hedef ≥ %2; `4o` eski hedefle net ≥ %2; `P…` aynı kurallar ≥2 kaynak şartı OLMADAN (push üzerinde, n büyük kalsın diye); `T1/T2` yalnız tek filtre (push+panel tabanında).

## 4. Teyit sayısı — daha büyük kümede (n ve güven aralıklarıyla)

Üretim ekranındaki '4'lü teyit %100 (1/1)' **istatistiksel olarak anlamsızdır**: n=1 için Wilson %95 aralığı [21%–100%], 3/3 için bile [44%–100%]. Aşağıda aynı ölçüt 17.09 → 17.10 tüm bildirimlerde (kaynak bilgisi olan satırlar; 'başlıkta 4'LÜ TEYİT' grubu DB satırlarında başlık metninden) ölçüldü. NOT: başlıktaki '4'LÜ TEYİT' etiketi Master-Surge 4 katman teyididir (`is_4way` = confluence_4way veya ≥4 kaynak); `sources` içindeki dört kaynakla aynı şey DEĞİLDİR.

Tüm dönem (17.09 → 17.10):

| Grup | n | hit (ufuk, eski hedef) [Wilson95] | hit 60 dk | net H1 | fark H1 (rastgele) | fark H1 (oyn.-eşl.) |
|---|---|---|---|---|---|---|
| kaynak sayısı = 0 (bilinmiyor) | 664 | 12.7% [10–15] (84/664) | 36.4% [33–40] (242/664) | -0.49 ±0.08 | +0.03 [-0.05; +0.11] | +0.05 [-0.04; +0.14] |
| 1 kaynak | 629 | 17.0% [14–20] (107/629) | 43.4% [40–47] (273/629) | -0.57 ±0.18 | -0.04 [-0.23; +0.14] | +0.01 [-0.19; +0.21] |
| 2 kaynak | 174 | 4.6% [2–9] (8/174) | 18.4% [13–25] (32/174) | -0.39 ±0.15 | +0.14 [-0.01; +0.29] | +0.13 [-0.02; +0.28] |
| 3 kaynak | 1178 | 10.5% [9–12] (124/1178) | 38.4% [36–41] (452/1178) | -0.48 ±0.08 | +0.05 [-0.04; +0.13] | +0.05 [-0.03; +0.14] |
| 4 kaynak | 223 | 25.1% [20–31] (56/223) | 62.3% [56–68] (139/223) | -0.61 ±0.24 | -0.08 [-0.32; +0.17] | +0.10 [-0.42; +0.61] |
| aile = 1 | 798 | 14.3% [12–17] (114/798) | 38.1% [35–42] (304/798) | -0.53 ±0.15 | -0.00 [-0.15; +0.14] | +0.01 [-0.15; +0.16] |
| aile = 2 | 1179 | 10.3% [9–12] (122/1179) | 38.1% [35–41] (449/1179) | -0.48 ±0.08 | +0.04 [-0.04; +0.12] | +0.05 [-0.03; +0.13] |
| aile = 3 | 227 | 26.0% [21–32] (59/227) | 63.0% [57–69] (143/227) | -0.58 ±0.22 | -0.04 [-0.26; +0.18] | +0.13 [-0.37; +0.63] |
| kombinasyon: velocity | 629 | 17.0% [14–20] (107/629) | 43.4% [40–47] (273/629) | -0.57 ±0.18 | -0.04 [-0.23; +0.14] | +0.01 [-0.19; +0.21] |
| kombinasyon: jump+early | 169 | 4.1% [2–8] (7/169) | 18.3% [13–25] (31/169) | -0.39 ±0.14 | +0.14 [-0.01; +0.28] | +0.13 [-0.02; +0.27] |
| kombinasyon: jump+early+rising | 889 | 8.2% [7–10] (73/889) | 35.9% [33–39] (319/889) | -0.46 ±0.06 | +0.06 [+0.00; +0.12] | +0.07 [+0.00; +0.13] |
| kombinasyon: velocity+jump+early | 285 | 16.8% [13–22] (48/285) | 45.3% [40–51] (129/285) | -0.55 ±0.25 | -0.03 [-0.28; +0.22] | +0.11 [-0.20; +0.41] |
| kombinasyon: velocity+jump+early+rising | 223 | 25.1% [20–31] (56/223) | 62.3% [56–68] (139/223) | -0.61 ±0.24 | -0.08 [-0.32; +0.17] | +0.10 [-0.42; +0.61] |
| kombinasyon: velocity+rising | 0 | – | – | – | – | – |
| başlıkta 4'LÜ TEYİT (yalnız DB satırları) | 613 | 10.1% [8–13] (62/613) | 29.9% [26–34] (183/613) | -0.46 ±0.09 | +0.07 [-0.02; +0.16] | +0.07 [-0.02; +0.16] |
| mod: trend_devam | 985 | 21.5% [19–24] (212/985) | 52.2% [49–55] (514/985) | -0.38 ±0.13 | +0.14 [+0.01; +0.27] | +0.19 [+0.04; +0.34] |
| mod: notr | 390 | 16.2% [13–20] (63/390) | 43.6% [39–49] (170/390) | -0.89 ±0.23 | -0.36 [-0.59; -0.14] | -0.25 [-0.56; +0.06] |
| mod: unified | 1131 | 7.1% [6–9] (80/1131) | 32.1% [29–35] (363/1131) | -0.43 ±0.05 | +0.10 [+0.05; +0.14] | +0.10 [+0.05; +0.15] |
| mod: llm_ikinci_goz | 258 | 4.3% [2–7] (11/258) | 23.6% [19–29] (61/258) | -0.62 ±0.09 | -0.10 [-0.20; -0.01] | -0.09 [-0.18; +0.01] |
| mod: v_donusu | 21 | 14.3% [5–35] (3/21) | 23.8% [11–45] (5/21) | -0.71 ±0.48 | -0.17 [-0.65; +0.31] | -0.21 [-0.70; +0.27] |
| push | 2680 | 13.4% [12–15] (359/2680) | 40.2% [38–42] (1078/2680) | -0.49 ±0.06 | +0.04 [-0.02; +0.10] | +0.05 [-0.01; +0.11] |
| panel | 188 | 10.6% [7–16] (20/188) | 31.9% [26–39] (60/188) | -0.76 ±0.22 | -0.24 [-0.45; -0.02] | -0.24 [-0.47; -0.01] |

Son 7 gün:

| Grup | n | hit (ufuk, eski hedef) [Wilson95] | hit 60 dk | net H1 | fark H1 (rastgele) | fark H1 (oyn.-eşl.) |
|---|---|---|---|---|---|---|
| kaynak sayısı = 0 (bilinmiyor) | 42 | 23.8% [13–39] (10/42) | 57.1% [42–71] (24/42) | -0.30 ±0.09 | +0.22 [+0.12; +0.31] | +0.26 [+0.06; +0.46] |
| 1 kaynak | 344 | 11.9% [9–16] (41/344) | 38.7% [34–44] (133/344) | -0.58 ±0.29 | -0.05 [-0.34; +0.25] | +0.01 [-0.29; +0.31] |
| 2 kaynak | 24 | 8.3% [2–26] (2/24) | 20.8% [9–40] (5/24) | -0.25 ±0.40 | +0.26 [-0.14; +0.67] | +0.24 [-0.17; +0.64] |
| 3 kaynak | 142 | 15.5% [10–22] (22/142) | 40.1% [32–48] (57/142) | -0.55 ±0.30 | -0.02 [-0.32; +0.28] | -0.04 [-0.34; +0.27] |
| 4 kaynak | 23 | 34.8% [19–55] (8/23) | 60.9% [41–78] (14/23) | -0.68 ±0.57 | -0.15 [-0.72; +0.42] | -0.44 [-1.02; +0.13] |
| aile = 1 | 366 | 11.5% [9–15] (42/366) | 37.4% [33–42] (137/366) | -0.57 ±0.27 | -0.03 [-0.30; +0.24] | +0.00 [-0.28; +0.28] |
| aile = 2 | 144 | 16.0% [11–23] (23/144) | 40.3% [33–48] (58/144) | -0.54 ±0.31 | -0.01 [-0.32; +0.30] | -0.03 [-0.34; +0.29] |
| aile = 3 | 23 | 34.8% [19–55] (8/23) | 60.9% [41–78] (14/23) | -0.68 ±0.57 | -0.15 [-0.72; +0.42] | -0.44 [-1.02; +0.13] |
| kombinasyon: velocity | 344 | 11.9% [9–16] (41/344) | 38.7% [34–44] (133/344) | -0.58 ±0.29 | -0.05 [-0.34; +0.25] | +0.01 [-0.29; +0.31] |
| kombinasyon: jump+early | 22 | 4.5% [1–22] (1/22) | 18.2% [7–39] (4/22) | -0.29 ±0.26 | +0.23 [-0.04; +0.49] | +0.20 [-0.06; +0.46] |
| kombinasyon: jump+early+rising | 55 | 0.0% [0–7] (0/55) | 21.8% [13–34] (12/55) | -0.67 ±0.24 | -0.15 [-0.39; +0.09] | -0.21 [-0.45; +0.04] |
| kombinasyon: velocity+jump+early | 87 | 25.3% [17–35] (22/87) | 51.7% [41–62] (45/87) | -0.47 ±0.44 | +0.06 [-0.38; +0.49] | +0.66 [-0.10; +1.43] |
| kombinasyon: velocity+jump+early+rising | 23 | 34.8% [19–55] (8/23) | 60.9% [41–78] (14/23) | -0.68 ±0.57 | -0.15 [-0.72; +0.42] | -0.44 [-1.02; +0.13] |
| kombinasyon: velocity+rising | 0 | – | – | – | – | – |
| başlıkta 4'LÜ TEYİT (yalnız DB satırları) | 65 | 16.9% [10–28] (11/65) | 36.9% [26–49] (24/65) | -0.57 ±0.34 | -0.04 [-0.39; +0.30] | -0.07 [-0.41; +0.28] |
| mod: trend_devam | 270 | 19.3% [15–24] (52/270) | 49.3% [43–55] (133/270) | -0.35 ±0.28 | +0.19 [-0.09; +0.47] | +0.30 [+0.01; +0.58] |
| mod: notr | 116 | 15.5% [10–23] (18/116) | 42.2% [34–51] (49/116) | -0.78 ±0.44 | -0.27 [-0.71; +0.18] | -0.01 [-0.56; +0.54] |
| mod: unified | 70 | 1.4% [0–8] (1/70) | 22.9% [15–34] (16/70) | -0.52 ±0.17 | +0.01 [-0.16; +0.19] | -0.04 [-0.22; +0.14] |
| mod: llm_ikinci_goz | 21 | 9.5% [3–29] (2/21) | 42.9% [24–63] (9/21) | -0.75 ±0.63 | -0.24 [-0.87; +0.39] | -0.29 [-0.93; +0.34] |
| mod: v_donusu | 15 | 0.0% [0–20] (0/15) | 6.7% [1–30] (1/15) | -0.60 ±0.05 | -0.07 [-0.14; -0.00] | -0.10 [-0.17; -0.04] |
| push | 527 | 14.4% [12–18] (76/527) | 41.6% [37–46] (219/527) | -0.52 ±0.23 | +0.01 [-0.22; +0.24] | +0.03 [-0.20; +0.27] |
| panel | 48 | 14.6% [7–27] (7/48) | 29.2% [18–43] (14/48) | -0.81 ±0.48 | -0.28 [-0.76; +0.20] | -0.40 [-0.93; +0.12] |

Okuma: teyit sayısı arttıkça ufuk içi isabet yükselir (1 kaynak %17, 3 kaynak %10, **4 kaynak %25 [20–31], n=223**) fakat bu, teyitli bildirimlerin daha küçük ortalama hedef taşıması (7 günde 4 kaynakta ort. hedef %2,35 vs %3,1) ve güçlü pompa anlarında gelmesiyle açıklanır; net PnL'de teyit sayısı bir fark yaratmaz (4 kaynak: −0,61 ±0,24, rastgele farkı [−0,32; +0,17]). Başlığında '4'LÜ TEYİT' yazan 613 bildirimde isabet %10,1 [8–13], net −0,46 ±0,09 — yani üretimdeki tek '4'lü teyit 1/1' gözleminin büyük kümede karşılığı yok. Tek anlamlı ayrım **mod**: yalnız `trend_devam` modu tüm dönemde rastgeleden iyi (+0,14 [+0,01; +0,27], isabet %21,5) ama net yine −0,38 ±0,13; `notr` modu belirgin kötü (−0,89).

## 5. Dinamik hedef varyantları — karşılaştırma

Her satırda hedef kuralı değişir; 'net≥2 filtre = evet' satırı yalnız net hedefi ≥ %2 olanları bırakır. Hit, kuralın KENDİ hedefine göredir; rastgele sütunu aynı kuralın rastgele anlarda uygulanmışı.

**Push bildirimleri, son 7 gün:**

| Hedef kuralı (push, 7 gün) | net≥2 filtre | n | ort. brüt / net hedef % | hit (ufuk) | rastgele hit (oyn.-eşl.) | net H1 ; fark (rast.) | net H2 ; fark (rast.) | fark H1 (oyn.-eşl.) |
|---|---|---|---|---|---|---|---|---|
| eski hedef (sabit) | hayır | 527 | 3.15 / 2.62 | 14.4% [12–18] (76/527) | 0.3% [0–1] (3/890) | -0.52 ±0.23 ; +0.01 [-0.22; +0.24] | -0.56 ±0.39 ; +0.01 [-0.39; +0.40] | +0.03 [-0.20; +0.27] |
| eski hedef (sabit) | evet | 323 | 3.72 / 3.19 | 6.5% [4–10] (21/323) | 0.1% [0–1] (1/722) | -0.48 ±0.25 ; +0.05 [-0.20; +0.30] | -0.61 ±0.56 ; -0.05 [-0.61; +0.52] | +0.04 [-0.22; +0.29] |
| (a) ATR k=1 | hayır | 527 | 2.09 / 1.57 | 26.6% [23–30] (140/527) | 16.0% [14–19] (142/890) | -0.48 ±0.22 ; +0.05 [-0.17; +0.28] | -0.55 ±0.23 ; -0.02 [-0.26; +0.22] | +0.06 [-0.17; +0.28] |
| (a) ATR k=1 | evet | 151 | 4.01 / 3.49 | 15.2% [10–22] (23/151) | 0.0% [0–17] (0/19) | -0.35 ±0.29 ; +0.36 [-0.21; +0.93] | -0.82 ±0.22 ; +0.09 [-0.81; +0.99] | -0.07 [-0.65; +0.51] |
| (a) ATR k=1.5 | hayır | 527 | 3.14 / 2.61 | 15.7% [13–19] (83/527) | 6.7% [5–9] (60/890) | -0.46 ±0.25 ; +0.08 [-0.17; +0.32] | -0.66 ±0.26 ; -0.11 [-0.38; +0.15] | +0.09 [-0.16; +0.34] |
| (a) ATR k=1.5 | evet | 276 | 4.69 / 4.16 | 12.7% [9–17] (35/276) | 0.0% [0–4] (0/102) | -0.29 ±0.39 ; +0.29 [-0.13; +0.71] | -0.56 ±0.25 ; +0.21 [-0.44; +0.86] | +0.48 [+0.04; +0.92] |
| (a) ATR k=2 | hayır | 527 | 4.19 / 3.66 | 8.0% [6–11] (42/527) | 2.6% [2–4] (23/890) | -0.54 ±0.24 ; -0.01 [-0.25; +0.23] | -0.69 ±0.40 ; -0.14 [-0.54; +0.27] | +0.00 [-0.24; +0.24] |
| (a) ATR k=2 | evet | 347 | 5.57 / 5.04 | 6.9% [5–10] (24/347) | 0.0% [0–2] (0/164) | -0.46 ±0.34 ; +0.09 [-0.27; +0.44] | -0.69 ±0.47 ; +0.08 [-0.53; +0.70] | +0.21 [-0.17; +0.60] |
| (b) direnç k=1 | hayır | 527 | 1.63 / 1.10 | 37.0% [33–41] (195/527) | 18.1% [16–21] (161/890) | -0.51 ±0.20 ; +0.02 [-0.18; +0.23] | -0.55 ±0.23 ; -0.01 [-0.25; +0.22] | +0.02 [-0.19; +0.23] |
| (b) direnç k=1 | evet | 97 | 3.92 / 3.40 | 13.4% [8–22] (13/97) | 0.0% [0–19] (0/16) | -0.42 ±0.31 ; +0.21 [-0.56; +0.98] | -1.11 ±0.52 ; -0.24 [-1.37; +0.90] | -0.39 [-1.11; +0.34] |
| (b) direnç k=1.5 | hayır | 527 | 2.12 / 1.60 | 31.3% [27–35] (165/527) | 10.8% [9–13] (96/890) | -0.52 ±0.22 ; +0.01 [-0.21; +0.23] | -0.60 ±0.22 ; -0.06 [-0.29; +0.17] | +0.02 [-0.21; +0.24] |
| (b) direnç k=1.5 | evet | 154 | 4.42 / 3.90 | 11.7% [8–18] (18/154) | 0.0% [0–6] (0/63) | -0.35 ±0.48 ; +0.17 [-0.36; +0.69] | -0.75 ±0.34 ; -0.12 [-1.07; +0.83] | +0.24 [-0.32; +0.79] |
| (b) direnç k=2 | hayır | 527 | 2.51 / 1.99 | 27.7% [24–32] (146/527) | 8.0% [6–10] (71/890) | -0.58 ±0.20 ; -0.05 [-0.25; +0.16] | -0.64 ±0.27 ; -0.09 [-0.37; +0.18] | -0.04 [-0.25; +0.16] |
| (b) direnç k=2 | evet | 184 | 4.97 / 4.45 | 8.7% [5–14] (16/184) | 0.0% [0–4] (0/98) | -0.57 ±0.42 ; -0.07 [-0.50; +0.35] | -0.93 ±0.42 ; -0.27 [-1.03; +0.48] | +0.01 [-0.48; +0.50] |
| (c) ampirik q60 (60 dk MFE) | hayır | 514 | 0.80 / 0.28 | 52.1% [48–56] (268/514) | 13.4% [11–16] (119/890) | -0.46 ±0.10 ; +0.07 [-0.03; +0.16] | -0.46 ±0.12 ; +0.08 [-0.06; +0.21] | +0.07 [-0.03; +0.17] |
| (c) ampirik q60 (60 dk MFE) | evet | 0 | – | – | – | – | – | – |
| (c') ampirik q60 (ufuk MFE) | hayır | 317 | 0.23 / -0.29 | 79.2% [74–83] (251/317) | 54.7% [51–58] (398/728) | -0.44 ±0.06 ; +0.08 [+0.02; +0.14] | -0.44 ±0.10 ; +0.06 [-0.04; +0.16] | +0.05 [-0.02; +0.11] |
| (c') ampirik q60 (ufuk MFE) | evet | 0 | – | – | – | – | – | – |

**Push + ≥2 kaynak, son 7 gün:**

| Hedef kuralı (push+≥2 kaynak, 7 gün) | net≥2 filtre | n | ort. brüt / net hedef % | hit (ufuk) | rastgele hit (oyn.-eşl.) | net H1 ; fark (rast.) | net H2 ; fark (rast.) | fark H1 (oyn.-eşl.) |
|---|---|---|---|---|---|---|---|---|
| eski hedef (sabit) | hayır | 151 | 3.07 / 2.54 | 17.9% [13–25] (27/151) | 0.2% [0–1] (1/421) | -0.46 ±0.20 ; +0.07 [-0.13; +0.27] | -0.54 ±0.18 ; -0.02 [-0.22; +0.18] | +0.06 [-0.15; +0.26] |
| eski hedef (sabit) | evet | 78 | 3.87 / 3.34 | 5.1% [2–12] (4/78) | 0.2% [0–1] (1/400) | -0.38 ±0.26 ; +0.15 [-0.11; +0.41] | -0.39 ±0.44 ; +0.13 [-0.32; +0.58] | +0.10 [-0.16; +0.36] |
| (a) ATR k=1 | hayır | 151 | 2.08 / 1.55 | 32.5% [25–40] (49/151) | 15.7% [13–19] (66/421) | -0.46 ±0.18 ; +0.06 [-0.12; +0.24] | -0.62 ±0.20 ; -0.14 [-0.35; +0.08] | +0.05 [-0.12; +0.23] |
| (a) ATR k=1 | evet | 51 | 3.83 / 3.30 | 17.6% [10–30] (9/51) | 0.0% [0–49] (0/4) | -0.52 ±0.24 ; +0.28 [-0.81; +1.36] | -1.06 ±0.62 ; -0.19 [-1.95; +1.57] | -0.42 [-0.68; -0.16] |
| (a) ATR k=1.5 | hayır | 151 | 3.12 / 2.59 | 18.5% [13–25] (28/151) | 7.8% [6–11] (33/421) | -0.45 ±0.16 ; +0.07 [-0.09; +0.24] | -0.79 ±0.21 ; -0.29 [-0.51; -0.07] | +0.07 [-0.10; +0.24] |
| (a) ATR k=1.5 | evet | 77 | 4.89 / 4.36 | 15.6% [9–25] (12/77) | 0.0% [0–22] (0/14) | -0.29 ±0.28 ; +0.18 [-0.27; +0.63] | -0.84 ±0.45 ; -0.03 [-0.75; +0.70] | +0.90 [+0.18; +1.63] |
| (a) ATR k=2 | hayır | 151 | 4.15 / 3.63 | 7.9% [5–13] (12/151) | 2.4% [1–4] (10/421) | -0.46 ±0.17 ; +0.07 [-0.10; +0.24] | -0.75 ±0.34 ; -0.24 [-0.59; +0.11] | +0.06 [-0.11; +0.24] |
| (a) ATR k=2 | evet | 95 | 5.83 / 5.30 | 7.4% [4–14] (7/95) | 0.0% [0–12] (0/27) | -0.42 ±0.30 ; -0.01 [-0.32; +0.31] | -0.85 ±0.53 ; -0.13 [-0.71; +0.45] | +0.44 [-0.13; +1.00] |
| (b) direnç k=1 | hayır | 151 | 1.50 / 0.98 | 44.4% [37–52] (67/151) | 16.6% [13–20] (70/421) | -0.44 ±0.17 ; +0.08 [-0.09; +0.25] | -0.50 ±0.13 ; -0.01 [-0.15; +0.13] | +0.07 [-0.11; +0.24] |
| (b) direnç k=1 | evet | 30 | 3.53 / 3.00 | 10.0% [3–26] (3/30) | 0.0% [0–49] (0/4) | -0.63 ±0.40 ; +0.27 [-0.78; +1.32] | -1.60 ±0.68 ; -0.63 [-2.08; +0.81] | -0.53 [-0.94; -0.12] |
| (b) direnç k=1.5 | hayır | 151 | 1.88 / 1.35 | 35.8% [29–44] (54/151) | 10.7% [8–14] (45/421) | -0.47 ±0.22 ; +0.05 [-0.16; +0.27] | -0.55 ±0.14 ; -0.05 [-0.20; +0.10] | +0.05 [-0.18; +0.27] |
| (b) direnç k=1.5 | evet | 40 | 4.16 / 3.63 | 7.5% [3–20] (3/40) | 0.0% [0–24] (0/12) | -0.47 ±0.63 ; +0.11 [-0.68; +0.89] | -1.19 ±0.39 ; -0.52 [-1.53; +0.49] | +0.56 [-0.35; +1.47] |
| (b) direnç k=2 | hayır | 151 | 2.18 / 1.65 | 32.5% [25–40] (49/151) | 6.2% [4–9] (26/421) | -0.52 ±0.21 ; +0.01 [-0.21; +0.22] | -0.60 ±0.11 ; -0.10 [-0.22; +0.02] | -0.00 [-0.22; +0.21] |
| (b) direnç k=2 | evet | 44 | 4.73 / 4.20 | 6.8% [2–18] (3/44) | 0.0% [0–15] (0/22) | -0.70 ±0.63 ; -0.24 [-0.91; +0.42] | -1.43 ±0.36 ; -0.83 [-1.60; -0.05] | +0.14 [-0.64; +0.92] |
| (c) ampirik q60 (60 dk MFE) | hayır | 148 | 0.80 / 0.28 | 54.7% [47–63] (81/148) | 6.7% [5–9] (28/421) | -0.35 ±0.07 ; +0.17 [+0.10; +0.24] | -0.30 ±0.09 ; +0.19 [+0.09; +0.30] | +0.16 [+0.08; +0.24] |
| (c) ampirik q60 (60 dk MFE) | evet | 0 | – | – | – | – | – | – |
| (c') ampirik q60 (ufuk MFE) | hayır | 101 | 0.19 / -0.34 | 82.2% [74–88] (83/101) | 51.0% [46–56] (200/392) | -0.47 ±0.09 ; +0.04 [-0.05; +0.13] | -0.43 ±0.11 ; +0.05 [-0.07; +0.17] | +0.02 [-0.07; +0.11] |
| (c') ampirik q60 (ufuk MFE) | evet | 0 | – | – | – | – | – | – |

**Push bildirimleri, önceki dönem (17.09 → 09.10, kaynak bilgisi aranmadı):**

| Hedef kuralı (push, önceki dönem) | net≥2 filtre | n | ort. brüt / net hedef % | hit (ufuk) | rastgele hit (oyn.-eşl.) | net H1 ; fark (rast.) | net H2 ; fark (rast.) | fark H1 (oyn.-eşl.) |
|---|---|---|---|---|---|---|---|---|
| eski hedef (sabit) | hayır | 1531 | 2.87 / 2.34 | 13.7% [12–15] (209/1531) | 0.9% [1–1] (41/4775) | -0.47 ±0.05 ; +0.05 [+0.00; +0.11] | -0.51 ±0.11 ; +0.03 [-0.09; +0.15] | +0.06 [+0.01; +0.12] |
| eski hedef (sabit) | evet | 912 | 3.59 / 3.06 | 10.7% [9–13] (98/912) | 0.3% [0–1] (9/2628) | -0.44 ±0.08 ; +0.09 [+0.01; +0.17] | -0.55 ±0.17 ; +0.00 [-0.17; +0.17] | +0.09 [+0.00; +0.17] |
| (a) ATR k=1 | hayır | 1531 | 1.61 / 1.08 | 31.4% [29–34] (480/1531) | 14.4% [13–15] (686/4774) | -0.50 ±0.05 ; +0.03 [-0.02; +0.08] | -0.53 ±0.09 ; -0.01 [-0.10; +0.08] | +0.04 [-0.02; +0.09] |
| (a) ATR k=1 | evet | 298 | 3.99 / 3.47 | 20.1% [16–25] (60/298) | 7.9% [3–17] (5/63) | -0.63 ±0.15 ; -0.06 [-0.30; +0.19] | -0.75 ±0.28 ; -0.01 [-0.57; +0.55] | -0.01 [-0.71; +0.68] |
| (a) ATR k=1.5 | hayır | 1531 | 2.41 / 1.89 | 17.3% [15–19] (265/1531) | 6.4% [6–7] (305/4774) | -0.51 ±0.06 ; +0.02 [-0.04; +0.08] | -0.56 ±0.11 ; -0.03 [-0.14; +0.08] | +0.03 [-0.03; +0.09] |
| (a) ATR k=1.5 | evet | 514 | 4.79 / 4.26 | 12.5% [10–16] (64/514) | 2.3% [1–5] (5/213) | -0.67 ±0.15 ; -0.06 [-0.24; +0.11] | -0.75 ±0.29 ; -0.04 [-0.46; +0.38] | -0.06 [-0.37; +0.25] |
| (a) ATR k=2 | hayır | 1531 | 3.21 / 2.69 | 11.0% [10–13] (169/1531) | 3.1% [3–4] (147/4774) | -0.51 ±0.06 ; +0.02 [-0.04; +0.08] | -0.59 ±0.11 ; -0.06 [-0.17; +0.05] | +0.03 [-0.03; +0.09] |
| (a) ATR k=2 | evet | 660 | 5.61 / 5.09 | 8.9% [7–11] (59/660) | 1.3% [1–3] (5/374) | -0.64 ±0.12 ; -0.05 [-0.19; +0.08] | -0.81 ±0.19 ; -0.06 [-0.34; +0.21] | -0.04 [-0.25; +0.17] |
| (b) direnç k=1 | hayır | 1531 | 1.18 / 0.65 | 41.9% [39–44] (642/1531) | 15.5% [15–17] (742/4774) | -0.49 ±0.05 ; +0.03 [-0.02; +0.08] | -0.52 ±0.08 ; -0.00 [-0.09; +0.08] | +0.04 [-0.01; +0.09] |
| (b) direnç k=1 | evet | 163 | 4.00 / 3.48 | 22.1% [16–29] (36/163) | 9.1% [4–20] (5/55) | -0.62 ±0.31 ; -0.14 [-0.51; +0.23] | -0.95 ±0.39 ; -0.27 [-0.87; +0.33] | -0.12 [-0.91; +0.66] |
| (b) direnç k=1.5 | hayır | 1531 | 1.54 / 1.01 | 33.6% [31–36] (515/1531) | 8.8% [8–10] (419/4774) | -0.49 ±0.05 ; +0.03 [-0.02; +0.09] | -0.50 ±0.09 ; +0.02 [-0.07; +0.11] | +0.04 [-0.01; +0.10] |
| (b) direnç k=1.5 | evet | 247 | 4.51 / 3.98 | 16.6% [12–22] (41/247) | 2.0% [1–6] (3/153) | -0.53 ±0.32 ; +0.03 [-0.31; +0.37] | -0.63 ±0.43 ; +0.03 [-0.51; +0.56] | +0.05 [-0.42; +0.52] |
| (b) direnç k=2 | hayır | 1531 | 1.83 / 1.31 | 30.0% [28–32] (459/1531) | 6.1% [5–7] (293/4774) | -0.49 ±0.05 ; +0.03 [-0.02; +0.09] | -0.51 ±0.09 ; +0.03 [-0.07; +0.12] | +0.04 [-0.02; +0.10] |
| (b) direnç k=2 | evet | 304 | 4.89 / 4.36 | 13.5% [10–18] (41/304) | 0.4% [0–2] (1/248) | -0.52 ±0.26 ; +0.04 [-0.23; +0.31] | -0.74 ±0.32 ; -0.02 [-0.41; +0.38] | +0.02 [-0.30; +0.35] |
| (c) ampirik q60 (60 dk MFE) | hayır | 1522 | 0.79 / 0.26 | 43.5% [41–46] (662/1522) | 6.6% [6–7] (316/4772) | -0.50 ±0.04 ; +0.03 [-0.01; +0.07] | -0.50 ±0.07 ; +0.03 [-0.05; +0.11] | +0.03 [-0.01; +0.08] |
| (c) ampirik q60 (60 dk MFE) | evet | 1 | 2.68 / 2.15 | 100.0% [21–100] (1/1) | 0.0% [0–23] (0/13) | +2.45 ; – | +2.45 ; – | – |
| (c') ampirik q60 (ufuk MFE) | hayır | 921 | 0.17 / -0.35 | 76.0% [73–79] (700/921) | 45.4% [44–47] (1810/3991) | -0.44 ±0.04 ; +0.08 [+0.04; +0.12] | -0.42 ±0.05 ; +0.08 [+0.03; +0.13] | +0.09 [+0.04; +0.13] |
| (c') ampirik q60 (ufuk MFE) | evet | 0 | – | – | – | – | – | – |

## 6. Net ≥ %2 filtresinin etkisi

- P4o. push + net ≥ %2 (eski hedefle): n=323 (42.5/gün), isabet 6.5% (21/323), net -0.48% ±0.25, eski 'ulaştı'nın 21/83'si kalır
- P4a. push + (a) + net ≥ %2: n=276 (36.3/gün), isabet 12.7% (35/276), net -0.29% ±0.39, eski 'ulaştı'nın 64/83'si kalır
- P4b. push + (b) + net ≥ %2: n=154 (20.3/gün), isabet 11.7% (18/154), net -0.35% ±0.48, eski 'ulaştı'nın 31/83'si kalır
- P4c. push + (c) + net ≥ %2: 0 bildirim
- 4o. 2 + net ≥ %2 (eski hedefle): n=78 (10.3/gün), isabet 5.1% (4/78), net -0.38% ±0.26, eski 'ulaştı'nın 4/83'si kalır
- 4a. 3a + net hedef ≥ %2: n=77 (10.1/gün), isabet 15.6% (12/77), net -0.29% ±0.28, eski 'ulaştı'nın 26/83'si kalır
- 4b. 3b + net hedef ≥ %2: n=40 (5.3/gün), isabet 7.5% (3/40), net -0.47% ±0.63, eski 'ulaştı'nın 11/83'si kalır

Net hedef ≥ %2 koşulu bildirimlerin ~%40–70'ini eler ama kalanlarda isabet düşer (hedef büyüdüğü için) ve ortalama net (7 günde −0,3…−0,5, önceki dönemde −0,4…−0,7) hâlâ negatiftir; H2'de (60 dk, ATR stop) filtreli kümelerin net'i daha da kötü ve belirsizdir (n küçük). Filtre 'umut verici görünen ama zaten ulaşılması zor hedefleri' ayıklar; ulaşılabilir hedeflerin net'i ise %2'nin altındadır — iki koşul birlikte sağlanan örneklerde hit %5–15, başabaş ise %45–60.

## 7. Aday kümeleri — politika NE gönderirdi?

**Hız Avcısı adayları (velocity_candidates; tek kaynak = Hız, dolayısıyla teyit şartı uygulanamaz; yalnız dinamik hedef + net ≥ %2 aşamaları).**

Son 7 gün:

| Aşama | n | n/gün | ort. hedef % | hit (ufuk) [Wilson95] | rastgele hit (oyn.-eşl.) | hit 60 dk | rastgele hit60 (oyn.-eşl.) | eski 'ulaştı' payı |
|---|---|---|---|---|---|---|---|---|
| 0. tüm Hız Avcısı adayları (sıra≤10, 60 dk soğuma) | 2554 | 336.1 | 2.91 | 4.6% [4–6] (118/2554) | 0.4% [0–1] (5/1427) | 25.2% [24–27] (643/2554) | 6.7% [5–8] (95/1427) | 118/118 (100%) |
| net≥2 (eski hedef) | 1746 | 229.8 | 3.42 | 1.8% [1–3] (31/1746) | 0.2% [0–1] (2/946) | 20.0% [18–22] (349/1746) | 3.5% [2–5] (33/946) | 31/118 (26%) |
| (a) ATR k=1.5 | 2554 | 336.1 | 1.58 | 13.0% [12–14] (331/2554) | 6.7% [5–8] (95/1427) | 50.5% [49–52] (1290/2554) | 39.9% [37–43] (570/1427) | 118/118 (100%) |
| (b) direnç k=1.5 | 2554 | 336.1 | 1.27 | 20.6% [19–22] (525/2554) | 8.9% [8–10] (127/1427) | 57.2% [55–59] (1462/2554) | 43.2% [41–46] (616/1427) | 118/118 (100%) |
| (c) ampirik | 2500 | 329.0 | 0.76 | 29.5% [28–31] (738/2500) | 7.5% [6–9] (102/1359) | 65.6% [64–67] (1640/2500) | 39.1% [37–42] (531/1359) | 117/118 (99%) |
| (a) + net≥2 | 402 | 52.9 | 3.96 | 6.7% [5–10] (27/402) | 3.7% [1–18] (1/27) | 35.1% [31–40] (141/402) | 11.1% [4–28] (3/27) | 58/118 (49%) |
| (b) + net≥2 | 251 | 33.0 | 3.95 | 6.4% [4–10] (16/251) | 5.3% [1–25] (1/19) | 31.5% [26–37] (79/251) | 10.5% [3–31] (2/19) | 31/118 (26%) |
| (c) + net≥2 | 0 | 0.0 | – | – | – | – | – | 0/118 (0%) |
| (a k=2) + net≥2 | 646 | 85.0 | 4.39 | 3.9% [3–6] (25/646) | 0.0% [0–6] (0/61) | 28.6% [25–32] (185/646) | 14.8% [8–26] (9/61) | 73/118 (62%) |
| (b k=2) + net≥2 | 374 | 49.2 | 4.17 | 5.6% [4–8] (21/374) | 0.0% [0–10] (0/34) | 27.8% [24–33] (104/374) | 17.6% [8–34] (6/34) | 40/118 (34%) |

| Aşama | n | net H1 [%95] | kazanan % | rastgele H1 | fark H1 (rast.) [%95] | oyn.-eşl. H1 | fark H1 (oyn.) [%95] | toplam net/gün (puan) |
|---|---|---|---|---|---|---|---|---|
| 0. tüm Hız Avcısı adayları (sıra≤10, 60 dk soğuma) | 2554 | -0.50 ±0.04 | 22% | -0.53 ±0.01 | +0.03 [-0.01; +0.07] | -0.55 ±0.04 | +0.04 [-0.01; +0.10] | -168.1 |
| net≥2 (eski hedef) | 1746 | -0.54 ±0.06 | 21% | -0.52 ±0.01 | -0.01 [-0.08; +0.05] | -0.53 ±0.03 | -0.01 [-0.08; +0.06] | -123.1 |
| (a) ATR k=1.5 | 2554 | -0.51 ±0.04 | 24% | -0.53 ±0.01 | +0.02 [-0.02; +0.07] | -0.54 ±0.04 | +0.04 [-0.02; +0.09] | -170.3 |
| (b) direnç k=1.5 | 2554 | -0.50 ±0.03 | 26% | -0.53 ±0.01 | +0.03 [-0.01; +0.07] | -0.54 ±0.04 | +0.04 [-0.01; +0.09] | -168.0 |
| (c) ampirik | 2500 | -0.49 ±0.04 | 29% | -0.53 ±0.01 | +0.03 [-0.00; +0.07] | -0.55 ±0.03 | +0.05 [-0.00; +0.10] | -162.8 |
| (a) + net≥2 | 402 | -0.56 ±0.13 | 31% | -0.76 ±0.46 | +0.20 [-0.28; +0.68] | -0.61 ±0.53 | +0.05 [-0.50; +0.60] | -29.7 |
| (b) + net≥2 | 251 | -0.59 ±0.13 | 31% | -0.33 ±0.26 | -0.26 [-0.55; +0.03] | -0.70 ±0.62 | +0.11 [-0.53; +0.75] | -19.4 |
| (a k=2) + net≥2 | 646 | -0.55 ±0.12 | 30% | -0.68 ±0.15 | +0.13 [-0.07; +0.32] | -0.71 ±0.17 | +0.16 [-0.05; +0.36] | -47.1 |
| (b k=2) + net≥2 | 374 | -0.55 ±0.13 | 30% | -0.33 ±0.18 | -0.21 [-0.43; +0.01] | -0.67 ±0.28 | +0.12 [-0.18; +0.43] | -27.0 |

| Aşama | n | net H2 | rastgele H2 | fark H2 (rast.) | net H1, iyimser kayma %0,05 | rastgele (iyimser) | brüt 60 dk getiri (ücretsiz) | rastgele brüt 60 dk | fark brüt 60 dk |
|---|---|---|---|---|---|---|---|---|---|
| 0. tüm Hız Avcısı adayları (sıra≤10, 60 dk soğuma) | 2554 | -0.51 ±0.14 | -0.61 ±0.05 | +0.09 [-0.05; +0.24] | -0.30 ±0.04 | -0.33 ±0.01 | -0.17 ±0.21 | -0.12 ±0.08 | -0.05 [-0.28; +0.18] |
| net≥2 (eski hedef) | 1746 | -0.56 ±0.17 | -0.61 ±0.06 | +0.05 [-0.13; +0.23] | -0.34 ±0.06 | -0.32 ±0.01 | -0.26 ±0.27 | -0.11 ±0.08 | -0.15 [-0.43; +0.13] |
| (a) ATR k=1.5 | 2554 | -0.50 ±0.07 | -0.56 ±0.04 | +0.06 [-0.02; +0.14] | -0.32 ±0.04 | -0.34 ±0.01 | -0.17 ±0.21 | -0.12 ±0.08 | -0.05 [-0.27; +0.18] |
| (b) direnç k=1.5 | 2554 | -0.51 ±0.05 | -0.56 ±0.04 | +0.05 [-0.02; +0.11] | -0.32 ±0.03 | -0.34 ±0.01 | -0.17 ±0.21 | -0.12 ±0.08 | -0.05 [-0.27; +0.18] |
| (c) ampirik | 2500 | -0.49 ±0.05 | -0.56 ±0.04 | +0.07 [+0.01; +0.13] | -0.32 ±0.03 | -0.33 ±0.01 | -0.16 ±0.21 | -0.12 ±0.08 | -0.04 [-0.27; +0.19] |
| (a) + net≥2 | 402 | -0.57 ±0.23 | -0.65 ±0.35 | +0.09 [-0.33; +0.50] | -0.37 ±0.11 | -0.55 ±0.48 | -0.44 ±0.24 | -0.04 ±0.90 | -0.40 [-1.33; +0.54] |
| (b) + net≥2 | 251 | -0.77 ±0.22 | -0.33 ±0.21 | -0.44 [-0.74; -0.14] | -0.39 ±0.14 | -0.09 ±0.27 | -0.50 ±0.41 | -0.22 ±0.35 | -0.27 [-0.81; +0.27] |
| (a k=2) + net≥2 | 646 | -0.62 ±0.19 | -0.90 ±0.10 | +0.28 [+0.07; +0.49] | -0.36 ±0.12 | -0.48 ±0.15 | -0.39 ±0.31 | -0.52 ±0.19 | +0.14 [-0.23; +0.50] |
| (b k=2) + net≥2 | 374 | -0.69 ±0.27 | -0.70 ±0.27 | +0.00 [-0.37; +0.38] | -0.35 ±0.13 | -0.13 ±0.18 | -0.35 ±0.43 | -0.05 ±0.69 | -0.30 [-1.11; +0.51] |

Önceki dönem (21.09 → 09.10):

| Aşama | n | n/gün | ort. hedef % | hit (ufuk) [Wilson95] | rastgele hit (oyn.-eşl.) | hit 60 dk | rastgele hit60 (oyn.-eşl.) | eski 'ulaştı' payı |
|---|---|---|---|---|---|---|---|---|
| 0. tüm Hız Avcısı adayları (sıra≤10, 60 dk soğuma) | 4637 | 244.1 | 3.17 | 2.6% [2–3] (120/4637) | 0.1% [0–0] (1/1739) | 21.4% [20–23] (990/4637) | 2.6% [2–4] (46/1739) | 120/120 (100%) |
| net≥2 (eski hedef) | 3758 | 197.8 | 3.44 | 1.9% [2–2] (73/3758) | 0.1% [0–0] (1/1396) | 19.9% [19–21] (747/3758) | 1.0% [1–2] (14/1396) | 73/120 (61%) |
| (a) ATR k=1.5 | 4636 | 244.0 | 1.53 | 13.9% [13–15] (643/4636) | 6.9% [6–8] (120/1739) | 51.4% [50–53] (2383/4636) | 46.9% [45–49] (816/1739) | 120/120 (100%) |
| (b) direnç k=1.5 | 4636 | 244.0 | 1.24 | 21.3% [20–22] (987/4636) | 8.3% [7–10] (144/1739) | 57.6% [56–59] (2671/4636) | 49.5% [47–52] (860/1739) | 120/120 (100%) |
| (c) ampirik | 4019 | 211.5 | 0.90 | 24.3% [23–26] (975/4019) | 4.4% [3–6] (62/1411) | 61.9% [60–63] (2486/4019) | 39.6% [37–42] (559/1411) | 100/120 (83%) |
| (a) + net≥2 | 632 | 33.3 | 4.05 | 5.4% [4–7] (34/632) | 0.0% [0–49] (0/4) | 35.3% [32–39] (223/632) | 0.0% [0–49] (0/4) | 51/120 (42%) |
| (b) + net≥2 | 435 | 22.9 | 4.01 | 5.3% [4–8] (23/435) | 0.0% [0–66] (0/2) | 33.8% [30–38] (147/435) | 0.0% [0–66] (0/2) | 36/120 (30%) |
| (c) + net≥2 | 7 | 0.4 | 2.87 | 0.0% [0–35] (0/7) | 0.0% [0–66] (0/2) | 14.3% [3–51] (1/7) | 0.0% [0–66] (0/2) | 0/120 (0%) |
| (a k=2) + net≥2 | 1087 | 57.2 | 4.35 | 3.6% [3–5] (39/1087) | 0.0% [0–8] (0/42) | 28.7% [26–31] (312/1087) | 9.5% [4–22] (4/42) | 68/120 (57%) |
| (b k=2) + net≥2 | 642 | 33.8 | 4.23 | 4.0% [3–6] (26/642) | 0.0% [0–10] (0/35) | 29.6% [26–33] (190/642) | 11.4% [5–26] (4/35) | 47/120 (39%) |

| Aşama | n | net H1 [%95] | kazanan % | rastgele H1 | fark H1 (rast.) [%95] | oyn.-eşl. H1 | fark H1 (oyn.) [%95] | toplam net/gün (puan) |
|---|---|---|---|---|---|---|---|---|
| 0. tüm Hız Avcısı adayları (sıra≤10, 60 dk soğuma) | 4637 | -0.55 ±0.03 | 20% | -0.53 ±0.01 | -0.02 [-0.05; +0.02] | -0.55 ±0.02 | -0.00 [-0.04; +0.04] | -133.8 |
| net≥2 (eski hedef) | 3758 | -0.56 ±0.04 | 20% | -0.53 ±0.01 | -0.02 [-0.06; +0.02] | -0.54 ±0.02 | -0.01 [-0.06; +0.03] | -110.2 |
| (a) ATR k=1.5 | 4636 | -0.55 ±0.03 | 22% | -0.53 ±0.01 | -0.01 [-0.05; +0.02] | -0.54 ±0.02 | -0.00 [-0.04; +0.04] | -133.0 |
| (b) direnç k=1.5 | 4636 | -0.54 ±0.04 | 24% | -0.53 ±0.01 | -0.01 [-0.05; +0.03] | -0.54 ±0.02 | +0.00 [-0.04; +0.04] | -131.8 |
| (c) ampirik | 4019 | -0.53 ±0.04 | 26% | -0.53 ±0.01 | -0.00 [-0.04; +0.03] | -0.55 ±0.03 | +0.01 [-0.03; +0.06] | -112.7 |
| (a) + net≥2 | 632 | -0.71 ±0.17 | 27% | -0.84 ±0.25 | +0.13 [-0.17; +0.42] | -1.16 ±0.32 | +0.45 [+0.09; +0.81] | -23.7 |
| (b) + net≥2 | 435 | -0.63 ±0.18 | 27% | -0.27 ±0.15 | -0.36 [-0.60; -0.12] | -1.11 ±0.00 | +0.48 [+0.30; +0.66] | -14.4 |
| (c) + net≥2 | 7 | -1.29 ±0.69 | 29% | -0.74 ±0.00 | -0.55 [-1.24; +0.14] | -0.57 ±0.07 | -0.72 [-1.41; -0.03] | -0.5 |
| (a k=2) + net≥2 | 1087 | -0.65 ±0.10 | 26% | -0.60 ±0.32 | -0.05 [-0.39; +0.29] | -0.67 ±0.12 | +0.02 [-0.14; +0.18] | -37.1 |
| (b k=2) + net≥2 | 642 | -0.63 ±0.11 | 26% | -0.53 ±0.43 | -0.10 [-0.54; +0.34] | -0.62 ±0.11 | -0.01 [-0.17; +0.15] | -21.3 |

**Birleşik tarama journal'ı** (yalnız 14.10 05:30 → 16.10 01:55, **~1,85 gün**; satırlar çoğunlukla push KARARI almamış gölge adaylardır — short_squeeze/pulse/snapback kaynakları bildirim kaynağı değildir; 30 dk sembol soğuması uygulandı):

| Aşama | n | n/gün | ort. hedef % | hit (ufuk) [Wilson95] | rastgele hit (oyn.-eşl.) | hit 60 dk | rastgele hit60 (oyn.-eşl.) | eski 'ulaştı' payı |
|---|---|---|---|---|---|---|---|---|
| 0. tüm birleşik tarama adayları (30 dk soğuma) | 2471 | 1335.2 | 4.29 | 0.5% [0–1] (12/2471) | 0.1% [0–0] (1/1508) | 6.4% [6–7] (159/2471) | 1.3% [1–2] (20/1508) | 12/32 (38%) |
| ≥2 kaynak | 2189 | 1182.8 | 4.47 | 0.5% [0–1] (10/2189) | 0.1% [0–0] (1/1377) | 5.2% [4–6] (113/2189) | 1.3% [1–2] (18/1377) | 10/32 (31%) |
| ≥3 kaynak | 499 | 269.6 | 5.73 | 1.4% [1–3] (7/499) | 0.0% [0–2] (0/214) | 13.8% [11–17] (69/499) | 0.9% [0–3] (2/214) | 7/32 (22%) |
| ≥2 aile | 2189 | 1182.8 | 4.47 | 0.5% [0–1] (10/2189) | 0.1% [0–0] (1/1377) | 5.2% [4–6] (113/2189) | 1.3% [1–2] (18/1377) | 10/32 (31%) |
| ≥2 bildirim kaynağı (velocity/jump/early/rising) | 447 | 241.5 | 5.75 | 1.1% [0–3] (5/447) | 0.0% [0–2] (0/192) | 13.4% [11–17] (60/447) | 1.0% [0–4] (2/192) | 5/32 (16%) |
| ≥2 bildirim kaynağı + (b) + net≥2 | 79 | 42.7 | 3.68 | 1.3% [0–7] (1/79) | 0.0% [0–79] (0/1) | 34.2% [25–45] (27/79) | 0.0% [0–79] (0/1) | 0/32 (0%) |
| ≥2 bildirim kaynağı + net≥2 (eski) | 371 | 200.5 | 6.50 | 1.1% [0–3] (4/371) | 0.0% [0–2] (0/159) | 9.4% [7–13] (35/371) | 1.3% [0–4] (2/159) | 4/32 (12%) |
| ≥2 kaynak + (a) | 2176 | 1175.8 | 1.05 | 8.6% [7–10] (187/2176) | 8.9% [7–10] (121/1365) | 49.7% [48–52] (1081/2176) | 48.9% [46–52] (668/1365) | 10/32 (31%) |
| ≥2 kaynak + (b) | 2176 | 1175.8 | 0.90 | 11.8% [10–13] (256/2176) | 10.8% [9–13] (147/1365) | 52.9% [51–55] (1152/2176) | 51.4% [49–54] (701/1365) | 10/32 (31%) |
| ≥2 kaynak + (c) | 2134 | 1153.1 | 0.71 | 15.4% [14–17] (328/2134) | 7.9% [7–10] (105/1323) | 53.1% [51–55] (1133/2134) | 41.2% [39–44] (545/1323) | 10/32 (31%) |
| ≥2 kaynak + (a) + net≥2 | 170 | 91.9 | 3.94 | 4.1% [2–8] (7/170) | 0.0% [0–79] (0/1) | 25.9% [20–33] (44/170) | 0.0% [0–79] (0/1) | 4/32 (12%) |
| ≥2 kaynak + (b) + net≥2 | 113 | 61.1 | 3.92 | 2.7% [1–8] (3/113) | 0.0% [0–79] (0/1) | 25.7% [19–34] (29/113) | 0.0% [0–79] (0/1) | 2/32 (6%) |
| ≥2 kaynak + (c) + net≥2 | 0 | 0.0 | – | – | – | – | – | 0/32 (0%) |
| ≥2 kaynak + net≥2 (eski) | 2059 | 1112.6 | 4.62 | 0.4% [0–1] (8/2059) | 0.0% [0–0] (0/1313) | 3.8% [3–5] (79/2059) | 1.1% [1–2] (14/1313) | 8/32 (25%) |
| hepsi + (b) + net≥2 | 113 | 61.1 | 3.89 | 1.8% [0–6] (2/113) | 0.0% [0–79] (0/1) | 24.8% [18–33] (28/113) | 0.0% [0–79] (0/1) | 1/32 (3%) |

| Aşama | n | net H1 [%95] | kazanan % | rastgele H1 | fark H1 (rast.) [%95] | oyn.-eşl. H1 | fark H1 (oyn.) [%95] | toplam net/gün (puan) |
|---|---|---|---|---|---|---|---|---|
| 0. tüm birleşik tarama adayları (30 dk soğuma) | 2471 | -0.53 ±0.06 | 13% | -0.52 ±0.03 | -0.01 [-0.07; +0.06] | -0.52 ±0.03 | -0.01 [-0.07; +0.06] | -707.0 |
| ≥2 kaynak | 2189 | -0.54 ±0.04 | 12% | -0.52 ±0.03 | -0.02 [-0.07; +0.03] | -0.52 ±0.03 | -0.02 [-0.07; +0.03] | -640.5 |
| ≥3 kaynak | 499 | -0.47 ±0.02 | 25% | -0.50 ±0.00 | +0.04 [+0.02; +0.06] | -0.52 ±0.01 | +0.05 [+0.03; +0.07] | -126.3 |
| ≥2 aile | 2189 | -0.54 ±0.04 | 12% | -0.52 ±0.03 | -0.02 [-0.07; +0.03] | -0.52 ±0.03 | -0.02 [-0.07; +0.03] | -640.5 |
| ≥2 bildirim kaynağı (velocity/jump/early/rising) | 447 | -0.50 ±0.00 | 23% | -0.50 ±0.01 | -0.00 [-0.01; +0.01] | -0.53 ±0.01 | +0.02 [+0.01; +0.03] | -121.7 |
| ≥2 bildirim kaynağı + (b) + net≥2 | 79 | -0.50 ±0.11 | 34% | -0.52 | – | -0.52 | – | -21.2 |
| ≥2 bildirim kaynağı + net≥2 (eski) | 371 | -0.49 ±0.01 | 26% | -0.51 ±0.01 | +0.02 [+0.01; +0.03] | -0.52 ±0.00 | +0.04 [+0.03; +0.04] | -97.8 |
| ≥2 kaynak + (a) | 2176 | -0.54 ±0.04 | 13% | -0.52 ±0.02 | -0.01 [-0.06; +0.03] | -0.53 ±0.02 | -0.01 [-0.05; +0.03] | -633.5 |
| ≥2 kaynak + (b) | 2176 | -0.54 ±0.03 | 14% | -0.52 ±0.03 | -0.02 [-0.05; +0.02] | -0.53 ±0.02 | -0.01 [-0.05; +0.02] | -633.1 |
| ≥2 kaynak + (c) | 2134 | -0.54 ±0.04 | 14% | -0.52 ±0.01 | -0.02 [-0.06; +0.02] | -0.53 ±0.01 | -0.02 [-0.06; +0.03] | -624.7 |
| ≥2 kaynak + (a) + net≥2 | 170 | -0.44 ±0.16 | 34% | -0.34 ±0.00 | -0.10 [-0.27; +0.06] | -0.52 | – | -40.7 |
| ≥2 kaynak + (b) + net≥2 | 113 | -0.46 ±0.10 | 31% | -0.52 | – | -0.52 | – | -27.9 |
| ≥2 kaynak + net≥2 (eski) | 2059 | -0.54 ±0.04 | 12% | -0.52 ±0.03 | -0.01 [-0.07; +0.04] | -0.52 ±0.03 | -0.01 [-0.07; +0.04] | -597.5 |
| hepsi + (b) + net≥2 | 113 | -0.45 ±0.17 | 29% | -0.92 ±0.55 | +0.48 [-0.10; +1.05] | -0.52 | – | -27.2 |

## 8. Dayanıklılık — önceki dönem ve haftalık

Önceki dönem (17.09 → 09.10) bildirim hunisi (**yalnız kaynak bilgisi olan satırlar**; ilk hafta 17–25.09 `sources` hep dolu, 26.09–11.10 arası ~%20–35'i NULL):

| Aşama | n | n/gün | ort. hedef % | hit (ufuk) [Wilson95] | rastgele hit (oyn.-eşl.) | hit 60 dk | rastgele hit60 (oyn.-eşl.) | eski 'ulaştı' payı |
|---|---|---|---|---|---|---|---|---|
| 0. Mevcut: gönderilen tümü (push+panel) | 1671 | 74.7 | 2.92 | 13.3% [12–15] (222/1671) | 0.8% [1–1] (42/5032) | 41.1% [39–43] (687/1671) | 13.8% [13–15] (693/5032) | 222/222 (100%) |
| 1. + yalnız push (panel kaldırıldı) | 1531 | 68.4 | 2.87 | 13.7% [12–15] (209/1531) | 0.9% [1–1] (41/4775) | 41.9% [39–44] (641/1531) | 14.2% [13–15] (676/4775) | 209/222 (94%) |
| 2. + ≥2 farklı kaynak | 1278 | 57.1 | 2.87 | 11.5% [10–13] (147/1278) | 0.8% [1–1] (38/4688) | 40.2% [38–43] (514/1278) | 13.9% [13–15] (652/4688) | 147/222 (66%) |
| 2b. + ≥3 kaynak | 1137 | 50.8 | 2.75 | 12.4% [11–14] (141/1137) | 1.0% [1–1] (38/3728) | 43.0% [40–46] (489/1137) | 16.6% [15–18] (619/3728) | 141/222 (64%) |
| 2c. + ≥4 kaynak | 184 | 8.2 | 3.04 | 23.9% [18–31] (44/184) | 6.8% [2–18] (3/44) | 63.0% [56–70] (116/184) | 38.6% [26–53] (17/44) | 44/222 (20%) |
| 2d. + ≥2 aile (jump+early tek sayılır) | 1140 | 50.9 | 2.75 | 12.4% [11–14] (141/1140) | 1.0% [1–1] (38/3761) | 42.9% [40–46] (489/1140) | 16.5% [15–18] (621/3761) | 141/222 (64%) |
| 3a. 2 + dinamik hedef (a: ATR) | 1278 | 57.1 | 2.16 | 16.4% [15–19] (210/1278) | 6.4% [6–7] (298/4687) | 57.3% [55–60] (732/1278) | 50.5% [49–52] (2368/4687) | 147/222 (66%) |
| 3b. 2 + dinamik hedef (b: direnç) | 1278 | 57.1 | 1.37 | 32.6% [30–35] (416/1278) | 8.7% [8–10] (409/4687) | 69.0% [66–71] (882/1278) | 53.3% [52–55] (2497/4687) | 147/222 (66%) |
| 3c. 2 + dinamik hedef (c: ampirik) | 1277 | 57.1 | 0.80 | 40.8% [38–44] (521/1277) | 6.4% [6–7] (298/4685) | 74.2% [72–77] (948/1277) | 45.8% [44–47] (2144/4685) | 147/222 (66%) |
| 4a. 3a + net hedef ≥ %2 | 372 | 16.6 | 4.59 | 11.0% [8–15] (41/372) | 1.6% [1–5] (3/187) | 45.7% [41–51] (170/372) | 27.3% [21–34] (51/187) | 89/222 (40%) |
| 4b. 3b + net hedef ≥ %2 | 170 | 7.6 | 4.29 | 14.7% [10–21] (25/170) | 0.7% [0–4] (1/138) | 50.0% [43–57] (85/170) | 24.6% [18–32] (34/138) | 47/222 (21%) |
| 4c. 3c + net hedef ≥ %2 | 0 | 0.0 | – | – | – | – | – | 0/222 (0%) |
| 4o. 2 + net ≥ %2 (eski hedefle) | 757 | 33.8 | 3.67 | 8.9% [7–11] (67/757) | 0.3% [0–1] (8/2569) | 30.8% [28–34] (233/757) | 4.7% [4–6] (121/2569) | 67/222 (30%) |
| P3a. push + dinamik (a) | 1531 | 68.4 | 2.41 | 17.3% [15–19] (265/1531) | 6.4% [6–7] (305/4774) | 56.4% [54–59] (863/1531) | 50.6% [49–52] (2415/4774) | 209/222 (94%) |
| P3b. push + dinamik (b) | 1531 | 68.4 | 1.54 | 33.6% [31–36] (515/1531) | 8.8% [8–10] (419/4774) | 68.3% [66–71] (1045/1531) | 53.4% [52–55] (2547/4774) | 209/222 (94%) |
| P3c. push + dinamik (c) | 1522 | 68.0 | 0.79 | 43.5% [41–46] (662/1522) | 6.6% [6–7] (316/4772) | 74.7% [72–77] (1137/1522) | 46.1% [45–48] (2202/4772) | 206/222 (93%) |
| P4a. push + (a) + net ≥ %2 | 514 | 23.0 | 4.79 | 12.5% [10–16] (64/514) | 2.3% [1–5] (5/213) | 46.5% [42–51] (239/514) | 31.5% [26–38] (67/213) | 135/222 (61%) |
| P4b. push + (b) + net ≥ %2 | 247 | 11.0 | 4.51 | 16.6% [12–22] (41/247) | 2.0% [1–6] (3/153) | 50.6% [44–57] (125/247) | 28.1% [22–36] (43/153) | 74/222 (33%) |
| P4c. push + (c) + net ≥ %2 | 1 | 0.0 | 2.68 | 100.0% [21–100] (1/1) | 0.0% [0–23] (0/13) | 100.0% [21–100] (1/1) | 23.1% [8–50] (3/13) | 1/222 (0%) |
| P4o. push + net ≥ %2 (eski hedefle) | 912 | 40.8 | 3.59 | 10.7% [9–13] (98/912) | 0.3% [0–1] (9/2628) | 32.8% [30–36] (299/912) | 5.2% [4–6] (136/2628) | 98/222 (44%) |
| T1. yalnız ≥2 kaynak (panel dahil) | 1386 | 61.9 | 2.93 | 11.3% [10–13] (156/1386) | 0.8% [1–1] (39/4932) | 39.5% [37–42] (547/1386) | 13.5% [13–14] (665/4932) | 156/222 (70%) |
| T2. yalnız net ≥ %2 (eski hedef, hepsi) | 1027 | 45.9 | 3.60 | 10.5% [9–13] (108/1027) | 0.3% [0–1] (9/2876) | 32.3% [30–35] (332/1027) | 5.2% [4–6] (149/2876) | 108/222 (49%) |

| Aşama | n | net H1 [%95] | kazanan % | rastgele H1 | fark H1 (rast.) [%95] | oyn.-eşl. H1 | fark H1 (oyn.) [%95] | toplam net/gün (puan) |
|---|---|---|---|---|---|---|---|---|
| 0. Mevcut: gönderilen tümü (push+panel) | 1671 | -0.50 ±0.05 | 29% | -0.53 ±0.01 | +0.03 [-0.02; +0.08] | -0.53 ±0.02 | +0.04 [-0.01; +0.09] | -37.0 |
| 1. + yalnız push (panel kaldırıldı) | 1531 | -0.47 ±0.05 | 30% | -0.53 ±0.01 | +0.05 [+0.00; +0.11] | -0.53 ±0.02 | +0.06 [+0.01; +0.12] | -32.3 |
| 2. + ≥2 farklı kaynak | 1278 | -0.47 ±0.07 | 28% | -0.53 ±0.01 | +0.06 [-0.02; +0.13] | -0.53 ±0.02 | +0.06 [-0.01; +0.14] | -26.8 |
| 2b. + ≥3 kaynak | 1137 | -0.48 ±0.08 | 29% | -0.53 ±0.01 | +0.05 [-0.04; +0.13] | -0.54 ±0.02 | +0.06 [-0.03; +0.14] | -24.3 |
| 2c. + ≥4 kaynak | 184 | -0.65 ±0.27 | 38% | -0.54 ±0.01 | -0.11 [-0.38; +0.16] | -0.77 ±0.59 | +0.12 [-0.53; +0.77] | -5.3 |
| 2d. + ≥2 aile (jump+early tek sayılır) | 1140 | -0.48 ±0.08 | 29% | -0.53 ±0.01 | +0.05 [-0.04; +0.13] | -0.54 ±0.02 | +0.06 [-0.03; +0.14] | -24.4 |
| 3a. 2 + dinamik hedef (a: ATR) | 1278 | -0.50 ±0.08 | 28% | -0.53 ±0.01 | +0.03 [-0.05; +0.10] | -0.54 ±0.02 | +0.04 [-0.04; +0.12] | -28.4 |
| 3b. 2 + dinamik hedef (b: direnç) | 1278 | -0.49 ±0.06 | 35% | -0.53 ±0.01 | +0.04 [-0.03; +0.10] | -0.53 ±0.02 | +0.04 [-0.02; +0.11] | -28.0 |
| 3c. 2 + dinamik hedef (c: ampirik) | 1277 | -0.48 ±0.04 | 39% | -0.53 ±0.01 | +0.04 [+0.00; +0.09] | -0.53 ±0.02 | +0.05 [+0.01; +0.10] | -27.5 |
| 4a. 3a + net hedef ≥ %2 | 372 | -0.71 ±0.21 | 30% | -0.65 ±0.08 | -0.06 [-0.29; +0.17] | -0.65 ±0.23 | -0.05 [-0.37; +0.26] | -11.8 |
| 4b. 3b + net hedef ≥ %2 | 170 | -0.54 ±0.36 | 32% | -0.59 ±0.11 | +0.05 [-0.32; +0.43] | -0.60 ±0.28 | +0.06 [-0.39; +0.51] | -4.1 |
| 4o. 2 + net ≥ %2 (eski hedefle) | 757 | -0.41 ±0.10 | 29% | -0.53 ±0.01 | +0.12 [+0.02; +0.22] | -0.52 ±0.03 | +0.12 [+0.01; +0.22] | -13.8 |
| P3a. push + dinamik (a) | 1531 | -0.51 ±0.06 | 29% | -0.53 ±0.00 | +0.02 [-0.04; +0.08] | -0.54 ±0.02 | +0.03 [-0.03; +0.09] | -34.6 |
| P3b. push + dinamik (b) | 1531 | -0.49 ±0.05 | 36% | -0.53 ±0.00 | +0.03 [-0.02; +0.09] | -0.53 ±0.02 | +0.04 [-0.01; +0.10] | -33.6 |
| P3c. push + dinamik (c) | 1522 | -0.50 ±0.04 | 42% | -0.53 ±0.01 | +0.03 [-0.01; +0.07] | -0.53 ±0.02 | +0.03 [-0.01; +0.08] | -34.0 |
| P4a. push + (a) + net ≥ %2 | 514 | -0.67 ±0.15 | 31% | -0.61 ±0.08 | -0.06 [-0.24; +0.11] | -0.62 ±0.27 | -0.06 [-0.37; +0.25] | -15.5 |
| P4b. push + (b) + net ≥ %2 | 247 | -0.53 ±0.32 | 33% | -0.56 ±0.10 | +0.03 [-0.31; +0.37] | -0.58 ±0.35 | +0.05 [-0.42; +0.52] | -5.9 |
| P4c. push + (c) + net ≥ %2 | 1 | +2.45 | 100% | -0.55 ±0.07 | – | -0.61 ±0.33 | – | +0.1 |
| P4o. push + net ≥ %2 (eski hedefle) | 912 | -0.44 ±0.08 | 30% | -0.53 ±0.01 | +0.09 [+0.01; +0.17] | -0.53 ±0.03 | +0.09 [+0.00; +0.17] | -17.8 |
| T1. yalnız ≥2 kaynak (panel dahil) | 1386 | -0.48 ±0.06 | 28% | -0.53 ±0.01 | +0.04 [-0.02; +0.11] | -0.54 ±0.02 | +0.05 [-0.01; +0.12] | -29.9 |
| T2. yalnız net ≥ %2 (eski hedef, hepsi) | 1027 | -0.47 ±0.07 | 30% | -0.53 ±0.01 | +0.06 [-0.01; +0.13] | -0.53 ±0.03 | +0.06 [-0.02; +0.14] | -21.5 |

| Aşama | n | net H2 | rastgele H2 | fark H2 (rast.) | net H1, iyimser kayma %0,05 | rastgele (iyimser) | brüt 60 dk getiri (ücretsiz) | rastgele brüt 60 dk | fark brüt 60 dk |
|---|---|---|---|---|---|---|---|---|---|
| 0. Mevcut: gönderilen tümü (push+panel) | 1671 | -0.54 ±0.11 | -0.54 ±0.04 | +0.00 [-0.11; +0.11] | -0.30 ±0.05 | -0.33 ±0.01 | -0.29 ±0.35 | -0.03 ±0.05 | -0.26 [-0.62; +0.10] |
| 1. + yalnız push (panel kaldırıldı) | 1531 | -0.51 ±0.11 | -0.54 ±0.04 | +0.03 [-0.09; +0.15] | -0.28 ±0.05 | -0.33 ±0.00 | -0.20 ±0.36 | -0.03 ±0.05 | -0.17 [-0.53; +0.19] |
| 2. + ≥2 farklı kaynak | 1278 | -0.53 ±0.12 | -0.53 ±0.04 | +0.00 [-0.13; +0.13] | -0.28 ±0.07 | -0.33 ±0.01 | -0.03 ±0.38 | -0.03 ±0.06 | +0.00 [-0.39; +0.39] |
| 2b. + ≥3 kaynak | 1137 | -0.54 ±0.14 | -0.53 ±0.04 | -0.01 [-0.15; +0.13] | -0.29 ±0.08 | -0.33 ±0.01 | -0.07 ±0.44 | -0.03 ±0.06 | -0.04 [-0.49; +0.40] |
| 2c. + ≥4 kaynak | 184 | -0.71 ±0.30 | -0.60 ±0.04 | -0.12 [-0.42; +0.18] | -0.44 ±0.27 | -0.34 ±0.01 | +0.17 ±1.24 | -0.08 ±0.07 | +0.25 [-0.99; +1.50] |
| 2d. + ≥2 aile (jump+early tek sayılır) | 1140 | -0.54 ±0.14 | -0.53 ±0.04 | -0.01 [-0.15; +0.14] | -0.29 ±0.08 | -0.33 ±0.01 | -0.07 ±0.44 | -0.03 ±0.06 | -0.04 [-0.49; +0.40] |
| 3a. 2 + dinamik hedef (a: ATR) | 1278 | -0.57 ±0.10 | -0.53 ±0.03 | -0.05 [-0.15; +0.06] | -0.31 ±0.08 | -0.33 ±0.00 | -0.03 ±0.38 | -0.03 ±0.06 | +0.00 [-0.39; +0.39] |
| 3b. 2 + dinamik hedef (b: direnç) | 1278 | -0.52 ±0.08 | -0.52 ±0.03 | +0.00 [-0.08; +0.08] | -0.32 ±0.06 | -0.33 ±0.00 | -0.03 ±0.38 | -0.03 ±0.06 | +0.00 [-0.39; +0.39] |
| 3c. 2 + dinamik hedef (c: ampirik) | 1277 | -0.48 ±0.07 | -0.52 ±0.03 | +0.04 [-0.04; +0.12] | -0.33 ±0.04 | -0.33 ±0.01 | -0.03 ±0.38 | -0.03 ±0.06 | -0.00 [-0.39; +0.39] |
| 4a. 3a + net hedef ≥ %2 | 372 | -0.87 ±0.28 | -0.89 ±0.29 | +0.02 [-0.38; +0.43] | -0.50 ±0.22 | -0.44 ±0.08 | -0.33 ±1.12 | -0.56 ±0.59 | +0.23 [-1.04; +1.49] |
| 4b. 3b + net hedef ≥ %2 | 170 | -0.78 ±0.46 | -0.86 ±0.30 | +0.08 [-0.47; +0.62] | -0.34 ±0.36 | -0.38 ±0.11 | -0.19 ±1.25 | -0.41 ±0.66 | +0.22 [-1.20; +1.64] |
| 4o. 2 + net ≥ %2 (eski hedefle) | 757 | -0.55 ±0.17 | -0.55 ±0.03 | -0.01 [-0.17; +0.16] | -0.22 ±0.10 | -0.33 ±0.01 | +0.08 ±0.32 | -0.03 ±0.05 | +0.11 [-0.21; +0.44] |
| P3a. push + dinamik (a) | 1531 | -0.56 ±0.11 | -0.53 ±0.03 | -0.03 [-0.14; +0.08] | -0.32 ±0.06 | -0.33 ±0.00 | -0.20 ±0.36 | -0.03 ±0.05 | -0.17 [-0.53; +0.19] |
| P3b. push + dinamik (b) | 1531 | -0.50 ±0.09 | -0.53 ±0.02 | +0.02 [-0.07; +0.11] | -0.32 ±0.05 | -0.33 ±0.00 | -0.20 ±0.36 | -0.03 ±0.05 | -0.17 [-0.53; +0.19] |
| P3c. push + dinamik (c) | 1522 | -0.50 ±0.07 | -0.53 ±0.03 | +0.03 [-0.05; +0.11] | -0.35 ±0.04 | -0.33 ±0.00 | -0.20 ±0.35 | -0.03 ±0.05 | -0.17 [-0.53; +0.19] |
| P4a. push + (a) + net ≥ %2 | 514 | -0.75 ±0.29 | -0.71 ±0.30 | -0.04 [-0.46; +0.38] | -0.47 ±0.16 | -0.41 ±0.08 | -0.57 ±0.86 | -0.47 ±0.43 | -0.09 [-1.06; +0.87] |
| P4b. push + (b) + net ≥ %2 | 247 | -0.63 ±0.43 | -0.65 ±0.31 | +0.03 [-0.51; +0.56] | -0.34 ±0.31 | -0.36 ±0.10 | -0.52 ±0.94 | -0.25 ±0.49 | -0.27 [-1.33; +0.78] |
| P4c. push + (c) + net ≥ %2 | 1 | +2.45 | -0.60 ±0.25 | – | +2.45 | -0.35 ±0.07 | -5.03 | -0.12 ±0.26 | – |
| P4o. push + net ≥ %2 (eski hedefle) | 912 | -0.55 ±0.17 | -0.55 ±0.04 | +0.00 [-0.17; +0.17] | -0.25 ±0.08 | -0.33 ±0.01 | -0.20 ±0.34 | -0.03 ±0.05 | -0.17 [-0.51; +0.17] |
| T1. yalnız ≥2 kaynak (panel dahil) | 1386 | -0.56 ±0.12 | -0.54 ±0.04 | -0.02 [-0.14; +0.10] | -0.29 ±0.06 | -0.33 ±0.01 | -0.11 ±0.39 | -0.02 ±0.06 | -0.09 [-0.48; +0.30] |
| T2. yalnız net ≥ %2 (eski hedef, hepsi) | 1027 | -0.58 ±0.14 | -0.55 ±0.04 | -0.04 [-0.18; +0.10] | -0.28 ±0.07 | -0.33 ±0.01 | -0.32 ±0.35 | -0.03 ±0.05 | -0.29 [-0.64; +0.06] |

Haftalık tablo (net H1, aynı aşamalar; H-3 haftası 9 gün ve düşük n):

| Aşama | Hafta | n | hit (ufuk) | net H1 | rastgele H1 | fark H1 |
|---|---|---|---|---|---|---|
| 1. + yalnız push (panel kaldırıldı) | H0 10.10–17.10 | 527 | 14.4% [12–18] (76/527) | -0.52 ±0.23 | -0.53 ±0.02 | +0.01 [-0.22; +0.24] |
| 1. + yalnız push (panel kaldırıldı) | H-1 03.10–09.10 | 774 | 13.4% [11–16] (104/774) | -0.52 ±0.07 | -0.52 ±0.01 | +0.00 [-0.07; +0.07] |
| 1. + yalnız push (panel kaldırıldı) | H-2 26.09–02.10 | 448 | 9.2% [7–12] (41/448) | -0.46 ±0.14 | -0.52 ±0.01 | +0.06 [-0.07; +0.20] |
| 1. + yalnız push (panel kaldırıldı) | H-3 17.09–25.09 | 931 | 14.8% [13–17] (138/931) | -0.46 ±0.07 | -0.53 ±0.01 | +0.07 [+0.00; +0.14] |
| 2. + ≥2 farklı kaynak | H0 10.10–17.10 | 151 | 17.9% [13–25] (27/151) | -0.46 ±0.20 | -0.52 ±0.02 | +0.07 [-0.13; +0.27] |
| 2. + ≥2 farklı kaynak | H-1 03.10–09.10 | 253 | 11.1% [8–16] (28/253) | -0.46 ±0.22 | -0.52 ±0.01 | +0.06 [-0.16; +0.28] |
| 2. + ≥2 farklı kaynak | H-2 26.09–02.10 | 220 | 6.4% [4–10] (14/220) | -0.44 ±0.09 | -0.53 ±0.01 | +0.09 [-0.01; +0.18] |
| 2. + ≥2 farklı kaynak | H-3 17.09–25.09 | 805 | 13.0% [11–16] (105/805) | -0.48 ±0.09 | -0.53 ±0.01 | +0.05 [-0.04; +0.14] |
| 3b. 2 + dinamik hedef (b: direnç) | H0 10.10–17.10 | 151 | 35.8% [29–44] (54/151) | -0.47 ±0.22 | -0.52 ±0.02 | +0.05 [-0.16; +0.27] |
| 3b. 2 + dinamik hedef (b: direnç) | H-1 03.10–09.10 | 253 | 31.2% [26–37] (79/253) | -0.51 ±0.18 | -0.52 ±0.01 | +0.01 [-0.17; +0.19] |
| 3b. 2 + dinamik hedef (b: direnç) | H-2 26.09–02.10 | 220 | 33.6% [28–40] (74/220) | -0.46 ±0.04 | -0.53 ±0.01 | +0.06 [+0.02; +0.11] |
| 3b. 2 + dinamik hedef (b: direnç) | H-3 17.09–25.09 | 805 | 32.7% [30–36] (263/805) | -0.49 ±0.08 | -0.53 ±0.01 | +0.04 [-0.04; +0.12] |
| 4a. 3a + net hedef ≥ %2 | H0 10.10–17.10 | 77 | 15.6% [9–25] (12/77) | -0.29 ±0.28 | -0.47 ±0.35 | +0.18 [-0.27; +0.63] |
| 4a. 3a + net hedef ≥ %2 | H-1 03.10–09.10 | 105 | 5.7% [3–12] (6/105) | -0.65 ±0.41 | -0.55 ±0.26 | -0.10 [-0.58; +0.39] |
| 4a. 3a + net hedef ≥ %2 | H-2 26.09–02.10 | 38 | 15.8% [7–30] (6/38) | -1.00 ±0.55 | -0.63 ±0.26 | -0.37 [-0.98; +0.24] |
| 4a. 3a + net hedef ≥ %2 | H-3 17.09–25.09 | 229 | 12.7% [9–18] (29/229) | -0.69 ±0.28 | -0.66 ±0.10 | -0.02 [-0.32; +0.27] |
| 4b. 3b + net hedef ≥ %2 | H0 10.10–17.10 | 40 | 7.5% [3–20] (3/40) | -0.47 ±0.63 | -0.58 ±0.46 | +0.11 [-0.68; +0.89] |
| 4b. 3b + net hedef ≥ %2 | H-1 03.10–09.10 | 48 | 6.2% [2–17] (3/48) | -0.42 ±0.70 | -0.54 ±0.21 | +0.12 [-0.62; +0.85] |
| 4b. 3b + net hedef ≥ %2 | H-2 26.09–02.10 | 19 | 5.3% [1–25] (1/19) | -0.78 ±0.66 | -0.61 ±0.22 | -0.17 [-0.86; +0.53] |
| 4b. 3b + net hedef ≥ %2 | H-3 17.09–25.09 | 103 | 20.4% [14–29] (21/103) | -0.55 ±0.47 | -0.60 ±0.14 | +0.05 [-0.43; +0.54] |
| 4c. 3c + net hedef ≥ %2 | H0 10.10–17.10 | 0 | – | – | – | – |
| 4c. 3c + net hedef ≥ %2 | H-1 03.10–09.10 | 0 | – | – | – | – |
| 4c. 3c + net hedef ≥ %2 | H-2 26.09–02.10 | 0 | – | – | – | – |
| 4c. 3c + net hedef ≥ %2 | H-3 17.09–25.09 | 0 | – | – | – | – |
| 4o. 2 + net ≥ %2 (eski hedefle) | H0 10.10–17.10 | 78 | 5.1% [2–12] (4/78) | -0.38 ±0.26 | -0.53 ±0.03 | +0.15 [-0.11; +0.41] |
| 4o. 2 + net ≥ %2 (eski hedefle) | H-1 03.10–09.10 | 173 | 5.8% [3–10] (10/173) | -0.27 ±0.23 | -0.52 ±0.01 | +0.25 [+0.02; +0.48] |
| 4o. 2 + net ≥ %2 (eski hedefle) | H-2 26.09–02.10 | 214 | 6.1% [4–10] (13/214) | -0.44 ±0.09 | -0.53 ±0.01 | +0.09 [-0.00; +0.18] |
| 4o. 2 + net ≥ %2 (eski hedefle) | H-3 17.09–25.09 | 370 | 11.9% [9–16] (44/370) | -0.45 ±0.14 | -0.53 ±0.01 | +0.08 [-0.06; +0.23] |
| P3b. push + dinamik (b) | H0 10.10–17.10 | 527 | 31.3% [27–35] (165/527) | -0.52 ±0.22 | -0.53 ±0.01 | +0.01 [-0.21; +0.23] |
| P3b. push + dinamik (b) | H-1 03.10–09.10 | 774 | 33.5% [30–37] (259/774) | -0.59 ±0.07 | -0.52 ±0.01 | -0.07 [-0.15; +0.00] |
| P3b. push + dinamik (b) | H-2 26.09–02.10 | 448 | 36.6% [32–41] (164/448) | -0.53 ±0.07 | -0.52 ±0.01 | -0.00 [-0.07; +0.06] |
| P3b. push + dinamik (b) | H-3 17.09–25.09 | 931 | 33.8% [31–37] (315/931) | -0.47 ±0.07 | -0.53 ±0.01 | +0.06 [-0.01; +0.13] |
| P4a. push + (a) + net ≥ %2 | H0 10.10–17.10 | 276 | 12.7% [9–17] (35/276) | -0.29 ±0.39 | -0.58 ±0.16 | +0.29 [-0.13; +0.71] |
| P4a. push + (a) + net ≥ %2 | H-1 03.10–09.10 | 326 | 11.3% [8–15] (37/326) | -0.77 ±0.19 | -0.57 ±0.17 | -0.20 [-0.46; +0.06] |
| P4a. push + (a) + net ≥ %2 | H-2 26.09–02.10 | 100 | 16.0% [10–24] (16/100) | -0.89 ±0.52 | -0.49 ±0.24 | -0.40 [-0.97; +0.17] |
| P4a. push + (a) + net ≥ %2 | H-3 17.09–25.09 | 316 | 12.7% [9–17] (40/316) | -0.60 ±0.21 | -0.64 ±0.11 | +0.03 [-0.21; +0.27] |
| P4b. push + (b) + net ≥ %2 | H0 10.10–17.10 | 154 | 11.7% [8–18] (18/154) | -0.35 ±0.48 | -0.52 ±0.20 | +0.17 [-0.36; +0.69] |
| P4b. push + (b) + net ≥ %2 | H-1 03.10–09.10 | 154 | 9.7% [6–15] (15/154) | -0.76 ±0.56 | -0.50 ±0.14 | -0.26 [-0.84; +0.32] |
| P4b. push + (b) + net ≥ %2 | H-2 26.09–02.10 | 52 | 11.5% [5–23] (6/52) | -0.96 ±0.31 | -0.55 ±0.26 | -0.42 [-0.82; -0.02] |
| P4b. push + (b) + net ≥ %2 | H-3 17.09–25.09 | 150 | 20.0% [14–27] (30/150) | -0.53 ±0.44 | -0.58 ±0.12 | +0.05 [-0.41; +0.51] |
| P4c. push + (c) + net ≥ %2 | H0 10.10–17.10 | 0 | – | – | – | – |
| P4c. push + (c) + net ≥ %2 | H-1 03.10–09.10 | 0 | – | – | – | – |
| P4c. push + (c) + net ≥ %2 | H-2 26.09–02.10 | 2 | 100.0% [34–100] (2/2) | -0.46 ±0.00 | -0.55 ±0.13 | +0.10 [-0.03; +0.22] |
| P4c. push + (c) + net ≥ %2 | H-3 17.09–25.09 | 0 | – | – | – | – |
| P4o. push + net ≥ %2 (eski hedefle) | H0 10.10–17.10 | 323 | 6.5% [4–10] (21/323) | -0.48 ±0.25 | -0.54 ±0.02 | +0.05 [-0.20; +0.30] |
| P4o. push + net ≥ %2 (eski hedefle) | H-1 03.10–09.10 | 539 | 7.8% [6–10] (42/539) | -0.46 ±0.07 | -0.52 ±0.01 | +0.06 [-0.01; +0.14] |
| P4o. push + net ≥ %2 (eski hedefle) | H-2 26.09–02.10 | 425 | 8.2% [6–11] (35/425) | -0.44 ±0.11 | -0.52 ±0.01 | +0.08 [-0.03; +0.20] |
| P4o. push + net ≥ %2 (eski hedefle) | H-3 17.09–25.09 | 455 | 14.1% [11–18] (64/455) | -0.43 ±0.14 | -0.53 ±0.01 | +0.11 [-0.03; +0.25] |
| T2. yalnız net ≥ %2 (eski hedef, hepsi) | H0 10.10–17.10 | 347 | 6.6% [4–10] (23/347) | -0.53 ±0.25 | -0.54 ±0.02 | +0.00 [-0.25; +0.25] |
| T2. yalnız net ≥ %2 (eski hedef, hepsi) | H-1 03.10–09.10 | 565 | 7.8% [6–10] (44/565) | -0.48 ±0.08 | -0.52 ±0.01 | +0.04 [-0.04; +0.12] |
| T2. yalnız net ≥ %2 (eski hedef, hepsi) | H-2 26.09–02.10 | 485 | 8.5% [6–11] (41/485) | -0.46 ±0.12 | -0.52 ±0.01 | +0.06 [-0.07; +0.19] |
| T2. yalnız net ≥ %2 (eski hedef, hepsi) | H-3 17.09–25.09 | 484 | 13.6% [11–17] (66/484) | -0.44 ±0.11 | -0.53 ±0.01 | +0.09 [-0.03; +0.20] |

## 9. Üretimdeki 83 satır (15.10 22:30 → 17.10)

| Üretim satırları (22:30 15.10 → 17.10) | satır | sonuçlanmış | uygulama etiketi: 'Hedefe ulaştı' [Wilson95] | bizim hesap: hit (ufuk, eski hedef) | net H1 | rastgele (oyn.-eşl.) H1 |
|---|---|---|---|---|---|---|
| tümü (push+panel) | 79 | 79 | 21.5% [14–32] (17/79) | 12.7% [7–22] (10/79) | -0.82 ±0.12 | -0.52 ±0.15 |
| yalnız push | 77 | 77 | 22.1% [14–33] (17/77) | 13.0% [7–22] (10/77) | -0.81 ±0.12 | -0.53 ±0.20 |
| panel | 2 | 2 | 0.0% [0–66] (0/2) | 0.0% [0–66] (0/2) | -1.07 ±1.37 | -0.50 ±0.23 |
| push, 1 kaynak | 69 | 69 | 21.7% [14–33] (15/69) | 13.0% [7–23] (9/69) | -0.78 ±0.13 | -0.62 ±0.25 |
| push, ≥2 kaynak | 8 | 8 | 25.0% [7–59] (2/8) | 12.5% [2–47] (1/8) | -1.04 ±0.19 | -0.38 ±0.15 |
| push, ≥3 kaynak | 8 | 8 | 25.0% [7–59] (2/8) | 12.5% [2–47] (1/8) | -1.04 ±0.19 | -0.38 ±0.15 |
| push, ≥2 aile | 8 | 8 | 25.0% [7–59] (2/8) | 12.5% [2–47] (1/8) | -1.04 ±0.19 | -0.38 ±0.15 |

| Üretim satırlarında filtre | n | hit (ufuk) | net H1 | rastgele (oyn.-eşl.) H1 |
|---|---|---|---|---|
| push + (a) k=1.5 | 77 | 16.9% [10–27] (13/77) | -0.75 ±0.10 | -0.52 ±0.20 |
| push + (b) k=1.5 | 77 | 32.5% [23–44] (25/77) | -0.78 ±0.08 | -0.51 ±0.20 |
| push + (c) | 74 | 52.7% [41–64] (39/74) | -0.67 ±0.05 | -0.49 ±0.19 |
| push + (a) + net≥2 | 31 | 16.1% [7–33] (5/31) | -0.62 ±0.15 | -1.07 ±0.66 |
| push + (b) + net≥2 | 22 | 22.7% [10–43] (5/22) | -0.40 ±0.10 | -0.91 ±0.06 |
| push + (c) + net≥2 | 0 | – | – | – |
| push + eski hedef + net≥2 | 54 | 7.4% [3–18] (4/54) | -0.83 ±0.41 | -0.50 ±0.28 |
| push+≥2 kaynak + net≥2 (eski) | 6 | 0.0% [0–39] (0/6) | -0.90 ±0.05 | -0.38 ±0.15 |

Not: Bu satırlardaki 'Hedefe ulaştı' etiketi uygulamanın kendisidir; 'bizim hesap' sütunu yukarıdaki katı ölçümdür. Son saatlerdeki 'Bekliyor' satırlar ve 60+10 dk pencere dolmayanlar dışarıdadır. Tek başına bu örnekle (n≈80, yalnızca ~8 satır ≥2 kaynaklı) hiçbir politika sonucu çıkarılamaz.

## 10. Karar

**Net-pozitif (n ≥ 100) hiçbir yapılandırma yok; bu yüzden 'kesin parametre' önerilemez.** Önerilen politikanın tüm bileşenleri (push-only, ≥2/≥3/≥4 teyit, ATR/direnç/ampirik dinamik hedef, net ≥ %2 filtresi, bunların birleşimi) 7 günde ve önceki dönemde, gerçekçi doluşla (60 sn + %0,15 kayma + %0,1125 ücret) bildirim başına ortalama net **negatif** kalır; rastgele giriş tabanı ile fark çoğunlukla sıfırdan ayırt edilemez.


**Hangi parça işe yarıyor (kârlılık değil, yanlış alarm / zarar azaltma):**

1. *Panel bildirimlerini kaldırmak*: panel bildirimleri push'tan daha kötü (net −0,8 vs −0,5; §4 tablosunda `panel` satırı) ve sayıca az; kaldırmak toplam zararı biraz azaltır, ana akışı değiştirmez.
2. *≥2 kaynak teyidi*: günlük bildirim sayısını ~%70 azaltır (≈70 → ≈20/gün), ortalama net −0,52 → −0,46 gibi küçük bir iyileşme (fark güven aralığı sıfırı içerir); 'toplam net/gün' zararı ≈ −36 puandan ≈ −9 puana iner (sadece sayı azaldığı için). Teyit sayısı ile isabet artar ama net değişmez.
3. *Dinamik hedef*: hedefi küçülttüğü için 'başarı' (hit) şişer (örn. (c) %50+), net hedef ≥ %2 koşulu ile birleşince isabet tekrar %5–15'e iner. Hedef büyüklüğü **oynaklığı** iyi öngörür (ρ≈0,3–0,4), yönü öngörmez.
4. *Net ≥ %2*: yalnızca matematiksel tutarlılık sağlar (gösterilen hedef maliyet sonrası anlamlı olur); kârlılığı pozitife çevirmez.

**Önerilen yol:** (a) 'başarı' ölçütünü 'hedefe dokunuş' yerine **maliyet sonrası realize net PnL / beklenen değer** yapın (Raporlar'da bildirim başına net ve rastgele tabana göre fark); (b) bildirimleri 'al' sinyali olarak sunmayın — veri, sinyal sonrası brüt 60 dk sürüklenmenin pozitif olmadığını (son 7 günde belirgin negatif) söylüyor (pompa kovalama); (c) ≥2 teyit + net ≥ %2'yi 'kalite filtresi' olarak (gürültüyü azaltmak için) kullanmak isterseniz bunu kârlılık iddiası olmadan yapın; (d) gerçek bir avantaj için ek, yönü öngören bir girdi (ör. taker alım baskısı, emir defteri derinliği; bu çalışmada ölçülmedi) ve out-of-sample doğrulama gerekir.

## 11. Sınırlar

- **Örneklem:** 7 günlük pencere ≈ 575 gönderilen bildirim; ≥2 kaynak ≈ 150, ≥4 kaynak ≈ 22 (güven aralıkları geniş); dinamik+net≥2 aşamalarında rastgele taban çok küçük (rastgele anlar nadiren ATR-yüksek) — fark sütunları o satırlarda zayıf, mutlak net yine ölçülmüştür.
- **Aday kümeleri:** birleşik tarama journal'ı yalnız ~1,85 gün dolu (sonrası test kirliliği: LOWTRY/MIDTRY/A/B satırları filtrelendi); 30 gün geriye journal analizi yapılamadı. Hız Avcısı adayları tek kaynaklıdır; çoklu-kaynak teyidi aday düzeyinde yeniden kurulamadı (jump/early/rising dedektörlerinin geçmiş tekrar-oynatması yok).
- **Kaynak alanı:** önceki dönemde (özellikle 26.09–11.10) `sources` NULL olan satırlar ≥2 aşamasından dışarıda; `llm_ikinci_goz` modunun tüm satırları NULL. Legacy `global_lead_lag` modu (28.09–07.10, 717 satır) çıkarıldı.
- **Ölçüm:** olay zamanı DB'de saniye çözünürlüklü, üretim satırlarında dakika çözünürlüklü (+30 sn varsayıldı); isabet ölçümümüz uygulamanınkinden sıkı (başlangıç sonraki dakika barı); dolu bar yok → flat mum doldurma; aynı sembolün art arda bildirimleri bağımsız değil (gün-kümeleme tam telafi etmez; 60 dk tekilleştirme ayrıca uygulanmadı, bildirimlerin kendi soğuması geçerli).
- **Simülatör:** TP tam fiyattan dolar (limit emri varsayımı), stop-önce bar içi sıra, sabit %0,15 kayma; gerçek derinlik/kayma sembole göre değişir (likit olmayan TRY çiftlerinde kötüleşir). 60 sn giriş gecikmesi ölçülmüş-gerçeğe yakın varsayım; 0 sn gecikmenin etkisi ayrıca sınanmadı (yalnız kayma duyarlılığı: tablo C).
- **Dinamik hedef:** k, direnç payı (0,9), tolerans (%0,3), yüzdelik (q60) tek nokta seçimleridir; k∈{1; 1,5; 2} için tablo verildi ama başka parametre ızgarası taranmadı (bu bilinçli: taranırsa çoklu-karşılaştırma yanlılığı artar). (c) için 14 günlük geçmiş en az 500 çapa ister.
- **Gün-kümeli SE:** journal setinde yalnız 2–3 gün olduğundan ±değerleri (özellikle ±0,00–0,02 olanlar) güvenilmezdir; küçük n'li taban satırlarında (n<30) fark sütunları göstermeliktir.
- **Çoklu karşılaştırma:** ~20 aşama × 2 dönem × 3 çıkış yapısı gösterildi; tek tek yorumlanan küçük farklar (+0,1 civarı) anlamlı sayılmamalı.
- **Rejim:** tek 7+23 günlük dönem; farklı piyasa rejimlerinde sonuçlar değişebilir (önceki 90 gün çalışmalarıyla tutarlı: sürüklenme negatif).
