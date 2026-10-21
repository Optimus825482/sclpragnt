# MA kesişimi kombinasyon araması — 90 gün (2026-10-21 16:39)

Evren: 24 sa hacmi ≥ 1M TL olan tüm çiftler (aktivite filtresi yok); 310 TRY çifti; saatlik ortalama taranan 286.1). Eğitim: ilk 60 gün, test: son 30 gün. Maliyet (gidiş-dönüş): 0.275%. Giriş: sinyal mumu kapanışı (piyasa). Sembol başına tek pozisyon (tutma süresi dolmadan ikinci sinyal atlanır).

Denenen: 72 giriş seti (TF × MA üçlüsü × kural; toplam 4335226 ham sinyal) × 108 çıkış kombinasyonu × 137 filtre maskesi = 1061280 geçerli deneme (n eğitim ≥ 60, n test ≥ 25); 782 tanesi eğitimde artı.

## Hem eğitimde hem testte artı olanlar (min(eğitim, test) ortalamasına göre)

| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| H1 | 9/21/55 | mid_slow | 5 | 3 | 240 | 2/1 | StochRSI≤50 + saat 09–23 | 832 | +0.08% | 48% | 523 | +0.12% | 50% |
| H1 | 9/21/55 | mid_slow | 5 | 4 | 240 | 2/1 | StochRSI≤50 + saat 09–23 | 832 | +0.08% | 48% | 523 | +0.09% | 50% |
| H1 | 9/21/55 | mid_slow | 5 | 3 | 240 | yok | StochRSI≤50 + saat 09–23 | 832 | +0.07% | 44% | 523 | +0.08% | 47% |
| H1 | 9/21/55 | mid_slow | 5 | 3 | 240 | 2/1 | StochRSI≤50 + ATR14≥0.6% | 1130 | +0.06% | 48% | 649 | +0.07% | 53% |
| H1 | 9/21/55 | mid_slow | 5 | 3 | 240 | 1.5/0.75 | StochRSI≤50 + saat 09–23 | 832 | +0.06% | 49% | 523 | +0.13% | 53% |
| H1 | 9/21/55 | mid_slow | 5 | 4 | 240 | 1.5/0.75 | StochRSI≤50 + saat 09–23 | 832 | +0.06% | 49% | 523 | +0.11% | 53% |
| H1 | 9/21/55 | mid_slow | 5 | 4 | 240 | yok | StochRSI≤50 + saat 09–23 | 832 | +0.07% | 45% | 523 | +0.05% | 47% |
| H1 | 9/21/55 | mid_slow | 5 | 3 | 240 | 1/0.5 | gövde≥1% + yavaşa uzaklık≤1% | 76 | +0.05% | 63% | 37 | +0.41% | 68% |
| M5 | 10/30/100 | ribbon | 5 | 4 | 120 | 2/1 | yavaşa uzaklık≤1% + ATR14≥0.6% | 207 | +0.05% | 49% | 118 | +0.11% | 53% |
| H1 | 8/34/89 | mid_slow | 5 | 3 | 240 | 1/0.5 | ADX>25 + hacim≥2× | 310 | +0.05% | 66% | 129 | +0.05% | 63% |
| H1 | 9/21/55 | mid_slow | 3 | 3 | 240 | 2/1 | StochRSI≤50 + saat 09–23 | 832 | +0.04% | 48% | 523 | +0.06% | 50% |
| H1 | 9/21/55 | mid_slow | 5 | 3 | 240 | yok | gövde≥1% + yavaşa uzaklık≤1% | 76 | +0.04% | 37% | 37 | +0.48% | 49% |
| H1 | 9/21/55 | mid_slow | 5 | 3 | 240 | 2/1 | StochRSI≤50 + yavaşa uzaklık≤1% | 1141 | +0.04% | 45% | 621 | +0.07% | 51% |
| H1 | 9/21/55 | mid_slow | 5 | 3 | 240 | yok | StochRSI≤50 + ATR14≥0.6% | 1130 | +0.04% | 45% | 649 | +0.04% | 49% |
| H1 | 9/21/55 | mid_slow | 5 | 4 | 240 | 1/0.5 | gövde≥1% + yavaşa uzaklık≤1% | 76 | +0.04% | 63% | 37 | +0.38% | 68% |
| H1 | 9/21/55 | mid_slow | 5 | 3 | 240 | 1.5/0.75 | StochRSI≤50 + ATR14≥0.6% | 1130 | +0.04% | 51% | 649 | +0.08% | 55% |
| H1 | 9/21/55 | mid_slow | 3 | 4 | 240 | 2/1 | StochRSI≤50 + saat 09–23 | 832 | +0.04% | 48% | 523 | +0.04% | 50% |
| H1 | 9/21/55 | mid_slow | 5 | 3 | 240 | 1/0.5 | StochRSI≤50 + saat 09–23 | 832 | +0.04% | 55% | 523 | +0.07% | 59% |
| H1 | 9/21/55 | mid_slow | 5 | 4 | 240 | 1.5/0.75 | StochRSI≤50 + ATR14≥0.6% | 1130 | +0.03% | 51% | 649 | +0.04% | 56% |
| H1 | 9/21/55 | mid_slow | 5 | 4 | 240 | 2/1 | StochRSI≤50 + ATR14≥0.6% | 1130 | +0.06% | 49% | 649 | +0.03% | 53% |
| H1 | 9/21/55 | mid_slow | 5 | 4 | 240 | 2/1 | StochRSI≤50 + yavaşa uzaklık≤1% | 1141 | +0.04% | 45% | 621 | +0.03% | 51% |
| H1 | 9/21/55 | mid_slow | 5 | 4 | 240 | 1/0.5 | StochRSI≤50 + saat 09–23 | 832 | +0.03% | 55% | 523 | +0.04% | 59% |
| H1 | 9/21/55 | mid_slow | 3 | 3 | 240 | 1.5/0.75 | StochRSI≤50 + saat 09–23 | 832 | +0.03% | 49% | 523 | +0.07% | 53% |
| H1 | 9/21/55 | mid_slow | 5 | 4 | 240 | yok | gövde≥1% + yavaşa uzaklık≤1% | 76 | +0.03% | 37% | 37 | +0.40% | 49% |
| H1 | 9/21/55 | mid_slow | 3 | 3 | 240 | 1/0.5 | gövde≥1% + yavaşa uzaklık≤1% | 76 | +0.03% | 63% | 37 | +0.33% | 68% |

## Eğitimde en iyi 25 (test sütunu: seçim sonrası tek bakış)

| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| M30 | 7/20/99 | ribbon | 5 | 4 | 240 | yok | StochRSI≤50 + gövde≥1% | 234 | +0.18% | 44% | 111 | -0.77% | 32% |
| M5 | 3/8/21 | ribbon | 3 | 4 | 240 | yok | gövde≥1% + yavaşa uzaklık≤1% | 127 | +0.16% | 50% | 56 | -0.52% | 38% |
| M30 | 9/21/55 | ribbon | 5 | 3 | 240 | 1.5/0.75 | StochRSI≤50 + hacim≥1.5× | 267 | +0.14% | 55% | 136 | -0.25% | 45% |
| H1 | 9/21/55 | mid_slow | 5 | 4 | 240 | 2/1 | StochRSI≤50 + yavaş MA yükseliyor | 365 | +0.14% | 48% | 181 | -0.21% | 51% |
| M5 | 10/30/100 | ribbon | 5 | 4 | 120 | yok | yavaşa uzaklık≤1% + ATR14≥0.6% | 207 | +0.13% | 43% | 118 | -0.06% | 42% |
| H1 | 9/21/55 | mid_slow | 5 | 3 | 240 | 2/1 | StochRSI≤50 + yavaş MA yükseliyor | 365 | +0.13% | 48% | 181 | -0.16% | 50% |
| H1 | 10/30/100 | ribbon | 5 | 4 | 240 | 1.5/0.75 | ADX>25 + hacim≥1.5× | 294 | +0.13% | 56% | 121 | -0.31% | 46% |
| M5 | 3/8/21 | ribbon | 5 | 4 | 240 | yok | gövde≥1% + yavaşa uzaklık≤1% | 127 | +0.13% | 46% | 56 | -0.34% | 38% |
| M15 | 7/20/99 | mid_slow | 5 | 4 | 240 | yok | StochRSI≤50 + gövde≥1% | 75 | +0.13% | 43% | 47 | -0.60% | 40% |
| M5 | 3/8/21 | ribbon | 5 | 4 | 240 | 1.5/0.75 | gövde≥1% + yavaşa uzaklık≤1% | 127 | +0.13% | 58% | 56 | -0.30% | 48% |
| M15 | 7/20/99 | mid_slow | 5 | 2 | 240 | yok | StochRSI≤50 + gövde≥1% | 75 | +0.12% | 39% | 47 | -0.49% | 32% |
| M30 | 7/20/99 | ribbon | 5 | 4 | 240 | 1.5/0.75 | StochRSI≤50 + ADX>25 | 780 | +0.12% | 54% | 322 | -0.24% | 50% |
| M15 | 8/34/89 | ribbon | 5 | 2 | 240 | 1.5/0.75 | StochRSI≤50 + gövde≥1% | 98 | +0.12% | 54% | 42 | -0.17% | 57% |
| M30 | 9/21/55 | ribbon | 5 | 4 | 240 | 1.5/0.75 | StochRSI≤50 + hacim≥1.5× | 267 | +0.12% | 55% | 136 | -0.35% | 45% |
| M15 | 7/20/99 | mid_slow | 5 | 2 | 120 | 2/1 | StochRSI≤50 + gövde≥1% | 80 | +0.11% | 49% | 47 | -0.29% | 38% |
| H1 | 9/21/55 | mid_slow | 5 | 4 | 240 | yok | StochRSI≤50 + yavaş MA yükseliyor | 365 | +0.11% | 45% | 181 | -0.27% | 46% |
| M30 | 7/20/99 | ribbon | 5 | 3 | 240 | 1.5/0.75 | StochRSI≤50 + ADX>25 | 780 | +0.11% | 53% | 322 | -0.22% | 50% |
| H1 | 9/21/55 | mid_slow | 5 | 3 | 240 | yok | StochRSI≤50 + yavaş MA yükseliyor | 365 | +0.11% | 44% | 181 | -0.21% | 46% |
| M15 | 7/20/99 | mid_slow | 5 | 2 | 120 | yok | StochRSI≤50 + gövde≥1% | 80 | +0.11% | 40% | 47 | -0.42% | 34% |
| M30 | 9/21/55 | ribbon | 5 | 2 | 240 | 1.5/0.75 | StochRSI≤50 + hacim≥1.5× | 267 | +0.11% | 54% | 136 | -0.18% | 43% |
| M30 | 7/20/99 | ribbon | 5 | 4 | 240 | 2/1 | StochRSI≤50 + ADX>25 | 780 | +0.11% | 50% | 322 | -0.26% | 46% |
| H1 | 10/30/100 | ribbon | 5 | 4 | 240 | 1.5/0.75 | ADX>25 + gövde≥1% | 213 | +0.11% | 59% | 82 | -0.25% | 52% |
| M30 | 9/21/55 | ribbon | 5 | 3 | 240 | 2/1 | StochRSI≤50 + hacim≥1.5× | 267 | +0.11% | 52% | 136 | -0.22% | 43% |
| M5 | 3/8/21 | ribbon | 3 | 3 | 240 | yok | gövde≥1% + yavaşa uzaklık≤1% | 127 | +0.11% | 48% | 56 | -0.51% | 38% |
| M5 | 3/8/21 | ribbon | 5 | 3 | 240 | 1.5/0.75 | gövde≥1% + yavaşa uzaklık≤1% | 127 | +0.11% | 57% | 56 | -0.27% | 48% |

## Hedef %2 ve tutma ≤ 60 dk ile en iyi 15 (eğitime göre)

| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| — | yok | | | | | | | | | | | | |

## Okuma

- 1061280 denemenin eğitim ortalaması medyanı -0.28%, en iyi +0.18%; eğitimde en iyi 100'ün test ortalaması medyanı -0.28% ve 4 tanesi testte artı.
- Eğitimde en iyi görünen kombinasyonun testte de artı kalması gerekir; aksi hâlde sonuç çoklu deneme (seçim) gürültüsüdür. 1065312 denemeden şans eseri de artı çıkanlar olur.
- İz süren stop bir önceki mumun tepesinden; aynı mumda stop ve hedef görülürse stop. 1 dk mumlarda boşluk varsa pencere zaman değil mum sayar.
