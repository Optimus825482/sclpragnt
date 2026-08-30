---
name: pump24-research-findings-2026-08-31
description: Pump araştırması nihai bulgular — veri bugı, OOS, grid (pozitif EV
  yok), v2 filtre (doğrulandı), kesişim (izleme listesi)
metadata:
  node_type: memory
  type: project
  originSessionId: sess_591bbf4e-19bf-4f0e-ad51-8822844ec025
---

2026-08-30/31 pump24 araştırmasının tam özeti. Tüm pipeline `backend/scripts/pump24/`; raporlar repo kökünde `pump24_*.json` (10 dosya); bu özet [[pump24-pattern-research-2026-08-30]] dosyasının güncel/kesin hali — çelişki olursa bu geçerli. DB: `research_runs` id=6,8,9,10,11 + 3 pattern kaydı.

**Altyapı:** `features.py` (nedenli seri göstergeler, app formülleriyle birebir; smoke test RSI/ATR/ADX 1e-6 eşleşme) · `smc.py` (frame builder + M1 boşluk doldurma `fill_m1_gaps` + normalize MACD/AO/OBV) · `data.py` (Binance TR fetch + PG upsert; OKX repair hazır) · `events.py` (≥%2 M5 pump + 13 grup snapshot: m5_g0/g1/g2 + m1_g0..g9) · `patterns.py` (eşik kural madenciliği, `FIELD_THRESHOLDS` alan ölçekli) · `run.py` (fetch|events|patterns|backtest|smoke) · `oos.py` (fetch7d|oos) · `early.py` · `grid.py` · `intersection.py` · `filter_v2_test.py`.

**KRİTİK ders — veri bütünlüğü:** İlk `normalize_binance` Binance kline sütunlarını kaydırıyordu (row[0]=open_time→open). 213.574 bozuk satır; OHL mantık kontrolü (`high<low`) ile teşhis. Silindi, 7d yeniden çekildi, TÜM sonuçlar baştan hesaplandı. Yeni veri parselleri mutlaka OHLC tutarlılık assert'i içermeli. İlk candidate `pump24_volatility_confluence` bu yüzden `invalid_data`.

**Tanımlar:** pump = M5 kapanış_i/kapanış_(i-1)−1 ≥ %2 (m5_g0 = yükseliş başlangıç mumu). Dokunuş = sonraki N M5 barda high ≥ hedef (MFE tarzı). EV = düz N-bar tutma getiri − maliyet; yarış EV = hedef/stop yarışı. Taker maliyet %0,35 gidiş-dönüş (config: komisyon 0,15×2 + kayma 0,025×2), maker %0,15.

**5 kanıtlanmış bulgu (temiz veri, 50 sembol):**
1. **Sinyal gerçek + OOS stabil:** train(6g,185 olay)→test(1g,54 olay) fee-target düşüşü ~1 puan. `m5g0_atr_pct>1.5` OOS %70,8 vs taban %13,65; `m5g0_ema_gap_pct>2` raw %69,9.
2. **Erken giriş YOK:** M1/önceki-M5 göstergeleriyle karar mumu AÇILIŞINDAN giriş EV lift +0,01–0,02 pt (early.py). Kullanıcının "son 10 M1 mumunda işaret" hipotezinin cevabı: önceden öngörü yok, sinyal ilk pump M5 mumu içinde.
3. **Izgara: pozitif EV yok:** 8 kural × 240 hücre (6 hedef × 5 stop × 2 ufuk × 2 giriş × 2 maliyet) — train'de hiçbir hücre pozitif değil (en iyi −0,086%). Dar stop %82–85 stop oranıyla pump gürültüsüne yeniliyor; testte pozitife geçen 2 hücre train'de negatifti → gürültü. `pump24_no_positive_ev_close_entry` (rejected_for_trading, 0,75).
4. **v2 filtre: doğrulandı (izleme):** ATR%≥0,3 · BB genişlik≥2,5% · RSI≥60/≤35 · MFI 10–90 · LinReg eğim≥0,2%/bar veya Aroon≥50 → test OOS geçenlerde 3-bar +0,95 dokunuş **%40,4 vs taban %14,4** (+26pp); avg MFE3 2,7× taban; train→test güç ARTTI. Trend kolu taşır (n=936, %41,0); V-dönüş zayıf+küçük (n=40). `pump24_filter_v2_watchlist` (validated_as_filter, 0,7). Not: UI kalibrasyonu (%19) farklı isabet tanımı kullanıyor olabilir — hizalanmalı.
5. **Kesişim v2×pump: izleme listesi kesin, EV yok:** test günü parlak görünmüştü (v2+ema_gap>2 EV +0,60%) ama gün-bazlı analiz: hafta toplam EV(maker) +0,034% (sıfır), 3/7 gün pozitif; dokunuş %55–70 gün-bazlı STABİL (taban %12–25). Chop günlerinde getiri −0,5..−0,9%, trend günlerinde +0,5..+0,8% → rejim bağımlılığı. `pump24_v2_x_pump_watchlist` (validated_as_filter, 0,7).

**Canlı kullanım kararı:** Aday tarama = `v2 VE (ema_gap>2 veya ATR≥1,5)` → günlük ~85–165 sinyal barı, bunların %55–70'i 15 dk'da +0,95'e dokunur (3–4× sıkılaştırma). Giriş kararı ayrı katmana (ScalpAnalyzer/LLM) bırakılmalı. Açık sonraki adım: rejim filtresi (chop/trend ayrımı — chop_index/ADX) ile 4 negatif günü ayıklayıp EV'yi pozitife taşıma denemesi; ve 30+ gün veriyle maker-fill modeli.

**Teknik notlar:** psycopg3'te `mogrify` yok → `executemany`. Fiyat-ölçekli göstergeler (MACD/AO/OBV) semboller arası eşikte yüzde-normalize kullan (`macd_hist_pct` vb.). Binance TR M1'de işlem olmayan dakikalarda mum üretilmez → frame builder boşluk dolduruyor. Binance TR kline API ~8 gün 1m geçmiş tutar; daha gerisi OKX'ten. UI'daki "kalibrasyon" isabet tanımı ile MFE-tanımı hizalanmadan kalibrasyon döngüsü yanlış yönü düzeltir.
