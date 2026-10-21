# MA kesişimi kombinasyon araması — 90 gün (2026-10-21 14:45)

Evren: canlı sistem mantığı (ilk 50 yükselen + saatlik aktivite; 310 TRY çifti; saatlik ortalama taranan 11.7). Eğitim: ilk 60 gün, test: son 30 gün. Maliyet (gidiş-dönüş): 0.275%. Sembol başına tek pozisyon (tutma süresi dolmadan ikinci sinyal atlanır).

Denenen: 72 giriş seti (TF × MA üçlüsü × kural; toplam 149815 ham sinyal) × 240 çıkış kombinasyonu × 137 filtre maskesi = 1871480 geçerli deneme (n eğitim ≥ 60, n test ≥ 25); 108147 tanesi eğitimde artı.

## Hem eğitimde hem testte artı olanlar (min(eğitim, test) ortalamasına göre)

| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| M15 | 8/34/89 | mid_slow | 5 | 1.5 | 90 | yok | gövde≥1% | 66 | +0.62% | 41% | 42 | +0.67% | 45% |
| M15 | 8/34/89 | mid_slow | 5 | 1.5 | 90 | yok | gövde≥0.3% + gövde≥1% | 66 | +0.62% | 41% | 42 | +0.67% | 45% |
| M15 | 8/34/89 | mid_slow | 5 | 1.5 | 90 | yok | gövde≥1% + ATR14≥0.6% | 66 | +0.62% | 41% | 42 | +0.67% | 45% |
| M15 | 8/34/89 | mid_slow | 5 | 2 | 90 | yok | gövde≥1% | 66 | +0.60% | 44% | 42 | +0.68% | 50% |
| M15 | 8/34/89 | mid_slow | 5 | 2 | 90 | yok | gövde≥0.3% + gövde≥1% | 66 | +0.60% | 44% | 42 | +0.68% | 50% |
| M15 | 8/34/89 | mid_slow | 5 | 2 | 90 | yok | gövde≥1% + ATR14≥0.6% | 66 | +0.60% | 44% | 42 | +0.68% | 50% |
| M15 | 8/34/89 | mid_slow | 5 | 3 | 90 | yok | gövde≥1% | 66 | +0.66% | 50% | 42 | +0.60% | 52% |
| M15 | 8/34/89 | mid_slow | 5 | 3 | 90 | yok | gövde≥0.3% + gövde≥1% | 66 | +0.66% | 50% | 42 | +0.60% | 52% |
| M15 | 8/34/89 | mid_slow | 5 | 3 | 90 | yok | gövde≥1% + ATR14≥0.6% | 66 | +0.66% | 50% | 42 | +0.60% | 52% |
| M15 | 8/34/89 | mid_slow | 5 | 3 | 90 | yok | ADX>20 + gövde≥1% | 63 | +0.63% | 49% | 39 | +0.57% | 51% |
| M15 | 8/34/89 | mid_slow | 5 | 1.5 | 90 | yok | ADX>20 + gövde≥1% | 63 | +0.57% | 40% | 39 | +0.64% | 44% |
| M15 | 8/34/89 | mid_slow | 5 | 2 | 90 | yok | ADX>20 + gövde≥1% | 63 | +0.56% | 43% | 39 | +0.66% | 49% |
| H1 | 5/13/50 | fast_mid | 4 | 4 | 180 | yok | ADX>25 + hacim≥1.5× | 103 | +0.55% | 55% | 60 | +0.66% | 62% |
| H1 | 5/13/50 | fast_mid | 4 | 3 | 240 | yok | ADX>25 + hacim≥1.5× | 103 | +0.52% | 54% | 60 | +0.63% | 55% |
| H1 | 5/13/50 | fast_mid | 4 | 4 | 240 | yok | ADX>25 + hacim≥1.5× | 103 | +0.51% | 56% | 60 | +0.73% | 58% |
| H1 | 5/13/50 | fast_mid | 4 | 3 | 180 | yok | ADX>25 + hacim≥1.5× | 103 | +0.51% | 53% | 60 | +0.49% | 57% |
| M15 | 8/34/89 | mid_slow | 5 | 1.5 | 180 | yok | gövde≥1% | 66 | +0.48% | 38% | 41 | +0.57% | 41% |
| M15 | 8/34/89 | mid_slow | 5 | 1.5 | 180 | yok | gövde≥0.3% + gövde≥1% | 66 | +0.48% | 38% | 41 | +0.57% | 41% |
| M15 | 8/34/89 | mid_slow | 5 | 1.5 | 180 | yok | gövde≥1% + ATR14≥0.6% | 66 | +0.48% | 38% | 41 | +0.57% | 41% |
| H1 | 5/13/50 | ribbon | 4 | 3 | 180 | yok | ADX>25 + hacim≥1.5× | 91 | +0.47% | 54% | 53 | +0.49% | 58% |
| H1 | 5/13/50 | ribbon | 4 | 4 | 180 | yok | ADX>25 + hacim≥1.5× | 91 | +0.47% | 55% | 53 | +0.69% | 64% |
| M15 | 8/34/89 | mid_slow | 5 | 1.5 | 240 | yok | gövde≥1% | 66 | +0.47% | 36% | 41 | +0.48% | 37% |
| M15 | 8/34/89 | mid_slow | 5 | 1.5 | 240 | yok | gövde≥0.3% + gövde≥1% | 66 | +0.47% | 36% | 41 | +0.48% | 37% |
| M15 | 8/34/89 | mid_slow | 5 | 1.5 | 240 | yok | gövde≥1% + ATR14≥0.6% | 66 | +0.47% | 36% | 41 | +0.48% | 37% |
| H1 | 5/13/50 | ribbon | 4 | 3 | 240 | yok | ADX>25 + hacim≥1.5× | 91 | +0.47% | 54% | 53 | +0.66% | 57% |

## Eğitimde en iyi 25 (test sütunu: seçim sonrası tek bakış)

| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| M5 | 10/30/100 | ribbon | 5 | 4 | 120 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +1.14% | 59% | 36 | -0.63% | 31% |
| M5 | 10/30/100 | ribbon | 5 | 4 | 120 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +1.02% | 70% | 36 | -0.61% | 39% |
| M5 | 10/30/100 | ribbon | 5 | 3 | 120 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +0.96% | 55% | 36 | -0.75% | 28% |
| M5 | 10/30/100 | ribbon | 4 | 4 | 120 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +0.95% | 59% | 36 | -0.58% | 31% |
| M5 | 10/30/100 | ribbon | 5 | 4 | 90 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 67 | +0.94% | 52% | 37 | -1.02% | 32% |
| M5 | 10/30/100 | ribbon | 4 | 4 | 120 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +0.91% | 70% | 36 | -0.63% | 39% |
| M5 | 10/30/100 | ribbon | 5 | 4 | 180 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 60 | +0.89% | 53% | 35 | -1.16% | 29% |
| M5 | 10/30/100 | ribbon | 5 | 3 | 120 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +0.88% | 67% | 36 | -0.60% | 36% |
| M30 | 3/8/21 | ribbon | 5 | 3 | 240 | yok | hacim≥1.5× + yavaşa uzaklık≤2% | 84 | +0.85% | 54% | 60 | -0.59% | 32% |
| M5 | 10/30/100 | ribbon | 5 | 4 | 180 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 60 | +0.84% | 68% | 35 | -0.67% | 43% |
| M5 | 10/30/100 | ribbon | 4 | 4 | 90 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 67 | +0.84% | 54% | 37 | -0.99% | 32% |
| M5 | 10/30/100 | ribbon | 5 | 4 | 60 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 68 | +0.81% | 56% | 39 | -0.70% | 31% |
| M5 | 10/30/100 | ribbon | 5 | 3 | 90 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 67 | +0.81% | 51% | 37 | -1.00% | 32% |
| M5 | 10/30/100 | ribbon | 4 | 3 | 120 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +0.80% | 56% | 36 | -0.68% | 28% |
| M30 | 3/8/21 | ribbon | 5 | 4 | 240 | yok | hacim≥1.5× + yavaşa uzaklık≤2% | 84 | +0.80% | 54% | 60 | -0.55% | 33% |
| M5 | 10/30/100 | ribbon | 5 | 3 | 180 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 60 | +0.79% | 67% | 35 | -0.65% | 40% |
| M5 | 10/30/100 | ribbon | 5 | 3 | 60 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 68 | +0.78% | 54% | 39 | -0.67% | 31% |
| M5 | 10/30/100 | ribbon | 4 | 3 | 120 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +0.77% | 67% | 36 | -0.62% | 36% |
| M5 | 10/30/100 | ribbon | 5 | 4 | 120 | 1.5/0.75 | yavaşa uzaklık≤1% + ATR14≥0.6% | 66 | +0.75% | 74% | 36 | -0.44% | 50% |
| M5 | 10/30/100 | ribbon | 5 | 3 | 180 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 60 | +0.74% | 50% | 35 | -1.17% | 26% |
| M30 | 3/8/21 | mid_slow | 5 | 4 | 240 | yok | StochRSI≤50 + ADX>20 | 63 | +0.74% | 48% | 35 | -1.10% | 31% |
| M5 | 10/30/100 | ribbon | 5 | 4 | 90 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 67 | +0.74% | 58% | 37 | -0.74% | 41% |
| M30 | 3/8/21 | ribbon | 5 | 2 | 240 | yok | hacim≥1.5× + yavaşa uzaklık≤2% | 84 | +0.74% | 51% | 60 | -0.56% | 27% |
| H1 | 7/20/99 | fast_mid | 5 | 4 | 240 | yok | gövde≥1% + hacim≥2× | 73 | +0.74% | 56% | 41 | -0.53% | 34% |
| M5 | 10/30/100 | ribbon | 4 | 4 | 180 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 60 | +0.73% | 68% | 35 | -0.70% | 43% |

## Hedef %2 ve tutma ≤ 60 dk ile en iyi 15 (eğitime göre)

| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| — | yok | | | | | | | | | | | | |

## Okuma

- 1871480 denemenin eğitim ortalaması medyanı -0.23%, en iyi +1.14%; eğitimde en iyi 100'ün test ortalaması medyanı -0.46% ve 23 tanesi testte artı.
- Eğitimde en iyi görünen kombinasyonun testte de artı kalması gerekir; aksi hâlde sonuç çoklu deneme (seçim) gürültüsüdür. 2367360 denemeden şans eseri de artı çıkanlar olur.
- İz süren stop bir önceki mumun tepesinden; aynı mumda stop ve hedef görülürse stop. 1 dk mumlarda boşluk varsa pencere zaman değil mum sayar.
