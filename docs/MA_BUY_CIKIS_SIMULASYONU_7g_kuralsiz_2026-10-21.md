# MA BUY çıkış kuralı simülasyonu — gerçekleşebilir net % (2026-10-21 00:20)

Kaynak: `ma_buy_replay_canli_evren_7g_kuralsiz_2026-10-21.json` (455 sinyal, canlı sembol seçimi). Simülatör: `app/paper_sim.simulate_exit` (otonom paper kurallarının kopyası; aynı mumda stop ve hedef görülürse STOP önce → sonuçlar taban, tavan değil). Mum: arşivdeki 1 dakikalık. Giriş: sinyal mumunun kapanış fiyatı. Komisyon 0.1125%/bacak, kayma 0.025%. Ortak: stop %4, iz süren stop tetik %2 / aralık %1, hedef iz sürende korunur.

Senaryolar: A canlı (hedef TF'ye göre, tutma 60 dk) · B 2 saat · C TF'ye göre tutma (M5/M15 4 sa, M30 8 sa, H1 24 sa) · D C + hedef (M5/M15 %1,5, M30 %2, H1 %3) · E D + iz süren stop kapalı · F/G/I D ile stop %2 / %1,5 / %1 · H kalibre profili (stop %0,8, iz süren %1/%0,8).

## A canlı (60 dk)

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 237 | 37% | -0.45% | -0.34% | -1.11% | +1.25% | -107% | max_duration 153, take_profit 58, stop_loss 16, trailing_stop 10 |
| M15 | 130 | 44% | -0.30% | -0.13% | -1.31% | +1.23% | -40% | max_duration 84, take_profit 21, trailing_stop 14, stop_loss 10, open 1 |
| M30 | 61 | 46% | -0.34% | -0.20% | -1.22% | +0.82% | -21% | max_duration 45, trailing_stop 8, stop_loss 5, take_profit 3 |
| H1 | 27 | 41% | -0.26% | -0.25% | -1.30% | +0.98% | -7% | max_duration 16, trailing_stop 8, stop_loss 2, take_profit 1 |

## B 2 saat

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 237 | 47% | -0.48% | -0.12% | -1.65% | +1.25% | -114% | max_duration 117, take_profit 80, stop_loss 25, trailing_stop 13, open 2 |
| M15 | 130 | 44% | -0.38% | -0.34% | -1.58% | +1.59% | -50% | max_duration 71, take_profit 27, trailing_stop 17, stop_loss 14, open 1 |
| M30 | 61 | 56% | -0.15% | +0.12% | -1.53% | +1.45% | -9% | max_duration 35, trailing_stop 12, take_profit 9, stop_loss 5 |
| H1 | 27 | 48% | -0.32% | -0.00% | -2.00% | +1.18% | -9% | max_duration 11, trailing_stop 10, stop_loss 4, take_profit 2 |

## C TF'ye göre tutma

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 237 | 50% | -0.59% | +0.05% | -2.04% | +1.25% | -139% | take_profit 98, max_duration 83, stop_loss 41, trailing_stop 13, open 2 |
| M15 | 130 | 51% | -0.38% | +0.17% | -2.08% | +1.75% | -50% | max_duration 52, take_profit 39, stop_loss 20, trailing_stop 18, open 1 |
| M30 | 61 | 56% | -0.42% | +0.97% | -4.24% | +2.25% | -25% | trailing_stop 18, stop_loss 16, take_profit 15, max_duration 12 |
| H1 | 27 | 63% | -0.55% | +0.98% | -4.24% | +1.67% | -15% | trailing_stop 14, stop_loss 10, take_profit 3 |

## D C + hedef

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 237 | 50% | -0.59% | +0.05% | -2.04% | +1.25% | -139% | take_profit 98, max_duration 83, stop_loss 41, trailing_stop 13, open 2 |
| M15 | 130 | 59% | -0.33% | +1.25% | -2.01% | +1.25% | -43% | take_profit 65, max_duration 35, stop_loss 19, trailing_stop 10, open 1 |
| M30 | 61 | 56% | -0.46% | +1.31% | -4.24% | +1.75% | -28% | take_profit 25, stop_loss 16, max_duration 12, trailing_stop 8 |
| H1 | 27 | 63% | -0.55% | +0.98% | -4.24% | +1.67% | -15% | trailing_stop 14, stop_loss 10, take_profit 3 |

## E iz sürme yok

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 237 | 51% | -0.59% | +0.07% | -2.04% | +1.25% | -140% | take_profit 111, max_duration 83, stop_loss 41, open 2 |
| M15 | 130 | 59% | -0.33% | +1.25% | -2.01% | +1.25% | -43% | take_profit 75, max_duration 35, stop_loss 19, open 1 |
| M30 | 61 | 56% | -0.43% | +1.75% | -4.24% | +1.75% | -26% | take_profit 33, stop_loss 16, max_duration 12 |
| H1 | 27 | 52% | -0.50% | +2.75% | -4.24% | +2.75% | -13% | take_profit 14, stop_loss 12, open 1 |

## F D + stop %2

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 237 | 43% | -0.53% | -0.71% | -2.25% | +1.25% | -124% | stop_loss 95, take_profit 87, max_duration 44, trailing_stop 9, open 2 |
| M15 | 130 | 52% | -0.31% | +0.69% | -2.25% | +1.25% | -40% | take_profit 58, stop_loss 52, max_duration 12, trailing_stop 7, open 1 |
| M30 | 61 | 46% | -0.32% | -0.73% | -2.25% | +1.75% | -19% | stop_loss 28, take_profit 20, trailing_stop 8, max_duration 5 |
| H1 | 27 | 44% | -0.50% | -2.25% | -2.25% | +1.51% | -13% | stop_loss 15, trailing_stop 9, take_profit 3 |

## G D + stop %1,5

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 237 | 41% | -0.44% | -1.30% | -1.75% | +1.25% | -104% | stop_loss 113, take_profit 84, max_duration 32, trailing_stop 7, open 1 |
| M15 | 130 | 48% | -0.22% | -0.24% | -1.75% | +1.25% | -29% | stop_loss 58, take_profit 54, max_duration 10, trailing_stop 7, open 1 |
| M30 | 61 | 44% | -0.20% | -1.75% | -1.75% | +1.75% | -12% | stop_loss 32, take_profit 19, trailing_stop 8, max_duration 2 |
| H1 | 27 | 37% | -0.55% | -1.75% | -1.75% | +1.08% | -15% | stop_loss 17, trailing_stop 9, take_profit 1 |

## H kalibre profili

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 237 | 41% | -0.36% | -1.05% | -1.05% | +0.30% | -84% | stop_loss 136, trailing_stop 66, take_profit 29, max_duration 6 |
| M15 | 130 | 42% | -0.26% | -1.05% | -1.05% | +0.44% | -34% | stop_loss 70, trailing_stop 33, take_profit 23, max_duration 3, open 1 |
| M30 | 61 | 51% | -0.18% | +0.17% | -1.05% | +0.35% | -11% | stop_loss 30, trailing_stop 24, take_profit 7 |
| H1 | 27 | 56% | -0.03% | +0.17% | -1.05% | +0.49% | -1% | trailing_stop 14, stop_loss 12, take_profit 1 |

## I D + stop %1

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 237 | 32% | -0.43% | -1.25% | -1.25% | +1.25% | -102% | stop_loss 146, take_profit 65, max_duration 20, trailing_stop 5, open 1 |
| M15 | 130 | 37% | -0.28% | -1.25% | -1.25% | +1.25% | -36% | stop_loss 75, take_profit 43, max_duration 7, trailing_stop 4, open 1 |
| M30 | 61 | 36% | -0.20% | -1.25% | -1.25% | +1.75% | -12% | stop_loss 39, take_profit 16, trailing_stop 6 |
| H1 | 27 | 33% | -0.31% | -1.25% | -1.25% | +1.08% | -8% | stop_loss 18, trailing_stop 8, take_profit 1 |

## Dürüst sınırlar

- Giriş fiyatı sinyal mumunun kapanışı; canlıda tarayıcı mumu kapanıştan 30 sn sonra görür ve piyasa emri verir (küçük kayma).
- Paper motorunun dinamik breakeven / dinamik trailing ve LLM kapısı, MTF kapısı, sembol tekilleştirme gibi GİRİŞ engelleri simüle edilmedi; burada her sinyal işleme döner. Canlıda açılan işlem sayısı daha azdır.
- Aynı sembolde üst üste sinyaller ayrı işlem sayıldı (canlıda tekilleştirme bazılarını eler).
- Mum içi sıra bilinmediği için stop önce kabul edilir; gerçek sonuç biraz daha iyi olabilir.
