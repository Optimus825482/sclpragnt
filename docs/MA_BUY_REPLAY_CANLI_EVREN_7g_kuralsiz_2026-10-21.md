# MA BUY 7 günlük replay (CANLI sembol seçimiyle) — sinyal sonrası en yüksek yükseliş (2026-10-21 00:19)

Kapsam: son 7 gün, 153 (canlı seçim; evren 310) sembol, zaman dilimleri M5, M15, M30, H1. Kural ve parametreler canlı motorla aynı (SMA 7/20/99, StochRSI K ≤ 80 (1m hariç)).

**Ölçüt:** sinyal mumunun KAPANIŞINA göre, bir SONRAKİ sinyale (aynı sembol + TF) kadar görülen en yüksek `high` (MFE). Sonraki sinyali olmayan son sinyaller veri sonuna kadar ölçülür ve *açık uçlu* sayılır. 15 dk / 1 sa / 4 sa / 24 sa sütunları sabit ufuklardır, sonraki sinyalle sınırlanmaz.

## Özet (TF bazında)

| TF | Kural | Sinyal | Medyan MFE | Ortalama | P25 | P75 | ≥%1 | ≥%2 | ≥%3 | Hedefe dokunma | Zirveye medyan dk | Sonrakine medyan dk | Açık uçlu |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M5 | all | 237 | 2.24% | 4.24% | 1.04% | 5.86% | 0.76 | 0.53 | 0.42 | 0.62 | 135 | 1035 | 95 |
| M5 | fast_cross_mid | 185 | 2.11% | 4.11% | 0.93% | 5.34% | 0.75 | 0.51 | 0.39 | 0.61 | 130 | 815 | 71 |
| M5 | mid_cross_slow | 52 | 4.11% | 4.71% | 1.10% | 7.24% | 0.81 | 0.60 | 0.52 | 0.65 | 165.00 | 1580.00 | 24 |
| M15 | all | 130 | 3.04% | 5.26% | 1.22% | 7.02% | 0.78 | 0.60 | 0.50 | 0.60 | 165.00 | 1725.00 | 66 |
| M15 | fast_cross_mid | 115 | 3.15% | 5.46% | 1.25% | 7.14% | 0.78 | 0.60 | 0.50 | 0.60 | 165 | 1380 | 56 |
| M15 | mid_cross_slow | 15 | 2.41% | 3.74% | 1.16% | 6.35% | 0.80 | 0.60 | 0.47 | 0.60 | 300 | 4320 | 10 |
| M30 | all | 61 | 3.69% | 5.26% | 1.80% | 6.79% | 0.90 | 0.70 | 0.57 | 0.66 | 330 | 3390 | 41 |
| M30 | fast_cross_mid | 43 | 3.56% | 4.99% | 1.77% | 6.84% | 0.86 | 0.67 | 0.56 | 0.65 | 270 | 3390 | 29 |
| M30 | mid_cross_slow | 18 | 4.19% | 5.89% | 1.96% | 6.64% | 1.00 | 0.78 | 0.61 | 0.67 | 720.00 | 2850.00 | 12 |
| H1 | all | 27 | 4.97% | 8.13% | 2.07% | 10.38% | 0.89 | 0.85 | 0.70 | 0.70 | 840 | 5220 | 21 |
| H1 | fast_cross_mid | 12 | 4.75% | 9.05% | 2.03% | 10.40% | 0.92 | 0.83 | 0.67 | 0.67 | 570.00 | 5490.00 | 11 |
| H1 | mid_cross_slow | 15 | 6.32% | 7.39% | 2.94% | 10.38% | 0.87 | 0.87 | 0.73 | 0.73 | 1080 | 1500 | 10 |

## Sabit ufuklarda medyan en yüksek yükseliş

| TF | 15 dk | 1 sa | 4 sa | 24 sa |
|---|---:|---:|---:|---:|
| M5 | 0.37% (n=237) | 0.83% (n=236) | 1.42% (n=229) | 3.24% (n=206) |
| M15 | 0.31% (n=130) | 0.97% (n=129) | 1.85% (n=129) | 3.08% (n=108) |
| M30 | — | 0.91% (n=61) | 1.71% (n=61) | 3.07% (n=56) |
| H1 | — | 1.20% (n=27) | 2.05% (n=27) | 4.54% (n=24) |

## Sembol bazında sinyal sayısı

| Sembol | M5 | M15 | M30 | H1 | Toplam |
|---|---:|---:|---:|---:|---:|
| ACETRY | 1 | 2 | 1 | 0 | 4 |
| ACMTRY | 1 | 1 | 1 | 0 | 3 |
| AITRY | 0 | 1 | 0 | 0 | 1 |
| ALTTRY | 6 | 3 | 0 | 1 | 10 |
| AMPTRY | 7 | 6 | 4 | 0 | 17 |
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
| BTCTRY | 2 | 1 | 0 | 0 | 3 |
| CFGTRY | 2 | 0 | 0 | 0 | 2 |
| CHIPTRY | 2 | 2 | 1 | 0 | 5 |
| COMPTRY | 2 | 0 | 0 | 0 | 2 |
| CRVTRY | 1 | 0 | 0 | 0 | 1 |
| DODOTRY | 9 | 0 | 4 | 1 | 14 |
| DOTTRY | 0 | 0 | 0 | 1 | 1 |
| EDENTRY | 1 | 0 | 0 | 0 | 1 |
| EIGENTRY | 4 | 1 | 2 | 2 | 9 |
| ENATRY | 3 | 3 | 1 | 0 | 7 |
| ERATRY | 4 | 1 | 0 | 1 | 6 |
| ETHFITRY | 4 | 0 | 2 | 1 | 7 |
| ETHTRY | 1 | 0 | 0 | 0 | 1 |
| FETTRY | 2 | 0 | 0 | 0 | 2 |
| FILTRY | 1 | 0 | 0 | 1 | 2 |
| FOGOTRY | 0 | 0 | 1 | 0 | 1 |
| GPSTRY | 1 | 1 | 0 | 0 | 2 |
| HBARTRY | 1 | 0 | 0 | 0 | 1 |
| HEITRY | 2 | 3 | 1 | 0 | 6 |
| HYPETRY | 1 | 0 | 0 | 0 | 1 |
| IDTRY | 0 | 1 | 0 | 0 | 1 |
| INITTRY | 1 | 1 | 0 | 0 | 2 |
| INJTRY | 7 | 0 | 1 | 0 | 8 |
| IOTRY | 1 | 0 | 0 | 0 | 1 |
| KITETRY | 1 | 0 | 0 | 0 | 1 |
| LAZIOTRY | 3 | 4 | 0 | 0 | 7 |
| LINEATRY | 1 | 0 | 0 | 0 | 1 |
| LUMIATRY | 3 | 5 | 0 | 0 | 8 |
| LUNATRY | 1 | 0 | 0 | 0 | 1 |
| MAGICTRY | 2 | 1 | 0 | 1 | 4 |
| MANTATRY | 1 | 0 | 0 | 0 | 1 |
| MANTRATRY | 1 | 0 | 0 | 0 | 1 |
| MARSCOINTRY | 3 | 1 | 2 | 0 | 6 |
| MEGATRY | 1 | 1 | 1 | 0 | 3 |
| METISTRY | 1 | 0 | 1 | 0 | 2 |
| MINATRY | 0 | 1 | 0 | 0 | 1 |
| MOVRTRY | 1 | 0 | 0 | 0 | 1 |
| MUBARAKTRY | 3 | 3 | 1 | 0 | 7 |
| NEARTRY | 4 | 2 | 2 | 0 | 8 |
| NILTRY | 6 | 10 | 5 | 3 | 24 |
| NMRTRY | 2 | 3 | 0 | 0 | 5 |
| NOMTRY | 0 | 0 | 1 | 0 | 1 |
| NXPCTRY | 1 | 0 | 0 | 1 | 2 |
| OGNTRY | 0 | 1 | 0 | 0 | 1 |
| ONDOTRY | 2 | 0 | 2 | 1 | 5 |
| ONETRY | 1 | 0 | 0 | 0 | 1 |
| OPGTRY | 3 | 1 | 0 | 0 | 4 |
| OPTRY | 2 | 0 | 0 | 0 | 2 |
| PARTITRY | 1 | 1 | 0 | 0 | 2 |
| PENGUTRY | 1 | 1 | 1 | 0 | 3 |
| PEPETRY | 11 | 4 | 0 | 0 | 15 |
| PHATRY | 0 | 1 | 1 | 0 | 2 |
| PLUMETRY | 1 | 1 | 0 | 0 | 2 |
| PUMPTRY | 4 | 3 | 1 | 1 | 9 |
| PYTHTRY | 12 | 6 | 3 | 0 | 21 |
| RADTRY | 4 | 0 | 1 | 0 | 5 |
| RARETRY | 2 | 0 | 2 | 0 | 4 |
| RAYTRY | 3 | 1 | 0 | 0 | 4 |
| RENDERTRY | 0 | 1 | 0 | 0 | 1 |
| REZTRY | 0 | 2 | 0 | 0 | 2 |
| ROSETRY | 1 | 0 | 0 | 0 | 1 |
| RSRTRY | 1 | 0 | 1 | 0 | 2 |
| RVNTRY | 2 | 1 | 0 | 1 | 4 |
| SANDTRY | 1 | 0 | 1 | 2 | 4 |
| SANTOSTRY | 1 | 0 | 0 | 0 | 1 |
| SEITRY | 2 | 0 | 0 | 0 | 2 |
| SENTTRY | 3 | 6 | 3 | 2 | 14 |
| SHELLTRY | 1 | 1 | 0 | 0 | 2 |
| SKLTRY | 0 | 1 | 0 | 0 | 1 |
| SLPTRY | 1 | 0 | 0 | 0 | 1 |
| SOLTRY | 2 | 1 | 0 | 0 | 3 |
| SOLVTRY | 1 | 1 | 0 | 0 | 2 |
| STRAXTRY | 4 | 2 | 1 | 0 | 7 |
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
| XRPTRY | 3 | 1 | 0 | 0 | 4 |
| ZKTRY | 3 | 2 | 0 | 0 | 5 |
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
| AMPTRY | M30 | mid_cross_slow | 18.10 14:30 | 0.0367 | 30.25% | 1110 | 2280 | hayır |
| ERATRY | H1 | fast_cross_mid | 18.10 05:00 | 3.32 | 28.01% | 3300 | 3840 | evet |
| WALTRY | M15 | fast_cross_mid | 14.10 08:30 | 2.167 | 27.96% | 645 | 645 | hayır |
| TIATRY | H1 | mid_cross_slow | 16.10 05:00 | 29.71 | 26.56% | 1500 | 1500 | hayır |

## En zayıf 10 sinyal

| Sembol | TF | Kural | Sinyal zamanı | Fiyat | MFE | Zirveye dk | Sonrakine dk | Açık uçlu |
|---|---|---|---|---:|---:|---:|---:|---|
| PHATRY | M30 | fast_cross_mid | 20.10 09:00 | 3.28 | -0.30% | 30 | 780 | evet |
| AUDIOTRY | M30 | fast_cross_mid | 17.10 16:30 | 0.7875 | -0.18% | 30 | 4650 | evet |
| ZKTRY | M5 | mid_cross_slow | 14.10 12:15 | 0.792 | -0.13% | 5 | 1085 | hayır |
| TIATRY | M15 | fast_cross_mid | 20.10 17:30 | 32.34 | -0.12% | 15 | 285 | evet |
| WLDTRY | M5 | fast_cross_mid | 17.10 09:35 | 26.29 | -0.11% | 5 | 2725 | hayır |
| EIGENTRY | M15 | fast_cross_mid | 17.10 14:00 | 13.318 | -0.07% | 15 | 4815 | evet |
| ONETRY | M5 | mid_cross_slow | 14.10 13:25 | 0.08456 | -0.06% | 5 | 8520 | evet |
| XPLTRY | M30 | fast_cross_mid | 16.10 10:00 | 4.256 | -0.05% | 30 | 6480 | evet |
| AMPTRY | M15 | fast_cross_mid | 19.10 14:15 | 0.0466 | 0.00% | 15 | 1920 | evet |
| SKLTRY | M15 | mid_cross_slow | 18.10 01:00 | 0.239 | 0.00% | 15 | 4155 | evet |

## Dürüst sınırlar

- Mum verisi Binance TR herkese açık klines ucundan; sinyal mumu KAPANIŞI giriş fiyatı sayılır (spread/kayma yok).
- MFE "en yüksek görülen fiyat"tır, gerçekleşmiş kazanç değildir; çıkış kuralı simüle edilmemiştir.
- Açık uçlu sinyaller veri sonuna kadar ölçüldüğü için gerçek MFE daha yüksek olabilir.
- Sembol evreni raporun üretildiği andaki aktif + izlenen listedir; geçmişte aktif olup çıkanlar yoktur.

## Canlı sembol seçimi (yeniden üretim)

- Her 600 sn: 24 sa yükselenler ilk 50 (5m mumlardan: son kapanış / 24 sa önceki kapanış; 24 sa quote hacim). Her 3600 sn: aktivite filtresi (hacim ≥ 1,000,000 TL, 15 dk aralık ≥ %0.05, ATR ≥ 0.0012, hacim oranı ≥ 0.5, M1 düz mum filtresi açık [5/4, 30/25], kapsamlı pasiflik analizi).
- Saatlik anlık görüntü: 168; izlenen evrene giren sembol: 285; saat başına AKTİF: ortalama 8.7, en az 1, en çok 25; aktif küme boş olup izlenen listeye düşülen saat: 0.
- Aktivite kararları: {'PASSIVE': 6938, 'ACTIVE': 1462}. Sinyal elemesi: 6208 ham sinyalden 455 tanesi o anda taranan sembolde (kalanı sistem görmezdi).

| Sembol | Aktif saat | Sinyal |
|---|---:|---:|
| NILTRY | 50 | 24 |
| AMPTRY | 49 | 17 |
| SENTTRY | 44 | 14 |
| INJTRY | 41 | 8 |
| PEPETRY | 39 | 15 |
| TIATRY | 39 | 12 |
| PYTHTRY | 35 | 21 |
| WLDTRY | 35 | 12 |
| WALTRY | 31 | 10 |
| EIGENTRY | 31 | 9 |
| ERATRY | 28 | 6 |
| ALTTRY | 27 | 10 |
| STRY | 26 | 5 |
| DODOTRY | 26 | 14 |
| MARSCOINTRY | 25 | 6 |
| LUMIATRY | 25 | 8 |
| ETHFITRY | 24 | 7 |
| PUMPTRY | 22 | 9 |
| ZROTRY | 21 | 7 |
| RADTRY | 20 | 5 |

Sadeleştirmeler: açık paper pozisyonlarının evrene eklenmesi yok; ticker `priceChangePercent` yerine 5m kapanış oranı; `_m1_activity_features` karara girmediği için hesaplanmadı; aktivite kararı yalnız izlenen sembollerde (canlıda izlenmeyen sembolün 5m serisi olmadığından WARMING kalır).
