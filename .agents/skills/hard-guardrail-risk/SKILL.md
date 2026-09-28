---
name: hard-guardrail-risk
description: LLM'in zarar kabullenememe veya stop kaldırma yanılgısına düşmesini engelleyen, çelik sermaye koruma ve risk disiplini becerisi.
---

# Çelik Risk Disiplini (Hard Guardrail Risk)

Yapay zeka modelleri bazen "fiyat nasılsa buradan döner" diyerek pozisyonu taşımak isteyebilir. Bu beceri, deterministik çelik risk sınırlarını belirler.

## 1. Asla Çiğnenemez Kurallar

1. **Stop Asla Kaldırılamaz:**
   - Model stop'u kâr yönünde (yukarı) serbestçe taşıyabilir; ancak giriş fiyatının %2.5–%3.0'ünden daha aşağıya stop çekemez veya stop'u kaldıramaz.
   
2. **Maliyet Tabanı Güvencesi (Net Floor):**
   - Kâr %1.0'ı gördükten sonra stop seviyesi giriş fiyatı + gidiş-dönüş komisyonu (%0.30) + kayma payının altına asla düşürülemez.

3. **Maksimum Açık Kalma Süresi (Max Hold Duration):**
   - Scalping momentumu 30–45 dakika içinde gerçekleşmelidir. 60 dakikayı aşan ve kâr üretmeyen pozisyonlar sermaye kilitlenmesini önlemek için kapatılmalıdır.

4. **Devre Kesici (Circuit Breaker):**
   - Bir sembolde peş peşe 2 stop yaşandıysa en az 30 dakika o sembolden uzak durulur (`cooldown`).
