# Uygulama Denetim Raporu — 2026-10-15

**Kapsam:** Scalper Agent V4 monorepo (backend FastAPI ~100k satır Python, `frontend/` ve `scalperintelligent/` Next.js arayüzleri, `whatsapp-bridge/`, nginx gateway, docker-compose, migrations, testler, dokümantasyon).
**Yöntem:** Beş bağımsız salt-okunur inceleme ajanı paralel çalıştı (işlem mantığı, güvenlik, frontend, altyapı, kalite/test). Her ajan bulguları dosya:satır ile raporladı; kritik bulgular koordinatör tarafından kodda tekrar doğrulandı. Hiçbir dosya değiştirilmedi, test ve docker çalıştırılmadı.
**Önem dereceleri:** P0 = para/veri kaybı veya hesap ele geçirme riski; P1 = yanlış sonuç, sessiz arıza, ciddi operasyonel risk; P2 = kalite, bakım, performans.

---

## 1. Yönetici Özeti

Cüzdan yolu (advisory lock, `FOR UPDATE`, idempotent kapanış, komisyon bacakları) ve kimlik doğrulama çekirdeği (PBKDF2 200k, HMAC oturum, HttpOnly/SameSite cookie, WS origin auth, Fernet ile şifreli API anahtarları) sağlam. Buna karşın beş alanda birbirini tetikleyen yapısal riskler var:

| # | Alan | En kritik bulgu | Önem |
|---|------|-----------------|------|
| 1 | Güvenlik | LLM `read_only_sql` aracı tablo allowlist'ini regex ile yapıyor; virgüllü join + `u.*` ile `password_hash`, telefon, şifreli anahtarlar sızıyor. Uygulama DB kullanıcısı **superuser**. Non-admin oturuma açık. | P0 |
| 2 | Güvenlik | WhatsApp köprüsünde `BRIDGE_KEY` boşsa (compose varsayılanı boş) `/send` kimliksiz; `/qr` her zaman kimliksiz (hesap ele geçirme). | P0 |
| 3 | Frontend | Gerçek emir panelinde (scalperintelligent) sembol/tutar 20 sn'lik yenileme ile kullanıcı fark etmeden değişebiliyor; klavye kısayolları modal açıkken aktif; idempotency anahtarı yok (çift emir). | P0 |
| 4 | İşlem mantığı | Ticker 15 sn bayatsa SL/trailing/max_hold hiç çalışmıyor (pozisyon korumasız). Stop dolumu `max(current, stop)` ile gap'te iyimser; ATR stop ölü kod. | P1 |
| 5 | Altyapı | Veritabanı yedeği yok (tek volume). `/health` döngü ölümünü yansıtmıyor, unhealthy konteyner yeniden başlamıyor. Migration'lar tek sha ile toptan koşuyor. | P1 |

Toplam: **4 P0, 24 P1, 33 P2** bulgu (aşağıda alan bazında).

---

## 2. İşlem / Sinyal / Pozisyon Mantığı (Backend)

Dosyalar: `backend/app/routers/{auto_paper,combined_paper,velocity,monitoring,runtime}.py`, `market_data.py`, `database.py`, `binance_public.py`.

| Önem | Konum | Sorun | Çözüm |
|------|-------|-------|-------|
| P1 | auto_paper.py:1047-1097 | Ticker >15 sn bayat veya yoksa `_manage_single_trade` erken `return`; SL, trailing, max_hold çalışmaz. Satır 1052 yorumu "bayat olsa da 60 dk dolunca kapat" diyor, kod yapmıyor. | Bayat fiyatta REST (`_fresh_public_price`) ile tazele; süre `max_hold×1.5`'i aşarsa REST fiyatıyla zorla kapat. |
| P1 | auto_paper.py:1117,1184,1288; combined_paper.py:200 | Stop çıkışı `max(current, stop)` ile dolar → gap'te zarar sistematik küçük, PnL iyimser. Slippage sabit %0.025 (config.py:976). | `min(current, stop)` kullan; gap'e duyarlı slippage. |
| P1 | auto_paper.py:460-483 | REST/bildirim fiyatı `timestamp=now` ile paylaşımlı `market.tickers`'a yazılıyor; 60 sn eski fiyat "taze" görünüyor. | `source` ve gerçek yaş ile yaz ya da tickers'a hiç yazma. |
| P1 | database.py:262; binance_public.py:119-251 | DB `to_thread` ve REST aynı default executor'da; 429/418'de `time.sleep` 300-3600 sn thread tutuyor → ban anında DB işleri (kapanışlar) kuyrukta kalır. | DB için ayrı `ThreadPoolExecutor`; REST'te thread uyutmak yerine paylaşımlı async cooldown + circuit breaker. |
| P1 | database.py:7483,7529,7553; combined_paper.py:135,239 | Kombine paper açılış/kapanış/güncelleme hataları `logger.debug` ile yutuluyor; kapanış `None` dönünce kimse bilmiyor. | `logger.exception`; dönüşü kontrol et, retry; `closing_failed` durumu + alarm. |
| P1 | combined_paper.py:82-107,129 | Giriş fiyatı WhatsApp listesindeki `candidate["price"]` (dakikalar eski); taze ticker kontrolü ve giriş slippage'i yok, çıkışta var. | `_price(sym)` ile taze fiyat; giriş slippage'i; bayatsa açma. |
| P2 | auto_paper.py:763 | `max(sl_pct, min(sl_pct, 1.2*atr_pct))` her zaman `sl_pct` döner; ATR stop ölü kod (doğrulandı). | `max(sl_pct, min(0.028, 1.2*atr_pct))` ya da amaçlanan formül. |
| P2 | velocity.py:2872-2873 | `_last_m5_close_ms` tarama öncesi güncelleniyor; exception'da o mum atlanır. | Başarılı taramadan sonra güncelle. |
| P2 | market_data.py:707-711 | `async for` temiz kapanışla biterse backoff'suz anında reconnect → fırtına. | Döngü çıkışında da minimum bekleme. |
| P2 | market_data.py:722 | Her WS hatasında dedup'sız `repair_history_gaps` görevi. | Grup başına tek onarım görevi. |
| P2 | monitoring.py:2898-2900 | `daily_momentum_last_day` tarama bitmeden set; hata → gün atlanır; pencere tek saat. | Günü başarıdan sonra işaretle; `>=` penceresi. |
| P2 | runtime.py:417-419; monitoring.py:6047 | Pozisyon yönetimi hatası `print` ile traceback'siz; sürekli hata veren pozisyon 5 sn'de bir sessizce atlanır. | Sembol başına ardışık hata sayacı + alarm; `exc_info=True`. |
| P2 | monitoring.py:1951 | LLM ikinci göz için sınırsız `create_task`. | Semaphore. |
| P2 | auto_paper.py:1055 | `max_hold` 120 dk, yorum "60 dk (Erkan kararı)"; gömülü sabitler (`sl_cooldown 5.0`, breakeven gap 0.3, `sleep(30)`). | Tek config kaynağı; yorum/varsayılan hizası. |

**Mimari öneriler**
- Üç paper defterini (auto_paper, combined, velocity) tek `PaperLedger` servisinde birleştir: ortak fill modeli, tazelik kapısı, komisyon sözleşmesi. Şu an aynı mantık üç kopya ve sapmış.
- Tek `PriceService`: WS + REST fallback + yaş bilgisi; `market.tickers`'a yalnız WS yazıcısı yazsın.
- Uzun ömürlü döngüler için ortak `run_forever(name, step, backoff)` sarmalayıcısı: hata sayacı, `exc_info`, `loop_health` entegrasyonu tek yerde.
- Para yolundaki `except: pass` / `logger.debug` kalıplarını tara ve kaldır.

---

## 3. Güvenlik

| Önem | Konum | Sorun | Çözüm |
|------|-------|-------|-------|
| **P0** | database.py:4818-4857; llm_chat.py:2831,3453,3716 | `read_only_sql` tablo tespiti yalnız `FROM\|JOIN <ad>` regex'i; `SELECT u.* FROM positions p, users u` ile `password_hash`, `user_preferences` (telefon), `audit_logs` (IP/UA), `user_binance_keys` dökülür. DB kullanıcısı superuser → `pg_read_file`, `pg_sleep`. Araç non-admin'e açık; `search_memory` üzerinden prompt-injection ile tetiklenebilir. | AST tabanlı (pglast/sqlglot) çıkarım; ayrı `llm_readonly` rolü (7 tabloya GRANT SELECT, `statement_timeout=5s`), `SET LOCAL ROLE`; uygulama kullanıcısını superuser'dan düşür. |
| **P0** | whatsapp-bridge/index.js:117-118,137-141,158; docker-compose.yaml:386 | `BRIDGE_KEY` boşsa `/send` kimliksiz (compose varsayılanı boş, doğrulandı: satır 118 `if (!BRIDGE_KEY) return true`); `/qr` ve `/status` her zaman kimliksiz; `to` serbest; `!==` timing. | `${WHATSAPP_BRIDGE_KEY:?}`; key yoksa process çıksın; `/qr` auth arkasına; `timingSafeEqual`; `to`'yu izinli numaralarla sınırla. |
| P1 | llm_chat.py:2888-2902,3513-3520,3716 | Non-admin sohbetten `close_llm_position`, `update_llm_position_plan`, `set/remove_llm_symbol_guard`, `deactivate_coin`, `reconcile_portfolio` çalıştırabilir. | `_llm_admin_denied` kapısını bu dallara ekle; non-admin tool listesini allowlist yap. |
| P1 | nginx/default.conf:4-5,125,144; security.py:134-138 | Traefik arkasında `$remote_addr` = Traefik IP → login brute-force kilidi ve `limit_req` tüm kullanıcılar için tek anahtara çöker (5 hatalı deneme herkesi kilitler). | `set_real_ip_from <subnet>; real_ip_header X-Forwarded-For; real_ip_recursive on;`; backend'de güvenilir XFF. |
| P1 | llm_chat.py:2737,3288; velocity.py:1924; macd_monitor.py:1791 | LLM chat'te istek başına rate limit yok (sınırsız provider maliyeti); `velocity/manual-scan` admin kapısız paper pozisyon açıyor; `macd-mtf/scan?force_refresh=1` pahalı. | `rate_limit(f"llm_chat:{username}")`, günlük token bütçesi; manual-scan'e `require_admin` + lock. |
| P2 | main.py:481-486 | Env-admin logout'ta `session_version` artmıyor; çalınan cookie 12 saat geçerli. | `set_user_session_version("admin", +1)`. |
| P2 | main.py:417-429 | Kullanıcı adı numaralandırma (timing): var olan ~100 ms, olmayan anında 401. | Dummy hash doğrula. |
| P2 | main.py:368,710 | DB kullanıcı parolası min 6 karakter. | ≥12 + sözlük kontrolü. |
| P2 | backend/scripts/*.py (6 dosya) | Sabit `postgresql://postgres:****@localhost` bağlantı dizesi. | Varsayılanı kaldır, `DATABASE_URL` zorunlu. |
| P2 | main.py:594-692 | Admin DB tarayıcı/CSV export `password_hash`, şifreli anahtar, telefon, IP dışa aktarıyor. | Hassas sütun maskeleme (database.py:4830 regex'ini yeniden kullan). |
| P2 | nginx/default.conf:83; main.py:161-162 | CSP yalnız Report-Only (`unsafe-inline/eval`); HSTS iki kaynaktan çelişkili. | Nonce'lu enforce CSP; HSTS tek kaynak. |
| P2 | user_prefs.py:161 | WhatsApp test ucu rate limit'siz → sahibin WA hesabı ban riski. | Kullanıcı başı `rate_limit`. |

**Olumlu:** CORS `*` reddi, WS origin+subprotocol auth, SSRF için DNS/private-IP kontrolü, `subprocess` argv-list, gerçek Binance emirlerinde çift onay + kullanıcı başı anahtar, repoda canlı sır yok, bağımlılıklar güncel (fastapi 0.141, next 16.3, cryptography 50).

---

## 4. Frontend (`frontend/` = fe, `scalperintelligent/` = si)

| Önem | Konum | Sorun | Çözüm |
|------|-------|-------|-------|
| **P0** | si/page.tsx:79-83,244-246; si/components/OrderPanel.tsx:149-152 | Gerçek emir panelinde `selected` null iken sembol `filtered[0]`'dan geliyor; 20 sn'lik tarama yenilemesi sıralamayı değiştirince panel sembolü değişir, `amount` sıfırlanır; onay modalı açıkken de. page.tsx:88-114 j/k/f/m/Enter kısayolları button/dialog hedefini filtrelemiyor; modal açıkken Enter `quickAmount=1000` atar. | `reviewOpen` iken prop senkronunu kapat; onaydaki sembol+tutarı snapshot'la gönder; kısayolları modal/button hedefinde kapat. |
| **P0** | si/components/OrderPanel.tsx:293-300,491-515 | Gerçek emirde client idempotency anahtarı yok → timeout'ta tekrar gönderim = çift emir. Onay modalında odak tuzağı/Esc yok (fe'de `useModalA11y` var, si'ye taşınmamış). | `client_order_id`; belirsiz hatada önce `order-status` sorgula; modal hook'unu paylaş. |
| P1 | si/lib/hooks.ts:31-59 | `usePoll` önceki isteği iptal etmiyor, yol değişince eski `data` kalıyor; OrderPanel eski sembolün fiyatıyla SL/TP doldurabiliyor. | AbortController + istek sırası guard'ı + path değişince sıfırla. |
| P1 | si/lib/watchlist.ts:61-68,90-102 | Favori GET'i 401/5xx olsa da `remoteReady=true` → localStorage boş listesi PUT edilir, sunucudaki favoriler silinir. Hook her bileşende ayrı mount (N×GET/PUT). | PUT'u yalnız kullanıcı toggle'ında ve GET başarılıysa; tek context. |
| P1 | si/components/TopNav.tsx:125-136; si/lib/liveSocket.ts:46 | WS yalnız `subscribeLive` çağıran sayfalarda (ana, grafik) açılıyor; diğer 5 sayfada rozet kalıcı "KOPUK". | AuthGate altında tek kalıcı abonelik (fe/Sidebar:54 gibi). |
| P1 | si/components/LiveNotificationToast.tsx:74-76 | Otomatik kapanma `now` batch anında yakalanmış → toast'lar silinmiyor. Bileşen yalnız ana sayfada. | `Date.now()` / id bazlı timeout; AppShell seviyesine taşı. |
| P1 | si/components/MarketChart.tsx:175-190,270 | Her kline tick'inde `setData` + `fitContent` → zoom/pan her saniye sıfırlanıyor; `load()` için request-id yok (sembol karışması). | `series.update()`; `fitContent` yalnız ilk yüklemede; request-id. |
| P2 | si/ActiveTradesTable.tsx:26; si/emirler:61-76; si/gecmis-islemler:52-53 | `settings.error` yok sayılıyor; API hatası "Binance bağlı değil" görünüyor; başarısız poll'da eski liste uyarısız. | "Son güncelleme X sn / yenilenemedi" bandı. |
| P2 | si/PortfolioStrip:23-29; ActiveTradesTable:20-21; OrderPanel:80-81 | `/api/binance/settings` ve `/positions` ana sayfada 3× ayrı polling. | SWR/React Query ile dedupe. |
| P2 | si/PortfolioStrip.tsx:39 | `Number(h.pnl_try \|\| 0)` eksik K/Z'yi 0 sayıyor ("veri yok ≠ 0" kuralına aykırı). | null'u ayır. |
| P2 | si/FavoriteTickerBand.tsx:43-49 | Sunucu `change_pct`'si iki poll farkıyla eziliyor, 24s değişimi gibi görünüyor. | Sunucu değerini kullan. |
| P2 | fe/portfolio/page.tsx:149-152,188-233 | `.catch(() => undefined)` sessiz hatalar; sayfalamada guard yok; 1 sn'lik `nowTs` state'i 716 satırlık sayfayı her saniye render ediyor. | Hata durumu; request guard; geri sayımı ayrı bileşene al. |
| P2 | fe/binance-tr/BinancePositionChartModal.tsx:429-435 | Çıplak `fetch` (401/credentials atlanıyor); backend hata verirse doğrudan `api.binance.com`'a düşüyor (CORS/geo-block, IP sızıntısı). | Yalnız backend proxy. |
| P2 | fe/lib/liveSocket.ts:97; si/lib/liveSocket.ts:60 | Yalnız `tickers` ön-filtreli; `binance_price` (her saniye, tüm piyasa) her sayfada JSON.parse. si/pnl.ts'te `netOpenPnl*` ölü, `applyCommissionPct` bağlanmamış. | Tip bazlı abonelik; parse öncesi string kontrolü. |
| P2 | a11y: si/TopNav:153; fe/BottomNav:31-39; si/ActiveTradesTable:65-72 | Mobilde Çıkış butonu yok; durum yalnız renk; `aria-current`/`aria-label` eksik; null değer yeşil. | Standart a11y düzeltmeleri. |
| P2 | si/next.config.js:13,24; fe/lib/api.ts:5-6 | `BACKEND_ORIGIN` build-time bake (runtime env etkisiz); `localhost:8004` sabit; event adları farklı (`scalper:` / `odak:auth-expired`). | Runtime env; parametrik basePath/event. |

**Öneriler**
- Birleştirmeden önce `packages/shared` çıkar (api, liveSocket, format, pnl, usePoll, auth). Kopyalar ayrışmış: fe'de `fmtMinute/formatRatioPct/closedPnlTry` + testler var si'de yok; si'de `formatPct/formatCompact` var fe'de yok; yüzde yazımı farklı (`+12,3%` vs `%12.3`).
- Kısa vadede iki arayüz kalsın; si'nin gerçek-emir akışını fe'nin güvenlik/a11y kalıplarıyla hizala, sonra fe'yi si'ye route-group olarak taşı.
- Büyük sayfaları böl ve `dynamic` yükle: binance-tr 2542, charts 2224, BinancePositionChartModal 2142, settings 2061, reports 1915, monitoring 1884 satır; ~188 `any`.

---

## 5. Altyapı ve Operasyon

| Önem | Konum | Sorun | Çözüm |
|------|-------|-------|-------|
| P1 | docker-compose.yaml:359-364; .env.example | **Yedek yok.** `db-backup` servisi kaldırılmış; `scalper_postgres_data` tek kopya (işlem geçmişi, öğrenme, kalibrasyon). Restore prosedürü yalnız not. | Günlük `pg_dump -Fc` cron/sidecar + off-box kopya + haftalık restore testi. |
| P1 | docker-compose.yaml:190-210; routers/system.py:33 | `/health` sabit "alive"; event loop kilitlenirse konteyner "canlı ama ölü". Docker unhealthy'yi yeniden başlatmaz; `watchdog/heartbeat` yok. | Loop heartbeat'ine bağlı `/health` (stale → 503); autoheal/Coolify restart; döngü ölümünde WhatsApp/push alarmı. |
| P1 | nginx/default.conf:17,43-59 | `resolver` var ama `proxy_pass` upstream bloklarına gidiyor; `backend:8004` yalnız nginx açılışında çözülür. Backend redeploy'da IP değişince 502/503 (yorum satır 31-39 trade-off'u kabul ediyor). | `set $u http://backend:8004; proxy_pass $u;` ya da deploy'da gateway'i de yeniden başlat (`depends_on … restart: true`). |
| P1 | backend/scripts/run_postgres_migration.py:44-91 | Migration'lar tek string'e birleştirilip tek sha ile toptan koşuyor; dosya başına takip yok, rollback yok; 001:191 `ALTER COLUMN … TYPE halfvec` her koşuda risk; ACCESS EXCLUSIVE kilit yarışı. | `schema_migrations(version, applied_at)` + dosya başına transaction; expand/contract kuralı. |
| P2 | backend/Dockerfile:1,6 | Taban imaj digest'siz (`python:3.11-slim`), `postgresql-client` sürümü kayabilir (pg17 ile `pg_dump` mismatch). | `python:3.11-slim-bookworm@sha256:…`; pgdg'den `postgresql-client-17`. |
| P2 | frontend/scalperintelligent/whatsapp-bridge Dockerfile'ları | Node 20/22 tutarsız (20 EOL Nis 2026); si runner ROOT, `npm install` (lock var ama `npm ci` değil); bridge root + tek aşama + imajda git/ssh. | `node:22-alpine` + `USER node` + `npm ci`; multi-stage. |
| P2 | scalperintelligent/, nginx/ | `.dockerignore` yok → host `node_modules/.next` context'e giriyor. | frontend/.dockerignore'u kopyala. |
| P2 | docker-compose.yaml:190-210 | Healthcheck `timeout: 8s` < komutun `urlopen(timeout=10)`; interval 5s + Python süreci 2 CPU limitinde yük. | interval 15-30s, timeout ≥ probe. |
| P2 | git ls-files | `.commandcode/` (8), `.zcode/plans` (4), `.workbuddy-ai/memory` (5), `sinyal_hedef_basarisi_all (3).csv`, `docs/backtest_results.json` izleniyor. | `git rm -r --cached …`; `.gitignore`'a `.zcode/ .workbuddy-ai/ *.csv`. |
| P2 | backend/entrypoint.sh | CRLF, `.gitattributes` yok → Windows'ta yerel build "exec format error". | `*.sh text eol=lf`. |
| P2 | docs/GLOBAL_COOLIFY_HEALTHCHECK_TALIMATI.md; README.md:120 | Başka projeye ait talimat; README "3 konteyner" diyor, compose 6 servis. | Arşivle; README dağıtım bölümünü güncelle. |
| P2 | Gözlemlenebilirlik | `/metrics` yok, loglar düz metin; DB havuzu `max_size=8` sabit. | `/metrics` (heartbeat yaşı, havuz doluluğu) + JSON log. |

**Olumlu:** hiçbir servis host portu yayımlamıyor; sırlar `${…:?}` ile zorunlu; `restart: unless-stopped` + mem/cpu limitleri; `depends_on service_healthy`; named volume'lar; `exec "$@"` ile SIGTERM ve düzgün `shutdown_services`; TZ tutarlı; backend/frontend/nginx non-root; compose log rotasyonu tüm servislerde.

---

## 6. Kod Kalitesi, Test ve Dokümantasyon

| Önem | Konum | Sorun | Çözüm |
|------|-------|-------|-------|
| P1 | database.py (7869 satır, 525 fn), monitoring.py (6145, 135 fn), main.py (5224, 191 fn) | God-modüller; `main.py`'de router'a çıkarılmamış mantık, doğrudan testi yok. | database → repository modülleri (positions/signals/outcomes/learning); monitoring → master_radar/surge_gates/notification/target_tracking; main.py → ~300 satır. |
| P1 | analyzer.py (1602), llm_chat.py (3760) | İsim eşleşen test yok; yalnız dolaylı import (9/10 test). | İndikatör/skor birim testleri; tool-dispatch sözleşme testi. |
| P1 | config.py (1305 satır, 302 env okuması) + 72 dağınık okuma (main 13, security 11, monitoring 10, llm_second_eye 9, llm_analysis 9) | Tek Settings modülü yok; tipleme/doğrulama yok. | pydantic-settings; açılışta şema doğrulaması. |
| P1 | README.md:29,47 | "13 modül, 11 include_router" → gerçekte 15 modül, 12 kayıt; `bridge.py` listelenmiş ama yok; `user_prefs` ve `journal` tabloda yok. | Sayıları üreten test/script; tabloyu düzelt. |
| P1 | frontend/, scalperintelligent/ | ESLint yok; si'de 0 test, CI'da yok. | eslint + `next lint` CI kapısı; si smoke test. |
| P2 | .github/workflows/backend-tests.yml:71-77 | Sert kapı yalnız ruff E9/F821/F811 + coverage ≥%55 (ölçülen %57); ~5000 E/F ihlali danışma modunda; mypy/pyproject/pre-commit yok. | Aşamalı kapı (önce F, sonra E501'siz E); mypy yeni modüllerde `--strict`. |
| P2 | `_fmt_price` ×3 (binance_tr_private, combined_radar, whatsapp_notify); `_clamp_*`, `_json_safe*` varyantları | Yinelenen yardımcılar. | `api_common` altında tek kopya. |
| P2 | docs/ (43 dosya) | Çoğu tarihli araştırma; ADR/CHANGELOG/runbook yok; TESTLER.md 230 satır tarihsel içerik taşıyor. | `docs/research/`, `docs/adr/`, CHANGELOG. |
| P2 | backend/tests | İsimlendirme denetim dalgası etiketli (`test_w11b_*`, `test_m4_*`), modülle eşleşmiyor. | Modül adıyla yeniden adlandır / `tests/<modül>/`. |

**Kapsam haritası (isim eşleşen / import eden test):** monitoring 3/24, runtime 2/3, market_data 2/7, analyzer 0/9, database 4/41, ws_runtime zayıf, llm_chat 0/10, main.py 0/24. Olumlu: skip/xfail yok, ölü kod işaretleri düşük (TODO 1, FIXME 0).

---

## 7. Öncelikli Aksiyon Planı

**Hemen (bu hafta, güvenlik + para yolu)**
1. `read_only_sql`: AST tabanlı çıkarım + ayrı `llm_readonly` DB rolü; uygulama kullanıcısını superuser'dan düşür. Non-admin LLM tool listesini allowlist'e çevir.
2. WhatsApp köprüsü: `BRIDGE_KEY` zorunlu, `/qr` auth arkasına, `to` kısıtı.
3. si OrderPanel: sembol/tutar snapshot'ı, modal açıkken kısayol/prop senkronu kapalı, `client_order_id`.
4. Günlük `pg_dump` + off-box kopya; bir kez restore testi.

**Kısa vade (2-3 hafta, doğruluk + operasyon)**
5. Bayat ticker'da SL/trailing/max_hold için REST fallback + zorla kapanış; stop dolumunu `min(current, stop)` yap; ATR stop formülünü düzelt; kombine paper'da taze giriş fiyatı + giriş slippage'i.
6. Para yolundaki `logger.debug`/`print` hata yutmalarını `exception` + alarm'a çevir; `closing_failed` durumu.
7. DB için ayrı executor; REST ban'ında thread uyutma yerine async cooldown.
8. Heartbeat'li `/health` + autoheal; nginx real_ip + upstream DNS davranışı; `schema_migrations` tablosu.

**Orta vade (1-2 ay, yapı)**
9. `PaperLedger` ve `PriceService` birleştirmesi; `run_forever` sarmalayıcısı.
10. database/monitoring/main bölünmesi (mevcut testler sözleşme olarak); analyzer/llm_chat/ws testleri; coverage eşiği %60.
11. pydantic-settings; `packages/shared` frontend paketi; ESLint + CI; si WS/toast/usePoll düzeltmeleri; SWR ile veri katmanı.
12. Repo hijyeni (`git rm --cached` araç artıkları, `.gitattributes`, `.dockerignore`), imaj digest sabitleme, Node 22 + non-root + `npm ci`, README/doc düzeltmeleri.

---

## 8. Sınırlar ve Doğrulama Notları

- Statik inceleme; testler ve docker çalıştırılmadı (PATH'teki Python'da pytest yok, `frontend/node_modules` yok).
- Koordinatör tarafından kodda tekrar doğrulananlar: ATR stop ölü kodu (auto_paper:763), stop dolumu (auto_paper:1117), LLM SQL regex (database:4818/4845), köprü `BRIDGE_KEY` atlaması (index.js:118), nginx upstream/resolver çelişkisi (default.conf:17,43), sha tabanlı migration (run_postgres_migration:44-85), `/health` sabit yanıtı (system.py:33).
- si OrderPanel sembol kayması (P0) ajan tarafından kodda okunarak raporlandı; `selectedView?.symbol` zinciri görüldü ancak `filtered[0]` fallback'inin tüm koşulları koordinatör tarafından tekrar izlenmedi. Düzeltmeden önce tarayıcıda yeniden üretilmesi önerilir.
- Frontend'de `frontend/` tarafı örneklenerek incelendi (portfolio, monitoring, binance-tr, daily-rising); 28 sayfanın tamamı okunmadı.

---

## 9. Düzeltme Durumu (2026-10-15, aynı gün)

Yedi paralel düzeltme ajanı + ayrı bir P0 güvenlik oturumu çalıştı. Çalışma kopyasındaki değişiklikler **commit edilmedi**; P0 güvenlik düzeltmeleri `refs/heads/claude/youthful-williamson-5280ef` dalında iki commit olarak duruyor (bu kopyaya henüz birleştirilmedi).

**Doğrulama**
| Kontrol | Sonuç |
|---|---|
| Backend pytest (HEAD temel) | 26 başarısız / 1963 geçti (26'sı yerel Postgres eksikliğinden) |
| Backend pytest (düzeltme sonrası) | 26 başarısız / 2038 geçti; başarısızlar HEAD ile birebir aynı, **yeni başarısızlık yok**, +75 yeni test |
| frontend tsc / vitest | temiz / 74 geçti |
| scalperintelligent tsc | temiz |
| ESLint (her iki arayüz) | 0 hata (uyarılar `warn`; CI'ya lint job'ı eklendi) |

**Kapatılan bulgular (özet)**
- §2 İşlem mantığı: 1–14'ün tamamı (bayat ticker REST fallback + zorla kapanış; stop dolumu `min(current, stop)`; tickers'a sahte taze fiyat yazımı kaldırıldı; ayrı DB executor; REST 429/418'de thread uyutmak yerine paylaşımlı cooldown + `BinanceCooldownError`; kombine paper'da taze giriş + giriş slippage'i + `logger.exception` + kapanış retry; ATR stop formülü; velocity M5 işareti; WS reconnect floor; tek onarım görevi; günlük momentum işareti; pozisyon/tarama döngülerinde ardışık hata sayacı + alarm; LLM ikinci göz eşzamanlılık tavanı; gömülü sabitler config'e).
- §3 Güvenlik: P0-1 ve P0-2 ayrı dalda (sqlglot AST doğrulama, `READ ONLY` + 5 sn timeout, `llm_readonly` rolü için migration 014, non-admin allowlist; köprüde zorunlu anahtar, tüm uçlarda auth, `timingSafeEqual`, `to` allowlist'i). Bu kopyada: güvenilir XFF ile gerçek istemci IP'si ve `kullanıcı|ip` kilit anahtarı; LLM chat rate limit; `macd-mtf force_refresh` ve `velocity/manual-scan` admin + kilit; env-admin logout'ta session_version; dummy-hash ile timing eşitleme; parola ≥12 + yaygın parola listesi; script'lerde sabit DSN kaldırıldı; admin export'ta hassas sütun maskeleme; backend HSTS kaldırıldı (nginx tek kaynak); WhatsApp test ucu rate limit. **Atlandı:** günlük LLM token bütçesi (kodda token sayacı yok).
- §4 Frontend: si P0-1/P0-2 (yalnız açık seçim, modal açıkken dondurulmuş snapshot, kısayol filtresi, `client_order_id` + backend idempotent replay, "durum belirsiz" akışı, odak tuzağı); `usePoll` abort/sıra guard'ı; `WatchlistProvider`; kabuk seviyesinde tek WS ve toast host; `series.update()`; poll hata bandı; null K/Z; sunucu `change_pct`; tip ön-filtreli WS; a11y düzeltmeleri. fe: portfolio/daily-rising hata durumları + `Countdown`; orderbook yalnız backend proxy; `subscribeLive(listener, types)`; `NEXT_PUBLIC_API_BASE`; BottomNav/TopBar a11y. **Atlandı:** SWR/React Query (bağımlılık eklenmedi; 5 sn modül-içi paylaşımlı fetch kullanıldı), `BACKEND_ORIGIN` runtime okuma (standalone'da mümkün değil, yorumlandı), ortak `packages/shared` paketi.
- §5 Altyapı: heartbeat'li `/health` (503), autoheal sidecar, compose healthcheck zamanlaması, `db-backup` servisi + `scripts/pg_backup.sh` + README restore satırı; nginx real_ip + HSTS includeSubDomains + düzeltilmiş yorum; gateway `depends_on … restart: true`; Dockerfile'lar (bookworm + `postgresql-client-17`, Node 22, `npm ci`, non-root, multi-stage bridge); `.dockerignore`/`.gitattributes`; 21 araç artığı `git rm --cached`; eski Coolify talimatı arşive; README dağıtım bölümü. **Atlandı:** `schema_migrations` tablosu (ayrı iş, aşağıda kart), imaj digest sabitleme (ağ yok).
- §6 Kalite: README router tablosu + drift testi; ESLint + CI lint job'ı; 17 analyzer birim testi; TESTLER.md sadeleştirme. **Atlandı:** ruff F kapısı (161 mevcut ihlal), god-modül bölünmesi, pydantic-settings, test yeniden adlandırma.

**Dikkat gerektiren noktalar**
- `test_w10_adapter_fixes.py` içindeki 3 retry testi ve `test_w18_runtime_residual.py` HSTS testi yeni sözleşmeye göre güncellendi (eski testler "thread'de 90–1200 sn uyu" davranışını kilitliyordu).
- whatsapp-bridge non-root'a geçti: mevcut `whatsapp_auth` volume'u tek seferlik `chown 1000:1000` ister (Dockerfile yorumunda).
- `frontend/package-lock.json` ve `scalperintelligent/package-lock.json` ESLint için güncellendi; `npm ci` bir sonraki kurulumda yeni paketleri alır.
- Tarayıcıda uçtan uca deneme yapılmadı; si OrderPanel akışı tip düzeyinde doğrulandı.
