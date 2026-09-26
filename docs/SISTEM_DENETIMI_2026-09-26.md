# Scalper Agent V4 — Sistem Denetim Raporu

**Tarih:** 2026-09-26
**Kapsam:** Backend (~40.000 satır Python, 55 modül), Frontend (77 TS/TSX), test tabanı, DevOps, dokümantasyon
**Yöntem:** 14 paralel denetim alt-ajanı + kritik iddiaların kaynak koddan ve çalıştırılarak doğrulanması
**Test tabanı:** 97 dosya / 1426 test fonksiyonu / 1 hata (`pywebpush` ortamda kurulu değil, `requirements.txt:9`'da tanımlı)

---

## 1. Yönetici Özeti

Sistem genel olarak **tasarım düzeyinde olgun**: para yazan yolların advisory lock protokolü belgelenmiş, supervisor/restart mimarisi doğru kurulmuş, geç bağlama (`runtime_deps`) sessiz `NameError` sınıfını kökten kapatıyor, yorumlar tarihsel kararları geri okunabilir biçimde kayda geçiriyor, güvenlik tarafında SQL injection/command injection/ssrf/clickjacking alanlarında doğru kararlar verilmiş.

Ancak denetim üç **sistemik** sorun ortaya çıkardı:

1. **Ölü kapılar** — Birden fazla risk/ödül kapısı hesaplanıyor, sonucu sözlüğe yazılıyor, ama karar yolunda **hiç okunmuyor**. `master_surge` risk kapıları, türev/makro veri beslemesi, kalibrasyon çarpanı, `passed` hesabı: bunların hepsi canlı karara bağlı değil. Bu, "kapı varmış gibi görünüp çalışmama" sınıfı ve kod tabanındaki en yüksek etkili sorun.

2. **Doğrulanamayan testler** — Test sayısı yüksek (1426) ve çoğu anlamlı, ancak en kritik iki yol (para hareketi başlatan açılış, cüzdan mutabakatı) yalnız gevşek assert veya kaynak metni taramasıyla "kilitlenmiş". 7 test hiçbir şey doğrulamıyor.

3. **Para mutabakatı kaymaları** — Giriş komisyonu cüzdandan hiç düşülmüyor, çıkışta çift uygulanıyor; cüzdan ile raporlanan PnL sistemli olarak ayrışıyor.

Ayrıca bir **işlevsel regresyon** tespit edildi: `_binance_ticks_configured()` her çağrıda `UnboundLocalError` fırlatıyor, bu yüzden Binance fiyat tick yayını hiç çalışmıyor.

---

## 2. P0 — Doğrulanmış Kritik Bulgular

### 2.1 `_binance_ticks_configured` her çağrıda çöküyor → fiyat yayını tamamen ölü
**Dosya:** `backend/app/main.py:2306-2315`
**Durum:** Çalıştırılarak doğrulandı.

```python
_binance_tick_config_cache: tuple[float, bool] = (0.0, False)   # 2292

async def _binance_ticks_configured() -> bool:                # 2306
    now_ts = time.time()
    if _binance_tick_config_cache[0] > now_ts:                # yerel değişken okunuyor
        return _binance_tick_config_cache[1]
    ...
    _binance_tick_config_cache = (now_ts + 60.0, ok)           # 2315 — global'e yazmıyor
```

Fonksiyon `global _binance_tick_config_cache` bildirmiyor. Python'da atama, aynı isim için yerel kapsam yaratır; satır 2308'deki okuma da aynı yerel ismi okuduğu için `UnboundLocalError` fırlatır. Yürütülerek doğrulandı: `UnboundLocalError: cannot access local variable`.

**Etki:** `binance_price_tick_loop` (main.py:2422) her turda `if not await _binance_ticks_configured()` çağırıyor → istisna `while True`'daki `except Exception` ile yutuluyor → döngü asla ilerleyemiyor. `binance_price` WS mesajı **hiç yayınlanmıyor**. `BinancePositionChartModal.tsx:929` bu mesajı dinlediği için modalın canlı fiyatı güncellenmiyor.

Aynı desenin doğru kullanıldığı yer de mevcut (`runtime.py:1054` `global _llm_last_idle_attempt_at`) — yani bu bir tutarsızlık, kasıtsız sapma.

**Düzeltme:** `async def _binance_ticks_configured()` gövdesinin başına `global _binance_tick_config_cache` ekle.

---

### 2.2 `master_surge` risk kapıları hiçbir karar yoluna bağlı değil
**Dosyalar:** `unified_signals.py:273-303`, `monitoring.py:1061-1137` ve `:1373-1503`

`evaluate_master_surge()` `block_reason` üretir (`CROWDED_LONG_LIQUIDATION_RISK`, `BTC_PANIC_DOWNTREND`) ve `passed=False` yapar. `unified_signals` bunu yalnızca aday sözlüğüne kopyalar. `_notify` ve `_unified_fast_notify_impl` bu alanlara **hiç bakmıyor** — `monitoring.py` içinde `block_reason` okuyan tek satır 2135, o da sadece profil sözlüğüne kopyalıyor.

Üstüne `unified_signals.py:287-292` composite skoru **yalnız `confluence_4way` doğruysa** yükseltiyor. Yani kapı ters yönde çalışıyor: risk nedeniyle elenmesi gereken aday 4'lü teyit taşıyorsa skoru artıyor.

**Etki:** EXTREME_LONG fonlaması veya BTC panik döküşünde radar 100 puan üretse bile bildirim gider ve `auto_paper` pozisyon açabilir.

---

### 2.3 Türev ve makro veri yalnız LLM araç çağrısıyla doluyor → radar'da hep `None`
**Dosyalar:** `unified_signals.py:273-279`, `derivatives_service.py:160`, `macro_sentiment_service.py:102`

`_DERIVATIVES_CACHE` yalnız `get_derivatives_intel()` içinde yazılıyor; tek çağıran `llm_chat._get_derivatives_tool`. `_BTC_COMPASS_CACHE` yalnız `get_btc_compass()` içinde; tek çağıran `llm_chat._get_macro_sentiment_tool`. `main.py` hiçbir yerden çağırmıyor, arka plan döngüsü yok.

Radar 60 saniyede bir tarıyor ama bu cache'ler operatör LLM'ye sormadıkça boş kalıyor → `master_surge.py:505` ve `:540` hiç girmiyor.

**Etki:** -15 puanlık EXTREME_LONG cezası ve BTC panik kapısı **yapısal olarak hiç uygulanmıyor**. Kod doğru, tetikleyici yok.

**Bonus hata:** `_BTC_COMPASS_CACHE` `is_panic_dump` anahtarını taşıyor (`macro_sentiment_service.py:99`), `master_surge.py:541` ise `is_btc_panic` okuyor. Cache bir dolu olsa bile anahtar uyuşmazlığı kapıyı tetiklemezdi.

---

### 2.4 `microflow.refresh_depth` yalnız LLM aracında → depth/whale duvarı radar'da hep `None`
**Dosya:** `microflow.py:323`, tek çağıran `llm_chat.py:2038`

`velocity.py:815, 2061` yalnız `microflow.start(symbol)` çağırıyor. `get_snapshot` (microflow.py:371-386) `bids`/`asks` boş olduğu için `depth_try`, `wall_bid_try`, `wall_ask_try`, `ladder_asymmetry` hepsi `None` dönüyor.

**Etki:** 1s/5s bar ve CVD gerçek (canlı), depth tarafı ölü. `data_ready` bayrağı sembol değişiminde sıfırlanmadığı için (microflow.py:147) yeni sembole geçişte "veri yok" durumu gözlenemez.

---

### 2.5 Giriş komisyonu cüzdandan hiç düşülmüyor, çıkışta çift uygulanıyor
**Dosyalar:** `database.py:5166-5173` (açılış), `database.py:5501-5508` (kapanış), `auto_paper.py:473-481`

```python
# Açılış (auto_paper.py)
max_cost = order_value / (1 + commission_pct)      # komisyon İÇİNDEN karşılanıyor
# DB (database.py:5166)
debit = order_value * (1 + commission_pct)         # ...ama DB order_value'ın TAMAMINI düşüyor
```

Açılışta `order_value_try = order_value / 1.0015` yazılıyor, DB ise `order_value × 1.0015` düşüyor. Kapanışta `proceed = exit_price × quantity × (1 - commission)`.

Tam tur dönüşünde: net kayıp **-%0.45**, beklenen **-%0.30** (iki bacak komisyon). Fark, giriş komisyonunun `debit`'te bir kez daha sayılmasından.

**Etki:** Cüzdan ile raporlanan PnL sistemli olarak ayrışıyor — her işlemde `order_value × %0.15` fazla para kasada kalıyor ama PnL'de düşülüyor. `database.py:361-373` mutabakat sorgusu komisyonu hiç hesaba katmıyor, bu yüzden startup'ta bakiye şişer. Kâr kilidi `min_net_exit_pct` ile %0.355 net hedeflerken gerçek maliyet %0.45.

---

### 2.6 `reconcile_portfolio` advisory lock almadan cüzdayı üstüne yazıyor
**Dosya:** `database.py:551-597`

Dosyanın kendi dokümantasyonu (satır 240) para yazan her yolun `pg_advisory_xact_lock` ile korunduğunu söylüyor. Lock'lar gerçekten şurada: `commit_open_position:2731`, `commit_close_position:2772`, `open_auto_paper_trade:5116`, `close_auto_paper_trade:5483`.

`reconcile_portfolio` **hiç lock almadan** TRY satırını mutlak bir değerle eziyor (satır 596). `reset_trading_data:410-424` de aynı şekilde lock'suz `DELETE FROM virtual_wallet` + `DELETE FROM positions` yapıyor.

**Etki:** Eşzamanlı bir `commit_open_position` çalışırken reconcile'in hesapladığı `after` değeri açılışın debiti uygulanmadan yazılır → **o açılışın borcu cüzdadan silinir.** Reset'te benzer şekilde pozisyon açık kalır ama bakiyesi sıfırlanır.

---

### 2.7 `GET /api/research/ma-cascade-shadow` her çağrıda 500 döner
**Dosya:** `routers/reports.py:455-460`

```python
"enabled": config.SMA_CASCADE_SHADOW_ENABLED,
"max_sequence_minutes": config.SMA_CASCADE_MAX_SEQUENCE_MINUTES,
```

`config.py` içinde `SMA_CASCADE` **sıfır** tanım (doğrulandı: `grep -c SMA_CASCADE config.py` → 0). Korumalı olmayan öznitelik erişimi → `AttributeError` → 500. `docs/api-reference.md:157-166` bu endpoint'i çalışan bir araştırma yüzeyi olarak belgeliyor. Koruyan test yok.

---

### 2.8 LLM paper trade aracı admin kapısını `AttributeError` ile 500'e düşürüyor
**Dosyalar:** `main.py:3527-3529`, `routers/llm_chat.py:2493, 3234`

```python
async def llm_open_paper_trade(payload: dict, request: Request = None):
    _require_admin(request)     # request=None → NoneType.headers → AttributeError
```

Tool executor `request=None` ile çağırıyor. Her LLM paper açılışı 500 fırlatıyor. `test_w18_runtime_residual.py:718` bu yolu `request=None` **ve** anonymous ile test ediyor → kırılganlık testlerde yeşil görünüyor.

Ters yönde de risk var: `request=None` guard'ı eklenirse kapı kalkar ve **herhangi bir oturumlu kullanıcı** sohbetle pozisyon açabilir.

---

### 2.9 `velocity` pozisyon limiti TOCTOU açığı, varsayılan sınırsız
**Dosya:** `routers/velocity.py:2031-2046`

```python
if vel_max > 0:
    vel_open = sum(1 for pos in analyzer.positions.values()
                   if ...source == "velocity_auto")
    if vel_open >= vel_max:
        return {... "reason": "pozisyon_limiti_dolu"}
```

`VELOCITY_AUTO_MAX_OPEN_POSITIONS` default `0` = sınırsız. Sınırlı olsa bile sayım tamamen bellek içi ve kilit dışında; `open_position` async DB işlemleri sürerken ikinci bir görev aynı sayımı yapabilir. `manual-scan` endpoint'i (velocity.py:1402) aynı fonksiyonu çağırıyor ama otonom döngünün havuz filtresini uygulamıyor.

---

### 2.10 `_unified_fast_last` kalıcı değil, cooldown atlatması var
**Dosyalar:** `routers/monitoring.py:1149, 1355, 1382-1384, 1439`

`_notify` cooldown'u `notified_symbols` üzerinden uygular (satır 1148). `unified_fast_notify` kendi `_unified_fast_last` haritasına bakar ve `notified_symbols`'a **yazar ama okumaz** (satır 1439). İki ayrı zaman dünyası → 5-30 dakika bandında mükerrer bildirim.

`_unified_fast_last` ne persist ediliyor ne restore ediliyor (`_persist_runtime_state:178-219` yazmıyor, `reset-notifications:3030-3037` temizlemiyor) ve hiç budanmıyor. Restart sonrası tüm sembollerde 30 dakika cooldown'suz ateşlenebilir.

---

## 3. P1 — Yüksek Öncelikli Bulgular

### 3.1 Para / muhasebe

| # | Dosya | Bulgu |
|---|---|---|
| 1 | `auto_paper.py:765` + `:830` | `breakeven_activated` olduğunda sabit `stop_loss` kontrolü **önce** çalışıyor → kâr kilidi fiilen devre dışı, daha düşük fiyattan kapanma |
| 2 | `auto_paper.py:718, 737` | `max_hold` ve `symbol_deactivated` çıkışları bayat ticker fiyatından kapanıyor (tazelik kapısı yalnız SL/TP'de) |
| 3 | `analyzer.py:458-504` | `velocity_protection_armed` hiçbir yerde persist edilmiyor; `load_positions` restore etmiyor → restart sonrası sözleşme bozuluyor |
| 4 | `routers/monitoring.py:1201-1207` vs `:1446-1452` | "Hedef ilk girişten çapalanır" kuralı iki yerde farklı uygulanıyor; hızlı yol mevcut kaydı üstün yazıyor |
| 5 | `routers/velocity.py:775-789` | `microflow.get_snapshot` global tek sembol üzerinden okuyor; taranan tüm adaylara **aynı** sembolün mikro-yapısı yükleniyor, sıralama anahtarı `velocity_score × micro_mult` → yanlış aday seçimi |
| 6 | `circuit_breaker.py:45-46, 74-78` | `_paused` sözlüğü kilitsiz, tüm dict `set_llm_setting` ile yazılıyor → lost update; `resume` `_ensure_loaded()` çağırmıyor → restart sonrası 404 |
| 7 | `routers/velocity.py:1052, 1297` | `getattr(config, "AUTO_PAPER_SL_PCT", 1.5)` — bu isim config'de **yok** (sadece `AUTO_PAPER_SL_PCT_DEFAULT`), yani env'deki `AUTO_PAPER_SL_PCT` sessizce yok sayılıyor |

### 3.2 Doğruluk / mantık

| # | Dosya | Bulgu |
|---|---|---|
| 8 | `routers/monitoring.py:1083` | Varsayılan ayarda **iki kapı** çelişiyor: ham 1400 ve panel 71.5 (= ham 1730). 1400-1730 bandı listede görünüyor, bildirilmiyor. "TEK EŞİK" ilkesi varsayılanta sağlanmıyor |
| 9 | `routers/monitoring.py:1069, 1072, 1162` | `float(c.get("velocity_score", 0) or 0)` korumasız; tek bozuk satır 60 saniyelik turun tamamını düşürüyor. `combined_radar._num` aynı durumda NaN'ı doğru eliyor — tutarsız |
| 10 | `ml_forecast.py:288` | Eğitim MFI'si `neg_sum==0` iken NaN üretiyor, çıkarım 50.0/100.0 döndürüyor. Parity testi bu kolonu kapsamıyor |
| 11 | `master_surge.py:397-407` | `calculate_adaptive_targets` ATR'yi yüzde sanıyor; gerçek 5m ATR% ≈ 0.35 → `max(1.2, ...)` → **TP1 pratikte sabit %1.2** |
| 12 | `master_surge.py:60-76` | Fiyat 0'a düşerse `bid_px or 1.0` fallback → derinlik TRY cinsinden sayılıyor, `MIN_DEPTH_TRY=5000` kapısı sahte geçiliyor |
| 13 | `routers/velocity.py:1067-1074` | Aynı barda high ve low ikisi de eşiği geçerse **daima TP** sayılıyor → sistematik iyimser bias, kalibrasyonu ters yönde eğitiyor |
| 14 | `signals.ts:262-268` vs `technical_analysis.py:142-143` | CRSI backend'de fiyat seviyesiyle, frontend'de 1-bar değişimle sıralıyor — aynı isim, iki farklı sayı. `signals.ts:3` yorumu sapmayı yalnız mum formasyonları için kabul ediyor |
| 15 | `signals.ts:211-223` | MFI: frontend `negative===0 → 100` koşulsuz, backend `pos>0` kontrolü yapıyor → `positive===0 && negative===0` durumunda 100 vs 50 |
| 16 | `surge_learning.py:90-108` | `refresh_biases` **tüm geçmiş** radar verisini bugünkü skora geri projeliyor (walk-forward yok) + `total_samples` iki farklı evreni (gerçek işlem + bildirim adayı) topluyor |
| 17 | `calibration.py:104-116` | `entry_context["candles"]` aranıyor ama `analyzer.py:1274-1284` bu anahtarı hiç yazmıyor → `volume_band` daima `"unknown"`, `multiplier_for` daima 1.0. Kalibrasyon canlıda ölü |
| 18 | `calibration.py:49` vs `monitoring.py:2545` | UTC kovaları vs UTC+3 gün filtresi → kova istatistikleri 3 saat kaymış |
| 19 | `routers/monitoring.py:2617-2621` | 60 dakikalık değerlendirme penceresi sabit; 15dk ufuklu bildirimler sistematik dezavantajlı sayılıyor |

### 3.3 Güvenlik

| # | Dosya | Bulgu |
|---|---|---|
| 20 | `main.py:361-362` + `docker-compose.yaml` | Login hız sınırı `X-Real-IP` başlığına güveniyor; saldırgan her istekte farklı IP göndererek sınırı atlatıyor. `CORS allow_headers`'ta `X-Real-IP` izinli |
| 21 | `security.py:131-133` | `_user_session_versions` sözlüğünde kullanıcı yoksa `expected_version is None` → `sv` kontrolü **atlanıyor**. Silinen/askıya alınan kullanıcının token'ı 12 saat geçerli kalıyor |
| 22 | `main.py:707-710` | Rol düşürme koruması yalnız *kendini* koruyor. Başka admin'in rolü düşürüldüğünde token'daki imzalı `role` değişmiyor → 12 saat tam admin yetkisi |
| 23 | `main.py:1113-1130` | WS'te Origin doğrulanmıyor, subprotocol yansıtılmıyor |
| 24 | `main.py:3976-3979` | `pg_restore` yol kontrolü `startswith` ile; `os.path.realpath` yok, `islink` reddi yok |
| 25 | `routers/llm_chat.py:2197-2198` | `get_real_account` **global** Binance anahtarını okuyor — `main.py:290` yorumunun iddia ettiği kullanıcı izolasyonunu ihlal ediyor |
| 26 | `routers/llm_chat.py:3022, 3093` | `body.get("username")` ve `body.get("user_role")` token'daki değeri **eziyor** → istemci admin persona'sı tetikleyebilir |
| 27 | `llm_analysis.py:408, 613-617` + `llm_chat.py:2650` | `max_tokens` istemciden geliyor, sunucu tavanını eziyor (`int(...) or 4096` negatif değeri de geçirir) |
| 28 | `llm_chat.py:2605-2606` | `update/remove_market_alert` LLM'in verdiği `alert_id`'yi sahiplik denetimi olmadan kabul ediyor |
| 29 | `docker-compose.yaml` | `SCALPER_ENV`/`ENVIRONMENT` hiç ayarlanmamış → `PRODUCTION_MODE=False` → zayıf admin parolası engeli üretimde devre dışı |
| 30 | `binance_tr_private.py:128, 161, 168` | Emir POST'u idempotency anahtarı olmadan yeniden deneniyor; timeout sonrası borsa emri aldıysa ikinci kez gönderiliyor |
| 31 | `binance_tr_public.py:72` | `Retry-After` header'ı `REST_BACKOFF_MAX_SEC` (4 sn) ile kırpılıyor; Binance 429'da dakikalar beklettiğinde ban tırmanması garanti |
| 32 | `binance_tr_public.py:139-140` | 418 IP-ban geri çekilmesi 30/60/90 sn lineer; ban dakikalar-günler sürüyor |
| 33 | `binance_tr_private.py:78-81` | Private 429 geri çekilmesi `Retry-After` okumuyor, throttle/semaphore yok |
| 34 | `binance_tr_private.py:267-279` | `minNotional` uygulanmıyor; 5 TRY'lik toz bakiye 502 alıyor |

### 3.4 Dayanıklılık / async

| # | Dosya | Bulgu |
|---|---|---|
| 35 | `main.py:337, 339, 672, 702, 889` | `async def` içinde PBKDF2-200k senkron çağrı (~100-300 ms event loop bloke). `auth_login` `to_thread` kullanıyor, bu 5 nokta kullanmıyor |
| 36 | `api_common.py:212` + `main.py:1069-1074` | Shutdown sırasında respawn yarışı: iptal edilen görev `asyncio.gather` bitmeden yeni task yaratıyor; `microflow.stop()`/`close_db()` çalışmışken yeni WS açılıyor |
| 37 | `routers/llm_chat.py:1662` | `_historical_snapshot_at` async içinde `calculate_snapshot` senkron çalıştırıyor (7 timeframe × ~20 gösterge). Kod bunu bile biliyor (satır 2723 yorumu: "153 ms ölçüldü"), `stream_chat` düzeltilmiş, bu yol alınmamış → ~40 sembol × 153 ms = ~6 sn blok |
| 38 | `llm_analysis.py:903, 917` | Streaming'de her 1 sn'de yeni thread; `reader.cancel()` thread'i durdurmuyor, socket açık kalıyor |
| 39 | `main.py:3982-3984` | `pg_dump` ve `pg_restore` arasında karşılıklı dışlama kilidi yok |
| 40 | `routers/maintenance.py` `__main__.py:1062-1066` | `auto_paper` / `macd_monitor` stop çağrıları `except Exception: pass` içinde; hata olursa gerçek paper trade döngüsü açık kalıyor |
| 41 | `state.py:10-11` | Global singleton'lar import anında `config.SYMBOLS` ile donduruluyor; `bootstrap_symbol_activity` sonradan eziyor — sessiz yarış |

---

## 4. P2 — Orta Öncelikli / Diğer

### Frontend

| # | Dosya | Bulgu |
|---|---|---|
| 42 | `binance-tr/page.tsx:2035, 2163, 2328, 1765` | Gerçek parayla ilgili 4 modalda focus trap, Escape ve `aria-label` yok. `monitoring/page.tsx:307-336` doğru referans — kopyalanmalı |
| 43 | `globals.css:282, 17` | `.table-scroll > table { min-width: max-content }` + `body { overflow-x: hidden }` → mobilde kolonlar kırpılıyor. DESIGN.md "sayfa yatay taşmasın" diyor, `hidden` gizliyor |
| 44 | `binance-tr/page.tsx:397-398` | PnL `pnl.ts`'yi atlayıp brüt `(price - cost) * total` kullanıyor → aynı pozisyon Binance TR sekmesinde brüt, Portföy'de net görünüyor |
| 45 | `chat/page.tsx:482-498` | `res.ok` kontrolsuz fetch + `.catch(() => undefined)` → boş liste, neden görünmüyor. 6 sayfada tekrar ediyor. `api.ts:52`'de `getJSON` var |
| 46 | `chat/page.tsx:517-550`, `MultiChartCard.tsx:646` | `setInterval` yerine `useVisibleInterval` kullanılmamış; sekme gizliyken de çalışıyor. MultiChartCard her 6 sn'de 14 indikatörü yeniden hesaplıyor |
| 47 | `reports/page.tsx:134-138` | `Promise.all` içinde `.json()` — biri 500 dönünce tüm yükleme düşüyor, hangisinin çalıştığı belli olmuyor |
| 48 | `reports/page.tsx:9-18` | `format.ts` tek kaynak ilan edilmiş ama sayfa kendi `num`/`fmtDt`'ini taşıyor; `new Date().toLocaleString("tr-TR", {day,month})` ile farklı çıktı üretiyor |
| 49 | `streamChat.ts:4` | `StreamEvent.data: any` — 8 alan tüketim zinciri, backend alan adı değişirse derleme hatası vermez, `NaN` yayılır |

### API sözleşmesi

| # | Dosya | Bulgu |
|---|---|---|
| 50 | `ChatSettingsPanel.tsx:30-37` ↔ `main.py:2232-2236` | **TTS ayarları kalıcı değil.** Frontend `tts_rate`/`tts_pitch` gönderiyor, backend kaydetmiyor. Kullanıcı "KAYDEDİLDİ" görüyor, ayar sessizce 0'a dönüyor |
| 51 | `main.py:2391-2399` ↔ `binance-tr/page.tsx:322` | `binance_account_update` WS mesajı `user_id` taşıyor ama `ConnectionManager.broadcast` filtrelemiyor → **çok kullanıcılı kurulumda herkes herkesin bakiyesini görüyor.** Frontend bu mesajı zaten dinlemiyor (ölü) |
| 52 | `reports/page.tsx:1463` ↔ `velocity.py:1200` | `key={c.candidate_id}` — backend satır `id` döndürüyor. React duplicate key uyarısı + eylemler yanlış kaydı hedefler |
| 53 | `ws_runtime.py` ↔ `liveSocket.ts` | 3 backend mesaj tipi tüketici yok: `tickers` (**saniyede bir ölü trafik**), `binance_account_update`, `trade_repair_completed`. Ayrıca frontend `price_tick`/`bookTicker`/`depth` dinliyor, backend yayınlamıyor → tahta paneli hiç güncellenmiyor |
| 54 | `routers/chart_forecast.py:88-106` | `fresh=false` cache araması timeframe'i hiç dikkate almıyor → 5m'de üretilmiş cache 15m sekmesinde dönebilir |
| 55 | `main.py:1707` | `min_atr_pct` backend'de ×100 (yüzde), frontend küçük ölçek bekliyor (ölü alan, yeni tüketici için 100× hata riski) |
| 56 | `charts/page.tsx:1500-1505` | `Number(expected_price) || 0` — null hedef 0'a çiziliyor; "veri yok" ile "0 ₺" ayırt edilemiyor |
| 57 | `main.py:2046-2110` ↔ `portfolio/page.tsx:20-31` | Hata yolunda `entry`/`current` `float()` dönüşümü olmadan dönüyor → `entry: null` → `Number(null)` → 0 |

### Performans / bellek

| # | Dosya | Bulgu |
|---|---|---|
| 58 | `routers/velocity.py:657-664` | N+1: tarama havuzundaki **her** sembol için ayrı `get_symbol_target_state` → 2 profil × ~110 sembol = **220 DB round-trip** per tur, `psycopg` `max_size=8`. `strategy_loop` (5 sn stop kontrolü) bloklanıyor. `get_all_symbol_target_states` (database.py:5078) **zaten var** |
| 59 | `unified_signals.py:57, 68-83` | `_unified_notified_at` / `_unified_notified_score` hiç budanmıyor. `monitoring.py`'deki karşılıkları 500/250 sınırıyla budanıyor — burada yok |
| 60 | `routers/macd_monitor.py:120-151` | Dokuz modül sözlüğü; `_compute_pass_locked:1367-1372` sadece 3'ünü temizliyor. `_jump_alerted_at`, `_early_alerted_at`, `_early_last_gap`, `_last_rest_refresh`, `_rest_refresh_failures` kalıcı kalıyor. `_trend_cache` sembol başına ~1.5-3 KB |
| 61 | `main.py:1546, 1554` | `ticker_24h()` **iki kez** çağrılıyor (weight 80 her biri), `radar_loop` 60 sn'de bir → **saniyede 160 weight**. `velocity.py:316` doğru deseni uygulamış (`_ticker_rows` parametresi), `main.py` uygulamamış |
| 62 | `routers/monitoring.py:2029-2046` | `_check_pending_targets`: sembol başına 3 statement + COMMIT, seri await. 20 pending × 60dk pencere = 60 executor işi, 2-3 sn havuz kilidi |
| 63 | `routers/runtime.py:127-219` | `ws_broadcast_loop` her saniye tüm tickers + tüm pozisyonları yeniden serileştiriyor; `send_json` **her istemci için ayrı** JSON dump |
| 64 | `ws_runtime.py:22-35` | Backpressure yok — `gather` tüm göndermeleri bitene kadar bekler, 0.75 sn timeout biriktikçe döngü yavaşlıyor. `ws_live_candles.py:98` her kline'da `create_task(broadcast(...))` → görev patlaması riski |
| 65 | `market_data.py:865-872, 799, 819, 497` | `dict(self.tickers)` tam kopya **4 ayrı yerde**, her kline olayında → 70 elemanlı dict kopyası, ~100 KB/s |
| 66 | `derivatives_service.py:41-46` | Ağ hatası "vadeli piyasada listeli değil" olarak **90 sn cache'leniyor**; `master_surge.py:505` risk kapısı fail-open |
| 67 | `unified_signals.py:278, 361` | Türev önbelleği TTL'siz doğrudan okunuyor (90 sn bayat kontrolü atlanıyor) |
| 68 | `database.py:5299-5300` | `auto_paper_trades` gün filtresi OR koşulu indexlenemez; rapor uçları `limit=None` ile `SELECT *` çekiyor, 3 ayrı yerde tekrar ediyor |
| 69 | `routers/velocity.py:813-817` | `microflow.start()` aday başına **seri** await → tur başına 20 WS bağlantısı, ~7 sn blok. `asyncio.gather` gerekir |
| 70 | `analyzer.py:1019` | Her giriş denemesinde `database.load_positions()` tam tablo okuması |
| 71 | `routers/monitoring.py:1676-1694` | Unified modda rising push **başarısız olsa bile** `note_notified` yazılmıyor → aynı sembol tekrar push edilebilir. Radar yolu (`:1294-1298`) bu kuralı doğru uyguluyor |

### DevOps / altyapı

| # | Dosya | Bulgu |
|---|---|---|
| 72 | `backend/scripts/run_postgres_migration.py:45` vs `database.py:264-266` | Entrypoint migration'ı 001/002 okuyup sha yazıyor, `init_db` beş dosyayı okuyup **farklı** sha hesaplıyor → her restart'ta tam DDL + ACCESS EXCLUSIVE kilit yarışı. `005_user_binance_keys.sql` yalnız ikinci yolda oluşur |
| 73 | Repo kökü | ~2.4 MB ham container log'u (3 dosya) kökte duruyor, `.gitignore` kapsamıyor, **gerçek kullanıcı IP'leri ve cihaz UA'ları** içeriyor. Credential sızıntısı yok (grep doğruladı) |
| 74 | `docker-compose.yaml` | Hiçbir serviste `mem_limit` / `cpus` / `deploy.resources` yok. Sembol evreni 309'a çıkmış durumda |
| 75 | `docker-compose.yaml` | Secret'lar plaintext `environment:` ile veriliyor; `*_FILE`/Docker secrets yok |
| 76 | `nginx/default.conf:84-91` | `/ws` bloğunda `X-Real-IP`/`X-Forwarded-For` yok (diğer bloklarda var) → WS bağlantılarında istemci IP'si kayboluyor. `proxy_send_timeout`/`connect_timeout` tanımsız |
| 77 | `nginx/default.conf:30` | HSTS `includeSubDomains` + 1 yıl max-age, `preload` yok. TLS Coolify/Traefik'te sonlanıyor — bu katman bağımlı karar |
| 78 | `nginx/default.conf` | CSP yok (Next.js inline stiller nedeniyle — kabul edilebilir, `report-only` düşünülebilir). `/_next/static` için immutable cache bloğu yok |
| 79 | `nginx/default.conf` | Rate limit yalnız `/api/auth/login` ve `/api/`'de; `/ws` korumasız |
| 80 | `app/migration_monitor.py` | Ölü kod: `fetch_target_counts` **daima `{}`** dönüyor, `run()` statik "completed" yazıyor. `/api/migration/*` uçları yanıltıcı 200 döner |
| 81 | `database.py:299-330` | ~12 ek `ALTER TABLE ADD COLUMN IF NOT EXISTS` init_db'ye gömülü, versiyonsuz. `lock_timeout=5s` altında sessizce başarısız olabilir |
| 82 | `database.py:2635-2726` | `backfill_replay_parity_observations` index'i `try/except: pass` ile kuruyor → index kurulamazsa her yeniden çalıştırmada mükerrer satır |
| 83 | `database.py:2767, 2811, 2616` | Commit sonrası embedding enqueue `except Exception: pass` → kalıcı iş kaydı sessizce düşüyor |
| 84 | `database.py:721-725, 4480-4489, 1614-1634` | Kayıt silen yollarda `except Exception: pass` → yarım silme, sessiz veri kaybı |
| 85 | `database.py:5464-5470` | `update_auto_paper_trailing` `rowcount` kontrol etmeden her zaman `True` dönüyor (aynı modülde `close_auto_paper_trade` doğru davranıyor) |
| 86 | `embedding_worker.py:116-120` | `_persist_embedding` üç statement'ı açık transaction bloğu olmadan → asyncpg implicit commit, yarım belge kalıcı |
| 87 | `database.py:3588-3615` | `read_only_query`: LIMIT sarmalama yalnız en dıştaki ifadeye uygulanıyor (recursive CTE/setops sızabilir), sütun allowlist yok (JSONB alanlar LLM'e sızıyor) |
| 88 | Kök dizin | `apply_edits.mjs` (24 KB), `RUNME.txt`, `EXECUTE.txt`, `cleanup_list.txt`, `run_steps.txt` — script kendini silmeyi amaçlıyor ama hâlâ duruyor |
| 89 | `frontend/package.json` | `engines` alanı yok → Node sürüm sözleşmesi tanımlanmamış (CI `node-version: 20` sabit) |
| 90 | `.gitignore` | Eksik: genel `*.log`, `*-all-logs-*.txt`, `.commandcode/`, `.workbuddy-ai/` |

---

## 5. Test Kalitesi

### Ölçümler

| Metrik | Değer |
|---|---|
| Test dosyası | 97 |
| Test fonksiyonu | **1426** |
| Toplam assert | ~3186 |
| `assertTrue(True)` placeholder | 4 |
| Koşulsuz geçen (tautolojik) assert | 2 |
| `inspect.getsource` kaynak-metni testi | **41 kullanım / 8 dosya** |
| Mock/patch/monkeypatch | 637 |
| `conftest.py` | **yok** |
| Frontend test dosyası | **0** |
| CI kalite kapısı | yalnız pytest + typecheck + build |
| lint/coverage/pre-commit | **0** |

### Bulgular

| # | Dosya | Bulgu |
|---|---|---|
| 91 | `test_audit_fixes.py:19-29` | **Totoloji:** test, testin kendi içine gömülü geçici `positive_leg` yardımcısını doğruluyor, `app` koduna hiç dokunmuyor. `place_paper_order` OCO doğrulaması silinse test yeşil kalır |
| 92 | `test_m4_database_fixes.py:141` | `assert status in ("opened", "error")` — **para hareketi başlatan testin kendisi her koşulda geçiyor.** Cüzdan bakiyesi düşülmeden "opened" dönse yakalamaz |
| 93 | `test_w20_residual_extras.py:37-41` | `if source:` koruması — `hasattr` yanlışsa test assert almadan yeşil geçiyor |
| 94 | `test_regressions.py:155-165` | 3 test adı sözleşme veriyor, gövde `assertTrue(True)`. `test_ws_live_candles.py:249` aynı — 5 bozuk input deneyip doğrulama yok |
| 95 | `test_m6_source_contracts.py` (6/6), `test_quality_gates.py`, `test_w7_reconcile_parity.py:160-190` | Kaynak metni taraması. Yeniden adlandırma/yorum kaydırma testi kırar, hiçbir işlevsel regresyonu yakalamaz |
| 96 | `test_w6_money_math.py:256-279` | Frontend/backend komisyon eşitliği **yalnız regex ile** doğrulanıyor — `pnl.ts` hesabı yanlış olsa test yeşil |
| 97 | `test_m1_monitoring_fixes.py:387` vs `test_w10:243`, `test_w9:107` | CI'da yapay bekleme (`sleep(30)`, `sleep(0.15)` + thread join) → flake üretici |
| 98 | Proje geneli | `conftest.py` yok; `database._run_db` modül globali testlerde doğrudan atanıyor (test_m4:79, test_w7:86, test_database_purity:62, test_w19:95) → `setUp` sonrası hata `tearDown`'ı atlayabilir, sıra bağımlılığı |
| 99 | `pytest.ini` | `filterwarnings = ignore::DeprecationWarning` tamamen susturuyor; `pytest-timeout` yok → sonsuza kadar bekleyen test CI job'ı asılı tutar |
| 100 | `test_security_behavior.py:91, 103, 121` | `asyncio.run(update_config(...))` ile router fonksiyonlarına doğrudan çağrı → FastAPI DI/wiring katmanı hiç sınanmıyor. `TestClient` ile en az bir test gerekir |

### Kapsama boşlukları (kritik dallar)

- Cüzdan mutabakatı (açık/kapalı bakiye toplamı) — **test yok**
- `max_open_positions` eşik davranışı — test yok
- Stop/TP gap-through (`min`/`max` fill) yönleri — test yok
- `_binance_ticks_configured` — test yok (P0 regresyonu bu yüzden yakalanmadı)
- `evaluate_master_surge` bütünsel (yalnız `evaluate_layerN` ayrı test ediliyor)
- `MicroFlow` sınıfının kendisi (yalnız `_open_velocity_position` tarafı mock'lanıyor)
- `deliver_web_push` 410 Gone abonelik temizliği — **hiç test yok**
- `unified_fast_notify` restart sonrası davranışı — test yok
- `crsi`/`mfi` backend-frontend parity — test yok
- Frontend PnL matematiği — test yok

---

## 6. Dokümantasyon Tutarsızlıkları

| # | Belge | Belge ne diyor | Kod ne yapıyor |
|---|---|---|---|
| 101 | `docs/LIVE_PARITY_REPLAY.md:3-6` | "Aktif `BB_MFI_MEAN_REVERSION` ayarlarını dondurur" | Strateji 2026-09-04'te kaldırılmış; `ACTIVE_STRATEGY` config'de **yok**. `run_portfolio_backtest.py:47` `SystemExit`, `live_parity_snapshot()` 25 `getattr` ile `AttributeError`. Belgedeki **her komut** çöker |
| 102 | `SCALPER_TRADE_POLICY.md:13` | "Spread %0.15 üzerinde olmamalı" | `LLM_MAX_ENTRY_SPREAD_PCT` default **1.0** (config.py:588). Ayrıca `llm_chat.py:1712, 1738` LLM'ye ayrı kapı olarak `0.25` veriyor — üç farklı değer |
| 103 | `README.md:84` | "`BACKTEST_ASSUMED_SPREAD_PCT` ince ayar" | `config.py`'de **yok**; yalnız ölü `run_portfolio_backtest.py:74` okuyor. Kullanıcı `.env`'e yazarsa etkisiz |
| 104 | `config.py:312, 316-334` | "`sl_pct` = `AUTO_PAPER_SL_PCT_DEFAULT` (aşağıda, **%3.0**)"; "RR_MIN=0.6 + SL=%3.0 → hedef ≥ %1.8" | Gerçek değer **1.5** (config.py:615). `RR_MIN=0.6` + SL=%1.5 → hedef ≥ %0.9 gerektirir. **R/R kapısı belgelenenin 2 katı gevşek** — para eşiği |
| 105 | `.env.example:10-13` | 4 A2A değişkeni | `backend/app/` altında A2A geçen **hiçbir Python dosyası yok**. Modül tamamen kaldırılmış, 4 ölü satır kalmış |
| 106 | `README.md:113` | "The backend is deliberately paper-only (`LIVE_TRADING=false`)" | `LIVE_TRADING` `backend/app/` içinde **hiç okunmuyor**. Gerçek kapı: `ENABLE_REAL_BINANCE_SELL` env (system.py:86) + DB'deki `user_binance_keys.real_sell_enabled`. Güvenlik yanlış değişkene bağlanmış |
| 107 | `README.md:31-42` | 7 modüllü API tablosu | `routers/` altında 11 dosya, 9 kayıt. Eksik: `monitoring`, `macd_monitor`, `auto_paper`, `chart_forecast`, `llm_position_tools`. **Sistemin en kritik parçası (monitoring radar) hiç belgelenmemiş** |
| 108 | `SCALPER_TRADE_POLICY.md:24` | "varsayılan 30 dakikalık cooldown" | `LLM_REENTRY_COOLDOWN_SEC` = 30 dk (zarar), `LLM_PROFIT_REENTRY_COOLDOWN_SEC` = **5 dk** (kâr). Ayrım belgede hiç anılmıyor — kârlı çıkışta 6 kat hızlı geri giriş |
| 109 | `LLM_FORECAST_JOURNAL.md:13` | Tek yön eşiği: min %0.15, ATR türevli | `forecast_learning.py:147` round-trip maliyet tabanı uyguluyor, `llm_chat.py:679` **uygulamıyor** → 1000 TRY'de %0.40'lık maliyet içi hareketler "yön" sayılıyor |
| 110 | `docs/AUDIT_FIX_REPORT_2026-08-25.md:4, 127` | "136/136" ve "175/175 OK" | Aynı rapor içinde iki farklı sayı; gerçek 1426. `TESTLER.md` ise PUMP araştırma raporu — test komutu içermiyor |

### Doğrulanmış **doğru** olanlar (kayıt altına alındı)

- Portlar tutarlı: README `8004`/`3004` ↔ `start.ps1` ↔ `package.json`.
- `VELOCITY_PROFIT_LOCK_PCT = 0.01` **doğru**: `analyzer.py:500` `max(0.01/100, min_net_exit_pct(...))` — sabit taban %0.01, asıl taban round-trip maliyeti (~%0.355). Önceki denetimde "50 kat düşük" denmişti, **bu yanlıştı**; yalnız `config.py:273` yorumu yanıltıcı.
- UI hata metinleri kaliteli: `frontend/app/**` içinde `AttributeError`/`NoneType` sızıntısı yok.
- `dangerouslySetInnerHTML`, `eval`, localStorage'da token, URL'de token — **yok**.
- Sembol formatı `/open/v1` yolunda tutarlı (`BTC_USDT` ↔ `BTCTRY` normalize).
- HMAC imza doğru; secret loglanmıyor, istemciye dönmüyor.
- Public HTTP sağlığı iyi: 15 sn timeout, jitter'lı üstel backoff, 429/5xx/418 ayrımı, paylaşılan semaphore.
- WS yeniden bağlanma sağlam: ping/pong, host rotasyonu, üstel backoff, nesiller arası bekleme, boşluk onarımı, bounded tape.
- `runtime_deps` geç bağlama deseni sessiz `NameError` sınıfını kökten kapatıyor.
- Supervisor restart mimarisi (`coro_factory` zorunluluğu, `MAX_BACKGROUND_RESTARTS`) doğru.
- `CancelledError` bilinçli yeniden fırlatılıyor (5 döngüde).
- CI prod Python'u (3.11) doğru hedefliyor, prod ile aynı DB imajını kullanıyor.
- `requirements.txt` `==` ile sabit, `package-lock.json` commit'li, CI `npm ci` kullanıyor.
- Log rotasyonu `x-logging` anchor'ı ile tüm servislerde tanımlı.
- `HARD_STOP_LOSS_PCT=0.012` / `SPOT_PROFIT_TARGET_PCT=0.01` README ile birebir tutarlı.
- `DESIGN.md` kodla örtüşüyor (320px/768px/44px/route listesi).

### Ölü kod / ölü ayar

| Öğe | Kanıt |
|---|---|
| `combined_radar.build_unified_envelope` / `build_combined_candidates` | Canlı yolda çağıran yok |
| `AUTO_PAPER_SL_PCT` (`getattr` ile okunuyor, config'de yok) | 3 nokta, hep 1.5 dönüyor |
| `VELOCITY_CALIBRATED_HIT_PCT = 19.3`, `VELOCITY_BASE_RATE_PCT = 1.97` | Sabitler, hiçbir hesaba katılmıyor |
| `migration_monitor.fetch_target_counts` | Daima `{}` |
| `SMA_CASCADE_*` (4 değişken) | config'de yok, endpoint 500 veriyor |
| `.env.example`'daki 4 A2A değişkeni | A2A modülü yok |
| `backend/scripts/` — 118 dosya | 5'i testler/üretim tarafından kullanılıyor (`run_portfolio_backtest`, `combined_radar_replay_24h` ← `maintenance.py:640`, `research_m1_spikes_all_symbols` ← `pattern_research.py:124` subprocess, `migrate_sqlite_to_postgres`, `run_postgres_migration`). ~113 ölü |
| `docs/` — 17 CSV/SQL çıktısı | Veri üretim artefaktı, kaynak değil; `analysis_snapshots (2).sql` gibi yedekleme kalıntı adları |
| `read_only_query` tablo allowlist'i | `LLM_TOOL` yüzeyi, tablo allowlist var ama sütun allowlist yok |

---

## 7. Önerilen Düzeltme Sırası

### Faz 1 — Hemen (işlevsel regresyon + para)
1. `main.py:2306` — `global _binance_tick_config_cache` ekle. Fiyat yayını şu an ölü.
2. `database.py:5166-5173` / `:5501-5508` — giriş/çıkış komisyon formülünü tek yerde tanımla; `MIN_EXPECTED_NET_PNL_TRY` ile hizala.
3. `database.py:551-597` ve `:410-424` — `reconcile_portfolio` ve `reset_trading_data`'ya `pg_advisory_xact_lock("paper_portfolio_open")` ekle.
4. `main.py:3527-3529` — `llm_open_paper_trade(payload, request=None)` içinde `request is None` → 403; executor'a `request` geçir.
5. `routers/reports.py:455-460` — ya `getattr` guard'ı ya `config.py`'ye tanımlar; test ekle.
6. `auto_paper.py:765` — `breakeven_activated` varken `effective_stop = max(stop_loss, breakeven_stop)`.

### Faz 2 — Risk kapılarını bağla
7. `monitoring.py:_notify` ve `_unified_fast_notify_impl` — `block_reason` / `master_surge.passed` kontrolü ekle.
8. `main.py` — `get_derivatives_intel` + `get_btc_compass` çağıran arka plan döngüsü ekle; `is_panic_dump`/`is_btc_panic` anahtar uyuşmazlığını düzelt.
9. `velocity.py` — `detect_velocity_candidates` içinde `get_all_symbol_target_states()` tek seferde al (220 DB turu → 2).
10. `analyzer.py:1274` — `entry_context["candles"]` ekle veya `calibration.build_buckets`'ı gerçek şemayı okuyacak şekilde düzelt.
11. `microflow.get_snapshot(symbol=...)` parametrik yap; `velocity.py:775-789` sembol kontrolü koy.

### Faz 3 — Test tabanını onar
12. `test_audit_fixes.py`, `test_m4`, `test_w20`, `test_regressions.py`, `test_ws_live_candles.py` içindeki 7 sahte pozitif testi düzelt/sil.
13. `conftest.py` + ortak DB fixture (`monkeypatch.setattr`).
14. CI'a `ruff check` + `ruff format --check` + `pytest --cov --cov-fail-under` + `pytest-timeout` ekle.
15. Frontend'e vitest; `pnl.ts` ve `signals.ts` için gerçek sayısal testler.
16. `_binance_ticks_configured`, cüzdan mutabakatı, `max_open_positions`, gap-through fill, `evaluate_master_surge` bütünsel, 410 Gone temizliği için testler.

### Faz 4 — Dayanıklılık
17. `main.py:337, 339, 672, 702, 889` — `asyncio.to_thread` ile sarmala.
18. `api_common.py` — `_shutting_down` bayrağı + registry `.clear()`.
19. `llm_chat.py:1662` — `calculate_snapshot`'ı `to_thread`'e taşı.
20. `unified_signals` + `macd_monitor` sözlüklerine TTL budama.
21. `ws_runtime.broadcast` — istemci başına bounded kuyruk, `gather` → fire-and-forget.
22. `main.py:1546/1554` — `ticker_24h` çift çağrısını teke indir; `trading_symbols` 5 dk cache.
23. `market_data.py` — `dict(self.tickers)` kopyalarını kaldır.

### Faz 5 — DevOps ve hijyen
24. Kök log dosyalarını sil; `.gitignore`'a `*.log`, `*-all-logs-*.txt` ekle.
25. `run_postgres_migration.py` ve `database.py` aynı migration listesini okusun.
26. Compose'a `SCALPER_ENV=production` + `deploy.resources.limits` + `*_FILE` secret'ları.
27. `nginx` `/ws` bloğuna `X-Forwarded-For` + timeout'lar; HSTS'ten `includeSubDomains`.
28. `database.py:2767, 2811, 721-725, 4480` — sessiz `pass` → `logger.warning(exc_info=True)`.
29. `backend/scripts/` — 3 üretim bağımlısını `backend/tools/`'a taşı, ~113 ölü dosyayı sil.
30. Kök scratch dosyaları (`apply_edits.mjs`, `RUNME.txt`, …) sil veya `.gitignore`'a ekle.

### Faz 6 — Dokümantasyon
31. `LIVE_PARITY_REPLAY.md` + `api-reference.md:157-166` → sil veya aktif profile yaz.
32. `config.py:312, 316-334` yorumlarını 1.5 geometrisine göre yeniden yaz; `MONITORING_RR_MIN` kalibrasyonunu yeniden ölç.
33. `SCALPER_TRADE_POLICY.md` spread eşiğini `LLM_MAX_ENTRY_SPREAD_PCT` ile hizala; kâr/zarar cooldown ayrımını ekle.
34. README: router tablosunu 11 dosyaya güncelle, gerçek kapıyı (`ENABLE_REAL_BINANCE_SELL`) yaz, monitoring modülünü ekle.
35. `.env.example`'dan 4 A2A satırını sil; `BACKTEST_ASSUMED_SPREAD_PCT` referanslarını temizle.
36. `TESTLER.md`'ye güncel koşma komutu + 1426/97 sayısını ekle; `AUDIT_FIX_REPORT`'ı tarihlendir.

---

## 8. Denetim Sınırları

- **Frontend `typecheck` çalıştırılmadı** — ortamda Node/npm erişimi doğrulanamadı. Tip uyuşmazlıkları yalnız `tsconfig` (`strict: true`) okumasıyla değerlendirildi.
- **Canlı ağ/piyasa testi yapılmadı** — Binance rate-limit, WS kopması ve gerçek emir akışı gözlenmedi. Dış API bulguları kaynak kod analizine dayanıyor.
- **Çalışan backend instance'ı yok** — bulgular statik analiz + 1426 testin çalıştırılmasıyla doğrulandı. Prod verisi/ölçümü incelenmedi.
- **Coolify/Traefik katmanı** bu depoda değil — TLS sonlandırma, anahtar yönetimi ve gerçek HSTS etkinliği denetlenemedi.
- **Bağımlılık zafiyet taraması** (pip-audit/npm audit) çevrimdışı yapılamadı; sürümler güncel görünüyor ama CVE durumu doğrulanmadı.
- Bazı alt-ajan iddiaları doğrulamada **elendi** ve rapora alınmadı: `VELOCITY_PROFIT_LOCK_PCT` birim hatası (yanlış — `max()` ile doğru çalışıyor), `auth_login` `user=None` AttributeError (yok — akış doğru), `liveSocket` StrictMode yarışı (yok — koruma mevcut), `macd-monitor/settings` sarmalı uyuşmazlığı (yok — tutarlı), `/api/auto-paper/stats` alan adları (doğrulanamadı, düşük güvenle çıkarıldı).

---

## 9. Önerilen Eylem Döngüsü

Bu rapor 110 bulgu içeriyor; hepsini tek seferde düzeltmek riskli. Önerilen yaklaşım:

1. **Faz 1'i tek başına uygula** (6 madde, ~2-3 saat). Bunlar işlevsel regresyon ve para mutabakatı; test tabanı yeşil kalarak ilerlenebilir.
2. Her faz sonunda `pytest` + `npm run typecheck` çalıştır, commit'le.
3. **Faz 3'ü (test onarımı) Faz 1-2'den önce değil, sonra yap** — çünkü bazı mevcut "kilit" testleri (totoloji olmasalar da) düzeltilmiş kodun beklenen davranışını tanımlıyor; önce davranış, sonra testler.
4. Faz 4-6 paralel ilerleyebilir.
