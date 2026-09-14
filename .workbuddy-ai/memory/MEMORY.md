# Scalper Agent V4 — Kalıcı Proje Notları

Oturumlar arası kurallar. Günlük kayıt: `YYYY-MM-DD.md`. Raporlar `outputs/`.

## 1. Değişmez sözleşmeler

- **Paper-only.** Gerçek emir yolu yok. Strateji değişikliği OOS kanıtı olmadan aktive edilmez.
- **Renk:** YEŞİL=kâr, KIRMIZI=zarar; `null`/`NaN` **nötr** (`text-bunker-muted`). Kalibre edilmemiş metriğe güven rengi VERMEZ.
- **Gösterge TEK kaynak** `app/technical_analysis.py`. `ml_forecast.py`/`velocity.py` import eder, kopya üretmez. Şekil değişirse `ml_forecast.FEATURE_VERSION` artır.
- **Geç bağlama:** router→main yalnızca `app/runtime_deps.py` (`pending_dep`+`bind`); `startup_services()` ilk satırı `assert_ready()`. Router global'i monkeypatch EDİLMEZ.
- **Okuma yolu saf:** `database.load_*`/`get_*` DB'ye yazmaz.
- **Birim:** dışa açılan `*_pct` = yüzde, iç hesap = kesir (`_ratio_from_pct`).
- **Araştırma betikleri** (`backend/scripts`, `work/`) silinmez.

## 2. Düzenleme & doğrulama (ZORUNLU)

- **Aynı dosyaya paralel düzenleme GÖNDERME** — son yazan öncekini ezer. Birden çok değişiklik → **tek atomik script** (her `(old,new)` tam 1 eşleşme, hepsi doğrulanmadan yazmaz). Sonra `grep -c`.
- **Git Bash ters bölü bozar** (`\n`→`/n` → `count`=0 → betik hiçbir şey yapmaz, testler yanlış yeşil). Newline'lı betiği **Write ile dosyaya yaz**.
- **İddia → kanıt:** mutasyonla doğrula. Kaçan mutasyon = zayıf test; **ya testi güçlendir ya iddiayı çek** (D-07 `<`→`<=` float gürültüsünde görünmüyordu → tam temsil edilen değer seç: eşik 1.0, 100→101).
- **İç içe `patch`:** dış patch'i iç patch ezer (D-07 testinde `_ticker_price` sustu) → yardımcıya parametre geç.
- **Yeni global state →** TÜM `_reset_state()` yardımcılarını güncelle (`test_monitoring.py` ×2, `test_m1_monitoring_fixes.py`).
- **`next build`:** sandbox shim `.next` silmeyi engeller — kod hatası DEĞİL. `tsc --noEmit` tek başına yetmez.
- **Denetim dersi:** planına değil **BULGU LİSTESİNE** güven, parti sonunda ID bazında tara.

## 3. Otonom döngüler

- `velocity.autonomous_velocity_loop` **AKTİF**; çift kilit `VELOCITY_AUTO_ENABLED` (env) **ve** `llm_paper_trade_enabled` (DB).
- **Kablolama koruması** `tests/test_loop_wiring.py`: her `*_loop` ya `_start_background(<ad>…)` ya `create_task(<ad>(…))`. İsim geçişi SAYILMAZ.
- Bağlanmamış (bilinçli): `runtime.invalidate_wallet_caches`, `_ma_cascade_observation_context`, `maintenance._persist_replay_parity_observation`.

## 4. Para matematiği & ölçüm

- **Gidiş-dönüş maliyet TEK KAYNAK:** `config.round_trip_cost()` = (0.0015+0.00025)×2 = **0.0035 = %0.35**. `min_net_exit_pct` ve `velocity.round_trip_cost_pct()` bunu kullanır. **Eski "%0.30" notları YANLIŞ.**
- Dikkat: `value = float(order_value or DEFAULT)` → `min_net_exit_pct(0)` varsayılan tutarı kullanır; saf maliyet için **negatif** geç.
- **Açık pozisyon net K/Z TEK KAYNAK** `frontend/app/lib/pnl.ts`: `net = brüt − commission × q × (giriş + çıkış)` (**iki bacak**). Eksik girdi → **null**.
- **Backend `pnl_try` bilinçli tek bacak** (`main.py:1677`, `runtime.py:152`) — muhasebe. Eşitlemek açık iş.
- **Cüzdan mutabakatı TEK KAYNAK (V-01):** `database._portfolio_reconcile_figures(conn, cutoff)`.
- **MACD (F-02)** `database._macd_forward_outcomes(...)` yalnız KAPANMIŞ 5m barla mühürlenir. **(F-01)** `_stable_range` + `_own_activity_changed`. **(TAH-02)** isabet penceresi `forecast_learning.py`.

## 5. Radar / bildirim ölçümü (D-05…D-08)

Rapor `outputs/radar_duzeltme_raporu_2026-09-14.md`.
- **MFE = ulaşılamaz TEPE.** Gerçek: `velocity._exit_pct_from_window` (ufuk sonu close) ve `net_pct = exit − round_trip_cost_pct()`. DB `velocity_candidates.exit_pct/net_pct`. **TAMAMEN/KISMI/BAŞARISIZ (R3-04) DEĞİŞMEDİ.**
- **Fiyat tabanı TEK KAYNAK:** `_ticker_price(sym)` (tazelik doğrulanmış ticker; yoksa aday fiyatı) — D-05. Ayrı taban = tablo/mum uyuşmazlığı.
- **D-07 yeniden tetikleme:** cooldown 300 sn + pending(ufuk+2dk) yalnızca ZAMAN bakar. Ek kapı `|fiyat − son_bildirim_fiyatı|/son < MONITORING_REFIRE_MIN_MOVE_PCT (%0.35)`. Durum: `notified_prices`, `refire_blocked`. (Kanıt: 88 çiftte 26 bastırma, 0 TAMAMEN kaybı.)
- **D-08 skor doygunluğu:** `normalize_score = min(100, raw/CAP*100)` sert kırpar; kırpılma **rejime bağlı** (yerel DB %0.1, kullanıcı tablosu %96.2). **CAP DEĞİŞTİRİLMEDİ** — hedef bantları panel ölçeğinde, cap = strateji değişimi. Yerine ham `velocity_score` + `saturated` bayrağı (additive).
- **Hedef kalibrasyonu — OOS sonucu (`outputs/hedef_kalibrasyon_OOS_2026-09-14.md`):** skor MFE'yi gerçekten seçiyor (en üst/en alt decile MFE≥%2 oranı **4.13×**: %9.3→%38.3) → kenar VAR. Mevcut koşullu politika (EV +0.346 y.p.) en iyi sabit hedefi (%1.00, +0.341) GEÇİYOR; decile kalibrasyonu yalnız **+0.015 y.p. (%4.3)** → gürültü, aktive edilmedi. **Ders 1:** `ort. hedef × ort. isabet` koşullu politikada GEÇERSİZ (korelasyonu yoksayar) → kayıt bazlı `EV = ort(hedef × 1{MFE≥hedef})`. **Ders 2:** tek dönemlik oranlara bakıp "yapısal bozuk" deme — sistem hedefleri %2.5→%1.43 çekmiş, isabet %8→%30 çıkmış (zaman eğilimi).

## 6. ML / tahmin

- **Bar dayanağı (W3):** `TRAINING_BAR_MINUTES=5`; çıkarım 5m KAPANIŞ barlardan (1m YASAK).
- **Artifact:** `ML_MODELS_DIR` → Windows'ta cwd sürücüsü (`D:\data\ml_models`). **Başka sürücüden başlatmak → 503.** `start.ps1` `cd backend` yapar.
- **I-05:** `feature_version`+`feature_names`+`training_bar_minutes` eşleşmeli. **ML-05 kapısı:** `atr_pct`/`ret3_pct`/`rsi` biri None ise tahmin YOK.
- **`ml_hit_probability` skora/hedefe GİRMEZ** — AST kilidi `tests/test_ml_etki_kilidi.py`. Kanıt: tablo r=−0.050; DB r=+0.095/+0.111 → iki örneklem işaret olarak bile uyuşmuyor. Arayüzde **nötr** (`frontend/app/lib/mlProbability.ts`).
- **`ml_target_pct` KORUNDU** (vs MFE r=+0.344, t=+6.91) ama pratikte etkisiz: ML medyan %0.38 bekler, radar %2–4 ister → bağlayıcı 0/359.

## 7. Piyasa verisi & WS (W8/W9/W10)

- **REST klines SON satırı AÇIK mum** → önce `market._closed_history(...)`; yoksa `age=inf` → kalıcı fail-closed (B-02).
- **Tazelik toleransı = bar aralığı + pay** (`chart_forecast` 300+120=420 sn). `interval*2+30` YASAK.
- **B-01** WS bayrağı sleep'ten SONRA + `WS_GENERATION_MIN_INTERVAL_SEC`. **B-03** URL her denemede yeniden; backoff 30 sn tavan. **B-05** çerçeve başına `_handle_ws_frame()`. **B-06** `self._bg_tasks` + `add_done_callback`. **B-04** `ticker_24h` **merge**. **B-17** MicroFlow kendi `aggTrade` soketi.
- **`_interval_ms` KATI** `re.fullmatch(r"(\d+)([smhdwM])")`; `M`=ay, `m`=dk.
- **`trade_flow` KAYAN pencere** (1 sn kova); tumbling reset YASAK.
- **Public REST tek semafor** (`REST_MAX_CONCURRENCY=8`) + `REST_WEIGHT_SOFT_LIMIT=4500`. Yeniden deneme: 429/5xx/418 + bozuk gövde. **`code != 0` iş hatası DENENMEZ.**

## 8. MACD MONITOR

Rapor `outputs/macd_monitor_denetim_raporu.md`.
- **Trend gücü yönsüz — KANITLA** (OOS 312 sembol: IC −0.049, t −23.8 @30m) → yön skora EKLENMEZ.
- **C1:** M3/M30 WS'de değil → REST (3m≈75sn, 30m≈1860sn). **C3 kanıt:** `macd_monitor_alerts` + `macd_evidence_loop`; **eşik/ağırlık yalnızca bu kanıtla değişir.**
- **Snapshot'ın İKİ tüketicisi** — yeni WS tipinde ikisini de güncelle (`lib/macdSnapshot.ts` → `mergeMacdDelta`).

## 9. Frontend & komutlar

- `reactStrictMode: true` → dev'de effect çift çağrısı; CONNECTING'de `ws.close()` uyarısı zararsız.
- Grafik doğrudan Binance TR WS (`NEXT_PUBLIC_BINANCE_WS_BASE`, yedek `stream.binance.me`). `API_BASE = NEXT_PUBLIC_API_URL || browserOrigin`; nginx `/api/`→`backend:8004`.
- Komutlar: `backend/venv/Scripts/python.exe -m pytest tests/ -q` (özet satırı yazdırmaz — nokta say); `npx tsc --noEmit`; `python -m py_compile`.
- `couldn't stop thread 'pool-1-worker-N'` = zararsız psycopg teardown gürültüsü.
- **Yerel DB son kayıt 2026-09-07**; kullanıcı arayüzü dağıtımdaki instance'dan geliyor → ölçümden önce tarih aralığını kontrol et.
