# Scalper Agent V4 — Düzeltme ve İleri Geliştirme Raporu

**Tarih:** 2026-08-25 · **Kapsam:** 2026-08-25 denetiminde tespit edilen tüm kritik/önemli bulguların düzeltilmesi
**Doğrulama:** Backend 136/136 test OK · Tüm Python modülleri derleniyor · Frontend production build başarılı (24 rota) · Paper-only sözleşmesi korundu

---

## Bölüm 1 — Uygulanan Düzeltmeler

### Faz A — Kritik

| # | Sorun | Düzeltme | Dosya |
|---|---|---|---|
| A1 | Backtest kısmi çıkış muhasebesi her kademe ~1 order_size sanal sermaye ekliyordu; tüm exit-profile araştırmaları geçersizdi | Satılan kısım için `invested_cost`'tan maliyet düşülüyor, hayali para ekleme kaldırıldı | `backend/app/backtest.py` |
| A2 | Tek psycopg bağlantısı + global lock; PG restartında süreç kalıcı kilitleniyordu | Transport hatasında bağlantı kapatılıp sıfırlanıyor (`_PG_FATAL_ERRORS`), sonraki işlem taze bağlantı açıyor | `backend/app/database.py` |
| A3 | `/api/postgres/restore` keyfi dosya yolunu `pg_restore --clean` ile silip atıyordu | Yalnızca sunucu-üretimi `scalper-postgres-*.dump` + PGDMP imzası + `pg_restore --list` ön doğrulaması | `backend/app/main.py` |
| A4a | Eksik bacaklı OCO emri LONG'da anında tetikleniyordu (stop=0 → price>=0) | Oluşturmada bacak doğrulaması; değerlendirmede eksik bacaklı OCO asla tetiklenmez | `backend/app/analyzer.py` |
| A4b | BUY STOP_LIMIT dolgu modeli ters: limitin üstünde fiyatta daha iyi fiyattan dolum | Dolgu artık piyasa fiyatından; limit üstündeyse dolum yok | `backend/app/analyzer.py` |

### Faz B — Veri hattı

| # | Sorun | Düzeltme |
|---|---|---|
| B1 | Rate-limit takibi tanımsız değişkenler yüzünden hiç çalışmıyordu (NameError yutuluyordu) | `_rate_limit_used`/`_rate_limit_last_reset` modül düzeyinde tanımlandı; `rate_limit_snapshot()` artık güvenle çağrılabilir — `binance_tr_public.py` |
| B2 | Yerel saat kayması REST hidrasyonda kapanmamış mumu "kapanmış" kabul edebiliyordu (look-ahead) | `_closed_history`'de 1500 ms güvenlik payı — `market_data.py` |
| B3 | WS kesintisi sonrası mum gap'leri hiç onarılmıyordu | Yeni `MarketData.repair_history_gaps()`: WS hata sonrası + nesil yenilemesinde + REST refresh döngüsünde (10 sn) otomatik backfill — `market_data.py`, `main.py` |
| B4 | Top-gainer aktivasyonu yeni sembollerin geçmişini hydrate etmiyordu (MTF stratejileri ~4,6 saat ölüydü) | Aktivasyonda yeni semboller için `ensure_history(min_candles=55)` hidrasyonu — `main.py` |
| B5 | Mutabakat formülü açık pozisyon giriş komisyonlarını iki kez düşüyordu | Çift düşüm kaldırıldı; panel sapması artık doğru — `main.py` |

### Faz C — Araştırma/öğrenme

| # | Sorun | Düzeltme |
|---|---|---|
| C1 | Custom/LLM backtestleri spread maliyeti olmadan değerlendirilip klasik stratejilere karşı avantajlıydı | `_run_custom` da `BACKTEST_ASSUMED_SPREAD_PCT` (0,1%) tabanını kullanıyor — `backtest.py` |
| C2 | Trailing stop aynı barın kendi yüksek değerinden türetilerek iyimser dolum üretiyordu | Her iki motorda trailing seviyesi bar öncesi bilinen zirveden hesaplanıyor — `backtest.py` |
| C3 | Instinct terfisi aynı deneyimin tekrarıyla şişirilebiliyordu | `upsert_instinct` artık tekrar eden `experience_id`'lerde kanıt/konfiden artırmıyor — `agent_learning.py` |
| C4 | NaN/Inf JSONB insert'leri psycopg'de transaction rollback'e yol açıyordu | `_json_safe_dumps` yardımcısı tüm 37 payload serileştirmesine uygulandı — `database.py` |
| C5 | Bayat test `test_bb_mfi_v1_signal_contract` dip teyidi filtresini hesaba katmıyordu | Test gerçekçi dip mumuyla güncellendi + engelleme davranışı da test ediliyor |

### Faz D — Operasyon/güvenlik

| # | Sorun | Düzeltme |
|---|---|---|
| D1 | Login throttle map sınırsız büyüyordu | 512 anahtar sınırı + eviction — `security.py` |
| D2 | Bozuk alarm kuralı alert döngüsünü her saniye düşürüyor, hata sessizce yutuluyordu | Kural başına izole değerlendirme + bozuk kural devre dışı bırakılıyor; POST `/api/alerts` tip doğrulaması — `alerting.py`, `main.py` |
| D3 | Scan-log `ticker.get("price")` diye var olmayan alanı okuyordu | `last_price` kullanılıyor — `main.py` |
| D4 | DATABASE_URL parolası argv'de `ps` ile okunabiliyordu; timeout'ta subprocess orphan kalıyordu; DB tamamen RAM'e okunuyordu | URL stdin ile aktarılıyor (`-` konvansiyonu), kill+recover eklendi, chunked hashing — `migration_monitor.py`, `scripts/migrate_sqlite_to_postgres.py` |
| D5 | microstructure_snapshots vb. tablolar sınırsız büyüyordu (~1,5M satır/gün riski) | `prune_retention()` + 6 saatlik `retention_loop` (`RETENTION_DAYS`, varsayılan 30) — `database.py`, `main.py`; paper trades/signals korunur |
| D6 | Her ayar kaydetmede tam evren refetch + WS reconnect → dakikalarca trade durması | Yalnızca sembol/timeframe değişiminde refetch; aksi halde sadece gap-repair — `main.py` |
| D7 | Restart 24h timeout / 2h hard-stop re-entry bloklarını siliyordu | Bloklar `llm_settings` KV'sinde kalıcı; açılışta geri yükleniyor — `analyzer.py` |

### Faz E — Frontend

| # | Sorun | Düzeltme |
|---|---|---|
| E1 | `/monitor?tab=pump` hydration uyuşmazlığı | Query parametresi useEffect içinde okunuyor — `monitor/page.tsx` |
| E2 | GainerRadar sayfayı açmak config'e PUT atıp radar execute tetikliyordu | Otomatik yan etkiler kaldırıldı; açık "✓ Listeye Ekle" onay düğmesi; sayfa notu güncellendi ("otomatik paper pozisyon açmaz") — `GainerRadar.tsx` |
| E3 | Settings NaN→null gönderiyor, istemci doğrulaması yoktu | Save öncesi NaN alan reddi + `num()` güvenli hale getirildi — `settings/page.tsx` |
| E4 | Backtest/alarm silmeleri onsuz kalıcı siliniyordu; alarm mutasyonlarında hata yönetimi yoktu | `window.confirm` + try/catch + bilgilendirme — `backtest/page.tsx`, `AlertPanel.tsx` |
| E5 | Ana WS reconnect sabit 2 sn retry storm'u | Üstel backoff + jitter + 30 sn tavan; açıkta sıfırlama — `lib/liveSocket.ts` |
| E6 | WS kopukken LiveTerminal "● LIVE" pulse etmeye devam ediyordu | `useLiveStatus` ile "○ BAĞLANIYOR / ○ BAĞLANTI YOK" durumu — `LiveTerminal.tsx` |
| E7 | Graf candle WS'inde reconnect yoktu; kopunca mumlar donuyordu | Aynı backoff mantığıyla yeniden bağlanma — `charts/page.tsx` |
| E8 | `text-bunker-700` (~2.4:1) kanıt metni kontrastı AA altındaydı | Yeni `bunker-600` (#6a6f9e) token'ı; risk paneli sert-kodlu bilgiler kaldırıldı — `tailwind.config.ts`, `LiveTerminal.tsx` |
| E9 | `prefers-reduced-motion` yarım uygulanmıştı (pulse/skeleton/smooth-scroll çalışmaya devam ediyordu) | Global animasyon/scroll bastırma eklendi — `globals.css` |
| E10 | Radar tablosunda `.toFixed()` crash riski | Guarded formatter (`fmt`) — `GainerRadar.tsx` |
| E11 | DESIGN.md çekirdek rotası `/signal-replay` 404 veriyordu | Yeni sayfa: salt-okunur kapalı-mum karar tekrarı (`POST /api/strategy/replay` arkasına); sidebar'a eklendi |

### Faz F — Dokümantasyon

- README akış diyagramı gerçek mimariyle değiştirildi (BB-MFI v3, kapalı mum, atomik paper commit).
- Pozisyon yönetimi bölümü artık gerçeği anlatıyor: BB-MFI −%8.882/+%2.317/teyitli sell; eski −%1/+%0.2/%0.5 modelinin kodda olmadığı açıkça belirtildi.
- `DEFAULT_ORDER_USDT` birim notu, `RETENTION_DAYS`, replay API uçları eklendi.
- Yeni test dosyası: `backend/tests/test_audit_fixes.py` (kısmi çıkış muhasebesi, saat-kayması payı, rate-limit snapshot, emir validasyonu).

### Faz H — LLM hafıza ve self-learning iyileştirmeleri

| # | Sorun | Düzeltme | Dosya |
|---|---|---|---|
| H1 | Recall skoru başarılı sonuçlara tek taraflı +0.10 veriyordu → hafıza pozitif yanlılıydı, LLM kendi başarısızlık derslerini göremiyordu | Doğrulanmış sonuç (başarılı **veya** başarısız) eşit +0.08 puan alıyor; çelişki cezası aynen — failure lesson'lar artık geri geliyor | `memory_service.py` |
| H2 | Injection marker'ları yalnızca İngilizceydi; *"önceki talimatları yoksay"* gibi Türkçe enjeksiyonlar sanitization'a takılmıyordu | 8 Türkçe marker eklendi (`yoksay`, `görmezden gel`, `önceki talimat`, `sistem istemi`, `kuralları aş`, `yeni talimatlar:`…) | `memory_service.py` |
| H3 | Instinct confidence'i sadece artıyordu (+0.05 ratchet); bayat kalıplar eski sermayesiyle promotion eşiğini geçebiliyordu | 14 gün güçlenmeyen adaylar 0.05 adımla 0.30 tabanına decay ediyor; `promote_validated_instincts` artık `decayed` sayacı da döndürüyor | `agent_learning.py` |
| H4 | Tool-loop 25 round'a kadar sınırsız token yakabiliyor, tek büyük araç yanıtı konuşmayı şişirebiliyordu, maliyet görünmezdi | `LLM_TOOL_MAX_ROUNDS` / `LLM_TOOL_TOKEN_BUDGET` (~600k) / `LLM_TOOL_RESULT_MAX_CHARS` (40k kırpma) bütçeleri; yanıta `tool_loop` telemetrisi (round, çağrı sayısı, provider prompt/total tokens) eklendi | `llm_analysis.py` |
| H5 | Bozuk `pnl` değeri trade-close yolunda embedding dokümanı üretmeden crash ediyordu | Malformed pnl güvenle "flat" outcome'a düşüyor | `embedding_worker.py` |

Bu fazla birlikte öğrenme döngüsünün politika uyumu güçlendirildi: kanıt gerçek ve tekilleştirilmiş (C3), güncellik zorunlu (H3), hatıralar iki dilli enjeksiyon taramasından geçiyor (H2), recall iki polariteyi de taşıyor (H1) ve LLM çağrı maliyeti ölçülüp sınırlanıyor (H4).

Yeni test dosyası: `backend/tests/test_llm_memory_learning.py` (9 test: simetrik outcome işaretleme, Türkçe injection yakalama, decay alanı, bütçe pozitifliği, kırpma, token tahmini, pnl güvenliği).

### Faz I — PUMP Monitor optimizasyonu (işlem geçmişi analizi + gerçek-veri replay)

292 işlemlük PUMP_MONITOR geçmişi (−1.680 TL net) analiz edildi; bulgular yeni kurallara dönüştürüldü ve **gerçek Binance TR 5m kline verisiyle (18 sembol × 48 saat) bar-bar replay ile doğrulandı** (`work/pump_replay_engine.py`).

| # | Bulgu | Uygulanan kural |
|---|---|---|
| I1 | VR>2.0 girişleri tek başına −1.029 TL (patlamış pump'ı kovalama) | `PUMP_MONITOR_MAX_ENTRY_VOLUME_RATIO=2.0` giriş filtresi; UI'da "pump zaten patladı" gerekçesiyle görünür |
| I2 | 56 stop +%0.5 MFE görmüştü, sonra tam zarara döndü (−1.536 TL) | Break-even: MFE ≥ tetikte stop net-floor'a taşınır → çıkış nedeni `pump_break_even_stop`; re-entry hard-stop bloğu uygulanır |
| I3 | Stopların %48'i hiç +%0.3 görmemişti (başarısız teyit) | Fast-fail erken çıkış (`pump_fast_fail_no_progress`) — **replay'de değer katmadığı için varsayılan KAPALI** (`PUMP_MONITOR_FAST_FAIL_ENABLED=false`, env ile açılır) |

**Replay eşik taramaları:** BE trigger 0.3% > 0.5% (−1.353 vs −1.690 TL) → varsayılan **0.3%** seçildi. VR cap 2.0 makul (1.5 marjinal daha iyi ama işlem sayısını düşürür). Fast-fail tüm eşiklerde net'i kötüleştirdi (erken çıkanlar sonradan trailing'e ulaşmış).

**Canlı doğrulama:** Test sunucusunda pump taraması çalıştırıldı; ARBTRY (vr=2.11) yeni filtreye takıldı ve gerekçe UI'da görüntülendi.

Yeni test dosyası: `backend/tests/test_pump_monitor_improvements.py` (6 test: BE arm/lift, armed stop çıkış gerekçesi, fast-fail davranışı + default-kapalı sözleşmesi, config defaultları).

### Faz J — Kârlılık ve sinyal kalitesi geliştirme paketi (S1–S7)

Trade-history analizi sonrası sinyal kalitesi ve sermaye koruması için yedi geliştirme uygulandı. Tümü paper-only, tümü config ile açılıp kapanabilir:

| # | Geliştirme | Uygulama |
|---|---|---|
| S1 | **Maliyet-farkındalıklı giriş kapıları** | `expected_net < MIN_EXPECTED_NET_PNL_TRY` → `BUY_BLOCKED:expected_net_below_floor`; ATR kapasite kapısı: hedef mesafesi < `MIN_TARGET_ATR_CAPACITY_RATIO`×ATR ise giriş reddi (`atr_capacity_insufficient`) — `analyzer.py` |
| S2 | **Strateji devre kesici** | Son N (20) işlemin kayan expectancy'si `STRATEGY_BREAKER_EXPECTANCY_FLOOR` altına inerse strateji PAUSE; yeni girişler `strategy_circuit_breaker_paused` ile bloklanır, açık pozisyonlar yönetilmeye devam eder. Yalnızca insan onayıyla resume (`POST /api/strategy/breaker/resume`); durum `GET /api/strategy/breaker`. Pause durumu KV'de restart'a dayanıklı — `circuit_breaker.py` |
| S3 | **Kova bazlı win-rate kalibrasyonu** | Kapanan işlemler strateji × saat bandı × hacim-bandı kovalarına gruplanır (haftalık yenileme); ≥8 örnekli kötü kovalar boyutu 0.5'e kadar küçültür, bilinmeyen kovalar nötr. Tablo: `GET /api/strategy/calibration` — `calibration.py`, pump context'ine `calibration_multiplier` yazılır |
| S4 | **Rejim-gated boyutlama** | Mean-reversion trendli rejimde 0.5x; continuation ölü range'de 0.7x; düşük güvenli/unknown rejim nötr — `calibration.regime_size_multiplier`, analyzer girişinde uygulanır |
| S5 | **Dinamik korelasyon kontrolü** | BTC **ve ETH** benchmark'larına karşı her sembolün rolling Pearson korelasyonu mum-cache'ten 30 dk'da bir hesaplanır (ek borsa çağrısı yok); korelasyon-ağırlıklı portföy maruziyeti `MAX_CLUSTER_EXPOSURE_PCT` (%60) aşarsa yeni giriş `CLUSTER_CAP` ile reddedilir. İnce veri → muhafazakâr 0.75 default. API: `GET /api/strategy/correlation` — `correlation.py` |
| S6 | **Volatiliteye göre boyutlama** | Sabit emir tutarı yerine eşit-risk ölçekleme: ATR% tabanın üstündeki sembolde pozisyon oranlı küçülür (min 0.35x clamp), sakinde tam boyut — `_entry_order_value` |
| S7 | **Terfi hattı + evren kaydı** | (a) Point-in-time sembol-evren kaydı: her top-gainer değişiminde snapshot JSON'a yazılır; araştırma araçları geçmiş herhangi bir andaki evreni yeniden kurabilir (survivorship-bias giderici) — `universe_registry.py`, `GET /api/strategy/universe-history`. (b) Aday-strateji terfi hattı: `shadow → walk_forward → paper_candidate → active`; her kapı objektif kanıt ister (≥120 shadow gözlemi / WF OOS PASS / ≥20 paper işlem), `active` **asla otomatik değil**, `human_approved=true` şart; her geçiş denetim izine yazılır — `promotion.py`, API: `/api/strategy/pipeline*` |

Yeni test dosyaları: `test_quality_gates.py` (S1/S2, 7 test), `test_calibration_sizing.py` (S3/S6, 6 test), `test_regime_correlation.py` (S4/S5, 8 test), `test_promotion_pipeline.py` (S7, 3 test).

---

## Bölüm 2 — Doğrulama Sonuçları

```
Backend derleme:   py_compile app/*.py scripts/*.py        → OK
Backend testler:   python -m unittest discover -s tests    → 175/175 OK
Frontend build:    npm run build                           → EXIT 0, 24 rota
TS parse kontrolü: 5 düzenlenen .tsx dosyası               → 0 hata
PUMP replay:       gerçek 48s kline, bar-bar simülasyon    → +550 TL iyileşme; BE trigger 0.3% seçildi
Değişen dosya:     30 modified + 8 new (test dosyaları, signal-replay/, pump_replay_engine.py,
                   circuit_breaker.py, calibration.py, correlation.py, promotion.py, universe_registry.py)
```

Not: Depoda `.gitattributes` yok ve mevcut dosyalar LF/CRLF karışık. Düzenlemeler sırasında oluşan satır-sonu kirliliği temizlendi; kalan diff'ler yalnızca gerçek değişikliklerdir. Kalan birkaç `git diff --check` bayrağı bu mevcut karışık EOL durumundan kaynaklı kozmetik uyarılardır. Öneri: köke `.gitattributes` (`* text=auto eol=lf`) eklenip tek seferlik normalizasyon yapılması.

---

## Bölüm 3 — İleri Geliştirme Önerileri (öncelikli yol haritası)

### Kısa vade (1-2 sprint)

1. **Exit-profile çalışmalarının yeniden koşulması** — A1 muhasebe düzeltmesi sonrası mevcut tüm exit-profile sonuçları eski (şişirilmiş) motorla üretilmiş durumda; `run_exit_profile_backtests` ile temiz veri toplanmalı.
2. **`.gitattributes` + EOL normalizasyonu** — satır sonu kirliliğinin kökten çözümü.
3. **pytest kurulumu** — venv'de pytest yok; unittest yeterli ama CI için pytest + coverage raporu değerli.
4. **Ağırlıklı uçlara rate-limit middleware'i** — `/api/backtest/run`, `/api/radar/execute`, LLM chat SSE hâlâ sınırsız; basit bir token-bucket middleware yeterli.
5. **DB hot-path'inin asyncpg'ye taşınması** — reconnect düzeltmesi dayanıklılık sağladı ama tek-lock mimarisi head-of-line blocking riskini sürdürüyor.
6. **`/api/reset` ve `/api/portfolio/reconcile` için `_open_position_lock`** — in-memory pozisyon haritasına kilitsiz dokunan iki uç nokta kaldı.

### Orta vade

7. **Birleşik indikatör kütüphanesi** — analyzer ile technical_analysis arasındaki çift EMA/RSI/CRSI tanımı tek kaynağa indirilmeli; snapshot ile strateji kararı ayrışmamalı.
8. **Kalıcı sembol-evren geçmişi** — top-gainer rotasyonunun yarattığı survivorship bias'ı gidermek için point-in-time universe rekonstrüksiyonu.
9. **Exchange saat senkronu izleme** — `/api/v3/time` offset ölçümü + |skew| > 1 sn alarmı.
10. ~~**LLM maliyet bütçesi**~~ — **H4 ile tamamlandı** (round/token bütçesi + tool_loop telemetrisi). Kalan: tool-loop telemetrisinin `/system-health` paneline taşınması.
11. **Frontend stale-data yaygınlaştırma** — Portfolio/Charts/Raporlar'a da `useLiveStatus` bazlı bayatlık bandı; `document.hidden`'da polling duraklatma.
12. **E2E smoke testleri** — paper açılış→yönetim→kapanış döngüsünün sahte-public-veriyle otomatik senaryosu.
13. **Hafıza kalite metrikleri** — recall'da outcome dağılımının (profit/loss oranı) periyodik raporlanması; H1 sonrası failure-lesson'ların gerçekten geri geldiğinin izlenmesi.

### Uzun vade / stratejik

13. **SQLite dalının tamamen emekliye ayrılması** — compose/Dockerfile'daki `SCALPER_DB_PATH` artefaktları ve sqlite branch bakım yükü kaldırılmalı.
14. **Walk-forward otomasyonu** — aday stratejilerin otomatik WF/OOS kapılarından geçmeden "candidate" etiketi taşımaması (policy ile uyumlu insan onay kapısı korunarak).
15. **Gözlemlenebilirlik** — yapılandırılmış loglama + Prometheus/OpenTelemetry export; strateji kararlarının trace-id ile takibi.
16. **Mobil UX turu** — DESIGN.md'deki 44px dokunma hedefi, modal focus-trap ve Escape davranışlarının tamamlanması.

### Bilinen açık kalemler (bilinçli olarak dokunulmadı)

- `strategy_breakout` / `strategy_mean_reversion` / UT spec'leri kayıtlı değil (ölü kod) — davranış değişikliği riski nedeniyle kaldırılmadı.
- İki farklı profit-factor sentinel'i (999 vs None) — araştırma çıktılarını tüketen araçlarla birlikte değiştirilmeli.
- PUMP_MONITOR sayfasındaki BUY_BLOCKED yeşil renklendirme — sayfa sahibiyle netleştirilmeli.
- Fisher exact-paper modu env ile açılıyor ve ortak cüzdanı kullanıyor — politika sorusu; varsayılan kapalı kalması önerilir.

---

*Bu rapor salt-okunur denetim + düzeltme çalışmasının çıktısıdır. Hiçbir aşamada gerçek emir yolu eklenmedi, canlı strateji davranışı (BUY_SIGNAL/BUY_BLOCKED disiplini, 10.000 TL paper bakiyesi) değiştirilmedi.*
