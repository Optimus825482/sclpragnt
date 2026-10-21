# MA kesişimi kombinasyon araması — 90 gün (2026-10-21 15:02)

Evren: canlı sistem mantığı (ilk 50 yükselen + saatlik aktivite; 310 TRY çifti; saatlik ortalama taranan 11.7). Eğitim: ilk 60 gün, test: son 30 gün. Maliyet (gidiş-dönüş): 0.275%. Giriş: kapanışın %0.5 altına limit, 15 dk içinde dolmazsa yok. Sembol başına tek pozisyon (tutma süresi dolmadan ikinci sinyal atlanır).

Denenen: 72 giriş seti (TF × MA üçlüsü × kural; toplam 149815 ham sinyal) × 108 çıkış kombinasyonu × 137 filtre maskesi = 702036 geçerli deneme (n eğitim ≥ 60, n test ≥ 25); 42165 tanesi eğitimde artı.

## Hem eğitimde hem testte artı olanlar (min(eğitim, test) ortalamasına göre)

| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| H1 | 5/13/50 | ribbon | 5 | 2 | 240 | yok | ADX>25 + hacim≥1.5× | 60 | +0.76% | 48% | 36 | +0.69% | 44% |
| H1 | 5/13/50 | ribbon | 5 | 3 | 240 | yok | ADX>25 + hacim≥1.5× | 60 | +0.62% | 52% | 36 | +1.36% | 58% |
| H1 | 5/13/50 | ribbon | 5 | 3 | 240 | yok | RSI<70 + hacim≥1.5× | 64 | +0.61% | 48% | 30 | +0.67% | 50% |
| H1 | 5/13/50 | fast_mid | 5 | 3 | 240 | yok | ADX>25 + hacim≥1.5× | 65 | +0.60% | 52% | 40 | +1.03% | 55% |
| H1 | 3/8/21 | ribbon | 5 | 3 | 240 | 1.5/0.75 | gövde≥1% + hacim≥2× | 71 | +0.57% | 76% | 34 | +0.65% | 74% |
| H1 | 5/13/50 | ribbon | 5 | 2 | 240 | yok | ADX>20 + hacim≥1.5× | 76 | +0.55% | 45% | 41 | +0.55% | 44% |
| H1 | 5/13/50 | ribbon | 5 | 3 | 240 | yok | StochRSI≤80 + hacim≥1.5× | 84 | +0.54% | 49% | 40 | +0.78% | 52% |
| H1 | 5/13/50 | ribbon | 5 | 2 | 240 | yok | StochRSI≤80 + hacim≥1.5× | 84 | +0.65% | 45% | 40 | +0.52% | 45% |
| H1 | 5/13/50 | ribbon | 5 | 2 | 120 | yok | ADX>25 + hacim≥1.5× | 60 | +0.52% | 48% | 36 | +0.51% | 44% |
| H1 | 5/13/50 | ribbon | 3 | 3 | 120 | yok | ADX>25 + hacim≥1.5× | 60 | +0.51% | 60% | 36 | +0.57% | 61% |
| H1 | 3/8/21 | ribbon | 5 | 3 | 240 | 1.5/0.75 | gövde≥0.3% + hacim≥2× | 82 | +0.50% | 72% | 37 | +0.50% | 70% |
| H1 | 3/8/21 | ribbon | 3 | 3 | 240 | 1.5/0.75 | gövde≥1% + hacim≥2× | 71 | +0.51% | 76% | 34 | +0.49% | 74% |
| H1 | 3/8/21 | ribbon | 5 | 3 | 240 | 2/1 | gövde≥1% + hacim≥2× | 71 | +0.58% | 70% | 34 | +0.49% | 68% |
| H1 | 5/13/50 | ribbon | 5 | 2 | 120 | yok | StochRSI≤80 + hacim≥1.5× | 84 | +0.48% | 48% | 40 | +0.50% | 45% |
| H1 | 5/13/50 | fast_mid | 5 | 3 | 240 | yok | hacim≥1.5× + yavaş MA yükseliyor | 85 | +0.65% | 52% | 42 | +0.47% | 45% |
| H1 | 5/13/50 | ribbon | 5 | 3 | 240 | yok | hacim≥1.5× + yavaş MA yükseliyor | 81 | +0.47% | 49% | 38 | +0.78% | 50% |
| H1 | 5/13/50 | ribbon | 5 | 3 | 120 | yok | ADX>25 + hacim≥1.5× | 60 | +0.47% | 52% | 36 | +1.13% | 58% |
| H1 | 5/13/50 | fast_mid | 5 | 3 | 240 | yok | ADX>25 + saat 09–23 | 103 | +0.47% | 50% | 73 | +0.47% | 49% |
| H1 | 5/13/50 | fast_mid | 5 | 2 | 240 | yok | ADX>25 + hacim≥1.5× | 65 | +0.72% | 49% | 40 | +0.47% | 42% |
| H1 | 5/13/50 | fast_mid | 5 | 3 | 120 | yok | ADX>25 + hacim≥1.5× | 65 | +0.47% | 51% | 40 | +0.81% | 52% |
| H1 | 5/13/50 | ribbon | 3 | 4 | 240 | yok | ADX>25 + hacim≥1.5× | 60 | +0.46% | 63% | 36 | +0.49% | 67% |
| H1 | 5/13/50 | fast_mid | 5 | 3 | 240 | yok | ADX>20 + hacim≥1.5× | 86 | +0.46% | 49% | 53 | +0.62% | 51% |
| H1 | 5/13/50 | ribbon | 5 | 3 | 240 | yok | ADX>25 + saat 09–23 | 101 | +0.46% | 50% | 69 | +0.61% | 51% |
| H1 | 5/13/50 | fast_mid | 3 | 3 | 120 | yok | ADX>25 + hacim≥1.5× | 65 | +0.49% | 58% | 40 | +0.45% | 57% |
| H1 | 5/13/50 | fast_mid | 5 | 3 | 120 | yok | StochRSI≤80 + hacim≥1.5× | 98 | +0.45% | 50% | 48 | +0.47% | 50% |

## Eğitimde en iyi 25 (test sütunu: seçim sonrası tek bakış)

| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| H1 | 7/20/99 | fast_mid | 5 | 4 | 240 | yok | RSI<70 + hacim≥2× | 60 | +0.85% | 53% | 26 | -0.96% | 27% |
| H1 | 5/13/50 | fast_mid | 5 | 3 | 120 | yok | RSI<70 + hacim≥2× | 67 | +0.83% | 52% | 35 | -0.38% | 37% |
| H1 | 5/13/50 | fast_mid | 5 | 3 | 240 | yok | RSI<70 + hacim≥2× | 67 | +0.82% | 52% | 35 | -0.28% | 40% |
| H1 | 5/13/50 | fast_mid | 5 | 3 | 240 | yok | RSI<70 + hacim≥1.5× | 93 | +0.81% | 53% | 45 | +0.01% | 42% |
| M5 | 10/30/100 | fast_mid | 5 | 4 | 240 | 1.5/0.75 | StochRSI≤50 + yavaşa uzaklık≤2% | 62 | +0.81% | 76% | 38 | -0.80% | 47% |
| M15 | 10/30/100 | mid_slow | 5 | 4 | 120 | yok | ADX>25 + hacim≥1.5× | 68 | +0.79% | 57% | 49 | -0.15% | 47% |
| H1 | 5/13/50 | fast_mid | 5 | 4 | 120 | yok | RSI<70 + hacim≥2× | 67 | +0.79% | 54% | 35 | -0.57% | 37% |
| H1 | 5/13/50 | fast_mid | 5 | 2 | 240 | yok | hacim≥2× + yavaş MA yükseliyor | 60 | +0.78% | 47% | 34 | +0.16% | 35% |
| H1 | 5/13/50 | fast_mid | 5 | 2 | 240 | yok | hacim≥1.5× + yavaş MA yükseliyor | 85 | +0.77% | 48% | 42 | +0.17% | 36% |
| M5 | 10/30/100 | fast_mid | 5 | 3 | 240 | 2/1 | StochRSI≤50 + yavaşa uzaklık≤2% | 62 | +0.77% | 66% | 38 | -0.69% | 39% |
| H1 | 5/13/50 | fast_mid | 5 | 3 | 240 | yok | gövde≥1% + hacim≥2× | 63 | +0.77% | 52% | 41 | +0.03% | 39% |
| M5 | 3/8/21 | ribbon | 5 | 4 | 240 | yok | gövde≥1% + yavaşa uzaklık≤2% | 106 | +0.76% | 54% | 66 | -0.17% | 45% |
| H1 | 5/13/50 | ribbon | 5 | 2 | 240 | yok | ADX>25 + hacim≥1.5× | 60 | +0.76% | 48% | 36 | +0.69% | 44% |
| M5 | 10/30/100 | fast_mid | 5 | 4 | 240 | 2/1 | StochRSI≤50 + yavaşa uzaklık≤2% | 62 | +0.75% | 66% | 38 | -0.77% | 42% |
| H1 | 5/13/50 | fast_mid | 5 | 4 | 240 | yok | RSI<70 + hacim≥2× | 67 | +0.75% | 54% | 35 | -0.41% | 43% |
| M15 | 10/30/100 | mid_slow | 5 | 4 | 120 | yok | ADX>20 + hacim≥2× | 66 | +0.75% | 58% | 44 | -0.04% | 45% |
| M5 | 10/30/100 | fast_mid | 5 | 3 | 240 | 1.5/0.75 | StochRSI≤50 + yavaşa uzaklık≤2% | 62 | +0.75% | 74% | 38 | -0.73% | 45% |
| M5 | 10/30/100 | ribbon | 5 | 3 | 120 | yok | yavaşa uzaklık≤1% + saat 09–23 | 64 | +0.74% | 52% | 39 | -0.59% | 26% |
| M5 | 10/30/100 | fast_mid | 5 | 3 | 240 | yok | StochRSI≤50 + yavaşa uzaklık≤2% | 62 | +0.74% | 56% | 38 | -0.65% | 29% |
| H1 | 5/13/50 | fast_mid | 5 | 2 | 120 | yok | hacim≥2× + yavaş MA yükseliyor | 60 | +0.74% | 50% | 34 | -0.06% | 35% |
| M15 | 3/8/21 | mid_slow | 5 | 2 | 240 | yok | ADX>25 + gövde≥1% | 97 | +0.74% | 44% | 58 | -0.86% | 21% |
| H1 | 5/13/50 | fast_mid | 5 | 3 | 120 | yok | gövde≥1% + hacim≥2× | 63 | +0.73% | 49% | 41 | -0.09% | 39% |
| M5 | 10/30/100 | ribbon | 5 | 4 | 120 | yok | yavaşa uzaklık≤1% + saat 09–23 | 64 | +0.73% | 52% | 39 | -0.36% | 31% |
| M5 | 10/30/100 | ribbon | 5 | 4 | 240 | yok | StochRSI≤80 + yavaşa uzaklık≤1% | 64 | +0.72% | 59% | 30 | -1.51% | 20% |
| M5 | 10/30/100 | ribbon | 5 | 3 | 240 | yok | StochRSI≤80 + yavaşa uzaklık≤1% | 64 | +0.72% | 56% | 30 | -1.67% | 13% |

## Hedef %2 ve tutma ≤ 60 dk ile en iyi 15 (eğitime göre)

| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| M15 | 9/21/55 | ribbon | 2 | 2 | 60 | 1/0.5 | ADX>25 + gövde≥1% | 84 | +0.32% | 74% | 42 | -0.42% | 55% |
| H1 | 3/8/21 | ribbon | 2 | 2 | 60 | 1.5/0.75 | StochRSI≤50 + hacim≥1.5× | 63 | +0.30% | 63% | 25 | -0.44% | 44% |
| M15 | 9/21/55 | ribbon | 2 | 4 | 60 | 1/0.5 | ADX>25 + gövde≥1% | 84 | +0.30% | 77% | 42 | -0.44% | 62% |
| M15 | 3/8/21 | mid_slow | 2 | 2 | 60 | yok | ADX>25 + gövde≥1% | 102 | +0.29% | 60% | 59 | -0.56% | 39% |
| M15 | 3/8/21 | mid_slow | 2 | 2 | 60 | 2/1 | ADX>25 + gövde≥1% | 102 | +0.29% | 60% | 59 | -0.56% | 39% |
| H1 | 5/13/50 | ribbon | 2 | 2 | 60 | yok | StochRSI≤50 + saat 09–23 | 69 | +0.28% | 58% | 39 | -0.49% | 33% |
| H1 | 5/13/50 | ribbon | 2 | 2 | 60 | 2/1 | StochRSI≤50 + saat 09–23 | 69 | +0.28% | 58% | 39 | -0.49% | 33% |
| H1 | 3/8/21 | ribbon | 2 | 2 | 60 | yok | StochRSI≤50 + hacim≥1.5× | 63 | +0.27% | 60% | 25 | -0.44% | 40% |
| H1 | 3/8/21 | ribbon | 2 | 2 | 60 | 2/1 | StochRSI≤50 + hacim≥1.5× | 63 | +0.27% | 60% | 25 | -0.44% | 40% |
| M15 | 9/21/55 | fast_mid | 2 | 3 | 60 | yok | StochRSI≤80 + gövde≥1% | 91 | +0.27% | 63% | 53 | -0.36% | 47% |
| M15 | 9/21/55 | fast_mid | 2 | 3 | 60 | 2/1 | StochRSI≤80 + gövde≥1% | 91 | +0.27% | 63% | 53 | -0.36% | 47% |
| M15 | 7/20/99 | ribbon | 2 | 2 | 60 | yok | StochRSI≤80 + hacim≥2× | 65 | +0.25% | 62% | 44 | -0.57% | 41% |
| M15 | 7/20/99 | ribbon | 2 | 2 | 60 | 2/1 | StochRSI≤80 + hacim≥2× | 65 | +0.25% | 62% | 44 | -0.57% | 41% |
| M15 | 7/20/99 | ribbon | 2 | 2 | 60 | 1.5/0.75 | StochRSI≤80 + hacim≥2× | 65 | +0.25% | 66% | 44 | -0.42% | 48% |
| M15 | 9/21/55 | ribbon | 2 | 2 | 60 | yok | ADX>25 + gövde≥1% | 84 | +0.25% | 58% | 42 | -0.57% | 36% |

## Okuma

- 702036 denemenin eğitim ortalaması medyanı -0.28%, en iyi +0.85%; eğitimde en iyi 100'ün test ortalaması medyanı -0.26% ve 23 tanesi testte artı.
- Eğitimde en iyi görünen kombinasyonun testte de artı kalması gerekir; aksi hâlde sonuç çoklu deneme (seçim) gürültüsüdür. 1065312 denemeden şans eseri de artı çıkanlar olur.
- İz süren stop bir önceki mumun tepesinden; aynı mumda stop ve hedef görülürse stop. 1 dk mumlarda boşluk varsa pencere zaman değil mum sayar.
