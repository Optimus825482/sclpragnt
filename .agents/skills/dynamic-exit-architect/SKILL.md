---
name: dynamic-exit-architect
description: Kripto scalping işlemlerinde ufak geri çekilmelerde erken stop olmayı engelleyen, volatiliteye uyarlanabilir nefes alma alanı, dinamik TP ve kâr takip (trailing) mimarisi sunan LLM becerisi.
---

# Dinamik Pozisyon & Çıkış Mimarı (Dynamic Exit Architect)

Bu beceri, sabit kural bazlı çıkışların en büyük iki handikabını çözer:
1. Ufak ve normal geri çekilmelerde erken stop olup arkasından gelen büyük yükselişi kaçırmak.
2. Trailing stop'u çok dar tutarak kârı erken bırakmak veya çok geç tutarak tepe kârı geri vermek.

## 1. Çıkış Politikası İlkeleri

1. **Volatiliteye Göre Nefes Alma Alanı (ATR-Adaptive Breathing Room):**
   - Sabit %1.5 stop yerine, sembolün 5 dakikalık ATR oranına (`atr_pct`) göre stop belirlenir:
     - Düşük volatilite (ATR < %0.8): Stop = Giriş - %1.2 (Sıkı koruma)
     - Yüksek volatilite (ATR > %1.5): Stop = Giriş - (ATR × 1.1) (Gürültüde erken stop olmayı önler, tavan -%2.5)

2. **Dinamik Take-Profit (TP) Yönetimi:**
   - Önceden belirlenen tek bir sabit hedef yerine 2 kademeli hedefleme uygulanır:
     - **TP1 (Scalp / Risk Azaltma):** Giriş + %1.2 - %1.8 aralığında kâr kilidi (breakeven stop'u maliyet üstüne çeker).
     - **TP2 (Runner / Koşucu Hedefi):** Güçlü momentumda TP kaldırılmaz; üst direnç havuzuna (+%3.5 - %6.0) çekilir.

3. **Momentum Tükenişinde Erken Çıkış (Exhaustion Exit):**
   - Fiyat henüz TP hedefine varmamış olsa dahi, eğer 1m/5m'de RSI > 80'den aşağı kesmişse ve agresif satış blokları başlamışsa: *"Hedefe kadar bekleme, anlık kârı (%1.5+) realize et"* kuralı uygulanır.

4. **Kademeli Kâr Kilidi (Profit Ratchet):**
   - Kâr +%1.0'a ulaştığında stop kesinlikle maliyet + komisyon seviyesine (`net_floor`) taşınır.
   - Kâr arttıkça trailing mesafesi zirveden geriye doğru dinamik olarak daraltılır.
