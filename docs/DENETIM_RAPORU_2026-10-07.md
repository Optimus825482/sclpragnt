# Scalper Agent V4 — Genel Denetim Raporu

**Tarih:** 2026-10-07
**Kapsam:** Backend (298 .py / ~104.000 satır), Frontend (51 .tsx / 23 .ts), testler, DevOps, dokümantasyon, ML/öğrenme katmanı
**Yöntem:** 15 paralel denetim + kritik iddiaların kaynak koddan ve **çalıştırılarak** doğrulanması
**Taban ölçümler (bu raporda ölçüldü):**
- Test: **1713 test toplandı, tamamı yeşil** (exit 0)
- `ruff check app tests scripts` → **temiz** (sert kapı geçiyor)
- Frontend `tsc --noEmit` → **temiz**; `vitest` → 3 dosya / **67 test yeşil**
- Git ağacı temiz; 599 izlenen dosya; `.git` = **332 MB**

> Bu rapor önceki `docs/SISTEM_DENETIMI_2026-09-26.md` (110 bulgu) ve `docs/OTONOM_TRADE_TESHIS_2026-10-07.md` belgelerinin **açık/kapalı** durumunu güncel kod üzerinde yeniden doğrular ve **yeni** bulguları ekler.

---

## 1. Yönetici Özeti

Sistem tasarım düzeyinde olgun. Önceki denetimdeki **para-mutabakatı (P0) hatalarının çoğu gerçekten düzeltilmiş**: cüzdan komisyonu, reconcile/reset kilidi, breakeven sıralaması, bayat-ticker çıkışı, `_binance_ticks_configured` UnboundLocalError, master-surge kapısı "ölü kapı" durumu, türev/makro önbellek beslemesi, N+1 sembol-hedef sorgusu, XSS ve çok-kullanıcılı bakiye sızıntısı — hepsi kapanmış.

Ancak denetim üç **sistemik** sorun ortaya çıkardı:

1. **Yeni "kanıta dayalı" ayarlar canlıyı kilitliyor olabilir (P0).** Master Surge 4'lü-teyit kapısı ve `allowed_modes=["trend_devam"]` birlikte, kanıtlanabilir şekilde **radar/otonom bildirimlerin büyük çoğunluğunu bastırıyor**. İki kapı üst üste biniyor: (a) 4'lü teyit yoksa aday hiç bildirilmiyor, (b) bildirilse bile modu `"trend_devam"` olmadığı için (radar = `"unified"`) otonom açılmıyor.

2. **Rapor/telemetri filtreleri ticaret döngüsüne sızmış (P0).** Görsel bir "rapor başlangıcı" tarihi, `list_auto_paper_trades` üzerinden **pozisyon yönetim döngüsünü ve risk tavanını** da etkiliyor; başlangıçtan eski açık pozisyonlar sonsuza kadar yönetilmeden kalabiliyor.

3. **Yetkilendirme (rol) tutarsız.** Uygulama geneli middleware **yalnızca kimlik doğrulama** yapıyor, rol kontrolü her handler'ın kendi sorumluluğunda — ve 55 rotada hiç yok. Sonuç: admin olmayan oturumların pozisyon açmasına, alarm yazmasına, global ayar değiştirmesine izin veren yollar var.

Ek olarak ML/öğrenme katmanında **optimistik etiket sızıntısı** (gelecek tepe noktasının TP hedefi olarak servis edilmesi) ve DevOps'ta **üretim sertleştirmesi eksikleri** (düz metin secret, `development` env, placeholder köprü anahtarı, 332 MB `.git`) öne çıkıyor.

---

## 2. Öncelik Sıralı Bulgular

### P0 — Kritik

| # | Bulgu | Yer | Doğrulama |
|---|---|---|---|
| **P0-1** | **Master Surge 4'lü-teyit kapısı canlıda neredeyse tüm radar adaylarını bastırıyor.** `MASTER_SURGE_REQUIRE_4WAY=true` (varsayılan) iken `passed=True` yalnız 4 katmanın tamamı geçtiğinde; `MONITORING_MASTER_SURGE_GATE` varsayılan AÇIK. `unified_signals` her adaya `master_surge` ekliyor; `_notify` `passed is False` görünce `continue`. | `config.py:492`, `master_surge.py:499,601`, `unified_signals.py:302`, `monitoring.py:1297-1308` | **Çalıştırarak doğrulandı:** `_master_surge_block_reason({passed:False})` → `'NO_4WAY_CONFLUENCE'`; `gate_enabled=True` |
| **P0-2** | **Mod filtresi radar yolunu kapatıyor.** `allowed_modes=["trend_devam"]`, ama `trend_devam` yalnız velocity yolunda üretiliyor; radar/unified bildirimleri `mode="unified"`. Yani radar bildirimi hiçbir zaman otonom açılmıyor. | `auto_paper.py:1412`, `unified_signals.py:374,477`, `velocity.py:575` | **Doğrulandı** (kaynak taraması) |
| **P0-3** | **`reports_baseline` filtresi açık pozisyonları yönetimden düşürüyor.** `_check_open_positions` → `list_auto_paper_trades(status="open")`, fonksiyon `entry_time >= max(reset_cutoff, reports_baseline)` uyguluyor. `REPORTS_BASELINE_DEFAULT="2026-10-07 11:30"`. Bundan eski açık pozisyon **hiç taranmaz** (SL/TP/max_hold/trailing yok) ve **global açık-pozisyon tavanından** muaf kalır. | `config.py:519`, `database.py:5713-5718`, `auto_paper.py:892,547` | **Doğrulandı** |
| **P0-4** | **"Tüm emirleri iptal et" HTTP hatasını başarı sayıyor.** `apiRequest` non-ok'da throw etmez (yalnız `apiFetch`/`getJSON` eder); döngü `successCount++`'ı her durumda çalıştırıyor → canlıda SL/TP emirleri dururken "N emir iptal edildi" bildirimi. | `frontend/app/binance-tr/page.tsx:1031-1040`, `lib/api.ts:21` | **Doğrulandı** |
| **P0-5** | **Farklı kilit anahtarı, aynı cüzdan satırı.** `reconcile_portfolio`/`reset_trading_data` `paper_portfolio_open` kilidi alır; `open_auto_paper_trade`/`close_auto_paper_trade` **farklı** anahtarlar (`auto_paper_open_{sym}`, `auto_paper_close_{id}`) alır. Aynı `virtual_wallet` TRY satırını yazarlar, `SELECT … FOR UPDATE` yok → eşzamanlı açılış/kapanışın etkisi mutlak-değer yazımıyla **silinebilir**. | `database.py:447,714` vs `:5499,5943` | **Doğrulandı** |

### P1 — Yüksek

| # | Bulgu | Yer |
|---|---|---|
| **P1-1** | **Fast-scan hiç bildirim teslim etmiyor.** `_maybe_run_fast_scan` `await _run_scan()` sonucunu atıyor; `_deliver_scan_notifications` çağrılmıyor. Push/WS/`try_open_from_notification` çalışmaz. | `monitoring.py:2941-2945` |
| **P1-2** | **Master-surge risk kapısı yükseliş (rising) yolunda uygulanmıyor.** `_run_rising_scan`/`_build_rising_notification` `block_reason` taşımıyor → EXTREME_LONG/BTC-panik blok radar'da çalışırken rising'de açılıyor. | `monitoring.py:2144-2350`, `auto_paper.py:2106` |
| **P1-3** | **LLM ikinci-göz kapısı girişte etkisiz.** `try_open_from_notification` (ve LLM kapısı), `llm_verdict` yazılmadan **önce** çalışıyor → karar açılış anında boş; FAKE/TUZAK yalnız sonraki yeniden açılışta bastırılabiliyor. | `monitoring.py:1569-1586` |
| **P1-4** | **Eksik admin kapıları.** Uygulama middleware'i kimlik doğrular ama **rol kontrol etmez**; şu yollar admin kapısız: `POST /api/radar/execute` (paper emir açabilir), `POST /api/velocity/manual-scan`, `POST/PATCH/DELETE /api/alerts`, `place_paper_order`/`cancel/modify_paper_order` (LLM aracı), `create_market_alert` → `auto_paper_trade`. Admin olmayan oturum pozisyon açabilir / başkasının alarmını değiştirebilir. | `main.py:1911`, `velocity.py:1643`, `main.py:1409-1444`, `llm_chat.py:3505`, `llm_chat.py:82` |
| **P1-5** | **Oturum/güvenlik:** login hız-sınırı `X-Real-IP` başlığına güveniyor (sahtelenebilir, brute-force); WS `Origin` doğrulanmıyor (CSWSH); oturum token'ı cihaza bağlanmıyor (`client_fingerprint` hiç yazılmıyor → çalınan cookie 12 saat her yerden geçerli). | `main.py:385-386,1279-1295,445`; `security.py:84-105` |
| **P1-6** | **`read_only_query` kolon beyaz-listesi yok + LIMIT baypası.** Yalnız tablo adları denetleniyor; JSONB `metadata`/`snapshot` dahil tüm kolonlar LLM'e akabilir. İç `LIMIT` varlığı dış sarmalamayı iptal ediyor → sınırsız JOIN. | `database.py:3828-3855` |
| **P1-7** | **SSE iş parçacığı sızıntısı → DB havuzu açlığı.** `asyncio.wait_for(to_thread(lines.get), 1.0)` timeout'ta iptal edilse de thread `lines.get()` üzerinde bloklu kalır (varsayılan executor). Yavaş sağlayıcıda 600 sn'ye kadar 32 worker kilitlenir; **tüm DB çağrıları** kuyruğa girer. | `llm_analysis.py:981`, `database.py:241` |
| **P1-8** | **Borsa emir güvenilirliği:** `place_market_sell` alımda yapılan `executedQty` doğrulamasını **yapmaz** (kısmi dolum tam sanılır); `min_notional` koruması gerçek satış yolunda **ölü** (`last_price` hiç geçilmiyor → toz bakiye kalıcı takılır); POST, geçici-sınıf 5xx'te **idempotency anahtarı olmadan** yeniden denenir; `set-sl-tp cancel_existing` ile iptal-sonra-yerleştir arasında **kilitsiz pencere** (yerleştirme başarısızsa pozisyon stopsuz). | `binance_tr_private.py:552,545,366`, `main.py:3538` |
| **P1-9** | **ML optimistik etiket.** Hedef regresörü `mfe_{horizon} = fut_high/c - 1` (**gelecek tepe**) üzerine eğitiliyor ve bu değer canlı TP hedefi olarak servis ediliyor → model "değmiş olabilir"i öğreniyor, TP'ler ortalamanın ulaşamadığı yükseklikte kuruluyor; journal geri-beslemesi (3× ağırlık) sapmayı büyütüyor. Ayrıca sınıflandırıcı `class_weight`'siz (nadir pozitif sınıf → `ml_prob` eşiği aşılamaz, özellik ölü). | `ml_forecast.py:346-348,522,525`; `velocity.py:2311` |
| **P1-10** | **Velocity mikro-yapı ölü.** `microflow.get_snapshot` imzasında **`symbol` parametresi yok**, ama `velocity.py:992` `symbol=` ile çağırıyor; `TypeError` fallback global sembolü okur ve `got != target` olduğu için `None` döner → aktif olmayan adayların tamamı mikroyapısız sıralanıyor. | `microflow.py:401`, `velocity.py:992-1003` |
| **P1-11** | **DevOps/üretim sertleştirmesi:** `SCALPER_ENV` hâlâ `development` (zayıf admin parolası üretimde kabul); secret'lar düz metin `environment:`; köprü alıcısı varsayılan `enabled` + **placeholder** `BINANCE_TR_BRIDGE_SECRET` + `AUTO_TRADE=true`; tüm imajlar root; `init_db` DDL'i + sürümsüz `ALTER`'lar `lock_timeout=5s` altında (kilit altında `LockNotAvailableError` → crash-loop); migration sha iki farklı kaynaktan (glob vs sabit 5'li) → 6. dosya eklenince her restart'ta tam DDL. | `docker-compose.yaml:84,98`, `.env.example:35-37`, `database.py:213,291-356`, `run_postgres_migration.py:59` |

### P2 — Orta

| # | Bulgu | Yer |
|---|---|---|
| **P2-1** | Trailing/breakeven stop üst-sınır koruması DB katmanında yok (peak dışında monotonic guard yok). | `database.py:5897,5921` |
| **P2-2** | `TP_PRIMARY_ENABLED=false` → `take_profit` çıkışı ve `update_auto_paper_trade_tp` ölü kod; gerekçe tablosunda `take_profit` en iyi çıkıştı. | `auto_paper.py:1006` |
| **P2-3** | Dedup kapısı açık pozisyondayken de çalışıyor → mevcut pozisyonun TP'si 60 dk yükseltilemiyor. | `auto_paper.py:252` |
| **P2-4** | Breakeven/SL cooldown'ları yalnız bellekte (restart amnezisi); SL cooldown `breakeven_stop` çıkışını kapsamıyor. | `auto_paper.py:1219,326` |
| **P2-5** | `reconcile` açık pozisyonu `INITIAL_BALANCE_TRY` ile modelliyor → gerçek cüzdana bakmadan "yetersiz" bulduğu geçerli pozisyonu silebilir. | `database.py:621-743` |
| **P2-6** | Yedek/geri-yükleme arasında karşılıklı dışlama kilidi yok (`pg_restore --clean` canlı `pg_dump` altında şema düşürür). | `main.py:4397-4481` |
| **P2-7** | Tüm DB işleri + `to_thread` tek varsayılan executor'dan; gerçek tavan `max_size=8` havuz → eşzamanlı patlamada `PoolTimeout`. | `api_common.py:241`, `database.py:225` |
| **P2-8** | `ws_broadcast_loop` istemci olmasa ve veri değişmese de her saniye tüm ticker+pozisyonu yeniden serileştiriyor. | `routers/runtime.py:169-214` |
| **P2-9** | Frontend: stale closure (gösterge kaybolması), "● CANLI" rozeti hiç `false`'a dönmüyor, marker primitive sızıntısı, modal'da brüt vs net PnL tutarsızlığı, SHORT PnL işareti, chart modalı a11y eksik, `mtfBadge` hiç render edilmiyor (parser alanı düşürüyor). | `MultiChartCard.tsx:523`, `charts/page.tsx:536,1189`, `BinancePositionChartModal.tsx:1337,1357`, `lib/pnl.ts:61`, `monitoring/page.tsx:242` |
| **P2-10** | Test kalitesi: 4 `assertTrue(True)`, 52 `inspect.getsource` + 49 `read_text` kaynak-metni testi, `conftest.py` yok, **frontend `npm test` CI'da hiç çalışmıyor** (67 test yazılı ve geçiyor — ölçtüm), `TestClient` yok. | `backend/tests/*`, `.github/workflows/backend-tests.yml:117` |
| **P2-11** | Köprü (bridge) yeniden-oynatma koruması yok: `event_id` dedup yok, `timestamp` skew denetimi yok, `force:true` 60 sn cooldown'ı atlıyor. | `tr_bridge_receiver.py:346,232` |
| **P2-12** | Yedekleme aynı diskte (retention=2), geri-yükleme dokümanı `-Fc` dump için yanlış komut (`psql` → `pg_restore` olmalı), başarısızlıkta alarm yok. | `docker-compose.yaml:263-319` |
| **P2-13** | `binance_account_update` push döngüsü yazılmayan anahtarı (`binance_api_key_{user}`) okuyor + var olmayan `app.llm_utils` modülünü import ediyor → canlı bakiye push'u hiç çalışmaz. | `main.py:2613,2617` |

### P3 — Düşük / Hijyen

- **Repo şişkinliği:** `.git` **332 MB** (599 dosya için); geçmişte `node_modules` ve telif hakkı içeren **20,8 MB'lık müzik zip'i** (`docs/Dayan_Dedim_...zip`) var; **93 `backend/*.log` (25,4 MB)** ve `backend/*.window.txt` izleniyor (`.gitignore`'daki `*.log` kuralından önce force-add edilmiş); `backend/scripts/` ~88 ölü araştırma scripti.
- **Ölü kod/ayar:** `combined_radar.build_combined_candidates`/`build_unified_envelope` çağıransız; `VELOCITY_BASE_RATE_PCT`/`VELOCITY_CALIBRATED_HIT_PCT` yalnız çıktıya yazılıyor; `migration_monitor.fetch_target_counts` çağıransız; `VELOCITY_TRAIL_GAP_PCT`, `MASTER_SURGE_ENABLED` hiç okunmuyor; `trading_symbols_with_filters` yazılmış ama bağlanmamış.
- **Doküman tutarsızlıkları:** `README` **olmayan** `POST /api/strategy/replay` ve `/signal-replay` sayfasını belgeliyor; `routers/` **13** dosya ama README "11" diyor ve `bridge.py`/`snapback.py` eksik (ayrıca `runtime.py`/`llm_position_tools.py` `APIRouter` kullanmıyor); `TESTLER.md` "frontend test yok / vitest yok" **yanlış**; `config.py:328` yorumu hâlâ "SL %3.0" (gerçek **5.0**); `VELOCITY_PROFIT_LOCK_PCT` yorumu "+%0.5" ama değer %1,0 ve gerçek taban tur maliyeti ~%0.355.
- **Config tuzağı:** `AUTO_PAPER_*` varsayılanları **env ile geri alınabilir** deniyor, ama DB `auto_paper_settings` satırı env'i eziyor → admin bir kez kaydedince env rollback **sessizce etkisiz**.
- **Latent fallback sapmaları:** `getattr(config,"AUTO_PAPER_TRAILING_GAP_PCT",0.60)` (gerçek 0.3), `AUTO_PAPER_MAX_HOLD_MINUTES` fallback 60 (gerçek 120), `AUTO_PAPER_SL_PCT_DEFAULT` fallback 1.5 (gerçek 5.0) — attr bulunamazsa sessizce eski davranış.

---

## 3. Önceki Denetimden **Düzeltilmiş** Doğrulananlar

Para yolu: giriş komisyonu cüzdandan düşülüyor + çıkışta çift uygulanmıyor (§2.5) · reconcile/reset kilidi (§2.6) · breakeven önce kontroller (§3.1#1) · bayat-ticker çıkışı (§3.1#2) · `velocity_protection_armed` kalıcı (§3.1#3) · `AUTO_PAPER_SL_PCT_DEFAULT` adı (§3.1#7).
Radar/veri: master-surge "ölü kapı" → artık tüketiliyor (§2.2, ama P0-1'e yol açtı) · türev/makro önbellek arka plan döngüsü (§2.3) · `_unified_fast_last` persist/restore/prune (§2.10) · tek eşik (§3.2#8) · `_num` koruması (§3.2#9) · `_binance_ticks_configured` UnboundLocalError (§2.1) · `refresh_depth`/`data_ready` (§2.4) · MFI NaN (§3.2#10) · ATR hedef (§3.2#11) · CRSI/MFI frontend parity (§3.2#14/15) · `dict(tickers)` kopyası (§4#65) · PBKDF2 off-loop (§3.4#35).
Güvenlik: `sv` fail-closed (§3.3#21) · rol düşürme (§3.3#22) · alert sahipliği (§3.3#28) · türev/global anahtar izolasyonu (#25) · persona override (#26) · `max_tokens` clamp (#27) · `ma-sascade` 500 (§2.7) · `llm_open_paper_trade` 500 (§2.8) · XSS sıfır · çok-kullanıcılı bakiye sızıntısı (#51) · WS `X-Real-IP`/HSTS/rate-limit/resource limitleri (nginx/compose).
Borsa: Retry-After/418 ban backoff (#31-33), N+1 hedef sorgusu (#58).

---

## 4. Doğrulanamayan / Şüpheli

- **"Trailing stop hiç persist edilmiyor" iddiası (otonom döngü ajanı):** Kaynağı inceledim; `applied_trailing = max(new_trailing, current)` tepe yükseldikçe `current`'ı aşar ve `update_auto_paper_trailing` çağrılır. İddia **bu haliyle doğrulanamadı** (davranış beklenen gibi). Yalnız "persist edilen değerin DB'de monotonic guard'ı yok" (P2-1) geçerli.
- Borsa tarafında `clientOrderId`'yi Binance TR'nin gerçekten dedup edip etmediği ve parametrelerin POST gövdesi mi sorgu dizesi mi olduğu **canlı borsa olmadan** doğrulanamadı.

---

## 5. Öncelikli Yol Haritası

1. **Deploy öncesi (P0):** Canlı bir `/state` anlık görüntüsünde `surge_blocked_symbols` ve son bildirim sayısını kontrol et; boşsa `MASTER_SURGE_REQUIRE_4WAY=false` ve/veya `MONITORING_MASTER_SURGE_GATE=false` ile kapıyı aç. `allowed_modes`'u en az `["trend_devam","unified","velocity"]` yap (yoksa hiç açılış olmaz). `REPORTS_BASELINE_AT`'i pozisyon yönetiminden **ayır** (yönetim `include_archived=True` okumalı).
2. **Para güvenliği:** Tüm cüzdan-yazan yollar için **tek** advisory-lock anahtarı (`paper_portfolio_open`) kullan; ya da `virtual_wallet` satırını `SELECT … FOR UPDATE` ile kilitle. Frontend iptal döngüsünde `res.ok` kontrolü ekle.
3. **Yetkilendirme:** Middleware'e rol bilinci ekle ya da P1-4'te listelenen rotalara `_require_admin` ekle; WS `Origin` doğrula; oturuma `client_fingerprint` bağla.
4. **Borsa dayanıklılığı:** `place_market_sell`'e `executedQty` doğrulaması + `last_price` geç; POST'ta geçici 5xx'te idempotency anahtarı zorunlu kıl; `set-sl-tp` yerleştir/dogrula adımını kilitle.
5. **DevOps:** `SCALPER_ENV=production`; secret'ları `*_FILE`/Docker secret'a taşı; köprü varsayılanını `enabled=false` + gerçek secret zorunlu yap; konteynerleri root dışı çalıştır; `init_db`'deki sürümsüz ALTER'ları try/except + uzun `lock_timeout` ile sar; migration sha'sını tek kaynağa indir.
6. **Test/CI:** Frontend `npm test`'i CI'ya ekle; mevcut 4 `assertTrue(True)` ve kaynak-metni testlerini davranış testine çevir; `conftest.py` ile merkezi fikstür.
7. **Hijyen:** 20,8 MB zip + 93 log + `node_modules` geçmişini `git filter-repo` ile temizle (332 MB → ~60 MB); ölü scriptleri arşivle; README/doküman sapmalarını düzelt.

---

## Ek — Denetim Kapsamı ve Arka Plan Doğrulamaları

**Paralel denetim başlıkları (15):** para/cüzdan mutabakatı · otonom ticaret döngüleri (auto_paper/velocity/macd) · radar & bildirim teslimi · master_surge & birleşik sinyal · borsa istemcileri (public/private/WS) · veritabanı & kilitler · arka plan döngüleri & zamanlayıcılar · ML/öğrenme & journal geri-beslemesi · LLM sohbet & araç yüzeyi · yetkilendirme & güvenlik · REST/SSE/WS katmanı · yapılandırma & env varsayılanları · ön yüz veri akışı & hata yönetimi · ön yüz görselleştirme & erişilebilirlik · test/CI & repo hijyeni.

**Arka planda ayrıca doğrulanan veri noktaları:**
- 1 MB üstü izlenen dosya sayısı **5**: `docs/*.zip` 20,8 MB · `pump24/state/oos_events_train.json` 5,9 MB · `pump24/state/m3_events.json` 2,4 MB · `backend/portfolio-replay-scan-121.log` 1,9 MB · `pump24/state/events.json` 1,3 MB.
- `.git` = **332 MB** (599 izlenen dosya); buna karşılık **çalışma ağacı 3,1 GB** — yani izlenen kaynak yalnızca ~60 MB iken ~3 GB'ı izlenmeyen/yoksayılan artık (`work/` altındaki `node_modules`, `.pytest_cache`, `.ruff_cache`, yerel `backend/scripts/*.log`). Depo geçmişi kadar *checkout* da şişmiş durumda.
- `.claude/` dizininde **izlenen dosya yok**; `.agents/`, `.commandcode/`, `.zcode/`, `.workbuddy-ai/` dizinlerine `backend/`, `frontend/`, `docker-compose.yaml` içinden **hiç atıf yok** → editör/araç artığı repo gürültüsü.
- Test koşusu sonunda `couldn't stop thread 'pool-1-worker-*'` uyarıları görülür (exit 0); kaynak kod kaynaklı değil, test sonlandırma sırasındaki thread kapatma gürültüsü — ancak P2-7/P1-7'deki "tek varsayılan executor" temasını teyit ediyor.

**Kısıt:** Tüm denetim **salt-okuma** yapıldı; bu rapor dışında hiçbir depo dosyası değiştirilmedi. Canlı borsa ve üretim veritabanı olmadan doğrulanamayan iki nokta §4'te açıkça belirtilmiştir.
