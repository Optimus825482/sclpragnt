# Radar/Tarama Sistemi İyileştirme Analizi — 2026-10-14

Amaç: yükseliş potansiyeli taşıyan coinleri daha isabetli tespit etmek için mevcut motorların
kod seviyesinde denetimi + kanıta dayalı yöntem araştırması. Salt analiz; bu dosya uygulama
planının girdisidir.

## BÖLÜM A — Mevcut Sistemin Denetimi (kod seviyesi)

### A.1 Motor envanteri

| Motor | Sinyaller | Eşikler | Ölçüm katmanı | Durum |
|---|---|---|---|---|
| Velocity (5/15/30/60dk) | RSI, MFI, BB genişliği, LinReg eğim, Aroon, ATR, MACD hist, hacim z-skoru | Statik + ATR eşiği otomatik kalibre | Journal + lift + worst-case TP/SL | En olgun |
| Günlük momentum | 8s getiri, ATR%, ADX, +DI, eğim, spread | Statik, günde 1 kez 11:30 | 24h MFE/MAE outcomes | Kanıtlı (%19.8 vs %5.3 baz) |
| Short-squeeze | Yalnız funding ≤ −0.01/−0.03/−0.10% | Statik | YOK | Tek-veri, en zayıf |
| Pulse (miniTicker) | 1dk getiri ≥0.4% + hacim burst ≥2× | Statik | YOK | En düşük gecikme |
| Snapback | 1H RSI(7)<20 + RSI(14)<30 + BTC EMA200 rejim | Statik | IS/OOS replay var, canlı journal YOK | Olgun ama ölçüsüz |
| MACD jump/early | Çok TF MACD + CVD + dip/proximity | Statik + lift onaylı dip reçetesi | Outcome + LIFT (en olgun) | Güçlü |
| MACD MTF | M1/M3/M5/M15 kesişim yaşı + eğim | Konfluans ≥45 | Dolaylı | Teyit katmanı |
| Master Surge | Likidite + squeeze/dip + orderflow (CVD/whale) + MTF yeşil + türev fail-closed | Katman puanları statik | YOK | En zengin, ölçüsüz |

### A.2 Yapısal bulgular

1. **Panel ağırlığı %60 velocity** — `_combined_quality_score` adayları fiilen velocity ham
   skoruyla sürüyor; kaynak/katman bonusları (+8/+4) kanıtlanmış lift olmadan sabit.
2. **30/60 dk ufukları kanıtlanmış negatif EV** — `velocity.py:241-248` kod yorumu açıkça
   "MAE>MFE → pump-and-fade" diyor. Peak-capture olmadan bu ufuklar zarar eder.
3. **Rejim ayrımı eksik** — ADX yalnız günlük momentumda; BTC EMA200 kalkanı yalnız
   snapback/master surge'da. Global trend/chop rejimi tarama eşiğini/hedefini değiştirmiyor.
4. **Kullanılmayan hazır veri** — kline yanıtındaki `takerBuyBaseVolume` (CVD için bedava),
   OI delta, taker buy/sell ratio, likidasyon akışı, orderbook imbalance zaman serisi, VWAP.
5. **False-positive kaynakları** — yeni liste (discovery medyan tabanı 1.0 → yapay burst),
   düşük likidite (squeezede depth kapısı yok, velocity'de spread kontrolü fail-open),
   24h gainer havuzundaki eski pump'lar.
6. **Ölçüsüz motorlar** — pulse, snapback, short-squeeze, master-surge ve unified `scan_score`
   için ayrı outcome journal yok; bonusların haklılığı test edilemiyor.

## BÖLÜM B — Kanıta Dayalı Yöntem Araştırması (özet + kaynaklar)

1. **Hacim-delta / CVD eğimi** — anormal hacim kısa vadede devam drifti öngörür (Lo&Wang 2000;
   Gervais 2001). Pratik: hacim z>2σ **+** yön onayı; CVD'yi mutlak değil **eğim** olarak,
   fiyat hareketsizken kullan. Kaynak: bookmap.com/blog (CVD), Lo&Wang (MIT).
2. **Emir defteri imbalance** — kısa vadeli fiyat yönünü öngörür ama yarı ömür saniyeler mertebesinde
   (Cont 2014, Gould&Bonart 2016). Taramada birincil sinyal değil **teyit/tie-breaker**; spoofing
   iptal kuralı şart. Kaynak: academic.oup.com/jfec, arxiv 1512.03492.
3. **Lead-lag (Global↔TR)** — perp fiyat keşfi spotu öncükler (Chan 1992; Albers&Chang 2021).
   Global USDT paritesi önce hareket ettiyse TR'de "yakalanmamış taşıma" sinyali; global patladıysa
   geç faz → kaçın. NOT: kod içi 45 günlük ölçüm korelasyonu doğruladı (+0.14-0.16) ama net EV
   maliyet altında — sinyal olarak değil **teyit filtresi** olarak değerlendir.
4. **ATR-normalize momentum + zirveye yakınlık** — ham yüzde yerine getiri/ATR; George&Hwang (2004)
   52W zirveye yakınlık, geçmiş getiriden güçlü öngörücü. `1 − (high(n)−p)/ATR ≥ 0.9` filosu.
   Kaynak: bauer.uh.edu/tgeorge/papers/gh4-paper.pdf.
5. **Squeeze→kırılım** — BBW yüzdelik dilimi <%20 izleme + genişleme/hacim barda sinyal (TTM Squeeze).
   Choppiness >61.8 chop, <38.2 trend.
6. **Rejim kapısı** — BBW rejim özelliği Bollinger sinyal kalitesini ADX'ten iyi ayırt ediyor
   (meta-labeling çalışmaları). Mevcut sinyallere **AND gate** olarak, skor değiştirmeden eklenir
   → en ucuz false-positive azaltımı.
7. **OI + funding erken uyarı** — funding gelecekteki spot volatilitesi hakkında ayrı bilgi taşır
   (JFM 2026). OI 24s +%10 + ılımlı pozitif funding = erken birikim; funding >0.1%/8s = aşırı
   ısınma → yeni long bastır. Public fapi endpoint'leri yeterli.
8. **Ensemble scorer** — korelasyonsuz 4-5 sinyal ailesi, sınırlı katkı (−1..+1), "skor ≥ T **ve**
   ≥3 aile pozitif" hibriti; ağırlıklar canlı MFE/MAE'den güncellenir (Huck/ETIA; SSRN AI-confluence:
   Sharpe 1.81 vs 0.81, win %69; baskın özellikler BB %B, RSI, ATR).
9. **Tuzaklar** — P&D illiquid coinleri hedefler, "uzun sessizlik + ani hacim z>4" ön-tespiti
   (Dhawan&Putniş; ACM 3561300); MFE yanılsaması (derinlik yoksa tepe işlenemez); yeni liste
   <30 gün ayrı filo; wash trading (NBER w30783: raporlanan hacmin %70'i şüpheli olabilir).

## BÖLÜM C — ÖNCELİKLİ EYLEM PLANI (etki/çaba sıralı)

| # | Eylem | Nereye | Etki | Çaba |
|---|---|---|---|---|
| 1 | **Rejim kapısı**: ADX+Choppiness/BBW AND gate; chop'ta skor ×0.5 veya sinyal bastır | velocity + unified_scan | Yüksek | Düşük |
| 2 | **Taker buy/sell + hacim z-skoru yön onayı**: `takerBuyBaseVolume` zaten kline'da | velocity hacim katmanı | Yüksek | Düşük |
| 3 | **Zirveye yakınlık + ATR-normalize momentum filosu skoru** | unified_scan (yeni aile) | Yüksek | Düşük |
| 4 | **P&D/likidite hijyeni**: 24s hacim tabanı, listing yaşı <30g ayrı filo, parabolik+z>4 "geç faz" etiketi, spread fail-open→fail-closed | pulse/discovery + velocity | Yüksek | Düşük |
| 5 | **30/60 dk ufuklarını peak-capture'a bağla veya kaldır** (kod zaten negatif EV diyor) | velocity profilleri | Yüksek | Orta |
| 6 | **OI delta + funding trendi squeeze doğrulaması** (derivatives_service zaten veriyi çekiyor) | short_squeeze | Orta-Yüksek | Orta |
| 7 | **Ölçüsüz motorlara outcome journal** (pulse, snapback, squeeze, master-surge) — bonus ağırlıklarını kanıtla | database + router'lar | Yüksek (araç) | Orta |
| 8 | **Ensemble scorer**: velocity yerine korelasyonsuz aile oylaması; ağırlıklar canlı sonuçlardan adaptif | unified_scan mimarisi | Yüksek | Orta-Büyük |
| 9 | **Global lead-lag'i sinyal değil teyit filtresi olarak yeniden konumlandır** | global_radar | Orta | Orta |
| 10 | **CVD eğimi + orderbook imbalance tie-breaker** (spoofing iptal kuralıyla) | microflow/master surge | Orta | Orta-Büyük |

### Uygulama sırası önerisi
Faz 1 (hızlı kazanç, 1-3+4): filtre tabanlı, sinyal mantığı değişmez, false-positive düşer.
Faz 2 (ölçüm, 7): hangi motor gerçekten iş yarıyorsa kanıtla; bonusları veriye bağla.
Faz 3 (mimari, 5+8+6+9+10): negatif EV ufuklar temizlenir, skor motoru ensemble'a geçer.

## UYGULAMA DURUMU (2026-10-14)

| Madde | Durum | Yer |
|---|---|---|
| 1 Rejim kapısı | ✅ velocity `_radar` bloğu (Choppiness 10 bar > 61.8 + ADX < 20 → skor ×0.5) | velocity.py, config VELOCITY_REGIME_* |
| 2 Taker teyidi | ✅ kline[9]/[5] oranı; güçli ×1.05 / zayıf ×0.95 (eski 9-sütun veride fail-open) | velocity.py, VELOCITY_TAKER_* |
| 3 Zirve-yakınlık | ✅ range_pos_60 (1s aralık konumu) + unified 'proximity' ailesi +2 | velocity.py + unified_scan._radar_family_bonus |
| 4 P&D hijyeni | ✅ 24s hacim tabanı 1M TRY (kline isteğinden önce eler), geç faz (24s ≥%40 → ×0.6), spread fail-closed (×0.85) | velocity.py, VELOCITY_MIN_QUOTE_VOL_24H vb. |
| 5 30/60 dk ufuk | ✅ VELOCITY_EXTRA_HORIZONS_ENABLED varsayılanı false (peak-capture kanıtlanınca env ile açılır) | config.py |
| 6 OI + funding squeeze teyidi | ✅ derivatives_service.squeeze_confirmation (OI 1s Δ ≥%10 → ×1.25, ≤−%8 → ×0.7; funding trendi strengthening/easing) | derivatives_service.py + monitoring._short_squeeze_candidates |
| 7 Outcome journal | ✅ unified_candidate_outcomes tablosu (migration 013) + döngü içi fill + /api/unified-scan/outcome-stats | unified_outcomes.py, database.py, monitoring.py |
| 8 Ensemble scorer | ✅ unified _radar_family_bonus: flow/proximity/clean aileleri (+2 each, cap +6); radar verisi yoksa davranış eski | unified_scan.py |
| 9 Lead-lag teyit konumlandırma | ✅ global radar geç faz kapısı (global 24s ≥%25 → tespit işlenmez); residual filtresi zaten vardı | global_radar.py, GLOBAL_LATE_PHASE_CHANGE_PCT |
| 10 CVD/book imbalance | ✅ book_imbalance (bid−ask)/(bid+ask) aday `radar` alanında; unified sıralama tie-breaker. CVD zaten microflow micro_mult ile sıralamada | velocity.py + unified_scan.sort |

Tüm yeni eşikler env ile ayarlanabilir, varsayılanlar temkinli. `radar` alanı aday satırlarında taşınır → UI/outcome journal açıklayıcılığı hazır. Doğrulama: test_daily_rising_combined + test_unified_outcomes + velocity testleri geçti (ruff/py_compile temiz).
