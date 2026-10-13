# Katmanlı Ağırlıklı Puanlama — Replay Kararı (2026-10-13)

**ARAŞTIRMA — canlıya alınmadı.**

## Soru
Birleştirme planında **katmanlı/ağırlıklı bir puanlama** kurup aday seçimini
iyileştirebilir miyiz? (mevcut 3 ayrı puanlama yerine tek, ağırlıklı skor)

## Yöntem
`rising_pool.score_candidate` — 4 katman, 0-1 normalize, ağırlıklı toplam → 0-100:
- **L1 GÜÇ** (ağırlık 0.35): velocity panel skoru
- **L2 MUTABAKAT** (0.30): füzyon kaynak sayısı + master_surge confluence katmanı
- **L3 TREND** (0.20): `ret3_pct` pozitif/anlamlı (fiyat gerçekten yukarı mı)
- **L4 LİKİDİTE** (0.15): ATR/hacim uyumu (ince/oynak tahtayı cezalandır)

Replay: 5.909 aday (15 gün), walk-forward eşik (eğitimde üst %50 → sınavda uygula).

## Sonuçlar (sınav kümesi, taker %0.35)
| Akış | n | EV | Kazanma | Payoff | 3-fold |
|---|---|---|---|---|---|
| Mevcut (tüm adaylar) | 2364 | −0.459 | 37.2% | 0.82 | — |
| Birleşik (confluence kapı) | 2328 | −0.456 | 37.4% | 0.82 | kararlı neg |
| **Skor-top-N (yüksek skor %50)** | 1261 | **−0.550** | 35.7% | 0.78 | −0.91/−0.34/−0.40 |
| **Düşük skor %50** | 1103 | **−0.355** | — | — | — |

- **paired t (skor-top vs mevcut) = −1.6** → yüksek skoru seçmek **daha KÖTÜ**.
- **Skor TERS çalışıyor:** düşük-skor yarısı (−0.355) yüksek-skor yarısından (−0.55) iyi.
- `ret3` tek başına: yüksek −0.483 vs düşük −0.43 (trend katmanı da zararlı).

## KARAR
**EŞİĞİ GEÇMEDİ — daha da kötü.** Katmanlı ağırlıklı skor, aday seçimini iyileştirmedi;
**kötüleştirdi**. Yüksek skorlu yarı mevcut popülasyondan −0.09 puan daha kötü.

**Neden:** Güç+trend katmanları, "hareket **zaten olmuş**" adayları öne çıkarıyor
(momentum-chasing). Bu adayların geri çekilmesi daha büyük → EV düşüyor. Düşük-skor
yarısının (henüz hareket etmemiş) daha iyi olması bunu doğruluyor — ama o bile negatif.

Bu, 9. kez aynı kök nedeni doğruluyor: **mevcut aday uzayında skorlamayla seçim edge
yaratmıyor**; ham bilgi içeriği maliyetin altında. Skorlamayı tersine çevirmek de kâra
çevirmiyor (−0.355 hâlâ negatif).

## Aşama C (canlıya alma) YAPILMADI
Birleşik sistem + katmanlı skor canlıya alınmadı. `rising_pool.score_candidate` kodu
durur (test edildi, bayrak kapalı); ileride farklı bir sinyal sınıfıyla denenebilir.

## Yeniden üretim
```
python backend/scripts/unified_pool_replay.py --days 15
```
Rapor: `work/unified_pool_replay.json`.
