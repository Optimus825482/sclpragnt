# İndikatör Kılavuzu — Hassasiyet (filtre) ve Hedef Boyutu Çalışması (2026-10-17)

Bu rapor `backend/scripts/indfilter_report.py` tarafından üretilmiştir (A: `indfilter_study.py`, B: `indfilter_target.py`, özellikler `indfilter_feats.py`, kütüphane `app/rescan/indicators_ext.py`). Çevrimdışı araştırma; canlı koda bağlanmaz.

## 0. Hüküm (sayılardan otomatik üretilir)

**Karar:** KISMEN: 1 kural seçim-dışı her blokta net−taban'ı küçük ölçüde iyileştirdi (ayrıntılar yukarıda) ama mutlak net her birinde NEGATİF kaldı; yani zararı azaltıyor, kâra çevirmiyor.

### 0a. Hassasiyet (filtre)

- **Hız Avcısı (90 gün, 3 blok).** 438 özellikten ATR-kontrollü net−taban'da BH q<0,05: 177 (tüm bloklarda aynı işaretli: 171); ATR-kontrollü hit'te q<0,05: 354; ham net'te q<0,05: 195. Hem hit'te hem net−taban'da anlamlı 165 özelliğin 164'sinde işaret TERS (hit'i artıran özellik net'i düşürüyor).
  En güçlü ATR-kontrollü özellikler (r, t, q, blok uyumu): `res:swing_5m` (-0.047, -6.7, 0.000, 3/3); `5m.efi13` (-0.048, -6.1, 0.000, 3/3); `idea:no_swing_high_in_target` (-0.040, -6.0, 0.000, 3/3); `5m.pvt_slope12` (-0.042, -5.5, 0.000, 3/3).
  Kural kapsamı `tümü`: seçim döneminde seçilen 6 kuraldan seçim-dışı her blokta Δ(net−taban) > 0, net(tutulan) > net(hepsi) ve birleşik %95 alt sınır > 0 olan: **1**.
  - GEÇEN KURAL `A3: res:swing_5m <= 4.965`: seçim-dışı birleşik n=4790 (81/gün), net -0.50 (hepsi -0.57), net−taban +0.25, Δ(net−taban) +0.11 [alt sınır +0.03]; blok 2: Δ +0.08, net -0.47 (hepsi -0.51), n=2202, blok 3: Δ +0.13, net -0.53 (hepsi -0.62), n=2588. Mutlak net hâlâ NEGATİF.
  Klasik fikirler (32 önceden belirlenmiş koşul): her blokta tutulan−düşen > 0 ve %95 alt sınır > 0 olan: **0**. |t| en büyük üç fikir: `no_swing_high_in_target` (Δ -0.22, t -4.5); `obv_up` (Δ -0.13, t -2.9); `adx25_di_up` (Δ -0.12, t -2.5).
  Aşırı-uyum tanısı: seçimde en iyi 50 adayın seçim-dışı ortalama Δ(net−taban) = +0.03 (pozitif pay 82%); tüm adaylar -0.00.
- **Push bildirimleri (17.09–17.10; seçim/değerlendirme).** 419 özellikten ATR-kontrollü net−taban'da BH q<0,05: 0 (tüm bloklarda aynı işaretli: 0); ATR-kontrollü hit'te q<0,05: 73; ham net'te q<0,05: 0. Hem hit'te hem net−taban'da anlamlı 0 özelliğin 0'sinde işaret TERS (hit'i artıran özellik net'i düşürüyor).
  En güçlü ATR-kontrollü özellikler (r, t, q, blok uyumu): `15m.mfi14` (-0.070, -3.5, 0.263, 2/2); `15m.rvi_vol` (-0.081, -3.4, 0.263, 2/2); `15m.obv_slope48` (-0.085, -3.4, 0.263, 2/2); `5m.ob_age` (-0.073, -3.2, 0.263, 2/2).
  Kural kapsamı `tümü`: seçim döneminde seçilen 6 kuraldan seçim-dışı her blokta Δ(net−taban) > 0, net(tutulan) > net(hepsi) ve birleşik %95 alt sınır > 0 olan: **0**.
  Kural kapsamı `teyit kuralı (yeni canlı)`: seçim döneminde seçilen 6 kuraldan seçim-dışı her blokta Δ(net−taban) > 0, net(tutulan) > net(hepsi) ve birleşik %95 alt sınır > 0 olan: **0**.
  Klasik fikirler (32 önceden belirlenmiş koşul): her blokta tutulan−düşen > 0 ve %95 alt sınır > 0 olan: **0**. |t| en büyük üç fikir: `chop_trending_15m` (Δ -0.28, t -2.2); `no_equal_highs_in_target_15m` (Δ +1.12, t +2.2); `no_swing_high_in_target` (Δ +0.26, t +1.8).
  Aşırı-uyum tanısı: seçimde en iyi 50 adayın seçim-dışı ortalama Δ(net−taban) = +0.12 (pozitif pay 88%); tüm adaylar -0.02.

### 0b. Hedef boyutu

- **Hız Avcısı / tümü.** Seçim-dışı: sabit (sinyalin) hedef net -0.57, hit 21.9%, ort. hedef 3.45%. En iyi 3 model (ham net): `ref: ATR-yalnız kuantil (q=0.4) [net]` net -0.53 (Δ vs sabit +0.04 [+0.01; +0.07]), hit 55.7%, ort. hedef 1.30%; `M1 ATR (k=0.25) [net]` net -0.53 (Δ vs sabit +0.04 [+0.01; +0.07]), hit 56.9%, ort. hedef 1.27%; `M2 ATR+direnç (poc_15m, pay 0.5, k 0.25) [net]` net -0.53 (Δ vs sabit +0.04 [+0.01; +0.07]), hit 57.7%, ort. hedef 1.22%.
  Seçim-dışı mutlak net > 0 olan model: **0**.
  Hedef doğruluğu (pinball, aynı q'lu ATR-yalnız referansa göre iyileşme; seçim-dışı bloklar): `M4 doğrusal kuantil (q=0.4, 5 özellik) [net]` blok 2: +0.2% (kısmi Spearman | ATR +0.103); `M4 doğrusal kuantil (q=0.4, 5 özellik) [net]` blok 3: +0.4% (kısmi Spearman | ATR +0.097); `M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban]` blok 2: +1.1% (kısmi Spearman | ATR +0.134); `M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban]` blok 3: +0.4% (kısmi Spearman | ATR +0.111); `M5 GBM kuantil (q=0.7, 433 özellik) [net−taban]` blok 2: +2.0% (kısmi Spearman | ATR +0.165); `M5 GBM kuantil (q=0.7, 433 özellik) [net−taban]` blok 3: +1.0% (kısmi Spearman | ATR +0.129).
  İndikatör katkısı (tümü; özellikli model − ATR-yalnız referans, seçim-dışı Δnet): `M4 doğrusal kuantil (q=0.4, 5 özellik) [net]` -0.00 [alt -0.01]; `M5 GBM kuantil (q=0.5, 433 özellik) [net]` -0.02 [alt -0.04]; `M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban]` -0.01 [alt -0.02]; `M5 GBM kuantil (q=0.7, 433 özellik) [net−taban]` +0.01 [alt -0.01].
- **Push bildirimleri / tümü.** Seçim-dışı: sabit (sinyalin) hedef net -0.65, hit 38.8%, ort. hedef 3.19%. En iyi 3 model (ham net): `M3 ampirik (emp60) [net]` net -0.59 (Δ vs sabit +0.06 [-0.23; +0.35]), hit 70.3%, ort. hedef 1.05%; `M3 ampirik (emp60) [net−taban]` net -0.59 (Δ vs sabit +0.06 [-0.23; +0.35]), hit 70.3%, ort. hedef 1.05%; `sabit 1,5` net -0.59 (Δ vs sabit +0.06 [-0.21; +0.33]), hit 59.6%, ort. hedef 1.50%.
  Seçim-dışı mutlak net > 0 olan model: **0**.
- **Push bildirimleri / teyit kuralı (yeni canlı).** Seçim-dışı: sabit (sinyalin) hedef net -0.48, hit 61.5%, ort. hedef 2.29%. En iyi 3 model (ham net): `M3 ampirik (emp60) [net]` net -0.27 (Δ vs sabit +0.22 [-0.17; +0.61]), hit 88.5%, ort. hedef 1.03%; `M3 ampirik (emp60) [net−taban]` net -0.27 (Δ vs sabit +0.22 [-0.17; +0.61]), hit 88.5%, ort. hedef 1.03%; `sabit 1,5` net -0.32 (Δ vs sabit +0.17 [-0.16; +0.49]), hit 78.2%, ort. hedef 1.50%.
  Seçim-dışı mutlak net > 0 olan model: **0**.
  Hedef doğruluğu (pinball, aynı q'lu ATR-yalnız referansa göre iyileşme; seçim-dışı bloklar): `M4 doğrusal kuantil (q=0.4, 5 özellik) [net]` blok 2: +1.2% (kısmi Spearman | ATR +0.124); `M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban]` blok 2: +1.7% (kısmi Spearman | ATR +0.136).
  İndikatör katkısı (tümü; özellikli model − ATR-yalnız referans, seçim-dışı Δnet): `M4 doğrusal kuantil (q=0.4, 5 özellik) [net]` +0.00 [alt -0.13]; `M5 GBM kuantil (q=0.5, 433 özellik) [net]` -0.10 [alt -0.30]; `M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban]` +0.03 [alt -0.04]; `M5 GBM kuantil (q=0.6, 433 özellik) [net−taban]` +0.07 [alt +0.01].
  İndikatör katkısı (teyit kuralı (yeni canlı); özellikli model − ATR-yalnız referans, seçim-dışı Δnet): `M4 doğrusal kuantil (q=0.4, 5 özellik) [net]` -0.29 [alt -0.66]; `M5 GBM kuantil (q=0.5, 433 özellik) [net]` -0.35 [alt -0.82]; `M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban]` +0.15 [alt -0.04]; `M5 GBM kuantil (q=0.6, 433 özellik) [net−taban]` +0.19 [alt -0.26].

### 0c. Ölçüt özeti (kural/model geçişleri)

- **A / ha / tümü:** seçilen 6 kuraldan SEÇİM-DIŞI her blokta net−taban'ı iyileştiren ve birleşik %95 alt sınırı > 0 olan: **1**; her seçim-dışı blokta mutlak net > 0 olan: **0**.
- **A / ha / klasik fikirler:** her blokta tutulan−düşen farkı > 0 ve %95 alt sınırı > 0 olan fikir sayısı: **0** (–).
- **A / notif / tümü:** seçilen 6 kuraldan SEÇİM-DIŞI her blokta net−taban'ı iyileştiren ve birleşik %95 alt sınırı > 0 olan: **0**; her seçim-dışı blokta mutlak net > 0 olan: **0**.
- **A / notif / teyit kuralı (yeni canlı):** seçilen 6 kuraldan SEÇİM-DIŞI her blokta net−taban'ı iyileştiren ve birleşik %95 alt sınırı > 0 olan: **0**; her seçim-dışı blokta mutlak net > 0 olan: **0**.
- **A / notif / klasik fikirler:** her blokta tutulan−düşen farkı > 0 ve %95 alt sınırı > 0 olan fikir sayısı: **0** (–).
- **B / ha / tümü:** sabit hedefe göre (AYNI olaylarda eşleştirilmiş) SEÇİM-DIŞI her blokta ham neti artıran ve birleşik %95 alt sınırı > 0 olan model: **5** (M3 ampirik (emp50) [net], M3 ampirik (emp70) [net−taban], M4 doğrusal kuantil (q=0.4, 5 özellik) [net], sabit 1,5, sabit 2,0); net−taban'ı artıran: **0** (–); seçim-dışı her blokta mutlak net > 0 olan model: **0**. İndikatör katkısı (özellikli model − ATR-yalnız referans, her seçim-dışı blokta Δnet > 0 ve birleşik alt sınır > 0): **0** (–).
- **B / notif / tümü:** sabit hedefe göre (AYNI olaylarda eşleştirilmiş) SEÇİM-DIŞI her blokta ham neti artıran ve birleşik %95 alt sınırı > 0 olan model: **0** (–); net−taban'ı artıran: **0** (–); seçim-dışı her blokta mutlak net > 0 olan model: **0**. İndikatör katkısı (özellikli model − ATR-yalnız referans, her seçim-dışı blokta Δnet > 0 ve birleşik alt sınır > 0): **1** (M5 GBM kuantil (q=0.6, 433 özellik) [net−taban]).
- **B / notif / teyit kuralı (yeni canlı):** sabit hedefe göre (AYNI olaylarda eşleştirilmiş) SEÇİM-DIŞI her blokta ham neti artıran ve birleşik %95 alt sınırı > 0 olan model: **0** (–); net−taban'ı artıran: **0** (–); seçim-dışı her blokta mutlak net > 0 olan model: **0**. İndikatör katkısı (özellikli model − ATR-yalnız referans, her seçim-dışı blokta Δnet > 0 ve birleşik alt sınır > 0): **0** (–).

Doğrulama:
- nedensellik testi (ha): olay 60; karsilastirma 23280; farkli ozellik 0
- nedensellik testi (notif): olay 40; karsilastirma 15520; farkli ozellik 0

## 1. Soru ve yöntem

**Soru:** TradingView göstergeleri kılavuzundaki ~100 klasik + SMC göstergesi, sistemin (a) bildirdiği sinyallerin HASSASİYETİNİ (net sonuç, yalnız hit değil)
ya da (b) HEDEFİN büyüklüğünü iyileştirebilir mi? (Erken uyarı başka bir çalışmada.)

**Nüfuslar.** (1) Hız Avcısı (HA) canlı-benzeri bölümler: `work/rescan_90g_nogate.jsonl`, rank ≤ 10, aşırı alımda değil, aynı sembolde 60 dk içindeki tekrarlar tek bölüm; 90 gün,
üç blok: B1 20 Tem–18 Ağu, B2 19 Ağu–17 Eyl, B3 18 Eyl–16 Eki. (2) Push bildirimleri: `work/confirm_elems/events.pkl` (2007 olay, 17 Eyl–17 Eki) ve bunların YENİ canlı
teyit kuralını geçen alt kümesi (≥ 2 farklı kaynak ∧ Hız kaynaklar arasında ∧ mod ≠ unified). Seçim dönemi 17.09–09.10, değerlendirme 10.10–17.10 (önceki çalışmayla aynı).

**Özellikler (sinyal anından ÖNCE kapanmış son 5 dk ve 15 dk barı).** `app/rescan/indicators_ext.py::compute_all` (134 sütun/zaman dilimi: hareketli ortalama aileleri, OBV/CMF/Klinger/CVD,
osilatörler, SuperTrend kümesi, Ichimoku, Donchian, Keltner/sıkışma, Choppiness, VWAP/çapalı VWAP/POC, SMC: BOS/CHoCH, eşit tepe/dip, likidite süpürmesi, FVG, order block, yer değiştirme, TD),
`pattern_study.features_matrix` (EMA fan, RSI, MFI, ATR, BB, MACD, ADX/DI, Aroon, getiriler, taker...), jsonl/event alanları (`ex:*`), `dyn_target` bileşenleri (`dyn:*`),
direnç mesafeleri (`res:*`: 24 sa / 60 dk zirve, son onaylı salınım tepesi, eşit tepe, POC üstü) ve 25 önceden belirlenmiş klasik fikir (`idea:*`; eşikler literatür varsayılanları, AYARLANMADI).
Boşluklu mumlar `pattern_study.fill_gaps` ile düz mumla doldurulur. Nedensellik: kesilmiş seriyle yeniden hesap testi + sentetik gelecek-bozma birim testi (aşağıda).

**Başarı tanımları.** (A) *hit*: giriş (sinyal + 60 sn) barının açılışına göre 60 dk içinde 1 dk yüksekleri sinyal hedefini görür. (B) *net*: `exit_sim` — 60 sn gecikme, %0,15 kayma, %0,1125/bacak ücret,
TP = sinyal hedefi, SL %3, zaman stopu 60 dk. *Taban:* olay başına 3 rastgele giriş — aynı sembol, aynı blok, herhangi bir sinyalden ≥ 2 sa uzak, 5 dk ATR%'si ±%25 (en az 8 aday; yoksa en yakın 8),
AYNI TP/SL/zaman. *net−taban* = olay neti − o olayın tabanının ortalaması (oynaklık eşleşmiş çift fark).

**Oynaklık kontrolü.** (i) Kısmi Spearman: özellik ve sonucun sıraları, ATR ve hedef/ATR sıralarının 1.+2. derece terimlerine göre arındırılır; t küme-dayanıklı (gün kümeleri). (ii) ATR tersilleri içinde
özelliğin üst yarısı − alt yarısı farkı (tersil ağırlıklı). (iii) Sonuç olarak *net−taban* (taban ATR'ye eşleşmiş). BH q değerleri özellikler arası.

**Filtre kuralları.** Aday = özellik × yön × 3 eşik (1/3, 1/2, 2/3 yüzdelik; yalnız SEÇİM döneminden, sonra dondurulur). Seçim dönemi (HA: B1; bildirim: 17.09–09.10) t-istatistiğine göre iki hedef işleviyle en iyi 3'er FARKLI özellik
(A: net−taban, N: ham net; toplam ≤ 6 kural). Değerlendirme: diğer bloklarda dokunulmadan. Aşırı uyum tanısı: seçimde en iyi 50 adayın seçim-dışı performansı.

**Hedef modelleri.** M0 sinyalin kendi hedefi; M1 ATR ölçekli (k eğitimde); M2 ATR + direnç payı (kaynak/pay/k eğitimde); M3 ampirik (dyn_target (c), q eğitimde); M4 doğrusal kuantil regresyonu
(eğitimde seçilen 5 özellik + log ATR); M5 gradyan artırmalı kuantil (tüm özellikler). Parametreler YALNIZ eğitim bloğunda seçilir (net−taban ölçütüyle; taban aynı hedefle). Test: sonraki bloklar dokunulmadan.

## 3. A — Hassasiyet (filtre) çalışması

### Nüfus 2 — push bildirimleri (17.09–17.10)
Olay 2007, geçerli (pencere + ATR + hedef) 2007; özellik sayısı 439 (klasik-fikir sütunları dahil).

#### Nüfus özeti (mevcut sinyal; taban = oynaklık-eşleşmiş rastgele)

| kapsam | dilim | n | gün/adet | hit | taban hit | net | taban net | net − taban [95] | ort. ATR% |
|---|---|---|---|---|---|---|---|---|---|
| tümü | seçim 17.09–09.10 | 1522 | 66.2 | 41.9% | 21.0% | -0.56 | -0.70 | +0.14 [-0.00; +0.28] | 1.51 |
| tümü | değerlendirme 10.10–17.10 | 485 | 60.6 | 38.8% | 18.6% | -0.65 | -0.82 | +0.18 [-0.15; +0.50] | 1.80 |
| tümü | tümü | 2007 | 64.7 | 41.1% | 20.4% | -0.58 | -0.73 | +0.15 [+0.02; +0.28] | 1.58 |
| teyit kuralı | seçim 17.09–09.10 | 338 | 14.7 | 53.8% | 30.2% | -0.80 | -0.91 | +0.11 [-0.22; +0.44] | 2.59 |
| teyit kuralı | değerlendirme 10.10–17.10 | 78 | 9.8 | 61.5% | 31.6% | -0.48 | -1.09 | +0.60 [+0.34; +0.86] | 2.64 |
| teyit kuralı | tümü | 416 | 13.4 | 55.3% | 30.4% | -0.74 | -0.94 | +0.20 [-0.08; +0.48] | 2.60 |


#### A1. Özellik sıralaması — kapsam: tümü (n=2007)

`r` = kısmi Spearman (ATR ve hedef/ATR sıralarının 1.+2. derece terimleri sabit; ham sütunda kontrol yok); `t` küme-dayanıklı (gün); q = BH (özellikler arası). 'net−taban' = olay neti − eşleşmiş rastgele taban neti.

Anlamlı (BH q) özellik sayısı:

| sonuç | özellik | q<0,05 | q<0,01 |
|---|---|---|---|
| net (ham) | 419 | 0 | 0 |
| net (ATR-kontrollü) | 419 | 0 | 0 |
| net−taban (ham) | 419 | 0 | 0 |
| net−taban (ATR-kontrollü) | 419 | 0 | 0 |
| hit (ham) | 419 | 185 | 155 |
| hit (ATR-kontrollü) | 419 | 73 | 39 |
| hit−taban (ATR-kontrollü) | 419 | 58 | 8 |

Hem hit'te hem net−taban'da (ATR-kontrollü) anlamlı 0 özellikten **0**'inde işaretler TERS (hit'i artıran özellik net'i azaltıyor): hit'e bakarak seçilen filtre net'i bozabilir.

En iyi 15 özellik — ATR-kontrollü net−taban |t| sıralı:

| özellik | kapsam | ham r(net) [t] | ATR-kont. r(net) [t] | ATR-kont. r(net−taban) [t] | q | ATR-kont. r(hit) [t] | q(hit) | AUC net>0 | AUC hit | blok r(net−taban) | işaret uyumu |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 15m.mfi14 | 100% | -0.065 [-3.2] | -0.063 [-2.9] | -0.070 [-3.5] | 0.263 | -0.028 [-1.5] | 0.343 | 0.481 | 0.507 | -0.051 / -0.141 | 2/2 |
| 15m.rvi_vol | 100% | -0.070 [-2.8] | -0.073 [-2.9] | -0.081 [-3.4] | 0.263 | -0.027 [-1.0] | 0.569 | 0.476 | 0.501 | -0.076 / -0.114 | 2/2 |
| 15m.obv_slope48 | 100% | -0.087 [-3.0] | -0.083 [-2.8] | -0.085 [-3.4] | 0.263 | -0.046 [-1.5] | 0.329 | 0.480 | 0.510 | -0.072 / -0.128 | 2/2 |
| 5m.ob_age | 100% | -0.077 [-3.6] | -0.076 [-3.4] | -0.073 [-3.2] | 0.263 | -0.093 [-4.4] | 0.003 | 0.452 | 0.466 | -0.063 / -0.099 | 2/2 |
| 15m.kvo | 100% | -0.072 [-3.1] | -0.067 [-2.9] | -0.070 [-3.2] | 0.263 | -0.044 [-2.3] | 0.112 | 0.482 | 0.501 | -0.057 / -0.118 | 2/2 |
| 15m.green_run | 100% | -0.051 [-2.7] | -0.054 [-2.9] | -0.054 [-2.9] | 0.495 | +0.013 [+0.5] | 0.777 | 0.484 | 0.495 | -0.037 / -0.112 | 2/2 |
| 15m.obv_slope12 | 100% | -0.064 [-2.7] | -0.064 [-2.6] | -0.070 [-2.8] | 0.547 | -0.011 [-0.4] | 0.820 | 0.476 | 0.503 | -0.044 / -0.133 | 2/2 |
| 5m.obv_slope48 | 100% | -0.062 [-2.6] | -0.063 [-2.6] | -0.061 [-2.6] | 0.676 | -0.008 [-0.3] | 0.874 | 0.491 | 0.504 | -0.054 / -0.085 | 2/2 |
| res:eqh_15m | 100% | +0.050 [+2.0] | +0.049 [+2.0] | +0.058 [+2.6] | 0.676 | +0.019 [+0.8] | 0.658 | 0.505 | 0.502 | +0.077 / +0.021 | 2/2 |
| 15m.vi_minus | 100% | +0.041 [+1.9] | +0.044 [+1.9] | +0.052 [+2.5] | 0.676 | +0.021 [+0.8] | 0.621 | 0.515 | 0.505 | +0.035 / +0.108 | 2/2 |
| idea:chop_trending_15m | 100% | -0.040 [-2.1] | -0.040 [-1.9] | -0.051 [-2.5] | 0.676 | -0.044 [-2.2] | 0.128 | 0.491 | 0.494 | -0.038 / -0.094 | 2/2 |
| 5m.td_sell9 | 100% | -0.039 [-2.3] | -0.040 [-2.4] | -0.043 [-2.4] | 0.676 | -0.025 [-1.5] | 0.333 | 0.493 | 0.492 | -0.047 / -0.026 | 2/2 |
| 5m.mass_index | 100% | -0.051 [-2.4] | -0.045 [-2.1] | -0.048 [-2.4] | 0.676 | -0.024 [-1.0] | 0.536 | 0.501 | 0.552 | -0.048 / -0.063 | 2/2 |
| 15m.vol_osc | 100% | -0.046 [-2.1] | -0.040 [-1.8] | -0.049 [-2.4] | 0.676 | -0.023 [-0.9] | 0.573 | 0.492 | 0.530 | -0.037 / -0.100 | 2/2 |
| 5m.green_share12 | 100% | +0.040 [+1.9] | +0.043 [+2.0] | +0.050 [+2.3] | 0.738 | +0.060 [+2.5] | 0.087 | 0.534 | 0.548 | +0.054 / +0.026 | 2/2 |

En iyi 15 özellik — HAM net |t| sıralı (ATR'nin etkisi dahil):

| özellik | kapsam | ham r(net) [t] | ATR-kont. r(net) [t] | ATR-kont. r(net−taban) [t] | q | ATR-kont. r(hit) [t] | q(hit) | AUC net>0 | AUC hit | blok r(net−taban) | işaret uyumu |
|---|---|---|---|---|---|---|---|---|---|---|---|
| res:swing_5m | 100% | +0.044 [+3.7] | +0.037 [+3.0] | +0.018 [+1.2] | 0.953 | +0.086 [+5.3] | 0.001 | 0.523 | 0.518 | +0.015 / +0.029 | 2/2 |
| 5m.ob_age | 100% | -0.077 [-3.6] | -0.076 [-3.4] | -0.073 [-3.2] | 0.263 | -0.093 [-4.4] | 0.003 | 0.452 | 0.466 | -0.063 / -0.099 | 2/2 |
| 15m.mfi14 | 100% | -0.065 [-3.2] | -0.063 [-2.9] | -0.070 [-3.5] | 0.263 | -0.028 [-1.5] | 0.343 | 0.481 | 0.507 | -0.051 / -0.141 | 2/2 |
| 15m.kvo | 100% | -0.072 [-3.1] | -0.067 [-2.9] | -0.070 [-3.2] | 0.263 | -0.044 [-2.3] | 0.112 | 0.482 | 0.501 | -0.057 / -0.118 | 2/2 |
| 5m.ob_dist | 100% | -0.049 [-3.0] | -0.034 [-1.7] | -0.039 [-1.6] | 0.953 | +0.005 [+0.2] | 0.933 | 0.518 | 0.603 | -0.017 / -0.088 | 2/2 |
| 15m.obv_slope48 | 100% | -0.087 [-3.0] | -0.083 [-2.8] | -0.085 [-3.4] | 0.263 | -0.046 [-1.5] | 0.329 | 0.480 | 0.510 | -0.072 / -0.128 | 2/2 |
| 15m.rvi_vol | 100% | -0.070 [-2.8] | -0.073 [-2.9] | -0.081 [-3.4] | 0.263 | -0.027 [-1.0] | 0.569 | 0.476 | 0.501 | -0.076 / -0.114 | 2/2 |
| 15m.mass_index | 100% | -0.056 [-2.7] | -0.046 [-2.3] | -0.027 [-1.4] | 0.953 | -0.066 [-3.0] | 0.037 | 0.499 | 0.526 | -0.033 / -0.018 | 2/2 |
| 15m.green_run | 100% | -0.051 [-2.7] | -0.054 [-2.9] | -0.054 [-2.9] | 0.495 | +0.013 [+0.5] | 0.777 | 0.484 | 0.495 | -0.037 / -0.112 | 2/2 |
| 15m.obv_slope12 | 100% | -0.064 [-2.7] | -0.064 [-2.6] | -0.070 [-2.8] | 0.547 | -0.011 [-0.4] | 0.820 | 0.476 | 0.503 | -0.044 / -0.133 | 2/2 |
| 15m.pvt_slope12 | 100% | -0.046 [-2.7] | -0.031 [-1.6] | -0.025 [-1.5] | 0.953 | +0.016 [+0.7] | 0.723 | 0.532 | 0.616 | -0.010 / -0.062 | 2/2 |
| 5m.obv_slope48 | 100% | -0.062 [-2.6] | -0.063 [-2.6] | -0.061 [-2.6] | 0.676 | -0.008 [-0.3] | 0.874 | 0.491 | 0.504 | -0.054 / -0.085 | 2/2 |
| 15m.atr_ratio | 100% | -0.065 [-2.5] | -0.055 [-2.1] | -0.052 [-2.2] | 0.747 | -0.059 [-2.2] | 0.122 | 0.504 | 0.561 | -0.044 / -0.093 | 2/2 |
| 5m.cmf20_chg5 | 100% | +0.046 [+2.5] | +0.042 [+2.2] | +0.036 [+1.9] | 0.835 | +0.087 [+4.6] | 0.002 | 0.528 | 0.518 | +0.043 / +0.020 | 2/2 |
| 5m.mass_index | 100% | -0.051 [-2.4] | -0.045 [-2.1] | -0.048 [-2.4] | 0.676 | -0.024 [-1.0] | 0.536 | 0.501 | 0.552 | -0.048 / -0.063 | 2/2 |

En iyi 15 özellik — ATR-kontrollü HIT |t| sıralı:

| özellik | kapsam | ham r(net) [t] | ATR-kont. r(net) [t] | ATR-kont. r(net−taban) [t] | q | ATR-kont. r(hit) [t] | q(hit) | AUC net>0 | AUC hit | blok r(net−taban) | işaret uyumu |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ex:pump30 | 100% | -0.004 [-0.2] | +0.016 [+0.9] | -0.005 [-0.3] | 0.967 | +0.130 [+5.7] | 0.001 | 0.562 | 0.654 | -0.010 / +0.011 | 1/2 |
| 5m.bb_pctb | 100% | +0.022 [+1.2] | +0.016 [+0.8] | +0.013 [+0.7] | 0.957 | +0.110 [+5.6] | 0.001 | 0.517 | 0.520 | +0.008 / +0.035 | 2/2 |
| res:swing_5m | 100% | +0.044 [+3.7] | +0.037 [+3.0] | +0.018 [+1.2] | 0.953 | +0.086 [+5.3] | 0.001 | 0.523 | 0.518 | +0.015 / +0.029 | 2/2 |
| 5m.vi_minus | 100% | -0.031 [-2.1] | -0.022 [-1.4] | -0.023 [-1.3] | 0.953 | -0.098 [-5.3] | 0.001 | 0.475 | 0.487 | -0.030 / -0.004 | 2/2 |
| 5m.px_dema | 100% | +0.011 [+0.6] | +0.029 [+1.5] | +0.017 [+0.8] | 0.957 | +0.121 [+5.1] | 0.001 | 0.556 | 0.630 | +0.007 / +0.046 | 2/2 |
| idea:chop_trending | 100% | +0.026 [+1.8] | +0.019 [+1.3] | +0.020 [+1.1] | 0.953 | +0.084 [+5.0] | 0.001 | 0.509 | 0.508 | +0.027 / +0.002 | 2/2 |
| 5m.cci20 | 100% | +0.015 [+0.8] | +0.009 [+0.4] | +0.008 [+0.4] | 0.967 | +0.101 [+5.0] | 0.001 | 0.516 | 0.524 | +0.003 / +0.023 | 2/2 |
| 5m.px_kama | 100% | -0.001 [-0.1] | +0.023 [+1.0] | +0.014 [+0.7] | 0.957 | +0.104 [+5.0] | 0.001 | 0.555 | 0.639 | +0.016 / +0.015 | 2/2 |
| idea:no_swing_high_in_target | 100% | +0.045 [+2.3] | +0.043 [+2.2] | +0.028 [+1.7] | 0.938 | +0.090 [+4.9] | 0.001 | 0.525 | 0.536 | +0.025 / +0.041 | 2/2 |
| 5m.px_ema7 | 100% | -0.009 [-0.5] | +0.014 [+0.7] | +0.007 [+0.4] | 0.967 | +0.112 [+4.9] | 0.001 | 0.555 | 0.643 | -0.000 / +0.032 | 1/2 |
| 5m.pvt_slope12 | 100% | +0.010 [+0.5] | +0.030 [+1.3] | +0.021 [+0.9] | 0.957 | +0.117 [+4.8] | 0.001 | 0.562 | 0.640 | +0.029 / +0.006 | 2/2 |
| 5m.disp_up_cnt5 | 100% | +0.045 [+2.1] | +0.044 [+2.0] | +0.041 [+1.7] | 0.936 | +0.106 [+4.7] | 0.002 | 0.530 | 0.539 | +0.041 / +0.042 | 2/2 |
| 5m.cmo14 | 100% | +0.004 [+0.2] | -0.001 [-0.1] | -0.004 [-0.2] | 0.970 | +0.082 [+4.6] | 0.002 | 0.520 | 0.531 | -0.000 / -0.011 | 2/2 |
| 5m.cmf20_chg5 | 100% | +0.046 [+2.5] | +0.042 [+2.2] | +0.036 [+1.9] | 0.835 | +0.087 [+4.6] | 0.002 | 0.528 | 0.518 | +0.043 / +0.020 | 2/2 |
| 5m.px_tema | 100% | +0.000 [+0.0] | +0.013 [+0.5] | +0.009 [+0.4] | 0.967 | +0.099 [+4.4] | 0.003 | 0.535 | 0.592 | -0.006 / +0.049 | 1/2 |


Aile bazında özet (ATR-kontrollü):

| aile | özellik | q<0,05 (net−taban, ATR-kont.) | …ve tüm bloklarda aynı işaret | q<0,05 (hit−taban) | medyan |r| | en güçlü özellik |
|---|---|---|---|---|---|---|
| mevcut özellik (pattern_study: EMA/RSI/MFI/ATR/BB/MACD/ADX/taker...) | 105 | 0 | 0 | 15 | 0.015 | 15m.mfi14 (r -0.070, t -3.5) |
| trend/kanal (SuperTrend, PSAR, Ichimoku, Donchian, Keltner, sıkışma, Choppiness) | 68 | 0 | 0 | 8 | 0.017 | 15m.vi_minus (r +0.052, t +2.5) |
| osilatörler (Stoch, TSI, KST, Fisher, CCI, ...) | 56 | 0 | 0 | 8 | 0.013 | 15m.crsi (r -0.042, t -2.2) |
| SMC (BOS/CHoCH, eşit tepe/dip, süpürme, FVG, OB, TD) | 48 | 0 | 0 | 5 | 0.021 | 5m.ob_age (r -0.073, t -3.2) |
| hareketli ortalamalar (ALMA/HMA/DEMA/KAMA/McGinley/LSMA) | 34 | 0 | 0 | 9 | 0.010 | 15m.slope_kama (r -0.027, t -1.2) |
| hacim/akış (OBV, A/D, CMF, Klinger, CVD, OFI) | 30 | 0 | 0 | 6 | 0.019 | 15m.obv_slope48 (r -0.085, t -3.4) |
| klasik fikir (0/1) | 29 | 0 | 0 | 2 | 0.013 | idea:chop_trending_15m (r -0.051, t -2.5) |
| mevcut sistem alanları (jsonl/olay) | 19 | 0 | 0 | 3 | 0.009 | ex:score (r +0.028, t +1.2) |
| oynaklık (ATR oranı, HV, RVI) | 8 | 0 | 0 | 1 | 0.027 | 15m.rvi_vol (r -0.081, t -3.4) |
| konum (VWAP, çapalı VWAP, POC) | 8 | 0 | 0 | 0 | 0.013 | 5m.avwap_age (r -0.019, t -0.8) |
| direnç mesafesi | 8 | 0 | 0 | 1 | 0.025 | res:eqh_15m (r +0.058, t +2.6) |
| dyn_target bileşenleri | 6 | 0 | 0 | 0 | 0.021 | dyn:room (r +0.031, t +1.2) |


ATR tersilleri içinde en iyi 8 özellik (ATR-kontrollü net−taban sıralı):

| özellik (üst yarı − alt yarı) | Δhit pp (ATR-tersil içi) | tersil 1/2/3 Δhit pp | Δnet | Δ(net−taban) | tersil 1/2/3 Δ(net−taban) |
|---|---|---|---|---|---|
| 15m.mfi14 | -0.8 [t -0.4] | -0.8 / +1.6 / -3.1 | -0.23 [t -2.1] | -0.37 [t -3.2] | -0.20 / -0.46 / -0.45 |
| 15m.rvi_vol | +1.2 [t +0.5] | +2.2 / +4.0 / -2.5 | -0.25 [t -2.0] | -0.35 [t -2.7] | +0.03 / -0.36 / -0.71 |
| 15m.obv_slope48 | -3.4 [t -1.5] | -4.4 / -2.0 / -3.7 | -0.37 [t -2.5] | -0.42 [t -3.1] | -0.24 / -0.48 / -0.55 |
| 5m.ob_age | -8.7 [t -3.5] | -3.8 / -8.8 / -13.5 | -0.40 [t -3.4] | -0.40 [t -2.8] | -0.27 / -0.32 / -0.60 |
| 15m.kvo | -2.2 [t -0.9] | +1.0 / +0.4 / -7.9 | -0.22 [t -1.7] | -0.23 [t -1.8] | +0.04 / -0.29 / -0.43 |
| 15m.green_run | +2.1 [t +1.2] | +8.3 / -0.6 / -1.3 | -0.20 [t -1.7] | -0.21 [t -2.0] | +0.30 / -0.28 / -0.67 |
| 15m.obv_slope12 | -1.4 [t -0.7] | -4.4 / +2.8 / -2.5 | -0.30 [t -2.5] | -0.37 [t -2.7] | -0.23 / -0.16 / -0.72 |
| 5m.obv_slope48 | -0.6 [t -0.2] | -2.0 / +10.0 / -9.7 | -0.19 [t -1.7] | -0.27 [t -2.1] | -0.09 / +0.23 / -0.95 |


En güçlü 3 özelliğin kuintil profili (kapsam: tümü; mutlak net bir kuintilde > 0 oluyor mu?):

| özellik | kuintil | alt sınır | n | hit | net | net−taban | blok net (seçim / değerlendirme) |
|---|---|---|---|---|---|---|---|
| 15m.mfi14 | K1 | 3.32 | 402 | 40.5% | -0.38 | +0.23 | -0.53 / -0.10 |
| 15m.mfi14 | K2 | 59.4 | 401 | 42.1% | -0.44 | +0.45 | -0.29 / -0.99 |
| 15m.mfi14 | K3 | 70.1 | 401 | 37.7% | -0.73 | +0.09 | -0.71 / -0.80 |
| 15m.mfi14 | K4 | 79 | 401 | 42.1% | -0.45 | +0.21 | -0.45 / -0.48 |
| 15m.mfi14 | K5 | 88.7 | 402 | 43.0% | -0.88 | -0.24 | -0.81 / -1.17 |
| 15m.rvi_vol | K1 | 14.2 | 402 | 46.0% | -0.40 | +0.41 | -0.42 / -0.38 |
| 15m.rvi_vol | K2 | 51.8 | 401 | 36.7% | -0.42 | +0.38 | -0.27 / -0.85 |
| 15m.rvi_vol | K3 | 58.9 | 401 | 38.9% | -0.57 | +0.12 | -0.56 / -0.63 |
| 15m.rvi_vol | K4 | 65.2 | 400 | 42.0% | -0.51 | +0.13 | -0.49 / -0.61 |
| 15m.rvi_vol | K5 | 72.2 | 403 | 41.9% | -0.99 | -0.29 | -0.98 / -1.03 |
| 15m.obv_slope48 | K1 | -0.8 | 402 | 38.1% | -0.50 | +0.24 | -0.52 / -0.48 |
| 15m.obv_slope48 | K2 | 0.0545 | 401 | 43.6% | -0.34 | +0.45 | -0.29 / -0.51 |
| 15m.obv_slope48 | K3 | 0.195 | 401 | 40.4% | -0.52 | +0.14 | -0.55 / -0.41 |
| 15m.obv_slope48 | K4 | 0.305 | 401 | 40.9% | -0.51 | +0.23 | -0.46 / -0.78 |
| 15m.obv_slope48 | K5 | 0.439 | 402 | 42.5% | -1.03 | -0.32 | -0.96 / -1.36 |


#### A1. Özellik sıralaması — kapsam: teyit kuralı (yeni canlı) (n=416)

`r` = kısmi Spearman (ATR ve hedef/ATR sıralarının 1.+2. derece terimleri sabit; ham sütunda kontrol yok); `t` küme-dayanıklı (gün); q = BH (özellikler arası). 'net−taban' = olay neti − eşleşmiş rastgele taban neti.

Anlamlı (BH q) özellik sayısı:

| sonuç | özellik | q<0,05 | q<0,01 |
|---|---|---|---|
| net (ham) | 398 | 0 | 0 |
| net (ATR-kontrollü) | 398 | 0 | 0 |
| net−taban (ham) | 398 | 0 | 0 |
| net−taban (ATR-kontrollü) | 398 | 0 | 0 |
| hit (ham) | 398 | 20 | 9 |
| hit (ATR-kontrollü) | 398 | 0 | 0 |
| hit−taban (ATR-kontrollü) | 398 | 0 | 0 |

Hem hit'te hem net−taban'da (ATR-kontrollü) anlamlı 0 özellikten **0**'inde işaretler TERS (hit'i artıran özellik net'i azaltıyor): hit'e bakarak seçilen filtre net'i bozabilir.

En iyi 15 özellik — ATR-kontrollü net−taban |t| sıralı:

| özellik | kapsam | ham r(net) [t] | ATR-kont. r(net) [t] | ATR-kont. r(net−taban) [t] | q | ATR-kont. r(hit) [t] | q(hit) | AUC net>0 | AUC hit | blok r(net−taban) | işaret uyumu |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 5m.willr14 | 100% | -0.093 [-2.0] | -0.101 [-2.3] | -0.125 [-2.8] | 0.989 | -0.039 [-0.9] | 0.827 | 0.460 | 0.466 | -0.165 / +0.126 | 1/2 |
| 15m.cvd_slope48 | 100% | -0.017 [-0.4] | -0.014 [-0.4] | -0.073 [-2.6] | 0.989 | +0.022 [+0.4] | 0.934 | 0.509 | 0.532 | -0.076 / -0.108 | 2/2 |
| 5m.donch_pos20 | 100% | -0.075 [-1.6] | -0.083 [-1.8] | -0.108 [-2.4] | 0.989 | -0.046 [-1.0] | 0.805 | 0.470 | 0.465 | -0.150 / +0.153 | 1/2 |
| 15m.tk_net12 | 100% | -0.058 [-1.3] | -0.056 [-1.3] | -0.078 [-2.1] | 0.989 | -0.019 [-0.3] | 0.941 | 0.480 | 0.505 | -0.100 / -0.034 | 2/2 |
| idea:chop_trending_15m | 100% | -0.094 [-2.4] | -0.085 [-2.0] | -0.097 [-2.1] | 0.989 | -0.097 [-1.9] | 0.496 | 0.454 | 0.462 | -0.071 / -0.280 | 2/2 |
| dyn:peak60dist | 100% | +0.072 [+1.4] | +0.087 [+1.7] | +0.097 [+2.1] | 0.989 | +0.040 [+0.7] | 0.867 | 0.555 | 0.561 | +0.120 / -0.173 | 1/2 |
| 15m.ms_eql | 100% | -0.055 [-1.2] | -0.068 [-1.6] | -0.073 [-2.1] | 0.989 | -0.021 [-0.4] | 0.914 | 0.477 | 0.491 | -0.062 / -0.180 | 2/2 |
| idea:above_avwap_15m | 100% | +0.118 [+2.5] | +0.112 [+2.3] | +0.099 [+2.0] | 0.989 | +0.151 [+2.8] | 0.306 | 0.545 | 0.551 | +0.094 / +0.129 | 2/2 |
| 15m.trix_sig_diff | 100% | -0.087 [-2.3] | -0.091 [-2.4] | -0.079 [-2.0] | 0.989 | -0.107 [-1.9] | 0.496 | 0.448 | 0.480 | -0.072 / -0.035 | 2/2 |
| 15m.tk_net6 | 100% | -0.064 [-1.4] | -0.056 [-1.2] | -0.067 [-2.0] | 0.989 | -0.030 [-0.5] | 0.907 | 0.486 | 0.495 | -0.094 / -0.015 | 2/2 |
| idea:above_vwap_15m | 100% | +0.118 [+3.4] | +0.113 [+3.3] | +0.084 [+2.0] | 0.989 | +0.104 [+2.3] | 0.409 | 0.547 | 0.534 | +0.080 / +0.129 | 2/2 |
| ex:tp | 100% | +0.124 [+2.8] | +0.127 [+2.1] | +0.098 [+1.9] | 0.989 | +0.018 [+0.4] | 0.934 | 0.464 | 0.480 | +0.098 / +0.055 | 2/2 |
| ex:score | 100% | +0.084 [+1.4] | +0.102 [+1.8] | +0.106 [+1.8] | 0.989 | +0.185 [+3.2] | 0.304 | 0.589 | 0.627 | +0.073 / +0.204 | 2/2 |
| 15m.squeeze_release | 100% | +0.043 [+0.8] | +0.051 [+0.9] | +0.113 [+1.8] | 0.989 | +0.074 [+1.5] | 0.618 | 0.527 | 0.529 | +0.146 / -0.053 | 1/2 |
| idea:cvd_up | 100% | -0.082 [-1.9] | -0.077 [-1.8] | -0.071 [-1.8] | 0.989 | +0.004 [+0.1] | 0.974 | 0.487 | 0.507 | -0.106 / +0.041 | 1/2 |

En iyi 15 özellik — HAM net |t| sıralı (ATR'nin etkisi dahil):

| özellik | kapsam | ham r(net) [t] | ATR-kont. r(net) [t] | ATR-kont. r(net−taban) [t] | q | ATR-kont. r(hit) [t] | q(hit) | AUC net>0 | AUC hit | blok r(net−taban) | işaret uyumu |
|---|---|---|---|---|---|---|---|---|---|---|---|
| idea:above_vwap_15m | 100% | +0.118 [+3.4] | +0.113 [+3.3] | +0.084 [+2.0] | 0.989 | +0.104 [+2.3] | 0.409 | 0.547 | 0.534 | +0.080 / +0.129 | 2/2 |
| ex:tp | 100% | +0.124 [+2.8] | +0.127 [+2.1] | +0.098 [+1.9] | 0.989 | +0.018 [+0.4] | 0.934 | 0.464 | 0.480 | +0.098 / +0.055 | 2/2 |
| idea:no_swing_high_in_target | 100% | +0.117 [+2.8] | +0.120 [+2.9] | +0.056 [+1.5] | 0.989 | +0.143 [+3.1] | 0.304 | 0.553 | 0.551 | +0.029 / +0.121 | 2/2 |
| 15m.vi_plus | 100% | -0.082 [-2.7] | -0.080 [-2.4] | -0.054 [-1.2] | 0.989 | -0.068 [-1.1] | 0.773 | 0.459 | 0.490 | -0.030 / -0.089 | 2/2 |
| 15m.ichi_cloud_thick | 100% | +0.093 [+2.5] | +0.080 [+2.1] | +0.049 [+1.1] | 0.989 | +0.104 [+2.1] | 0.421 | 0.554 | 0.574 | +0.051 / -0.023 | 1/2 |
| idea:above_avwap_15m | 100% | +0.118 [+2.5] | +0.112 [+2.3] | +0.099 [+2.0] | 0.989 | +0.151 [+2.8] | 0.306 | 0.545 | 0.551 | +0.094 / +0.129 | 2/2 |
| res:swing_5m | 100% | +0.095 [+2.4] | +0.094 [+2.5] | +0.048 [+0.9] | 0.989 | +0.126 [+3.6] | 0.304 | 0.561 | 0.543 | +0.014 / +0.154 | 2/2 |
| idea:chop_trending_15m | 100% | -0.094 [-2.4] | -0.085 [-2.0] | -0.097 [-2.1] | 0.989 | -0.097 [-1.9] | 0.496 | 0.454 | 0.462 | -0.071 / -0.280 | 2/2 |
| 15m.vi_diff | 100% | -0.083 [-2.4] | -0.075 [-2.1] | -0.041 [-0.9] | 0.989 | -0.055 [-1.0] | 0.801 | 0.466 | 0.488 | -0.024 / -0.104 | 2/2 |
| 15m.kst_sig_diff | 100% | -0.086 [-2.3] | -0.090 [-2.3] | -0.071 [-1.8] | 0.989 | -0.107 [-1.8] | 0.560 | 0.451 | 0.482 | -0.060 / -0.043 | 2/2 |
| 15m.trix_sig_diff | 100% | -0.087 [-2.3] | -0.091 [-2.4] | -0.079 [-2.0] | 0.989 | -0.107 [-1.9] | 0.496 | 0.448 | 0.480 | -0.072 / -0.035 | 2/2 |
| 5m.obv_slope48 | 100% | -0.128 [-2.2] | -0.122 [-2.2] | -0.089 [-1.6] | 0.989 | -0.041 [-0.7] | 0.862 | 0.455 | 0.484 | -0.091 / -0.109 | 2/2 |
| 5m.rvi_vol | 100% | -0.112 [-2.2] | -0.119 [-2.4] | -0.072 [-1.3] | 0.989 | -0.046 [-1.0] | 0.782 | 0.463 | 0.478 | -0.097 / +0.005 | 1/2 |
| 5m.tk_share1 | 100% | -0.107 [-2.2] | -0.120 [-2.5] | -0.061 [-1.4] | 0.989 | -0.096 [-2.0] | 0.465 | 0.448 | 0.446 | -0.062 / -0.047 | 2/2 |
| 5m.psar_state | 100% | -0.096 [-2.2] | -0.090 [-2.0] | -0.035 [-0.7] | 0.989 | +0.045 [+0.9] | 0.812 | 0.483 | 0.500 | -0.062 / +0.127 | 1/2 |

En iyi 15 özellik — ATR-kontrollü HIT |t| sıralı:

| özellik | kapsam | ham r(net) [t] | ATR-kont. r(net) [t] | ATR-kont. r(net−taban) [t] | q | ATR-kont. r(hit) [t] | q(hit) | AUC net>0 | AUC hit | blok r(net−taban) | işaret uyumu |
|---|---|---|---|---|---|---|---|---|---|---|---|
| res:swing_5m | 100% | +0.095 [+2.4] | +0.094 [+2.5] | +0.048 [+0.9] | 0.989 | +0.126 [+3.6] | 0.304 | 0.561 | 0.543 | +0.014 / +0.154 | 2/2 |
| ex:pump30 | 100% | +0.014 [+0.3] | +0.008 [+0.2] | -0.016 [-0.4] | 0.989 | +0.161 [+3.2] | 0.304 | 0.534 | 0.611 | -0.059 / +0.202 | 1/2 |
| ex:score | 100% | +0.084 [+1.4] | +0.102 [+1.8] | +0.106 [+1.8] | 0.989 | +0.185 [+3.2] | 0.304 | 0.589 | 0.627 | +0.073 / +0.204 | 2/2 |
| idea:no_swing_high_in_target | 100% | +0.117 [+2.8] | +0.120 [+2.9] | +0.056 [+1.5] | 0.989 | +0.143 [+3.1] | 0.304 | 0.553 | 0.551 | +0.029 / +0.121 | 2/2 |
| 5m.rvi_sig_diff | 100% | +0.047 [+1.2] | +0.043 [+1.0] | +0.046 [+0.9] | 0.989 | +0.140 [+3.1] | 0.304 | 0.531 | 0.538 | +0.011 / +0.247 | 2/2 |
| 5m.dist_low24_pct | 100% | +0.064 [+1.5] | +0.072 [+1.5] | +0.064 [+1.5] | 0.989 | +0.173 [+3.1] | 0.304 | 0.565 | 0.651 | +0.066 / +0.035 | 2/2 |
| 15m.ema50_99 | 100% | +0.080 [+2.0] | +0.080 [+1.8] | +0.062 [+1.3] | 0.989 | +0.136 [+3.0] | 0.304 | 0.564 | 0.626 | +0.064 / +0.042 | 2/2 |
| 5m.smi_sig_diff | 100% | +0.037 [+1.1] | +0.032 [+0.8] | +0.027 [+0.5] | 0.989 | +0.158 [+3.0] | 0.304 | 0.537 | 0.537 | -0.018 / +0.235 | 1/2 |
| idea:above_avwap_15m | 100% | +0.118 [+2.5] | +0.112 [+2.3] | +0.099 [+2.0] | 0.989 | +0.151 [+2.8] | 0.306 | 0.545 | 0.551 | +0.094 / +0.129 | 2/2 |
| 15m.dist_low24_pct | 100% | +0.077 [+1.9] | +0.089 [+1.9] | +0.069 [+1.7] | 0.989 | +0.163 [+2.8] | 0.306 | 0.571 | 0.647 | +0.083 / -0.018 | 1/2 |
| 5m.ao_chg | 100% | +0.034 [+0.8] | +0.032 [+0.7] | +0.017 [+0.4] | 0.989 | +0.146 [+2.8] | 0.306 | 0.553 | 0.584 | -0.018 / +0.169 | 1/2 |
| 5m.ms_trend | 100% | +0.077 [+2.0] | +0.083 [+2.1] | +0.073 [+1.7] | 0.989 | +0.119 [+2.8] | 0.306 | 0.537 | 0.535 | +0.046 / +0.118 | 2/2 |
| idea:ms_bullish | 100% | +0.077 [+2.0] | +0.083 [+2.1] | +0.073 [+1.7] | 0.989 | +0.119 [+2.8] | 0.306 | 0.537 | 0.535 | +0.046 / +0.118 | 2/2 |
| 5m.lsma_px | 100% | +0.001 [+0.0] | -0.017 [-0.4] | -0.017 [-0.4] | 0.989 | +0.134 [+2.7] | 0.308 | 0.518 | 0.572 | -0.068 / +0.244 | 1/2 |
| 5m.chop_drop12 | 100% | -0.058 [-1.2] | -0.060 [-1.1] | -0.043 [-0.7] | 0.989 | -0.156 [-2.7] | 0.308 | 0.459 | 0.457 | +0.004 / -0.259 | 1/2 |


Aile bazında özet (ATR-kontrollü):

| aile | özellik | q<0,05 (net−taban, ATR-kont.) | …ve tüm bloklarda aynı işaret | q<0,05 (hit−taban) | medyan |r| | en güçlü özellik |
|---|---|---|---|---|---|---|
| mevcut özellik (pattern_study: EMA/RSI/MFI/ATR/BB/MACD/ADX/taker...) | 105 | 0 | 0 | 0 | 0.024 | 15m.tk_net12 (r -0.078, t -2.1) |
| trend/kanal (SuperTrend, PSAR, Ichimoku, Donchian, Keltner, sıkışma, Choppiness) | 63 | 0 | 0 | 0 | 0.025 | 5m.donch_pos20 (r -0.108, t -2.4) |
| osilatörler (Stoch, TSI, KST, Fisher, CCI, ...) | 56 | 0 | 0 | 0 | 0.027 | 5m.willr14 (r -0.125, t -2.8) |
| SMC (BOS/CHoCH, eşit tepe/dip, süpürme, FVG, OB, TD) | 39 | 0 | 0 | 0 | 0.035 | 15m.ms_eql (r -0.073, t -2.1) |
| hareketli ortalamalar (ALMA/HMA/DEMA/KAMA/McGinley/LSMA) | 34 | 0 | 0 | 0 | 0.014 | 15m.px_kama (r +0.045, t +1.2) |
| hacim/akış (OBV, A/D, CMF, Klinger, CVD, OFI) | 30 | 0 | 0 | 0 | 0.036 | 15m.cvd_slope48 (r -0.073, t -2.6) |
| klasik fikir (0/1) | 27 | 0 | 0 | 0 | 0.044 | idea:chop_trending_15m (r -0.097, t -2.1) |
| mevcut sistem alanları (jsonl/olay) | 15 | 0 | 0 | 0 | 0.034 | ex:tp (r +0.098, t +1.9) |
| oynaklık (ATR oranı, HV, RVI) | 8 | 0 | 0 | 0 | 0.043 | 5m.rvi_vol (r -0.072, t -1.3) |
| konum (VWAP, çapalı VWAP, POC) | 8 | 0 | 0 | 0 | 0.025 | 15m.avwap_age (r -0.042, t -0.9) |
| direnç mesafesi | 7 | 0 | 0 | 0 | 0.025 | res:poc_5m (r +0.048, t +0.9) |
| dyn_target bileşenleri | 6 | 0 | 0 | 0 | 0.013 | dyn:peak60dist (r +0.097, t +2.1) |


ATR tersilleri içinde en iyi 8 özellik (ATR-kontrollü net−taban sıralı):

| özellik (üst yarı − alt yarı) | Δhit pp (ATR-tersil içi) | tersil 1/2/3 Δhit pp | Δnet | Δ(net−taban) | tersil 1/2/3 Δ(net−taban) |
|---|---|---|---|---|---|
| 5m.willr14 | -5.3 [t -1.1] | -6.6 / -5.8 / -3.4 | -0.40 [t -1.3] | -0.74 [t -2.5] | -0.87 / -1.24 / -0.11 |
| 15m.cvd_slope48 | +4.9 [t +0.8] | +2.0 / +5.8 / +7.0 | -0.13 [t -0.5] | -0.55 [t -2.2] | +0.12 / -0.36 / -1.42 |
| 5m.donch_pos20 | -8.2 [t -1.6] | -6.6 / -8.7 / -9.2 | -0.31 [t -0.9] | -0.56 [t -1.6] | -0.86 / -0.84 / +0.00 |
| 15m.tk_net12 | -3.4 [t -0.6] | -3.7 / -2.9 / -3.4 | -0.39 [t -1.2] | -0.55 [t -1.6] | -0.05 / -0.53 / -1.08 |
| idea:chop_trending_15m | -3.3 [t -0.6] | +6.1 / -12.8 / +nan | -0.36 [t -1.0] | -0.28 [t -0.6] | -0.36 / -0.20 / +nan |
| dyn:peak60dist | -0.5 [t -0.1] | -3.7 / +0.0 / +2.3 | +0.10 [t +0.3] | +0.28 [t +1.0] | +0.17 / +0.92 / -0.23 |
| 15m.ms_eql | -2.4 [t -0.3] | -3.4 / -26.7 / +22.7 | -0.72 [t -1.6] | -0.82 [t -2.3] | -1.05 / -1.99 / +0.59 |
| idea:above_avwap_15m | +nan [t +nan] | +nan / +nan / +nan | +nan [t +nan] | +nan [t +nan] | +nan / +nan / +nan |


En güçlü 3 özelliğin kuintil profili (kapsam: teyit kuralı (yeni canlı); mutlak net bir kuintilde > 0 oluyor mu?):

| özellik | kuintil | alt sınır | n | hit | net | net−taban | blok net (seçim / değerlendirme) |
|---|---|---|---|---|---|---|---|
| 5m.willr14 | K1 | -95.2 | 83 | 56.6% | -0.68 | +0.27 | -0.60 / -1.03 |
| 5m.willr14 | K2 | -35 | 83 | 55.4% | -0.66 | +0.55 | -0.54 / -0.98 |
| 5m.willr14 | K3 | -19.9 | 83 | 57.8% | -0.54 | +0.50 | -0.52 / -0.65 |
| 5m.willr14 | K4 | -10.8 | 83 | 59.0% | -0.50 | +0.35 | -0.57 / -0.17 |
| 5m.willr14 | K5 | -4.65 | 84 | 47.6% | -1.31 | -0.65 | -1.66 / +1.22 |
| 15m.cvd_slope48 | K1 | -0.264 | 83 | 47.0% | -0.80 | +0.42 | -0.85 / -0.56 |
| 15m.cvd_slope48 | K2 | -0.0406 | 83 | 54.2% | -0.92 | +0.27 | -1.06 / -0.43 |
| 15m.cvd_slope48 | K3 | -0.00701 | 83 | 59.0% | -0.31 | +0.35 | -0.39 / +0.08 |
| 15m.cvd_slope48 | K4 | 0.0226 | 82 | 65.9% | -0.45 | +0.47 | -0.52 / -0.09 |
| 15m.cvd_slope48 | K5 | 0.0508 | 85 | 50.6% | -1.20 | -0.49 | -1.20 / -1.21 |
| 5m.donch_pos20 | K1 | 0.191 | 82 | 56.1% | -0.68 | +0.32 | -0.64 / -0.88 |
| 5m.donch_pos20 | K2 | 0.667 | 84 | 58.3% | -0.58 | +0.59 | -0.31 / -1.31 |
| 5m.donch_pos20 | K3 | 0.818 | 83 | 57.8% | -0.67 | +0.39 | -0.75 / -0.31 |
| 5m.donch_pos20 | K4 | 0.897 | 82 | 58.5% | -0.32 | +0.57 | -0.45 / +0.25 |
| 5m.donch_pos20 | K5 | 0.958 | 85 | 45.9% | -1.43 | -0.84 | -1.69 / +0.59 |


#### A2. Klasik fikirler (önceden belirlenmiş koşullar; eşik seçimi YOK)

Kapsam: tümü

| fikir (koşul sağlanınca al) | tutulan pay | n | hit tutulan | hit düşen | net tutulan | net düşen | net−taban tutulan | Δ(net−taban) tutulan−düşen | blok Δ(net−taban) | blok net (tutulan) | her blokta + ve %95>0 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| above_avwap | 94% | 1891 | 41.4% | 37.1% | -0.57 | -0.77 | +0.16 | +0.21 [t +0.7] | +0.52 / -0.05 | -0.54 / -0.66 | hayır |
| above_avwap_15m | 92% | 1842 | 41.3% | 39.4% | -0.58 | -0.60 | +0.14 | -0.13 [t -0.5] | +0.24 / -0.47 | -0.54 / -0.73 | hayır |
| above_poc | 84% | 1690 | 41.1% | 41.0% | -0.57 | -0.64 | +0.13 | -0.13 [t -0.7] | -0.13 / -0.12 | -0.55 / -0.66 | hayır |
| above_poc_15m | 82% | 1639 | 41.1% | 41.0% | -0.56 | -0.65 | +0.13 | -0.10 [t -0.5] | -0.06 / -0.14 | -0.54 / -0.67 | hayır |
| above_vwap | 94% | 1885 | 41.4% | 36.9% | -0.57 | -0.69 | +0.15 | +0.06 [t +0.2] | +0.23 / -0.07 | -0.55 / -0.66 | hayır |
| above_vwap_15m | 91% | 1818 | 41.5% | 37.0% | -0.55 | -0.82 | +0.16 | +0.13 [t +0.4] | +0.44 / -0.16 | -0.52 / -0.67 | hayır |
| adx25_di_up | 77% | 1536 | 40.6% | 42.9% | -0.60 | -0.51 | +0.13 | -0.08 [t -0.5] | -0.11 / -0.01 | -0.57 / -0.70 | hayır |
| adx25_di_up_15m | 74% | 1477 | 43.5% | 34.3% | -0.54 | -0.69 | +0.18 | +0.10 [t +0.6] | +0.09 / +0.17 | -0.52 / -0.63 | hayır |
| after_sweep_12bar | 10% | 198 | 43.9% | 40.8% | -0.60 | -0.58 | +0.24 | +0.10 [t +0.6] | +0.09 / +0.12 | -0.54 / -0.76 | hayır |
| after_sweep_3bar | 1% | 24 | 37.5% | 41.1% | -0.59 | -0.58 | -0.02 | -0.17 [t -0.3] | – / – | – / – | hayır |
| bull_fvg_open | 95% | 1897 | 40.7% | 48.2% | -0.60 | -0.20 | +0.13 | -0.31 [t -0.9] | -0.42 / -0.15 | -0.58 / -0.68 | hayır |
| bull_order_block_active | 90% | 1812 | 41.4% | 38.5% | -0.54 | -0.97 | +0.18 | +0.33 [t +1.3] | +0.33 / +0.35 | -0.51 / -0.62 | hayır |
| chop_trending | 57% | 1135 | 41.8% | 40.3% | -0.53 | -0.65 | +0.19 | +0.10 [t +0.8] | +0.15 / -0.06 | -0.50 / -0.60 | hayır |
| chop_trending_15m | 48% | 966 | 40.5% | 41.7% | -0.69 | -0.48 | +0.00 | -0.28 [t -2.2] | -0.21 / -0.51 | -0.64 / -0.84 | hayır |
| cmf_pos | 81% | 1630 | 42.8% | 34.0% | -0.55 | -0.69 | +0.16 | +0.04 [t +0.2] | +0.10 / -0.07 | -0.53 / -0.62 | hayır |
| cmf_pos_15m | 78% | 1575 | 41.7% | 39.1% | -0.60 | -0.51 | +0.11 | -0.16 [t -0.8] | +0.04 / -0.56 | -0.55 / -0.77 | hayır |
| cvd_up | 67% | 1343 | 42.8% | 37.7% | -0.57 | -0.60 | +0.13 | -0.06 [t -0.5] | -0.05 / -0.11 | -0.55 / -0.64 | hayır |
| cvd_up_15m | 64% | 1276 | 41.9% | 39.7% | -0.53 | -0.67 | +0.14 | -0.02 [t -0.2] | -0.04 / +0.02 | -0.51 / -0.59 | hayır |
| ichimoku_above_cloud | 93% | 1867 | 40.9% | 44.3% | -0.59 | -0.47 | +0.14 | -0.17 [t -0.7] | +0.02 / -0.32 | -0.56 / -0.70 | hayır |
| ichimoku_above_cloud_15m | 90% | 1801 | 41.3% | 39.8% | -0.59 | -0.47 | +0.12 | -0.25 [t -1.1] | -0.11 / -0.40 | -0.55 / -0.75 | hayır |
| in_bull_fvg_tap | 13% | 260 | 40.4% | 41.2% | -0.55 | -0.58 | +0.11 | -0.05 [t -0.3] | -0.03 / -0.11 | -0.50 / -0.70 | hayır |
| in_bull_order_block_tap | 4% | 71 | 36.6% | 41.3% | -0.60 | -0.58 | +0.11 | -0.04 [t -0.1] | -0.09 / – | -0.50 / – | hayır |
| ms_bullish | 94% | 1879 | 41.5% | 35.2% | -0.56 | -0.90 | +0.17 | +0.29 [t +1.1] | +0.17 / +0.48 | -0.54 / -0.62 | hayır |
| ms_bullish_15m | 91% | 1818 | 41.7% | 34.9% | -0.58 | -0.60 | +0.16 | +0.07 [t +0.3] | +0.10 / +0.05 | -0.54 / -0.70 | hayır |
| no_equal_highs_in_target | 99% | 1991 | 41.2% | 31.2% | -0.57 | -1.19 | +0.15 | +0.56 [t +1.1] | – / – | – / – | hayır |
| no_equal_highs_in_target_15m | 99% | 1990 | 41.3% | 23.5% | -0.57 | -1.54 | +0.16 | +1.12 [t +2.2] | – / – | – / – | hayır |
| no_swing_high_in_target | 83% | 1665 | 43.2% | 31.0% | -0.53 | -0.84 | +0.19 | +0.26 [t +1.8] | +0.23 / +0.37 | -0.51 / -0.58 | hayır |
| no_swing_high_in_target_15m | 83% | 1673 | 43.1% | 31.1% | -0.58 | -0.56 | +0.17 | +0.10 [t +0.6] | +0.22 / -0.23 | -0.54 / -0.73 | hayır |
| obv_up | 88% | 1766 | 41.8% | 35.7% | -0.56 | -0.68 | +0.16 | +0.07 [t +0.3] | +0.03 / +0.19 | -0.55 / -0.61 | hayır |
| obv_up_15m | 88% | 1761 | 41.6% | 37.8% | -0.58 | -0.58 | +0.16 | +0.07 [t +0.3] | +0.22 / -0.14 | -0.55 / -0.70 | hayır |
| supertrend_all_green | 85% | 1703 | 40.8% | 43.1% | -0.57 | -0.63 | +0.13 | -0.16 [t -0.8] | -0.07 / -0.29 | -0.54 / -0.68 | hayır |
| supertrend_all_green_15m | 79% | 1585 | 41.5% | 39.8% | -0.53 | -0.75 | +0.17 | +0.10 [t +0.6] | +0.22 / -0.07 | -0.51 / -0.63 | hayır |


ATR tersilleri içinde klasik fikirler (kapsam: tümü; oynaklık etkisi ayrıştırılmış):

| fikir (tutulan − düşen) | Δhit pp: ATR tersil 1 / 2 / 3 | Δ(net−taban): tersil 1 / 2 / 3 | n tutulan/düşen |
|---|---|---|---|
| above_avwap | +2.8 / +11.9 / +8.9 | -0.04 / +0.28 / +0.35 | 651/18 / 621/48 / 619/50 |
| above_avwap_15m | -3.8 / +12.3 / +7.0 | -0.47 / +0.34 / -0.29 | 641/28 / 606/63 / 595/74 |
| above_poc | +4.8 / +0.6 / +8.7 | +0.22 / -0.30 / -0.05 | 606/63 / 552/117 / 532/137 |
| above_poc_15m | +7.6 / -0.5 / +3.8 | +0.51 / -0.27 / -0.25 | 587/82 / 521/148 / 531/138 |
| above_vwap | +18.3 / +9.4 / +3.1 | +0.58 / +0.11 / -0.15 | 642/27 / 628/41 / 615/54 |
| above_vwap_15m | +11.0 / +9.1 / +5.8 | +0.20 / +0.28 / +0.03 | 628/41 / 599/70 / 591/78 |
| adx25_di_up | -2.2 / +4.4 / -11.4 | -0.01 / +0.05 / -0.32 | 500/169 / 519/150 / 517/152 |
| adx25_di_up_15m | +11.8 / +0.3 / +3.7 | +0.29 / -0.26 / +0.19 | 466/203 / 466/203 / 545/124 |
| after_sweep_12bar | +1.4 / +2.8 / +1.6 | +0.20 / +0.49 / -0.36 | 61/608 / 64/605 / 73/596 |
| after_sweep_3bar | – / – / – | – / – / – | 6/663 / 7/662 / 11/658 |
| bull_fvg_open | -8.6 / +12.3 / -4.1 | -0.60 / +0.61 / -0.62 | 654/15 / 635/34 / 608/61 |
| bull_order_block_active | +5.1 / +6.5 / +1.8 | +0.15 / +0.66 / +0.29 | 605/64 / 613/56 / 594/75 |
| chop_trending | +6.2 / +8.7 / +6.6 | +0.02 / +0.36 / +0.10 | 448/221 / 388/281 / 299/370 |
| chop_trending_15m | -2.3 / +2.2 / -7.7 | -0.21 / -0.25 / -0.43 | 300/369 / 326/343 / 340/329 |
| cmf_pos | +10.2 / +1.5 / +9.3 | +0.27 / -0.18 / -0.05 | 522/147 / 555/114 / 553/116 |
| cmf_pos_15m | -0.3 / -0.4 / +5.5 | +0.20 / -0.22 / -0.54 | 522/147 / 513/156 / 540/129 |
| cvd_up | +5.2 / +3.9 / +5.0 | +0.32 / -0.10 / -0.44 | 446/223 / 441/228 / 456/213 |
| cvd_up_15m | +5.6 / +2.4 / +2.2 | +0.43 / -0.01 / -0.44 | 456/213 / 399/270 / 421/248 |
| ichimoku_above_cloud | +17.2 / +5.9 / -9.5 | +0.23 / +0.17 / -0.53 | 645/24 / 614/55 / 608/61 |
| ichimoku_above_cloud_15m | +9.4 / +4.6 / -7.1 | +0.05 / -0.09 / -0.69 | 614/55 / 584/85 / 603/66 |
| in_bull_fvg_tap | +0.4 / -2.9 / +4.4 | -0.16 / -0.06 / +0.14 | 95/574 / 87/582 / 78/591 |
| in_bull_order_block_tap | – / -10.5 / -10.7 | – / -0.43 / +0.07 | 11/658 / 32/637 / 28/641 |
| ms_bullish | +8.1 / +13.2 / +11.2 | +0.20 / +0.36 / +0.41 | 640/29 / 630/39 / 609/60 |
| ms_bullish_15m | +15.8 / +4.3 / +2.4 | +0.75 / +0.02 / -0.51 | 612/57 / 599/70 / 607/62 |
| no_equal_highs_in_target | – / – / – | – / – / – | 666/3 / 662/7 / 663/6 |
| no_equal_highs_in_target_15m | – / – / – | – / – / – | 661/8 / 665/4 / 664/5 |
| no_swing_high_in_target | +3.3 / +17.6 / +18.0 | +0.18 / +0.34 / +0.30 | 561/108 / 558/111 / 546/123 |
| no_swing_high_in_target_15m | +6.5 / +6.4 / +5.6 | +0.13 / -0.37 / +0.48 | 509/160 / 562/107 / 602/67 |
| obv_up | +13.5 / +13.9 / -2.3 | +0.53 / +0.33 / -0.49 | 599/70 / 588/81 / 579/90 |
| obv_up_15m | +3.4 / +2.9 / +3.5 | +0.09 / +0.07 / +0.03 | 587/82 / 582/87 / 592/77 |
| supertrend_all_green | +4.9 / +9.9 / +7.2 | +0.22 / -0.13 / -0.11 | 620/49 / 594/75 / 489/180 |
| supertrend_all_green_15m | +6.5 / +12.7 / +2.5 | +0.23 / +0.25 / +0.04 | 576/93 / 530/139 / 479/190 |


Kapsam: yeni teyit kuralını geçenler

| fikir (koşul sağlanınca al) | tutulan pay | n | hit tutulan | hit düşen | net tutulan | net düşen | net−taban tutulan | Δ(net−taban) tutulan−düşen | blok Δ(net−taban) | blok net (tutulan) | her blokta + ve %95>0 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| above_avwap | 91% | 379 | 57.0% | 37.8% | -0.66 | -1.54 | +0.29 | +1.03 [t +1.8] | +0.95 / – | -0.71 / – | hayır |
| above_avwap_15m | 89% | 370 | 58.1% | 32.6% | -0.60 | -1.87 | +0.33 | +1.14 [t +2.3] | +1.07 / – | -0.65 / – | hayır |
| above_poc | 82% | 342 | 56.4% | 50.0% | -0.60 | -1.37 | +0.31 | +0.61 [t +1.4] | +0.43 / – | -0.68 / – | hayır |
| above_poc_15m | 80% | 331 | 57.7% | 45.9% | -0.58 | -1.38 | +0.31 | +0.52 [t +1.4] | +0.56 / – | -0.62 / – | hayır |
| above_vwap | 93% | 387 | 55.8% | 48.3% | -0.71 | -1.18 | +0.25 | +0.72 [t +1.1] | +0.60 / – | -0.77 / – | hayır |
| above_vwap_15m | 89% | 369 | 57.2% | 40.4% | -0.60 | -1.85 | +0.31 | +0.99 [t +2.2] | +0.90 / – | -0.64 / – | hayır |
| adx25_di_up | 73% | 304 | 54.9% | 56.2% | -0.77 | -0.66 | +0.19 | -0.04 [t -0.1] | -0.08 / – | -0.80 / – | hayır |
| adx25_di_up_15m | 75% | 314 | 57.6% | 48.0% | -0.63 | -1.08 | +0.35 | +0.61 [t +1.5] | +0.42 / – | -0.71 / – | hayır |
| after_sweep_12bar | 10% | 40 | 70.0% | 53.7% | -1.11 | -0.70 | -0.05 | -0.28 [t -0.5] | -0.16 / – | -0.93 / – | hayır |
| after_sweep_3bar | 0% | 2 | 50.0% | 55.3% | -0.73 | -0.74 | +0.27 | +0.07 [t +0.3] | – / – | – / – | hayır |
| bull_fvg_open | 91% | 379 | 55.1% | 56.8% | -0.80 | -0.09 | +0.17 | -0.34 [t -0.5] | -0.48 / – | -0.85 / – | hayır |
| bull_order_block_active | 90% | 373 | 55.0% | 58.1% | -0.73 | -0.82 | +0.21 | +0.03 [t +0.1] | -0.10 / – | -0.79 / – | hayır |
| chop_trending | 48% | 201 | 57.2% | 53.5% | -0.69 | -0.78 | +0.27 | +0.14 [t +0.4] | +0.14 / -0.00 | -0.73 / -0.57 | hayır |
| chop_trending_15m | 44% | 184 | 51.1% | 58.6% | -1.08 | -0.47 | -0.17 | -0.66 [t -2.3] | -0.58 / -1.27 | -1.09 / -1.04 | hayır |
| cmf_pos | 84% | 351 | 57.0% | 46.2% | -0.74 | -0.71 | +0.16 | -0.26 [t -0.5] | -0.25 / – | -0.80 / – | hayır |
| cmf_pos_15m | 77% | 322 | 58.7% | 43.6% | -0.67 | -0.97 | +0.23 | +0.14 [t +0.3] | +0.27 / – | -0.71 / – | hayır |
| cvd_up | 69% | 285 | 55.8% | 54.2% | -0.86 | -0.49 | +0.04 | -0.50 [t -1.7] | -0.77 / – | -0.97 / – | hayır |
| cvd_up_15m | 59% | 245 | 57.6% | 52.0% | -0.78 | -0.68 | +0.06 | -0.35 [t -1.1] | -0.60 / +0.68 | -0.87 / -0.40 | hayır |
| ichimoku_above_cloud | 89% | 372 | 54.8% | 59.1% | -0.76 | -0.59 | +0.20 | +0.02 [t +0.0] | -0.10 / – | -0.82 / – | hayır |
| ichimoku_above_cloud_15m | 88% | 364 | 56.0% | 50.0% | -0.70 | -1.03 | +0.22 | +0.14 [t +0.3] | +0.05 / – | -0.74 / – | hayır |
| in_bull_fvg_tap | 10% | 43 | 65.1% | 54.2% | +0.13 | -0.84 | +1.06 | +0.96 [t +1.9] | +1.31 / – | +0.35 / – | hayır |
| in_bull_order_block_tap | 5% | 19 | 42.1% | 55.9% | -0.95 | -0.73 | -0.41 | -0.64 [t -0.6] | – / – | – / – | hayır |
| ms_bullish | 90% | 376 | 57.2% | 37.5% | -0.65 | -1.59 | +0.29 | +0.89 [t +1.7] | +0.59 / – | -0.71 / – | hayır |
| ms_bullish_15m | 88% | 368 | 56.2% | 47.9% | -0.75 | -0.69 | +0.20 | -0.05 [t -0.1] | -0.15 / – | -0.79 / – | hayır |
| no_equal_highs_in_target | 99% | 412 | 55.6% | 25.0% | -0.73 | -1.56 | +0.21 | +0.85 [t +0.6] | – / – | – / – | hayır |
| no_equal_highs_in_target_15m | 99% | 413 | 55.4% | 33.3% | -0.73 | -1.56 | +0.21 | +1.64 [t +1.5] | – / – | – / – | hayır |
| no_swing_high_in_target | 84% | 350 | 58.3% | 39.4% | -0.59 | -1.52 | +0.28 | +0.52 [t +1.3] | +0.38 / – | -0.65 / – | hayır |
| no_swing_high_in_target_15m | 88% | 365 | 55.9% | 51.0% | -0.74 | -0.74 | +0.25 | +0.38 [t +0.7] | +0.62 / – | -0.76 / – | hayır |
| obv_up | 87% | 360 | 55.6% | 53.6% | -0.77 | -0.55 | +0.17 | -0.20 [t -0.3] | -0.46 / – | -0.86 / – | hayır |
| obv_up_15m | 87% | 360 | 56.4% | 48.2% | -0.72 | -0.87 | +0.24 | +0.30 [t +0.6] | +0.42 / – | -0.75 / – | hayır |
| supertrend_all_green | 77% | 320 | 55.9% | 53.1% | -0.74 | -0.73 | +0.16 | -0.19 [t -0.6] | -0.39 / – | -0.81 / – | hayır |
| supertrend_all_green_15m | 72% | 300 | 56.7% | 51.7% | -0.63 | -1.01 | +0.32 | +0.42 [t +1.2] | +0.07 / +1.95 | -0.73 / -0.22 | hayır |


#### A3. Filtre kuralları — seçim: seçim 17.09–09.10; sonra DOKUNULMADAN: değerlendirme 10.10–17.10

Seçim dönemi: n=1522, aday kural 2162 (özellik × yön × 3 eşik). Hedef işlevi: (a) net−taban [oynaklık kontrollü], (b) ham net. Her hedef için en iyi 3 FARKLI özellik (Jaccard ≤ 0,7).

- A1: `15m.ms_bos_up > 1e-09` — seçim dönemi t=2.2, n=181, ort.=+0.65
- A2: `5m.ret3 > 3.089` — seçim dönemi t=2.0, n=507, ort.=+0.45
- A3: `5m.px_mcg > 5.379` — seçim dönemi t=1.7, n=507, ort.=+0.37
- N1: `15m.rvi_vol <= 58.68` — seçim dönemi t=1.6, n=508, ort.=-0.33
- N2: `5m.chop_drop12 <= -14.75` — seçim dönemi t=1.5, n=759, ort.=-0.42
- N3: `15m.obv_slope48 <= 0.36` — seçim dönemi t=1.5, n=1015, ort.=-0.41

Kapsam: tümü

| kural | dilim | n | gün/adet | hit | hit (hepsi) | net | net (hepsi) | net−taban | Δ(net−taban) vs hepsi [95] | ATR% (tutulan/hepsi) |
|---|---|---|---|---|---|---|---|---|---|---|
| A1: 15m.ms_bos_up > 1e-09 | seçim 17.09–09.10 | 181 | 7.9 | 43.1% | 41.9% | -0.20 | -0.56 | +0.65 | +0.51 [+0.09; +0.93] | 1.23 / 1.51 |
| A1: 15m.ms_bos_up > 1e-09 | değerlendirme 10.10–17.10 | 46 | 5.8 | 32.6% | 38.8% | -1.01 | -0.65 | +0.03 | -0.15 [-0.85; +0.56] | 1.62 / 1.80 |
| A2: 5m.ret3 > 3.089 | seçim 17.09–09.10 | 507 | 22.0 | 59.4% | 41.9% | -0.41 | -0.56 | +0.45 | +0.31 [+0.07; +0.54] | 2.32 / 1.51 |
| A2: 5m.ret3 > 3.089 | değerlendirme 10.10–17.10 | 192 | 24.0 | 46.4% | 38.8% | -0.62 | -0.65 | +0.39 | +0.21 [-0.23; +0.65] | 2.12 / 1.80 |
| A3: 5m.px_mcg > 5.379 | seçim 17.09–09.10 | 507 | 22.0 | 61.1% | 41.9% | -0.50 | -0.56 | +0.37 | +0.23 [-0.02; +0.49] | 2.60 / 1.51 |
| A3: 5m.px_mcg > 5.379 | değerlendirme 10.10–17.10 | 166 | 20.8 | 50.6% | 38.8% | -0.66 | -0.65 | +0.33 | +0.16 [-0.23; +0.54] | 2.73 / 1.80 |
| N1: 15m.rvi_vol <= 58.68 | seçim 17.09–09.10 | 508 | 22.1 | 42.9% | 41.9% | -0.33 | -0.56 | +0.42 | +0.28 [-0.02; +0.58] | 1.58 / 1.51 |
| N1: 15m.rvi_vol <= 58.68 | değerlendirme 10.10–17.10 | 273 | 34.1 | 39.6% | 38.8% | -0.54 | -0.65 | +0.37 | +0.19 [-0.14; +0.52] | 1.70 / 1.80 |
| N2: 5m.chop_drop12 <= -14.75 | seçim 17.09–09.10 | 759 | 33.0 | 43.5% | 41.9% | -0.42 | -0.56 | +0.28 | +0.14 [-0.03; +0.31] | 1.34 / 1.51 |
| N2: 5m.chop_drop12 <= -14.75 | değerlendirme 10.10–17.10 | 240 | 30.0 | 40.4% | 38.8% | -0.51 | -0.65 | +0.25 | +0.07 [-0.37; +0.50] | 1.49 / 1.80 |
| N3: 15m.obv_slope48 <= 0.36 | seçim 17.09–09.10 | 1015 | 44.1 | 41.8% | 41.9% | -0.41 | -0.56 | +0.28 | +0.14 [-0.02; +0.29] | 1.37 / 1.51 |
| N3: 15m.obv_slope48 <= 0.36 | değerlendirme 10.10–17.10 | 368 | 46.0 | 39.1% | 38.8% | -0.51 | -0.65 | +0.35 | +0.17 [-0.19; +0.54] | 1.74 / 1.80 |


Kapsam: teyit kuralı (yeni canlı)

| kural | dilim | n | gün/adet | hit | hit (hepsi) | net | net (hepsi) | net−taban | Δ(net−taban) vs hepsi [95] | ATR% (tutulan/hepsi) |
|---|---|---|---|---|---|---|---|---|---|---|
| A1: 15m.ms_bos_up > 1e-09 | seçim 17.09–09.10 | 37 | 1.6 | 54.1% | 53.8% | -0.42 | -0.80 | +0.68 | +0.57 [-0.48; +1.62] | 1.95 / 2.59 |
| A1: 15m.ms_bos_up > 1e-09 | değerlendirme 10.10–17.10 | 10 | 1.2 | 70.0% | 61.5% | +0.40 | -0.48 | +1.74 | +1.14 [-0.09; +2.37] | 2.83 / 2.64 |
| A2: 5m.ret3 > 3.089 | seçim 17.09–09.10 | 212 | 9.2 | 59.0% | 53.8% | -0.71 | -0.80 | +0.26 | +0.16 [-0.17; +0.48] | 2.73 / 2.59 |
| A2: 5m.ret3 > 3.089 | değerlendirme 10.10–17.10 | 46 | 5.8 | 65.2% | 61.5% | -0.27 | -0.48 | +1.05 | +0.45 [-0.02; +0.91] | 2.74 / 2.64 |
| A3: 5m.px_mcg > 5.379 | seçim 17.09–09.10 | 208 | 9.0 | 61.1% | 53.8% | -0.66 | -0.80 | +0.28 | +0.17 [-0.17; +0.52] | 2.93 / 2.59 |
| A3: 5m.px_mcg > 5.379 | değerlendirme 10.10–17.10 | 55 | 6.9 | 60.0% | 61.5% | -0.65 | -0.48 | +0.69 | +0.08 [-0.18; +0.35] | 2.93 / 2.64 |
| N1: 15m.rvi_vol <= 58.68 | seçim 17.09–09.10 | 145 | 6.3 | 51.7% | 53.8% | -0.61 | -0.80 | +0.29 | +0.18 [-0.55; +0.91] | 2.53 / 2.59 |
| N1: 15m.rvi_vol <= 58.68 | değerlendirme 10.10–17.10 | 36 | 4.5 | 63.9% | 61.5% | -0.17 | -0.48 | +0.64 | +0.04 [-0.79; +0.87] | 2.29 / 2.64 |
| N2: 5m.chop_drop12 <= -14.75 | seçim 17.09–09.10 | 170 | 7.4 | 55.3% | 53.8% | -0.66 | -0.80 | +0.22 | +0.11 [-0.33; +0.56] | 2.21 / 2.59 |
| N2: 5m.chop_drop12 <= -14.75 | değerlendirme 10.10–17.10 | 37 | 4.6 | 78.4% | 61.5% | +0.20 | -0.48 | +1.25 | +0.65 [+0.17; +1.13] | 2.37 / 2.64 |
| N3: 15m.obv_slope48 <= 0.36 | seçim 17.09–09.10 | 218 | 9.5 | 54.6% | 53.8% | -0.47 | -0.80 | +0.39 | +0.28 [-0.22; +0.78] | 2.48 / 2.59 |
| N3: 15m.obv_slope48 <= 0.36 | değerlendirme 10.10–17.10 | 54 | 6.8 | 63.0% | 61.5% | -0.42 | -0.48 | +0.59 | -0.02 [-0.37; +0.34] | 2.56 / 2.64 |


**Aşırı uyum tanısı** (seçim döneminde en iyi 50 aday kuralın seçim dışı performansı; hepsi aynı yönde sistematik bir kenar olsaydı OOS ortalaması > 0 olurdu):

| hedef | aday | OOS: en iyi-50 ort. Δ | en iyi-50 pozitif pay | tüm adaylar ort. Δ | tüm adaylar pozitif pay |
|---|---|---|---|---|---|
| net−taban | 1926 | +0.12 | 88.0% | -0.02 | 50.0% |
| ham net | 1926 | +0.08 | 82.0% | -0.01 | 50.0% |


### Nüfus 1 — Hız Avcısı canlı-benzeri bölümler (90 gün)
Olay 20343, geçerli (pencere + ATR + hedef) 20343; özellik sayısı 439 (klasik-fikir sütunları dahil).

#### Nüfus özeti (mevcut sinyal; taban = oynaklık-eşleşmiş rastgele)

| kapsam | dilim | n | gün/adet | hit | taban hit | net | taban net | net − taban [95] | ort. ATR% |
|---|---|---|---|---|---|---|---|---|---|
| tümü | B1 (20 Tem–18 Ağu) | 6110 | 203.7 | 25.2% | 5.3% | -0.54 | -0.87 | +0.33 [+0.25; +0.41] | 1.36 |
| tümü | B2 (19 Ağu–17 Eyl) | 6797 | 226.6 | 21.3% | 4.2% | -0.51 | -0.62 | +0.10 [+0.02; +0.18] | 1.16 |
| tümü | B3 (18 Eyl–16 Eki) | 7436 | 256.4 | 22.5% | 3.9% | -0.62 | -0.79 | +0.17 [+0.07; +0.26] | 1.21 |
| tümü | tümü | 20343 | 228.6 | 22.9% | 4.4% | -0.56 | -0.76 | +0.19 [+0.14; +0.25] | 1.24 |


#### A1. Özellik sıralaması — kapsam: tümü (n=20343)

`r` = kısmi Spearman (ATR ve hedef/ATR sıralarının 1.+2. derece terimleri sabit; ham sütunda kontrol yok); `t` küme-dayanıklı (gün); q = BH (özellikler arası). 'net−taban' = olay neti − eşleşmiş rastgele taban neti.

Anlamlı (BH q) özellik sayısı:

| sonuç | özellik | q<0,05 | q<0,01 |
|---|---|---|---|
| net (ham) | 438 | 195 | 135 |
| net (ATR-kontrollü) | 438 | 180 | 119 |
| net−taban (ham) | 438 | 207 | 129 |
| net−taban (ATR-kontrollü) | 438 | 177 | 98 |
| hit (ham) | 438 | 318 | 291 |
| hit (ATR-kontrollü) | 438 | 354 | 334 |
| hit−taban (ATR-kontrollü) | 438 | 353 | 332 |

Hem hit'te hem net−taban'da (ATR-kontrollü) anlamlı 165 özellikten **164**'inde işaretler TERS (hit'i artıran özellik net'i azaltıyor): hit'e bakarak seçilen filtre net'i bozabilir.

En iyi 15 özellik — ATR-kontrollü net−taban |t| sıralı:

| özellik | kapsam | ham r(net) [t] | ATR-kont. r(net) [t] | ATR-kont. r(net−taban) [t] | q | ATR-kont. r(hit) [t] | q(hit) | AUC net>0 | AUC hit | blok r(net−taban) | işaret uyumu |
|---|---|---|---|---|---|---|---|---|---|---|---|
| res:swing_5m | 100% | -0.026 [-3.4] | -0.045 [-6.2] | -0.047 [-6.7] | 0.000 | +0.037 [+5.3] | 0.000 | 0.479 | 0.476 | -0.056 / -0.041 / -0.047 | 3/3 |
| 5m.efi13 | 100% | -0.046 [-5.8] | -0.049 [-6.3] | -0.048 [-6.1] | 0.000 | +0.077 [+12.0] | 0.000 | 0.482 | 0.530 | -0.037 / -0.054 / -0.053 | 3/3 |
| idea:no_swing_high_in_target | 100% | -0.033 [-4.6] | -0.036 [-5.2] | -0.040 [-6.0] | 0.000 | +0.019 [+2.7] | 0.011 | 0.489 | 0.500 | -0.056 / -0.029 / -0.037 | 3/3 |
| 5m.pvt_slope12 | 100% | -0.041 [-5.0] | -0.048 [-6.1] | -0.042 [-5.5] | 0.000 | +0.075 [+11.0] | 0.000 | 0.482 | 0.520 | -0.043 / -0.044 / -0.042 | 3/3 |
| 5m.px_wma | 100% | -0.050 [-5.9] | -0.053 [-6.0] | -0.043 [-5.0] | 0.000 | +0.083 [+10.9] | 0.000 | 0.488 | 0.532 | -0.037 / -0.050 / -0.044 | 3/3 |
| 5m.px_ema20 | 100% | -0.053 [-6.3] | -0.049 [-5.7] | -0.042 [-5.0] | 0.000 | +0.082 [+10.8] | 0.000 | 0.492 | 0.545 | -0.036 / -0.045 / -0.046 | 3/3 |
| 5m.kvo | 100% | -0.023 [-3.0] | -0.039 [-5.3] | -0.036 [-4.9] | 0.000 | +0.062 [+9.4] | 0.000 | 0.481 | 0.495 | -0.035 / -0.024 / -0.049 | 3/3 |
| 5m.kc_pos | 100% | -0.010 [-1.3] | -0.043 [-5.5] | -0.037 [-4.9] | 0.000 | +0.081 [+11.9] | 0.000 | 0.477 | 0.468 | -0.034 / -0.030 / -0.045 | 3/3 |
| 5m.px_mcg | 100% | -0.058 [-7.3] | -0.043 [-5.3] | -0.039 [-4.7] | 0.000 | +0.082 [+11.9] | 0.000 | 0.499 | 0.570 | -0.031 / -0.044 / -0.041 | 3/3 |
| 5m.ms_dist_sh | 100% | -0.013 [-1.4] | -0.043 [-5.1] | -0.038 [-4.6] | 0.000 | +0.085 [+11.6] | 0.000 | 0.482 | 0.476 | -0.027 / -0.035 / -0.049 | 3/3 |
| 5m.ret10 | 100% | -0.043 [-5.0] | -0.047 [-5.6] | -0.040 [-4.6] | 0.000 | +0.084 [+11.7] | 0.000 | 0.488 | 0.530 | -0.031 / -0.051 / -0.039 | 3/3 |
| 5m.bb_pctb | 100% | -0.010 [-1.3] | -0.038 [-5.1] | -0.032 [-4.6] | 0.000 | +0.085 [+13.2] | 0.000 | 0.479 | 0.475 | -0.027 / -0.030 / -0.041 | 3/3 |
| 5m.slope_kama | 100% | -0.027 [-3.2] | -0.043 [-5.4] | -0.037 [-4.6] | 0.000 | +0.080 [+10.6] | 0.000 | 0.485 | 0.506 | -0.023 / -0.049 / -0.041 | 3/3 |
| 5m.minus_di14 | 100% | +0.045 [+5.5] | +0.038 [+4.9] | +0.037 [+4.5] | 0.001 | -0.070 [-10.6] | 0.000 | 0.505 | 0.454 | +0.020 / +0.046 / +0.047 | 3/3 |
| 5m.fisher | 100% | -0.020 [-2.4] | -0.041 [-5.1] | -0.035 [-4.4] | 0.001 | +0.071 [+9.4] | 0.000 | 0.486 | 0.496 | -0.015 / -0.040 / -0.047 | 3/3 |

En iyi 15 özellik — HAM net |t| sıralı (ATR'nin etkisi dahil):

| özellik | kapsam | ham r(net) [t] | ATR-kont. r(net) [t] | ATR-kont. r(net−taban) [t] | q | ATR-kont. r(hit) [t] | q(hit) | AUC net>0 | AUC hit | blok r(net−taban) | işaret uyumu |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 5m.kc_width | 100% | -0.081 [-12.0] | -0.015 [-2.4] | -0.012 [-1.9] | 0.121 | +0.052 [+7.0] | 0.000 | 0.538 | 0.674 | -0.019 / -0.015 / -0.003 | 3/3 |
| ex:atr_pct | 100% | -0.081 [-11.8] | -0.026 [-3.1] | -0.021 [-2.5] | 0.039 | +0.080 [+10.8] | 0.000 | 0.528 | 0.665 | -0.028 / -0.022 / -0.020 | 3/3 |
| ex:m1_atr_prev | 100% | -0.081 [-11.6] | -0.025 [-3.1] | -0.020 [-2.5] | 0.038 | +0.077 [+10.7] | 0.000 | 0.529 | 0.665 | -0.030 / -0.021 / -0.017 | 3/3 |
| 5m.atr14_pct | 100% | -0.078 [-11.4] | +0.003 [+0.5] | +0.007 [+1.1] | 0.372 | +0.008 [+1.2] | 0.254 | 0.539 | 0.671 | +0.025 / -0.006 / +0.005 | 2/3 |
| ex:m3_atr_prev | 100% | -0.077 [-11.1] | -0.019 [-2.4] | -0.015 [-1.9] | 0.125 | +0.068 [+8.9] | 0.000 | 0.530 | 0.664 | -0.029 / -0.016 / -0.005 | 3/3 |
| 5m.hv20 | 100% | -0.082 [-11.0] | -0.027 [-3.4] | -0.026 [-3.3] | 0.007 | -0.006 [-0.8] | 0.452 | 0.526 | 0.651 | -0.063 / -0.015 / -0.012 | 3/3 |
| 5m.bb_width_pct | 100% | -0.081 [-10.9] | -0.029 [-3.7] | -0.025 [-3.2] | 0.008 | +0.019 [+2.9] | 0.007 | 0.528 | 0.642 | -0.022 / -0.009 / -0.039 | 3/3 |
| 5m.donch_width20 | 100% | -0.078 [-10.4] | -0.018 [-2.5] | -0.017 [-2.3] | 0.057 | +0.030 [+4.9] | 0.000 | 0.533 | 0.657 | -0.009 / -0.002 / -0.030 | 3/3 |
| 15m.kc_width | 100% | -0.071 [-10.1] | -0.003 [-0.5] | +0.004 [+0.7] | 0.604 | -0.003 [-0.5] | 0.656 | 0.536 | 0.655 | -0.006 / +0.003 / +0.015 | 2/3 |
| ex:velocity_score | 100% | -0.069 [-10.1] | -0.037 [-4.6] | -0.035 [-4.4] | 0.001 | +0.074 [+10.7] | 0.000 | 0.506 | 0.596 | -0.061 / -0.024 / -0.029 | 3/3 |
| 5m.lsma_se_pct | 100% | -0.072 [-10.0] | -0.012 [-1.6] | -0.010 [-1.3] | 0.302 | +0.003 [+0.4] | 0.688 | 0.529 | 0.642 | -0.044 / +0.011 / -0.001 | 2/3 |
| 15m.lsma_se_pct | 100% | -0.073 [-9.9] | -0.021 [-3.1] | -0.008 [-1.1] | 0.368 | -0.003 [-0.4] | 0.697 | 0.528 | 0.632 | -0.019 / -0.017 / +0.013 | 2/3 |
| 15m.hv20 | 100% | -0.072 [-9.9] | -0.017 [-2.4] | -0.004 [-0.6] | 0.660 | +0.005 [+0.8] | 0.476 | 0.530 | 0.639 | -0.020 / -0.009 / +0.012 | 2/3 |
| 15m.atr14_pct | 100% | -0.066 [-9.7] | -0.001 [-0.1] | +0.009 [+1.5] | 0.234 | -0.006 [-0.9] | 0.391 | 0.536 | 0.646 | +0.003 / +0.001 / +0.021 | 3/3 |
| 15m.donch_width20 | 100% | -0.068 [-9.6] | -0.007 [-0.9] | -0.003 [-0.4] | 0.763 | +0.011 [+1.5] | 0.168 | 0.537 | 0.646 | +0.009 / -0.013 / +0.001 | 1/3 |

En iyi 15 özellik — ATR-kontrollü HIT |t| sıralı:

| özellik | kapsam | ham r(net) [t] | ATR-kont. r(net) [t] | ATR-kont. r(net−taban) [t] | q | ATR-kont. r(hit) [t] | q(hit) | AUC net>0 | AUC hit | blok r(net−taban) | işaret uyumu |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 5m.cci20 | 100% | -0.006 [-0.8] | -0.036 [-4.9] | -0.031 [-4.4] | 0.001 | +0.088 [+14.0] | 0.000 | 0.480 | 0.475 | -0.028 / -0.027 / -0.040 | 3/3 |
| 5m.bb_pctb | 100% | -0.010 [-1.3] | -0.038 [-5.1] | -0.032 [-4.6] | 0.000 | +0.085 [+13.2] | 0.000 | 0.479 | 0.475 | -0.027 / -0.030 / -0.041 | 3/3 |
| 5m.vi_minus | 100% | +0.005 [+0.6] | +0.036 [+4.6] | +0.031 [+3.9] | 0.002 | -0.080 [-12.0] | 0.000 | 0.519 | 0.525 | +0.014 / +0.036 / +0.040 | 3/3 |
| 5m.efi13 | 100% | -0.046 [-5.8] | -0.049 [-6.3] | -0.048 [-6.1] | 0.000 | +0.077 [+12.0] | 0.000 | 0.482 | 0.530 | -0.037 / -0.054 / -0.053 | 3/3 |
| 5m.kc_pos | 100% | -0.010 [-1.3] | -0.043 [-5.5] | -0.037 [-4.9] | 0.000 | +0.081 [+11.9] | 0.000 | 0.477 | 0.468 | -0.034 / -0.030 / -0.045 | 3/3 |
| 5m.px_mcg | 100% | -0.058 [-7.3] | -0.043 [-5.3] | -0.039 [-4.7] | 0.000 | +0.082 [+11.9] | 0.000 | 0.499 | 0.570 | -0.031 / -0.044 / -0.041 | 3/3 |
| 5m.cmo14 | 100% | -0.020 [-2.4] | -0.040 [-5.2] | -0.032 [-4.4] | 0.001 | +0.081 [+11.8] | 0.000 | 0.484 | 0.497 | -0.017 / -0.034 / -0.043 | 3/3 |
| 5m.rsi14 | 100% | -0.019 [-2.3] | -0.038 [-4.8] | -0.034 [-4.4] | 0.001 | +0.080 [+11.8] | 0.000 | 0.484 | 0.495 | -0.022 / -0.034 / -0.044 | 3/3 |
| 5m.ret10 | 100% | -0.043 [-5.0] | -0.047 [-5.6] | -0.040 [-4.6] | 0.000 | +0.084 [+11.7] | 0.000 | 0.488 | 0.530 | -0.031 / -0.051 / -0.039 | 3/3 |
| 5m.vi_diff | 100% | -0.014 [-1.7] | -0.035 [-4.5] | -0.028 [-3.7] | 0.003 | +0.079 [+11.7] | 0.000 | 0.486 | 0.495 | -0.012 / -0.033 / -0.037 | 3/3 |
| 5m.ms_dist_sh | 100% | -0.013 [-1.4] | -0.043 [-5.1] | -0.038 [-4.6] | 0.000 | +0.085 [+11.6] | 0.000 | 0.482 | 0.476 | -0.027 / -0.035 / -0.049 | 3/3 |
| 5m.mfi14 | 100% | -0.021 [-2.9] | -0.035 [-5.3] | -0.028 [-3.9] | 0.002 | +0.075 [+11.4] | 0.000 | 0.488 | 0.506 | -0.018 / -0.026 / -0.037 | 3/3 |
| 5m.vol_ratio | 100% | -0.007 [-1.0] | -0.029 [-4.1] | -0.028 [-4.1] | 0.001 | +0.063 [+11.3] | 0.000 | 0.484 | 0.478 | -0.037 / -0.014 / -0.034 | 3/3 |
| 5m.smi_erg | 100% | -0.019 [-2.3] | -0.037 [-4.7] | -0.034 [-4.4] | 0.001 | +0.080 [+11.3] | 0.000 | 0.486 | 0.502 | -0.019 / -0.036 / -0.044 | 3/3 |
| 5m.slope_mcg | 100% | -0.048 [-5.9] | -0.036 [-4.4] | -0.033 [-3.9] | 0.002 | +0.077 [+11.2] | 0.000 | 0.502 | 0.569 | -0.022 / -0.042 / -0.034 | 3/3 |


Aile bazında özet (ATR-kontrollü):

| aile | özellik | q<0,05 (net−taban, ATR-kont.) | …ve tüm bloklarda aynı işaret | q<0,05 (hit−taban) | medyan |r| | en güçlü özellik |
|---|---|---|---|---|---|---|
| mevcut özellik (pattern_study: EMA/RSI/MFI/ATR/BB/MACD/ADX/taker...) | 105 | 48 | 46 | 92 | 0.015 | 5m.px_ema20 (r -0.042, t -5.0) |
| trend/kanal (SuperTrend, PSAR, Ichimoku, Donchian, Keltner, sıkışma, Choppiness) | 68 | 19 | 18 | 47 | 0.012 | 5m.kc_pos (r -0.037, t -4.9) |
| SMC (BOS/CHoCH, eşit tepe/dip, süpürme, FVG, OB, TD) | 63 | 16 | 15 | 37 | 0.013 | 5m.ms_dist_sh (r -0.038, t -4.6) |
| osilatörler (Stoch, TSI, KST, Fisher, CCI, ...) | 56 | 32 | 32 | 52 | 0.021 | 5m.fisher (r -0.035, t -4.4) |
| hareketli ortalamalar (ALMA/HMA/DEMA/KAMA/McGinley/LSMA) | 34 | 27 | 26 | 32 | 0.024 | 5m.px_wma (r -0.043, t -5.0) |
| klasik fikir (0/1) | 32 | 8 | 8 | 26 | 0.010 | idea:no_swing_high_in_target (r -0.040, t -6.0) |
| hacim/akış (OBV, A/D, CMF, Klinger, CVD, OFI) | 30 | 12 | 12 | 28 | 0.015 | 5m.efi13 (r -0.048, t -6.1) |
| mevcut sistem alanları (jsonl/olay) | 19 | 7 | 7 | 15 | 0.015 | ex:velocity_score (r -0.035, t -4.4) |
| direnç mesafesi | 9 | 2 | 2 | 6 | 0.007 | res:swing_5m (r -0.047, t -6.7) |
| oynaklık (ATR oranı, HV, RVI) | 8 | 3 | 2 | 6 | 0.014 | 5m.hv20 (r -0.026, t -3.3) |
| konum (VWAP, çapalı VWAP, POC) | 8 | 0 | 0 | 8 | 0.007 | 15m.poc_dist (r +0.011, t +1.5) |
| dyn_target bileşenleri | 6 | 3 | 3 | 4 | 0.020 | dyn:emp70 (r +0.034, t +3.8) |


ATR tersilleri içinde en iyi 8 özellik (ATR-kontrollü net−taban sıralı):

| özellik (üst yarı − alt yarı) | Δhit pp (ATR-tersil içi) | tersil 1/2/3 Δhit pp | Δnet | Δ(net−taban) | tersil 1/2/3 Δ(net−taban) |
|---|---|---|---|---|---|
| res:swing_5m | +3.8 [t +3.2] | +nan / +nan / +3.8 | -0.16 [t -2.4] | -0.22 [t -2.8] | +nan / +nan / -0.22 |
| 5m.efi13 | +4.4 [t +9.6] | +3.8 / +5.0 / +4.4 | -0.11 [t -3.1] | -0.13 [t -3.3] | -0.05 / -0.04 / -0.29 |
| idea:no_swing_high_in_target | +nan [t +nan] | +nan / +nan / +nan | +nan [t +nan] | +nan [t +nan] | +nan / +nan / +nan |
| 5m.pvt_slope12 | +4.2 [t +8.1] | +2.7 / +5.0 / +4.8 | -0.12 [t -3.2] | -0.12 [t -2.8] | -0.08 / -0.03 / -0.24 |
| 5m.px_wma | +3.6 [t +6.7] | +3.4 / +3.9 / +3.6 | -0.12 [t -3.2] | -0.11 [t -2.8] | -0.10 / -0.05 / -0.20 |
| 5m.px_ema20 | +4.0 [t +7.0] | +3.0 / +4.5 / +4.5 | -0.10 [t -2.7] | -0.10 [t -2.5] | -0.12 / +0.01 / -0.19 |
| 5m.kvo | +3.4 [t +6.5] | +2.4 / +5.3 / +2.7 | -0.05 [t -1.4] | -0.07 [t -1.7] | -0.10 / +0.04 / -0.15 |
| 5m.kc_pos | +2.8 [t +4.9] | +1.9 / +4.0 / +2.4 | -0.08 [t -2.4] | -0.11 [t -2.9] | -0.11 / +0.00 / -0.22 |


En güçlü 3 özelliğin kuintil profili (kapsam: tümü; mutlak net bir kuintilde > 0 oluyor mu?):

| özellik | kuintil | alt sınır | n | hit | net | net−taban | blok net (B1 / B2 / B3) |
|---|---|---|---|---|---|---|---|
| res:swing_5m | K1 | 0.00303 | 4069 | 22.9% | -0.40 | +0.39 | -0.31 / -0.40 / -0.46 |
| res:swing_5m | K2 | 2.12 | 4068 | 26.0% | -0.63 | +0.23 | -0.63 / -0.59 / -0.66 |
| res:swing_5m | K3 | 9.6 | 647 | 44.0% | -0.40 | +0.43 | -0.43 / -0.31 / -0.45 |
| res:swing_5m | K5 | 99 | 11558 | 20.7% | -0.60 | +0.10 | -0.60 / -0.54 / -0.67 |
| 5m.efi13 | K1 | -17.9 | 4069 | 22.1% | -0.50 | +0.31 | -0.48 / -0.44 / -0.58 |
| 5m.efi13 | K2 | -0.0336 | 4068 | 21.8% | -0.51 | +0.26 | -0.54 / -0.55 / -0.45 |
| 5m.efi13 | K3 | 0.253 | 4069 | 21.3% | -0.52 | +0.20 | -0.49 / -0.44 / -0.61 |
| 5m.efi13 | K4 | 0.595 | 4068 | 21.1% | -0.66 | +0.08 | -0.57 / -0.66 / -0.73 |
| 5m.efi13 | K5 | 1.3 | 4069 | 28.3% | -0.62 | +0.11 | -0.61 / -0.48 / -0.74 |
| idea:no_swing_high_in_target | K2 | 0 | 5578 | 22.9% | -0.45 | +0.35 | -0.38 / -0.45 / -0.52 |
| idea:no_swing_high_in_target | K5 | 1 | 14764 | 22.9% | -0.60 | +0.13 | -0.60 / -0.54 / -0.66 |


#### A2. Klasik fikirler (önceden belirlenmiş koşullar; eşik seçimi YOK)

Kapsam: tümü

| fikir (koşul sağlanınca al) | tutulan pay | n | hit tutulan | hit düşen | net tutulan | net düşen | net−taban tutulan | Δ(net−taban) tutulan−düşen | blok Δ(net−taban) | blok net (tutulan) | her blokta + ve %95>0 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| above_avwap | 81% | 16437 | 23.3% | 21.4% | -0.55 | -0.60 | +0.20 | +0.02 [t +0.4] | +0.02 / +0.09 / -0.01 | -0.52 / -0.50 / -0.62 | hayır |
| above_avwap_15m | 78% | 15964 | 23.5% | 20.8% | -0.55 | -0.62 | +0.20 | +0.04 [t +0.8] | +0.13 / +0.04 / -0.01 | -0.49 / -0.51 / -0.62 | hayır |
| above_poc | 64% | 12935 | 23.5% | 21.9% | -0.54 | -0.59 | +0.21 | +0.05 [t +0.9] | +0.01 / +0.10 / +0.06 | -0.53 / -0.50 / -0.60 | hayır |
| above_poc_15m | 61% | 12395 | 23.8% | 21.6% | -0.53 | -0.61 | +0.21 | +0.05 [t +1.0] | +0.12 / +0.06 / -0.01 | -0.46 / -0.50 / -0.61 | hayır |
| above_vwap | 74% | 15129 | 23.3% | 22.0% | -0.56 | -0.57 | +0.18 | -0.04 [t -0.8] | -0.04 / -0.00 / -0.05 | -0.53 / -0.51 / -0.63 | hayır |
| above_vwap_15m | 72% | 14550 | 23.6% | 21.2% | -0.55 | -0.60 | +0.19 | -0.01 [t -0.1] | +0.07 / -0.01 / -0.05 | -0.49 / -0.51 / -0.63 | hayır |
| adx25_di_up | 48% | 9730 | 24.1% | 21.9% | -0.59 | -0.53 | +0.13 | -0.12 [t -2.5] | -0.11 / -0.09 / -0.15 | -0.56 / -0.53 / -0.67 | hayır |
| adx25_di_up_15m | 55% | 11137 | 25.9% | 19.4% | -0.55 | -0.58 | +0.20 | +0.01 [t +0.2] | +0.13 / -0.10 / +0.00 | -0.49 / -0.52 / -0.62 | hayır |
| after_sweep_12bar | 15% | 3044 | 23.8% | 22.8% | -0.56 | -0.56 | +0.24 | +0.05 [t +0.9] | -0.07 / +0.05 / +0.16 | -0.59 / -0.51 / -0.58 | hayır |
| after_sweep_3bar | 3% | 648 | 23.3% | 22.9% | -0.62 | -0.56 | +0.28 | +0.09 [t +0.8] | +0.13 / +0.05 / +0.08 | -0.47 / -0.53 / -0.82 | hayır |
| bull_fvg_open | 84% | 17092 | 22.7% | 24.1% | -0.57 | -0.50 | +0.17 | -0.16 [t -2.4] | -0.10 / -0.15 / -0.19 | -0.54 / -0.53 / -0.64 | hayır |
| bull_order_block_active | 76% | 15504 | 23.5% | 21.1% | -0.56 | -0.56 | +0.19 | -0.03 [t -0.6] | -0.02 / -0.04 / -0.02 | -0.54 / -0.51 / -0.62 | hayır |
| chop_trending | 43% | 8797 | 19.4% | 25.6% | -0.56 | -0.56 | +0.13 | -0.12 [t -2.4] | -0.20 / +0.00 / -0.14 | -0.54 / -0.51 / -0.64 | hayır |
| chop_trending_15m | 31% | 6325 | 23.0% | 22.9% | -0.58 | -0.56 | +0.13 | -0.09 [t -1.8] | -0.04 / -0.05 / -0.16 | -0.51 / -0.51 / -0.69 | hayır |
| cmf_pos | 61% | 12324 | 23.7% | 21.7% | -0.57 | -0.54 | +0.19 | -0.02 [t -0.4] | -0.14 / +0.05 / +0.04 | -0.60 / -0.50 / -0.61 | hayır |
| cmf_pos_15m | 62% | 12596 | 24.1% | 21.0% | -0.55 | -0.57 | +0.20 | +0.03 [t +0.6] | +0.08 / -0.07 / +0.10 | -0.51 / -0.53 / -0.61 | hayır |
| cvd_up | 54% | 11035 | 22.7% | 23.2% | -0.56 | -0.57 | +0.18 | -0.03 [t -0.6] | -0.16 / +0.18 / -0.11 | -0.56 / -0.45 / -0.66 | hayır |
| cvd_up_15m | 52% | 10617 | 23.6% | 22.2% | -0.52 | -0.61 | +0.23 | +0.08 [t +1.6] | +0.04 / +0.16 / +0.03 | -0.49 / -0.46 / -0.60 | hayır |
| ichimoku_above_cloud | 71% | 14484 | 23.6% | 21.2% | -0.56 | -0.58 | +0.18 | -0.04 [t -0.7] | -0.00 / -0.04 / -0.05 | -0.52 / -0.50 / -0.63 | hayır |
| ichimoku_above_cloud_15m | 75% | 15231 | 24.1% | 19.5% | -0.55 | -0.59 | +0.19 | -0.01 [t -0.2] | +0.13 / -0.11 / -0.02 | -0.49 / -0.53 / -0.62 | hayır |
| in_bull_fvg_tap | 16% | 3313 | 21.9% | 23.1% | -0.54 | -0.56 | +0.19 | -0.01 [t -0.2] | +0.02 / -0.10 / +0.02 | -0.49 / -0.58 / -0.56 | hayır |
| in_bull_order_block_tap | 7% | 1450 | 24.7% | 22.8% | -0.50 | -0.57 | +0.29 | +0.11 [t +1.6] | +0.14 / +0.11 / +0.03 | -0.51 / -0.35 / -0.62 | hayır |
| ms_bullish | 74% | 15058 | 23.1% | 22.5% | -0.58 | -0.51 | +0.16 | -0.12 [t -2.4] | -0.10 / -0.09 / -0.16 | -0.55 / -0.52 / -0.65 | hayır |
| ms_bullish_15m | 76% | 15502 | 23.7% | 20.5% | -0.57 | -0.53 | +0.17 | -0.11 [t -2.1] | -0.07 / -0.15 / -0.09 | -0.54 / -0.53 / -0.64 | hayır |
| no_equal_highs_in_target | 98% | 19846 | 22.9% | 22.4% | -0.57 | -0.36 | +0.19 | -0.22 [t -1.6] | -0.34 / -0.09 / -0.20 | -0.55 / -0.52 / -0.63 | hayır |
| no_equal_highs_in_target_15m | 98% | 19923 | 23.1% | 14.6% | -0.56 | -0.65 | +0.20 | +0.19 [t +1.7] | +0.19 / +0.17 / +0.24 | -0.54 / -0.51 / -0.62 | hayır |
| no_swing_high_in_target | 73% | 14764 | 22.9% | 22.9% | -0.60 | -0.45 | +0.13 | -0.22 [t -4.5] | -0.33 / -0.13 / -0.20 | -0.60 / -0.54 / -0.66 | hayır |
| no_swing_high_in_target_15m | 71% | 14497 | 24.4% | 19.3% | -0.60 | -0.48 | +0.17 | -0.08 [t -1.7] | +0.05 / -0.26 / -0.04 | -0.55 / -0.58 / -0.66 | hayır |
| obv_up | 65% | 13228 | 22.7% | 23.4% | -0.59 | -0.51 | +0.15 | -0.13 [t -2.9] | -0.07 / -0.11 / -0.21 | -0.54 / -0.54 / -0.68 | hayır |
| obv_up_15m | 68% | 13822 | 23.8% | 21.0% | -0.56 | -0.57 | +0.18 | -0.03 [t -0.7] | +0.00 / -0.09 / -0.00 | -0.52 / -0.52 / -0.63 | hayır |
| supertrend_all_green | 56% | 11335 | 21.2% | 25.1% | -0.58 | -0.53 | +0.14 | -0.12 [t -2.5] | -0.19 / -0.01 / -0.14 | -0.59 / -0.51 / -0.65 | hayır |
| supertrend_all_green_15m | 50% | 10110 | 23.3% | 22.5% | -0.56 | -0.56 | +0.16 | -0.06 [t -1.3] | -0.02 / -0.07 / -0.10 | -0.51 / -0.52 / -0.66 | hayır |


ATR tersilleri içinde klasik fikirler (kapsam: tümü; oynaklık etkisi ayrıştırılmış):

| fikir (tutulan − düşen) | Δhit pp: ATR tersil 1 / 2 / 3 | Δ(net−taban): tersil 1 / 2 / 3 | n tutulan/düşen |
|---|---|---|---|
| above_avwap | +2.4 / +2.7 / +7.1 | -0.01 / +0.07 / +0.07 | 5831/950 / 5459/1322 / 5147/1628 |
| above_avwap_15m | +3.1 / +3.2 / +7.3 | +0.01 / +0.07 / +0.09 | 5647/1134 / 5268/1513 / 5049/1726 |
| above_poc | +2.8 / +2.6 / +4.0 | +0.04 / +0.07 / +0.07 | 4643/2138 / 4256/2525 / 4036/2739 |
| above_poc_15m | +2.2 / +3.3 / +5.9 | +0.04 / +0.08 / +0.06 | 4534/2247 / 4048/2733 / 3813/2962 |
| above_vwap | +3.5 / +3.6 / +5.0 | -0.06 / +0.10 / -0.08 | 5513/1268 / 5021/1760 / 4595/2186 |
| above_vwap_15m | +3.5 / +4.6 / +6.1 | -0.00 / +0.11 / -0.05 | 5332/1449 / 4771/2010 / 4447/2334 |
| adx25_di_up | +1.5 / +4.1 / +1.6 | -0.05 / +0.07 / -0.37 | 3318/3463 / 3177/3604 / 3235/3545 |
| adx25_di_up_15m | +3.5 / +3.1 / +3.4 | +0.05 / +0.11 / -0.24 | 3068/3713 / 3639/3142 / 4430/2349 |
| after_sweep_12bar | +0.3 / -2.9 / -0.9 | +0.02 / -0.06 / +0.12 | 692/6089 / 1116/5665 / 1236/5545 |
| after_sweep_3bar | -2.6 / -5.0 / -1.4 | +0.01 / -0.10 / +0.18 | 119/6662 / 229/6552 / 300/6481 |
| bull_fvg_open | +5.9 / +3.7 / +2.4 | -0.06 / -0.04 / -0.19 | 6177/604 / 5814/967 / 5101/1679 |
| bull_order_block_active | +3.4 / +3.5 / +3.7 | +0.07 / +0.07 / -0.18 | 5322/1459 / 5214/1567 / 4968/1812 |
| chop_trending | -0.8 / +3.9 / +0.2 | -0.11 / +0.05 / -0.10 | 4775/2006 / 2497/4284 / 1525/5256 |
| chop_trending_15m | +0.4 / +3.1 / +1.4 | -0.08 / +0.06 / -0.21 | 2500/4278 / 1928/4853 / 1897/4883 |
| cmf_pos | +2.3 / +2.8 / +3.7 | -0.07 / -0.01 / +0.05 | 4356/2425 / 4013/2768 / 3955/2825 |
| cmf_pos_15m | +1.6 / +0.7 / +5.9 | -0.03 / -0.00 / +0.11 | 4215/2566 / 4059/2722 / 4322/2457 |
| cvd_up | +1.2 / +2.2 / +4.2 | +0.02 / +0.02 / -0.04 | 4278/2503 / 3749/3032 / 3008/3773 |
| cvd_up_15m | +1.3 / +3.3 / +4.2 | +0.07 / +0.18 / +0.03 | 3962/2819 / 3422/3359 / 3233/3547 |
| ichimoku_above_cloud | +4.5 / +4.7 / +4.7 | -0.04 / +0.12 / -0.12 | 5288/1493 / 4705/2076 / 4491/2288 |
| ichimoku_above_cloud_15m | +2.7 / +2.7 / +6.2 | +0.02 / +0.06 / -0.14 | 5044/1737 / 4923/1858 / 5264/1512 |
| in_bull_fvg_tap | -2.1 / +0.6 / +2.9 | -0.03 / +0.03 / +0.04 | 1333/5448 / 1031/5750 / 949/5831 |
| in_bull_order_block_tap | -1.7 / -2.2 / +0.3 | +0.05 / +0.12 / +0.06 | 299/6482 / 509/6272 / 642/6138 |
| ms_bullish | +5.0 / +5.0 / +3.6 | -0.15 / -0.00 / -0.12 | 5661/1120 / 4989/1792 / 4408/2372 |
| ms_bullish_15m | +1.7 / +2.8 / +4.1 | -0.11 / -0.03 / -0.20 | 5222/1559 / 5019/1762 / 5261/1518 |
| no_equal_highs_in_target | +5.0 / -0.3 / -0.9 | +0.12 / -0.09 / -0.62 | 6639/142 / 6595/186 / 6612/168 |
| no_equal_highs_in_target_15m | +3.4 / +5.6 / +5.3 | +0.21 / +0.16 / -0.01 | 6578/203 / 6631/150 / 6714/65 |
| no_swing_high_in_target | +2.9 / +2.2 / +1.8 | -0.20 / -0.10 / -0.29 | 5479/1302 / 4663/2118 / 4622/2158 |
| no_swing_high_in_target_15m | +0.6 / +1.5 / +2.5 | -0.08 / -0.09 / -0.23 | 4377/2404 / 4519/2262 / 5601/1178 |
| obv_up | +2.8 / +3.9 / +2.3 | -0.10 / -0.04 / -0.16 | 5089/1692 / 4451/2330 / 3688/3093 |
| obv_up_15m | +2.4 / +4.4 / +2.5 | -0.01 / +0.09 / -0.16 | 4737/2044 / 4490/2291 / 4595/2185 |
| supertrend_all_green | +2.0 / +2.4 / +3.4 | -0.09 / +0.01 / -0.13 | 5084/1697 / 3808/2973 / 2443/4337 |
| supertrend_all_green_15m | +2.7 / +4.8 / +4.4 | -0.03 / +0.08 / -0.16 | 4124/2657 / 3246/3535 / 2740/4038 |


#### A3. Filtre kuralları — seçim: B1 (20 Tem–18 Ağu); sonra DOKUNULMADAN: B2 (19 Ağu–17 Eyl), B3 (18 Eyl–16 Eki)

Seçim dönemi: n=6110, aday kural 2194 (özellik × yön × 3 eşik). Hedef işlevi: (a) net−taban [oynaklık kontrollü], (b) ham net. Her hedef için en iyi 3 FARKLI özellik (Jaccard ≤ 0,7).

- A1: `15m.avwap_dist > 3.553` — seçim dönemi t=2.9, n=2037, ort.=+0.56
- A2: `15m.ema20_50 > 1.813` — seçim dönemi t=2.9, n=2037, ort.=+0.62
- A3: `res:swing_5m <= 4.965` — seçim dönemi t=2.8, n=2037, ort.=+0.53
- N1: `5m.hv20 <= 1.061` — seçim dönemi t=2.4, n=4073, ort.=-0.47
- N2: `ex:velocity_score <= 1762` — seçim dönemi t=2.4, n=3055, ort.=-0.46
- N3: `5m.lsma_se_pct <= 0.6854` — seçim dönemi t=2.3, n=2037, ort.=-0.43

Kapsam: tümü

| kural | dilim | n | gün/adet | hit | hit (hepsi) | net | net (hepsi) | net−taban | Δ(net−taban) vs hepsi [95] | ATR% (tutulan/hepsi) |
|---|---|---|---|---|---|---|---|---|---|---|
| A1: 15m.avwap_dist > 3.553 | B1 (20 Tem–18 Ağu) | 2037 | 67.9 | 34.6% | 25.2% | -0.40 | -0.54 | +0.56 | +0.23 [+0.11; +0.35] | 1.79 / 1.36 |
| A1: 15m.avwap_dist > 3.553 | B2 (19 Ağu–17 Eyl) | 2665 | 88.8 | 27.0% | 21.3% | -0.46 | -0.51 | +0.18 | +0.08 [-0.06; +0.21] | 1.33 / 1.16 |
| A1: 15m.avwap_dist > 3.553 | B3 (18 Eyl–16 Eki) | 2988 | 103.0 | 26.2% | 22.5% | -0.67 | -0.62 | +0.17 | +0.00 [-0.12; +0.13] | 1.40 / 1.21 |
| A1: 15m.avwap_dist > 3.553 | OOS (seçim dışı tümü) | 5653 | 95.8 | 26.6% | 21.9% | -0.57 | -0.57 | +0.17 | +0.04 [-0.05; +0.13] | 1.37 / 1.19 |
| A2: 15m.ema20_50 > 1.813 | B1 (20 Tem–18 Ağu) | 2037 | 67.9 | 37.7% | 25.2% | -0.43 | -0.54 | +0.62 | +0.29 [+0.13; +0.44] | 2.10 / 1.36 |
| A2: 15m.ema20_50 > 1.813 | B2 (19 Ağu–17 Eyl) | 2446 | 81.5 | 29.2% | 21.3% | -0.51 | -0.51 | +0.09 | -0.01 [-0.17; +0.15] | 1.65 / 1.16 |
| A2: 15m.ema20_50 > 1.813 | B3 (18 Eyl–16 Eki) | 2861 | 98.7 | 28.7% | 22.5% | -0.62 | -0.62 | +0.25 | +0.09 [-0.04; +0.21] | 1.70 / 1.21 |
| A2: 15m.ema20_50 > 1.813 | OOS (seçim dışı tümü) | 5307 | 89.9 | 29.0% | 21.9% | -0.57 | -0.57 | +0.18 | +0.04 [-0.06; +0.14] | 1.68 / 1.19 |
| A3: res:swing_5m <= 4.965 | B1 (20 Tem–18 Ağu) | 2037 | 67.9 | 26.3% | 25.2% | -0.44 | -0.54 | +0.53 | +0.20 [+0.08; +0.32] | 1.45 / 1.36 |
| A3: res:swing_5m <= 4.965 | B2 (19 Ağu–17 Eyl) | 2202 | 73.4 | 22.0% | 21.3% | -0.47 | -0.51 | +0.18 | +0.08 [-0.02; +0.18] | 1.25 / 1.16 |
| A3: res:swing_5m <= 4.965 | B3 (18 Eyl–16 Eki) | 2588 | 89.2 | 22.5% | 22.5% | -0.53 | -0.62 | +0.30 | +0.13 [+0.02; +0.25] | 1.27 / 1.21 |
| A3: res:swing_5m <= 4.965 | OOS (seçim dışı tümü) | 4790 | 81.2 | 22.3% | 21.9% | -0.50 | -0.57 | +0.25 | +0.11 [+0.03; +0.19] | 1.26 / 1.19 |
| N1: 5m.hv20 <= 1.061 | B1 (20 Tem–18 Ağu) | 4073 | 135.8 | 18.4% | 25.2% | -0.47 | -0.54 | +0.29 | -0.04 [-0.09; +0.01] | 0.82 / 1.36 |
| N1: 5m.hv20 <= 1.061 | B2 (19 Ağu–17 Eyl) | 5217 | 173.9 | 17.3% | 21.3% | -0.49 | -0.51 | +0.14 | +0.04 [-0.04; +0.11] | 0.84 / 1.16 |
| N1: 5m.hv20 <= 1.061 | B3 (18 Eyl–16 Eki) | 5488 | 189.2 | 17.7% | 22.5% | -0.60 | -0.62 | +0.12 | -0.04 [-0.13; +0.04] | 0.84 / 1.21 |
| N1: 5m.hv20 <= 1.061 | OOS (seçim dışı tümü) | 10705 | 181.4 | 17.5% | 21.9% | -0.54 | -0.57 | +0.13 | -0.01 [-0.06; +0.05] | 0.84 / 1.19 |
| N2: ex:velocity_score <= 1762 | B1 (20 Tem–18 Ağu) | 3055 | 101.8 | 21.0% | 25.2% | -0.46 | -0.54 | +0.35 | +0.02 [-0.05; +0.10] | 1.00 / 1.36 |
| N2: ex:velocity_score <= 1762 | B2 (19 Ağu–17 Eyl) | 3560 | 118.7 | 18.0% | 21.3% | -0.54 | -0.51 | +0.08 | -0.03 [-0.12; +0.06] | 0.94 / 1.16 |
| N2: ex:velocity_score <= 1762 | B3 (18 Eyl–16 Eki) | 3739 | 128.9 | 18.9% | 22.5% | -0.58 | -0.62 | +0.14 | -0.02 [-0.11; +0.06] | 0.96 / 1.21 |
| N2: ex:velocity_score <= 1762 | OOS (seçim dışı tümü) | 7299 | 123.7 | 18.5% | 21.9% | -0.56 | -0.57 | +0.11 | -0.03 [-0.09; +0.04] | 0.95 / 1.19 |
| N3: 5m.lsma_se_pct <= 0.6854 | B1 (20 Tem–18 Ağu) | 2037 | 67.9 | 15.7% | 25.2% | -0.43 | -0.54 | +0.28 | -0.05 [-0.14; +0.03] | 0.66 / 1.36 |
| N3: 5m.lsma_se_pct <= 0.6854 | B2 (19 Ağu–17 Eyl) | 2495 | 83.2 | 14.4% | 21.3% | -0.51 | -0.51 | +0.07 | -0.03 [-0.12; +0.05] | 0.67 / 1.16 |
| N3: 5m.lsma_se_pct <= 0.6854 | B3 (18 Eyl–16 Eki) | 2418 | 83.4 | 14.6% | 22.5% | -0.59 | -0.62 | +0.08 | -0.09 [-0.20; +0.03] | 0.66 / 1.21 |
| N3: 5m.lsma_se_pct <= 0.6854 | OOS (seçim dışı tümü) | 4913 | 83.3 | 14.5% | 21.9% | -0.55 | -0.57 | +0.07 | -0.06 [-0.13; +0.01] | 0.67 / 1.19 |


**Aşırı uyum tanısı** (seçim döneminde en iyi 50 aday kuralın seçim dışı performansı; hepsi aynı yönde sistematik bir kenar olsaydı OOS ortalaması > 0 olurdu):

| hedef | aday | OOS: en iyi-50 ort. Δ | en iyi-50 pozitif pay | tüm adaylar ort. Δ | tüm adaylar pozitif pay |
|---|---|---|---|---|---|
| net−taban | 2009 | +0.03 | 82.0% | -0.00 | 50.0% |
| ham net | 2009 | +0.01 | 68.0% | -0.00 | 50.2% |


## 4. B — Hedef boyutlandırma çalışması

### Nüfus 2 — push bildirimleri
Eğitim: seçim 17.09–09.10 (n=1522); test: değerlendirme 10.10–17.10.

#### B1. MFE / MAE öngörücüleri — kapsam: tümü (n=2007)

Anlamlı (BH q<0,05) özellik sayısı — ham vs ATR-kontrollü:

| sonuç | özellik | ham | ATR-kontrollü |
|---|---|---|---|
| MFE60 | 419 | 212 | 115 |
| MFE60/ATR | 419 | 181 | 117 |
| MAE60 | 419 | 249 | 182 |
| MAE60/ATR | 419 | 194 | 198 |

Referans: ATR'nin kendisi ile Spearman(ATR, MFE60) = +0.388 [t +18.3]; Spearman(ATR, MAE60 mutlak) = +0.541 [t +23.2].

En iyi 15 özellik — MFE60 (ATR-kontrollü):

| özellik | ham r(MFE) [t] | ATR-kont. r(MFE) [t] | q | blok işaret uyumu | ATR-kont. r(MFE/ATR) [t] | ATR-kont. r(MAE mutlak) [t] | q(MAE) |
|---|---|---|---|---|---|---|---|
| ex:pump30 | +0.339 [+11.3] | +0.173 [+7.5] | 0.000 | 2/2 | +0.170 [+8.0] | +0.177 [+8.7] | 0.000 |
| 5m.px_dema | +0.290 [+9.4] | +0.150 [+6.8] | 0.000 | 2/2 | +0.146 [+6.8] | +0.147 [+6.4] | 0.000 |
| 5m.pvt_slope12 | +0.296 [+9.5] | +0.142 [+6.8] | 0.000 | 2/2 | +0.138 [+7.4] | +0.111 [+4.7] | 0.000 |
| 5m.vi_minus | -0.018 [-0.9] | -0.121 [-6.7] | 0.000 | 2/2 | -0.118 [-7.2] | -0.111 [-4.7] | 0.000 |
| res:swing_5m | +0.037 [+1.8] | +0.101 [+6.6] | 0.000 | 2/2 | +0.091 [+5.9] | +0.082 [+3.5] | 0.005 |
| 5m.px_ema7 | +0.322 [+10.5] | +0.142 [+6.6] | 0.000 | 2/2 | +0.136 [+6.6] | +0.158 [+6.9] | 0.000 |
| 5m.cmf20_chg5 | +0.061 [+2.8] | +0.120 [+6.5] | 0.000 | 2/2 | +0.121 [+6.7] | +0.066 [+3.6] | 0.004 |
| idea:no_swing_high_in_target | +0.090 [+4.4] | +0.102 [+6.3] | 0.000 | 2/2 | +0.084 [+4.7] | +0.059 [+2.5] | 0.044 |
| 5m.px_wma | +0.333 [+10.7] | +0.136 [+6.2] | 0.000 | 2/2 | +0.135 [+6.2] | +0.165 [+7.6] | 0.000 |
| 5m.max_candle12 | +0.385 [+16.2] | +0.115 [+6.2] | 0.000 | 2/2 | +0.109 [+6.6] | +0.072 [+2.9] | 0.020 |
| 5m.bb_pctb | +0.056 [+2.5] | +0.134 [+6.2] | 0.000 | 2/2 | +0.130 [+6.0] | +0.168 [+6.9] | 0.000 |
| idea:chop_trending | +0.013 [+0.8] | +0.099 [+6.0] | 0.000 | 2/2 | +0.094 [+5.9] | +0.081 [+3.8] | 0.002 |
| 5m.disp_up_cnt5 | +0.099 [+4.2] | +0.130 [+5.9] | 0.000 | 2/2 | +0.131 [+6.4] | +0.099 [+3.6] | 0.004 |
| 5m.cci20 | +0.060 [+2.5] | +0.125 [+5.9] | 0.000 | 2/2 | +0.126 [+6.0] | +0.167 [+7.4] | 0.000 |
| 5m.px_kama | +0.306 [+11.1] | +0.121 [+5.9] | 0.000 | 2/2 | +0.118 [+5.6] | +0.109 [+5.4] | 0.000 |

En iyi 15 özellik — MFE60 (ham):

| özellik | ham r(MFE) [t] | ATR-kont. r(MFE) [t] | q | blok işaret uyumu | ATR-kont. r(MFE/ATR) [t] | ATR-kont. r(MAE mutlak) [t] | q(MAE) |
|---|---|---|---|---|---|---|---|
| 5m.atr14_pct | +0.388 [+18.3] | +0.002 [+0.1] | 0.936 | 1/2 | +0.003 [+0.2] | -0.009 [-0.6] | 0.648 |
| ex:atr | +0.388 [+18.3] | +0.002 [+0.1] | 0.936 | 1/2 | +0.003 [+0.2] | -0.009 [-0.6] | 0.648 |
| 5m.kc_width | +0.400 [+17.7] | +0.109 [+4.9] | 0.000 | 2/2 | +0.106 [+5.3] | +0.107 [+4.7] | 0.000 |
| 5m.donch_width20 | +0.390 [+16.3] | +0.086 [+3.8] | 0.004 | 2/2 | +0.088 [+3.9] | +0.095 [+3.9] | 0.002 |
| 5m.hv20 | +0.390 [+16.2] | +0.079 [+3.4] | 0.010 | 2/2 | +0.076 [+3.3] | +0.017 [+0.8] | 0.571 |
| 5m.max_candle12 | +0.385 [+16.2] | +0.115 [+6.2] | 0.000 | 2/2 | +0.109 [+6.6] | +0.072 [+2.9] | 0.020 |
| 15m.hv20 | +0.366 [+16.1] | +0.054 [+2.6] | 0.050 | 2/2 | +0.050 [+2.5] | +0.025 [+1.3] | 0.319 |
| 5m.bb_width_pct | +0.374 [+15.8] | +0.072 [+3.2] | 0.014 | 2/2 | +0.071 [+3.3] | +0.068 [+3.0] | 0.016 |
| 15m.lsma_se_pct | +0.356 [+15.4] | +0.035 [+1.4] | 0.344 | 2/2 | +0.030 [+1.2] | -0.004 [-0.2] | 0.887 |
| 5m.qv24_log10 | +0.235 [+15.3] | +0.015 [+0.9] | 0.591 | 2/2 | +0.020 [+1.2] | -0.050 [-1.7] | 0.176 |
| 15m.qv24_log10 | +0.228 [+15.2] | +0.014 [+0.8] | 0.613 | 2/2 | +0.018 [+1.1] | -0.057 [-2.0] | 0.110 |
| 5m.lsma_se_pct | +0.381 [+15.1] | +0.080 [+3.5] | 0.008 | 2/2 | +0.080 [+3.6] | +0.059 [+2.4] | 0.049 |
| 15m.atr14_pct | +0.362 [+15.0] | +0.029 [+1.2] | 0.409 | 2/2 | +0.030 [+1.3] | -0.023 [-0.9] | 0.498 |
| 5m.ms_dist_sl | +0.361 [+14.6] | +0.109 [+5.2] | 0.000 | 2/2 | +0.109 [+5.3] | +0.136 [+6.0] | 0.000 |
| 15m.kc_width | +0.368 [+14.3] | +0.018 [+0.8] | 0.598 | 1/2 | +0.016 [+0.8] | -0.010 [-0.4] | 0.754 |

En iyi 15 özellik — MAE60 mutlak (ATR-kontrollü):

| özellik | ham r(MFE) [t] | ATR-kont. r(MFE) [t] | q | blok işaret uyumu | ATR-kont. r(MFE/ATR) [t] | ATR-kont. r(MAE mutlak) [t] | q(MAE) |
|---|---|---|---|---|---|---|---|
| ex:pump30 | +0.339 [+11.3] | +0.173 [+7.5] | 0.000 | 2/2 | +0.170 [+8.0] | +0.177 [+8.7] | 0.000 |
| 5m.drawdown12_pct | +0.253 [+9.4] | -0.051 [-2.1] | 0.129 | 2/2 | -0.051 [-2.1] | -0.139 [-8.4] | 0.000 |
| 5m.px_ema20 | +0.339 [+10.5] | +0.121 [+5.0] | 0.000 | 2/2 | +0.116 [+4.8] | +0.162 [+7.8] | 0.000 |
| 5m.tk_qratio | +0.038 [+2.2] | +0.064 [+3.5] | 0.007 | 2/2 | +0.068 [+3.7] | +0.143 [+7.8] | 0.000 |
| 5m.px_ema50 | +0.326 [+8.9] | +0.081 [+2.8] | 0.039 | 2/2 | +0.075 [+2.6] | +0.144 [+7.6] | 0.000 |
| 5m.px_wma | +0.333 [+10.7] | +0.136 [+6.2] | 0.000 | 2/2 | +0.135 [+6.2] | +0.165 [+7.6] | 0.000 |
| 5m.px_mcg | +0.352 [+11.2] | +0.109 [+4.2] | 0.002 | 2/2 | +0.102 [+4.1] | +0.157 [+7.6] | 0.000 |
| 5m.cci20 | +0.060 [+2.5] | +0.125 [+5.9] | 0.000 | 2/2 | +0.126 [+6.0] | +0.167 [+7.4] | 0.000 |
| dyn:emp50 | -0.029 [-0.8] | -0.017 [-0.6] | 0.706 | 1/2 | -0.016 [-0.6] | -0.128 [-7.1] | 0.000 |
| 5m.ret5 | +0.306 [+8.9] | +0.136 [+5.3] | 0.000 | 2/2 | +0.128 [+5.6] | +0.157 [+7.1] | 0.000 |
| 5m.psar_dist | +0.282 [+7.7] | +0.095 [+3.4] | 0.010 | 2/2 | +0.097 [+3.8] | +0.151 [+7.1] | 0.000 |
| 5m.slope_kama | +0.225 [+7.2] | +0.123 [+5.0] | 0.000 | 2/2 | +0.123 [+5.5] | +0.148 [+7.0] | 0.000 |
| 5m.px_ema7 | +0.322 [+10.5] | +0.142 [+6.6] | 0.000 | 2/2 | +0.136 [+6.6] | +0.158 [+6.9] | 0.000 |
| 5m.bb_pctb | +0.056 [+2.5] | +0.134 [+6.2] | 0.000 | 2/2 | +0.130 [+6.0] | +0.168 [+6.9] | 0.000 |
| 5m.ema7_slope3 | +0.318 [+9.2] | +0.131 [+5.1] | 0.000 | 2/2 | +0.129 [+5.3] | +0.157 [+6.9] | 0.000 |


#### B1. MFE / MAE öngörücüleri — kapsam: teyit kuralı (yeni canlı) (n=416)

Anlamlı (BH q<0,05) özellik sayısı — ham vs ATR-kontrollü:

| sonuç | özellik | ham | ATR-kontrollü |
|---|---|---|---|
| MFE60 | 398 | 42 | 0 |
| MFE60/ATR | 398 | 28 | 0 |
| MAE60 | 398 | 183 | 113 |
| MAE60/ATR | 398 | 105 | 122 |

Referans: ATR'nin kendisi ile Spearman(ATR, MFE60) = +0.192 [t +4.9]; Spearman(ATR, MAE60 mutlak) = +0.336 [t +8.1].

En iyi 15 özellik — MFE60 (ATR-kontrollü):

| özellik | ham r(MFE) [t] | ATR-kont. r(MFE) [t] | q | blok işaret uyumu | ATR-kont. r(MFE/ATR) [t] | ATR-kont. r(MAE mutlak) [t] | q(MAE) |
|---|---|---|---|---|---|---|---|
| 5m.rvi_sig_diff | +0.082 [+2.0] | +0.161 [+4.2] | 0.055 | 2/2 | +0.162 [+4.0] | +0.060 [+1.5] | 0.291 |
| ex:score | +0.233 [+4.8] | +0.198 [+4.1] | 0.055 | 2/2 | +0.196 [+4.0] | +0.065 [+1.6] | 0.239 |
| ex:pump30 | +0.217 [+4.7] | +0.190 [+4.0] | 0.055 | 2/2 | +0.184 [+3.9] | +0.229 [+5.3] | 0.000 |
| 5m.bb_pctb | +0.067 [+1.5] | +0.155 [+3.7] | 0.080 | 2/2 | +0.161 [+4.0] | +0.254 [+6.7] | 0.000 |
| 5m.cci20 | +0.070 [+1.5] | +0.161 [+3.6] | 0.080 | 2/2 | +0.164 [+3.6] | +0.206 [+5.5] | 0.000 |
| 5m.lsma_z | +0.080 [+1.5] | +0.174 [+3.5] | 0.080 | 2/2 | +0.178 [+3.8] | +0.253 [+7.4] | 0.000 |
| 5m.px_kama | +0.167 [+4.6] | +0.130 [+3.5] | 0.080 | 2/2 | +0.126 [+3.6] | +0.199 [+6.2] | 0.000 |
| res:swing_5m | +0.096 [+2.4] | +0.135 [+3.5] | 0.080 | 2/2 | +0.135 [+3.4] | +0.107 [+2.4] | 0.069 |
| 5m.smi_sig_diff | +0.067 [+1.2] | +0.166 [+3.4] | 0.080 | 2/2 | +0.169 [+3.4] | +0.191 [+5.1] | 0.000 |
| 5m.ao_chg | +0.151 [+2.9] | +0.166 [+3.4] | 0.080 | 2/2 | +0.157 [+3.2] | +0.157 [+3.8] | 0.005 |
| 5m.dist_low24_pct | +0.249 [+5.4] | +0.167 [+3.3] | 0.086 | 2/2 | +0.153 [+3.0] | +0.043 [+0.7] | 0.617 |
| 5m.chop_drop12 | -0.069 [-1.4] | -0.152 [-3.3] | 0.096 | 2/2 | -0.147 [-3.1] | -0.124 [-2.5] | 0.059 |
| 5m.ms_dist_sh | +0.099 [+2.9] | +0.122 [+3.2] | 0.101 | 2/2 | +0.119 [+3.3] | +0.205 [+4.3] | 0.002 |
| 5m.px_dema | +0.153 [+3.0] | +0.148 [+3.2] | 0.105 | 2/2 | +0.148 [+3.3] | +0.243 [+5.8] | 0.000 |
| 5m.macd_hist_pct | +0.137 [+3.6] | +0.115 [+3.1] | 0.108 | 2/2 | +0.124 [+3.1] | +0.125 [+2.6] | 0.048 |

En iyi 15 özellik — MFE60 (ham):

| özellik | ham r(MFE) [t] | ATR-kont. r(MFE) [t] | q | blok işaret uyumu | ATR-kont. r(MFE/ATR) [t] | ATR-kont. r(MAE mutlak) [t] | q(MAE) |
|---|---|---|---|---|---|---|---|
| 5m.hv20 | +0.236 [+5.6] | +0.142 [+3.0] | 0.125 | 2/2 | +0.133 [+2.8] | +0.030 [+0.7] | 0.665 |
| 5m.kc_width | +0.220 [+5.4] | +0.120 [+2.4] | 0.181 | 1/2 | +0.124 [+2.6] | +0.106 [+2.2] | 0.089 |
| 5m.dist_low24_pct | +0.249 [+5.4] | +0.167 [+3.3] | 0.086 | 2/2 | +0.153 [+3.0] | +0.043 [+0.7] | 0.617 |
| 5m.atr14_pct | +0.192 [+4.9] | -0.021 [-0.3] | 0.929 | 0/2 | -0.009 [-0.1] | -0.003 [-0.0] | 0.983 |
| ex:atr | +0.192 [+4.9] | -0.021 [-0.3] | 0.929 | 0/2 | -0.009 [-0.1] | -0.003 [-0.0] | 0.983 |
| ex:score | +0.233 [+4.8] | +0.198 [+4.1] | 0.055 | 2/2 | +0.196 [+4.0] | +0.065 [+1.6] | 0.239 |
| 5m.lsma_se_pct | +0.201 [+4.8] | +0.083 [+1.3] | 0.609 | 2/2 | +0.068 [+1.1] | +0.068 [+1.8] | 0.183 |
| 15m.dist_low24_pct | +0.236 [+4.8] | +0.149 [+2.8] | 0.146 | 2/2 | +0.135 [+2.5] | -0.009 [-0.2] | 0.938 |
| ex:pump30 | +0.217 [+4.7] | +0.190 [+4.0] | 0.055 | 2/2 | +0.184 [+3.9] | +0.229 [+5.3] | 0.000 |
| 5m.donch_width20 | +0.220 [+4.7] | +0.108 [+1.8] | 0.410 | 1/2 | +0.105 [+1.6] | +0.155 [+3.3] | 0.013 |
| 5m.px_kama | +0.167 [+4.6] | +0.130 [+3.5] | 0.080 | 2/2 | +0.126 [+3.6] | +0.199 [+6.2] | 0.000 |
| 15m.atr14_pct | +0.208 [+4.6] | +0.093 [+1.7] | 0.410 | 2/2 | +0.083 [+1.6] | -0.052 [-1.2] | 0.383 |
| 15m.hv20 | +0.226 [+4.5] | +0.124 [+2.2] | 0.242 | 2/2 | +0.114 [+2.0] | +0.021 [+0.5] | 0.767 |
| 5m.max_candle12 | +0.204 [+4.5] | +0.121 [+2.3] | 0.211 | 2/2 | +0.123 [+2.3] | +0.108 [+2.4] | 0.075 |
| 15m.kc_width | +0.203 [+4.3] | +0.072 [+1.1] | 0.699 | 2/2 | +0.062 [+1.0] | +0.002 [+0.0] | 0.980 |

En iyi 15 özellik — MAE60 mutlak (ATR-kontrollü):

| özellik | ham r(MFE) [t] | ATR-kont. r(MFE) [t] | q | blok işaret uyumu | ATR-kont. r(MFE/ATR) [t] | ATR-kont. r(MAE mutlak) [t] | q(MAE) |
|---|---|---|---|---|---|---|---|
| 5m.px_alma | +0.133 [+2.7] | +0.110 [+2.2] | 0.242 | 2/2 | +0.107 [+2.2] | +0.291 [+8.2] | 0.000 |
| 5m.macd_hist_slope | +0.114 [+1.9] | +0.122 [+2.2] | 0.242 | 2/2 | +0.120 [+2.3] | +0.252 [+7.7] | 0.000 |
| 5m.lsma_px | +0.143 [+2.5] | +0.160 [+3.1] | 0.108 | 2/2 | +0.159 [+3.2] | +0.246 [+7.5] | 0.000 |
| 5m.lsma_z | +0.080 [+1.5] | +0.174 [+3.5] | 0.080 | 2/2 | +0.178 [+3.8] | +0.253 [+7.4] | 0.000 |
| 5m.px_tema | +0.137 [+2.2] | +0.154 [+2.8] | 0.146 | 2/2 | +0.153 [+2.9] | +0.247 [+7.4] | 0.000 |
| 5m.px_hma | +0.147 [+2.8] | +0.151 [+2.9] | 0.131 | 2/2 | +0.149 [+3.0] | +0.248 [+7.4] | 0.000 |
| 5m.px_ema7 | +0.162 [+3.5] | +0.129 [+2.8] | 0.146 | 2/2 | +0.126 [+2.8] | +0.282 [+7.1] | 0.000 |
| 5m.bb_pctb | +0.067 [+1.5] | +0.155 [+3.7] | 0.080 | 2/2 | +0.161 [+4.0] | +0.254 [+6.7] | 0.000 |
| 5m.donch_break20 | +0.046 [+1.0] | +0.082 [+1.9] | 0.341 | 2/2 | +0.089 [+1.9] | +0.218 [+6.6] | 0.000 |
| 5m.px_kama | +0.167 [+4.6] | +0.130 [+3.5] | 0.080 | 2/2 | +0.126 [+3.6] | +0.199 [+6.2] | 0.000 |
| 5m.crsi | +0.007 [+0.2] | +0.044 [+0.9] | 0.806 | 2/2 | +0.043 [+0.9] | +0.282 [+6.0] | 0.000 |
| 5m.disp_body_atr | +0.023 [+0.5] | +0.064 [+1.4] | 0.555 | 2/2 | +0.071 [+1.6] | +0.241 [+5.9] | 0.000 |
| 5m.ret1 | +0.056 [+1.2] | +0.049 [+1.1] | 0.740 | 2/2 | +0.052 [+1.2] | +0.254 [+5.9] | 0.000 |
| 5m.px_dema | +0.153 [+3.0] | +0.148 [+3.2] | 0.105 | 2/2 | +0.148 [+3.3] | +0.243 [+5.8] | 0.000 |
| 5m.cci20 | +0.070 [+1.5] | +0.161 [+3.6] | 0.080 | 2/2 | +0.164 [+3.6] | +0.206 [+5.5] | 0.000 |


#### B2. Hedef modelleri

- Seçim ölçütü `net` (yalnız eğitim bloğu seçim 17.09–09.10): ATR k=0.25; direnç=('res:h60', 0.7, 0.25); ampirik=dyn:emp60; QR özellikleri=['ex:pump30', 'idea:chop_trending', '5m.pvt_slope12', '5m.ms_dist_sh', '5m.chop14'], q=0.4; GBM q=0.5
- Seçim ölçütü `excess` (yalnız eğitim bloğu seçim 17.09–09.10): ATR k=1.2; direnç=('res:h24', 0.7, 4.8); ampirik=dyn:emp60; QR özellikleri=['ex:pump30', 'idea:chop_trending', '5m.pvt_slope12', '5m.ms_dist_sh', '5m.chop14'], q=0.7; GBM q=0.6

Dönem `seçim 17.09–09.10` = SEÇİM dönemi (örneklem içi); diğerleri örneklem DIŞI. `net−taban`: aynı model hedefiyle oynaklık-eşleşmiş rastgele giriş. [net] / [net−taban] etiketi: parametrelerin hangi ölçütle seçildiği.


Kapsam: tümü

| model | dilim | n | ort. hedef % | hit | taban hit | net | taban net | net−taban [95] | Δnet vs M0 [95] | Δ(net−taban) vs M0 [95] | hedef≥2.5: pay / net−taban |
|---|---|---|---|---|---|---|---|---|---|---|---|
| M0 sabit (sinyalin hedefi) | seçim 17.09–09.10 | 1522 | 2.87 | 41.9% | 21.0% | -0.56 | -0.70 | +0.14 [-0.00; +0.28] | – | – | 65% / +0.10 (n=988) |
| M0 sabit (sinyalin hedefi) | değerlendirme 10.10–17.10 | 485 | 3.19 | 38.8% | 18.6% | -0.65 | -0.82 | +0.18 [-0.15; +0.50] | – | – | 71% / +0.10 (n=346) |
| sabit 1,5 | seçim 17.09–09.10 | 1522 | 1.50 | 57.5% | 38.7% | -0.59 | -0.61 | +0.01 [-0.11; +0.14] | -0.03 [-0.09; +0.02] | -0.13 [-0.19; -0.06] | – |
| sabit 1,5 | değerlendirme 10.10–17.10 | 485 | 1.50 | 59.6% | 38.8% | -0.59 | -0.76 | +0.17 [+0.05; +0.28] | +0.06 [-0.21; +0.33] | -0.01 [-0.27; +0.26] | – |
| sabit 2,0 | seçim 17.09–09.10 | 1522 | 2.00 | 50.3% | 28.3% | -0.59 | -0.63 | +0.04 [-0.09; +0.18] | -0.03 [-0.09; +0.02] | -0.10 [-0.17; -0.03] | – |
| sabit 2,0 | değerlendirme 10.10–17.10 | 485 | 2.00 | 51.3% | 30.0% | -0.65 | -0.82 | +0.16 [-0.10; +0.43] | -0.00 [-0.12; +0.11] | -0.01 [-0.11; +0.08] | – |
| sabit 3,0 | seçim 17.09–09.10 | 1522 | 3.00 | 37.6% | 16.9% | -0.59 | -0.70 | +0.11 [-0.04; +0.25] | -0.03 [-0.08; +0.01] | -0.03 [-0.08; +0.01] | 100% / +0.11 (n=1522) |
| sabit 3,0 | değerlendirme 10.10–17.10 | 485 | 3.00 | 39.8% | 18.2% | -0.65 | -0.85 | +0.20 [-0.11; +0.51] | -0.00 [-0.09; +0.08] | +0.03 [-0.07; +0.12] | 100% / +0.20 (n=485) |
| M1 ATR (k=0.25) [net] | seçim 17.09–09.10 | 1522 | 1.54 | 63.5% | 41.5% | -0.53 | -0.64 | +0.11 [-0.04; +0.27] | +0.03 [-0.04; +0.10] | -0.03 [-0.11; +0.06] | 14% / +0.24 (n=213) |
| M1 ATR (k=0.25) [net] | değerlendirme 10.10–17.10 | 485 | 1.70 | 61.0% | 39.5% | -0.59 | -0.82 | +0.23 [+0.03; +0.44] | +0.06 [-0.14; +0.26] | +0.06 [-0.15; +0.26] | 16% / +0.66 (n=79) |
| M2 ATR+direnç (h60, pay 0.7, k 0.25) [net] | seçim 17.09–09.10 | 1522 | 1.30 | 66.7% | 46.1% | -0.49 | -0.63 | +0.13 [+0.01; +0.26] | +0.06 [-0.02; +0.15] | -0.01 [-0.09; +0.08] | 7% / +0.32 (n=112) |
| M2 ATR+direnç (h60, pay 0.7, k 0.25) [net] | değerlendirme 10.10–17.10 | 485 | 1.49 | 63.3% | 43.6% | -0.60 | -0.79 | +0.19 [-0.01; +0.39] | +0.05 [-0.17; +0.26] | +0.01 [-0.18; +0.21] | 11% / +0.59 (n=53) |
| M3 ampirik (emp60) [net] | seçim 17.09–09.10 | 1522 | 1.06 | 68.8% | 50.5% | -0.52 | -0.58 | +0.06 [-0.05; +0.17] | +0.04 [-0.04; +0.11] | -0.08 [-0.16; -0.00] | – |
| M3 ampirik (emp60) [net] | değerlendirme 10.10–17.10 | 485 | 1.05 | 70.3% | 52.0% | -0.59 | -0.72 | +0.13 [+0.00; +0.26] | +0.06 [-0.23; +0.35] | -0.05 [-0.32; +0.23] | – |
| M4 doğrusal kuantil (q=0.4, 5 özellik) [net] | seçim 17.09–09.10 | 1522 | 1.89 | 56.8% | 34.2% | -0.54 | -0.66 | +0.12 [-0.03; +0.26] | +0.02 [-0.05; +0.08] | -0.02 [-0.09; +0.05] | 26% / +0.32 (n=395) |
| M4 doğrusal kuantil (q=0.4, 5 özellik) [net] | değerlendirme 10.10–17.10 | 485 | 2.06 | 52.8% | 32.0% | -0.67 | -0.82 | +0.15 [-0.03; +0.33] | -0.02 [-0.24; +0.20] | -0.03 [-0.22; +0.17] | 27% / +0.67 (n=133) |
| M5 GBM kuantil (q=0.5, 433 özellik) [net] | seçim 17.09–09.10 | 1522 | 2.54 | 48.2% | 24.1% | -0.53 | -0.71 | +0.18 [+0.04; +0.32] | +0.02 [-0.03; +0.08] | +0.04 [-0.03; +0.10] | 37% / +0.83 (n=567) |
| M5 GBM kuantil (q=0.5, 433 özellik) [net] | değerlendirme 10.10–17.10 | 485 | 2.65 | 42.9% | 24.3% | -0.78 | -0.86 | +0.09 [-0.25; +0.42] | -0.13 [-0.28; +0.02] | -0.09 [-0.24; +0.06] | 46% / +0.29 (n=223) |
| ref: ATR-yalnız kuantil (q=0.4) [net] | seçim 17.09–09.10 | 1522 | 1.85 | 57.6% | 35.2% | -0.58 | -0.66 | +0.08 [-0.07; +0.23] | -0.02 [-0.08; +0.04] | -0.06 [-0.14; +0.02] | 24% / +0.12 (n=372) |
| ref: ATR-yalnız kuantil (q=0.4) [net] | değerlendirme 10.10–17.10 | 485 | 2.09 | 51.8% | 31.7% | -0.67 | -0.84 | +0.17 [-0.06; +0.39] | -0.03 [-0.19; +0.14] | -0.01 [-0.17; +0.14] | 31% / +0.50 (n=148) |
| M1 ATR (k=1.20) [net−taban] | seçim 17.09–09.10 | 1522 | 4.86 | 26.4% | 6.3% | -0.64 | -0.85 | +0.21 [+0.06; +0.36] | -0.09 [-0.16; -0.01] | +0.07 [-0.02; +0.16] | 76% / +0.29 (n=1158) |
| M1 ATR (k=1.20) [net−taban] | değerlendirme 10.10–17.10 | 485 | 5.73 | 20.4% | 6.0% | -0.79 | -0.98 | +0.19 [-0.10; +0.49] | -0.14 [-0.22; -0.06] | +0.02 [-0.05; +0.09] | 89% / +0.25 (n=431) |
| M2 ATR+direnç (h24, pay 0.7, k 4.80) [net−taban] | seçim 17.09–09.10 | 1522 | 4.60 | 39.2% | 23.1% | -0.49 | -0.75 | +0.27 [+0.14; +0.39] | +0.07 [-0.03; +0.17] | +0.13 [+0.04; +0.21] | 58% / +0.38 (n=890) |
| M2 ATR+direnç (h24, pay 0.7, k 4.80) [net−taban] | değerlendirme 10.10–17.10 | 485 | 4.42 | 37.3% | 21.6% | -0.70 | -0.87 | +0.17 [-0.10; +0.44] | -0.05 [-0.16; +0.06] | -0.00 [-0.14; +0.14] | 64% / +0.20 (n=310) |
| M3 ampirik (emp60) [net−taban] | seçim 17.09–09.10 | 1522 | 1.06 | 68.8% | 50.5% | -0.52 | -0.58 | +0.06 [-0.05; +0.17] | +0.04 [-0.04; +0.11] | -0.08 [-0.16; -0.00] | – |
| M3 ampirik (emp60) [net−taban] | değerlendirme 10.10–17.10 | 485 | 1.05 | 70.3% | 52.0% | -0.59 | -0.72 | +0.13 [+0.00; +0.26] | +0.06 [-0.23; +0.35] | -0.05 [-0.32; +0.23] | – |
| M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban] | seçim 17.09–09.10 | 1522 | 4.26 | 30.2% | 9.9% | -0.65 | -0.83 | +0.18 [+0.02; +0.35] | -0.09 [-0.17; -0.02] | +0.04 [-0.06; +0.15] | 72% / +0.23 (n=1095) |
| M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban] | değerlendirme 10.10–17.10 | 485 | 4.77 | 23.9% | 8.8% | -0.80 | -0.96 | +0.16 [-0.11; +0.44] | -0.15 [-0.23; -0.07] | -0.01 [-0.09; +0.07] | 86% / +0.27 (n=417) |
| M5 GBM kuantil (q=0.6, 433 özellik) [net−taban] | seçim 17.09–09.10 | 1522 | 3.24 | 37.8% | 16.1% | -0.56 | -0.77 | +0.21 [+0.03; +0.39] | -0.00 [-0.06; +0.06] | +0.07 [-0.01; +0.15] | 55% / +0.83 (n=832) |
| M5 GBM kuantil (q=0.6, 433 özellik) [net−taban] | değerlendirme 10.10–17.10 | 485 | 3.47 | 34.8% | 15.5% | -0.75 | -0.90 | +0.15 [-0.18; +0.48] | -0.11 [-0.23; +0.02] | -0.02 [-0.15; +0.10] | 69% / +0.30 (n=334) |
| ref: ATR-yalnız kuantil (q=0.7) [net−taban] | seçim 17.09–09.10 | 1522 | 4.29 | 30.6% | 8.0% | -0.61 | -0.85 | +0.24 [+0.10; +0.38] | -0.05 [-0.13; +0.02] | +0.10 [+0.01; +0.19] | 73% / +0.33 (n=1111) |
| ref: ATR-yalnız kuantil (q=0.7) [net−taban] | değerlendirme 10.10–17.10 | 485 | 4.96 | 23.7% | 7.8% | -0.82 | -0.98 | +0.15 [-0.13; +0.44] | -0.18 [-0.27; -0.09] | -0.02 [-0.11; +0.07] | 87% / +0.23 (n=423) |


İndikatör katkısı (özellikli kuantil model − ATR-yalnız kuantil referansı):

| model (özellikli) | dilim | n | Δnet vs ATR-yalnız ref [95] | Δ(net−taban) vs ATR-yalnız ref [95] |
|---|---|---|---|---|
| M4 doğrusal kuantil (q=0.4, 5 özellik) [net] | seçim 17.09–09.10 | 1522 | +0.04 [-0.01; +0.08] | +0.04 [-0.01; +0.09] |
| M4 doğrusal kuantil (q=0.4, 5 özellik) [net] | değerlendirme 10.10–17.10 | 485 | +0.00 [-0.13; +0.14] | -0.02 [-0.15; +0.12] |
| M5 GBM kuantil (q=0.5, 433 özellik) [net] | seçim 17.09–09.10 | 1522 | +0.05 [-0.01; +0.10] | +0.10 [+0.03; +0.17] |
| M5 GBM kuantil (q=0.5, 433 özellik) [net] | değerlendirme 10.10–17.10 | 485 | -0.10 [-0.30; +0.09] | -0.08 [-0.28; +0.12] |
| M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban] | seçim 17.09–09.10 | 1522 | -0.04 [-0.08; +0.01] | -0.05 [-0.10; -0.01] |
| M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban] | değerlendirme 10.10–17.10 | 485 | +0.03 [-0.04; +0.09] | +0.01 [-0.04; +0.06] |
| M5 GBM kuantil (q=0.6, 433 özellik) [net−taban] | seçim 17.09–09.10 | 1522 | +0.05 [-0.00; +0.11] | -0.03 [-0.09; +0.04] |
| M5 GBM kuantil (q=0.6, 433 özellik) [net−taban] | değerlendirme 10.10–17.10 | 485 | +0.07 [+0.01; +0.14] | -0.00 [-0.09; +0.08] |


Hedef doğruluğu (kuantil modelleri):

| model | dilim | n | q | P(MFE ≥ hedef) (kalibrasyon) | Spearman(hedef, MFE) | kısmi (ATR sabit) [t] | pinball | pinball iyileşme vs ATR-yalnız (aynı q) |
|---|---|---|---|---|---|---|---|---|
| M4 doğrusal kuantil (q=0.4, 5 özellik) [net] | seçim 17.09–09.10 | 1522 | 0.40 | 56.8% (hedef 60%) | +0.425 | +0.155 [t +9.3] | 1.218 | +1.0% |
| M4 doğrusal kuantil (q=0.4, 5 özellik) [net] | değerlendirme 10.10–17.10 | 485 | 0.40 | 52.8% (hedef 60%) | +0.350 | +0.124 [t +3.5] | 1.169 | +1.2% |
| M5 GBM kuantil (q=0.5, 433 özellik) [net] | seçim 17.09–09.10 | 1522 | 0.50 | 48.2% (hedef 50%) | +0.644 | +0.615 [t +40.4] | 1.188 | – |
| M5 GBM kuantil (q=0.5, 433 özellik) [net] | değerlendirme 10.10–17.10 | 485 | 0.50 | 42.9% (hedef 50%) | +0.352 | +0.130 [t +4.3] | 1.363 | – |
| ref: ATR-yalnız kuantil (q=0.4) [net] | seçim 17.09–09.10 | 1522 | 0.40 | 57.6% (hedef 60%) | +0.397 | -0.014 [t -0.6] | 1.231 | – |
| ref: ATR-yalnız kuantil (q=0.4) [net] | değerlendirme 10.10–17.10 | 485 | 0.40 | 51.8% (hedef 60%) | +0.333 | -0.042 [t -2.8] | 1.184 | – |
| M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban] | seçim 17.09–09.10 | 1522 | 0.70 | 30.2% (hedef 30%) | +0.435 | +0.179 [t +9.1] | 1.500 | +2.0% |
| M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban] | değerlendirme 10.10–17.10 | 485 | 0.70 | 23.9% (hedef 30%) | +0.359 | +0.136 [t +3.9] | 1.463 | +1.7% |
| M5 GBM kuantil (q=0.6, 433 özellik) [net−taban] | seçim 17.09–09.10 | 1522 | 0.60 | 37.8% (hedef 40%) | +0.639 | +0.603 [t +33.1] | 1.239 | – |
| M5 GBM kuantil (q=0.6, 433 özellik) [net−taban] | değerlendirme 10.10–17.10 | 485 | 0.60 | 34.8% (hedef 40%) | +0.378 | +0.179 [t +3.3] | 1.455 | – |
| ref: ATR-yalnız kuantil (q=0.7) [net−taban] | seçim 17.09–09.10 | 1522 | 0.70 | 30.6% (hedef 30%) | +0.402 | -0.055 [t -1.4] | 1.530 | – |
| ref: ATR-yalnız kuantil (q=0.7) [net−taban] | değerlendirme 10.10–17.10 | 485 | 0.70 | 23.7% (hedef 30%) | +0.338 | -0.053 [t -4.1] | 1.489 | – |


Kapsam: teyit kuralı (yeni canlı)

| model | dilim | n | ort. hedef % | hit | taban hit | net | taban net | net−taban [95] | Δnet vs M0 [95] | Δ(net−taban) vs M0 [95] | hedef≥2.5: pay / net−taban |
|---|---|---|---|---|---|---|---|---|---|---|---|
| M0 sabit (sinyalin hedefi) | seçim 17.09–09.10 | 338 | 2.96 | 53.8% | 30.2% | -0.80 | -0.91 | +0.11 [-0.22; +0.44] | – | – | 76% / +0.14 (n=257) |
| M0 sabit (sinyalin hedefi) | değerlendirme 10.10–17.10 | 78 | 2.29 | 61.5% | 31.6% | -0.48 | -1.09 | +0.60 [+0.34; +0.86] | – | – | – |
| sabit 1,5 | seçim 17.09–09.10 | 338 | 1.50 | 71.6% | 54.7% | -0.74 | -0.71 | -0.03 [-0.25; +0.19] | +0.06 [-0.10; +0.23] | -0.14 [-0.33; +0.05] | – |
| sabit 1,5 | değerlendirme 10.10–17.10 | 78 | 1.50 | 78.2% | 49.1% | -0.32 | -0.87 | +0.55 [+0.25; +0.84] | +0.17 [-0.16; +0.49] | -0.06 [-0.47; +0.36] | – |
| sabit 2,0 | seçim 17.09–09.10 | 338 | 2.00 | 66.3% | 42.7% | -0.75 | -0.78 | +0.02 [-0.19; +0.24] | +0.05 [-0.10; +0.20] | -0.08 [-0.29; +0.12] | – |
| sabit 2,0 | değerlendirme 10.10–17.10 | 78 | 2.00 | 66.7% | 36.3% | -0.46 | -1.03 | +0.57 [+0.42; +0.73] | +0.02 [-0.17; +0.22] | -0.03 [-0.27; +0.21] | – |
| sabit 3,0 | seçim 17.09–09.10 | 338 | 3.00 | 55.0% | 29.6% | -0.78 | -0.88 | +0.10 [-0.22; +0.42] | +0.01 [-0.09; +0.12] | -0.01 [-0.10; +0.08] | 100% / +0.10 (n=338) |
| sabit 3,0 | değerlendirme 10.10–17.10 | 78 | 3.00 | 52.6% | 23.1% | -0.81 | -1.12 | +0.31 [+0.06; +0.56] | -0.32 [-0.60; -0.04] | -0.29 [-0.57; -0.01] | 100% / +0.31 (n=78) |
| M1 ATR (k=0.25) [net] | seçim 17.09–09.10 | 338 | 2.26 | 66.3% | 42.6% | -0.72 | -0.83 | +0.10 [-0.23; +0.44] | +0.08 [-0.07; +0.22] | -0.00 [-0.20; +0.19] | 36% / +0.28 (n=120) |
| M1 ATR (k=0.25) [net] | değerlendirme 10.10–17.10 | 78 | 2.30 | 69.2% | 35.5% | -0.63 | -1.16 | +0.53 [+0.36; +0.70] | -0.15 [-0.38; +0.09] | -0.07 [-0.36; +0.21] | 31% / -0.11 (n=24) |
| M2 ATR+direnç (h60, pay 0.7, k 0.25) [net] | seçim 17.09–09.10 | 338 | 1.71 | 75.4% | 53.2% | -0.63 | -0.75 | +0.12 [-0.11; +0.35] | +0.17 [-0.00; +0.34] | +0.01 [-0.19; +0.21] | 19% / +0.19 (n=64) |
| M2 ATR+direnç (h60, pay 0.7, k 0.25) [net] | değerlendirme 10.10–17.10 | 78 | 1.80 | 74.4% | 44.0% | -0.39 | -1.06 | +0.67 [+0.44; +0.91] | +0.10 [-0.21; +0.40] | +0.07 [-0.27; +0.41] | – |
| M3 ampirik (emp60) [net] | seçim 17.09–09.10 | 338 | 1.08 | 80.5% | 65.9% | -0.66 | -0.59 | -0.07 [-0.23; +0.08] | +0.14 [-0.02; +0.30] | -0.18 [-0.44; +0.08] | – |
| M3 ampirik (emp60) [net] | değerlendirme 10.10–17.10 | 78 | 1.03 | 88.5% | 59.4% | -0.27 | -0.83 | +0.56 [+0.22; +0.91] | +0.22 [-0.17; +0.61] | -0.04 [-0.49; +0.42] | – |
| M4 doğrusal kuantil (q=0.4, 5 özellik) [net] | seçim 17.09–09.10 | 338 | 2.73 | 59.2% | 35.1% | -0.72 | -0.81 | +0.09 [-0.24; +0.42] | +0.07 [-0.07; +0.22] | -0.02 [-0.21; +0.17] | 61% / +0.21 (n=205) |
| M4 doğrusal kuantil (q=0.4, 5 özellik) [net] | değerlendirme 10.10–17.10 | 78 | 2.82 | 53.8% | 26.5% | -0.97 | -1.10 | +0.13 [-0.31; +0.58] | -0.48 [-0.84; -0.13] | -0.47 [-0.84; -0.10] | 64% / +0.18 (n=50) |
| M5 GBM kuantil (q=0.5, 433 özellik) [net] | seçim 17.09–09.10 | 338 | 3.78 | 46.2% | 24.2% | -0.72 | -0.90 | +0.18 [-0.11; +0.48] | +0.08 [-0.10; +0.25] | +0.07 [-0.10; +0.24] | 76% / +0.55 (n=257) |
| M5 GBM kuantil (q=0.5, 433 özellik) [net] | değerlendirme 10.10–17.10 | 78 | 3.92 | 42.3% | 16.7% | -1.04 | -1.26 | +0.22 [-0.12; +0.56] | -0.55 [-0.95; -0.15] | -0.38 [-0.77; +0.00] | 79% / +0.29 (n=62) |
| ref: ATR-yalnız kuantil (q=0.4) [net] | seçim 17.09–09.10 | 338 | 2.74 | 59.8% | 34.5% | -0.79 | -0.85 | +0.06 [-0.27; +0.40] | +0.01 [-0.15; +0.16] | -0.05 [-0.25; +0.15] | 60% / +0.07 (n=203) |
| ref: ATR-yalnız kuantil (q=0.4) [net] | değerlendirme 10.10–17.10 | 78 | 2.79 | 55.1% | 26.9% | -0.68 | -1.11 | +0.43 [+0.07; +0.79] | -0.20 [-0.47; +0.07] | -0.17 [-0.38; +0.03] | 68% / +0.42 (n=53) |
| M1 ATR (k=1.20) [net−taban] | seçim 17.09–09.10 | 338 | 7.25 | 24.6% | 5.0% | -0.98 | -1.18 | +0.20 [-0.18; +0.57] | -0.18 [-0.40; +0.04] | +0.09 [-0.21; +0.38] | 99% / +0.21 (n=335) |
| M1 ATR (k=1.20) [net−taban] | değerlendirme 10.10–17.10 | 78 | 7.56 | 21.8% | 3.0% | -1.07 | -1.43 | +0.36 [-0.29; +1.01] | -0.58 [-1.34; +0.18] | -0.24 [-0.94; +0.45] | 100% / +0.36 (n=78) |
| M2 ATR+direnç (h24, pay 0.7, k 4.80) [net−taban] | seçim 17.09–09.10 | 338 | 4.10 | 55.6% | 32.4% | -0.88 | -1.01 | +0.13 [-0.12; +0.38] | -0.08 [-0.28; +0.12] | +0.02 [-0.18; +0.22] | 53% / -0.02 (n=178) |
| M2 ATR+direnç (h24, pay 0.7, k 4.80) [net−taban] | değerlendirme 10.10–17.10 | 78 | 3.61 | 61.5% | 30.8% | -0.55 | -1.04 | +0.49 [+0.14; +0.85] | -0.07 [-0.42; +0.28] | -0.11 [-0.42; +0.20] | 51% / +0.07 (n=40) |
| M3 ampirik (emp60) [net−taban] | seçim 17.09–09.10 | 338 | 1.08 | 80.5% | 65.9% | -0.66 | -0.59 | -0.07 [-0.23; +0.08] | +0.14 [-0.02; +0.30] | -0.18 [-0.44; +0.08] | – |
| M3 ampirik (emp60) [net−taban] | değerlendirme 10.10–17.10 | 78 | 1.03 | 88.5% | 59.4% | -0.27 | -0.83 | +0.56 [+0.22; +0.91] | +0.22 [-0.17; +0.61] | -0.04 [-0.49; +0.42] | – |
| M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban] | seçim 17.09–09.10 | 338 | 6.34 | 28.4% | 6.4% | -1.00 | -1.16 | +0.16 [-0.26; +0.58] | -0.20 [-0.46; +0.06] | +0.05 [-0.32; +0.42] | 99% / +0.17 (n=336) |
| M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban] | değerlendirme 10.10–17.10 | 78 | 6.51 | 25.6% | 5.1% | -1.00 | -1.39 | +0.39 [-0.24; +1.02] | -0.52 [-1.29; +0.26] | -0.22 [-0.94; +0.51] | 100% / +0.39 (n=78) |
| M5 GBM kuantil (q=0.6, 433 özellik) [net−taban] | seçim 17.09–09.10 | 338 | 4.78 | 35.5% | 14.7% | -0.83 | -1.03 | +0.19 [-0.23; +0.62] | -0.03 [-0.23; +0.16] | +0.09 [-0.20; +0.37] | 88% / +0.46 (n=299) |
| M5 GBM kuantil (q=0.6, 433 özellik) [net−taban] | değerlendirme 10.10–17.10 | 78 | 4.96 | 34.6% | 9.0% | -0.96 | -1.38 | +0.42 [+0.12; +0.72] | -0.48 [-0.92; -0.03] | -0.18 [-0.58; +0.22] | 92% / +0.43 (n=72) |
| ref: ATR-yalnız kuantil (q=0.7) [net−taban] | seçim 17.09–09.10 | 338 | 6.44 | 30.2% | 6.0% | -0.94 | -1.18 | +0.24 [-0.13; +0.60] | -0.14 [-0.35; +0.07] | +0.13 [-0.15; +0.41] | 99% / +0.25 (n=333) |
| ref: ATR-yalnız kuantil (q=0.7) [net−taban] | değerlendirme 10.10–17.10 | 78 | 6.61 | 23.1% | 4.3% | -1.15 | -1.38 | +0.22 [-0.37; +0.82] | -0.67 [-1.43; +0.09] | -0.38 [-1.09; +0.33] | 100% / +0.22 (n=78) |


İndikatör katkısı (özellikli kuantil model − ATR-yalnız kuantil referansı):

| model (özellikli) | dilim | n | Δnet vs ATR-yalnız ref [95] | Δ(net−taban) vs ATR-yalnız ref [95] |
|---|---|---|---|---|
| M4 doğrusal kuantil (q=0.4, 5 özellik) [net] | seçim 17.09–09.10 | 338 | +0.07 [-0.04; +0.17] | +0.03 [-0.09; +0.15] |
| M4 doğrusal kuantil (q=0.4, 5 özellik) [net] | değerlendirme 10.10–17.10 | 78 | -0.29 [-0.66; +0.09] | -0.30 [-0.67; +0.08] |
| M5 GBM kuantil (q=0.5, 433 özellik) [net] | seçim 17.09–09.10 | 338 | +0.07 [-0.06; +0.20] | +0.12 [-0.06; +0.30] |
| M5 GBM kuantil (q=0.5, 433 özellik) [net] | değerlendirme 10.10–17.10 | 78 | -0.35 [-0.82; +0.11] | -0.21 [-0.63; +0.21] |
| M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban] | seçim 17.09–09.10 | 338 | -0.06 [-0.21; +0.10] | -0.08 [-0.24; +0.08] |
| M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban] | değerlendirme 10.10–17.10 | 78 | +0.15 [-0.04; +0.34] | +0.16 [-0.05; +0.37] |
| M5 GBM kuantil (q=0.6, 433 özellik) [net−taban] | seçim 17.09–09.10 | 338 | +0.11 [-0.05; +0.27] | -0.04 [-0.23; +0.14] |
| M5 GBM kuantil (q=0.6, 433 özellik) [net−taban] | değerlendirme 10.10–17.10 | 78 | +0.19 [-0.26; +0.64] | +0.20 [-0.24; +0.63] |


### Nüfus 1 — Hız Avcısı canlı-benzeri bölümler
Eğitim: B1 (20 Tem–18 Ağu) (n=6110); test: B2 (19 Ağu–17 Eyl), B3 (18 Eyl–16 Eki).

#### B1. MFE / MAE öngörücüleri — kapsam: tümü (n=20343)

Anlamlı (BH q<0,05) özellik sayısı — ham vs ATR-kontrollü:

| sonuç | özellik | ham | ATR-kontrollü |
|---|---|---|---|
| MFE60 | 438 | 345 | 381 |
| MFE60/ATR | 438 | 381 | 382 |
| MAE60 | 438 | 359 | 387 |
| MAE60/ATR | 438 | 399 | 382 |

Referans: ATR'nin kendisi ile Spearman(ATR, MFE60) = +0.305 [t +45.3]; Spearman(ATR, MAE60 mutlak) = +0.405 [t +50.1].

En iyi 15 özellik — MFE60 (ATR-kontrollü):

| özellik | ham r(MFE) [t] | ATR-kont. r(MFE) [t] | q | blok işaret uyumu | ATR-kont. r(MFE/ATR) [t] | ATR-kont. r(MAE mutlak) [t] | q(MAE) |
|---|---|---|---|---|---|---|---|
| 5m.bb_pctb | -0.011 [-1.4] | +0.120 [+17.6] | 0.000 | 3/3 | +0.117 [+17.0] | +0.181 [+21.8] | 0.000 |
| 5m.cci20 | -0.020 [-2.6] | +0.120 [+16.8] | 0.000 | 3/3 | +0.118 [+15.9] | +0.171 [+20.7] | 0.000 |
| 5m.px_wma | +0.094 [+13.0] | +0.117 [+16.7] | 0.000 | 3/3 | +0.114 [+17.0] | +0.196 [+22.0] | 0.000 |
| 5m.ms_dist_sh | -0.022 [-3.1] | +0.112 [+16.6] | 0.000 | 3/3 | +0.110 [+15.9] | +0.174 [+18.9] | 0.000 |
| 5m.rsi14 | +0.018 [+2.3] | +0.117 [+16.4] | 0.000 | 3/3 | +0.113 [+15.2] | +0.172 [+19.2] | 0.000 |
| 5m.kc_pos | -0.032 [-4.1] | +0.116 [+16.3] | 0.000 | 3/3 | +0.112 [+15.3] | +0.184 [+20.9] | 0.000 |
| 5m.px_mcg | +0.150 [+20.7] | +0.117 [+16.2] | 0.000 | 3/3 | +0.107 [+15.9] | +0.181 [+20.1] | 0.000 |
| 5m.px_ema20 | +0.113 [+15.4] | +0.117 [+16.1] | 0.000 | 3/3 | +0.111 [+16.1] | +0.189 [+20.8] | 0.000 |
| ex:velocity_score | +0.220 [+33.2] | +0.110 [+16.0] | 0.000 | 3/3 | +0.099 [+15.1] | +0.179 [+21.3] | 0.000 |
| 5m.ret10 | +0.072 [+10.4] | +0.108 [+15.9] | 0.000 | 3/3 | +0.105 [+15.6] | +0.182 [+20.7] | 0.000 |
| 5m.px_ema7 | +0.103 [+14.8] | +0.108 [+15.7] | 0.000 | 3/3 | +0.106 [+16.3] | +0.182 [+21.7] | 0.000 |
| 5m.px_dema | +0.058 [+8.6] | +0.098 [+15.6] | 0.000 | 3/3 | +0.099 [+16.6] | +0.168 [+17.6] | 0.000 |
| 5m.px_ema99 | +0.190 [+26.4] | +0.111 [+15.6] | 0.000 | 3/3 | +0.103 [+15.1] | +0.141 [+14.6] | 0.000 |
| 5m.ms_dist_sl | +0.196 [+31.0] | +0.100 [+15.5] | 0.000 | 3/3 | +0.089 [+14.4] | +0.162 [+19.5] | 0.000 |
| 5m.cmo14 | +0.012 [+1.6] | +0.113 [+15.4] | 0.000 | 3/3 | +0.109 [+14.6] | +0.167 [+19.4] | 0.000 |

En iyi 15 özellik — MFE60 (ham):

| özellik | ham r(MFE) [t] | ATR-kont. r(MFE) [t] | q | blok işaret uyumu | ATR-kont. r(MFE/ATR) [t] | ATR-kont. r(MAE mutlak) [t] | q(MAE) |
|---|---|---|---|---|---|---|---|
| 5m.kc_width | +0.312 [+45.9] | +0.066 [+10.1] | 0.000 | 3/3 | +0.060 [+8.9] | +0.096 [+11.5] | 0.000 |
| 5m.atr14_pct | +0.305 [+45.3] | -0.003 [-0.4] | 0.680 | 1/3 | -0.006 [-0.7] | +0.000 [+0.1] | 0.952 |
| 5m.donch_width20 | +0.285 [+42.1] | +0.057 [+7.7] | 0.000 | 3/3 | +0.049 [+6.3] | +0.075 [+8.0] | 0.000 |
| ex:m1_atr_prev | +0.299 [+41.7] | +0.102 [+14.2] | 0.000 | 3/3 | +0.090 [+12.8] | +0.135 [+15.1] | 0.000 |
| ex:atr_pct | +0.297 [+41.5] | +0.103 [+13.6] | 0.000 | 3/3 | +0.090 [+12.1] | +0.147 [+16.2] | 0.000 |
| ex:m3_atr_prev | +0.294 [+40.9] | +0.089 [+12.1] | 0.000 | 3/3 | +0.079 [+11.1] | +0.105 [+12.2] | 0.000 |
| 15m.kc_width | +0.274 [+40.1] | -0.006 [-0.8] | 0.473 | 1/3 | -0.010 [-1.3] | +0.010 [+1.4] | 0.185 |
| 15m.atr14_pct | +0.259 [+36.6] | -0.007 [-1.0] | 0.357 | 2/3 | -0.011 [-1.5] | +0.006 [+0.8] | 0.425 |
| 5m.bb_width_pct | +0.254 [+36.4] | +0.035 [+5.0] | 0.000 | 3/3 | +0.026 [+3.5] | +0.074 [+8.3] | 0.000 |
| 5m.lsma_se_pct | +0.247 [+34.7] | +0.005 [+0.7] | 0.482 | 1/3 | -0.004 [-0.5] | +0.030 [+3.7] | 0.000 |
| 5m.hv20 | +0.255 [+34.3] | -0.033 [-3.8] | 0.000 | 2/3 | -0.043 [-4.7] | +0.029 [+3.7] | 0.001 |
| 15m.bb_width_pct | +0.249 [+33.3] | +0.024 [+3.3] | 0.002 | 3/3 | +0.017 [+2.4] | +0.034 [+3.6] | 0.001 |
| 15m.donch_width20 | +0.263 [+33.3] | +0.024 [+3.1] | 0.004 | 3/3 | +0.019 [+2.4] | +0.026 [+3.1] | 0.003 |
| ex:velocity_score | +0.220 [+33.2] | +0.110 [+16.0] | 0.000 | 3/3 | +0.099 [+15.1] | +0.179 [+21.3] | 0.000 |
| 5m.dist_low24_pct | +0.271 [+32.2] | +0.106 [+12.4] | 0.000 | 3/3 | +0.098 [+12.0] | +0.110 [+12.0] | 0.000 |

En iyi 15 özellik — MAE60 mutlak (ATR-kontrollü):

| özellik | ham r(MFE) [t] | ATR-kont. r(MFE) [t] | q | blok işaret uyumu | ATR-kont. r(MFE/ATR) [t] | ATR-kont. r(MAE mutlak) [t] | q(MAE) |
|---|---|---|---|---|---|---|---|
| 5m.px_wma | +0.094 [+13.0] | +0.117 [+16.7] | 0.000 | 3/3 | +0.114 [+17.0] | +0.196 [+22.0] | 0.000 |
| 5m.bb_pctb | -0.011 [-1.4] | +0.120 [+17.6] | 0.000 | 3/3 | +0.117 [+17.0] | +0.181 [+21.8] | 0.000 |
| 5m.px_ema7 | +0.103 [+14.8] | +0.108 [+15.7] | 0.000 | 3/3 | +0.106 [+16.3] | +0.182 [+21.7] | 0.000 |
| ex:velocity_score | +0.220 [+33.2] | +0.110 [+16.0] | 0.000 | 3/3 | +0.099 [+15.1] | +0.179 [+21.3] | 0.000 |
| 5m.efi13 | +0.061 [+8.8] | +0.097 [+14.6] | 0.000 | 3/3 | +0.090 [+13.0] | +0.171 [+21.0] | 0.000 |
| 5m.kc_pos | -0.032 [-4.1] | +0.116 [+16.3] | 0.000 | 3/3 | +0.112 [+15.3] | +0.184 [+20.9] | 0.000 |
| 5m.px_ema20 | +0.113 [+15.4] | +0.117 [+16.1] | 0.000 | 3/3 | +0.111 [+16.1] | +0.189 [+20.8] | 0.000 |
| 5m.ret10 | +0.072 [+10.4] | +0.108 [+15.9] | 0.000 | 3/3 | +0.105 [+15.6] | +0.182 [+20.7] | 0.000 |
| 5m.cci20 | -0.020 [-2.6] | +0.120 [+16.8] | 0.000 | 3/3 | +0.118 [+15.9] | +0.171 [+20.7] | 0.000 |
| 5m.px_mcg | +0.150 [+20.7] | +0.117 [+16.2] | 0.000 | 3/3 | +0.107 [+15.9] | +0.181 [+20.1] | 0.000 |
| 5m.mfi14 | +0.020 [+2.8] | +0.101 [+13.9] | 0.000 | 3/3 | +0.098 [+12.9] | +0.144 [+20.1] | 0.000 |
| 5m.pvt_slope12 | +0.048 [+7.0] | +0.098 [+14.3] | 0.000 | 3/3 | +0.093 [+14.0] | +0.163 [+19.8] | 0.000 |
| 5m.ret5 | +0.081 [+11.2] | +0.102 [+14.5] | 0.000 | 3/3 | +0.100 [+14.5] | +0.166 [+19.8] | 0.000 |
| 5m.slope_kama | +0.023 [+3.0] | +0.105 [+13.5] | 0.000 | 3/3 | +0.102 [+13.0] | +0.163 [+19.6] | 0.000 |
| 5m.ms_dist_sl | +0.196 [+31.0] | +0.100 [+15.5] | 0.000 | 3/3 | +0.089 [+14.4] | +0.162 [+19.5] | 0.000 |


#### B2. Hedef modelleri

- Seçim ölçütü `net` (yalnız eğitim bloğu B1 (20 Tem–18 Ağu)): ATR k=0.25; direnç=('res:poc_15m', 0.5, 0.25); ampirik=dyn:emp50; QR özellikleri=['5m.px_ema99', '5m.dist_low24_pct', '5m.px_wma', '5m.ret10', '5m.px_ema20'], q=0.4; GBM q=0.5
- Seçim ölçütü `excess` (yalnız eğitim bloğu B1 (20 Tem–18 Ağu)): ATR k=1.2; direnç=('res:eqh_15m', 0.9, 2.4); ampirik=dyn:emp70; QR özellikleri=['5m.px_ema99', '5m.dist_low24_pct', '5m.px_wma', '5m.ret10', '5m.px_ema20'], q=0.7; GBM q=0.7

Dönem `B1 (20 Tem–18 Ağu)` = SEÇİM dönemi (örneklem içi); diğerleri örneklem DIŞI. `net−taban`: aynı model hedefiyle oynaklık-eşleşmiş rastgele giriş. [net] / [net−taban] etiketi: parametrelerin hangi ölçütle seçildiği.


Kapsam: tümü

| model | dilim | n | ort. hedef % | hit | taban hit | net | taban net | net−taban [95] | Δnet vs M0 [95] | Δ(net−taban) vs M0 [95] | hedef≥2.5: pay / net−taban |
|---|---|---|---|---|---|---|---|---|---|---|---|
| M0 sabit (sinyalin hedefi) | B1 (20 Tem–18 Ağu) | 6110 | 3.46 | 25.2% | 5.3% | -0.54 | -0.87 | +0.33 [+0.25; +0.41] | – | – | 100% / +0.33 (n=6110) |
| M0 sabit (sinyalin hedefi) | B2 (19 Ağu–17 Eyl) | 6797 | 3.44 | 21.3% | 4.2% | -0.51 | -0.62 | +0.10 [+0.02; +0.18] | – | – | 100% / +0.10 (n=6797) |
| M0 sabit (sinyalin hedefi) | B3 (18 Eyl–16 Eki) | 7436 | 3.46 | 22.5% | 3.9% | -0.62 | -0.79 | +0.17 [+0.07; +0.26] | – | – | 100% / +0.17 (n=7436) |
| M0 sabit (sinyalin hedefi) | OOS (ilk blok dışı) | 14233 | 3.45 | 21.9% | 4.1% | -0.57 | -0.71 | +0.14 [+0.07; +0.20] | – | – | 100% / +0.14 (n=14233) |
| sabit 1,5 | B1 (20 Tem–18 Ağu) | 6110 | 1.50 | 50.9% | 26.5% | -0.54 | -0.73 | +0.19 [+0.12; +0.25] | -0.00 [-0.04; +0.04] | -0.14 [-0.19; -0.09] | – |
| sabit 1,5 | B2 (19 Ağu–17 Eyl) | 6797 | 1.50 | 48.7% | 27.8% | -0.50 | -0.55 | +0.05 [-0.01; +0.11] | +0.01 [-0.03; +0.05] | -0.06 [-0.10; -0.02] | – |
| sabit 1,5 | B3 (18 Eyl–16 Eki) | 7436 | 1.50 | 49.4% | 26.8% | -0.56 | -0.68 | +0.11 [+0.04; +0.18] | +0.06 [+0.02; +0.09] | -0.05 [-0.09; -0.01] | – |
| sabit 1,5 | OOS (ilk blok dışı) | 14233 | 1.50 | 49.1% | 27.3% | -0.54 | -0.62 | +0.08 [+0.03; +0.13] | +0.04 [+0.01; +0.06] | -0.05 [-0.08; -0.03] | – |
| sabit 2,0 | B1 (20 Tem–18 Ağu) | 6110 | 2.00 | 41.8% | 18.0% | -0.53 | -0.76 | +0.23 [+0.16; +0.31] | +0.01 [-0.02; +0.05] | -0.09 [-0.14; -0.05] | – |
| sabit 2,0 | B2 (19 Ağu–17 Eyl) | 6797 | 2.00 | 38.9% | 16.5% | -0.50 | -0.57 | +0.07 [-0.00; +0.15] | +0.01 [-0.02; +0.05] | -0.03 [-0.06; +0.00] | – |
| sabit 2,0 | B3 (18 Eyl–16 Eki) | 7436 | 2.00 | 40.0% | 16.3% | -0.58 | -0.72 | +0.15 [+0.06; +0.23] | +0.04 [+0.01; +0.07] | -0.02 [-0.05; +0.02] | – |
| sabit 2,0 | OOS (ilk blok dışı) | 14233 | 2.00 | 39.5% | 16.4% | -0.54 | -0.65 | +0.11 [+0.05; +0.17] | +0.03 [+0.01; +0.05] | -0.02 [-0.05; -0.00] | – |
| sabit 3,0 | B1 (20 Tem–18 Ağu) | 6110 | 3.00 | 29.2% | 7.3% | -0.54 | -0.85 | +0.31 [+0.23; +0.39] | -0.00 [-0.02; +0.02] | -0.02 [-0.05; +0.00] | 100% / +0.31 (n=6110) |
| sabit 3,0 | B2 (19 Ağu–17 Eyl) | 6797 | 3.00 | 25.6% | 5.7% | -0.52 | -0.61 | +0.10 [+0.02; +0.17] | -0.00 [-0.02; +0.02] | -0.01 [-0.03; +0.01] | 100% / +0.10 (n=6797) |
| sabit 3,0 | B3 (18 Eyl–16 Eki) | 7436 | 3.00 | 26.9% | 5.9% | -0.60 | -0.77 | +0.18 [+0.09; +0.27] | +0.03 [+0.01; +0.04] | +0.01 [-0.00; +0.03] | 100% / +0.18 (n=7436) |
| sabit 3,0 | OOS (ilk blok dışı) | 14233 | 3.00 | 26.3% | 5.8% | -0.56 | -0.70 | +0.14 [+0.08; +0.20] | +0.01 [-0.00; +0.03] | +0.00 [-0.01; +0.02] | 100% / +0.14 (n=14233) |
| M1 ATR (k=0.25) [net] | B1 (20 Tem–18 Ağu) | 6110 | 1.40 | 56.8% | 34.0% | -0.54 | -0.72 | +0.18 [+0.11; +0.25] | -0.00 [-0.03; +0.03] | -0.15 [-0.19; -0.12] | 9% / +0.38 (n=546) |
| M1 ATR (k=0.25) [net] | B2 (19 Ağu–17 Eyl) | 6797 | 1.25 | 56.5% | 37.3% | -0.51 | -0.53 | +0.02 [-0.05; +0.08] | -0.00 [-0.04; +0.04] | -0.09 [-0.13; -0.05] | 4% / -0.09 (n=300) |
| M1 ATR (k=0.25) [net] | B3 (18 Eyl–16 Eki) | 7436 | 1.28 | 57.3% | 36.4% | -0.54 | -0.66 | +0.12 [+0.04; +0.19] | +0.08 [+0.04; +0.12] | -0.05 [-0.09; -0.01] | 5% / +0.47 (n=405) |
| M1 ATR (k=0.25) [net] | OOS (ilk blok dışı) | 14233 | 1.27 | 56.9% | 36.9% | -0.53 | -0.60 | +0.07 [+0.02; +0.12] | +0.04 [+0.01; +0.07] | -0.07 [-0.10; -0.04] | 5% / +0.23 (n=705) |
| M2 ATR+direnç (poc_15m, pay 0.5, k 0.25) [net] | B1 (20 Tem–18 Ağu) | 6110 | 1.33 | 57.9% | 35.2% | -0.53 | -0.71 | +0.18 [+0.11; +0.25] | +0.01 [-0.03; +0.04] | -0.15 [-0.19; -0.11] | 7% / +0.53 (n=432) |
| M2 ATR+direnç (poc_15m, pay 0.5, k 0.25) [net] | B2 (19 Ağu–17 Eyl) | 6797 | 1.20 | 57.3% | 38.5% | -0.52 | -0.53 | +0.01 [-0.05; +0.07] | -0.00 [-0.04; +0.04] | -0.09 [-0.14; -0.05] | 3% / -0.15 (n=217) |
| M2 ATR+direnç (poc_15m, pay 0.5, k 0.25) [net] | B3 (18 Eyl–16 Eki) | 7436 | 1.23 | 58.1% | 37.4% | -0.54 | -0.66 | +0.11 [+0.04; +0.19] | +0.08 [+0.04; +0.12] | -0.05 [-0.09; -0.01] | 4% / +0.60 (n=332) |
| M2 ATR+direnç (poc_15m, pay 0.5, k 0.25) [net] | OOS (ilk blok dışı) | 14233 | 1.22 | 57.7% | 37.9% | -0.53 | -0.60 | +0.06 [+0.01; +0.12] | +0.04 [+0.01; +0.07] | -0.07 [-0.10; -0.04] | 4% / +0.30 (n=549) |
| M3 ampirik (emp50) [net] | B1 (20 Tem–18 Ağu) | 5929 | 1.11 | 60.8% | 39.3% | -0.53 | -0.68 | +0.16 [+0.10; +0.21] | +0.01 [-0.04; +0.06] | -0.17 [-0.24; -0.10] | 3% / +1.37 (n=162) |
| M3 ampirik (emp50) [net] | B2 (19 Ağu–17 Eyl) | 6776 | 1.05 | 59.9% | 42.6% | -0.50 | -0.52 | +0.01 [-0.03; +0.06] | +0.01 [-0.04; +0.06] | -0.09 [-0.14; -0.03] | – |
| M3 ampirik (emp50) [net] | B3 (18 Eyl–16 Eki) | 7436 | 1.03 | 60.9% | 42.2% | -0.56 | -0.62 | +0.07 [+0.01; +0.13] | +0.07 [+0.03; +0.11] | -0.10 [-0.15; -0.05] | – |
| M3 ampirik (emp50) [net] | OOS (ilk blok dışı) | 14212 | 1.04 | 60.4% | 42.4% | -0.53 | -0.57 | +0.04 [+0.00; +0.08] | +0.04 [+0.01; +0.07] | -0.09 [-0.13; -0.06] | – |
| M4 doğrusal kuantil (q=0.4, 5 özellik) [net] | B1 (20 Tem–18 Ağu) | 6110 | 1.46 | 55.5% | 31.3% | -0.54 | -0.73 | +0.20 [+0.12; +0.27] | +0.00 [-0.03; +0.03] | -0.13 [-0.17; -0.10] | 9% / +0.45 (n=553) |
| M4 doğrusal kuantil (q=0.4, 5 özellik) [net] | B2 (19 Ağu–17 Eyl) | 6797 | 1.37 | 53.5% | 32.8% | -0.51 | -0.54 | +0.03 [-0.04; +0.09] | +0.00 [-0.04; +0.04] | -0.07 [-0.12; -0.03] | 4% / -0.40 (n=295) |
| M4 doğrusal kuantil (q=0.4, 5 özellik) [net] | B3 (18 Eyl–16 Eki) | 7436 | 1.41 | 54.3% | 31.8% | -0.55 | -0.68 | +0.13 [+0.06; +0.21] | +0.07 [+0.04; +0.11] | -0.03 [-0.07; +0.00] | 6% / +0.65 (n=428) |
| M4 doğrusal kuantil (q=0.4, 5 özellik) [net] | OOS (ilk blok dışı) | 14233 | 1.39 | 53.9% | 32.3% | -0.53 | -0.62 | +0.08 [+0.03; +0.13] | +0.04 [+0.01; +0.07] | -0.05 [-0.08; -0.02] | 5% / +0.22 (n=723) |
| M5 GBM kuantil (q=0.5, 433 özellik) [net] | B1 (20 Tem–18 Ağu) | 6110 | 1.85 | 48.4% | 23.5% | -0.53 | -0.78 | +0.26 [+0.17; +0.34] | +0.01 [-0.01; +0.04] | -0.07 [-0.10; -0.04] | 20% / +0.76 (n=1233) |
| M5 GBM kuantil (q=0.5, 433 özellik) [net] | B2 (19 Ağu–17 Eyl) | 6797 | 1.73 | 46.4% | 24.5% | -0.52 | -0.56 | +0.04 [-0.03; +0.11] | -0.01 [-0.04; +0.03] | -0.06 [-0.10; -0.02] | 14% / -0.18 (n=948) |
| M5 GBM kuantil (q=0.5, 433 özellik) [net] | B3 (18 Eyl–16 Eki) | 7436 | 1.80 | 46.8% | 23.2% | -0.59 | -0.72 | +0.13 [+0.05; +0.21] | +0.03 [+0.01; +0.06] | -0.03 [-0.06; -0.01] | 16% / +0.37 (n=1223) |
| M5 GBM kuantil (q=0.5, 433 özellik) [net] | OOS (ilk blok dışı) | 14233 | 1.77 | 46.6% | 23.8% | -0.56 | -0.64 | +0.09 [+0.04; +0.14] | +0.02 [-0.01; +0.04] | -0.05 [-0.07; -0.02] | 15% / +0.13 (n=2171) |
| ref: ATR-yalnız kuantil (q=0.4) [net] | B1 (20 Tem–18 Ağu) | 6110 | 1.41 | 56.0% | 32.3% | -0.54 | -0.73 | +0.19 [+0.12; +0.26] | +0.00 [-0.03; +0.04] | -0.14 [-0.18; -0.10] | 7% / +0.49 (n=438) |
| ref: ATR-yalnız kuantil (q=0.4) [net] | B2 (19 Ağu–17 Eyl) | 6797 | 1.29 | 55.1% | 35.2% | -0.52 | -0.53 | +0.02 [-0.05; +0.08] | -0.00 [-0.04; +0.04] | -0.08 [-0.12; -0.04] | 4% / -0.21 (n=240) |
| ref: ATR-yalnız kuantil (q=0.4) [net] | B3 (18 Eyl–16 Eki) | 7436 | 1.32 | 56.2% | 34.5% | -0.54 | -0.67 | +0.13 [+0.05; +0.20] | +0.08 [+0.04; +0.12] | -0.04 [-0.08; +0.00] | 4% / +0.65 (n=318) |
| ref: ATR-yalnız kuantil (q=0.4) [net] | OOS (ilk blok dışı) | 14233 | 1.30 | 55.7% | 34.8% | -0.53 | -0.61 | +0.08 [+0.02; +0.13] | +0.04 [+0.01; +0.07] | -0.06 [-0.09; -0.03] | 4% / +0.28 (n=558) |
| M1 ATR (k=1.20) [net−taban] | B1 (20 Tem–18 Ağu) | 6110 | 4.68 | 18.5% | 3.3% | -0.57 | -0.91 | +0.35 [+0.25; +0.44] | -0.03 [-0.06; +0.00] | +0.02 [-0.02; +0.06] | 80% / +0.41 (n=4861) |
| M1 ATR (k=1.20) [net−taban] | B2 (19 Ağu–17 Eyl) | 6797 | 4.33 | 17.8% | 4.1% | -0.52 | -0.62 | +0.10 [+0.02; +0.17] | -0.01 [-0.03; +0.01] | -0.00 [-0.03; +0.02] | 78% / +0.12 (n=5315) |
| M1 ATR (k=1.20) [net−taban] | B3 (18 Eyl–16 Eki) | 7436 | 4.44 | 17.8% | 3.6% | -0.64 | -0.79 | +0.15 [+0.06; +0.25] | -0.02 [-0.05; +0.02] | -0.01 [-0.04; +0.02] | 80% / +0.20 (n=5949) |
| M1 ATR (k=1.20) [net−taban] | OOS (ilk blok dışı) | 14233 | 4.39 | 17.8% | 3.9% | -0.58 | -0.71 | +0.13 [+0.07; +0.19] | -0.01 [-0.03; +0.01] | -0.01 [-0.03; +0.01] | 79% / +0.16 (n=11264) |
| M2 ATR+direnç (eqh_15m, pay 0.9, k 2.40) [net−taban] | B1 (20 Tem–18 Ağu) | 6110 | 6.57 | 10.7% | 1.4% | -0.57 | -0.92 | +0.35 [+0.25; +0.46] | -0.03 [-0.07; +0.01] | +0.02 [-0.02; +0.07] | 96% / +0.36 (n=5882) |
| M2 ATR+direnç (eqh_15m, pay 0.9, k 2.40) [net−taban] | B2 (19 Ağu–17 Eyl) | 6797 | 6.48 | 8.3% | 1.5% | -0.52 | -0.63 | +0.11 [+0.04; +0.19] | -0.01 [-0.03; +0.02] | +0.01 [-0.02; +0.04] | 97% / +0.12 (n=6586) |
| M2 ATR+direnç (eqh_15m, pay 0.9, k 2.40) [net−taban] | B3 (18 Eyl–16 Eki) | 7436 | 6.57 | 8.6% | 1.2% | -0.66 | -0.80 | +0.14 [+0.04; +0.24] | -0.04 [-0.07; +0.00] | -0.02 [-0.06; +0.02] | 98% / +0.15 (n=7253) |
| M2 ATR+direnç (eqh_15m, pay 0.9, k 2.40) [net−taban] | OOS (ilk blok dışı) | 14233 | 6.52 | 8.4% | 1.3% | -0.59 | -0.72 | +0.13 [+0.07; +0.19] | -0.02 [-0.04; +0.00] | -0.01 [-0.03; +0.02] | 97% / +0.14 (n=13839) |
| M3 ampirik (emp70) [net−taban] | B1 (20 Tem–18 Ağu) | 5929 | 1.50 | 53.3% | 31.0% | -0.55 | -0.74 | +0.19 [+0.13; +0.25] | -0.01 [-0.06; +0.04] | -0.13 [-0.20; -0.06] | 7% / +0.89 (n=427) |
| M3 ampirik (emp70) [net−taban] | B2 (19 Ağu–17 Eyl) | 6776 | 1.29 | 54.7% | 36.0% | -0.51 | -0.55 | +0.04 [-0.01; +0.09] | +0.01 [-0.04; +0.05] | -0.06 [-0.12; -0.01] | 4% / +0.27 (n=296) |
| M3 ampirik (emp70) [net−taban] | B3 (18 Eyl–16 Eki) | 7436 | 1.24 | 56.0% | 35.8% | -0.56 | -0.65 | +0.10 [+0.03; +0.16] | +0.07 [+0.03; +0.10] | -0.07 [-0.11; -0.02] | 2% / -0.25 (n=158) |
| M3 ampirik (emp70) [net−taban] | OOS (ilk blok dışı) | 14212 | 1.26 | 55.4% | 35.9% | -0.53 | -0.60 | +0.07 [+0.03; +0.11] | +0.04 [+0.01; +0.07] | -0.06 [-0.10; -0.03] | 3% / +0.09 (n=454) |
| M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban] | B1 (20 Tem–18 Ağu) | 6110 | 3.22 | 30.0% | 8.4% | -0.56 | -0.88 | +0.31 [+0.23; +0.39] | -0.02 [-0.06; +0.02] | -0.02 [-0.06; +0.03] | 57% / +0.44 (n=3491) |
| M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban] | B2 (19 Ağu–17 Eyl) | 6797 | 3.02 | 27.2% | 8.6% | -0.53 | -0.61 | +0.08 [-0.00; +0.17] | -0.01 [-0.04; +0.01] | -0.02 [-0.05; +0.00] | 59% / +0.09 (n=4034) |
| M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban] | B3 (18 Eyl–16 Eki) | 7436 | 3.14 | 27.5% | 7.7% | -0.63 | -0.78 | +0.15 [+0.06; +0.24] | -0.00 [-0.03; +0.02] | -0.01 [-0.04; +0.01] | 62% / +0.21 (n=4619) |
| M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban] | OOS (ilk blok dışı) | 14233 | 3.08 | 27.4% | 8.1% | -0.58 | -0.70 | +0.12 [+0.06; +0.18] | -0.01 [-0.03; +0.01] | -0.02 [-0.04; +0.00] | 61% / +0.16 (n=8653) |
| M5 GBM kuantil (q=0.7, 433 özellik) [net−taban] | B1 (20 Tem–18 Ağu) | 6110 | 3.12 | 29.7% | 8.8% | -0.56 | -0.87 | +0.32 [+0.24; +0.39] | -0.02 [-0.05; +0.02] | -0.01 [-0.05; +0.02] | 53% / +0.62 (n=3233) |
| M5 GBM kuantil (q=0.7, 433 özellik) [net−taban] | B2 (19 Ağu–17 Eyl) | 6797 | 2.91 | 28.7% | 9.1% | -0.51 | -0.61 | +0.10 [+0.01; +0.19] | +0.00 [-0.02; +0.02] | -0.00 [-0.03; +0.02] | 53% / +0.14 (n=3589) |
| M5 GBM kuantil (q=0.7, 433 özellik) [net−taban] | B3 (18 Eyl–16 Eki) | 7436 | 3.03 | 28.3% | 8.3% | -0.62 | -0.77 | +0.16 [+0.06; +0.25] | +0.00 [-0.02; +0.03] | -0.01 [-0.03; +0.02] | 55% / +0.25 (n=4121) |
| M5 GBM kuantil (q=0.7, 433 özellik) [net−taban] | OOS (ilk blok dışı) | 14233 | 2.97 | 28.5% | 8.7% | -0.57 | -0.70 | +0.13 [+0.06; +0.20] | +0.00 [-0.01; +0.02] | -0.01 [-0.02; +0.01] | 54% / +0.20 (n=7710) |
| ref: ATR-yalnız kuantil (q=0.7) [net−taban] | B1 (20 Tem–18 Ağu) | 6110 | 3.17 | 30.0% | 7.9% | -0.57 | -0.88 | +0.31 [+0.23; +0.40] | -0.03 [-0.06; +0.01] | -0.02 [-0.06; +0.03] | 54% / +0.47 (n=3319) |
| ref: ATR-yalnız kuantil (q=0.7) [net−taban] | B2 (19 Ağu–17 Eyl) | 6797 | 2.86 | 29.3% | 9.3% | -0.53 | -0.61 | +0.08 [+0.00; +0.16] | -0.01 [-0.03; +0.01] | -0.02 [-0.05; +0.00] | 48% / +0.09 (n=3281) |
| ref: ATR-yalnız kuantil (q=0.7) [net−taban] | B3 (18 Eyl–16 Eki) | 7436 | 2.95 | 29.4% | 8.5% | -0.61 | -0.77 | +0.16 [+0.07; +0.25] | +0.01 [-0.02; +0.04] | -0.00 [-0.03; +0.02] | 50% / +0.26 (n=3731) |
| ref: ATR-yalnız kuantil (q=0.7) [net−taban] | OOS (ilk blok dışı) | 14233 | 2.91 | 29.3% | 8.9% | -0.57 | -0.69 | +0.12 [+0.06; +0.19] | -0.00 [-0.02; +0.02] | -0.01 [-0.03; +0.01] | 49% / +0.18 (n=7012) |


İndikatör katkısı (özellikli kuantil model − ATR-yalnız kuantil referansı):

| model (özellikli) | dilim | n | Δnet vs ATR-yalnız ref [95] | Δ(net−taban) vs ATR-yalnız ref [95] |
|---|---|---|---|---|
| M4 doğrusal kuantil (q=0.4, 5 özellik) [net] | B1 (20 Tem–18 Ağu) | 6110 | -0.00 [-0.01; +0.01] | +0.00 [-0.01; +0.02] |
| M4 doğrusal kuantil (q=0.4, 5 özellik) [net] | B2 (19 Ağu–17 Eyl) | 6797 | +0.00 [-0.00; +0.01] | +0.01 [+0.00; +0.02] |
| M4 doğrusal kuantil (q=0.4, 5 özellik) [net] | B3 (18 Eyl–16 Eki) | 7436 | -0.01 [-0.02; +0.01] | +0.01 [-0.01; +0.02] |
| M4 doğrusal kuantil (q=0.4, 5 özellik) [net] | OOS (ilk blok dışı) | 14233 | -0.00 [-0.01; +0.01] | +0.01 [+0.00; +0.02] |
| M5 GBM kuantil (q=0.5, 433 özellik) [net] | B1 (20 Tem–18 Ağu) | 6110 | +0.01 [-0.02; +0.04] | +0.06 [+0.03; +0.09] |
| M5 GBM kuantil (q=0.5, 433 özellik) [net] | B2 (19 Ağu–17 Eyl) | 6797 | -0.00 [-0.03; +0.02] | +0.02 [-0.00; +0.05] |
| M5 GBM kuantil (q=0.5, 433 özellik) [net] | B3 (18 Eyl–16 Eki) | 7436 | -0.04 [-0.07; -0.02] | +0.00 [-0.02; +0.03] |
| M5 GBM kuantil (q=0.5, 433 özellik) [net] | OOS (ilk blok dışı) | 14233 | -0.02 [-0.04; -0.01] | +0.01 [-0.00; +0.03] |
| M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban] | B1 (20 Tem–18 Ağu) | 6110 | +0.00 [-0.02; +0.02] | -0.00 [-0.02; +0.02] |
| M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban] | B2 (19 Ağu–17 Eyl) | 6797 | -0.00 [-0.02; +0.01] | +0.00 [-0.02; +0.02] |
| M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban] | B3 (18 Eyl–16 Eki) | 7436 | -0.01 [-0.03; +0.01] | -0.01 [-0.03; +0.01] |
| M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban] | OOS (ilk blok dışı) | 14233 | -0.01 [-0.02; +0.00] | -0.00 [-0.02; +0.01] |
| M5 GBM kuantil (q=0.7, 433 özellik) [net−taban] | B1 (20 Tem–18 Ağu) | 6110 | +0.01 [-0.01; +0.03] | +0.00 [-0.02; +0.03] |
| M5 GBM kuantil (q=0.7, 433 özellik) [net−taban] | B2 (19 Ağu–17 Eyl) | 6797 | +0.02 [+0.00; +0.03] | +0.02 [+0.00; +0.04] |
| M5 GBM kuantil (q=0.7, 433 özellik) [net−taban] | B3 (18 Eyl–16 Eki) | 7436 | -0.00 [-0.02; +0.02] | -0.00 [-0.02; +0.01] |
| M5 GBM kuantil (q=0.7, 433 özellik) [net−taban] | OOS (ilk blok dışı) | 14233 | +0.01 [-0.01; +0.02] | +0.01 [-0.01; +0.02] |


Hedef doğruluğu (kuantil modelleri):

| model | dilim | n | q | P(MFE ≥ hedef) (kalibrasyon) | Spearman(hedef, MFE) | kısmi (ATR sabit) [t] | pinball | pinball iyileşme vs ATR-yalnız (aynı q) |
|---|---|---|---|---|---|---|---|---|
| M4 doğrusal kuantil (q=0.4, 5 özellik) [net] | B1 (20 Tem–18 Ağu) | 6110 | 0.40 | 55.5% (hedef 60%) | +0.361 | +0.130 [t +9.8] | 0.945 | +0.7% |
| M4 doğrusal kuantil (q=0.4, 5 özellik) [net] | B2 (19 Ağu–17 Eyl) | 6797 | 0.40 | 53.5% (hedef 60%) | +0.296 | +0.103 [t +8.4] | 0.814 | +0.2% |
| M4 doğrusal kuantil (q=0.4, 5 özellik) [net] | B3 (18 Eyl–16 Eki) | 7436 | 0.40 | 54.3% (hedef 60%) | +0.303 | +0.097 [t +7.0] | 0.848 | +0.4% |
| M5 GBM kuantil (q=0.5, 433 özellik) [net] | B1 (20 Tem–18 Ağu) | 6110 | 0.50 | 48.4% (hedef 50%) | +0.471 | +0.368 [t +30.9] | 1.028 | – |
| M5 GBM kuantil (q=0.5, 433 özellik) [net] | B2 (19 Ağu–17 Eyl) | 6797 | 0.50 | 46.4% (hedef 50%) | +0.314 | +0.143 [t +11.1] | 0.922 | – |
| M5 GBM kuantil (q=0.5, 433 özellik) [net] | B3 (18 Eyl–16 Eki) | 7436 | 0.50 | 46.8% (hedef 50%) | +0.298 | +0.104 [t +7.5] | 0.962 | – |
| ref: ATR-yalnız kuantil (q=0.4) [net] | B1 (20 Tem–18 Ağu) | 6110 | 0.40 | 56.0% (hedef 60%) | +0.324 | -0.044 [t -3.2] | 0.952 | – |
| ref: ATR-yalnız kuantil (q=0.4) [net] | B2 (19 Ağu–17 Eyl) | 6797 | 0.40 | 55.1% (hedef 60%) | +0.272 | -0.009 [t -0.7] | 0.816 | – |
| ref: ATR-yalnız kuantil (q=0.4) [net] | B3 (18 Eyl–16 Eki) | 7436 | 0.40 | 56.2% (hedef 60%) | +0.278 | -0.040 [t -2.9] | 0.851 | – |
| M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban] | B1 (20 Tem–18 Ağu) | 6110 | 0.70 | 30.0% (hedef 30%) | +0.369 | +0.151 [t +14.6] | 1.158 | +1.5% |
| M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban] | B2 (19 Ağu–17 Eyl) | 6797 | 0.70 | 27.2% (hedef 30%) | +0.310 | +0.134 [t +9.9] | 0.998 | +1.1% |
| M4 doğrusal kuantil (q=0.7, 5 özellik) [net−taban] | B3 (18 Eyl–16 Eki) | 7436 | 0.70 | 27.5% (hedef 30%) | +0.308 | +0.111 [t +8.2] | 1.044 | +0.4% |
| M5 GBM kuantil (q=0.7, 433 özellik) [net−taban] | B1 (20 Tem–18 Ağu) | 6110 | 0.70 | 29.7% (hedef 30%) | +0.462 | +0.346 [t +29.8] | 1.086 | +7.6% |
| M5 GBM kuantil (q=0.7, 433 özellik) [net−taban] | B2 (19 Ağu–17 Eyl) | 6797 | 0.70 | 28.7% (hedef 30%) | +0.325 | +0.165 [t +13.1] | 0.990 | +2.0% |
| M5 GBM kuantil (q=0.7, 433 özellik) [net−taban] | B3 (18 Eyl–16 Eki) | 7436 | 0.70 | 28.3% (hedef 30%) | +0.312 | +0.129 [t +9.6] | 1.038 | +1.0% |
| ref: ATR-yalnız kuantil (q=0.7) [net−taban] | B1 (20 Tem–18 Ağu) | 6110 | 0.70 | 30.0% (hedef 30%) | +0.337 | -0.002 [t -0.1] | 1.176 | – |
| ref: ATR-yalnız kuantil (q=0.7) [net−taban] | B2 (19 Ağu–17 Eyl) | 6797 | 0.70 | 29.3% (hedef 30%) | +0.287 | -0.007 [t -0.8] | 1.010 | – |
| ref: ATR-yalnız kuantil (q=0.7) [net−taban] | B3 (18 Eyl–16 Eki) | 7436 | 0.70 | 29.4% (hedef 30%) | +0.293 | -0.018 [t -2.6] | 1.048 | – |


## 5. Sınırlar

- **Çoklu karşılaştırma:** yüzlerce özellik × 4–7 sonuç × 2 nüfus × 2 kapsam; BH q özellikler arası uygulandı, ama sonuçlar arası değil. Seçilen kurallar/ayarlar tek bir seçim dönemine uyar; yalnız
  seçim-dışı bloklardaki dokunulmamış sonuçlar kanıt sayılmalı. t>2 tek başına kanıt değildir (bkz. aşırı uyum tanısı).
- **Tek piyasa dönemi:** 90 gün / 30 gün; rejim değişimi (özellikle son blok) genellenebilirliği sınırlar. Gün kümeleri bağımsız sayılmıştır; bloklar arası bağımlılık (rejim) ölçülmedi.
- **Bildirim nüfusu küçük:** 2007 olay (seçim 1522, değerlendirme 485), yeni teyit kuralı alt kümesi 416 (değerlendirme ≈ 78): güç düşük; sıfır bulgu "etki yok" kanıtı değildir.
- **Taban:** oynaklık-eşleşmiş rastgele giriş (ATR ±%25); sinyal yakınındaki bilgi (ör. aynı gün hareketli semboller) tamamen eşleşmez. HA'da taban bloğun tüm 5 dk anlarından, sinyallerden ≥ 2 sa uzak seçilir.
- **Gerçekçilik:** rescan canlıyı birebir üretmez; 60 sn gecikme ve %0,15 kayma varsayım. Hit/net bir sembolün 1 dk verisine dayanır; boşluklu dakika düz mum sayıldı.
- **Klasik fikir eşikleri** (ADX 25, Choppiness 38,2 vb.) literatür varsayılanıdır, bu veride ayarlanmadı; "SuperTrend kümesi" = (10,1)-(11,2)-(12,3); VWAP oturumu UTC günü; "FVG/OB içinde" = bu barda önceki açık
  boşluğa/bölgeye giriş; "süpürme sonrası" = son 3/12 barda dip süpürmesi; "eşit tepe" = son iki onaylı tepe ATR·0,15 içinde.
- **Hedef modelleri:** tek hedef ufku (60 dk); kuantil regresyon az örnekli bildirim nüfusunda (≈1500 eğitim) kararsız; GBM tüm özellikleri kullanır ve aşırı uyuma en yatkın modeldir.
- Bu çalışma yönlü edge aramaz; sinyal gerçek (şansın üstünde) ama maliyet sonrası net negatif olduğu önceki çalışmalarda gösterildi. Filtre/hedef yalnız "daha az negatif" ya da pozitif yapabilir.