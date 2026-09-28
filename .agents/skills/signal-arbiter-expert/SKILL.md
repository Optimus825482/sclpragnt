---
name: signal-arbiter-expert
description: Scalper yükseliş ve kırılım sinyallerini hacim-fiyat uyumsuzluğu, CVD, emir defteri dengesizliği ve boğa tuzağı risklerine karşı denetleyen LLM hakemlik becerisi.
---

# Sinyal Hakemi & Tuzak Dedektörü (Signal Arbiter Expert)

Bu beceri, kural motorunun (Radar / MACD / Master Surge) ürettiği yükseliş sinyallerini derinlemesine inceleyerek **"GERÇEK MOMENTUM (DEVAM)"** veya **"BOĞA TUZAĞI (FAKE)"** ayrımını yapar.

## 1. Analiz Kanıtları ve Tartım Kuralları

1. **Kümülatif Hacim Deltası (CVD) Uyumsuzluğu:**
   - Fiyat yeni tepe yaparken veya direnç kırarken CVD (taker buy - taker sell) negatif kalıyorsa veya düşüyorsa: **%90 İhtimalle BOĞA TUZAĞI (FAKE)**.
   - Fiyat kırılımıyla birlikte güçlü agresif alıcı akışı (CVD spike) varsa: **GÜÇLÜ TEYİT (DEVAM)**.

2. **Direnç İğnesi ve Üst Fitil (Rejection Wicks):**
   - 1m/5m mumlarda gövdeden 2 kat uzun üst fitil varsa, satıcılar tepeyi savunuyordur. Direnç seviyesinde oluşan bu iğnelerden sonra işleme girilmez.

3. **Emir Defteri ve Likidite Duvarları:**
   - Ask (satış) tarafında sahte kalın duvarlar (spoofing) ve Bid (alış) tarafında zayıf derinlik varsa, breakout sonrası fiyat anında çökebilir.
   - Spread > %0.30 ise veya 24s hacim sığsa kayma maliyeti kazancı yok eder.

4. **Vadeli / Türev Baskısı (Derivatives & Funding):**
   - Fonlama oranı aşırı şişmişse (`EXTREME_LONG`), açık faiz (Open Interest) zirvedeyken fiyat teklemeye başladıysa likidasyon kaskadı riski çok yüksektir. Karar: `FAKE` veya `YÜKSEK_RİSK`.

## 2. Karar Çıktı Standardı

Hakemlik sonucunda şu standart kararlar üretilir:
- **DEVAM:** Hacim, derinlik, CVD ve MTF trend uyumlu; sahte kırılım riski düşük. (Güven: %75–%98)
- **FAKE:** Hacim desteği yok, dirençten ret yedi, CVD negatif veya aşırı fonlama riski var. (Güven: %80–%99)
- **BELIRSIZ:** Kanıtlar yetersiz, veri bayat veya teyitler çelişkili.
