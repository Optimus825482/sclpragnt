# MA BUY 7 günlük replay (CANLI sembol seçimiyle) — sinyal sonrası en yüksek yükseliş (2026-10-21 00:17)

Kapsam: son 7 gün, 153 (canlı seçim; evren 310) sembol, zaman dilimleri M5, M15, M30, H1. Kural ve parametreler canlı motorla aynı (SMA 7/20/99, StochRSI K ≤ 80 (1m hariç)).

**Ölçüt:** sinyal mumunun KAPANIŞINA göre, bir SONRAKİ sinyale (aynı sembol + TF) kadar görülen en yüksek `high` (MFE). Sonraki sinyali olmayan son sinyaller veri sonuna kadar ölçülür ve *açık uçlu* sayılır. 15 dk / 1 sa / 4 sa / 24 sa sütunları sabit ufuklardır, sonraki sinyalle sınırlanmaz.

## Özet (TF bazında)

| TF | Kural | Sinyal | Medyan MFE | Ortalama | P25 | P75 | ≥%1 | ≥%2 | ≥%3 | Hedefe dokunma | Zirveye medyan dk | Sonrakine medyan dk | Açık uçlu |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M5 | all | 237 | 2.24% | 4.24% | 1.04% | 5.86% | 0.76 | 0.53 | 0.42 | 0.62 | 135 | 1035 | 95 |
| M5 | fast_cross_mid | 185 | 2.11% | 4.11% | 0.93% | 5.34% | 0.75 | 0.51 | 0.39 | 0.61 | 130 | 815 | 71 |
| M5 | mid_cross_slow | 52 | 4.11% | 4.71% | 1.10% | 7.24% | 0.81 | 0.60 | 0.52 | 0.65 | 165.00 | 1580.00 | 24 |
| M15 | all | 12 | 12.11% | 15.55% | 4.82% | 25.10% | 1.00 | 0.83 | 0.83 | 0.83 | 772.50 | 4477.50 | 11 |
| M15 | fast_cross_mid | 11 | 12.67% | 15.91% | 3.19% | 26.04% | 1.00 | 0.82 | 0.82 | 0.82 | 1200 | 4440 | 10 |
| M15 | mid_cross_slow | 1 | 11.55% | 11.55% | — | — | 1.00 | 1.00 | 1.00 | 1.00 | 30 | 4515 | 1 |
| M30 | all | 25 | 4.70% | 5.37% | 1.23% | 7.59% | 0.84 | 0.64 | 0.56 | 0.60 | 270 | 4680 | 22 |
| M30 | fast_cross_mid | 23 | 4.93% | 5.59% | 1.25% | 8.14% | 0.83 | 0.65 | 0.57 | 0.61 | 300 | 4680 | 21 |
| M30 | mid_cross_slow | 2 | 2.94% | 2.94% | 0.32% | 5.57% | 1.00 | 0.50 | 0.50 | 0.50 | 60.00 | 5895.00 | 1 |
| H1 | all | 1 | 6.76% | 6.76% | — | — | 1.00 | 1.00 | 1.00 | 1.00 | 360 | 2640 | 1 |
| H1 | fast_cross_mid | 1 | 6.76% | 6.76% | — | — | 1.00 | 1.00 | 1.00 | 1.00 | 360 | 2640 | 1 |

## Sabit ufuklarda medyan en yüksek yükseliş

| TF | 15 dk | 1 sa | 4 sa | 24 sa |
|---|---:|---:|---:|---:|
| M5 | 0.37% (n=237) | 0.83% (n=236) | 1.42% (n=229) | 3.24% (n=206) |
| M15 | 1.16% (n=12) | 2.25% (n=12) | 5.76% (n=12) | 11.55% (n=11) |
| M30 | — | 0.78% (n=25) | 1.25% (n=25) | 2.34% (n=22) |
| H1 | — | 3.78% (n=1) | 5.16% (n=1) | 6.76% (n=1) |

## Sembol bazında sinyal sayısı

| Sembol | M5 | M15 | M30 | H1 | Toplam |
|---|---:|---:|---:|---:|---:|
| ACETRY | 1 | 1 | 0 | 0 | 2 |
| ACMTRY | 1 | 1 | 0 | 0 | 2 |
| ALTTRY | 6 | 1 | 0 | 0 | 7 |
| AMPTRY | 7 | 2 | 2 | 0 | 11 |
| APETRY | 1 | 0 | 0 | 0 | 1 |
| APTTRY | 2 | 0 | 0 | 0 | 2 |
| ARBTRY | 3 | 0 | 0 | 0 | 3 |
| ARKMTRY | 1 | 0 | 0 | 0 | 1 |
| ARTRY | 1 | 0 | 0 | 0 | 1 |
| ASTERTRY | 1 | 0 | 0 | 0 | 1 |
| ATRY | 3 | 0 | 1 | 0 | 4 |
| ATTRY | 1 | 0 | 0 | 0 | 1 |
| AUDIOTRY | 3 | 0 | 1 | 0 | 4 |
| AXLTRY | 2 | 0 | 1 | 0 | 3 |
| BABYTRY | 1 | 0 | 0 | 0 | 1 |
| BBTRY | 2 | 0 | 0 | 0 | 2 |
| BEAMXTRY | 1 | 0 | 1 | 0 | 2 |
| BERATRY | 2 | 0 | 0 | 0 | 2 |
| BMTTRY | 3 | 0 | 0 | 0 | 3 |
| BNBTRY | 1 | 0 | 0 | 0 | 1 |
| BTCTRY | 2 | 0 | 0 | 0 | 2 |
| CFGTRY | 2 | 0 | 0 | 0 | 2 |
| CHIPTRY | 2 | 0 | 1 | 0 | 3 |
| COMPTRY | 2 | 0 | 0 | 0 | 2 |
| CRVTRY | 1 | 0 | 0 | 0 | 1 |
| DODOTRY | 9 | 0 | 2 | 0 | 11 |
| EDENTRY | 1 | 0 | 0 | 0 | 1 |
| EIGENTRY | 4 | 0 | 1 | 0 | 5 |
| ENATRY | 3 | 0 | 0 | 0 | 3 |
| ERATRY | 4 | 1 | 0 | 0 | 5 |
| ETHFITRY | 4 | 0 | 1 | 0 | 5 |
| ETHTRY | 1 | 0 | 0 | 0 | 1 |
| FETTRY | 2 | 0 | 0 | 0 | 2 |
| FILTRY | 1 | 0 | 0 | 0 | 1 |
| GPSTRY | 1 | 0 | 0 | 0 | 1 |
| HBARTRY | 1 | 0 | 0 | 0 | 1 |
| HEITRY | 2 | 1 | 0 | 0 | 3 |
| HYPETRY | 1 | 0 | 0 | 0 | 1 |
| INITTRY | 1 | 0 | 0 | 0 | 1 |
| INJTRY | 7 | 0 | 1 | 0 | 8 |
| IOTRY | 1 | 0 | 0 | 0 | 1 |
| KITETRY | 1 | 0 | 0 | 0 | 1 |
| LAZIOTRY | 3 | 0 | 0 | 0 | 3 |
| LINEATRY | 1 | 0 | 0 | 0 | 1 |
| LUMIATRY | 3 | 0 | 0 | 0 | 3 |
| LUNATRY | 1 | 0 | 0 | 0 | 1 |
| MAGICTRY | 2 | 0 | 0 | 0 | 2 |
| MANTATRY | 1 | 0 | 0 | 0 | 1 |
| MANTRATRY | 1 | 0 | 0 | 0 | 1 |
| MARSCOINTRY | 3 | 0 | 0 | 0 | 3 |
| MEGATRY | 1 | 0 | 1 | 0 | 2 |
| METISTRY | 1 | 0 | 0 | 0 | 1 |
| MOVRTRY | 1 | 0 | 0 | 0 | 1 |
| MUBARAKTRY | 3 | 0 | 0 | 0 | 3 |
| NEARTRY | 4 | 0 | 0 | 0 | 4 |
| NILTRY | 6 | 0 | 0 | 0 | 6 |
| NMRTRY | 2 | 0 | 0 | 0 | 2 |
| NXPCTRY | 1 | 0 | 0 | 0 | 1 |
| ONDOTRY | 2 | 0 | 1 | 0 | 3 |
| ONETRY | 1 | 0 | 0 | 0 | 1 |
| OPGTRY | 3 | 0 | 0 | 0 | 3 |
| OPTRY | 2 | 0 | 0 | 0 | 2 |
| PARTITRY | 1 | 0 | 0 | 0 | 1 |
| PENGUTRY | 1 | 0 | 1 | 0 | 2 |
| PEPETRY | 11 | 0 | 0 | 0 | 11 |
| PHATRY | 0 | 1 | 1 | 0 | 2 |
| PLUMETRY | 1 | 0 | 0 | 0 | 1 |
| PUMPTRY | 4 | 0 | 0 | 0 | 4 |
| PYTHTRY | 12 | 1 | 0 | 0 | 13 |
| RADTRY | 4 | 0 | 1 | 0 | 5 |
| RARETRY | 2 | 0 | 2 | 0 | 4 |
| RAYTRY | 3 | 0 | 0 | 0 | 3 |
| ROSETRY | 1 | 0 | 0 | 0 | 1 |
| RSRTRY | 1 | 0 | 1 | 0 | 2 |
| RVNTRY | 2 | 0 | 0 | 0 | 2 |
| SANDTRY | 1 | 0 | 1 | 0 | 2 |
| SANTOSTRY | 1 | 0 | 0 | 0 | 1 |
| SEITRY | 2 | 0 | 0 | 0 | 2 |
| SENTTRY | 3 | 0 | 1 | 1 | 5 |
| SHELLTRY | 1 | 0 | 0 | 0 | 1 |
| SLPTRY | 1 | 0 | 0 | 0 | 1 |
| SOLTRY | 2 | 0 | 0 | 0 | 2 |
| SOLVTRY | 1 | 1 | 0 | 0 | 2 |
| STRAXTRY | 4 | 0 | 0 | 0 | 4 |
| STRKTRY | 0 | 0 | 1 | 0 | 1 |
| STRY | 4 | 0 | 0 | 0 | 4 |
| STXTRY | 1 | 0 | 0 | 0 | 1 |
| TAOTRY | 1 | 0 | 0 | 0 | 1 |
| TIATRY | 7 | 1 | 0 | 0 | 8 |
| WALTRY | 6 | 1 | 0 | 0 | 7 |
| WCTTRY | 2 | 0 | 0 | 0 | 2 |
| WLDTRY | 7 | 0 | 1 | 0 | 8 |
| XAUTTRY | 1 | 0 | 0 | 0 | 1 |
| XPLTRY | 1 | 0 | 1 | 0 | 2 |
| XRPTRY | 3 | 0 | 0 | 0 | 3 |
| ZKTRY | 3 | 0 | 0 | 0 | 3 |
| ZROTRY | 4 | 0 | 0 | 0 | 4 |

## En yüksek 10 yükseliş

| Sembol | TF | Kural | Sinyal zamanı | Fiyat | MFE | Zirveye dk | Sonrakine dk | Açık uçlu |
|---|---|---|---|---:|---:|---:|---:|---|
| PYTHTRY | M15 | fast_cross_mid | 14.10 21:45 | 4.081 | 40.90% | 1215 | 8670 | evet |
| WALTRY | M5 | fast_cross_mid | 14.10 04:55 | 2.02 | 36.24% | 620 | 620 | hayır |
| COMPTRY | M5 | fast_cross_mid | 20.10 19:05 | 1216 | 34.05% | 25 | 165 | hayır |
| PYTHTRY | M5 | fast_cross_mid | 15.10 14:45 | 4.293 | 33.94% | 195 | 435 | hayır |
| AMPTRY | M15 | fast_cross_mid | 18.10 13:15 | 0.0366 | 30.60% | 1200 | 3420 | evet |
| AMPTRY | M30 | fast_cross_mid | 17.10 16:00 | 0.0376 | 27.13% | 2460 | 4680 | evet |
| ALTTRY | M15 | fast_cross_mid | 17.10 20:15 | 0.434 | 26.04% | 3930 | 4440 | evet |
| BMTTRY | M5 | mid_cross_slow | 20.10 10:45 | 0.868 | 24.08% | 320 | 465 | hayır |
| ALTTRY | M5 | mid_cross_slow | 19.10 09:10 | 0.445 | 22.70% | 1290 | 1520 | hayır |
| WALTRY | M15 | fast_cross_mid | 14.10 19:15 | 2.737 | 22.29% | 315 | 8820 | evet |

## En zayıf 10 sinyal

| Sembol | TF | Kural | Sinyal zamanı | Fiyat | MFE | Zirveye dk | Sonrakine dk | Açık uçlu |
|---|---|---|---|---:|---:|---:|---:|---|
| PHATRY | M30 | fast_cross_mid | 20.10 09:00 | 3.28 | -0.30% | 30 | 780 | evet |
| AUDIOTRY | M30 | fast_cross_mid | 17.10 16:30 | 0.7875 | -0.18% | 30 | 4650 | evet |
| ZKTRY | M5 | mid_cross_slow | 14.10 12:15 | 0.792 | -0.13% | 5 | 1085 | hayır |
| WLDTRY | M5 | fast_cross_mid | 17.10 09:35 | 26.29 | -0.11% | 5 | 2725 | hayır |
| ONETRY | M5 | mid_cross_slow | 14.10 13:25 | 0.08456 | -0.06% | 5 | 8520 | evet |
| XPLTRY | M30 | fast_cross_mid | 16.10 10:00 | 4.256 | -0.05% | 30 | 6480 | evet |
| AUDIOTRY | M5 | fast_cross_mid | 16.10 23:00 | 0.81 | 0.00% | 5 | 1035 | hayır |
| MARSCOINTRY | M5 | fast_cross_mid | 14.10 07:40 | 4.27 | 0.00% | 5 | 3770 | hayır |
| PUMPTRY | M5 | fast_cross_mid | 19.10 07:40 | 0.2235 | 0.00% | 5 | 235 | hayır |
| PYTHTRY | M5 | fast_cross_mid | 14.10 16:40 | 4.194 | 0.00% | 5 | 375 | hayır |

## Dürüst sınırlar

- Mum verisi Binance TR herkese açık klines ucundan; sinyal mumu KAPANIŞI giriş fiyatı sayılır (spread/kayma yok).
- MFE "en yüksek görülen fiyat"tır, gerçekleşmiş kazanç değildir; çıkış kuralı simüle edilmemiştir.
- Açık uçlu sinyaller veri sonuna kadar ölçüldüğü için gerçek MFE daha yüksek olabilir.
- Sembol evreni raporun üretildiği andaki aktif + izlenen listedir; geçmişte aktif olup çıkanlar yoktur.

## Canlı sembol seçimi (yeniden üretim)

- Her 600 sn: 24 sa yükselenler ilk 50 (5m mumlardan: son kapanış / 24 sa önceki kapanış; 24 sa quote hacim). Her 3600 sn: aktivite filtresi (hacim ≥ 1,000,000 TL, 15 dk aralık ≥ %0.05, ATR ≥ 0.0012, hacim oranı ≥ 0.5, M1 düz mum filtresi açık [5/4, 30/25], kapsamlı pasiflik analizi).
- Saatlik anlık görüntü: 168; izlenen evrene giren sembol: 285; saat başına AKTİF: ortalama 8.7, en az 1, en çok 25; aktif küme boş olup izlenen listeye düşülen saat: 0.
- Aktivite kararları: {'PASSIVE': 6938, 'ACTIVE': 1462}. Sinyal elemesi: 4172 ham sinyalden 275 tanesi o anda taranan sembolde (kalanı sistem görmezdi).

| Sembol | Aktif saat | Sinyal |
|---|---:|---:|
| NILTRY | 50 | 6 |
| AMPTRY | 49 | 11 |
| SENTTRY | 44 | 5 |
| INJTRY | 41 | 8 |
| PEPETRY | 39 | 11 |
| TIATRY | 39 | 8 |
| PYTHTRY | 35 | 13 |
| WLDTRY | 35 | 8 |
| WALTRY | 31 | 7 |
| EIGENTRY | 31 | 5 |
| ERATRY | 28 | 5 |
| ALTTRY | 27 | 7 |
| STRY | 26 | 4 |
| DODOTRY | 26 | 11 |
| MARSCOINTRY | 25 | 3 |
| LUMIATRY | 25 | 3 |
| ETHFITRY | 24 | 5 |
| PUMPTRY | 22 | 4 |
| ZROTRY | 21 | 4 |
| RADTRY | 20 | 5 |

Sadeleştirmeler: açık paper pozisyonlarının evrene eklenmesi yok; ticker `priceChangePercent` yerine 5m kapanış oranı; `_m1_activity_features` karara girmediği için hesaplanmadı; aktivite kararı yalnız izlenen sembollerde (canlıda izlenmeyen sembolün 5m serisi olmadığından WARMING kalır).

## Ek kurallar (2026-10-21 tablosu)

M15: mum gövdesi ≥ %1 (yükseliş) ve RSI14 45–65 · M30: MACD(12,26,9) histogramı artıyor ve ADX14 > 20 · H1: son 3 mum yükseliş, 3 mumluk aralık ≥ %2, RSI14 45–65, ADX14 > 20 · M5: ek kural yok (karşılaştırma).

| Elenme nedeni | Sinyal |
|---|---:|
| 15m: mum gövdesi < %1 | 1290 |
| 30m: macd histogram artmıyor | 267 |
| 30m: adx ≤ 20 | 227 |
| 1h: son 3 mum yükseliş değil | 150 |
| 15m: rsi aralık dışı | 50 |
| 1h: rsi aralık dışı | 24 |
| 1h: dalga dar | 14 |
| 1h: adx ≤ 20 | 14 |
