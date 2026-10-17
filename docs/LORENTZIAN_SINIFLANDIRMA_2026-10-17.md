# Lorentzian Classification (kNN) — tahmin motoru çalışması (2026-10-17)

Çevrimdışı araştırma (`scripts/lorentzian_study.py`, `app/rescan/lorentzian.py`, `tests/test_lorentzian.py`); canlı koda bağlanmaz, DB'ye yazmaz.

## 0. Hüküm

**Karar: HAYIR — Lorentzian Classification (ne orijinal hali ne bizim etiketli kNN varyantı) tarayıcıları güçlendirmiyor ve ana tahmin motoruna alınmamalı.** 90 gün, 3 yürüyen-ileri blok, 306 sembol, yalnız 24 sa quote hacmi ≥ 5M TRY anları: hiçbir küme (orijinal, kNN-B, HGB, HA) mutlak net pozitif değil; oynaklık-eşleşmiş rastgele girişe göre de hiçbiri anlamlı pozitif değil (orijinal anlamlı NEGATİF: Δnet −0,06…−0,10 puan, ▼).

- **Orijinal betik (5 dk):** 1 100–1 450 giriş/gün (HA ~200/gün), 4 bar sonrası yükseliş isabeti %42–45 (rastgele %49–51 — yani yön olarak şansın ALTINDA), hit60@%1,5 lifti −1,8…+0,7 pp (anlamsız), ROC-AUC 0,50–0,53. Betikteki etiket kodu aslında GEÇMİŞ 4 barın tersi (niyet "4 bar sonrası"); iki kip de (pine/future) aynı sonucu verdi. 1 dk'da (60 sembol) da aynı: lift ≈ 0, Δnet −0,02…−0,05.
- **kNN-B (bizim etiket, sembol başına 2000 bar):** AUC 0,52–0,55, hit lifti ≈ 0, Δnet ≈ 0 (−0,10…+0,03; hiçbiri anlamlı pozitif değil). Sembol-içi kNN, olay etiketine bile gücünü taşıyamıyor.
- **Motor karşılaştırması (olay etiketi, aynı örnek):** AUC'nin neredeyse tamamı OYNAKLIK: yalnız ATR14% AUC 0,74; HGB 0,75; havuzlanmış kNN-Lorentzian 0,73; kNN-B 0,53; orijinal 0,50–0,53. ATR üçte birlikleri İÇİNDE: HGB 0,64 > yalnız-ATR 0,605 > havuz kNN-Lorentzian 0,594 > kNN-B 0,52–0,54. Yani kNN-Lorentzian gradient boosting'ten İYİ DEĞİL (aynı veriyle bile daha zayıf; ATR'nin üzerine bilgi eklemiyor); HGB'nin ATR üstü katkısı küçük (+0,036 AUC) ve net'e dönüşmüyor (HGB üst %0,25: hit %77 ama Δnet vs oynaklık-eşl. −0,13/−0,19 — yüksek hit oynaklık eseri, maliyet ve SL3 yiyor).
- **HA ile ilişki:** orijinal sinyallerin yalnız %7–9'u ±60 dk içinde HA ile örtüşüyor; HA'sız (eklenen) sinyallerin Δnet'i −0,10…−0,13 (▼) → yeni, işe yarar bir sinyal kaynağı değil. HGB/kNN-B üst dilimleri HA ile %90+ örtüşüyor (ikisi de yüksek oynaklık/hız anlarını seçiyor), HA'dan önce gelme avantajı yok (medyan HA +10…30 dk SONRA).
- **HA filtresi olarak:** 6 filtre × 3 blok; tutulan − düşen farkı tutarlı biçimde pozitif değil (OL-future pred>0: Δfazla −0,16 ▼; HGB B3: Δnet −0,30 ▼; kNN-B üst %20: B2 +0,20 ▲ ama B3 +0,05, Δnet ≈ 0). Mutlak net hiçbirinde pozitif değil.
- **Maliyet gerçeği:** gidiş-dönüş yaklaşık %0,53 (kayma+ücret); HA'nın bile hit60 liftine (+26 pp) rağmen TP1,5/SL3/T60 net'i −0,50…−0,56.

Öneri: Lorentzian'ı tarayıcıya ya da tahmin motoruna EKLEME (kod `app/rescan/lorentzian.py`'de duruyor, canlıya bağlı değil). Tahmin motoru aranıyorsa kıyas çizgisi "yalnız ATR + HGB"; kNN-Lorentzian ona bir şey katmıyor.

### 0a. Özet tablo (blok başına; yürüyen ileri; yalnız 24 sa quote hacmi ≥ 5M TRY anları)

Sütunlar: yükseliş % = sinyalden 4 bar (20 dk) sonra kapanış > sinyal kapanışı oranı (parantez: aynı sembol+saat rastgele). hit60@1,5 = 1 dk yolda giriş (sinyal+60 sn → sonraki 1 dk açılışı) sonrası 60 dk içinde yüksek ≥ +%1,5. lift = sinyal − saat-eşleşmiş rastgele (pp). net = exit_sim (0,15% kayma, 0,1125%/bacak): TP1,5/SL3/T60 ve iz (act1,0/gap0,8/SL3/T60); Δnet = sinyal − rastgele (SE: gün-kümeli, bağımsız kabul). ▲/▼ = %95 aralık 0'ı dışlıyor.

**B1 20.07-18.08** (30 gün)

| Küme | sinyal/gün | yükseliş % (rastg.) | hit60@1,5 % (rastg.) | lift pp vs saat-rastg. (SE) | lift pp vs oynaklık-eşl. (SE) | net TP % | Δnet TP vs saat-rastg. | Δnet TP vs oynaklık-eşl. | net iz % | Δnet iz vs oynaklık-eşl. |
|---|---|---|---|---|---|---|---|---|---|---|
| OL-pine | 1102.7 | 42.6 (49.1) | 10.6 (11.4) | -0.8 (0.5) | +0.1 (0.4) | -0.56 | -0.06 (0.02) ▼ | -0.09 (0.02) ▼ | -0.57 | -0.09 (0.01) ▼ |
| OL-future | 593.0 | 42.2 (48.9) | 11.8 (11.1) | +0.7 (0.4) | +0.6 (0.5) | -0.56 | -0.05 (0.02) ▼ | -0.08 (0.02) ▼ | -0.58 | -0.08 (0.02) ▼ |
| kNN-B q0.25% | 0.0 | – | – | – | – | – | – | – | – | – |
| HGB q0.25% | 0.0 | – | – | – | – | – | – | – | – | – |
| HA | 201.0 | 43.2 (48.7) | 51.2 (25.4) | +25.8 (0.9) ▲ | +3.7 (1.1) ▲ | -0.54 | -0.09 (0.03) ▼ | -0.12 (0.03) ▼ | -0.54 | -0.11 (0.03) ▼ |
| Rastgele (saat-eşl., HA örneği) | – | 48.7 | 25.4 | – | – | -0.45 | – | – | -0.48 | – |
| Rastgele (saat+oynaklık-eşl., HA örneği) | – | – | 47.5 | – | – | -0.42 | – | – | -0.43 | – |

**B2 19.08-17.09** (30 gün)

| Küme | sinyal/gün | yükseliş % (rastg.) | hit60@1,5 % (rastg.) | lift pp vs saat-rastg. (SE) | lift pp vs oynaklık-eşl. (SE) | net TP % | Δnet TP vs saat-rastg. | Δnet TP vs oynaklık-eşl. | net iz % | Δnet iz vs oynaklık-eşl. |
|---|---|---|---|---|---|---|---|---|---|---|
| OL-pine | 1335.0 | 45.3 (51.0) | 12.7 (14.5) | -1.8 (1.1) | -0.5 (1.0) | -0.55 | -0.08 (0.03) ▼ | -0.10 (0.03) ▼ | -0.56 | -0.10 (0.03) ▼ |
| OL-future | 732.1 | 45.2 (50.7) | 14.0 (14.3) | -0.2 (1.2) | +0.1 (1.2) | -0.54 | -0.06 (0.03) | -0.09 (0.03) ▼ | -0.56 | -0.09 (0.03) ▼ |
| kNN-B q0.25% | 68.5 | 50.4 (48.2) | 23.6 (22.9) | +0.7 (2.1) | -0.3 (1.9) | -0.48 | -0.03 (0.04) | -0.00 (0.04) | -0.50 | +0.01 (0.04) |
| HGB q0.25% | 9.8 | 42.3 (48.1) | 77.6 (24.2) | +53.4 (3.2) ▲ | +4.2 (3.0) | -0.71 | -0.14 (0.12) | -0.13 (0.14) | -0.73 | -0.22 (0.16) |
| HA | 224.3 | 46.3 (50.0) | 48.9 (23.0) | +25.9 (1.2) ▲ | +3.9 (1.4) ▲ | -0.50 | -0.04 (0.03) | -0.09 (0.04) ▼ | -0.54 | -0.13 (0.03) ▼ |
| Rastgele (saat-eşl., HA örneği) | – | 50.0 | 23.0 | – | – | -0.46 | – | – | -0.48 | – |
| Rastgele (saat+oynaklık-eşl., HA örneği) | – | – | 44.9 | – | – | -0.42 | – | – | -0.41 | – |

**B3 18.09-16.10** (29 gün)

| Küme | sinyal/gün | yükseliş % (rastg.) | hit60@1,5 % (rastg.) | lift pp vs saat-rastg. (SE) | lift pp vs oynaklık-eşl. (SE) | net TP % | Δnet TP vs saat-rastg. | Δnet TP vs oynaklık-eşl. | net iz % | Δnet iz vs oynaklık-eşl. |
|---|---|---|---|---|---|---|---|---|---|---|
| OL-pine | 1457.7 | 44.8 (50.7) | 13.7 (14.7) | -1.0 (0.9) | -0.1 (0.8) | -0.53 | -0.05 (0.03) | -0.08 (0.03) ▼ | -0.53 | -0.08 (0.03) ▼ |
| OL-future | 813.3 | 44.8 (50.3) | 14.8 (14.7) | +0.1 (0.9) | +0.4 (0.9) | -0.52 | -0.03 (0.03) | -0.06 (0.03) ▼ | -0.52 | -0.06 (0.03) |
| kNN-B q0.25% | 72.8 | 45.3 (48.9) | 20.5 (20.1) | +0.4 (1.6) | -1.0 (1.5) | -0.54 | -0.04 (0.04) | -0.10 (0.04) ▼ | -0.55 | -0.09 (0.04) ▼ |
| HGB q0.25% | 28.7 | 45.5 (46.3) | 76.7 (23.9) | +52.8 (1.9) ▲ | +2.0 (2.0) | -0.52 | +0.01 (0.10) | -0.19 (0.12) | -0.46 | -0.19 (0.11) |
| HA | 253.4 | 43.1 (48.8) | 49.5 (23.5) | +26.0 (1.0) ▲ | +3.3 (1.2) ▲ | -0.56 | -0.08 (0.04) ▼ | -0.13 (0.04) ▼ | -0.55 | -0.12 (0.03) ▼ |
| Rastgele (saat-eşl., HA örneği) | – | 48.8 | 23.5 | – | – | -0.48 | – | – | -0.49 | – |
| Rastgele (saat+oynaklık-eşl., HA örneği) | – | – | 46.1 | – | – | -0.44 | – | – | -0.42 | – |

### 0b. Bar düzeyi ayrım gücü (ROC-AUC; tüm likit barlar)

| Blok | skor | AUC (60 dk olay ≥%1,5) | AUC (4 bar yükseliş) | pred>0: yükseliş doğruluğu | pred<0: düşüş doğruluğu | olay oranı pred>0 / pred≤0 |
|---|---|---|---|---|---|---|
| B1 | Orijinal (future etiket) | 0.518 | 0.482 | 46.9 | 50.0 | 12.0 / 10.8 |
| B1 | Orijinal (pine etiket) | 0.515 | 0.454 | 43.8 | 47.6 | 12.0 / 10.8 |
| B1 | kNN-B (olay etiketi) | 0.617 | 0.501 | – | – | – |
| B1 | (taban) | olay oranı 11.3 % | yükseliş oranı 48.5 % | | | |
| B2 | Orijinal (future etiket) | 0.500 | 0.484 | 48.8 | 48.4 | 14.0 / 14.1 |
| B2 | Orijinal (pine etiket) | 0.514 | 0.457 | 46.1 | 46.1 | 14.8 / 13.4 |
| B2 | kNN-B (olay etiketi) | 0.525 | 0.494 | – | – | – |
| B2 | HGB (olay etiketi) | 0.752 | 0.493 | – | – | – |
| B2 | (taban) | olay oranı 14.1 % | yükseliş oranı 50.2 % | | | |
| B3 | Orijinal (future etiket) | 0.502 | 0.487 | 49.0 | 48.8 | 14.5 / 14.4 |
| B3 | Orijinal (pine etiket) | 0.507 | 0.462 | 46.4 | 46.7 | 14.8 / 14.2 |
| B3 | kNN-B (olay etiketi) | 0.548 | 0.499 | – | – | – |
| B3 | HGB (olay etiketi) | 0.752 | 0.488 | – | – | – |
| B3 | (taban) | olay oranı 14.5 % | yükseliş oranı 50.0 % | | | |

### 0c. Motor karşılaştırması: kNN-Lorentzian mı HistGradientBoosting mı? (aynı saatlik örnek, 60 dk olay etiketi)

Yalnız olay etiketi için sıralama gücü. 'ATR içi AUC' = ATR14% üçte birlikleri içinde AUC'lerin ortalaması (oynaklık etkisi arındırılmış). Üst-q isabet = skoru en yüksek q payındaki olay oranı (taban olay oranı ile kıyasla).

| Blok | Skor | AUC | ATR içi AUC (düşük/orta/yüksek) | isabet üst %0,25 | üst %1 | üst %5 |
|---|---|---|---|---|---|---|
| B2 | ATR14% (tek özellik) | 0.741 | 0.605 (0.593 / 0.564 / 0.657) | 67.9 | 64.3 | 50.7 |
| B2 | HGB (7 özellik, havuz) | 0.751 | 0.641 (0.652 / 0.599 / 0.671) | 73.8 | 66.2 | 51.8 |
| B2 | kNN-Lorentzian havuz (7 özellik) | 0.726 | 0.593 (0.568 / 0.557 / 0.653) | 67.2 | 63.4 | 50.4 |
| B2 | kNN-B (sembol başına 2000 bar) | 0.525 | 0.518 (0.560 / 0.503 / 0.492) | 23.0 | 22.8 | 20.7 |
| B2 | Orijinal (future etiket) | 0.504 | 0.502 (0.490 / 0.512 / 0.503) | 15.1 | 14.5 | 14.3 |
| B2 | Orijinal (pine etiket) | 0.528 | 0.530 (0.524 / 0.533 / 0.533) | 15.6 | 15.6 | 15.6 |
| B2 | taban olay oranı 14.1 % (yalnız-ATR üst %0,25/%1/%5: 67.9 / 64.3 / 50.7) | | | | | |
| B3 | ATR14% (tek özellik) | 0.746 | 0.607 (0.592 / 0.572 / 0.656) | 74.1 | 68.3 | 51.9 |
| B3 | HGB (7 özellik, havuz) | 0.756 | 0.641 (0.653 / 0.598 / 0.671) | 76.6 | 69.9 | 54.0 |
| B3 | kNN-Lorentzian havuz (7 özellik) | 0.732 | 0.595 (0.579 / 0.553 / 0.653) | 68.4 | 65.0 | 52.3 |
| B3 | kNN-B (sembol başına 2000 bar) | 0.547 | 0.535 (0.581 / 0.529 / 0.495) | 20.4 | 19.6 | 20.6 |
| B3 | Orijinal (future etiket) | 0.501 | 0.502 (0.499 / 0.505 / 0.503) | 15.9 | 15.8 | 14.8 |
| B3 | Orijinal (pine etiket) | 0.508 | 0.522 (0.515 / 0.530 / 0.522) | 15.3 | 15.3 | 15.3 |
| B3 | taban olay oranı 14.6 % (yalnız-ATR üst %0,25/%1/%5: 74.1 / 68.3 / 51.9) | | | | | |

## 1. Yöntem

- **Orijinal betik (OL)**: jdehorty `Lorentzian Classification` (MLExtensions/KernelFunctions kaynak okundu). Özellikler RSI(14,1), WT(10,11), CCI(20,1), ADX(20,2), RSI(9,1); Lorentzian mesafe Σlog(1+|xi−yi|); ANN döngüsü birebir (`d ≥ lastDistance ∧ i%4≠0`, k=8, `lastDistance = distances[round(k·3/4)]`, en eskiyi at), pencere 2000 bar (kayan), tahmin = komşu etiket toplamı; filtreler: volatilite (ATR1 > ATR10) + rejim (KLMF eğim ≥ −0,1); ADX/EMA/SMA filtreleri kapalı; çekirdek RQK (h=8, r=8, x=25) boğa; giriş = sinyalin LONG'a DÖNDÜĞÜ bar ∧ çekirdek boğa. Nedensellik: kesme-değişmezliği testle doğrulandı.
- **Etiket bulgusu (önemli)**: betik kodunda `y_train_series = src[4] < src[0] ? SHORT : src[4] > src[0] ? LONG` ve etiket AYNI barın özellikleriyle saklanır → etiket GEÇMİŞ 4 barlık hareketin TERSİDİR (gecikmesiz; "4 bar sonrası" niyetine rağmen). İki kip de ölçüldü: **OL-pine** = betiğin gerçekte yaptığı (y[j]=sign(c[j−4]−c[j]), geçmiş j≤t); **OL-future** = belgelenen niyet (y[j]=sign(c[j+4]−c[j]), etiketi bilinen j≤t−4).
- **Varyant B (kNN-B)**: aynı ANN/Lorentzian makinesi; etiket = bizim olay (t+1 açılışından 60 dk içinde yüksek ≥ +%1,5; t+12'de bilinir → gecikme 12 bar); 7 özellik (5m ATR14%, ret1, ret10, EMA50/99 farkı, taker alış payı 3 bar, hacim oranı, range_pos24) — geçmiş 2000 barlık z-skoruyla [0,1]'e nedensel ölçeklenir. Skor = komşuların olay sayısı (0–8), eşit skorlarda daha yakın komşular öne.
- **HGB**: sklearn HistGradientBoosting (150 iterasyon, 31 yaprak), AYNI 7 özellik (ham), havuzlanmış tüm semboller; B2 ← B1, B3 ← B1+B2 (her seferinde önceki bloğun SON 5 günü + 12 bar tecrit eğitimden çıkarılır; eşik o 5 günün skorlarından seçilir). B1 için eğitim verisi yok → HGB B1'de YOK.
- **Eşik (kNN-B, HGB)**: "üst q" = likit bar-anların en yüksek skorlu %q'su; kNN-B için eşik ÖNCEKİ bloğun skor dağılımından, HGB için bekletme günlerinden; B1'de kNN-B için önceki blok olmadığından yok. Ana satır q=%0,25 (≈ HA sıklığı), %0,1 ve %1 detayda. Sinyal sonrası aynı sembolde 60 dk soğuma (tüm kümelere; OL'nin ham giriş sayısı ayrıca verilir).
- **Rastgele taban**: sinyal başına 2 rastgele giriş: aynı sembol, aynı blok, aynı yerel saat, likit (ve oynaklık-eşleşmiş sürüm: ayrıca 5m ATR14% ±%25). Net: exit_sim, 60 sn gecikme, %0,15 kayma, %0,1125/bacak; gün-kümeli SE.
- **HA**: `work/indfilter/events_ha.pkl` (rank ≤ 10, aşırı alımda değil, 60 dk bölüm) → likit olanlar; aynı exit_sim (HA'nın kendi hedefiyle değil, tüm kümeler için aynı TP1,5/SL3/T60 ve iz). HA filtresi bölümü HA'nın KENDİ hedefini ve indfilter oynaklık-eşleşmiş tabanını kullanır.

## 2. Ayrıntı — tüm kümeler

**B1 20.07-18.08**

| Küme | sinyal/gün | yükseliş % (rastg.) | hit60@1,5 % (rastg.) | lift pp vs saat-rastg. (SE) | lift pp vs oynaklık-eşl. (SE) | net TP % | Δnet TP vs saat-rastg. | Δnet TP vs oynaklık-eşl. | net iz % | Δnet iz vs oynaklık-eşl. |
|---|---|---|---|---|---|---|---|---|---|---|
| OL-pine | 1102.7 | 42.6 (49.1) | 10.6 (11.4) | -0.8 (0.5) | +0.1 (0.4) | -0.56 | -0.06 (0.02) ▼ | -0.09 (0.02) ▼ | -0.57 | -0.09 (0.01) ▼ |
| OL-future | 593.0 | 42.2 (48.9) | 11.8 (11.1) | +0.7 (0.4) | +0.6 (0.5) | -0.56 | -0.05 (0.02) ▼ | -0.08 (0.02) ▼ | -0.58 | -0.08 (0.02) ▼ |
| kNN-B q0.1% | 0.0 | – | – | – | – | – | – | – | – | – |
| kNN-B q0.25% | 0.0 | – | – | – | – | – | – | – | – | – |
| kNN-B q1% | 0.0 | – | – | – | – | – | – | – | – | – |
| HGB q0.1% | 0.0 | – | – | – | – | – | – | – | – | – |
| HGB q0.25% | 0.0 | – | – | – | – | – | – | – | – | – |
| HGB q1% | 0.0 | – | – | – | – | – | – | – | – | – |
| HA | 201.0 | 43.2 (48.7) | 51.2 (25.4) | +25.8 (0.9) ▲ | +3.7 (1.1) ▲ | -0.54 | -0.09 (0.03) ▼ | -0.12 (0.03) ▼ | -0.54 | -0.11 (0.03) ▼ |

**B2 19.08-17.09**

| Küme | sinyal/gün | yükseliş % (rastg.) | hit60@1,5 % (rastg.) | lift pp vs saat-rastg. (SE) | lift pp vs oynaklık-eşl. (SE) | net TP % | Δnet TP vs saat-rastg. | Δnet TP vs oynaklık-eşl. | net iz % | Δnet iz vs oynaklık-eşl. |
|---|---|---|---|---|---|---|---|---|---|---|
| OL-pine | 1335.0 | 45.3 (51.0) | 12.7 (14.5) | -1.8 (1.1) | -0.5 (1.0) | -0.55 | -0.08 (0.03) ▼ | -0.10 (0.03) ▼ | -0.56 | -0.10 (0.03) ▼ |
| OL-future | 732.1 | 45.2 (50.7) | 14.0 (14.3) | -0.2 (1.2) | +0.1 (1.2) | -0.54 | -0.06 (0.03) | -0.09 (0.03) ▼ | -0.56 | -0.09 (0.03) ▼ |
| kNN-B q0.1% | 28.3 | 52.1 (48.5) | 25.8 (23.7) | +2.1 (2.4) | +0.6 (2.5) | -0.47 | +0.00 (0.06) | -0.02 (0.06) | -0.48 | +0.01 (0.06) |
| kNN-B q0.25% | 68.5 | 50.4 (48.2) | 23.6 (22.9) | +0.7 (2.1) | -0.3 (1.9) | -0.48 | -0.03 (0.04) | -0.00 (0.04) | -0.50 | +0.01 (0.04) |
| kNN-B q1% | 179.5 | 50.2 (50.5) | 21.9 (20.6) | +1.3 (1.7) | +0.1 (1.6) | -0.48 | +0.00 (0.03) | -0.01 (0.03) | -0.49 | -0.01 (0.03) |
| HGB q0.1% | 5.7 | 43.2 (51.5) | 77.3 (27.3) | +50.0 (4.5) ▲ | +2.3 (4.4) | -0.85 | -0.38 (0.20) | -0.21 (0.21) | -0.82 | -0.39 (0.23) |
| HGB q0.25% | 9.8 | 42.3 (48.1) | 77.6 (24.2) | +53.4 (3.2) ▲ | +4.2 (3.0) | -0.71 | -0.14 (0.12) | -0.13 (0.14) | -0.73 | -0.22 (0.16) |
| HGB q1% | 36.8 | 47.5 (46.8) | 70.4 (25.1) | +45.3 (1.7) ▲ | +0.9 (1.7) | -0.60 | -0.08 (0.06) | -0.17 (0.07) ▼ | -0.51 | -0.17 (0.09) ▼ |
| HA | 224.3 | 46.3 (50.0) | 48.9 (23.0) | +25.9 (1.2) ▲ | +3.9 (1.4) ▲ | -0.50 | -0.04 (0.03) | -0.09 (0.04) ▼ | -0.54 | -0.13 (0.03) ▼ |

**B3 18.09-16.10**

| Küme | sinyal/gün | yükseliş % (rastg.) | hit60@1,5 % (rastg.) | lift pp vs saat-rastg. (SE) | lift pp vs oynaklık-eşl. (SE) | net TP % | Δnet TP vs saat-rastg. | Δnet TP vs oynaklık-eşl. | net iz % | Δnet iz vs oynaklık-eşl. |
|---|---|---|---|---|---|---|---|---|---|---|
| OL-pine | 1457.7 | 44.8 (50.7) | 13.7 (14.7) | -1.0 (0.9) | -0.1 (0.8) | -0.53 | -0.05 (0.03) | -0.08 (0.03) ▼ | -0.53 | -0.08 (0.03) ▼ |
| OL-future | 813.3 | 44.8 (50.3) | 14.8 (14.7) | +0.1 (0.9) | +0.4 (0.9) | -0.52 | -0.03 (0.03) | -0.06 (0.03) ▼ | -0.52 | -0.06 (0.03) |
| kNN-B q0.1% | 29.6 | 47.6 (50.1) | 21.4 (20.8) | +0.6 (2.1) | +1.6 (2.2) | -0.47 | -0.00 (0.06) | +0.03 (0.06) | -0.50 | +0.01 (0.06) |
| kNN-B q0.25% | 72.8 | 45.3 (48.9) | 20.5 (20.1) | +0.4 (1.6) | -1.0 (1.5) | -0.54 | -0.04 (0.04) | -0.10 (0.04) ▼ | -0.55 | -0.09 (0.04) ▼ |
| kNN-B q1% | 200.6 | 48.1 (49.7) | 20.4 (20.6) | -0.2 (1.2) | +0.3 (1.0) | -0.51 | -0.02 (0.03) | -0.02 (0.03) | -0.52 | -0.03 (0.03) |
| HGB q0.1% | 15.0 | 48.8 (48.0) | 80.3 (25.1) | +55.2 (2.5) ▲ | +5.5 (2.3) ▲ | -0.55 | -0.02 (0.09) | -0.09 (0.12) | -0.47 | -0.09 (0.14) |
| HGB q0.25% | 28.7 | 45.5 (46.3) | 76.7 (23.9) | +52.8 (1.9) ▲ | +2.0 (2.0) | -0.52 | +0.01 (0.10) | -0.19 (0.12) | -0.46 | -0.19 (0.11) |
| HGB q1% | 103.0 | 44.6 (50.0) | 65.9 (25.8) | +40.2 (1.1) ▲ | +4.4 (1.5) ▲ | -0.56 | -0.08 (0.04) | -0.07 (0.05) | -0.55 | -0.12 (0.05) ▼ |
| HA | 253.4 | 43.1 (48.8) | 49.5 (23.5) | +26.0 (1.0) ▲ | +3.3 (1.2) ▲ | -0.56 | -0.08 (0.04) ▼ | -0.13 (0.04) ▼ | -0.55 | -0.12 (0.03) ▼ |

OL ham (soğumasız) giriş sayısı: OL-pine B1: 36732; OL-pine B2: 44114; OL-pine B3: 46909; OL-future B1: 19426; OL-future B2: 23813; OL-future B3: 25629

## 3. HA ile örtüşme ve öncelik (±60 dk)

| Küme | Blok | sinyal | HA ±60 dk içinde % | HA SONRA geldi % (medyan öncelik dk) | HA'nın bu kümece ±60 dk kapsanması % | HA'sız sinyal: Δnet TP vs oynaklık-eşl. | HA'sız: lift pp |
|---|---|---|---|---|---|---|---|
| OL-pine | B1 | 33082 | 6.7 | 5.7 (15) | 42.0 | -0.12 (0.01) ▼ | -4.6 (0.4) |
| OL-pine | B2 | 40051 | 6.5 | 5.6 (10) | 43.1 | -0.13 (0.03) ▼ | -5.0 (1.0) |
| OL-pine | B3 | 42273 | 7.1 | 6.1 (10) | 46.6 | -0.11 (0.03) ▼ | -4.6 (0.8) |
| OL-future | B1 | 17791 | 8.7 | 6.8 (15) | 30.6 | -0.12 (0.01) ▼ | -4.0 (0.3) |
| OL-future | B2 | 21964 | 8.4 | 6.4 (15) | 31.4 | -0.12 (0.03) ▼ | -4.3 (1.2) |
| OL-future | B3 | 23587 | 8.6 | 6.7 (15) | 32.3 | -0.10 (0.03) ▼ | -4.1 (0.9) |
| kNN-B q0.1% | B2 | 849 | 16.3 | 10.2 (30) | 2.3 | -0.06 (0.06) | -3.9 (2.5) |
| kNN-B q0.1% | B3 | 859 | 12.0 | 7.6 (30) | 1.6 | -0.02 (0.05) | -4.9 (1.9) |
| kNN-B q0.25% | B2 | 2054 | 16.9 | 10.1 (30) | 5.6 | -0.06 (0.04) | -6.0 (1.9) |
| kNN-B q0.25% | B3 | 2112 | 13.8 | 8.6 (30) | 4.3 | -0.13 (0.03) ▼ | -5.3 (1.5) |
| kNN-B q1% | B2 | 5385 | 13.3 | 8.3 (25) | 10.2 | -0.06 (0.03) ▼ | -4.5 (1.5) |
| kNN-B q1% | B3 | 5817 | 10.3 | 7.0 (25) | 8.4 | -0.06 (0.03) | -4.9 (1.2) |
| HGB q0.1% | B2 | 172 | 95.3 | 82.6 (30) | 3.8 | -0.41 (1.16) | +35.2 (17.9) |
| HGB q0.1% | B3 | 436 | 96.6 | 83.0 (30) | 8.1 | +0.01 (0.52) | +54.9 (8.8) |
| HGB q0.25% | B2 | 295 | 92.9 | 77.6 (30) | 6.0 | +0.29 (0.36) | +56.7 (8.8) |
| HGB q0.25% | B3 | 831 | 97.1 | 79.5 (30) | 13.9 | -0.37 (0.43) | +46.9 (7.6) |
| HGB q1% | B2 | 1103 | 91.1 | 70.1 (25) | 18.0 | -0.43 (0.20) ▼ | +37.2 (3.7) |
| HGB q1% | B3 | 2987 | 90.7 | 67.2 (25) | 39.6 | -0.56 (0.14) ▼ | +21.5 (3.3) |

## 4. HA filtresi olarak (HA'nın kendi hedefi; net − oynaklık-eşleşmiş taban; tutulan − düşen)

| Blok | Filtre | tutulan n (gün) | tutulan net | tutulan fazlası | düşen net | düşen fazlası | Δ fazla (tut−düş) | Δ net (tut−düş) |
|---|---|---|---|---|---|---|---|---|
| B1 | HA tümü | 6031 | -0.54 | +0.33 | | | | |
| B1 | OL-future pred>0 | 2978 (99.3) | -0.59 | +0.26 | -0.49 | +0.41 | -0.16 (0.08) | -0.10 (0.06) |
| B1 | OL-pine pred>0 | 4471 (149.0) | -0.55 | +0.30 | -0.49 | +0.45 | -0.15 (0.11) | -0.06 (0.08) |
| B1 | OL-future durum=LONG | 3464 (115.5) | -0.55 | +0.33 | -0.52 | +0.34 | -0.01 (0.09) | -0.03 (0.06) |
| B1 | OL-pine durum=LONG | 4425 (147.5) | -0.53 | +0.31 | -0.56 | +0.39 | -0.08 (0.11) | +0.03 (0.08) |
| B2 | HA tümü | 6728 | -0.51 | +0.11 | | | | |
| B2 | OL-future pred>0 | 3182 (106.1) | -0.56 | +0.02 | -0.47 | +0.18 | -0.16 (0.07) ▼ | -0.10 (0.06) |
| B2 | OL-pine pred>0 | 5274 (175.8) | -0.51 | +0.10 | -0.51 | +0.11 | -0.01 (0.09) | -0.01 (0.08) |
| B2 | OL-future durum=LONG | 3678 (122.6) | -0.55 | +0.04 | -0.46 | +0.20 | -0.16 (0.07) ▼ | -0.09 (0.06) |
| B2 | OL-pine durum=LONG | 5051 (168.4) | -0.51 | +0.09 | -0.51 | +0.16 | -0.08 (0.09) | +0.00 (0.08) |
| B2 | kNN-B skor >= onceki-blok 80. yuzdelik | 1739 (58.0) | -0.50 | +0.26 | -0.51 | +0.06 | +0.20 (0.07) ▲ | +0.01 (0.06) |
| B2 | HGB skor >= bekletme 80. yuzdelik | 6545 (218.2) | -0.51 | +0.11 | -0.60 | +0.00 | +0.11 (0.12) | +0.09 (0.11) |
| B3 | HA tümü | 7363 | -0.62 | +0.17 | | | | |
| B3 | OL-future pred>0 | 3816 (131.6) | -0.66 | +0.13 | -0.58 | +0.21 | -0.08 (0.08) | -0.08 (0.07) |
| B3 | OL-pine pred>0 | 5617 (193.7) | -0.62 | +0.14 | -0.63 | +0.25 | -0.11 (0.09) | +0.01 (0.07) |
| B3 | OL-future durum=LONG | 4362 (150.4) | -0.64 | +0.16 | -0.60 | +0.18 | -0.02 (0.08) | -0.04 (0.06) |
| B3 | OL-pine durum=LONG | 5349 (184.4) | -0.66 | +0.11 | -0.53 | +0.32 | -0.21 (0.09) ▼ | -0.13 (0.07) |
| B3 | kNN-B skor >= onceki-blok 80. yuzdelik | 1497 (51.6) | -0.65 | +0.20 | -0.62 | +0.16 | +0.05 (0.09) | -0.03 (0.07) |
| B3 | HGB skor >= bekletme 80. yuzdelik | 7248 (249.9) | -0.63 | +0.17 | -0.33 | +0.24 | -0.07 (0.17) | -0.30 (0.14) ▼ |

## 5. 1 dakikalık orijinal (60 likit sembol)

Aynı kod 1 dk mumlarda (pencere 2000 dk, etiket 4 dk); karar 1 dk kapanışında, giriş +60 sn sonraki 1 dk açılışı; 60 dk soğuma. Ham (soğumasız) giriş: pine 162693, future 85509.

**B1 20.07-18.08**

| Küme | sinyal/gün | yükseliş % (rastg.) | hit60@1,5 % (rastg.) | lift pp vs saat-rastg. (SE) | lift pp vs oynaklık-eşl. (SE) | net TP % | Δnet TP vs saat-rastg. | Δnet TP vs oynaklık-eşl. | net iz % | Δnet iz vs oynaklık-eşl. |
|---|---|---|---|---|---|---|---|---|---|---|
| OL1-pine | 785.9 | 45.5 (49.0) | 15.6 (15.8) | -0.2 (0.6) | +0.1 (0.5) | -0.52 | -0.02 (0.01) | -0.03 (0.01) ▼ | -0.52 | -0.02 (0.01) ▼ |
| OL1-future | 525.7 | 45.6 (49.0) | 15.2 (16.1) | -0.9 (0.5) | +0.1 (0.5) | -0.52 | -0.03 (0.01) | -0.03 (0.01) | -0.53 | -0.03 (0.01) |

**B2 19.08-17.09**

| Küme | sinyal/gün | yükseliş % (rastg.) | hit60@1,5 % (rastg.) | lift pp vs saat-rastg. (SE) | lift pp vs oynaklık-eşl. (SE) | net TP % | Δnet TP vs saat-rastg. | Δnet TP vs oynaklık-eşl. | net iz % | Δnet iz vs oynaklık-eşl. |
|---|---|---|---|---|---|---|---|---|---|---|
| OL1-pine | 843.1 | 47.0 (49.1) | 17.2 (17.7) | -0.5 (1.5) | +0.3 (1.4) | -0.49 | -0.03 (0.03) | -0.02 (0.03) | -0.50 | -0.02 (0.03) |
| OL1-future | 549.4 | 47.1 (49.5) | 16.8 (17.3) | -0.5 (1.5) | -0.0 (1.4) | -0.51 | -0.04 (0.03) | -0.04 (0.03) | -0.52 | -0.03 (0.03) |

**B3 18.09-16.10**

| Küme | sinyal/gün | yükseliş % (rastg.) | hit60@1,5 % (rastg.) | lift pp vs saat-rastg. (SE) | lift pp vs oynaklık-eşl. (SE) | net TP % | Δnet TP vs saat-rastg. | Δnet TP vs oynaklık-eşl. | net iz % | Δnet iz vs oynaklık-eşl. |
|---|---|---|---|---|---|---|---|---|---|---|
| OL1-pine | 884.9 | 47.6 (49.8) | 16.9 (17.5) | -0.6 (1.3) | +0.0 (1.2) | -0.53 | -0.05 (0.03) | -0.05 (0.03) | -0.53 | -0.05 (0.03) |
| OL1-future | 572.1 | 47.2 (48.8) | 16.9 (17.4) | -0.5 (1.3) | -0.4 (1.2) | -0.54 | -0.04 (0.03) | -0.05 (0.03) | -0.54 | -0.05 (0.03) |

## 6. Sınırlar

- Betikteki `var predictions/distances` dizilerinin barlar arası taşınması ve büyüyen dizi (yalnız son 2000 grafik barı) yerine kayan 2000 barlık pencere kullanıldı; i%4 eşlemesi mutlak bar indeksine göre.
- ADX özelliğinde ortalama `sma` (MLExtensions n_adx), RQK penceresi x+2 = 27 örnek (KernelFunctions döngüsü `0..size+x`); küçük sapmalar sonucu değiştirmez (kesin Pine çıktısıyla bit düzeyinde karşılaştırma yapılamadı).
- Normalleştirme (WT/CCI) tarihsel (genişleyen) min/max — veri 19.07'de başladığından ilk günlerde dar aralık; kNN için geçmiş ≥ 300 bar şartı → B1'in ilk ~1-2 günü sinyal üretmez.
- Rastgele tabanın bağımsız kabulü ve sinyallerin kümelenmesi: SE'ler gün-kümeli ama sembol/zaman çakışması tamamen modellenmedi.
- HGB B1'de değerlendirilemez (öncesi yok); kNN-B B1'de eşiksiz.
- 90 gün tek rejim; sonuçlar yalnızca bu örnek için.
