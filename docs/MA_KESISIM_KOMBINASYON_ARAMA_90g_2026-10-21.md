# MA kesişimi kombinasyon araması — 90 gün (2026-10-21 14:33)

Evren: canlı sistem mantığı (ilk 50 yükselen + saatlik aktivite; 310 TRY çifti; saatlik ortalama taranan 11.7). Eğitim: ilk 60 gün, test: son 30 gün. Maliyet (gidiş-dönüş): 0.275%. Sembol başına tek pozisyon (tutma süresi dolmadan ikinci sinyal atlanır).

Denenen: 72 giriş seti (TF × MA üçlüsü × kural; toplam 149815 ham sinyal) × 360 çıkış kombinasyonu × 137 filtre maskesi = 2807220 geçerli deneme (n eğitim ≥ 60, n test ≥ 25); 77235 tanesi eğitimde artı.

## Hem eğitimde hem testte artı olanlar (min(eğitim, test) ortalamasına göre)

| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| H1 | 3/8/21 | mid_slow | 3 | 4 | 90 | yok | StochRSI≤80 + MACD hist artıyor | 73 | +0.42% | 55% | 42 | +0.67% | 60% |
| H1 | 3/8/21 | mid_slow | 3 | 4 | 120 | yok | StochRSI≤80 + MACD hist artıyor | 73 | +0.34% | 56% | 42 | +0.46% | 57% |
| H1 | 7/20/99 | fast_mid | 3 | 4 | 180 | 1.5/0.75 | RSI<70 + gövde≥1% | 85 | +0.33% | 73% | 36 | +0.39% | 72% |
| H1 | 7/20/99 | mid_slow | 3 | 3 | 240 | 1/0.5 | RSI 45–65 + ADX>25 | 81 | +0.33% | 74% | 39 | +0.35% | 85% |
| H1 | 3/8/21 | mid_slow | 3 | 4 | 90 | 2/1 | StochRSI≤80 + MACD hist artıyor | 73 | +0.32% | 56% | 42 | +0.43% | 64% |
| H1 | 7/20/99 | mid_slow | 2.5 | 3 | 240 | 1/0.5 | RSI 45–65 + ADX>25 | 81 | +0.32% | 74% | 39 | +0.34% | 85% |
| H1 | 3/8/21 | mid_slow | 2.5 | 4 | 90 | yok | StochRSI≤80 + MACD hist artıyor | 73 | +0.32% | 56% | 42 | +0.54% | 62% |
| M15 | 10/30/100 | mid_slow | 3 | 3 | 180 | 1.5/0.75 | RSI 45–65 + ADX>20 | 86 | +0.31% | 60% | 45 | +0.34% | 67% |
| H1 | 7/20/99 | mid_slow | 3 | 3 | 180 | 1/0.5 | RSI 45–65 + ADX>25 | 81 | +0.42% | 74% | 39 | +0.30% | 82% |
| H1 | 7/20/99 | mid_slow | 2.5 | 3 | 180 | 1/0.5 | RSI 45–65 + ADX>25 | 81 | +0.42% | 74% | 39 | +0.29% | 82% |
| H1 | 7/20/99 | mid_slow | 2 | 3 | 240 | 1/0.5 | RSI 45–65 + ADX>25 | 81 | +0.29% | 74% | 39 | +0.32% | 85% |
| H1 | 7/20/99 | fast_mid | 2.5 | 4 | 180 | 1.5/0.75 | RSI<70 + gövde≥1% | 85 | +0.28% | 73% | 36 | +0.29% | 72% |
| H1 | 7/20/99 | mid_slow | 3 | 4 | 240 | 1/0.5 | RSI 45–65 + ADX>25 | 81 | +0.36% | 75% | 39 | +0.28% | 85% |
| M15 | 10/30/100 | mid_slow | 3 | 3 | 180 | 1.5/0.75 | RSI 45–65 + ADX>25 | 75 | +0.28% | 60% | 39 | +0.34% | 67% |
| H1 | 7/20/99 | mid_slow | 3 | 4 | 180 | 1/0.5 | RSI 45–65 + ADX>25 | 81 | +0.47% | 75% | 39 | +0.28% | 82% |
| M15 | 10/30/100 | mid_slow | 3 | 4 | 180 | 1.5/0.75 | RSI 45–65 + ADX>20 | 86 | +0.30% | 62% | 45 | +0.27% | 67% |
| H1 | 7/20/99 | ribbon | 3 | 3 | 180 | 1.5/0.75 | ADX>25 + gövde≥0.3% | 64 | +0.27% | 66% | 32 | +0.38% | 75% |
| H1 | 7/20/99 | ribbon | 3 | 3 | 120 | 1.5/0.75 | ADX>25 + gövde≥0.3% | 64 | +0.27% | 66% | 32 | +0.35% | 69% |
| H1 | 7/20/99 | mid_slow | 2 | 3 | 180 | 1/0.5 | RSI 45–65 + ADX>25 | 81 | +0.39% | 74% | 39 | +0.27% | 82% |
| H1 | 7/20/99 | ribbon | 3 | 1.5 | 120 | 1.5/0.75 | ADX>25 + gövde≥0.3% | 64 | +0.27% | 56% | 32 | +0.42% | 62% |
| H1 | 7/20/99 | mid_slow | 2.5 | 4 | 240 | 1/0.5 | RSI 45–65 + ADX>25 | 81 | +0.35% | 75% | 39 | +0.27% | 85% |
| H1 | 7/20/99 | fast_mid | 3 | 4 | 240 | 1/0.5 | RSI<70 + gövde≥1% | 85 | +0.27% | 81% | 35 | +0.51% | 83% |
| H1 | 7/20/99 | ribbon | 3 | 1.5 | 240 | 1.5/0.75 | ADX>25 + gövde≥0.3% | 63 | +0.27% | 57% | 32 | +0.51% | 69% |
| H1 | 3/8/21 | mid_slow | 2.5 | 4 | 90 | 2/1 | StochRSI≤80 + MACD hist artıyor | 73 | +0.27% | 56% | 42 | +0.39% | 64% |
| H1 | 7/20/99 | mid_slow | 3 | 3 | 120 | 1/0.5 | RSI 45–65 + ADX>25 | 81 | +0.37% | 72% | 39 | +0.26% | 79% |

## Eğitimde en iyi 25 (test sütunu: seçim sonrası tek bakış)

| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| M5 | 10/30/100 | ribbon | 3 | 4 | 120 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +0.91% | 65% | 36 | -0.65% | 33% |
| M5 | 10/30/100 | ribbon | 3 | 4 | 120 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +0.81% | 70% | 36 | -0.59% | 39% |
| M5 | 10/30/100 | ribbon | 2.5 | 4 | 120 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +0.80% | 67% | 36 | -0.74% | 33% |
| M5 | 10/30/100 | ribbon | 3 | 3 | 120 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +0.78% | 62% | 36 | -0.72% | 31% |
| M5 | 10/30/100 | ribbon | 3 | 4 | 90 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 67 | +0.74% | 57% | 37 | -0.83% | 38% |
| M5 | 10/30/100 | ribbon | 2.5 | 4 | 120 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +0.72% | 70% | 36 | -0.63% | 39% |
| M5 | 10/30/100 | ribbon | 3 | 4 | 180 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 60 | +0.71% | 62% | 35 | -0.81% | 37% |
| M5 | 10/30/100 | ribbon | 3 | 3 | 180 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 60 | +0.68% | 60% | 35 | -0.79% | 34% |
| M5 | 10/30/100 | ribbon | 3 | 3 | 120 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +0.67% | 67% | 36 | -0.58% | 36% |
| M5 | 10/30/100 | ribbon | 3 | 4 | 120 | 1.5/0.75 | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +0.67% | 74% | 36 | -0.47% | 50% |
| M5 | 10/30/100 | ribbon | 2.5 | 3 | 120 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +0.67% | 64% | 36 | -0.79% | 31% |
| M5 | 10/30/100 | ribbon | 3 | 4 | 180 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 60 | +0.65% | 68% | 35 | -0.66% | 43% |
| M5 | 10/30/100 | ribbon | 3 | 3 | 90 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 67 | +0.64% | 55% | 37 | -0.81% | 38% |
| M5 | 10/30/100 | ribbon | 2.5 | 4 | 120 | 1.5/0.75 | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +0.59% | 74% | 36 | -0.53% | 50% |
| M5 | 10/30/100 | ribbon | 3 | 3 | 180 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 60 | +0.59% | 67% | 35 | -0.64% | 40% |
| M5 | 10/30/100 | ribbon | 2.5 | 3 | 120 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +0.59% | 67% | 36 | -0.64% | 36% |
| M5 | 10/30/100 | ribbon | 2 | 4 | 120 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +0.59% | 70% | 36 | -0.69% | 39% |
| M5 | 10/30/100 | ribbon | 2 | 4 | 120 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +0.59% | 70% | 36 | -0.69% | 39% |
| M5 | 10/30/100 | ribbon | 3 | 4 | 60 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 68 | +0.58% | 59% | 39 | -0.50% | 36% |
| M30 | 3/8/21 | mid_slow | 3 | 4 | 240 | yok | ADX>25 + hacim≥2× | 99 | +0.57% | 65% | 54 | -0.55% | 46% |
| M5 | 10/30/100 | ribbon | 2.5 | 4 | 180 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 60 | +0.57% | 65% | 35 | -0.89% | 37% |
| M5 | 10/30/100 | ribbon | 3 | 3 | 120 | 1.5/0.75 | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +0.56% | 71% | 36 | -0.46% | 47% |
| M5 | 10/30/100 | ribbon | 2.5 | 4 | 180 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 60 | +0.56% | 68% | 35 | -0.70% | 43% |
| M5 | 10/30/100 | ribbon | 3 | 4 | 90 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 67 | +0.54% | 58% | 37 | -0.67% | 41% |
| M5 | 10/30/100 | ribbon | 2.5 | 4 | 90 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 67 | +0.54% | 58% | 37 | -0.78% | 38% |

## Hedef %2 ve tutma ≤ 60 dk ile en iyi 15 (eğitime göre)

| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| M30 | 5/13/50 | mid_slow | 2 | 4 | 60 | 1/0.5 | gövde≥0.3% + hacim≥1.5× | 71 | +0.28% | 83% | 51 | -0.33% | 67% |
| M5 | 10/30/100 | ribbon | 2 | 4 | 60 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 68 | +0.26% | 59% | 39 | -0.55% | 38% |
| M5 | 10/30/100 | ribbon | 2 | 4 | 60 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 68 | +0.26% | 59% | 39 | -0.55% | 38% |
| H1 | 7/20/99 | mid_slow | 2 | 4 | 60 | 1.5/0.75 | RSI 45–65 + ADX>25 | 81 | +0.25% | 59% | 39 | -0.02% | 56% |
| M30 | 5/13/50 | mid_slow | 2 | 4 | 30 | 1/0.5 | gövde≥0.3% + hacim≥1.5× | 71 | +0.24% | 79% | 51 | -0.41% | 63% |
| H1 | 9/21/55 | fast_mid | 2 | 4 | 60 | 1/0.5 | StochRSI≤80 + RSI<70 | 77 | +0.24% | 62% | 45 | -0.24% | 58% |
| H1 | 3/8/21 | fast_mid | 2 | 4 | 30 | yok | StochRSI≤50 + hacim≥2× | 67 | +0.23% | 57% | 36 | -0.16% | 42% |
| H1 | 3/8/21 | fast_mid | 2 | 4 | 30 | 2/1 | StochRSI≤50 + hacim≥2× | 67 | +0.23% | 57% | 36 | -0.16% | 42% |
| H1 | 7/20/99 | mid_slow | 2 | 2 | 60 | 1.5/0.75 | RSI 45–65 + ADX>25 | 81 | +0.23% | 58% | 39 | -0.19% | 49% |
| M30 | 5/13/50 | mid_slow | 2 | 4 | 60 | 1/0.5 | hacim≥1.5× + MACD hist artıyor | 109 | +0.23% | 77% | 71 | -0.16% | 68% |
| M5 | 10/30/100 | ribbon | 2 | 3 | 60 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 68 | +0.22% | 57% | 39 | -0.52% | 38% |
| M5 | 10/30/100 | ribbon | 2 | 3 | 60 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 68 | +0.22% | 57% | 39 | -0.52% | 38% |
| H1 | 7/20/99 | mid_slow | 2 | 4 | 60 | 1/0.5 | RSI 45–65 + ADX>25 | 81 | +0.22% | 60% | 39 | +0.01% | 72% |
| H1 | 9/21/55 | fast_mid | 2 | 4 | 60 | 1/0.5 | StochRSI≤80 | 90 | +0.21% | 64% | 55 | -0.11% | 64% |
| H1 | 9/21/55 | fast_mid | 2 | 4 | 60 | 1/0.5 | StochRSI≤80 + ATR14≥0.6% | 90 | +0.21% | 64% | 55 | -0.11% | 64% |

## Okuma

- 2807220 denemenin eğitim ortalaması medyanı -0.27%, en iyi +0.91%; eğitimde en iyi 100'ün test ortalaması medyanı -0.46% ve 17 tanesi testte artı.
- Eğitimde en iyi görünen kombinasyonun testte de artı kalması gerekir; aksi hâlde sonuç çoklu deneme (seçim) gürültüsüdür. 3551040 denemeden şans eseri de artı çıkanlar olur.
- İz süren stop bir önceki mumun tepesinden; aynı mumda stop ve hedef görülürse stop. 1 dk mumlarda boşluk varsa pencere zaman değil mum sayar.
