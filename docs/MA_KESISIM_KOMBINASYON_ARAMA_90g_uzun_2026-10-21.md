# MA kesişimi kombinasyon araması — 90 gün (2026-10-21 15:06)

Evren: canlı sistem mantığı (ilk 50 yükselen + saatlik aktivite; 310 TRY çifti; saatlik ortalama taranan 11.7). Eğitim: ilk 60 gün, test: son 30 gün. Maliyet (gidiş-dönüş): 0.275%. Giriş: sinyal mumu kapanışı (piyasa). Sembol başına tek pozisyon (tutma süresi dolmadan ikinci sinyal atlanır).

Denenen: 72 giriş seti (TF × MA üçlüsü × kural; toplam 149815 ham sinyal) × 192 çıkış kombinasyonu × 137 filtre maskesi = 1493856 geçerli deneme (n eğitim ≥ 60, n test ≥ 25); 152309 tanesi eğitimde artı.

## Hem eğitimde hem testte artı olanlar (min(eğitim, test) ortalamasına göre)

| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| M5 | 7/20/99 | mid_slow | 8 | 4 | 480 | yok | gövde≥0.3% + yavaşa uzaklık≤1% | 60 | +0.84% | 48% | 25 | +0.86% | 48% |
| M5 | 7/20/99 | mid_slow | 8 | 6 | 480 | yok | gövde≥0.3% + yavaşa uzaklık≤1% | 60 | +0.75% | 50% | 25 | +1.16% | 52% |
| M5 | 9/21/55 | mid_slow | 8 | 6 | 480 | yok | RSI<70 + gövde≥1% | 75 | +0.70% | 49% | 39 | +1.78% | 54% |
| M30 | 9/21/55 | mid_slow | 3 | 6 | 480 | yok | gövde≥1% + saat 09–23 | 69 | +0.80% | 74% | 37 | +0.63% | 76% |
| M15 | 3/8/21 | ribbon | 8 | 6 | 480 | 1.5/0.75 | gövde≥1% + yavaşa uzaklık≤2% | 93 | +0.69% | 80% | 39 | +0.62% | 85% |
| M5 | 9/21/55 | mid_slow | 8 | 4 | 480 | yok | RSI<70 + gövde≥1% | 75 | +0.62% | 41% | 39 | +0.69% | 41% |
| M5 | 10/30/100 | ribbon | 8 | 6 | 480 | yok | StochRSI≤50 + RSI 45–65 | 137 | +0.68% | 47% | 56 | +0.61% | 50% |
| M15 | 3/8/21 | ribbon | 8 | 4 | 480 | 1.5/0.75 | gövde≥1% + yavaşa uzaklık≤2% | 93 | +0.65% | 78% | 39 | +0.60% | 85% |
| M15 | 3/8/21 | ribbon | 5 | 6 | 480 | 1.5/0.75 | gövde≥1% + yavaşa uzaklık≤2% | 93 | +0.67% | 80% | 39 | +0.60% | 85% |
| M15 | 7/20/99 | mid_slow | 8 | 6 | 480 | 1/0.5 | ADX>25 + hacim≥2× | 74 | +0.59% | 86% | 32 | +0.68% | 84% |
| M5 | 7/20/99 | mid_slow | 5 | 4 | 480 | yok | gövde≥0.3% + yavaşa uzaklık≤1% | 60 | +0.59% | 55% | 25 | +0.80% | 52% |
| M15 | 3/8/21 | ribbon | 5 | 4 | 480 | 1.5/0.75 | gövde≥1% + yavaşa uzaklık≤2% | 93 | +0.62% | 78% | 39 | +0.58% | 85% |
| M5 | 10/30/100 | ribbon | 8 | 6 | 480 | yok | StochRSI≤50 + saat 09–23 | 119 | +0.75% | 48% | 41 | +0.57% | 51% |
| M30 | 8/34/89 | mid_slow | 8 | 6 | 480 | yok | RSI 45–65 + yavaş MA yükseliyor | 80 | +0.56% | 45% | 41 | +1.08% | 63% |
| M15 | 7/20/99 | mid_slow | 5 | 6 | 480 | 1/0.5 | ADX>25 + hacim≥2× | 74 | +0.56% | 86% | 32 | +0.58% | 84% |
| M30 | 5/13/50 | mid_slow | 8 | 6 | 240 | yok | ADX>20 + gövde≥0.3% | 79 | +0.56% | 51% | 48 | +0.55% | 44% |
| M30 | 9/21/55 | mid_slow | 8 | 3 | 240 | yok | ADX>20 + gövde≥1% | 79 | +0.55% | 42% | 33 | +0.60% | 42% |
| M30 | 8/34/89 | mid_slow | 8 | 3 | 480 | yok | RSI 45–65 + yavaş MA yükseliyor | 80 | +0.55% | 40% | 41 | +1.10% | 56% |
| M5 | 7/20/99 | mid_slow | 8 | 2 | 480 | yok | gövde≥0.3% + yavaşa uzaklık≤1% | 60 | +0.55% | 33% | 25 | +0.85% | 40% |
| M5 | 10/30/100 | ribbon | 8 | 4 | 480 | yok | StochRSI≤50 + yavaş MA yükseliyor | 139 | +0.54% | 44% | 56 | +0.61% | 48% |
| M30 | 10/30/100 | mid_slow | 8 | 6 | 480 | 1.5/0.75 | StochRSI≤80 + hacim≥1.5× | 66 | +0.54% | 77% | 36 | +0.80% | 86% |
| H1 | 10/30/100 | fast_mid | 8 | 3 | 480 | yok | ADX>20 + yavaşa uzaklık≤2% | 62 | +0.54% | 45% | 32 | +0.55% | 41% |
| M15 | 10/30/100 | mid_slow | 8 | 6 | 480 | 1/0.5 | RSI 45–65 + ADX>20 | 85 | +0.53% | 81% | 45 | +0.54% | 84% |
| M30 | 8/34/89 | mid_slow | 8 | 3 | 240 | yok | RSI 45–65 + yavaş MA yükseliyor | 80 | +0.53% | 44% | 41 | +0.62% | 56% |
| M15 | 10/30/100 | mid_slow | 8 | 6 | 480 | 1/0.5 | RSI 45–65 + ADX>25 | 75 | +0.52% | 80% | 39 | +0.60% | 85% |

## Eğitimde en iyi 25 (test sütunu: seçim sonrası tek bakış)

| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| M5 | 8/34/89 | ribbon | 8 | 6 | 480 | yok | RSI 45–65 + gövde≥1% | 61 | +1.21% | 51% | 41 | +0.40% | 46% |
| M15 | 10/30/100 | mid_slow | 8 | 4 | 480 | yok | ADX>25 + hacim≥2× | 82 | +1.21% | 48% | 53 | -0.15% | 40% |
| M15 | 10/30/100 | mid_slow | 8 | 4 | 480 | yok | gövde≥0.3% + hacim≥1.5× | 62 | +1.21% | 50% | 41 | -1.40% | 29% |
| M5 | 10/30/100 | ribbon | 8 | 6 | 480 | yok | yavaşa uzaklık≤1% + saat 09–23 | 169 | +1.19% | 53% | 87 | -1.25% | 28% |
| M15 | 10/30/100 | mid_slow | 8 | 6 | 480 | yok | ADX>25 + hacim≥2× | 82 | +1.19% | 52% | 53 | -0.21% | 42% |
| H1 | 5/13/50 | fast_mid | 8 | 6 | 480 | yok | RSI 45–65 + hacim≥1.5× | 106 | +1.17% | 49% | 53 | -0.65% | 40% |
| M30 | 3/8/21 | ribbon | 8 | 3 | 240 | yok | hacim≥1.5× + yavaşa uzaklık≤2% | 84 | +1.17% | 52% | 60 | -0.52% | 30% |
| M5 | 10/30/100 | ribbon | 5 | 4 | 120 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +1.14% | 59% | 36 | -0.63% | 31% |
| H1 | 5/13/50 | fast_mid | 8 | 4 | 480 | yok | RSI 45–65 + hacim≥1.5× | 106 | +1.14% | 46% | 53 | -0.31% | 40% |
| M30 | 3/8/21 | ribbon | 8 | 4 | 240 | yok | hacim≥1.5× + yavaşa uzaklık≤2% | 84 | +1.12% | 52% | 60 | -0.48% | 32% |
| M15 | 9/21/55 | ribbon | 5 | 6 | 480 | yok | StochRSI≤50 + ADX>25 | 74 | +1.12% | 55% | 48 | -1.26% | 40% |
| M30 | 5/13/50 | mid_slow | 8 | 6 | 480 | yok | hacim≥1.5× + saat 09–23 | 110 | +1.11% | 54% | 74 | +0.23% | 46% |
| M30 | 3/8/21 | ribbon | 8 | 6 | 240 | yok | hacim≥1.5× + yavaşa uzaklık≤2% | 84 | +1.09% | 52% | 60 | -0.48% | 33% |
| M5 | 10/30/100 | ribbon | 5 | 6 | 120 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +1.09% | 59% | 36 | -0.52% | 31% |
| M5 | 10/30/100 | ribbon | 8 | 4 | 120 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +1.09% | 70% | 36 | -0.63% | 39% |
| M30 | 5/13/50 | mid_slow | 8 | 4 | 480 | yok | hacim≥1.5× + saat 09–23 | 110 | +1.07% | 51% | 74 | +0.07% | 41% |
| M5 | 10/30/100 | ribbon | 8 | 4 | 120 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +1.07% | 56% | 36 | -0.75% | 31% |
| M30 | 3/8/21 | ribbon | 8 | 2 | 240 | yok | hacim≥1.5× + yavaşa uzaklık≤2% | 84 | +1.05% | 50% | 60 | -0.54% | 25% |
| M30 | 5/13/50 | mid_slow | 8 | 6 | 480 | yok | RSI<70 + hacim≥1.5× | 90 | +1.05% | 52% | 51 | -0.07% | 39% |
| M5 | 10/30/100 | ribbon | 8 | 4 | 480 | yok | yavaşa uzaklık≤1% + saat 09–23 | 169 | +1.04% | 52% | 87 | -1.24% | 26% |
| H1 | 5/13/50 | fast_mid | 8 | 3 | 480 | yok | RSI 45–65 + hacim≥1.5× | 106 | +1.03% | 42% | 53 | -0.65% | 34% |
| M5 | 10/30/100 | ribbon | 8 | 6 | 120 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +1.03% | 70% | 36 | -0.53% | 39% |
| M15 | 10/30/100 | mid_slow | 8 | 6 | 480 | yok | gövde≥0.3% + hacim≥1.5× | 62 | +1.02% | 53% | 41 | -1.59% | 32% |
| M5 | 10/30/100 | ribbon | 8 | 6 | 120 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +1.02% | 56% | 36 | -0.64% | 31% |
| M30 | 5/13/50 | mid_slow | 8 | 4 | 480 | yok | hacim≥1.5× + yavaş MA yükseliyor | 126 | +1.02% | 49% | 76 | -0.38% | 36% |

## Hedef %2 ve tutma ≤ 60 dk ile en iyi 15 (eğitime göre)

| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| — | yok | | | | | | | | | | | | |

## Okuma

- 1493856 denemenin eğitim ortalaması medyanı -0.21%, en iyi +1.21%; eğitimde en iyi 100'ün test ortalaması medyanı -0.52% ve 9 tanesi testte artı.
- Eğitimde en iyi görünen kombinasyonun testte de artı kalması gerekir; aksi hâlde sonuç çoklu deneme (seçim) gürültüsüdür. 1893888 denemeden şans eseri de artı çıkanlar olur.
- İz süren stop bir önceki mumun tepesinden; aynı mumda stop ve hedef görülürse stop. 1 dk mumlarda boşluk varsa pencere zaman değil mum sayar.
