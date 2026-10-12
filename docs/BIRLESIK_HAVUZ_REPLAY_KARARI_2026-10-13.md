# Birleşik Havuz Replay — Aşama B Kararı (2026-10-13)

**ARAŞTIRMA — canlıya alınmadı, üretim davranışı değişmedi.**

## Soru
"Tüm motorlardan beslenen tek havuz + ortak karar kapısı" (birleşik sistem), mevcut
radar-tek-başına yaklaşımından **daha iyi mi?** Canlıya almadan önce replay ile ölçüldü.

## Yöntem
`backend/scripts/unified_pool_replay.py` — 5.909 `passes=true` aday (15 gün) + 5m fiyat
(118 sembol). İki akış AYNI simülatörle (TP/SL%3/ufuk-sonu, SL-önce kötümser) ölçüldü:
- **MEVCUT:** tüm passes adayları.
- **BİRLEŞİK:** ortak-karar vekili = *çok-kaynak teyidi* (aynı sembol ±15 dk'da ≥2 kez
  işaretlenmiş). `master_surge` composite/confluence canlı `_SNAPSHOT` olduğu için
  tarihsel yeniden üretilemez → confluence kavramının dürüst tarihsel vekili budur.

Walk-forward (ilk %60 / son %40), gün-gün, 3-fold, eşleştirilmiş t-testi, yoğunlaşma.

## Sonuçlar (sınav kümesi)
| Akış | n | Taker EV | Maker EV | Kazanma | Payoff |
|---|---|---|---|---|---|
| Mevcut (radar) | 2364 | −0.459% | −0.209% | 37.2% | 0.82 |
| **Birleşik (ortak karar)** | 2328 | **−0.456%** | **−0.206%** | 37.4% | 0.82 |

- **Eşleştirilmiş t (birleşik − mevcut) = 0.06** → fark İSTATİSTİKSEL OLARAK SIFIR.
- Birleşik 3-fold: **−0.62 / −0.38 / −0.37** (kararlı negatif).
- Gün-gün pozitif: **1/4**. Sembol yoğunlaşması: %18 (yüksek).

## KARAR
**EŞİĞİ GEÇMEDİ.** Birleşik havuz + ortak karar kapısı, kârlılığı **ölçülebilir biçimde
değiştirmiyor** (ΔEV ≈ 0.003 puan, t=0.06). Her iki akış da negatif, kararlı negatif.

**Neden:** Sorun sinyallerin *birleştirilmesi* değil, sinyalin *kendisi*. 8 tur ölçümde
(brüt edge ≈ maliyet) tutarlı çıkan tablo burada da aynı: adayları nasıl gruplarsak
gruplayalım, ham bilgi içeriği maliyetin altında. Birleştirme **mimari** olarak değerli
(çift tarama biter, tek kanal) ama **edge yaratmıyor.**

## Sonuç: Aşama C (canlıya alma) YAPILMADI
Senin kuralın gereği ("backtest geçmeden canlıya alma") birleşik sistem **canlıya
alınmadı.** A1 (rising_pool) + A2 (pool_learning) kodu yazıldı ve test edildi, ama
`UNIFIED_POOL_ENABLED` **varsayılan kapalı** → üretim davranışı birebir aynı.

## Ne yapılabilir (kullanıcı kararı)
1. **Mimari birleştirmeyi yine de al** (edge için değil, tek-kanal/temizlik için):
   `UNIFIED_POOL_ENABLED=true` → çift tarama biter, push+WhatsApp aynı havuzdan.
   Kârlılık değişmez.
2. **Birleştirmeyi de kapat** — kod durur (bayrak kapalı), ileride fikir değişirse açılır.
3. **Farklı eksen** — edge için gerçek yeni bilgi sınıfı (8 turda denendi: hiçbiri geçmedi).

## Yeniden üretim
```
python backend/scripts/unified_pool_replay.py --days 15
```
Rapor: `work/unified_pool_replay.json`.
