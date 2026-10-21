# H4 MA kesişimi araması — 90 gün, uzun tutma ve büyük hedef (2026-10-21 15:17)

Evren: canlı sistem mantığı (ilk 50 yükselen + saatlik aktivite; 310 TRY çifti). Dilim H4 (15m arşivinden). Eğitim ilk 60 gün, test son 30 gün. Maliyet 0.275%. Sembol başına tek pozisyon. Eşik: n eğitim ≥ 30, n test ≥ 12 (H4 sinyali seyrek).

Denenen: 18 giriş seti (3932 ham H4 sinyali) × 240 çıkış kombinasyonu × 137 filtre = 336960 geçerli deneme; 146760 tanesi eğitimde artı.

## İki dönemde de ≥ +2% olanlar

| MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| 8/34/89 | mid_slow | 10 | 8 | 4320 | yok | gövde≥1% | 41 | +3.08% | 63% | 14 | +3.03% | 57% |
| 8/34/89 | mid_slow | 10 | 8 | 4320 | yok | ADX>20 + gövde≥1% | 39 | +3.32% | 64% | 14 | +3.03% | 57% |
| 8/34/89 | mid_slow | 10 | 8 | 4320 | yok | gövde≥0.3% + gövde≥1% | 41 | +3.08% | 63% | 14 | +3.03% | 57% |
| 8/34/89 | mid_slow | 10 | 8 | 4320 | yok | gövde≥1% + ATR14≥0.6% | 41 | +3.08% | 63% | 14 | +3.03% | 57% |
| 8/34/89 | mid_slow | 10 | 8 | 4320 | yok | gövde≥1% + MACD hist artıyor | 40 | +2.91% | 62% | 14 | +3.03% | 57% |
| 8/34/89 | mid_slow | 10 | 8 | 1440 | yok | ADX>20 + gövde≥1% | 39 | +2.84% | 64% | 14 | +2.84% | 71% |
| 8/34/89 | mid_slow | 10 | 8 | 4320 | yok | gövde≥0.3% + MACD hist artıyor | 42 | +2.82% | 62% | 15 | +3.17% | 60% |
| 8/34/89 | mid_slow | 10 | 8 | 4320 | yok | gövde≥0.3% | 46 | +2.82% | 61% | 16 | +2.82% | 56% |
| 8/34/89 | mid_slow | 10 | 8 | 4320 | yok | gövde≥0.3% + ATR14≥0.6% | 46 | +2.82% | 61% | 16 | +2.82% | 56% |
| 8/34/89 | mid_slow | 10 | 8 | 4320 | yok | ADX>20 + gövde≥0.3% | 44 | +3.02% | 61% | 15 | +2.66% | 53% |
| 8/34/89 | mid_slow | 10 | 8 | 2880 | yok | ADX>20 + gövde≥0.3% | 44 | +3.04% | 66% | 15 | +2.64% | 60% |
| 8/34/89 | mid_slow | 10 | 8 | 2880 | yok | gövde≥1% | 41 | +2.93% | 66% | 14 | +2.59% | 57% |
| 8/34/89 | mid_slow | 10 | 8 | 2880 | yok | ADX>20 + gövde≥1% | 39 | +3.25% | 67% | 14 | +2.59% | 57% |
| 8/34/89 | mid_slow | 10 | 8 | 2880 | yok | gövde≥0.3% + gövde≥1% | 41 | +2.93% | 66% | 14 | +2.59% | 57% |
| 8/34/89 | mid_slow | 10 | 8 | 2880 | yok | gövde≥1% + MACD hist artıyor | 40 | +2.76% | 65% | 14 | +2.59% | 57% |
| 8/34/89 | mid_slow | 10 | 8 | 2880 | yok | gövde≥1% + ATR14≥0.6% | 41 | +2.93% | 66% | 14 | +2.59% | 57% |
| 8/34/89 | mid_slow | 10 | 8 | 1440 | yok | gövde≥1% | 41 | +2.59% | 63% | 14 | +2.84% | 71% |
| 8/34/89 | mid_slow | 10 | 8 | 1440 | yok | gövde≥0.3% + gövde≥1% | 41 | +2.59% | 63% | 14 | +2.84% | 71% |
| 8/34/89 | mid_slow | 10 | 8 | 1440 | yok | gövde≥1% + ATR14≥0.6% | 41 | +2.59% | 63% | 14 | +2.84% | 71% |
| 8/34/89 | mid_slow | 10 | 8 | 4320 | yok | MACD hist artıyor | 52 | +2.69% | 60% | 16 | +2.45% | 56% |

## Hem eğitimde hem testte artı olanlar (min(eğitim, test))

| MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| 8/34/89 | mid_slow | 10 | 8 | 4320 | yok | gövde≥1% | 41 | +3.08% | 63% | 14 | +3.03% | 57% |
| 8/34/89 | mid_slow | 10 | 8 | 4320 | yok | ADX>20 + gövde≥1% | 39 | +3.32% | 64% | 14 | +3.03% | 57% |
| 8/34/89 | mid_slow | 10 | 8 | 4320 | yok | gövde≥0.3% + gövde≥1% | 41 | +3.08% | 63% | 14 | +3.03% | 57% |
| 8/34/89 | mid_slow | 10 | 8 | 4320 | yok | gövde≥1% + ATR14≥0.6% | 41 | +3.08% | 63% | 14 | +3.03% | 57% |
| 8/34/89 | mid_slow | 10 | 8 | 4320 | yok | gövde≥1% + MACD hist artıyor | 40 | +2.91% | 62% | 14 | +3.03% | 57% |
| 8/34/89 | mid_slow | 10 | 8 | 1440 | yok | ADX>20 + gövde≥1% | 39 | +2.84% | 64% | 14 | +2.84% | 71% |
| 8/34/89 | mid_slow | 10 | 8 | 4320 | yok | gövde≥0.3% + MACD hist artıyor | 42 | +2.82% | 62% | 15 | +3.17% | 60% |
| 8/34/89 | mid_slow | 10 | 8 | 4320 | yok | gövde≥0.3% | 46 | +2.82% | 61% | 16 | +2.82% | 56% |
| 8/34/89 | mid_slow | 10 | 8 | 4320 | yok | gövde≥0.3% + ATR14≥0.6% | 46 | +2.82% | 61% | 16 | +2.82% | 56% |
| 8/34/89 | mid_slow | 10 | 8 | 4320 | yok | ADX>20 + gövde≥0.3% | 44 | +3.02% | 61% | 15 | +2.66% | 53% |
| 8/34/89 | mid_slow | 10 | 8 | 2880 | yok | ADX>20 + gövde≥0.3% | 44 | +3.04% | 66% | 15 | +2.64% | 60% |
| 8/34/89 | mid_slow | 10 | 8 | 2880 | yok | gövde≥1% | 41 | +2.93% | 66% | 14 | +2.59% | 57% |
| 8/34/89 | mid_slow | 10 | 8 | 2880 | yok | ADX>20 + gövde≥1% | 39 | +3.25% | 67% | 14 | +2.59% | 57% |
| 8/34/89 | mid_slow | 10 | 8 | 2880 | yok | gövde≥0.3% + gövde≥1% | 41 | +2.93% | 66% | 14 | +2.59% | 57% |
| 8/34/89 | mid_slow | 10 | 8 | 2880 | yok | gövde≥1% + MACD hist artıyor | 40 | +2.76% | 65% | 14 | +2.59% | 57% |
| 8/34/89 | mid_slow | 10 | 8 | 2880 | yok | gövde≥1% + ATR14≥0.6% | 41 | +2.93% | 66% | 14 | +2.59% | 57% |
| 8/34/89 | mid_slow | 10 | 8 | 1440 | yok | gövde≥1% | 41 | +2.59% | 63% | 14 | +2.84% | 71% |
| 8/34/89 | mid_slow | 10 | 8 | 1440 | yok | gövde≥0.3% + gövde≥1% | 41 | +2.59% | 63% | 14 | +2.84% | 71% |
| 8/34/89 | mid_slow | 10 | 8 | 1440 | yok | gövde≥1% + ATR14≥0.6% | 41 | +2.59% | 63% | 14 | +2.84% | 71% |
| 8/34/89 | mid_slow | 10 | 8 | 4320 | yok | MACD hist artıyor | 52 | +2.69% | 60% | 16 | +2.45% | 56% |
| 8/34/89 | mid_slow | 10 | 8 | 4320 | yok | MACD hist artıyor + ATR14≥0.6% | 52 | +2.69% | 60% | 16 | +2.45% | 56% |
| 8/34/89 | mid_slow | 10 | 5 | 2880 | yok | ADX>20 + gövde≥1% | 39 | +2.65% | 54% | 14 | +2.44% | 50% |
| 8/34/89 | mid_slow | 10 | 5 | 2880 | yok | gövde≥1% | 41 | +2.43% | 54% | 14 | +2.44% | 50% |
| 8/34/89 | mid_slow | 10 | 5 | 2880 | yok | gövde≥0.3% + gövde≥1% | 41 | +2.43% | 54% | 14 | +2.44% | 50% |
| 8/34/89 | mid_slow | 10 | 5 | 2880 | yok | gövde≥1% + ATR14≥0.6% | 41 | +2.43% | 54% | 14 | +2.44% | 50% |

## Eğitimde en iyi 15

| MA | Kural | Hedef% | Stop% | Tutma dk | İz süren | Filtre | n eğitim | Ort. net eğitim | Kazanan | n test | Ort. net test | Kazanan |
|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| 7/20/99 | mid_slow | 10 | 8 | 4320 | yok | ADX>25 + saat 09–23 | 34 | +4.37% | 68% | 12 | -3.77% | 25% |
| 10/30/100 | fast_mid | 10 | 8 | 4320 | yok | RSI<70 + gövde≥1% | 49 | +4.35% | 69% | 35 | -3.87% | 20% |
| 7/20/99 | mid_slow | 8 | 8 | 4320 | yok | ADX>25 + saat 09–23 | 34 | +4.18% | 74% | 12 | -4.27% | 25% |
| 10/30/100 | fast_mid | 10 | 8 | 4320 | yok | RSI<70 + hacim≥2× | 51 | +4.17% | 71% | 47 | -2.21% | 32% |
| 7/20/99 | mid_slow | 10 | 8 | 2880 | yok | ADX>25 + saat 09–23 | 34 | +4.04% | 65% | 12 | -3.77% | 25% |
| 7/20/99 | mid_slow | 8 | 8 | 4320 | yok | yavaş MA yükseliyor | 37 | +3.93% | 76% | 17 | -3.57% | 29% |
| 7/20/99 | mid_slow | 8 | 8 | 4320 | yok | yavaş MA yükseliyor + ATR14≥0.6% | 37 | +3.93% | 76% | 17 | -3.57% | 29% |
| 7/20/99 | fast_mid | 10 | 8 | 4320 | yok | StochRSI≤80 + RSI 45–65 | 38 | +3.92% | 68% | 32 | -1.75% | 34% |
| 7/20/99 | mid_slow | 8 | 8 | 2880 | yok | ADX>25 + saat 09–23 | 34 | +3.92% | 74% | 12 | -4.27% | 25% |
| 7/20/99 | mid_slow | 8 | 8 | 2880 | yok | ADX>25 + hacim≥1.5× | 34 | +3.90% | 74% | 12 | -4.27% | 25% |
| 7/20/99 | ribbon | 8 | 8 | 4320 | yok | RSI 45–65 + gövde≥0.3% | 32 | +3.84% | 72% | 41 | -0.66% | 44% |
| 7/20/99 | mid_slow | 8 | 8 | 4320 | yok | ADX>20 + yavaş MA yükseliyor | 35 | +3.83% | 74% | 13 | -4.58% | 23% |
| 7/20/99 | mid_slow | 8 | 8 | 4320 | yok | ADX>25 | 43 | +3.83% | 72% | 14 | -2.56% | 36% |
| 7/20/99 | mid_slow | 8 | 8 | 4320 | yok | ADX>20 + ADX>25 | 43 | +3.83% | 72% | 14 | -2.56% | 36% |
| 7/20/99 | mid_slow | 8 | 8 | 4320 | yok | ADX>25 + ATR14≥0.6% | 43 | +3.83% | 72% | 14 | -2.56% | 36% |

## Okuma

- 336960 denemenin eğitim ortalaması medyanı -0.07%, en iyi +4.37%.
- H4'te sinyal sayısı az; +%2 üstü görünen sonuçların n'i küçükse şans payı büyüktür. Komşu varyantları da artı olan kümeye bakın.
- Tutma 1–3 gün olduğunda sonuç TF kuralından çok piyasa yönüne bağlıdır (90 günün ilk 60 ve son 30 gününün rejimi farklı olabilir).
