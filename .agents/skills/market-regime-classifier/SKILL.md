---
name: market-regime-classifier
description: Piyasa mikro-yapısını Trend Genişlemesi (Trending), Testere/Yatay (Choppy/Range) veya Panik Çöküşü rejimlerine sınıflandırarak trade parametrelerini optimize eden LLM becerisi.
---

# Piyasa Rejimi Teşhisi (Market Regime Classifier)

Bir scalper sisteminin başarısı, uygulanan politikanın o anki piyasa rejimine uygunluğuna bağlıdır.

## 1. Rejim Sınıfları

1. **TREND_EXPANSION (Trend Genişlemesi / Güçlü Boğa):**
   - **Özellikler:** Bollinger Bantları açılıyor (genişleme), ADX > 25, EMA 9 > 21 > 50 sıralı, MTF MACD yeşil.
   - **Politika:** Trailing stop gevşek bırakılır (%0.8 - %1.2 gap), TP hedefleri yukarı çekilir (%3.0+), küçük geri çekilmelere izin verilir.

2. **CHOPPY_RANGE (Testere / Yatay Aralık):**
   - **Özellikler:** Bollinger Bantları sıkışık veya yatay, ADX < 20, fiyat EMA'ların etrafında dans ediyor.
   - **Politika:** Asla runner aranmaz. Hızlı vur-kaç (scalp) uygulanır. Hedef +%1.2 - +%1.5, kâr kilidi anında devreye sokulur, trailing dar tutulur (%0.4 - %0.5).

3. **MACRO_PANIC_DUMP (Piyasa Çöküşü / BTC Dump):**
   - **Özellikler:** BTC sert düşüyor, altcoinlerde panik satışları var.
   - **Politika:** **TAM TIKANMA (BUY_BLOCKED)**. Hiçbir sinyale, skoru ne kadar yüksek olursa olsun girilmez.
