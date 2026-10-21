# MA BUY çıkış kuralı simülasyonu — gerçekleşebilir net % (2026-10-21 00:43)

Kaynak: `ma_buy_replay_canli_evren_90g_kurallar_2026-10-21.json` (5446 sinyal, canlı sembol seçimi). Simülatör: `app/paper_sim.simulate_exit` (otonom paper kurallarının kopyası; aynı mumda stop ve hedef görülürse STOP önce → sonuçlar taban, tavan değil). Mum: arşivdeki 1 dakikalık. Giriş: sinyal mumunun kapanış fiyatı. Komisyon 0.1125%/bacak, kayma 0.025%. Ortak: stop %4, iz süren stop tetik %2 / aralık %1, hedef iz sürende korunur.

Senaryolar: A canlı (hedef TF'ye göre, tutma 60 dk) · B 2 saat · C TF'ye göre tutma (M5/M15 4 sa, M30 8 sa, H1 24 sa) · D C + hedef (M5/M15 %1,5, M30 %2, H1 %3) · E D + iz süren stop kapalı · F/G/I D ile stop %2 / %1,5 / %1 · H kalibre profili (stop %0,8, iz süren %1/%0,8).

## A canlı (60 dk)

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 4517 | 48% | -0.29% | -0.09% | -1.17% | +1.25% | -1318% | max_duration 2486, take_profit 1421, stop_loss 314, trailing_stop 296 |
| M15 | 297 | 52% | -0.35% | +0.19% | -1.75% | +1.75% | -105% | max_duration 131, take_profit 68, trailing_stop 59, stop_loss 39 |
| M30 | 577 | 48% | -0.37% | -0.22% | -1.56% | +1.05% | -215% | max_duration 338, trailing_stop 138, stop_loss 52, take_profit 49 |
| H1 | 55 | 35% | -0.84% | -0.66% | -2.37% | +0.93% | -46% | max_duration 36, trailing_stop 12, stop_loss 6, take_profit 1 |

## B 2 saat

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 4517 | 54% | -0.29% | +0.55% | -1.47% | +1.25% | -1324% | take_profit 1864, max_duration 1836, stop_loss 485, trailing_stop 330, open 2 |
| M15 | 297 | 56% | -0.37% | +0.83% | -2.42% | +1.75% | -110% | take_profit 92, max_duration 80, trailing_stop 65, stop_loss 60 |
| M30 | 577 | 53% | -0.31% | +0.28% | -1.65% | +1.25% | -177% | max_duration 252, trailing_stop 170, take_profit 80, stop_loss 75 |
| H1 | 55 | 42% | -0.85% | -0.60% | -2.75% | +1.13% | -47% | max_duration 26, trailing_stop 15, stop_loss 12, take_profit 2 |

## C TF'ye göre tutma

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 4517 | 61% | -0.29% | +1.25% | -1.75% | +1.25% | -1330% | take_profit 2262, max_duration 1165, stop_loss 731, trailing_stop 357, open 2 |
| M15 | 297 | 61% | -0.37% | +1.02% | -4.24% | +1.75% | -109% | take_profit 105, stop_loss 75, trailing_stop 71, max_duration 46 |
| M30 | 577 | 62% | -0.34% | +0.88% | -4.24% | +2.19% | -197% | trailing_stop 220, stop_loss 152, take_profit 126, max_duration 79 |
| H1 | 55 | 47% | -1.30% | -2.17% | -4.24% | +1.38% | -72% | stop_loss 25, trailing_stop 23, max_duration 4, take_profit 3 |

## D C + hedef

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 4517 | 61% | -0.29% | +1.25% | -1.75% | +1.25% | -1330% | take_profit 2262, max_duration 1165, stop_loss 731, trailing_stop 357, open 2 |
| M15 | 297 | 67% | -0.28% | +1.25% | -2.71% | +1.25% | -83% | take_profit 148, stop_loss 65, trailing_stop 49, max_duration 35 |
| M30 | 577 | 62% | -0.32% | +1.23% | -4.24% | +1.75% | -186% | take_profit 241, stop_loss 152, trailing_stop 106, max_duration 78 |
| H1 | 55 | 47% | -1.30% | -2.17% | -4.24% | +1.38% | -72% | stop_loss 25, trailing_stop 23, max_duration 4, take_profit 3 |

## E iz sürme yok

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 4517 | 61% | -0.30% | +1.25% | -1.74% | +1.25% | -1348% | take_profit 2619, max_duration 1165, stop_loss 731, open 2 |
| M15 | 297 | 67% | -0.32% | +1.25% | -2.71% | +1.25% | -96% | take_profit 197, stop_loss 65, max_duration 35 |
| M30 | 577 | 62% | -0.26% | +1.75% | -4.24% | +1.75% | -148% | take_profit 347, stop_loss 152, max_duration 78 |
| H1 | 55 | 38% | -1.34% | -4.24% | -4.24% | +2.75% | -73% | stop_loss 28, take_profit 21, max_duration 6 |

## F D + stop %2

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 4517 | 53% | -0.28% | +0.77% | -2.25% | +1.25% | -1283% | take_profit 2000, stop_loss 1678, max_duration 560, trailing_stop 277, open 2 |
| M15 | 297 | 57% | -0.24% | +1.25% | -2.25% | +1.25% | -70% | take_profit 127, stop_loss 125, trailing_stop 41, max_duration 4 |
| M30 | 577 | 50% | -0.27% | +0.14% | -2.25% | +1.75% | -156% | stop_loss 271, take_profit 199, trailing_stop 83, max_duration 24 |
| H1 | 55 | 38% | -0.76% | -2.25% | -2.25% | +1.21% | -42% | stop_loss 34, trailing_stop 18, take_profit 3 |

## G D + stop %1,5

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 4517 | 47% | -0.30% | -0.68% | -1.75% | +1.25% | -1337% | stop_loss 2130, take_profit 1799, max_duration 354, trailing_stop 233, open 1 |
| M15 | 297 | 50% | -0.22% | +0.31% | -1.75% | +1.25% | -65% | stop_loss 146, take_profit 114, trailing_stop 36, max_duration 1 |
| M30 | 577 | 44% | -0.26% | -1.75% | -1.75% | +1.75% | -150% | stop_loss 317, take_profit 175, trailing_stop 74, max_duration 11 |
| H1 | 55 | 35% | -0.55% | -1.75% | -1.75% | +1.17% | -30% | stop_loss 36, trailing_stop 16, take_profit 3 |

## H kalibre profili

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 4517 | 42% | -0.30% | -1.05% | -1.05% | +0.30% | -1360% | stop_loss 2549, trailing_stop 1249, take_profit 656, max_duration 63 |
| M15 | 297 | 38% | -0.39% | -1.05% | -1.05% | +0.23% | -115% | stop_loss 181, trailing_stop 91, take_profit 25 |
| M30 | 577 | 43% | -0.27% | -1.05% | -1.05% | +0.40% | -154% | stop_loss 324, trailing_stop 205, take_profit 47, max_duration 1 |
| H1 | 55 | 40% | -0.25% | -1.05% | -1.05% | +0.32% | -14% | stop_loss 33, trailing_stop 21, take_profit 1 |

## I D + stop %1

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 4517 | 38% | -0.29% | -1.25% | -1.25% | +1.25% | -1324% | stop_loss 2693, take_profit 1461, trailing_stop 195, max_duration 167, open 1 |
| M15 | 297 | 38% | -0.30% | -1.25% | -1.25% | +1.25% | -88% | stop_loss 183, take_profit 86, trailing_stop 28 |
| M30 | 577 | 36% | -0.23% | -1.25% | -1.25% | +1.75% | -133% | stop_loss 369, take_profit 141, trailing_stop 60, max_duration 7 |
| H1 | 55 | 25% | -0.50% | -1.25% | -1.25% | +0.93% | -27% | stop_loss 41, trailing_stop 13, take_profit 1 |

## Dürüst sınırlar

- Giriş fiyatı sinyal mumunun kapanışı; canlıda tarayıcı mumu kapanıştan 30 sn sonra görür ve piyasa emri verir (küçük kayma).
- Paper motorunun dinamik breakeven / dinamik trailing ve LLM kapısı, MTF kapısı, sembol tekilleştirme gibi GİRİŞ engelleri simüle edilmedi; burada her sinyal işleme döner. Canlıda açılan işlem sayısı daha azdır.
- Aynı sembolde üst üste sinyaller ayrı işlem sayıldı (canlıda tekilleştirme bazılarını eler).
- Mum içi sıra bilinmediği için stop önce kabul edilir; gerçek sonuç biraz daha iyi olabilir.
