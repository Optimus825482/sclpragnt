# MA kesişimi kombinasyon araması — 90 gün (2026-10-21 15:32)

Evren: likitler içinde 24 sa değişimi en düşük 50; 310 TRY çifti; saatlik ortalama taranan 50.0). Eğitim: ilk 60 gün, test: son 30 gün. Maliyet (gidiş-dönüş): 0.275%. Giriş: sinyal mumu kapanışı (piyasa). Sembol başına tek pozisyon (tutma süresi dolmadan ikinci sinyal atlanır).

Denenen: 72 giriş seti (TF × MA üçlüsü × kural; toplam 654485 ham sinyal) × 360 çıkış kombinasyonu × 137 filtre maskesi = 2751960 geçerli deneme (n eğitim ≥ 60, n test ≥ 25); 81344 tanesi eğitimde artı.

## Hem eğitimde hem testte artı olanlar (min(eğitim, test) ortalamasına göre)

| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| H1 | 10/30/100 | ribbon | 2.5 | 4 | 240 | yok | ATR14≥0.6% + saat 09–23 | 120 | +0.39% | 60% | 50 | +0.41% | 58% |
| H1 | 10/30/100 | ribbon | 3 | 4 | 240 | 2/1 | StochRSI≤80 + ATR14≥0.6% | 102 | +0.37% | 58% | 53 | +0.56% | 66% |
| H1 | 10/30/100 | ribbon | 2.5 | 4 | 240 | 2/1 | ATR14≥0.6% + saat 09–23 | 120 | +0.37% | 60% | 50 | +0.40% | 60% |
| H1 | 10/30/100 | ribbon | 3 | 4 | 240 | yok | ATR14≥0.6% + saat 09–23 | 120 | +0.40% | 58% | 50 | +0.36% | 58% |
| H1 | 10/30/100 | ribbon | 3 | 4 | 240 | 2/1 | ATR14≥0.6% + saat 09–23 | 120 | +0.35% | 60% | 50 | +0.40% | 60% |
| H1 | 10/30/100 | ribbon | 3 | 4 | 240 | yok | StochRSI≤80 + ATR14≥0.6% | 102 | +0.35% | 54% | 53 | +0.56% | 66% |
| H1 | 10/30/100 | ribbon | 3 | 3 | 240 | 2/1 | StochRSI≤80 + ATR14≥0.6% | 102 | +0.34% | 57% | 53 | +0.45% | 64% |
| H1 | 10/30/100 | ribbon | 3 | 3 | 240 | 2/1 | MACD hist artıyor + saat 09–23 | 64 | +0.34% | 56% | 25 | +0.34% | 44% |
| H1 | 10/30/100 | ribbon | 3 | 4 | 240 | 2/1 | MACD hist artıyor + saat 09–23 | 64 | +0.35% | 56% | 25 | +0.34% | 44% |
| H1 | 10/30/100 | ribbon | 2.5 | 4 | 240 | yok | yavaş MA yükseliyor + saat 09–23 | 125 | +0.33% | 58% | 55 | +0.36% | 53% |
| H1 | 10/30/100 | ribbon | 3 | 3 | 240 | yok | StochRSI≤80 + ATR14≥0.6% | 102 | +0.32% | 53% | 53 | +0.45% | 64% |
| H1 | 10/30/100 | ribbon | 2.5 | 4 | 240 | yok | RSI 45–65 + saat 09–23 | 121 | +0.34% | 57% | 60 | +0.32% | 52% |
| H1 | 10/30/100 | ribbon | 3 | 4 | 240 | 1.5/0.75 | MACD hist artıyor + saat 09–23 | 64 | +0.32% | 59% | 25 | +0.51% | 56% |
| H1 | 10/30/100 | ribbon | 2.5 | 4 | 240 | 2/1 | StochRSI≤80 + ATR14≥0.6% | 102 | +0.32% | 58% | 53 | +0.53% | 66% |
| H1 | 10/30/100 | ribbon | 2.5 | 4 | 240 | 2/1 | RSI 45–65 + saat 09–23 | 121 | +0.32% | 57% | 60 | +0.32% | 53% |
| H1 | 10/30/100 | ribbon | 3 | 4 | 240 | yok | yavaş MA yükseliyor + saat 09–23 | 125 | +0.33% | 56% | 55 | +0.32% | 53% |
| H1 | 10/30/100 | ribbon | 2.5 | 4 | 240 | yok | saat 09–23 | 135 | +0.32% | 56% | 64 | +0.31% | 52% |
| H1 | 10/30/100 | ribbon | 2.5 | 3 | 240 | 1.5/0.75 | ATR14≥0.6% + saat 09–23 | 120 | +0.31% | 63% | 50 | +0.31% | 64% |
| H1 | 10/30/100 | ribbon | 3 | 3 | 240 | 1.5/0.75 | MACD hist artıyor + saat 09–23 | 64 | +0.31% | 59% | 25 | +0.51% | 56% |
| H1 | 10/30/100 | ribbon | 2.5 | 4 | 240 | 2/1 | yavaş MA yükseliyor + saat 09–23 | 125 | +0.31% | 58% | 55 | +0.35% | 55% |
| H1 | 10/30/100 | ribbon | 2.5 | 4 | 240 | yok | StochRSI≤80 + ATR14≥0.6% | 102 | +0.31% | 56% | 53 | +0.52% | 66% |
| H1 | 10/30/100 | ribbon | 3 | 3 | 240 | yok | ATR14≥0.6% | 194 | +0.31% | 55% | 75 | +0.36% | 57% |
| H1 | 10/30/100 | ribbon | 3 | 3 | 240 | 1.5/0.75 | ATR14≥0.6% + saat 09–23 | 120 | +0.32% | 63% | 50 | +0.31% | 64% |
| H1 | 10/30/100 | ribbon | 3 | 4 | 240 | 1.5/0.75 | ATR14≥0.6% + saat 09–23 | 120 | +0.31% | 63% | 50 | +0.43% | 66% |
| H1 | 10/30/100 | ribbon | 2.5 | 4 | 240 | yok | RSI<70 + saat 09–23 | 134 | +0.31% | 56% | 64 | +0.31% | 52% |

## Eğitimde en iyi 25 (test sütunu: seçim sonrası tek bakış)

| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| M30 | 5/13/50 | mid_slow | 3 | 4 | 240 | yok | gövde≥1% + MACD hist artıyor | 70 | +0.66% | 60% | 30 | -0.91% | 33% |
| M30 | 9/21/55 | ribbon | 3 | 2 | 240 | yok | RSI<70 + hacim≥1.5× | 61 | +0.58% | 64% | 25 | -0.63% | 28% |
| M30 | 9/21/55 | ribbon | 3 | 4 | 240 | yok | RSI<70 + hacim≥1.5× | 61 | +0.58% | 64% | 25 | -0.33% | 36% |
| M30 | 9/21/55 | ribbon | 3 | 2 | 240 | yok | hacim≥1.5× | 62 | +0.57% | 63% | 25 | -0.63% | 28% |
| M30 | 9/21/55 | ribbon | 3 | 4 | 240 | yok | StochRSI≤80 + ATR14≥0.6% | 69 | +0.56% | 61% | 25 | -0.39% | 36% |
| M30 | 9/21/55 | ribbon | 3 | 3 | 240 | yok | RSI<70 + hacim≥1.5× | 61 | +0.56% | 64% | 25 | -0.35% | 36% |
| M30 | 9/21/55 | ribbon | 3 | 4 | 240 | yok | hacim≥1.5× | 62 | +0.56% | 63% | 25 | -0.33% | 36% |
| M30 | 9/21/55 | ribbon | 3 | 3 | 240 | yok | StochRSI≤80 + ATR14≥0.6% | 69 | +0.56% | 61% | 25 | -0.35% | 36% |
| M30 | 9/21/55 | ribbon | 3 | 3 | 240 | yok | StochRSI≤80 + saat 09–23 | 79 | +0.56% | 59% | 33 | -0.20% | 36% |
| M30 | 5/13/50 | mid_slow | 2.5 | 4 | 240 | yok | gövde≥1% + MACD hist artıyor | 70 | +0.56% | 61% | 30 | -0.85% | 37% |
| M15 | 7/20/99 | ribbon | 3 | 3 | 240 | yok | yavaşa uzaklık≤2% + ATR14≥0.6% | 111 | +0.56% | 64% | 52 | -0.38% | 44% |
| M30 | 9/21/55 | ribbon | 3 | 4 | 240 | yok | StochRSI≤80 + saat 09–23 | 79 | +0.55% | 59% | 33 | -0.19% | 36% |
| M15 | 7/20/99 | ribbon | 3 | 4 | 240 | yok | yavaşa uzaklık≤2% + ATR14≥0.6% | 111 | +0.55% | 65% | 52 | -0.41% | 44% |
| M30 | 9/21/55 | ribbon | 3 | 3 | 240 | yok | hacim≥1.5× | 62 | +0.55% | 63% | 25 | -0.35% | 36% |
| M30 | 5/13/50 | mid_slow | 3 | 4 | 240 | yok | gövde≥1% + ATR14≥0.6% | 74 | +0.53% | 59% | 31 | -0.78% | 35% |
| M30 | 9/21/55 | ribbon | 3 | 4 | 240 | yok | yavaşa uzaklık≤2% + ATR14≥0.6% | 91 | +0.53% | 59% | 29 | -0.57% | 31% |
| M30 | 9/21/55 | ribbon | 3 | 3 | 240 | yok | RSI 45–65 + saat 09–23 | 120 | +0.52% | 58% | 46 | -0.28% | 30% |
| M30 | 9/21/55 | ribbon | 3 | 4 | 240 | yok | RSI 45–65 + saat 09–23 | 120 | +0.52% | 58% | 46 | -0.29% | 30% |
| M30 | 9/21/55 | ribbon | 3 | 3 | 240 | yok | yavaşa uzaklık≤2% + ATR14≥0.6% | 91 | +0.52% | 59% | 29 | -0.55% | 31% |
| M30 | 9/21/55 | ribbon | 2.5 | 3 | 240 | yok | StochRSI≤80 + saat 09–23 | 79 | +0.51% | 59% | 33 | -0.24% | 36% |
| M15 | 7/20/99 | ribbon | 3 | 3 | 240 | 2/1 | yavaşa uzaklık≤2% + ATR14≥0.6% | 111 | +0.51% | 69% | 52 | -0.16% | 54% |
| M30 | 9/21/55 | ribbon | 2.5 | 2 | 240 | yok | RSI<70 + hacim≥1.5× | 61 | +0.51% | 64% | 25 | -0.67% | 28% |
| M30 | 9/21/55 | ribbon | 2.5 | 4 | 240 | yok | StochRSI≤80 + saat 09–23 | 79 | +0.51% | 59% | 33 | -0.06% | 39% |
| M15 | 7/20/99 | ribbon | 3 | 4 | 240 | 2/1 | yavaşa uzaklık≤2% + ATR14≥0.6% | 111 | +0.51% | 70% | 52 | -0.19% | 54% |
| M30 | 9/21/55 | ribbon | 2.5 | 4 | 240 | yok | RSI<70 + hacim≥1.5× | 61 | +0.50% | 64% | 25 | -0.19% | 40% |

## Hedef %2 ve tutma ≤ 60 dk ile en iyi 15 (eğitime göre)

| TF | MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| M15 | 8/34/89 | mid_slow | 2 | 1.5 | 60 | yok | yavaş MA yükseliyor + ATR14≥0.6% | 64 | +0.14% | 53% | 33 | -0.24% | 33% |
| M15 | 8/34/89 | mid_slow | 2 | 1.5 | 60 | 2/1 | yavaş MA yükseliyor + ATR14≥0.6% | 64 | +0.14% | 53% | 33 | -0.24% | 33% |
| M15 | 8/34/89 | mid_slow | 2 | 1.5 | 60 | 1/0.5 | yavaş MA yükseliyor + ATR14≥0.6% | 64 | +0.14% | 61% | 33 | -0.15% | 42% |
| H1 | 8/34/89 | ribbon | 2 | 3 | 60 | yok | ATR14≥0.6% + saat 09–23 | 125 | +0.13% | 50% | 36 | -0.44% | 17% |
| H1 | 8/34/89 | ribbon | 2 | 3 | 60 | 2/1 | ATR14≥0.6% + saat 09–23 | 125 | +0.13% | 50% | 36 | -0.44% | 17% |
| H1 | 8/34/89 | ribbon | 2 | 4 | 60 | yok | ATR14≥0.6% + saat 09–23 | 125 | +0.12% | 50% | 36 | -0.44% | 17% |
| H1 | 8/34/89 | ribbon | 2 | 4 | 60 | 2/1 | ATR14≥0.6% + saat 09–23 | 125 | +0.12% | 50% | 36 | -0.44% | 17% |
| M15 | 8/34/89 | mid_slow | 2 | 3 | 60 | yok | yavaş MA yükseliyor + ATR14≥0.6% | 64 | +0.10% | 55% | 33 | -0.12% | 33% |
| M15 | 8/34/89 | mid_slow | 2 | 3 | 60 | 2/1 | yavaş MA yükseliyor + ATR14≥0.6% | 64 | +0.10% | 55% | 33 | -0.12% | 33% |
| M15 | 8/34/89 | mid_slow | 2 | 1.5 | 60 | 1.5/0.75 | yavaş MA yükseliyor + ATR14≥0.6% | 64 | +0.10% | 56% | 33 | -0.21% | 36% |
| H1 | 8/34/89 | fast_mid | 2 | 3 | 60 | yok | StochRSI≤80 + saat 09–23 | 135 | +0.10% | 49% | 78 | -0.29% | 29% |
| H1 | 8/34/89 | fast_mid | 2 | 3 | 60 | 2/1 | StochRSI≤80 + saat 09–23 | 135 | +0.10% | 49% | 78 | -0.29% | 29% |
| M15 | 7/20/99 | mid_slow | 2 | 2 | 60 | 1.5/0.75 | hacim≥1.5× + ATR14≥0.6% | 95 | +0.10% | 49% | 50 | -0.42% | 40% |
| H1 | 8/34/89 | fast_mid | 2 | 2 | 60 | yok | StochRSI≤80 + saat 09–23 | 135 | +0.10% | 49% | 78 | -0.34% | 28% |
| H1 | 8/34/89 | fast_mid | 2 | 2 | 60 | 2/1 | StochRSI≤80 + saat 09–23 | 135 | +0.10% | 49% | 78 | -0.34% | 28% |

## Okuma

- 2751960 denemenin eğitim ortalaması medyanı -0.27%, en iyi +0.66%; eğitimde en iyi 100'ün test ortalaması medyanı -0.33% ve 2 tanesi testte artı.
- Eğitimde en iyi görünen kombinasyonun testte de artı kalması gerekir; aksi hâlde sonuç çoklu deneme (seçim) gürültüsüdür. 3551040 denemeden şans eseri de artı çıkanlar olur.
- İz süren stop bir önceki mumun tepesinden; aynı mumda stop ve hedef görülürse stop. 1 dk mumlarda boşluk varsa pencere zaman değil mum sayar.
