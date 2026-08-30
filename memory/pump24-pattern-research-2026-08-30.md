---
name: pump24-pattern-research-2026-08-30
description: 24h ≥%2 M5 pump desen araştırması — pump24 paketi, en iyi desen
  (ATR+AO konfluans) acc %75.4, recall %55.8
metadata:
  node_type: memory
  type: project
  originSessionId: sess_591bbf4e-19bf-4f0e-ad51-8822844ec025
---

2026-08-30: `backend/scripts/pump24/` paketi kuruldu (features/smc/data/events/patterns/run). 50 sembol × 24h M5+M1 klines `historical_candles`'a upsert edildi; ≥%2 M5 kapanış-kapanış pump'ları tespit edilip `historical_feature_snapshots`'a nedenli (sadece kapanmış mum) 13 grup snapshot'ı yazıldı (m5_g0/g1/g2 + m1_g0..g9, g0 = yükselişe en yakın mum). 251 kural madencilendi, 11.150 bar üzerinde backtest: baseline (sonraki 3 M5 barda high≥giriş*1.01) %12.59; en iyi AND-kombo `m5g0_atr_pct>1.5 AND m1g0_atr_pct>0.6 AND m5g0_awesome_pct>1.0` → acc %75.4 (n=354, lift +62.8), pump recall %55.8. Tekil en iyi: m5g0_atr_pct>1.5 → %68.4 / recall %81.4. Rapor: `pump24_desen_raporu.json` (repo kökü), DB: research_runs id=6 + research_patterns 'pump24_volatility_confluence' (status=candidate, confidence 0.6).

**Notlar:** Binance TR M1'de işlem olmayan dakikalarda mum üretilmez → `smc.fill_m1_gaps` flat doldurma şart. OKX public API eski M1 onarımı için (`data.fetch_okx_klines`) hazır ama bu pencerede gerekmedi. psycopg3'te `mogrify` yok → `executemany` kullan. Eşikler alan ölçeğine göre (`patterns.FIELD_THRESHOLDS`); fiyat-ölçekli alanlar (MACD/AO) yüzde-normalize (`macd_hist_pct` vb.). Pipeline komutları: `venv/Scripts/python.exe -m pump24.run fetch|events|patterns|backtest|smoke 24` (backend/scripts cwd). Sonraki adım: çoklu günlük OOS doğrulaması + fee-aware giriş simülasyonu.


## 2026-08-30 Güncellemesi: OOS + Fee Sim (sonraki adım tamamlandı)

**KRİTİK veri bugı bulundu ve düzeltildi:** `pump24/data.normalize_binance` Binance kline sütunlarını kaydırıyordu (row[0]=open_time open'a yazılıyordu) → 213.574 bozuk satır silindi, 7d veri yeniden çekildi, **tüm önceki sonuçlar geçersizdi**; eski `pump24_volatility_confluence` candidate'ı `invalid_data` yapıldı. Temiz veri sonucu DB'de `pump24_continuation_signal` (candidate, 0.55, research_runs id=8).

**Temiz veriyle net bulgular (rapor: `pump24_oos_sim_raporu.json`):**
1. **Sinyal gerçek + OOS stabil:** train %74,2 → test %73,5 fee-target; `m5g0_atr_pct>1.5` OOS %70,8 vs taban %13,65. `m5g0_ema_gap_pct>2` test raw %69,9.
2. **Erken giriş YOK:** M1/önceki-M5 göstergeleriyle karar mumu AÇILIŞINDAN giriş EV lift +0,01..0,02 pt → pump öncesi öngörü yok, sinyal ilk pump M5 mumu içinde beliriyor. `pump24/early.py`.
3. **Taker maliyetle dar hedefte EV≈0:** raced sim (+0,6 net / −1,5 stop / 3 bar) tüm kurallarda negatif; en iyi test EV −0,07% (maker_both). Stop asimetrisi avantajı yiyor.
4. **Para MFE'de:** `ema_gap>2` test MFE medyan +1,96%, %52,6 ≥+1,85 → sonraki adım: hedef/stop izgarası optimizasyonu (hedef ~p75 +2,3, stop −1,0, maker giriş) + 30+ gün OOS.

Yeni modüller: `pump24/oos.py` (fetch7d|oos), `pump24/early.py` (early). Smoke test OHLC tutarlılığı da kontrol etmeli (high<low = sütun kayması belirtisi).


## 2026-08-31: Target/Stop Izgara Taraması (SONUÇ: negatif)

`pump24/grid.py`: 8 aday kural × 240 hücre (6 hedef × 5 stop × 2 ufuk × 2 giriş × 2 maliyet). Train (6g) penceresinde **hiçbir hücre pozitif EV üretmedi** (en iyi −0,086%). OOS aynı-hücre kontrolü: testte 2 hücre pozitife geçti ama train'de negatiftiler → seçim gürültüsü. Nedenler: dar stop (0,5) %82-85 stop oranıyla pump gürültüsüne yeniliyor; geniş stop + maliyet de asimetriyi kapatıyor. Sinyalin istatistiksel gücü (OOS fee-target %70,8; MFE medyan +1,96%) yol-riski + maliyet karşısında yetersiz. Rapor: `pump24_grid_sonuc_raporu.json`; DB: research_runs id=9 + `pump24_no_positive_ev_close_entry` (status=rejected_for_trading, conf 0.75). **Karar:** sinyal otonom giriş olarak kullanılmaz; izleme/filtre değeri taşıyabilir. Pozitif EV için tek teorik pencere: stopsuz ufuk-3 + maker giriş (ters-seçim riski, modelleme yapılmadan alınamaz). Sonraki adım isterse: 30+ gün veriyle maker-fill modeli veya sinyali mevcut ScalpAnalyzer girişlerine filtre olarak entegre etme.


## 2026-08-31: v2 Aday Filtresi Testi (SONUÇ: izleme filtresi olarak DOĞRULANDI)

`pump24/filter_v2_test.py` — UI'daki v2 filtresi (ATR%≥0,3 · BB genişlik≥2,5% · RSI≥60 trend/≤35 V-dönüş · MFI 10–90 · LinReg slope≥0,2%/bar VEYA Aroon_up≥50) 7g temiz M5 verisinde test edildi. Karar barı = M5 kapanış; dokunuş = sonraki 3 M5 bar high ≥ hedef (MFE).

- **Test (24h OOS):** 976/9859 bar geçti (%9,9). Geçenlerde 3-bar +0,95 dokunuş **%40,4** vs taban %14,4 (**lift +26,0pp**); +1,5 dokunuş %27,5 vs %7,9; avg MFE3 %1,42 vs %0,53 (2,7×).
- **Train (6g):** %30,2 dokunuş vs %11,8 — testte güç arttı, filtre bozulmuyor.
- **Kollar:** trend (RSI≥60) taşıyor (test %41,0, n=936); V-dönüş (≤35) zayıf+küçük (n=40, %25,0) → kalibrasyon içinde ayrı ağırlıklandırılabilir.
- **Uyarılar:** (1) UI kalibrasyonu (%19 hedef, %17,5 ölçülen) muhtemelen başka isabet tanımı kullanıyor — tanım MFE-tarzıyla hizalanmalı. (2) Dokunuş ≠ işlenebilir EV: ızgara taraması stoplu girişte pozitif EV üretmemişti; bu filtre **aday seçim/izleme** değeri taşır, giriş kararı değil.
- Rapor: `pump24_filtro_v2_sonuc.json` + `pump24_filtro_v2_test.json`; DB: research_runs id=10 + `pump24_filter_v2_watchlist` (status=validated_as_filter, conf 0,7).


## 2026-08-31: v2 × Pump Kesişim Testi (izleme listesi netleşti)

`pump24/intersection.py` + gün-bazlı analiz (`pump24/state/ix_daily.json`). Setler: v2 ∩ {ema_gap>2, atr≥1.5, vwap_dist>2, awesome>1, bb_width>0.06}. 7 gün × 50 sembol.

**Test (24h trend günü) yanıltıcıydı:** v2+ema_gap>2 EV(maker)=+0,60% görünüyordu. **Gün-bazlı gerçektir:** hafta toplamında v2+ema_gap>2 → n=607, avg_ret3 +0,184%, **EV(maker) +0,034% (sıfır)**, 3/7 gün pozitif; v2+atr≥1.5 → EV −0,144%, 2/7 pozitif. Chop günlerinde (08-24/26/28) pump sonrası getiri −0,5..−0,9%; trend günlerinde +0,5..+0,8%.

**Karar:** Dokunuş oranı (MFE3≥0,95) kesişimde gün-bazlı **%55–70 stabil** (taban %12–25) → **izleme listesi değeri kesin**. Flat-tutma EV'si rejim bağımlı → otonom giriş yok. Rapor: `pump24_kesisim_sonuc_raporu.json`; DB: research_runs id=11 + `pump24_v2_x_pump_watchlist` (validated_as_filter, 0,7). Canlı kullanım önerisi: aday tarama = v2 VE (ema_gap>2 veya atr≥1.5) → günlük ~85-165 sinyal barı; giriş kararı ayrı katman (LLM/ScalpAnalyzer) vermeli.
