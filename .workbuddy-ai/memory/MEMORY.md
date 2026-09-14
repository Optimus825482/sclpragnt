# Scalper Agent V4 — Kalıcı Proje Notları

Oturumlar arası kurallar. Günlük kayıt: `YYYY-MM-DD.md`. Detaylı raporlar `outputs/`.

## 1. Değişmez sözleşmeler

- **Paper-only.** Sanal cüzdan, gerçek emir yolu yok. Strateji değişikliği OOS kanıtı olmadan aktive edilmez.
- **Renk:** YEŞİL=kâr, KIRMIZI=zarar; `null`/`NaN` **nötr** (`text-bunker-muted`), asla boyanmaz.
- **Gösterge TEK kaynak:** `app/technical_analysis.py` (`_rsi` Wilder; `_aroon` high/low + `period+1` + son-tekrar tie-break; `_linreg_slope_pct` 10-bar). `ml_forecast.py`/`routers/velocity.py` import eder, kopya üretmez.
- **Özellik sürümleme:** gösterge/özellik şekli değişirse `ml_forecast.FEATURE_VERSION` artır.
- **Geç bağlama:** router→main yalnızca `app/runtime_deps.py` (`pending_dep`+`bind`); `startup_services()` ilk satırı `assert_ready()`. Router global'i monkeypatch EDİLMEZ.
- **Okuma yolu saf:** `database.load_*`/`get_*` DB'ye yazmaz. Backfill ayrı fonksiyon + `init_db()`.
- **Birim:** dışa açılan `*_pct` = yüzde, iç hesap = kesir (`_ratio_from_pct`).
- **Araştırma betikleri** (`backend/scripts`, `backend/work`) **silinmez**. Ölü sembol sayısı 0.

## 2. Düzenleme & doğrulama (ZORUNLU)

- **Aynı dosyaya paralel düzenleme GÖNDERME** — son yazan öncekini ezer, değişiklik sessizce kaybolur. Birden çok değişiklik → **tek atomik script** (her `(old,new)` tam 1 eşleşme, hepsi doğrulanmadan yazmaz). Örnek: `work/apply_chart_forecast_fix.py`. Sonra `grep -c` ile doğrula.
- **Git Bash ters bölü bozar** (`\n`→`/n`, `str.count()`→0 → betik hiçbir şey yapmaz, testler yanlış yeşil). Newline/ters bölülü betiği **Write ile dosyaya yaz**, sonra çalıştır.
- **`next build`:** sandbox shim `.next` silmeyi engeller (`SAFE_DELETE_BULK_CONFIRM_REQUIRED`) — kod hatası DEĞİL. Önce `.next`'i sil, sonra derle. `tsc --noEmit` tek başına yetmez.
- **İddia → kanıt:** mutasyonla doğrula (eski davranışa çek, test kırılsın).

## 3. Otonom döngüler

- `velocity.autonomous_velocity_loop` **AKTİF**: `main.py` → `_start_background(...)`. Çift kilit `VELOCITY_AUTO_ENABLED` (env) **ve** `llm_paper_trade_enabled` (DB); kapı her turda okunur. Kapatma: env false **veya** DB 0.
- **Kablolama koruması** `tests/test_loop_wiring.py`: her `*_loop` ya `_start_background(<ad>…)` ya `create_task(<ad>(…))`. **Import/isim geçişi SAYILMAZ.**
- Bağlanmamış (bilinçli): `runtime.invalidate_wallet_caches`, `_ma_cascade_observation_context`, `maintenance._persist_replay_parity_observation`.

## 4. Para matematiği & ölçüm

- **Açık pozisyon net K/Z TEK KAYNAK** `frontend/app/lib/pnl.ts`: `net = brüt − commission_pct × q × (giriş + çıkış)` (**iki bacak**; tek bacak D-01 hatasıydı). Eksik girdi → **null** (0 değil).
- **Backend `pnl_try` bilinçli olarak tek bacak** (`main.py:1677`, `runtime.py:152`) — muhasebe/reconciliation için. Görüntü tek esasa çekildi, **muhasebe DEĞİŞMEDİ** → eşitlemek açık iş.
- **Cüzdan mutabakatı TEK KAYNAK (V-01):** `database._portfolio_reconcile_figures(conn, cutoff)`. TRY satırı iki defter (ana + `auto_paper_trades`) paylaşır. `reconcile_portfolio`, `preview_portfolio_reconcile`, `init_db` **aynı yardımcıyı** kullanmak zorunda.
- **`min_net_exit_pct` `0` davranışı** risk kapısı, sessizce değiştirme (`test_w6_money_math.py`).
- **MACD ileri getiri (F-02):** `database._macd_forward_outcomes(rows, base, t0_ms, now_ms)`; ufuk ancak hedefi kapsayan **KAPANMIŞ** 5m barla mühürlenir, yoksa `NULL`.
- **MACD hayalet alarm (F-01):** `_stable_range` (p5–p95, `n<20`→min/max) **ve** `_own_activity_changed`. Ekrandaki `strength` evren min-max kaldı.
- **İsabet penceresi (TAH-02)** tek kaynak `forecast_learning.py`: `grace=min(grace,horizon)`, `window=(h+grace)*60`.

## 5. Piyasa verisi & WS (W8/W9/W10)

- **REST klines SON satırı AÇIK mum.** Önbellekten önce `market._closed_history(rows, tf, now_ms)`; elle seri kurmak yasak → `last_closed_at_ms` yazılmazsa `age=inf` → **kalıcı fail-closed** (B-02). Örnek `routers/runtime.py:920`.
- **Tazelik toleransı = bar aralığı + pay** (WS 15 sn, REST 3m/30m 120 sn). `interval*2+30` YASAK. **Ders:** sabit 180 sn kapısı 5m seride yanlış — son KAPANMIŞ 5m barın yaşı 0..300 sn; kapı "ölü sembol" içindir → aralık+pay (`chart_forecast`: 300+120=420 sn).
- **WS nesil döngüsü (B-01):** bayrak **sleep'ten SONRA** kontrol edilir + `WS_GENERATION_MIN_INTERVAL_SEC`; yoksa binlerce yarım bağlantı/sn (ölçüldü ~11.900).
- **WS URL her denemede yeniden kurulur (B-03)** `_ws_url_for(...)`; donmuş `plan["url"]` yedeğe geçişi öldürür. Backoff `_ws_backoff_sec` (üstel+jitter, 30 sn tavan).
- **B-05** çerçeve başına `_handle_ws_frame()`; **B-06** arka plan görevleri `self._bg_tasks` + `add_done_callback`.
- **B-04** `_ticker_paged()` 50'lik + birleştirme; `ticker_24h` **merge** (replace değil) yoksa likidite kapısı kilitlenir.
- **`_interval_ms` KATI** `re.fullmatch(r"(\d+)([smhdwM])")`; `M`=ay, `m`=dk; sessiz varsayılan YASAK.
- **`trade_flow` KAYAN pencere** (1 sn kova); düz sayaçlar korunur (`macd_monitor._symbol_cvd`). Tumbling reset YASAK. `microflow._aggregate_5s` `//5000*5000` hizalar; **`MicroFlow.start()`** sembol değişiminde tahliye eder.
- **Public REST tek semafor** (`REST_MAX_CONCURRENCY=8`) + `REST_WEIGHT_SOFT_LIMIT=4500`. **Yeniden deneme:** 429/5xx/418 + bozuk gövde; 418 → 30–120 sn. **`code != 0` iş hatası DENENMEZ.**
- **Private:** `timestamp` sunucu ofsetiyle (`/open/v1/time`, 300 sn TTL); `_fmt_quantity` aşağı yuvarlar; `place_market_sell` adımı yalnız YÜKLÜ filtre önbelleğinden.
- **B-17:** MicroFlow kendi `aggTrade` soketini açar, MarketData ile birleştirilMEZ.
- **`universe_at()`** → `GET /api/research/universe-at?ts=`; `_MAX_ENTRIES=2000` saat ≈ 83 gün.

## 6. ML / tahmin

- **Bar dayanağı (W3):** `TRAINING_BAR_MINUTES=5`; çıkarım 5m KAPANIŞ barlardan, warmup yoksa tahmini atla (1m YASAK).
- **Artifact:** `ML_MODELS_DIR` varsayılan `/data/ml_models` → Windows'ta cwd sürücüsü (`D:\data\ml_models`); `upside_v3.joblib` var (308 sembol). **Backend'i başka sürücüden başlatmak artifact'ı bulamaz → 503.** `start.ps1` `cd backend` yapar → doğru.
- **I-05:** `feature_version`+`feature_names`+`training_bar_minutes` eşleşmeli; `training_bar_minutes` **yoksa** legacy kabul.
- **ML-05 kapısı:** `atr_pct`, `ret3_pct`, `rsi` — biri None ise tahmin YOK.

## 7. MACD MONITOR

Rapor `outputs/macd_monitor_denetim_raporu.md`; modül `routers/macd_monitor.py`; paneller `/macd-monitor`, `/monitoring`.
- **Trend gücü göreceli ve yönsüz — KANITLA DOĞRU** (OOS 312 sembol · 571.980 gözlem: yönlü formül contrarian, IC −0.049, t −23.8 @30m) → yön skora EKLENMEZ; `dir` tanımlayıcı.
- **C1 tazelik:** M3/M30 WS'de değil, `market.refresh_series()` REST (3m≈75sn, 30m≈1860sn).
- **Cooldown'lar ayrı:** jump ve erken, 30 dk, birbirini bloke etmez.
- **C3 kanıt:** `macd_monitor_alerts` + `macd_evidence_loop` → `/api/macd-monitor/alerts`. **Eşik/ağırlık yalnızca bu kanıtla değişir.**
- **Performans:** `_trend_cache` (B8), `macd_monitor_delta` WS (B9, her 5. pass tam yayın).
- **Snapshot'ın İKİ tüketicisi** — yeni WS mesaj tipinde ikisini de güncelle. Birleştirme: `frontend/app/lib/macdSnapshot.ts` → `mergeMacdDelta`.

## 8. 2026-09-12 denetimi (W1–W8, 10/10 KRİTİK kapandı)

`outputs/denetim_2026-09-12/` (`ANA_RAPOR.md`, `A…J_*.md`, `FIX_W1…W8_*.md`). 195 bulgu; red-team 10 doğrulandı / 2 kısmen / 0 red; test 381→493+ yeşil.
Kapanış: `ML-01`(W3) `D-01`(W2) `F-02`(W4) `G-01`(P1) `C-01/02`(W1) `H-01/02`(W5) `V-01`(W7) `B-01/02`(W8).
**Ders:** W1–W6'da "hepsi kapandı" sanıldı ama `V-01`,`B-01/02` hiç atanmamıştı → **planına değil BULGU LİSTESİNE güven**, parti sonunda ID bazında tara.
Operasyonel: `pytest` özet satırı yazdırmıyor; `couldn't stop thread 'pool-1-worker-N'` zararsız psycopg teardown gürültüsü.

## 9. Frontend

- `reactStrictMode: true` → dev'de effect çift çağrısı; CONNECTING'de `ws.close()` "closed before the connection is established" basar (gerçek hata DEĞİL, 2026-09-14'te bastırıldı).
- Grafik doğrudan Binance TR WS: `NEXT_PUBLIC_BINANCE_WS_BASE` (varsayılan `wss://stream-cloud.binance.tr`, yedek `wss://stream.binance.me`).
- `API_BASE = NEXT_PUBLIC_API_URL || browserOrigin`; rewrite yok. Dağıtımda nginx `/api/`→`backend:8004` — backend erişilemezse nginx 5xx (backend 503'üyle karıştırma).

## 10. Komutlar

- `backend/venv/Scripts/python.exe -m pytest tests/ -q`
- `frontend` içinde `npx tsc --noEmit`
- `python -m py_compile <dosyalar>`
