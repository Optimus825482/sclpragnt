# MA kesişimi kombinasyon araması — 90 gün (2026-10-21 15:02)

Evren: canlı sistem mantığı (ilk 50 yükselen + saatlik aktivite; 310 TRY çifti; saatlik ortalama taranan 11.7). Eğitim: ilk 60 gün, test: son 30 gün. Maliyet (gidiş-dönüş): 0.275%. Giriş: kapanışın %1 altına limit, 15 dk içinde dolmazsa yok. Sembol başına tek pozisyon (tutma süresi dolmadan ikinci sinyal atlanır).

Denenen: 72 giriş seti (TF × MA üçlüsü × kural; toplam 149815 ham sinyal) × 108 çıkış kombinasyonu × 137 filtre maskesi = 531072 geçerli deneme (n eğitim ≥ 60, n test ≥ 25); 51605 tanesi eğitimde artı.

## Hem eğitimde hem testte artı olanlar (min(eğitim, test) ortalamasına göre)

| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| M15 | 9/21/55 | ribbon | 5 | 3 | 60 | yok | RSI<70 + gövde≥1% | 77 | +0.61% | 47% | 41 | +0.78% | 54% |
| H1 | 5/13/50 | ribbon | 5 | 3 | 240 | yok | ADX>25 + saat 09–23 | 64 | +0.59% | 50% | 41 | +0.71% | 54% |
| M15 | 9/21/55 | ribbon | 5 | 4 | 60 | yok | RSI<70 + gövde≥1% | 77 | +0.59% | 48% | 41 | +0.81% | 54% |
| M30 | 5/13/50 | ribbon | 5 | 3 | 240 | yok | StochRSI≤50 + gövde≥1% | 74 | +0.75% | 51% | 34 | +0.57% | 47% |
| H1 | 5/13/50 | ribbon | 5 | 3 | 120 | yok | ADX>25 + saat 09–23 | 64 | +0.58% | 50% | 41 | +0.57% | 51% |
| H1 | 5/13/50 | fast_mid | 5 | 3 | 240 | yok | ADX>25 + saat 09–23 | 65 | +0.66% | 51% | 43 | +0.56% | 51% |
| M15 | 9/21/55 | ribbon | 5 | 3 | 60 | yok | gövde≥1% + ATR14≥0.6% | 105 | +0.54% | 48% | 55 | +0.61% | 53% |
| M15 | 9/21/55 | ribbon | 5 | 3 | 60 | yok | gövde≥1% + MACD hist artıyor | 105 | +0.53% | 47% | 55 | +0.59% | 51% |
| M15 | 9/21/55 | ribbon | 5 | 3 | 60 | yok | gövde≥1% | 106 | +0.53% | 47% | 56 | +0.60% | 52% |
| M15 | 9/21/55 | ribbon | 5 | 3 | 60 | yok | gövde≥0.3% + gövde≥1% | 106 | +0.53% | 47% | 56 | +0.60% | 52% |
| M30 | 5/13/50 | ribbon | 5 | 3 | 120 | yok | StochRSI≤50 + gövde≥1% | 76 | +0.77% | 51% | 34 | +0.52% | 47% |
| M15 | 9/21/55 | fast_mid | 5 | 3 | 120 | yok | RSI 45–65 + gövde≥1% | 85 | +0.60% | 51% | 45 | +0.51% | 53% |
| M15 | 3/8/21 | mid_slow | 5 | 3 | 240 | 2/1 | ADX>25 + gövde≥1% | 70 | +0.51% | 69% | 43 | +0.59% | 70% |
| M30 | 5/13/50 | ribbon | 5 | 3 | 120 | yok | StochRSI≤50 + gövde≥0.3% | 91 | +0.51% | 48% | 45 | +0.49% | 51% |
| M15 | 9/21/55 | ribbon | 5 | 3 | 60 | yok | gövde≥1% + yavaş MA yükseliyor | 101 | +0.48% | 48% | 55 | +0.52% | 51% |
| M15 | 9/21/55 | ribbon | 5 | 4 | 60 | yok | gövde≥1% + ATR14≥0.6% | 105 | +0.48% | 49% | 55 | +0.59% | 53% |
| M30 | 5/13/50 | ribbon | 5 | 3 | 120 | 2/1 | StochRSI≤50 + gövde≥1% | 76 | +0.48% | 64% | 34 | +0.51% | 62% |
| M15 | 3/8/21 | mid_slow | 5 | 3 | 120 | 2/1 | ADX>25 + gövde≥1% | 72 | +0.47% | 67% | 43 | +0.52% | 67% |
| M15 | 9/21/55 | ribbon | 5 | 4 | 60 | yok | gövde≥1% | 106 | +0.47% | 48% | 56 | +0.57% | 52% |
| M15 | 9/21/55 | ribbon | 5 | 4 | 60 | yok | gövde≥0.3% + gövde≥1% | 106 | +0.47% | 48% | 56 | +0.57% | 52% |
| H1 | 3/8/21 | ribbon | 5 | 2 | 240 | 1.5/0.75 | hacim≥2× | 60 | +0.47% | 68% | 31 | +0.53% | 68% |
| H1 | 3/8/21 | ribbon | 5 | 2 | 240 | 1.5/0.75 | hacim≥1.5× + hacim≥2× | 60 | +0.47% | 68% | 31 | +0.53% | 68% |
| H1 | 3/8/21 | ribbon | 5 | 2 | 240 | 1.5/0.75 | hacim≥2× + yavaş MA yükseliyor | 60 | +0.47% | 68% | 31 | +0.53% | 68% |
| H1 | 3/8/21 | ribbon | 5 | 2 | 240 | 1.5/0.75 | hacim≥2× + ATR14≥0.6% | 60 | +0.47% | 68% | 31 | +0.53% | 68% |
| M15 | 9/21/55 | ribbon | 5 | 4 | 60 | yok | gövde≥1% + MACD hist artıyor | 105 | +0.47% | 48% | 55 | +0.57% | 51% |

## Eğitimde en iyi 25 (test sütunu: seçim sonrası tek bakış)

| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| M30 | 7/20/99 | fast_mid | 5 | 4 | 240 | yok | RSI<70 + hacim≥2× | 61 | +1.08% | 59% | 37 | -1.08% | 30% |
| M5 | 3/8/21 | ribbon | 5 | 4 | 240 | yok | gövde≥1% + yavaşa uzaklık≤2% | 66 | +1.04% | 56% | 45 | +0.22% | 53% |
| M15 | 3/8/21 | mid_slow | 5 | 2 | 240 | yok | ADX>25 + hacim≥2× | 62 | +0.95% | 47% | 35 | -0.38% | 29% |
| M30 | 7/20/99 | fast_mid | 5 | 4 | 120 | yok | RSI<70 + hacim≥2× | 61 | +0.92% | 59% | 37 | -1.28% | 27% |
| M15 | 3/8/21 | mid_slow | 5 | 2 | 240 | yok | ADX>25 + gövde≥1% | 70 | +0.92% | 47% | 43 | -0.47% | 28% |
| M15 | 3/8/21 | mid_slow | 5 | 2 | 120 | yok | ADX>25 + gövde≥1% | 72 | +0.91% | 47% | 43 | -0.36% | 33% |
| M15 | 3/8/21 | mid_slow | 5 | 2 | 120 | yok | ADX>25 + hacim≥2× | 63 | +0.91% | 49% | 35 | -0.32% | 29% |
| M15 | 9/21/55 | fast_mid | 5 | 3 | 60 | yok | RSI 45–65 + gövde≥1% | 88 | +0.89% | 56% | 46 | +0.17% | 52% |
| M15 | 9/21/55 | fast_mid | 5 | 4 | 60 | yok | RSI 45–65 + gövde≥1% | 88 | +0.86% | 56% | 46 | +0.13% | 52% |
| M15 | 3/8/21 | mid_slow | 5 | 2 | 120 | yok | StochRSI≤80 + gövde≥1% | 65 | +0.86% | 48% | 49 | -0.50% | 31% |
| M15 | 3/8/21 | mid_slow | 5 | 2 | 60 | yok | ADX>25 + gövde≥1% | 73 | +0.84% | 47% | 44 | -0.44% | 32% |
| M5 | 7/20/99 | ribbon | 5 | 2 | 240 | yok | yavaşa uzaklık≤2% + ATR14≥0.6% | 62 | +0.84% | 45% | 34 | -0.44% | 26% |
| M15 | 3/8/21 | mid_slow | 5 | 4 | 240 | yok | ADX>25 + hacim≥2× | 62 | +0.84% | 55% | 35 | -0.60% | 37% |
| M15 | 3/8/21 | mid_slow | 5 | 3 | 120 | yok | ADX>25 + hacim≥2× | 63 | +0.84% | 54% | 35 | -0.27% | 37% |
| M15 | 3/8/21 | mid_slow | 5 | 3 | 240 | yok | ADX>25 + hacim≥2× | 62 | +0.83% | 52% | 35 | -0.15% | 37% |
| M15 | 3/8/21 | mid_slow | 5 | 3 | 120 | yok | ADX>25 + gövde≥1% | 72 | +0.83% | 53% | 43 | -0.29% | 40% |
| H1 | 3/8/21 | ribbon | 5 | 3 | 240 | yok | StochRSI≤50 + saat 09–23 | 79 | +0.83% | 56% | 40 | -0.44% | 35% |
| M30 | 9/21/55 | mid_slow | 5 | 4 | 240 | yok | yavaş MA yükseliyor + saat 09–23 | 66 | +0.82% | 56% | 28 | -0.49% | 46% |
| M15 | 3/8/21 | mid_slow | 5 | 3 | 240 | yok | ADX>20 + gövde≥1% | 96 | +0.82% | 52% | 60 | -0.24% | 37% |
| M15 | 3/8/21 | mid_slow | 5 | 4 | 120 | yok | ADX>25 + gövde≥1% | 72 | +0.81% | 56% | 43 | -0.42% | 42% |
| M15 | 3/8/21 | mid_slow | 5 | 4 | 120 | yok | ADX>25 + hacim≥2× | 63 | +0.81% | 56% | 35 | -0.58% | 37% |
| M30 | 5/13/50 | fast_mid | 5 | 4 | 120 | yok | StochRSI≤50 + gövde≥1% | 78 | +0.80% | 55% | 37 | +0.24% | 46% |
| M15 | 3/8/21 | mid_slow | 5 | 2 | 240 | yok | ADX>20 + gövde≥1% | 96 | +0.80% | 45% | 60 | -0.28% | 30% |
| M30 | 3/8/21 | ribbon | 5 | 4 | 240 | yok | RSI<70 + hacim≥1.5× | 69 | +0.79% | 55% | 59 | -0.52% | 44% |
| M15 | 3/8/21 | mid_slow | 5 | 4 | 240 | 1.5/0.75 | ADX>25 + hacim≥2× | 62 | +0.79% | 81% | 35 | +0.19% | 69% |

## Hedef %2 ve tutma ≤ 60 dk ile en iyi 15 (eğitime göre)

| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| M15 | 7/20/99 | fast_mid | 2 | 2 | 60 | 1.5/0.75 | ADX>25 + gövde≥1% | 77 | +0.34% | 69% | 56 | -0.51% | 46% |
| M15 | 7/20/99 | fast_mid | 2 | 2 | 60 | 1.5/0.75 | ADX>25 + hacim≥1.5× | 76 | +0.32% | 70% | 53 | -0.73% | 38% |
| M15 | 3/8/21 | ribbon | 2 | 4 | 60 | yok | RSI 45–65 + gövde≥1% | 128 | +0.31% | 65% | 62 | +0.07% | 58% |
| M15 | 3/8/21 | ribbon | 2 | 4 | 60 | 2/1 | RSI 45–65 + gövde≥1% | 128 | +0.31% | 65% | 62 | +0.07% | 58% |
| M15 | 3/8/21 | ribbon | 2 | 4 | 60 | 1/0.5 | RSI 45–65 + gövde≥1% | 128 | +0.30% | 79% | 62 | +0.14% | 76% |
| M15 | 9/21/55 | fast_mid | 2 | 3 | 60 | yok | RSI 45–65 + gövde≥1% | 88 | +0.30% | 65% | 46 | +0.01% | 61% |
| M15 | 9/21/55 | fast_mid | 2 | 3 | 60 | 2/1 | RSI 45–65 + gövde≥1% | 88 | +0.30% | 65% | 46 | +0.01% | 61% |
| M30 | 10/30/100 | mid_slow | 2 | 2 | 60 | 1.5/0.75 | MACD hist artıyor | 60 | +0.29% | 72% | 27 | -0.52% | 44% |
| M30 | 10/30/100 | mid_slow | 2 | 2 | 60 | 1.5/0.75 | MACD hist artıyor + ATR14≥0.6% | 60 | +0.29% | 72% | 27 | -0.52% | 44% |
| M15 | 9/21/55 | fast_mid | 2 | 3 | 60 | 1/0.5 | RSI 45–65 + gövde≥1% | 88 | +0.29% | 80% | 46 | +0.03% | 72% |
| M15 | 9/21/55 | fast_mid | 2 | 4 | 60 | 1/0.5 | RSI 45–65 + gövde≥1% | 88 | +0.28% | 80% | 46 | +0.02% | 74% |
| M15 | 9/21/55 | fast_mid | 2 | 2 | 60 | 1/0.5 | RSI 45–65 + gövde≥1% | 88 | +0.28% | 76% | 46 | +0.01% | 67% |
| M15 | 3/8/21 | ribbon | 2 | 4 | 60 | 1.5/0.75 | RSI 45–65 + gövde≥1% | 128 | +0.27% | 69% | 62 | +0.14% | 66% |
| M15 | 3/8/21 | mid_slow | 2 | 2 | 60 | yok | ADX>25 + gövde≥1% | 73 | +0.27% | 60% | 44 | -0.34% | 45% |
| M15 | 3/8/21 | mid_slow | 2 | 2 | 60 | 2/1 | ADX>25 + gövde≥1% | 73 | +0.27% | 60% | 44 | -0.34% | 45% |

## Okuma

- 531072 denemenin eğitim ortalaması medyanı -0.23%, en iyi +1.08%; eğitimde en iyi 100'ün test ortalaması medyanı -0.37% ve 20 tanesi testte artı.
- Eğitimde en iyi görünen kombinasyonun testte de artı kalması gerekir; aksi hâlde sonuç çoklu deneme (seçim) gürültüsüdür. 1065312 denemeden şans eseri de artı çıkanlar olur.
- İz süren stop bir önceki mumun tepesinden; aynı mumda stop ve hedef görülürse stop. 1 dk mumlarda boşluk varsa pencere zaman değil mum sayar.
