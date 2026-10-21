# MA BUY 7 günlük replay (CANLI sembol seçimiyle) — sinyal sonrası en yüksek yükseliş (2026-10-20 22:12)

Kapsam: son 7 gün, 151 (canlı seçim; evren 310) sembol, zaman dilimleri M5, M15, M30, H1. Kural ve parametreler canlı motorla aynı (SMA 7/20/99, StochRSI K ≤ 80 (1m hariç)).

**Ölçüt:** sinyal mumunun KAPANIŞINA göre, bir SONRAKİ sinyale (aynı sembol + TF) kadar görülen en yüksek `high` (MFE). Sonraki sinyali olmayan son sinyaller veri sonuna kadar ölçülür ve *açık uçlu* sayılır. 15 dk / 1 sa / 4 sa / 24 sa sütunları sabit ufuklardır, sonraki sinyalle sınırlanmaz.

## Özet (TF bazında)

| TF | Kural | Sinyal | Medyan MFE | Ortalama | P25 | P75 | ≥%1 | ≥%2 | ≥%3 | Hedefe dokunma | Zirveye medyan dk | Sonrakine medyan dk | Açık uçlu |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M5 | all | 250 | 2.31% | 4.22% | 1.04% | 5.71% | 0.76 | 0.54 | 0.43 | 0.62 | 135.00 | 910.00 | 95 |
| M5 | fast_cross_mid | 197 | 2.24% | 4.10% | 1.01% | 5.34% | 0.76 | 0.53 | 0.41 | 0.62 | 135 | 775 | 73 |
| M5 | mid_cross_slow | 53 | 4.11% | 4.66% | 1.06% | 6.37% | 0.77 | 0.60 | 0.51 | 0.64 | 115 | 1370 | 22 |
| M15 | all | 132 | 3.05% | 5.18% | 1.18% | 6.40% | 0.78 | 0.61 | 0.50 | 0.61 | 165.00 | 1612.50 | 65 |
| M15 | fast_cross_mid | 117 | 3.15% | 5.39% | 1.18% | 6.74% | 0.78 | 0.60 | 0.50 | 0.60 | 165 | 1380 | 56 |
| M15 | mid_cross_slow | 15 | 2.96% | 3.50% | 1.16% | 6.35% | 0.80 | 0.67 | 0.47 | 0.67 | 225 | 4290 | 9 |
| M30 | all | 61 | 3.69% | 5.25% | 1.80% | 6.79% | 0.90 | 0.70 | 0.57 | 0.66 | 330 | 3780 | 42 |
| M30 | fast_cross_mid | 42 | 3.45% | 5.00% | 1.65% | 6.87% | 0.86 | 0.67 | 0.55 | 0.64 | 255.00 | 3810.00 | 29 |
| M30 | mid_cross_slow | 19 | 4.54% | 5.82% | 2.08% | 6.50% | 1.00 | 0.79 | 0.63 | 0.68 | 570 | 3390 | 13 |
| H1 | all | 26 | 5.64% | 8.48% | 2.06% | 10.64% | 0.88 | 0.85 | 0.69 | 0.69 | 1050.00 | 5220.00 | 21 |
| H1 | fast_cross_mid | 11 | 4.84% | 9.81% | 2.02% | 11.41% | 0.91 | 0.82 | 0.64 | 0.64 | 780 | 5760 | 10 |
| H1 | mid_cross_slow | 15 | 6.32% | 7.51% | 2.94% | 10.38% | 0.87 | 0.87 | 0.73 | 0.73 | 1080 | 4020 | 11 |

## Sabit ufuklarda medyan en yüksek yükseliş

| TF | 15 dk | 1 sa | 4 sa | 24 sa |
|---|---:|---:|---:|---:|
| M5 | 0.33% (n=250) | 0.83% (n=248) | 1.47% (n=242) | 3.24% (n=217) |
| M15 | 0.31% (n=132) | 0.88% (n=131) | 1.85% (n=131) | 3.03% (n=110) |
| M30 | — | 0.91% (n=61) | 1.60% (n=61) | 3.07% (n=56) |
| H1 | — | 1.17% (n=26) | 1.83% (n=26) | 4.66% (n=23) |

## Sembol bazında sinyal sayısı

| Sembol | M5 | M15 | M30 | H1 | Toplam |
|---|---:|---:|---:|---:|---:|
| ACETRY | 1 | 2 | 1 | 0 | 4 |
| ACMTRY | 3 | 2 | 1 | 0 | 6 |
| AITRY | 0 | 1 | 0 | 0 | 1 |
| ALTTRY | 7 | 3 | 0 | 1 | 11 |
| AMPTRY | 10 | 7 | 4 | 1 | 22 |
| APETRY | 1 | 1 | 1 | 1 | 4 |
| APTTRY | 2 | 1 | 0 | 0 | 3 |
| ARBTRY | 3 | 2 | 0 | 0 | 5 |
| ARKMTRY | 1 | 0 | 0 | 0 | 1 |
| ARTRY | 1 | 0 | 1 | 0 | 2 |
| ASTERTRY | 1 | 0 | 0 | 0 | 1 |
| ATRY | 3 | 1 | 1 | 0 | 5 |
| ATTRY | 1 | 0 | 0 | 0 | 1 |
| AUDIOTRY | 3 | 1 | 1 | 0 | 5 |
| AXLTRY | 2 | 1 | 1 | 1 | 5 |
| BABYTRY | 1 | 1 | 0 | 0 | 2 |
| BBTRY | 2 | 2 | 0 | 0 | 4 |
| BEAMXTRY | 1 | 2 | 1 | 1 | 5 |
| BERATRY | 2 | 0 | 0 | 0 | 2 |
| BLURTRY | 0 | 1 | 0 | 0 | 1 |
| BMTTRY | 3 | 1 | 0 | 0 | 4 |
| BNBTRY | 1 | 0 | 0 | 0 | 1 |
| BTCTRY | 2 | 0 | 0 | 0 | 2 |
| CFGTRY | 2 | 0 | 0 | 0 | 2 |
| CHIPTRY | 2 | 2 | 1 | 0 | 5 |
| COMPTRY | 2 | 0 | 0 | 0 | 2 |
| CRVTRY | 1 | 0 | 0 | 0 | 1 |
| DODOTRY | 9 | 0 | 4 | 1 | 14 |
| DOTTRY | 0 | 0 | 0 | 1 | 1 |
| EDENTRY | 1 | 0 | 0 | 0 | 1 |
| EIGENTRY | 4 | 1 | 2 | 2 | 9 |
| ENATRY | 3 | 3 | 1 | 0 | 7 |
| ERATRY | 6 | 1 | 0 | 0 | 7 |
| ETHFITRY | 5 | 0 | 2 | 1 | 8 |
| ETHTRY | 1 | 0 | 0 | 0 | 1 |
| FETTRY | 1 | 0 | 0 | 0 | 1 |
| FILTRY | 1 | 0 | 0 | 1 | 2 |
| FOGOTRY | 0 | 0 | 1 | 0 | 1 |
| GPSTRY | 1 | 1 | 0 | 0 | 2 |
| HBARTRY | 2 | 0 | 1 | 0 | 3 |
| HEITRY | 1 | 2 | 1 | 0 | 4 |
| HYPETRY | 1 | 0 | 0 | 0 | 1 |
| IDTRY | 0 | 1 | 0 | 0 | 1 |
| INITTRY | 1 | 1 | 0 | 0 | 2 |
| INJTRY | 8 | 0 | 1 | 0 | 9 |
| IOTRY | 1 | 0 | 0 | 0 | 1 |
| JUVTRY | 1 | 0 | 0 | 0 | 1 |
| KITETRY | 1 | 0 | 0 | 0 | 1 |
| LAZIOTRY | 2 | 4 | 0 | 0 | 6 |
| LINEATRY | 1 | 0 | 0 | 0 | 1 |
| LUMIATRY | 3 | 5 | 0 | 0 | 8 |
| MAGICTRY | 3 | 2 | 0 | 1 | 6 |
| MANTATRY | 1 | 0 | 0 | 0 | 1 |
| MANTRATRY | 1 | 0 | 0 | 0 | 1 |
| MARSCOINTRY | 3 | 1 | 2 | 0 | 6 |
| MEGATRY | 1 | 1 | 1 | 0 | 3 |
| METISTRY | 1 | 0 | 1 | 0 | 2 |
| MINATRY | 0 | 1 | 0 | 0 | 1 |
| MOVRTRY | 1 | 0 | 0 | 0 | 1 |
| MUBARAKTRY | 1 | 3 | 1 | 0 | 5 |
| NEARTRY | 3 | 2 | 2 | 0 | 7 |
| NILTRY | 6 | 10 | 5 | 3 | 24 |
| NMRTRY | 2 | 3 | 0 | 0 | 5 |
| NOMTRY | 0 | 0 | 1 | 0 | 1 |
| NXPCTRY | 1 | 0 | 0 | 1 | 2 |
| OGNTRY | 1 | 1 | 0 | 0 | 2 |
| ONDOTRY | 2 | 0 | 2 | 1 | 5 |
| ONETRY | 1 | 0 | 0 | 0 | 1 |
| OPGTRY | 3 | 1 | 0 | 0 | 4 |
| OPTRY | 2 | 0 | 0 | 0 | 2 |
| PARTITRY | 1 | 1 | 0 | 0 | 2 |
| PENGUTRY | 1 | 1 | 1 | 0 | 3 |
| PEPETRY | 13 | 4 | 0 | 0 | 17 |
| PHATRY | 0 | 1 | 1 | 0 | 2 |
| PLUMETRY | 1 | 1 | 0 | 0 | 2 |
| PUMPTRY | 5 | 3 | 1 | 1 | 10 |
| PYTHTRY | 12 | 6 | 3 | 0 | 21 |
| RADTRY | 4 | 0 | 1 | 0 | 5 |
| RARETRY | 2 | 0 | 2 | 0 | 4 |
| RAYTRY | 3 | 1 | 0 | 0 | 4 |
| RENDERTRY | 0 | 1 | 0 | 0 | 1 |
| REZTRY | 0 | 2 | 0 | 0 | 2 |
| ROSETRY | 1 | 0 | 0 | 0 | 1 |
| RSRTRY | 1 | 0 | 1 | 0 | 2 |
| RVNTRY | 2 | 1 | 0 | 1 | 4 |
| SANDTRY | 0 | 0 | 1 | 1 | 2 |
| SANTOSTRY | 1 | 0 | 0 | 0 | 1 |
| SEITRY | 2 | 0 | 0 | 0 | 2 |
| SENTTRY | 3 | 6 | 2 | 2 | 13 |
| SHELLTRY | 1 | 1 | 0 | 0 | 2 |
| SKLTRY | 0 | 1 | 0 | 0 | 1 |
| SLPTRY | 1 | 0 | 0 | 0 | 1 |
| SOLTRY | 2 | 1 | 0 | 0 | 3 |
| SOLVTRY | 1 | 1 | 0 | 0 | 2 |
| STRAXTRY | 5 | 2 | 1 | 0 | 8 |
| STRKTRY | 0 | 1 | 1 | 0 | 2 |
| STRY | 4 | 1 | 0 | 0 | 5 |
| STXTRY | 1 | 0 | 0 | 0 | 1 |
| SUITRY | 0 | 0 | 1 | 0 | 1 |
| SUPERTRY | 0 | 0 | 0 | 1 | 1 |
| TAOTRY | 1 | 2 | 1 | 0 | 4 |
| TIATRY | 7 | 3 | 0 | 2 | 12 |
| UNITRY | 0 | 1 | 0 | 0 | 1 |
| WALTRY | 6 | 4 | 0 | 0 | 10 |
| WCTTRY | 2 | 1 | 0 | 0 | 3 |
| WLDTRY | 7 | 3 | 1 | 1 | 12 |
| XAUTTRY | 1 | 1 | 0 | 0 | 2 |
| XPLTRY | 1 | 0 | 1 | 0 | 2 |
| XRPTRY | 6 | 1 | 0 | 0 | 7 |
| ZKTRY | 3 | 3 | 0 | 0 | 6 |
| ZROTRY | 4 | 2 | 1 | 0 | 7 |

## En yüksek 10 yükseliş

| Sembol | TF | Kural | Sinyal zamanı | Fiyat | MFE | Zirveye dk | Sonrakine dk | Açık uçlu |
|---|---|---|---|---:|---:|---:|---:|---|
| WALTRY | M5 | fast_cross_mid | 14.10 04:55 | 2.02 | 36.24% | 620 | 620 | hayır |
| ALTTRY | H1 | fast_cross_mid | 16.10 21:00 | 0.407 | 34.40% | 5280 | 5760 | evet |
| PYTHTRY | M15 | fast_cross_mid | 15.10 08:00 | 4.285 | 34.19% | 600 | 600 | hayır |
| COMPTRY | M5 | fast_cross_mid | 20.10 19:05 | 1216 | 34.05% | 25 | 165 | hayır |
| PYTHTRY | M5 | fast_cross_mid | 15.10 14:45 | 4.293 | 33.94% | 195 | 435 | hayır |
| PYTHTRY | M30 | fast_cross_mid | 15.10 09:00 | 4.298 | 33.78% | 540 | 540 | hayır |
| AMPTRY | H1 | fast_cross_mid | 18.10 09:00 | 0.0363 | 31.68% | 1440 | 3600 | evet |
| AMPTRY | M30 | mid_cross_slow | 18.10 14:30 | 0.0367 | 30.25% | 1110 | 2280 | hayır |
| WALTRY | M15 | fast_cross_mid | 14.10 08:30 | 2.167 | 27.96% | 645 | 645 | hayır |
| TIATRY | H1 | mid_cross_slow | 16.10 05:00 | 29.71 | 26.56% | 1500 | 1500 | hayır |

## En zayıf 10 sinyal

| Sembol | TF | Kural | Sinyal zamanı | Fiyat | MFE | Zirveye dk | Sonrakine dk | Açık uçlu |
|---|---|---|---|---:|---:|---:|---:|---|
| PHATRY | M30 | fast_cross_mid | 20.10 09:00 | 3.28 | -0.30% | 30 | 750 | evet |
| AUDIOTRY | M30 | fast_cross_mid | 17.10 16:30 | 0.7875 | -0.18% | 30 | 4620 | evet |
| ZKTRY | M5 | mid_cross_slow | 14.10 12:15 | 0.792 | -0.13% | 5 | 1085 | hayır |
| TIATRY | M15 | fast_cross_mid | 20.10 17:30 | 32.34 | -0.12% | 15 | 255 | evet |
| WLDTRY | M5 | fast_cross_mid | 17.10 09:35 | 26.29 | -0.11% | 5 | 3400 | hayır |
| EIGENTRY | M15 | fast_cross_mid | 17.10 14:00 | 13.318 | -0.07% | 15 | 4785 | evet |
| ONETRY | M5 | mid_cross_slow | 14.10 13:25 | 0.08456 | -0.06% | 5 | 9160 | evet |
| XPLTRY | M30 | fast_cross_mid | 16.10 10:00 | 4.256 | -0.05% | 30 | 6450 | evet |
| AMPTRY | M15 | fast_cross_mid | 19.10 14:15 | 0.0466 | 0.00% | 15 | 1890 | evet |
| SKLTRY | M15 | mid_cross_slow | 18.10 01:00 | 0.239 | 0.00% | 15 | 4125 | evet |

## Dürüst sınırlar

- Mum verisi Binance TR herkese açık klines ucundan; sinyal mumu KAPANIŞI giriş fiyatı sayılır (spread/kayma yok).
- MFE "en yüksek görülen fiyat"tır, gerçekleşmiş kazanç değildir; çıkış kuralı simüle edilmemiştir.
- Açık uçlu sinyaller veri sonuna kadar ölçüldüğü için gerçek MFE daha yüksek olabilir.
- Sembol evreni raporun üretildiği andaki aktif + izlenen listedir; geçmişte aktif olup çıkanlar yoktur.

## Canlı sembol seçimi (yeniden üretim)

- Her 600 sn: 24 sa yükselenler ilk 50 (5m mumlardan: son kapanış / 24 sa önceki kapanış; 24 sa quote hacim). Her 3600 sn: aktivite filtresi (hacim ≥ 1,000,000 TL, 15 dk aralık ≥ %0.05, ATR ≥ 0.0012, hacim oranı ≥ 0.5, M1 düz mum filtresi açık [5/4, 30/25], kapsamlı pasiflik analizi).
- Saatlik anlık görüntü: 168; izlenen evrene giren sembol: 285; saat başına AKTİF: ortalama 8.7, en az 1, en çok 25; aktif küme boş olup izlenen listeye düşülen saat: 0.
- Aktivite kararları: {'PASSIVE': 6934, 'ACTIVE': 1466}. Sinyal elemesi: 6420 ham sinyalden 469 tanesi o anda taranan sembolde (kalanı sistem görmezdi).

| Sembol | Aktif saat | Sinyal |
|---|---:|---:|
| AMPTRY | 54 | 22 |
| NILTRY | 51 | 24 |
| INJTRY | 42 | 9 |
| SENTTRY | 42 | 13 |
| TIATRY | 40 | 12 |
| PEPETRY | 37 | 17 |
| WLDTRY | 35 | 12 |
| PYTHTRY | 33 | 21 |
| EIGENTRY | 31 | 9 |
| DODOTRY | 29 | 14 |
| WALTRY | 29 | 10 |
| ERATRY | 28 | 7 |
| MARSCOINTRY | 26 | 6 |
| STRY | 26 | 5 |
| LUMIATRY | 26 | 8 |
| ALTTRY | 26 | 11 |
| ETHFITRY | 24 | 8 |
| NEARTRY | 23 | 7 |
| ARBTRY | 21 | 5 |
| PUMPTRY | 21 | 10 |

Sadeleştirmeler: açık paper pozisyonlarının evrene eklenmesi yok; ticker `priceChangePercent` yerine 5m kapanış oranı; `_m1_activity_features` karara girmediği için hesaplanmadı; aktivite kararı yalnız izlenen sembollerde (canlıda izlenmeyen sembolün 5m serisi olmadığından WARMING kalır).
