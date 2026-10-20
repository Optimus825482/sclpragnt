# MA BUY 7 günlük replay — sinyal sonrası en yüksek yükseliş (2026-10-20 19:03)

Kapsam: son 7 gün, 22 sembol, zaman dilimleri M1, M5, M15, M30, H1. Kural ve parametreler canlı motorla aynı (SMA 7/20/99, StochRSI K ≤ 80 (1m hariç)).

**Ölçüt:** sinyal mumunun KAPANIŞINA göre, bir SONRAKİ sinyale (aynı sembol + TF) kadar görülen en yüksek `high` (MFE). Sonraki sinyali olmayan son sinyaller veri sonuna kadar ölçülür ve *açık uçlu* sayılır. 15 dk / 1 sa / 4 sa / 24 sa sütunları sabit ufuklardır, sonraki sinyalle sınırlanmaz.

## Özet (TF bazında)

| TF | Kural | Sinyal | Medyan MFE | Ortalama | P25 | P75 | ≥%1 | ≥%2 | ≥%3 | Hedefe dokunma | Zirveye medyan dk | Sonrakine medyan dk | Açık uçlu |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M1 | all | 3905 | 0.19% | 0.49% | 0.04% | 0.50% | 0.12 | 0.05 | 0.03 | 0.12 | 8 | 35 | 22 |
| M1 | fast_cross_mid | 2480 | 0.21% | 0.52% | 0.05% | 0.54% | 0.14 | 0.05 | 0.03 | 0.14 | 9.00 | 36.00 | 19 |
| M1 | mid_cross_slow | 1460 | 0.17% | 0.44% | 0.03% | 0.44% | 0.10 | 0.04 | 0.03 | 0.10 | 8.00 | 34.00 | 3 |
| M5 | all | 606 | 0.56% | 1.34% | 0.22% | 1.32% | 0.32 | 0.17 | 0.12 | 0.23 | 55.00 | 182.50 | 22 |
| M5 | fast_cross_mid | 440 | 0.57% | 1.36% | 0.20% | 1.39% | 0.33 | 0.17 | 0.12 | 0.24 | 55.00 | 182.50 | 15 |
| M5 | mid_cross_slow | 167 | 0.54% | 1.32% | 0.24% | 1.16% | 0.29 | 0.17 | 0.12 | 0.20 | 55 | 180 | 8 |
| M15 | all | 203 | 1.03% | 2.46% | 0.42% | 2.60% | 0.52 | 0.33 | 0.23 | 0.33 | 195 | 450 | 22 |
| M15 | fast_cross_mid | 146 | 1.02% | 2.72% | 0.34% | 2.95% | 0.51 | 0.36 | 0.25 | 0.36 | 195.00 | 480.00 | 19 |
| M15 | mid_cross_slow | 58 | 1.06% | 1.94% | 0.74% | 2.08% | 0.53 | 0.28 | 0.19 | 0.28 | 157.50 | 412.50 | 3 |
| M30 | all | 100 | 2.01% | 3.58% | 0.86% | 3.53% | 0.69 | 0.51 | 0.35 | 0.42 | 285.00 | 870.00 | 22 |
| M30 | fast_cross_mid | 66 | 1.95% | 2.96% | 0.84% | 3.42% | 0.67 | 0.50 | 0.32 | 0.41 | 240.00 | 840.00 | 16 |
| M30 | mid_cross_slow | 34 | 2.21% | 4.78% | 0.97% | 4.58% | 0.74 | 0.53 | 0.41 | 0.44 | 435.00 | 960.00 | 6 |
| H1 | all | 39 | 1.55% | 4.48% | 0.63% | 5.03% | 0.62 | 0.46 | 0.33 | 0.33 | 240 | 1320 | 16 |
| H1 | fast_cross_mid | 23 | 1.09% | 5.22% | 0.50% | 7.52% | 0.57 | 0.48 | 0.39 | 0.39 | 180 | 1320 | 10 |
| H1 | mid_cross_slow | 16 | 1.70% | 3.41% | 0.80% | 4.52% | 0.69 | 0.44 | 0.25 | 0.25 | 480.00 | 1230.00 | 6 |

## Sabit ufuklarda medyan en yüksek yükseliş

| TF | 15 dk | 1 sa | 4 sa | 24 sa |
|---|---:|---:|---:|---:|
| M1 | 0.13% (n=3904) | 0.36% (n=3889) | 0.74% (n=3792) | 1.61% (n=3329) |
| M5 | 0.11% (n=606) | 0.31% (n=605) | 0.64% (n=582) | 1.35% (n=538) |
| M15 | 0.14% (n=203) | 0.35% (n=202) | 0.70% (n=201) | 1.50% (n=183) |
| M30 | — | 0.43% (n=100) | 0.80% (n=91) | 2.03% (n=69) |
| H1 | — | 0.49% (n=38) | 0.95% (n=33) | 2.86% (n=26) |

## Sembol bazında sinyal sayısı

| Sembol | M1 | M5 | M15 | M30 | H1 | Toplam |
|---|---:|---:|---:|---:|---:|---:|
| ACMTRY | 135 | 27 | 8 | 3 | 0 | 173 |
| ADATRY | 197 | 30 | 7 | 3 | 0 | 237 |
| AMPTRY | 190 | 32 | 14 | 6 | 1 | 243 |
| APTTRY | 176 | 26 | 9 | 3 | 0 | 214 |
| ARBTRY | 181 | 28 | 5 | 4 | 2 | 220 |
| AVAXTRY | 173 | 31 | 7 | 4 | 1 | 216 |
| BNBTRY | 182 | 26 | 11 | 6 | 3 | 228 |
| BTCTRY | 188 | 22 | 12 | 5 | 3 | 230 |
| DOGETRY | 202 | 35 | 10 | 4 | 0 | 251 |
| DOTTRY | 171 | 24 | 8 | 7 | 4 | 214 |
| ERATRY | 155 | 19 | 9 | 4 | 4 | 191 |
| ETHTRY | 189 | 29 | 4 | 4 | 1 | 227 |
| INJTRY | 190 | 26 | 9 | 10 | 3 | 238 |
| LINKTRY | 177 | 20 | 10 | 4 | 0 | 211 |
| LTCTRY | 166 | 30 | 10 | 4 | 2 | 212 |
| NEARTRY | 177 | 27 | 7 | 3 | 2 | 216 |
| OPTRY | 160 | 23 | 7 | 4 | 0 | 194 |
| SOLTRY | 200 | 37 | 9 | 5 | 3 | 254 |
| SOLVTRY | 164 | 29 | 16 | 3 | 5 | 217 |
| SUITRY | 185 | 26 | 9 | 5 | 1 | 226 |
| WLDTRY | 163 | 23 | 12 | 4 | 3 | 205 |
| XRPTRY | 184 | 36 | 10 | 5 | 1 | 236 |

## En yüksek 10 yükseliş

| Sembol | TF | Kural | Sinyal zamanı | Fiyat | MFE | Zirveye dk | Sonrakine dk | Açık uçlu |
|---|---|---|---|---:|---:|---:|---:|---|
| AMPTRY | H1 | fast_cross_mid | 18.10 09:00 | 0.0363 | 31.68% | 1440 | 3420 | evet |
| AMPTRY | M30 | mid_cross_slow | 18.10 14:30 | 0.0367 | 30.25% | 1110 | 2280 | hayır |
| ERATRY | H1 | fast_cross_mid | 20.10 05:00 | 3.42 | 24.27% | 420 | 780 | evet |
| AMPTRY | M30 | mid_cross_slow | 16.10 13:30 | 0.0341 | 22.58% | 390 | 990 | hayır |
| AMPTRY | M5 | fast_cross_mid | 16.10 15:15 | 0.0341 | 22.58% | 285 | 1485 | hayır |
| AMPTRY | M15 | fast_cross_mid | 16.10 06:15 | 0.0326 | 22.39% | 705 | 705 | hayır |
| ERATRY | M15 | fast_cross_mid | 17.10 08:45 | 2.95 | 22.03% | 270 | 1410 | hayır |
| ERATRY | M30 | mid_cross_slow | 17.10 08:00 | 2.97 | 21.21% | 300 | 1140 | hayır |
| ERATRY | M5 | fast_cross_mid | 17.10 11:25 | 2.98 | 20.81% | 110 | 330 | hayır |
| ERATRY | M5 | fast_cross_mid | 20.10 06:30 | 3.56 | 19.38% | 350 | 655 | hayır |

## En zayıf 10 sinyal

| Sembol | TF | Kural | Sinyal zamanı | Fiyat | MFE | Zirveye dk | Sonrakine dk | Açık uçlu |
|---|---|---|---|---:|---:|---:|---:|---|
| ERATRY | M1 | fast_cross_mid | 20.10 03:40 | 3.45 | -0.58% | 1 | 2 | hayır |
| ERATRY | M1 | fast_cross_mid | 18.10 04:53 | 3.49 | -0.57% | 1 | 136 | hayır |
| SOLVTRY | M1 | mid_cross_slow | 14.10 16:54 | 0.188 | -0.53% | 1 | 181 | hayır |
| DOTTRY | M1 | fast_cross_mid | 20.10 18:11 | 58.4 | -0.51% | 1 | 45 | evet |
| SOLVTRY | M1 | mid_cross_slow | 18.10 14:55 | 0.215 | -0.47% | 1 | 18 | hayır |
| SOLVTRY | M1 | mid_cross_slow | 20.10 07:05 | 0.215 | -0.47% | 1 | 104 | hayır |
| ACMTRY | M1 | fast_cross_mid | 14.10 08:25 | 13.72 | -0.44% | 1 | 124 | hayır |
| ACMTRY | M1 | mid_cross_slow | 19.10 16:10 | 12.91 | -0.39% | 1 | 86 | hayır |
| DOTTRY | M5 | fast_cross_mid | 15.10 03:30 | 56.9 | -0.35% | 5 | 905 | hayır |
| ERATRY | M1 | mid_cross_slow | 16.10 18:51 | 2.9 | -0.34% | 1 | 228 | hayır |

## Dürüst sınırlar

- Mum verisi Binance TR herkese açık klines ucundan; sinyal mumu KAPANIŞI giriş fiyatı sayılır (spread/kayma yok).
- MFE "en yüksek görülen fiyat"tır, gerçekleşmiş kazanç değildir; çıkış kuralı simüle edilmemiştir.
- Açık uçlu sinyaller veri sonuna kadar ölçüldüğü için gerçek MFE daha yüksek olabilir.
- Sembol evreni raporun üretildiği andaki aktif + izlenen listedir; geçmişte aktif olup çıkanlar yoktur.
