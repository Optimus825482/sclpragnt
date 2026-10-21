# MA BUY çıkış kuralı simülasyonu — gerçekleşebilir net % (2026-10-21 00:19)

Kaynak: `ma_buy_replay_canli_evren_7g_kurallar_2026-10-21.json` (275 sinyal, canlı sembol seçimi). Simülatör: `app/paper_sim.simulate_exit` (otonom paper kurallarının kopyası; aynı mumda stop ve hedef görülürse STOP önce → sonuçlar taban, tavan değil). Mum: arşivdeki 1 dakikalık. Giriş: sinyal mumunun kapanış fiyatı. Komisyon 0.1125%/bacak, kayma 0.025%. Ortak: stop %4, iz süren stop tetik %2 / aralık %1, hedef iz sürende korunur.

Senaryolar: A canlı (hedef TF'ye göre, tutma 60 dk) · B 2 saat · C TF'ye göre tutma (M5/M15 4 sa, M30 8 sa, H1 24 sa) · D C + hedef (M5/M15 %1,5, M30 %2, H1 %3) · E D + iz süren stop kapalı · F/G/I D ile stop %2 / %1,5 / %1 · H kalibre profili (stop %0,8, iz süren %1/%0,8).

## A canlı (60 dk)

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 237 | 37% | -0.45% | -0.34% | -1.11% | +1.25% | -107% | max_duration 153, take_profit 58, stop_loss 16, trailing_stop 10 |
| M15 | 12 | 67% | +0.21% | +0.98% | -0.90% | +1.75% | +2% | max_duration 5, take_profit 3, trailing_stop 3, stop_loss 1 |
| M30 | 25 | 36% | -1.06% | -0.70% | -2.44% | +0.44% | -27% | max_duration 17, stop_loss 5, trailing_stop 2, take_profit 1 |
| H1 | 1 | 100% | +2.04% | +2.04% | — | — | +2% | trailing_stop 1 |

## B 2 saat

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 237 | 47% | -0.48% | -0.12% | -1.65% | +1.25% | -114% | max_duration 117, take_profit 80, stop_loss 25, trailing_stop 13, open 2 |
| M15 | 12 | 75% | +0.42% | +1.64% | -1.35% | +1.75% | +5% | take_profit 5, trailing_stop 4, max_duration 2, stop_loss 1 |
| M30 | 25 | 44% | -0.89% | -1.00% | -3.31% | +1.45% | -22% | max_duration 13, stop_loss 5, take_profit 5, trailing_stop 2 |
| H1 | 1 | 100% | +2.04% | +2.04% | — | — | +2% | trailing_stop 1 |

## C TF'ye göre tutma

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 237 | 50% | -0.59% | +0.05% | -2.04% | +1.25% | -139% | take_profit 98, max_duration 83, stop_loss 41, trailing_stop 13, open 2 |
| M15 | 12 | 75% | +0.28% | +1.64% | -1.82% | +1.75% | +3% | take_profit 5, trailing_stop 4, stop_loss 2, max_duration 1 |
| M30 | 25 | 44% | -1.15% | -0.72% | -4.24% | +2.25% | -29% | stop_loss 11, take_profit 7, trailing_stop 4, max_duration 3 |
| H1 | 1 | 100% | +2.04% | +2.04% | — | — | +2% | trailing_stop 1 |

## D C + hedef

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 237 | 50% | -0.59% | +0.05% | -2.04% | +1.25% | -139% | take_profit 98, max_duration 83, stop_loss 41, trailing_stop 13, open 2 |
| M15 | 12 | 75% | +0.06% | +1.25% | -1.82% | +1.25% | +1% | take_profit 6, trailing_stop 3, stop_loss 2, max_duration 1 |
| M30 | 25 | 44% | -1.29% | -0.72% | -4.24% | +1.75% | -32% | stop_loss 11, take_profit 9, max_duration 3, trailing_stop 2 |
| H1 | 1 | 100% | +2.04% | +2.04% | — | — | +2% | trailing_stop 1 |

## E iz sürme yok

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 237 | 51% | -0.59% | +0.07% | -2.04% | +1.25% | -140% | take_profit 111, max_duration 83, stop_loss 41, open 2 |
| M15 | 12 | 75% | +0.01% | +1.25% | -1.72% | +1.25% | +0% | take_profit 9, stop_loss 2, max_duration 1 |
| M30 | 25 | 44% | -1.26% | -0.72% | -4.24% | +1.75% | -32% | stop_loss 11, take_profit 11, max_duration 3 |
| H1 | 1 | 100% | +2.75% | +2.75% | — | — | +3% | take_profit 1 |

## F D + stop %2

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 237 | 43% | -0.53% | -0.71% | -2.25% | +1.25% | -124% | stop_loss 95, take_profit 87, max_duration 44, trailing_stop 9, open 2 |
| M15 | 12 | 75% | +0.43% | +1.25% | -1.48% | +1.25% | +5% | take_profit 6, stop_loss 3, trailing_stop 3 |
| M30 | 25 | 36% | -0.76% | -2.25% | -2.25% | +1.75% | -19% | stop_loss 15, take_profit 7, trailing_stop 2, max_duration 1 |
| H1 | 1 | 100% | +2.04% | +2.04% | — | — | +2% | trailing_stop 1 |

## G D + stop %1,5

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 237 | 41% | -0.44% | -1.30% | -1.75% | +1.25% | -104% | stop_loss 113, take_profit 84, max_duration 32, trailing_stop 7, open 1 |
| M15 | 12 | 75% | +0.55% | +1.25% | -1.10% | +1.25% | +7% | take_profit 6, stop_loss 3, trailing_stop 3 |
| M30 | 25 | 36% | -0.52% | -1.75% | -1.75% | +1.75% | -13% | stop_loss 16, take_profit 7, trailing_stop 2 |
| H1 | 1 | 100% | +2.04% | +2.04% | — | — | +2% | trailing_stop 1 |

## H kalibre profili

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 237 | 41% | -0.36% | -1.05% | -1.05% | +0.30% | -84% | stop_loss 136, trailing_stop 66, take_profit 29, max_duration 6 |
| M15 | 12 | 50% | -0.09% | -0.44% | -1.05% | +0.98% | -1% | trailing_stop 5, stop_loss 5, take_profit 2 |
| M30 | 25 | 44% | -0.22% | -1.05% | -1.05% | +0.28% | -6% | stop_loss 14, trailing_stop 7, take_profit 4 |
| H1 | 1 | 100% | +2.25% | +2.25% | — | — | +2% | trailing_stop 1 |

## I D + stop %1

| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M5 | 237 | 32% | -0.43% | -1.25% | -1.25% | +1.25% | -102% | stop_loss 146, take_profit 65, max_duration 20, trailing_stop 5, open 1 |
| M15 | 12 | 42% | -0.12% | -1.25% | -1.25% | +1.25% | -1% | stop_loss 7, take_profit 3, trailing_stop 2 |
| M30 | 25 | 32% | -0.31% | -1.25% | -1.25% | +1.75% | -8% | stop_loss 17, take_profit 7, trailing_stop 1 |
| H1 | 1 | 100% | +2.04% | +2.04% | — | — | +2% | trailing_stop 1 |

## Dürüst sınırlar

- Giriş fiyatı sinyal mumunun kapanışı; canlıda tarayıcı mumu kapanıştan 30 sn sonra görür ve piyasa emri verir (küçük kayma).
- Paper motorunun dinamik breakeven / dinamik trailing ve LLM kapısı, MTF kapısı, sembol tekilleştirme gibi GİRİŞ engelleri simüle edilmedi; burada her sinyal işleme döner. Canlıda açılan işlem sayısı daha azdır.
- Aynı sembolde üst üste sinyaller ayrı işlem sayıldı (canlıda tekilleştirme bazılarını eler).
- Mum içi sıra bilinmediği için stop önce kabul edilir; gerçek sonuç biraz daha iyi olabilir.
