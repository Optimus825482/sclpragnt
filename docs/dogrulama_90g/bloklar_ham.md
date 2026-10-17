

# ===== BLOK: 2026-07-20 .. 2026-08-18 =====
# Rejim kalkanı + aşırı alım kapısı — rescan ölçümü (2026-07-20 .. 2026-08-18)
Aday kaynağı: `rescan_90g_nogate.jsonl` (aşırı alım kapısı kapalı, journal cap 0). Birincil küme: tick başına sıralamaya giren adaylar (rank ≤ 10; canlı bildirim havuzuna en yakın) — satır 25443 (sembol-tick), bağımsız bölüm (60 dk) 7243; tüm geçenler 25489 satır. Mum: historical_candles 5m, 298 sembol. Net = TP / ilk SL −3% / ufuk sonu, −0.225% maliyet. Şans tabanı (null3) 7243 bölüm satırında ölçüldü.

## 0. Kalkan ne kadar süre açıktı? (5 dk tick payı, gün başına)
07-20 %1 · 07-21 %0 · 07-22 %0 · 07-23 %0 · 07-24 %33 · 07-25 %100 · 07-26 %98 · 07-27 %19 · 07-28 %99 · 07-29 %100 · 07-30 %61 · 07-31 %80 · 08-01 %100 · 08-02 %100 · 08-03 %81 · 08-04 %46 · 08-05 %0 · 08-06 %0 · 08-07 %0 · 08-08 %0 · 08-09 %0 · 08-10 %20 · 08-11 %84 · 08-12 %99 · 08-13 %100 · 08-14 %100 · 08-15 %100 · 08-16 %100 · 08-17 %64 · 08-18 %0

Toplam: tick'lerin **%53**'inde kalkan açık (BTC < 1H EMA200).

## 1. BTC rejim kalkanı (canlı kapılar aynen; bağımsız bölümler)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| Kalkan KAPALI — BTC ≥ EMA200 (bildirim gitti) | 2371 | %9.7 | %27.0 [25–29] | +2.98 | -2.65 | -0.31 (t -5.9) | +6.4 pp (n=2371) |
| Kalkan AÇIK — BTC < EMA200 (bildirim KESİLDİ) | 2452 | %8.9 | %25.5 [24–27] | +2.72 | -2.55 | -0.31 (t -6.3) | +5.8 pp (n=2452) |

Ön kayıtlı kural: **KALKAN_FAZLA_SIKI** (hit60 fark -1.5 puan; net60 farkı Welch t -0.11).

## 1b. Kalkan AÇIKKEN alt kümeler — yumuşatma adayı (sert = EMA'nın ≥%1 altı VE BTC 4 saatlik getiri < 0)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| Kalkan açık, YUMUŞAK bölge (gap > −1% ya da BTC 4s ≥ 0) → yumuşatılırsa bildirim gider | 1629 | %8.2 | %24.7 [23–27] | +2.66 | -2.60 | -0.39 (t -6.3) | +4.9 pp (n=1629) |
| Kalkan açık, SERT bölge (gap ≤ −1% ve BTC 4s < 0) → yine kesilir | 823 | %10.3 | %27.1 [24–30] | +2.83 | -2.46 | -0.17 (t -1.9) | +7.7 pp (n=823) |

## 2. Aşırı alım kapısı (MFI ≥ 90 / RSI ≥ 80) — kalkan KAPALI bölümlerde
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| Kapı GEÇTİ (bildirim gitti) | 2371 | %9.7 | %27.0 [25–29] | +2.98 | -2.65 | -0.31 (t -5.9) | +6.4 pp (n=2371) |
| Kapı ELEDİ (mfi/rsi_asiri_alim) | 1153 | %5.7 | %14.7 [13–17] | +1.77 | -1.75 | -0.47 (t -7.7) | +2.0 pp (n=1153) |

## 2b. Aşırı alım kapısı — trend_devam modu, kalkan KAPALI
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| trend_devam · geçti | 1232 | %8.0 | %22.2 [20–25] | +2.81 | -2.46 | -0.41 (t -5.7) | +3.7 pp (n=1232) |
| trend_devam · aşırı alım elendi | 1117 | %5.7 | %14.6 [13–17] | +1.76 | -1.75 | -0.47 (t -7.6) | +1.8 pp (n=1117) |

## 3. Kalkan × aşırı alım (bağımsız bölümler)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| kalkan kapalı · kapı geçti | 2371 | %9.7 | %27.0 [25–29] | +2.98 | -2.65 | -0.31 (t -5.9) | +6.4 pp (n=2371) |
| kalkan kapalı · aşırı alım | 1153 | %5.7 | %14.7 [13–17] | +1.77 | -1.75 | -0.47 (t -7.7) | +2.0 pp (n=1153) |
| kalkan açık · kapı geçti | 2452 | %8.9 | %25.5 [24–27] | +2.72 | -2.55 | -0.31 (t -6.3) | +5.8 pp (n=2452) |
| kalkan açık · aşırı alım | 1267 | %4.7 | %12.2 [10–14] | +1.52 | -1.95 | -0.64 (t -11.2) | -0.9 pp (n=1267) |

## 4. trend_devam modu × kalkan (kapı geçen)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| trend_devam · kalkan kapalı | 1232 | %8.0 | %22.2 [20–25] | +2.81 | -2.46 | -0.41 (t -5.7) | +3.7 pp (n=1232) |
| trend_devam · kalkan açık | 1270 | %8.2 | %22.8 [21–25] | +2.69 | -2.53 | -0.41 (t -6.0) | +4.6 pp (n=1270) |

## 5. Aynı kırılım, TÜM geçen adaylar (rank sınırı yok; bağımlı satırlar — yön teyidi)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| kalkan kapalı · geçti | 10624 | %12.7 | %32.6 [32–33] | +3.46 | -3.24 | -0.34 (t -12.9) | +6.4 pp (n=2371) |
| kalkan açık · geçti | 10262 | %12.0 | %32.0 [31–33] | +3.33 | -3.11 | -0.33 (t -12.4) | +5.8 pp (n=2452) |
| kalkan kapalı · aşırı alım | 2243 | %8.0 | %18.3 [17–20] | +2.30 | -2.14 | -0.41 (t -8.5) | +2.0 pp (n=1153) |
| kalkan açık · aşırı alım | 2360 | %6.6 | %15.2 [14–17] | +1.92 | -2.34 | -0.62 (t -13.9) | -0.9 pp (n=1267) |

## Sınırlar
- Pencere kısa/tek dönem olabilir; kalkanın açık olduğu günler kümelenmiş (rejim-dönem karışıklığı olası). Çoklu dönem için scripts/validation90_report.py.
- Rescan sapmaları (spread, taker oranı, ML hedef, kadans) docs/RESCAN_HARNESS.md'de; canlı adayların ~%90'ı yeniden üretiliyor.
- Giriş = aday fiyatı (bildirim anı); gecikmeli dolum yok. Hedef = adayın kendi target_pct'si; SL sabit.
- Şans tabanı yalnız örneklemde; 'şansa göre' sütunu hit60 − null3(hit). Çoklu karşılaştırma: tek t > 2 yeterli sayılmaz.


# ===== BLOK: 2026-08-19 .. 2026-09-17 =====
# Rejim kalkanı + aşırı alım kapısı — rescan ölçümü (2026-08-19 .. 2026-09-17)
Aday kaynağı: `rescan_90g_nogate.jsonl` (aşırı alım kapısı kapalı, journal cap 0). Birincil küme: tick başına sıralamaya giren adaylar (rank ≤ 10; canlı bildirim havuzuna en yakın) — satır 25428 (sembol-tick), bağımsız bölüm (60 dk) 8174; tüm geçenler 26622 satır. Mum: historical_candles 5m, 298 sembol. Net = TP / ilk SL −3% / ufuk sonu, −0.225% maliyet. Şans tabanı (null3) 8174 bölüm satırında ölçüldü.

## 0. Kalkan ne kadar süre açıktı? (5 dk tick payı, gün başına)
08-19 %0 · 08-20 %0 · 08-21 %0 · 08-22 %0 · 08-23 %0 · 08-24 %0 · 08-25 %0 · 08-26 %0 · 08-27 %0 · 08-28 %0 · 08-29 %22 · 08-30 %2 · 08-31 %44 · 09-01 %59 · 09-02 %100 · 09-03 %65 · 09-04 %0 · 09-05 %0 · 09-06 %0 · 09-07 %0 · 09-08 %58 · 09-09 %40 · 09-10 %100 · 09-11 %95 · 09-12 %100 · 09-13 %100 · 09-14 %68 · 09-15 %86 · 09-16 %100 · 09-17 %100

Toplam: tick'lerin **%38**'inde kalkan açık (BTC < 1H EMA200).

## 1. BTC rejim kalkanı (canlı kapılar aynen; bağımsız bölümler)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| Kalkan KAPALI — BTC ≥ EMA200 (bildirim gitti) | 3547 | %5.5 | %21.0 [20–22] | +2.33 | -2.27 | -0.30 (t -7.6) | +4.3 pp (n=3547) |
| Kalkan AÇIK — BTC < EMA200 (bildirim KESİLDİ) | 1786 | %7.1 | %22.9 [21–25] | +2.44 | -2.38 | -0.29 (t -5.1) | +5.2 pp (n=1786) |

Ön kayıtlı kural: **KALKAN_FAZLA_SIKI** (hit60 fark +1.9 puan; net60 farkı Welch t +0.08).

## 1b. Kalkan AÇIKKEN alt kümeler — yumuşatma adayı (sert = EMA'nın ≥%1 altı VE BTC 4 saatlik getiri < 0)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| Kalkan açık, YUMUŞAK bölge (gap > −1% ya da BTC 4s ≥ 0) → yumuşatılırsa bildirim gider | 1225 | %7.6 | %23.7 [21–26] | +2.48 | -2.50 | -0.29 (t -4.2) | +5.7 pp (n=1225) |
| Kalkan açık, SERT bölge (gap ≤ −1% ve BTC 4s < 0) → yine kesilir | 561 | %5.9 | %21.2 [18–25] | +2.35 | -2.11 | -0.29 (t -3.0) | +4.1 pp (n=561) |

## 2. Aşırı alım kapısı (MFI ≥ 90 / RSI ≥ 80) — kalkan KAPALI bölümlerde
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| Kapı GEÇTİ (bildirim gitti) | 3547 | %5.5 | %21.0 [20–22] | +2.33 | -2.27 | -0.30 (t -7.6) | +4.3 pp (n=3547) |
| Kapı ELEDİ (mfi/rsi_asiri_alim) | 1879 | %4.7 | %13.1 [12–15] | +1.69 | -1.89 | -0.48 (t -10.0) | +0.4 pp (n=1879) |

## 2b. Aşırı alım kapısı — trend_devam modu, kalkan KAPALI
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| trend_devam · geçti | 2089 | %4.6 | %19.0 [17–21] | +2.29 | -2.17 | -0.30 (t -5.8) | +3.6 pp (n=2089) |
| trend_devam · aşırı alım elendi | 1832 | %4.8 | %13.3 [12–15] | +1.70 | -1.89 | -0.48 (t -10.0) | +0.5 pp (n=1832) |

## 3. Kalkan × aşırı alım (bağımsız bölümler)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| kalkan kapalı · kapı geçti | 3547 | %5.5 | %21.0 [20–22] | +2.33 | -2.27 | -0.30 (t -7.6) | +4.3 pp (n=3547) |
| kalkan kapalı · aşırı alım | 1879 | %4.7 | %13.1 [12–15] | +1.69 | -1.89 | -0.48 (t -10.0) | +0.4 pp (n=1879) |
| kalkan açık · kapı geçti | 1786 | %7.1 | %22.9 [21–25] | +2.44 | -2.38 | -0.29 (t -5.1) | +5.2 pp (n=1786) |
| kalkan açık · aşırı alım | 962 | %4.8 | %15.3 [13–18] | +1.69 | -1.64 | -0.42 (t -6.2) | +2.2 pp (n=962) |

## 4. trend_devam modu × kalkan (kapı geçen)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| trend_devam · kalkan kapalı | 2089 | %4.6 | %19.0 [17–21] | +2.29 | -2.17 | -0.30 (t -5.8) | +3.6 pp (n=2089) |
| trend_devam · kalkan açık | 991 | %6.0 | %21.3 [19–24] | +2.37 | -2.18 | -0.25 (t -3.3) | +5.4 pp (n=991) |

## 5. Aynı kırılım, TÜM geçen adaylar (rank sınırı yok; bağımlı satırlar — yön teyidi)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| kalkan kapalı · geçti | 14074 | %8.2 | %26.6 [26–27] | +2.72 | -2.75 | -0.29 (t -13.6) | +4.3 pp (n=3547) |
| kalkan açık · geçti | 7196 | %9.9 | %28.6 [28–30] | +2.96 | -2.96 | -0.38 (t -12.3) | +5.2 pp (n=1786) |
| kalkan kapalı · aşırı alım | 3546 | %5.8 | %16.0 [15–17] | +1.94 | -2.17 | -0.47 (t -12.7) | +0.4 pp (n=1879) |
| kalkan açık · aşırı alım | 1806 | %6.1 | %17.8 [16–20] | +2.01 | -1.97 | -0.37 (t -7.0) | +2.2 pp (n=962) |

## Sınırlar
- Pencere kısa/tek dönem olabilir; kalkanın açık olduğu günler kümelenmiş (rejim-dönem karışıklığı olası). Çoklu dönem için scripts/validation90_report.py.
- Rescan sapmaları (spread, taker oranı, ML hedef, kadans) docs/RESCAN_HARNESS.md'de; canlı adayların ~%90'ı yeniden üretiliyor.
- Giriş = aday fiyatı (bildirim anı); gecikmeli dolum yok. Hedef = adayın kendi target_pct'si; SL sabit.
- Şans tabanı yalnız örneklemde; 'şansa göre' sütunu hit60 − null3(hit). Çoklu karşılaştırma: tek t > 2 yeterli sayılmaz.


# ===== BLOK: 2026-09-18 .. 2026-10-16 =====
# Rejim kalkanı + aşırı alım kapısı — rescan ölçümü (2026-09-18 .. 2026-10-16)
Aday kaynağı: `rescan_90g_nogate.jsonl` (aşırı alım kapısı kapalı, journal cap 0). Birincil küme: tick başına sıralamaya giren adaylar (rank ≤ 10; canlı bildirim havuzuna en yakın) — satır 28859 (sembol-tick), bağımsız bölüm (60 dk) 8659; tüm geçenler 29778 satır. Mum: historical_candles 5m, 298 sembol. Net = TP / ilk SL −3% / ufuk sonu, −0.225% maliyet. Şans tabanı (null3) 8659 bölüm satırında ölçüldü.

## 0. Kalkan ne kadar süre açıktı? (5 dk tick payı, gün başına)
09-18 %27 · 09-19 %0 · 09-20 %0 · 09-21 %0 · 09-22 %0 · 09-23 %0 · 09-24 %0 · 09-25 %0 · 09-26 %0 · 09-27 %0 · 09-28 %65 · 09-29 %78 · 09-30 %85 · 10-01 %63 · 10-02 %0 · 10-03 %0 · 10-04 %0 · 10-05 %0 · 10-06 %0 · 10-07 %79 · 10-08 %100 · 10-09 %100 · 10-10 %100 · 10-11 %100 · 10-12 %94 · 10-13 %77 · 10-14 %55 · 10-15 %100 · 10-16 %97

Toplam: tick'lerin **%42**'inde kalkan açık (BTC < 1H EMA200).

## 1. BTC rejim kalkanı (canlı kapılar aynen; bağımsız bölümler)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| Kalkan KAPALI — BTC ≥ EMA200 (bildirim gitti) | 3662 | %7.0 | %23.1 [22–24] | +2.44 | -2.37 | -0.39 (t -9.8) | +5.3 pp (n=3662) |
| Kalkan AÇIK — BTC < EMA200 (bildirim KESİLDİ) | 2350 | %7.2 | %21.8 [20–24] | +2.41 | -2.30 | -0.37 (t -7.4) | +5.4 pp (n=2350) |

Ön kayıtlı kural: **KALKAN_FAZLA_SIKI** (hit60 fark -1.3 puan; net60 farkı Welch t +0.28).

## 1b. Kalkan AÇIKKEN alt kümeler — yumuşatma adayı (sert = EMA'nın ≥%1 altı VE BTC 4 saatlik getiri < 0)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| Kalkan açık, YUMUŞAK bölge (gap > −1% ya da BTC 4s ≥ 0) → yumuşatılırsa bildirim gider | 1564 | %6.7 | %20.9 [19–23] | +2.32 | -2.34 | -0.41 (t -6.7) | +4.5 pp (n=1564) |
| Kalkan açık, SERT bölge (gap ≤ −1% ve BTC 4s < 0) → yine kesilir | 786 | %8.1 | %23.7 [21–27] | +2.59 | -2.23 | -0.29 (t -3.4) | +7.3 pp (n=786) |

## 2. Aşırı alım kapısı (MFI ≥ 90 / RSI ≥ 80) — kalkan KAPALI bölümlerde
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| Kapı GEÇTİ (bildirim gitti) | 3662 | %7.0 | %23.1 [22–24] | +2.44 | -2.37 | -0.39 (t -9.8) | +5.3 pp (n=3662) |
| Kapı ELEDİ (mfi/rsi_asiri_alim) | 1661 | %6.3 | %18.0 [16–20] | +2.00 | -1.92 | -0.32 (t -5.9) | +4.1 pp (n=1661) |

## 2b. Aşırı alım kapısı — trend_devam modu, kalkan KAPALI
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| trend_devam · geçti | 2148 | %6.1 | %20.9 [19–23] | +2.39 | -2.25 | -0.41 (t -7.9) | +4.8 pp (n=2148) |
| trend_devam · aşırı alım elendi | 1616 | %6.2 | %17.7 [16–20] | +1.98 | -1.92 | -0.34 (t -6.1) | +3.7 pp (n=1616) |

## 3. Kalkan × aşırı alım (bağımsız bölümler)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| kalkan kapalı · kapı geçti | 3662 | %7.0 | %23.1 [22–24] | +2.44 | -2.37 | -0.39 (t -9.8) | +5.3 pp (n=3662) |
| kalkan kapalı · aşırı alım | 1661 | %6.3 | %18.0 [16–20] | +2.00 | -1.92 | -0.32 (t -5.9) | +4.1 pp (n=1661) |
| kalkan açık · kapı geçti | 2350 | %7.2 | %21.8 [20–24] | +2.41 | -2.30 | -0.37 (t -7.4) | +5.4 pp (n=2350) |
| kalkan açık · aşırı alım | 986 | %6.2 | %16.6 [14–19] | +2.08 | -1.77 | -0.29 (t -4.2) | +3.6 pp (n=986) |

## 4. trend_devam modu × kalkan (kapı geçen)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| trend_devam · kalkan kapalı | 2148 | %6.1 | %20.9 [19–23] | +2.39 | -2.25 | -0.41 (t -7.9) | +4.8 pp (n=2148) |
| trend_devam · kalkan açık | 1311 | %6.7 | %19.5 [17–22] | +2.30 | -2.27 | -0.44 (t -6.6) | +4.2 pp (n=1311) |

## 5. Aynı kırılım, TÜM geçen adaylar (rank sınırı yok; bağımlı satırlar — yön teyidi)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| kalkan kapalı · geçti | 15208 | %10.2 | %28.8 [28–30] | +2.89 | -2.94 | -0.42 (t -19.9) | +5.3 pp (n=3662) |
| kalkan açık · geçti | 9281 | %10.0 | %28.1 [27–29] | +2.92 | -2.83 | -0.41 (t -15.3) | +5.4 pp (n=2350) |
| kalkan kapalı · aşırı alım | 3251 | %7.8 | %20.7 [19–22] | +2.36 | -2.28 | -0.36 (t -8.7) | +4.1 pp (n=1661) |
| kalkan açık · aşırı alım | 2038 | %8.1 | %20.7 [19–22] | +2.51 | -2.13 | -0.24 (t -4.6) | +3.6 pp (n=986) |

## Sınırlar
- Pencere kısa/tek dönem olabilir; kalkanın açık olduğu günler kümelenmiş (rejim-dönem karışıklığı olası). Çoklu dönem için scripts/validation90_report.py.
- Rescan sapmaları (spread, taker oranı, ML hedef, kadans) docs/RESCAN_HARNESS.md'de; canlı adayların ~%90'ı yeniden üretiliyor.
- Giriş = aday fiyatı (bildirim anı); gecikmeli dolum yok. Hedef = adayın kendi target_pct'si; SL sabit.
- Şans tabanı yalnız örneklemde; 'şansa göre' sütunu hit60 − null3(hit). Çoklu karşılaştırma: tek t > 2 yeterli sayılmaz.


# ===== BLOK: TÜM PENCERE 2026-07-20 .. 2026-10-16 =====
# Rejim kalkanı + aşırı alım kapısı — rescan ölçümü (2026-07-20 .. 2026-10-16)
Aday kaynağı: `rescan_90g_nogate.jsonl` (aşırı alım kapısı kapalı, journal cap 0). Birincil küme: tick başına sıralamaya giren adaylar (rank ≤ 10; canlı bildirim havuzuna en yakın) — satır 79730 (sembol-tick), bağımsız bölüm (60 dk) 24076; tüm geçenler 81889 satır. Mum: historical_candles 5m, 298 sembol. Net = TP / ilk SL −3% / ufuk sonu, −0.225% maliyet. Şans tabanı (null3) 24076 bölüm satırında ölçüldü.

## 0. Kalkan ne kadar süre açıktı? (5 dk tick payı, gün başına)
07-20 %1 · 07-21 %0 · 07-22 %0 · 07-23 %0 · 07-24 %33 · 07-25 %100 · 07-26 %98 · 07-27 %19 · 07-28 %99 · 07-29 %100 · 07-30 %61 · 07-31 %80 · 08-01 %100 · 08-02 %100 · 08-03 %81 · 08-04 %46 · 08-05 %0 · 08-06 %0 · 08-07 %0 · 08-08 %0 · 08-09 %0 · 08-10 %20 · 08-11 %84 · 08-12 %99 · 08-13 %100 · 08-14 %100 · 08-15 %100 · 08-16 %100 · 08-17 %64 · 08-18 %0 · 08-19 %0 · 08-20 %0 · 08-21 %0 · 08-22 %0 · 08-23 %0 · 08-24 %0 · 08-25 %0 · 08-26 %0 · 08-27 %0 · 08-28 %0 · 08-29 %22 · 08-30 %2 · 08-31 %44 · 09-01 %59 · 09-02 %100 · 09-03 %65 · 09-04 %0 · 09-05 %0 · 09-06 %0 · 09-07 %0 · 09-08 %58 · 09-09 %40 · 09-10 %100 · 09-11 %95 · 09-12 %100 · 09-13 %100 · 09-14 %68 · 09-15 %86 · 09-16 %100 · 09-17 %100 · 09-18 %27 · 09-19 %0 · 09-20 %0 · 09-21 %0 · 09-22 %0 · 09-23 %0 · 09-24 %0 · 09-25 %0 · 09-26 %0 · 09-27 %0 · 09-28 %65 · 09-29 %78 · 09-30 %85 · 10-01 %63 · 10-02 %0 · 10-03 %0 · 10-04 %0 · 10-05 %0 · 10-06 %0 · 10-07 %79 · 10-08 %100 · 10-09 %100 · 10-10 %100 · 10-11 %100 · 10-12 %94 · 10-13 %77 · 10-14 %55 · 10-15 %100 · 10-16 %97

Toplam: tick'lerin **%44**'inde kalkan açık (BTC < 1H EMA200).

## 1. BTC rejim kalkanı (canlı kapılar aynen; bağımsız bölümler)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| Kalkan KAPALI — BTC ≥ EMA200 (bildirim gitti) | 9580 | %7.1 | %23.3 [22–24] | +2.53 | -2.40 | -0.33 (t -13.5) | +5.2 pp (n=9580) |
| Kalkan AÇIK — BTC < EMA200 (bildirim KESİLDİ) | 6588 | %7.8 | %23.5 [22–25] | +2.53 | -2.42 | -0.33 (t -10.9) | +5.5 pp (n=6588) |

Ön kayıtlı kural: **KALKAN_FAZLA_SIKI** (hit60 fark +0.2 puan; net60 farkı Welch t +0.16).

## 1b. Kalkan AÇIKKEN alt kümeler — yumuşatma adayı (sert = EMA'nın ≥%1 altı VE BTC 4 saatlik getiri < 0)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| Kalkan açık, YUMUŞAK bölge (gap > −1% ya da BTC 4s ≥ 0) → yumuşatılırsa bildirim gider | 4418 | %7.5 | %23.1 [22–24] | +2.49 | -2.48 | -0.37 (t -10.0) | +5.0 pp (n=4418) |
| Kalkan açık, SERT bölge (gap ≤ −1% ve BTC 4s < 0) → yine kesilir | 2170 | %8.4 | %24.3 [23–26] | +2.62 | -2.28 | -0.25 (t -4.7) | +6.6 pp (n=2170) |

## 2. Aşırı alım kapısı (MFI ≥ 90 / RSI ≥ 80) — kalkan KAPALI bölümlerde
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| Kapı GEÇTİ (bildirim gitti) | 9580 | %7.1 | %23.3 [22–24] | +2.53 | -2.40 | -0.33 (t -13.5) | +5.2 pp (n=9580) |
| Kapı ELEDİ (mfi/rsi_asiri_alim) | 4693 | %5.5 | %15.3 [14–16] | +1.82 | -1.87 | -0.42 (t -13.6) | +2.1 pp (n=4693) |

## 2b. Aşırı alım kapısı — trend_devam modu, kalkan KAPALI
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| trend_devam · geçti | 5469 | %6.0 | %20.4 [19–22] | +2.45 | -2.27 | -0.37 (t -11.3) | +4.1 pp (n=5469) |
| trend_devam · aşırı alım elendi | 4565 | %5.5 | %15.2 [14–16] | +1.81 | -1.86 | -0.43 (t -13.6) | +2.0 pp (n=4565) |

## 3. Kalkan × aşırı alım (bağımsız bölümler)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| kalkan kapalı · kapı geçti | 9580 | %7.1 | %23.3 [22–24] | +2.53 | -2.40 | -0.33 (t -13.5) | +5.2 pp (n=9580) |
| kalkan kapalı · aşırı alım | 4693 | %5.5 | %15.3 [14–16] | +1.82 | -1.87 | -0.42 (t -13.6) | +2.1 pp (n=4693) |
| kalkan açık · kapı geçti | 6588 | %7.8 | %23.5 [22–25] | +2.53 | -2.42 | -0.33 (t -10.9) | +5.5 pp (n=6588) |
| kalkan açık · aşırı alım | 3215 | %5.2 | %14.5 [13–16] | +1.74 | -1.80 | -0.47 (t -12.6) | +1.4 pp (n=3215) |

## 4. trend_devam modu × kalkan (kapı geçen)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| trend_devam · kalkan kapalı | 5469 | %6.0 | %20.4 [19–22] | +2.45 | -2.27 | -0.37 (t -11.3) | +4.1 pp (n=5469) |
| trend_devam · kalkan açık | 3572 | %7.0 | %21.2 [20–23] | +2.46 | -2.34 | -0.38 (t -9.3) | +4.6 pp (n=3572) |

## 5. Aynı kırılım, TÜM geçen adaylar (rank sınırı yok; bağımlı satırlar — yön teyidi)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| kalkan kapalı · geçti | 39906 | %10.2 | %29.0 [29–29] | +2.98 | -2.95 | -0.35 (t -27.1) | +5.2 pp (n=9580) |
| kalkan açık · geçti | 26739 | %10.7 | %29.7 [29–30] | +3.09 | -2.97 | -0.37 (t -23.0) | +5.5 pp (n=6588) |
| kalkan kapalı · aşırı alım | 9040 | %7.1 | %18.2 [17–19] | +2.18 | -2.20 | -0.41 (t -17.3) | +2.1 pp (n=4693) |
| kalkan açık · aşırı alım | 6204 | %6.9 | %17.7 [17–19] | +2.14 | -2.16 | -0.42 (t -14.7) | +1.4 pp (n=3215) |

## Sınırlar
- Pencere kısa/tek dönem olabilir; kalkanın açık olduğu günler kümelenmiş (rejim-dönem karışıklığı olası). Çoklu dönem için scripts/validation90_report.py.
- Rescan sapmaları (spread, taker oranı, ML hedef, kadans) docs/RESCAN_HARNESS.md'de; canlı adayların ~%90'ı yeniden üretiliyor.
- Giriş = aday fiyatı (bildirim anı); gecikmeli dolum yok. Hedef = adayın kendi target_pct'si; SL sabit.
- Şans tabanı yalnız örneklemde; 'şansa göre' sütunu hit60 − null3(hit). Çoklu karşılaştırma: tek t > 2 yeterli sayılmaz.


# ===== TAKER DOĞRULAMA =====
Canlı-benzeri küme (rank<=10, aşırı alım değil, bağımsız bölüm): 16168; taker verisi yok: 1 (%0.0).

#### A. Taker sınıfı — 2026-07-20 .. 2026-08-18
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| taker strong | 1878 | %8.0 | %24.1 [22–26] | +2.77 | -2.20 | -0.23 (t -4.1) | +6.0 pp (n=1878) |
| taker neutral | 1632 | %12.3 | %31.9 [30–34] | +3.33 | -3.27 | -0.31 (t -4.7) | +7.9 pp (n=1632) |
| taker weak | 1313 | %7.5 | %22.4 [20–25] | +2.36 | -2.34 | -0.41 (t -6.5) | +3.9 pp (n=1313) |

strong − weak: hit60 +1.7 pp (z +1.10); net60 +0.18 (Welch t +2.14); şansa göre lift farkı +2.1 pp.

#### A. Taker sınıfı — 2026-08-19 .. 2026-09-17
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| taker strong | 2249 | %5.2 | %20.9 [19–23] | +2.31 | -2.05 | -0.20 (t -4.1) | +5.2 pp (n=2249) |
| taker neutral | 1669 | %7.7 | %24.1 [22–26] | +2.61 | -2.62 | -0.35 (t -5.7) | +4.4 pp (n=1669) |
| taker weak | 1415 | %5.4 | %19.9 [18–22] | +2.17 | -2.34 | -0.38 (t -6.4) | +3.8 pp (n=1415) |

strong − weak: hit60 +0.9 pp (z +0.67); net60 +0.18 (Welch t +2.27); şansa göre lift farkı +1.4 pp.

#### A. Taker sınıfı — 2026-09-18 .. 2026-10-16
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| taker strong | 2332 | %6.1 | %20.3 [19–22] | +2.28 | -2.13 | -0.37 (t -7.6) | +4.6 pp (n=2332) |
| taker neutral | 2013 | %9.0 | %26.9 [25–29] | +2.84 | -2.73 | -0.41 (t -7.1) | +7.1 pp (n=2013) |
| taker weak | 1666 | %6.1 | %20.6 [19–23] | +2.13 | -2.16 | -0.37 (t -6.6) | +4.1 pp (n=1666) |

strong − weak: hit60 -0.3 pp (z -0.20); net60 -0.00 (Welch t -0.04); şansa göre lift farkı +0.5 pp.

#### A. Taker sınıfı — TÜM PENCERE
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| taker strong | 6459 | %6.3 | %21.6 [21–23] | +2.43 | -2.12 | -0.27 (t -9.2) | +5.2 pp (n=6459) |
| taker neutral | 5314 | %9.6 | %27.5 [26–29] | +2.92 | -2.86 | -0.36 (t -10.1) | +6.5 pp (n=5314) |
| taker weak | 4394 | %6.3 | %20.9 [20–22] | +2.21 | -2.27 | -0.38 (t -11.3) | +4.0 pp (n=4394) |

strong − weak: hit60 +0.7 pp (z +0.85); net60 +0.11 (Welch t +2.50); şansa göre lift farkı +1.3 pp.

Ön kayıtlı taker kuralı: **TAKER_BELIRSIZ** (blok farkları pp: +1.7, +0.9, -0.3).

#### A2. Taker sınıfı × kalkan durumu (tüm pencere)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| kalkan kapalı · taker strong | 3883 | %6.0 | %21.2 [20–23] | +2.45 | -2.10 | -0.27 (t -7.0) | +4.9 pp (n=3883) |
| kalkan kapalı · taker weak | 2566 | %6.3 | %21.3 [20–23] | +2.19 | -2.30 | -0.42 (t -9.2) | +4.0 pp (n=2566) |
| kalkan açık · taker strong | 2576 | %6.9 | %22.1 [21–24] | +2.40 | -2.15 | -0.28 (t -5.9) | +5.7 pp (n=2576) |
| kalkan açık · taker weak | 1828 | %6.3 | %20.4 [19–22] | +2.24 | -2.24 | -0.34 (t -6.5) | +3.9 pp (n=1828) |

#### B. taker_buy_ratio ondalıkları (tüm pencere, eşit sayıda gözlem)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| D1 [−∞, 0.330) | 1607 | %3.3 | %16.4 [15–18] | +1.72 | -1.72 | -0.37 (t -7.3) | +3.5 pp (n=1607) |
| D2 [0.330, 0.412) | 1604 | %7.4 | %22.1 [20–24] | +2.38 | -2.45 | -0.41 (t -7.0) | +3.8 pp (n=1604) |
| D3 [0.412, 0.464) | 1638 | %8.9 | %26.1 [24–28] | +2.65 | -2.80 | -0.39 (t -6.3) | +5.6 pp (n=1638) |
| D4 [0.464, 0.504) | 1598 | %9.9 | %28.1 [26–30] | +2.91 | -2.78 | -0.36 (t -5.6) | +6.6 pp (n=1598) |
| D5 [0.504, 0.542) | 1629 | %10.7 | %28.1 [26–30] | +2.95 | -2.93 | -0.30 (t -4.7) | +7.0 pp (n=1629) |
| D6 [0.542, 0.580) | 1612 | %8.4 | %26.2 [24–28] | +2.94 | -2.90 | -0.42 (t -6.4) | +5.5 pp (n=1612) |
| D7 [0.580, 0.622) | 1618 | %7.8 | %26.1 [24–28] | +2.89 | -2.42 | -0.22 (t -3.4) | +6.4 pp (n=1618) |
| D8 [0.622, 0.672) | 1603 | %7.6 | %23.4 [21–26] | +2.64 | -2.33 | -0.31 (t -5.0) | +5.3 pp (n=1603) |
| D9 [0.672, 0.752) | 1637 | %6.0 | %20.5 [19–22] | +2.34 | -2.06 | -0.28 (t -4.9) | +5.2 pp (n=1637) |
| D10 [0.752, +∞) | 1621 | %3.8 | %16.7 [15–19] | +1.88 | -1.67 | -0.25 (t -4.9) | +4.2 pp (n=1621) |

Ondalık sırası ile hit60 arasında Spearman ρ = -0.08.

#### C. taker_buy_ratio sabit kutular (tüm pencere)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| [0.00, 0.35) | 1893 | %3.8 | %17.2 [16–19] | +1.78 | -1.85 | -0.38 (t -8.0) | +3.6 pp (n=1893) |
| [0.35, 0.40) | 983 | %7.4 | %22.8 [20–26] | +2.44 | -2.42 | -0.40 (t -5.3) | +4.2 pp (n=983) |
| [0.40, 0.45) | 1504 | %8.6 | %24.3 [22–26] | +2.60 | -2.70 | -0.39 (t -6.2) | +4.1 pp (n=1504) |
| [0.45, 0.50) | 1896 | %9.8 | %28.5 [26–31] | +2.88 | -2.79 | -0.36 (t -6.0) | +7.2 pp (n=1896) |
| [0.50, 0.55) | 2165 | %10.5 | %27.7 [26–30] | +2.93 | -2.91 | -0.34 (t -6.1) | +6.6 pp (n=2165) |
| [0.55, 0.58) | 1247 | %7.9 | %25.6 [23–28] | +2.91 | -2.91 | -0.42 (t -5.6) | +5.3 pp (n=1247) |
| [0.58, 0.62) | 1529 | %7.8 | %26.1 [24–28] | +2.90 | -2.41 | -0.21 (t -3.3) | +6.3 pp (n=1529) |
| [0.62, 0.70) | 2383 | %6.9 | %22.7 [21–24] | +2.52 | -2.31 | -0.32 (t -6.4) | +5.3 pp (n=2383) |
| [0.70, 1.01) | 2567 | %4.9 | %18.1 [17–20] | +2.08 | -1.77 | -0.25 (t -5.7) | +4.7 pp (n=2567) |

#### D. Eşik taraması (tüm pencere): oran >= c  vs  oran < c
| c | n(>=c) | hit60(>=c) | n(<c) | hit60(<c) | fark pp | z | net60 (>=c) | net60 (<c) | Welch t | lift(>=c) | lift(<c) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.40 | 13291 | %24.3 | 2876 | %19.1 | +5.2 | +5.97 | -0.32 | -0.39 | +1.44 | +5.6 | +3.8 |
| 0.45 | 11787 | %24.3 | 4380 | %20.9 | +3.4 | +4.57 | -0.31 | -0.39 | +1.90 | +5.8 | +3.9 |
| 0.48 | 10695 | %23.9 | 5472 | %22.4 | +1.5 | +2.10 | -0.31 | -0.38 | +1.99 | +5.7 | +4.6 |
| 0.50 | 9891 | %23.5 | 6276 | %23.2 | +0.3 | +0.47 | -0.30 | -0.38 | +1.98 | +5.6 | +4.9 |
| 0.52 | 9049 | %23.1 | 7118 | %23.7 | -0.6 | -0.86 | -0.29 | -0.38 | +2.31 | +5.5 | +5.1 |
| 0.55 | 7726 | %22.3 | 8441 | %24.3 | -2.0 | -3.05 | -0.29 | -0.37 | +2.07 | +5.3 | +5.3 |
| 0.58 | 6479 | %21.7 | 9688 | %24.5 | -2.8 | -4.16 | -0.27 | -0.38 | +2.82 | +5.3 | +5.3 |
| 0.60 | 5651 | %21.0 | 10516 | %24.6 | -3.7 | -5.23 | -0.27 | -0.36 | +2.38 | +5.1 | +5.4 |
| 0.62 | 4950 | %20.3 | 11217 | %24.7 | -4.4 | -6.11 | -0.28 | -0.35 | +1.76 | +5.0 | +5.5 |
| 0.65 | 3898 | %19.6 | 12269 | %24.5 | -4.9 | -6.33 | -0.26 | -0.36 | +2.29 | +5.2 | +5.3 |

#### E. Çarpanın marjinal etkisi (karşı-olgusal sıralama; bağımlı satırlar, bölüm tekilleştirmesi yok)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| TERFİ: çarpanla top-10'a girdi (çarpansız dışında) — strong bonusu sayesinde | 26 | %3.8 | %11.5 [4–29] | +1.68 | -3.09 | -0.36 (t -1.0) | +2.0 pp (n=15) |
| DÜŞÜŞ: çarpanla top-10'dan çıktı (çarpansız içinde) — weak cezası yüzünden | 29 | %0.0 | %10.3 [4–26] | +1.55 | -2.38 | -0.54 (t -1.3) | — |
| DEĞİŞMEYEN: iki durumda da top-10 | 65027 | %10.6 | %29.7 [29–30] | +3.06 | -2.99 | -0.36 (t -35.1) | +5.3 pp (n=16153) |

TERFİ − DÜŞÜŞ hit60 farkı +1.2 pp, gün-küme bootstrap %95 GA [-14.3, +17.0].
#### F. Kaba taker kutuları × blok (hit60 / lift pp / net60, n)
| kutu | 2026-07-20 .. 2026-08-18 | 2026-08-19 .. 2026-09-17 | 2026-09-18 .. 2026-10-16 | TÜM |
|---|---|---|---|---|
| [0.00, 0.35) | %17.3 / +3.4 / -0.41 (n=562) | %16.2 / +3.0 / -0.40 (n=619) | %18.0 / +4.3 / -0.34 (n=712) | %17.2 / +3.6 / -0.38 (n=1893) |
| [0.35, 0.45) | %26.3 / +4.4 / -0.42 (n=746) | %22.7 / +4.1 / -0.38 (n=790) | %22.5 / +3.9 / -0.39 (n=951) | %23.7 / +4.1 / -0.40 (n=2487) |
| [0.45, 0.58) | %31.8 / +7.8 / -0.32 (n=1628) | %24.1 / +4.5 / -0.35 (n=1670) | %26.8 / +7.1 / -0.41 (n=2010) | %27.5 / +6.5 / -0.36 (n=5308) |
| [0.58, 0.70) | %28.1 / +7.4 / -0.23 (n=1153) | %22.9 / +5.6 / -0.22 (n=1346) | %21.8 / +4.2 / -0.38 (n=1413) | %24.0 / +5.7 / -0.28 (n=3912) |
| [0.70, 1.01) | %18.0 / +4.0 / -0.22 (n=734) | %18.0 / +4.6 / -0.17 (n=908) | %18.3 / +5.3 / -0.34 (n=925) | %18.1 / +4.7 / -0.25 (n=2567) |

# ===== ASIRI ALIM KAPISI AYRISTIRMA =====

#### G1. MFI14(1m) kutuları (tüm pencere, rank<=10 bölümler, kalkan fark etmez)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| MFI [0, 60) | 6594 | %7.7 | %24.3 [23–25] | +2.47 | -2.44 | -0.34 (t -11.5) | +5.9 pp (n=6594) |
| MFI [60, 70) | 3152 | %8.5 | %25.5 [24–27] | +2.84 | -2.59 | -0.34 (t -7.4) | +5.8 pp (n=3152) |
| MFI [70, 80) | 3871 | %6.8 | %21.7 [20–23] | +2.51 | -2.42 | -0.34 (t -8.6) | +4.3 pp (n=3871) |
| MFI [80, 90) | 4058 | %6.2 | %18.9 [18–20] | +2.22 | -2.04 | -0.33 (t -9.2) | +3.2 pp (n=4058) |
| MFI [90, 95) | 2010 | %5.3 | %16.9 [15–19] | +2.02 | -1.83 | -0.36 (t -7.3) | +2.5 pp (n=2010) |
| MFI [95, 101) | 4391 | %5.1 | %13.8 [13–15] | +1.60 | -1.79 | -0.49 (t -16.0) | +1.9 pp (n=4391) |

#### G1b. RSI14(1m) kutuları (tüm pencere)
| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| RSI [0, 60) | 7343 | %8.5 | %26.4 [25–27] | +2.61 | -2.52 | -0.28 (t -9.8) | +6.6 pp (n=7343) |
| RSI [60, 70) | 6039 | %6.2 | %21.1 [20–22] | +2.45 | -2.30 | -0.37 (t -11.9) | +4.6 pp (n=6039) |
| RSI [70, 75) | 3066 | %5.6 | %18.4 [17–20] | +2.25 | -2.06 | -0.36 (t -8.7) | +3.7 pp (n=3066) |
| RSI [75, 80) | 2557 | %5.1 | %16.3 [15–18] | +1.96 | -1.97 | -0.45 (t -10.2) | +2.1 pp (n=2557) |
| RSI [80, 85) | 1881 | %6.0 | %15.6 [14–17] | +2.01 | -1.90 | -0.37 (t -7.3) | +1.3 pp (n=1881) |
| RSI [85, 101) | 3190 | %6.4 | %14.7 [14–16] | +1.69 | -1.91 | -0.51 (t -13.6) | +1.5 pp (n=3190) |

#### G2. Kapı varyantları — kalkan KAPALI bölümlerde elenen vs geçen (hit60 / lift pp / net60)
| varyant | 2026-07-20 .. 2026-08-18 | 2026-08-19 .. 2026-09-17 | 2026-09-18 .. 2026-10-16 | TÜM |
|---|---|---|---|---|
| MFI>=90 veya RSI>=80 (canlı) | elenen %14.7 / +2.0 / -0.47 (n=1153) · geçen %27.0 / +6.4 / -0.31 | elenen %13.1 / +0.4 / -0.48 (n=1879) · geçen %21.0 / +4.3 / -0.30 | elenen %18.0 / +4.1 / -0.32 (n=1661) · geçen %23.1 / +5.3 / -0.39 | elenen %15.3 / +2.1 / -0.42 (n=4693) · geçen %23.3 / +5.2 / -0.33 |
| yalnız MFI>=90 | elenen %13.9 / +1.6 / -0.53 (n=966) · geçen %26.5 / +6.2 / -0.30 | elenen %12.7 / +0.3 / -0.52 (n=1511) · geçen %20.4 / +3.9 / -0.30 | elenen %18.8 / +5.4 / -0.30 (n=1294) · geçen %22.4 / +4.7 / -0.39 | elenen %15.1 / +2.4 / -0.45 (n=3771) · geçen %22.6 / +4.8 / -0.33 |
| yalnız RSI>=80 | elenen %14.8 / +1.5 / -0.46 (n=715) · geçen %25.1 / +5.8 / -0.34 | elenen %12.9 / -0.2 / -0.48 (n=1197) · geçen %19.8 / +3.8 / -0.33 | elenen %18.2 / +3.6 / -0.36 (n=1090) · geçen %22.4 / +5.2 / -0.37 | elenen %15.3 / +1.6 / -0.43 (n=3002) · geçen %22.1 / +4.8 / -0.35 |
| MFI>=95 | elenen %12.1 / +0.7 / -0.57 (n=678) · geçen %25.6 / +5.9 / -0.31 | elenen %11.8 / +0.5 / -0.58 (n=1017) · geçen %19.8 / +3.5 / -0.31 | elenen %18.7 / +5.9 / -0.34 (n=834) · geçen %22.0 / +4.7 / -0.37 | elenen %14.2 / +2.3 / -0.50 (n=2529) · geçen %22.0 / +4.5 / -0.33 |
| RSI>=85 | elenen %13.0 / -0.3 / -0.63 (n=455) · geçen %24.5 / +5.7 / -0.32 | elenen %12.2 / -0.8 / -0.55 (n=731) · geçen %19.2 / +3.5 / -0.33 | elenen %18.3 / +4.0 / -0.38 (n=662) · geçen %22.0 / +5.0 / -0.37 | elenen %14.6 / +1.0 / -0.51 (n=1848) · geçen %21.6 / +4.6 / -0.34 |
| MFI>=90 VE RSI>=80 | elenen %13.3 / +0.7 / -0.55 (n=528) · geçen %24.7 / +5.7 / -0.33 | elenen %12.1 / -0.5 / -0.56 (n=829) · geçen %19.4 / +3.5 / -0.32 | elenen %19.6 / +5.8 / -0.33 (n=723) · geçen %21.8 / +4.8 / -0.37 | elenen %15.0 / +2.0 / -0.48 (n=2080) · geçen %21.6 / +4.5 / -0.34 |
| MFI>=95 veya RSI>=85 | elenen %12.8 / +0.7 / -0.56 (n=815) · geçen %26.1 / +6.2 / -0.30 | elenen %12.2 / -0.0 / -0.54 (n=1262) · geçen %20.1 / +3.8 / -0.31 | elenen %18.9 / +5.2 / -0.35 (n=1076) · geçen %22.2 / +4.8 / -0.37 | elenen %14.6 / +2.0 / -0.48 (n=3153) · geçen %22.4 / +4.8 / -0.33 |

#### H. Skor cezası (x0.85) aşırı alım adaylarını top-10'dan çıkarıyor mu? (trend_devam, kalkan kapalı, tick bazında)
rank<=10 aşırı alım trend_devam satırı: 8244; ceza sonrası hâlâ top-10'da: 8222 (%99.7).