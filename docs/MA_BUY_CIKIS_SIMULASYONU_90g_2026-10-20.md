# MA BUY çıkış kuralı simülasyonu — gerçekleşebilir net % (2026-10-20 23:25)

Kaynak: `ma_buy_replay_canli_evren_90g_2026-10-20.json` (8225 sinyal, canlı sembol seçimi). Simülatör: `app/paper_sim.simulate_exit` (otonom paper kurallarının kopyası; aynı mumda stop ve hedef görülürse STOP önce → sonuçlar taban, tavan değil). Mum: arşivdeki 1 dakikalık. Giriş: sinyal mumunun kapanış fiyatı. Komisyon 0.1125%/bacak, kayma 0.025%. Ortak: stop %4, iz süren stop tetik %2 / aralık %1, hedef iz sürende korunur.

Senaryolar: A canlı (hedef TF'ye göre, tutma 60 dk) · B 2 saat · C TF'ye göre tutma (M5/M15 4 sa, M30 8 sa, H1 24 sa) · D C + hedef (M5/M15 %1,5, M30 %2, H1 %3) · E D + iz süren stop kapalı · F/G/I D ile stop %2 / %1,5 / %1 · H kalibre profili (stop %0,8, iz süren %1/%0,8).

## A canlı (60 dk)

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 4520 | 48% | -0.29% | -0.09% | -1.17% | +1.25% | -1316% | max_duration 2487, take_profit 1423, stop_loss 314, trailing_stop 296 |
| M15 | 2166 | 44% | -0.34% | -0.25% | -1.32% | +1.20% | -739% | max_duration 1391, take_profit 388, trailing_stop 232, stop_loss 154, open 1 |
| M30 | 1068 | 46% | -0.31% | -0.25% | -1.32% | +0.99% | -330% | max_duration 703, trailing_stop 213, take_profit 83, stop_loss 69 |
| H1 | 471 | 48% | -0.26% | -0.09% | -1.37% | +1.06% | -125% | max_duration 287, trailing_stop 121, stop_loss 38, take_profit 25 |

## B 2 saat

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 4520 | 54% | -0.29% | +0.56% | -1.47% | +1.25% | -1324% | take_profit 1866, max_duration 1837, stop_loss 485, trailing_stop 330, open 2 |
| M15 | 2166 | 49% | -0.35% | -0.10% | -1.70% | +1.75% | -761% | max_duration 1065, take_profit 562, trailing_stop 277, stop_loss 261, open 1 |
| M30 | 1068 | 50% | -0.24% | +0.02% | -1.50% | +1.20% | -260% | max_duration 544, trailing_stop 277, take_profit 142, stop_loss 105 |
| H1 | 471 | 55% | -0.24% | +0.27% | -1.73% | +1.29% | -115% | max_duration 207, trailing_stop 160, stop_loss 63, take_profit 41 |

## C TF'ye göre tutma

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 4520 | 61% | -0.29% | +1.25% | -1.75% | +1.25% | -1332% | take_profit 2264, max_duration 1165, stop_loss 732, trailing_stop 357, open 2 |
| M15 | 2166 | 54% | -0.35% | +0.74% | -2.30% | +1.75% | -759% | take_profit 752, max_duration 702, stop_loss 396, trailing_stop 315, open 1 |
| M30 | 1068 | 60% | -0.30% | +0.87% | -3.06% | +2.21% | -324% | trailing_stop 376, stop_loss 251, take_profit 236, max_duration 205 |
| H1 | 471 | 64% | -0.34% | +0.95% | -4.24% | +1.62% | -158% | trailing_stop 230, stop_loss 146, take_profit 68, max_duration 27 |

## D C + hedef

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 4520 | 61% | -0.29% | +1.25% | -1.75% | +1.25% | -1332% | take_profit 2264, max_duration 1165, stop_loss 732, trailing_stop 357, open 2 |
| M15 | 2166 | 61% | -0.27% | +1.25% | -1.81% | +1.25% | -583% | take_profit 1108, max_duration 551, stop_loss 341, trailing_stop 165, open 1 |
| M30 | 1068 | 60% | -0.30% | +1.22% | -3.06% | +1.75% | -323% | take_profit 444, stop_loss 251, max_duration 202, trailing_stop 171 |
| H1 | 471 | 64% | -0.34% | +0.95% | -4.24% | +1.62% | -158% | trailing_stop 230, stop_loss 146, take_profit 68, max_duration 27 |

## E iz sürme yok

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 4520 | 61% | -0.30% | +1.25% | -1.74% | +1.25% | -1350% | take_profit 2621, max_duration 1165, stop_loss 732, open 2 |
| M15 | 2166 | 62% | -0.28% | +1.25% | -1.81% | +1.25% | -609% | take_profit 1273, max_duration 551, stop_loss 341, open 1 |
| M30 | 1068 | 60% | -0.25% | +1.75% | -3.06% | +1.75% | -269% | take_profit 614, stop_loss 251, max_duration 203 |
| H1 | 471 | 54% | -0.34% | +2.75% | -4.24% | +2.75% | -161% | take_profit 245, stop_loss 188, max_duration 37, open 1 |

## F D + stop %2

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 4520 | 53% | -0.28% | +0.77% | -2.25% | +1.25% | -1283% | take_profit 2002, stop_loss 1679, max_duration 560, trailing_stop 277, open 2 |
| M15 | 2166 | 53% | -0.27% | +0.84% | -2.25% | +1.25% | -584% | take_profit 976, stop_loss 809, max_duration 250, trailing_stop 130, open 1 |
| M30 | 1068 | 49% | -0.30% | -0.60% | -2.25% | +1.75% | -324% | stop_loss 507, take_profit 373, trailing_stop 134, max_duration 54 |
| H1 | 471 | 51% | -0.26% | +0.73% | -2.25% | +1.36% | -122% | stop_loss 230, trailing_stop 182, take_profit 57, max_duration 2 |

## G D + stop %1,5

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 4520 | 47% | -0.30% | -0.68% | -1.75% | +1.25% | -1336% | stop_loss 2131, take_profit 1801, max_duration 354, trailing_stop 233, open 1 |
| M15 | 2166 | 48% | -0.26% | -0.36% | -1.75% | +1.25% | -557% | stop_loss 1007, take_profit 893, max_duration 150, trailing_stop 115, open 1 |
| M30 | 1068 | 43% | -0.27% | -1.75% | -1.75% | +1.75% | -294% | stop_loss 589, take_profit 332, trailing_stop 119, max_duration 28 |
| H1 | 471 | 46% | -0.17% | -1.75% | -1.75% | +1.31% | -80% | stop_loss 254, trailing_stop 165, take_profit 52 |

## H kalibre profili

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 4520 | 42% | -0.30% | -1.05% | -1.05% | +0.30% | -1359% | stop_loss 2550, trailing_stop 1250, take_profit 657, max_duration 63 |
| M15 | 2166 | 43% | -0.27% | -1.05% | -1.05% | +0.38% | -577% | stop_loss 1197, trailing_stop 585, take_profit 360, max_duration 23, open 1 |
| M30 | 1068 | 42% | -0.29% | -1.05% | -1.05% | +0.36% | -311% | stop_loss 618, trailing_stop 357, take_profit 92, max_duration 1 |
| H1 | 471 | 49% | -0.14% | -1.05% | -1.05% | +0.40% | -65% | stop_loss 237, trailing_stop 218, take_profit 16 |

## I D + stop %1

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 4520 | 38% | -0.29% | -1.25% | -1.25% | +1.25% | -1323% | stop_loss 2694, take_profit 1463, trailing_stop 195, max_duration 167, open 1 |
| M15 | 2166 | 39% | -0.26% | -1.25% | -1.25% | +1.25% | -560% | stop_loss 1267, take_profit 740, trailing_stop 85, max_duration 73, open 1 |
| M30 | 1068 | 34% | -0.26% | -1.25% | -1.25% | +1.75% | -277% | stop_loss 694, take_profit 258, trailing_stop 100, max_duration 16 |
| H1 | 471 | 37% | -0.16% | -1.25% | -1.25% | +1.12% | -75% | stop_loss 295, trailing_stop 134, take_profit 42 |

## Dürüst sınırlar

- Giriş fiyatı sinyal mumunun kapanışı; canlıda tarayıcı mumu kapanıştan 30 sn sonra görür ve piyasa emri verir (küçük kayma).
- Paper motorunun dinamik breakeven / dinamik trailing ve LLM kapısı, MTF kapısı, sembol tekilleştirme gibi GİRİŞ engelleri simüle edilmedi; burada her sinyal işleme döner. Canlıda açılan işlem sayısı daha azdır.
- Aynı sembolde üst üste sinyaller ayrı işlem sayıldı (canlıda tekilleştirme bazılarını eler).
- Mum içi sıra bilinmediği için stop önce kabul edilir; gerçek sonuç biraz daha iyi olabilir.
