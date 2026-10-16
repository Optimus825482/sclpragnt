# 7 Günlük Backtest ve Replay Raporu — 2026-10-16

**Soru:** Güncel kod (main @ db0edc60 + bugünkü harness onarımları) ile son 7 günde (9–16 Ekim 2026) sistem para kazanıyor mu?
**Kısa cevap:** Hayır. Beş bağımsız ölçümün beşinde de ortalama net getiri negatif; zararın büyüklüğü işlem başına gidiş-dönüş maliyetine (%0.30–0.35) eşit. Brüt kenar sıfır civarında. Bugün eklenen zaman-stop varyantları bunu değiştirmiyor. Tek pozitif alt küme, radar replay'inde `jump+velocity` çakışmaları (+0.13 %/sinyal, n≈190), hipotez düzeyinde.

**Yöntem:** Yerel PostgreSQL 17'de `scalper_prod_copy` (549 MB üretim kopyası) dump/restore ile `scalper` olarak klonlandı, 17 migration uygulandı. Beş Sonnet ajanı paralel koştu; her biri tek harness'ı 7 gün için çalıştırıp metrikleri raporladı. Ham çıktılar scratchpad `backtest/` altında.

---

## 1. Ortam ve Veri

| Öğe | Durum |
|-----|-------|
| PostgreSQL | 17 (Windows servisi), pgvector kurulu |
| Veritabanı | `scalper` ← `scalper_prod_copy` (dump/restore; kopya başka oturum tarafından açık olduğundan TEMPLATE kullanılamadı) |
| Migration | 001–017 `schema_migrations` ile uygulandı (017 bu kurulumda yeni) |
| velocity_candidates | 2026-09-16 .. 10-16, 492k satır |
| auto_paper_trades | 2026-09-05 .. 10-16, 1752 satır (son 7 gün: 145 kapalı) |
| combined_paper_trades | 2026-10-11 .. 10-15, 219 satır |
| unified_candidate_outcomes | 2026-10-14 .. 10-16, 14k satır (journal yalnız 2 gün) |
| historical_candles | 5m, 98 sembol, 2026-10-09 .. 10-16 |
| monitoring_notifications | 2026-09-16 .. 10-16 (son 7 gün: 586) |
| Binance public REST | erişilebilir (eksik mumlar çekildi) |

**Test paketi (DB ile):** 2449 geçti, 16 başarısız. Önceden DB yokluğundan kırmızı olan 26 testin 10'u geçti. Kalan 16: Binance TR adaptörünün bugünden önce de kayık `clientOrderId` sözleşme testleri (4) ve üretim kopyasındaki canlı duruma bağlı testler (2 açık otonom pozisyon, 1 pozisyon, üretim ayarları → `score_below_min`, "mock called 0 times"; 12). Bugünkü değişikliklerden kaynaklanan regresyon yok.

---

## 2. Harness Sonuçları

### 2.1 Birleşik havuz replay'i (`unified_pool_replay.py --days 7`)
`passes=true` velocity adayları (37.525), TP/SL %3/ufuk sonu, taker %0.35; ilk %60 eğitim, son %40 sınav (~2.8 gün, n=6539).

| | baseline | time_stop 15 dk / 0.3 % | time_stop 20 dk / 0.5 % |
|---|---|---|---|
| TP oranı | %27.7 | %26.6 | %27.1 |
| Ort. net %/işlem | −0.420 | −0.415 | −0.419 |
| Medyan net % | −0.35 | −0.35 | −0.35 |
| Çıkış TP/SL/ufuk/time-stop | 1809/804/3926/0 | 1742/633/2279/1885 | 1772/712/2304/1752 |
| Maker maliyetiyle | −0.17 | −0.165 | −0.169 |

Tüm günler negatif (0/5), 3-fold hepsi negatif, karar GEÇMEDİ. Birleşik (confluence) kapı 6539 işlemden yalnız 66'sını eliyor; "skortop" (üst %50 skor) daha kötü (−0.457). İşlemlerin %91'i 13 ve 15 Ekim'de yığılmış, bağımsız değil.
**Harness kusuru:** script `work/market_cache.sqlite` istiyor (yok); ajan `_load_prices`'ı Postgres `historical_candles` okuyan sarmalayıcıyla çalıştırdı. Kalıcı düzeltme gerekli.

### 2.2 Kombine paper kalibrasyonu (`calibrate_combined_paper.py --hours 168 --fetch`)
51 çıkış konfigürasyonu, walk-forward (eğitim 22.515 / sınav 15.010), komisyon %0.15 + slippage %0.025.

| Konfig (sınav) | Kazanma % | Ort. net %/işlem | t |
|---|---|---|---|
| Baseline (SL 1.0 / trig 2.0 / gap 1.0) | 33.9 | −0.277 | −19.9 |
| En iyi: SL 0.8 / trig 1.0 / gap 0.8 | 42.7 | −0.183 | −15.4 |
| time_stop_15 | 26.7 | −0.266 | −20.3 |
| time_stop_20 | 30.7 | −0.264 | −20.0 |

Karar `KEEP_DEFAULT_NO_EDGE`. Giriş taraması (`--entry-scan`): hiçbir filtre pozitif değil; skor ≥p85 −0.180, ATR ≥p70 −0.176, 30 dk kovada top-1 **−0.862** (top-N seçimi bazdan kötü) → `NO_ENTRY_EDGE`. 12 Ekim raporuyla aynı yön; baseline zararı −0.42'den −0.277'ye küçülmüş (SL 1.0 artık canlı).

### 2.3 Birleşik radar replay'i (`combined_radar_replay_24h.py`, 7 × 24 saat)
Journal'daki velocity/rising/MACD kayıtları, 1m REST mumları, auto_paper B1–B4 çıkış merdiveni, maliyet %0.35.

| Gün | combined n | TP % | Kazanma % | Ort. net % | Velocity-only ort. net (n) |
|---|---|---|---|---|---|
| 09.10 | 212 | 9.0 | 30.2 | −0.505 | −0.506 (2611) |
| 10.10 | 189 | 9.0 | 32.3 | −0.475 | −0.427 (2794) |
| 11.10 | 214 | 10.3 | 43.5 | −0.268 | −0.393 (3698) |
| 12.10 | 216 | 12.0 | 35.6 | −0.452 | −0.514 (4000, sınır) |
| 13.10 | 211 | 8.1 | 30.3 | −0.478 | −0.654 (2833) |
| 14.10 | 64 | 9.4 | 37.5 | −0.462 | −0.476 (1007) |
| 15.10 | 249 | 7.2 | 34.1 | −0.439 | −0.430 (3182) |
| **Toplam** | **1355** | **9.2** | **34.5** | **−0.437** | **−0.483 (20125)** |

Unified akış −0.444 (n=2042). Combined velocity'yi 5/7 gün geçiyor ama fark ~0.05 puan. `rising_only` her gün 0 sinyal (filtreler hepsini eliyor). **Tek pozitif alt küme:** `jump+velocity` ve `jump+rising+velocity` çakışmaları: n≈95'er, kazanma %64–66, ort. net +0.13, medyan +0.21/+0.33. Hedef/MFE oranı 1.4–1.8× (TP çoğu zaman ulaşılamaz).
**Harness kusuru (düzeltildi):** `--help` argparse'ı çökertiyordu (`%` → `%%`, satır 1405/1407/1409).

### 2.4 Portföy backtest'i (`run_portfolio_backtest.py`, 98 sembol, 5m, 10.000 TL)
**Uyarı:** Bu script 4 Eylül'de kaldırılan **BB-MFI mean-reversion** stratejisini (Pine v3) oynatıyor; canlı velocity/LLM hattını ölçmüyor. Sonuç yalnız referans.

| Metrik | Spread %0.1 | Spread %0.2 |
|---|---|---|
| İşlem | 109 | 109 |
| Kazanma | %65.1 | %60.6 |
| Net | −762 TL (−%7.62) | −910 TL (−%9.10) |
| Profit factor | 0.72 | 0.67 |
| Maks. düşüş | %13.5 | %13.9 |
| Çıkışlar (TL) | 36 TP +1127 / 8 stop −1468 / 65 sinyal −303 | 35 TP +1053 / 8 stop −1462 / 66 sinyal −375 |

8 stop (−1468 TL), 36 TP'nin toplamından (+1127) fazla. Kayıp BLUR/0G/SENT'te yoğun.
**Harness kusuru (düzeltildi):** `config.BACKTEST_ASSUMED_SPREAD_PCT` yoktu (config.py'ye eklendi, varsayılan 0.001); kaldırılmış `ACTIVE_STRATEGY`/`BB_MFI_*` değerleri script içinde `setattr` ile tamamlandı; `analyzer.calculate_bollinger_bands` → `technical_analysis._bollinger`.

### 2.5 Gerçekleşen sonuçlar ve journal (SQL + yeni analiz araçları)
**auto_paper_trades (kapalı), İstanbul saati:**

| | n | Kazanma % | Ort. pnl % | Medyan | Toplam TRY | Payoff | Başabaş için gereken kazanma % | Medyan tutma |
|---|---|---|---|---|---|---|---|---|
| 09–15 Ekim | 145 | 52.4 | −0.326 | +0.188 | −1933 | 0.665 | 60.1 | 20.4 dk |
| 02–08 Ekim | 293 | 53.4 | −0.428 | +0.497 | −2443 | 0.564 | 64.0 | 17.8 dk |

Çıkış nedenleri (bu hafta): trailing_stop n53 +1.46, take_profit n17 +2.91, stop_loss n23 **−4.32** (her seferinde tam), max_duration n25 −1.51, symbol_deactivated n27 −1.37 (kazanma %3.7). Skor 95+ kovası (n77, −0.12) 85–95'ten (n68, −0.56) iyi. İşlem başı komisyon 10.34 TL (~0.30 puan); brüt ortalama ≈ −0.03 % → **zararın neredeyse tamamı komisyon**. İşlem başı notional 1994 → 3449 TL büyümüş, TRY zararı işlem başına −8.3 → −13.3.
**combined_paper_trades:** n219, kazanma %36.1, ort. −0.314, payoff 1.27 (stop_loss n131 −1.77, trailing n80 +2.08).
**Bildirimler (7 gün):** 586 bildirim, 116 sembol; ilk 10 sembol %40; aynı sembol 60 dk içinde tekrar **%45**; 28 satırda skor >100 (eski ham ölçek artığı).
**Journal (`radar_lift_analysis --days 7`, n=14.004, yalnız 2 gün):** hit %1.6; precision@5 = 0.00, @10 = 0.10; Spearman(skor, MFE) 0.373 genel ama ufka ayrılınca 0.17–0.21 (60 dk: −0.065). Lift: macd_mtf 5.14, skor 85–95 4.35, 95–100 3.55, skor <70 **0.21**; `short_squeeze` 0.01 (n9166), `snapback` 0.00, `fusion` 0.00 → KARAR: lift<1 aileler `['short_squeeze','fusion','snapback']`. Ufuk 0 satırlar (9166, short_squeeze) hit %0.1.

---

## 3. Kesişen Sonuçlar

1. **Maliyet duvarı doğrulandı.** Beş ölçümde ortalama net −0.28 … −0.48 %/işlem; gerçekleşen brüt ≈ 0, komisyon ≈ 0.30. 15 Ekim raporunun "yapısal sınır" tespiti 7 günlük veriyle tekrarlandı.
2. **Skor sıralaması seçici değil, ama eşik olarak işe yarıyor.** Skor <70 lift 0.21, 85+ lift 3.5–4.4; gerçekleşen 95+ kovası 85–95'ten iyi. Buna karşın top-N seçimi bazdan **kötü** (−0.86) ve precision@5 sıfır. Yani "en iyi 3'ü al" stratejisi zarar büyütüyor; "70 altını at" filtresi doğru.
3. **Zaman-stop yararsız.** Üç harness'ta da fark ±0.005 puan; kazancı SL'den time-stop'a kaydırıyor, EV değişmiyor. Flag kapalı kalmalı.
4. **Çıkış asimetrisi aynı:** stop −4.32 sabit ve tam; kazançlar +1.5/+2.9. Payoff 0.67 ile %60 kazanma gerekir, gerçekleşen %52. Kalibrasyonda dar stop (0.8) + erken trailing kaybı en çok azaltıyor (−0.277 → −0.183) ama 12 Ekim'de "riskli" bulunmuştu; canlıda sıkı SL 7× kötüleşmişti. Bu çelişki aynı harness'ta kapanmadan SL değiştirilmemeli.
5. **Kesilebilir aileler:** `short_squeeze` (9166 satır, hit %0.1), `snapback`, `fusion`. `rising_only` zaten sıfır sinyal üretiyor. `jump+velocity` çakışması tek umut vaat eden sinyal (n küçük).
6. **Sinyal bağımsızlığı zayıf:** %45 tekrar, ilk 10 sembol %40, replay işlemlerinin %91'i iki günde. İstatistikler iyimser.
7. **Ölçüm altyapısı eksikleri:** journal 2 günlük; `unified_pool_replay` sqlite'a bağımlı; `run_portfolio_backtest` eski stratejiyi oynatıyor; velocity journal günde 20k satır sınırına takılıyor (09/12/13 Ekim `truncated`); 28 bildirimde ham skor sızıntısı.

---

## 4. Önerilen Aksiyonlar (kanıt sırasıyla)

1. **Hemen:** `short_squeeze`, `snapback`, `fusion` ailelerini bildirim/otonom akışından çıkar (lift<1, n büyük). Skor <70 adayları listeye alma. Bunlar DENEY_KAYDI'na satır olarak girsin.
2. **Hemen:** zaman-stop flag'i kapalı kalsın; DENEY_KAYDI'na "yararsız, 3 harness" sonucu işlensin.
3. **Harness onarımı:** `unified_pool_replay._load_prices` Postgres `historical_candles` okusun; `run_portfolio_backtest` için canlı velocity hattını oynatan bir mod ya da "BB-MFI referans" etiketi; velocity journal satır sınırını kaldır/kademeli oku; bildirim kaydında ham skor normalizasyonu.
4. **Ölçüm:** journal 14 güne ulaşınca `radar_lift_analysis` ve `radar_bucket_analysis` tekrar; `jump+velocity` çakışması için ayrı sayaç; sembol bazlı dedup flag'ini (`RADAR_NOTIFY_SYMBOL_COOLDOWN_MIN=60`) 1 hafta A/B.
5. **Ürün kararı:** brüt kenar ≈ 0 iken komisyon 0.30 → komisyon indirimi (BNB/VIP), daha uzun ufuk ya da yalnız `trend_devam` + `jump+velocity` ile seyrek sinyal. Sinyal ayarıyla pozitife geçiş yolu bu 7 günde de görünmüyor.

---

## 5. Sınırlar
- 7 gün tek rejim; ardışık sinyaller korele; t değerleri iyimser.
- Replay'ler mid-price/1m-5m mum tabanlı; gerçek spread ve derinlik yok.
- `unified_pool_replay` ajan sarmalayıcısıyla koştu (repoda düzeltme yok); `run_portfolio_backtest` canlı stratejiyi ölçmüyor.
- Journal yalnız 14–16 Ekim; kova analizi için özellik CSV'si yok.
- Ham çıktılar scratchpad'de (`backtest/{unified_pool,calibrate,portfolio,radar_replay,realized}/`), repoya alınmadı.
