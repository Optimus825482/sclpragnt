# Scalper Agent V4 - Paper Trading Bot

Binance spot piyasasında hacim patlaması + trend yakalayan otomatik scalping botu. **Paper trading** modunda çalışır - gerçek emir göndermez, sanal cüzdan üzerinde işlem yapar.

## Çalışma Mantığı

```
Binance Public WS (1m kline)
        │
        ▼
market_data.py ──► ticker + kapanış fiyatları + hacim
        │
        ▼
analyzer.py (her 2 sn, tüm coinler)
        │
        ├── Hacim patlaması?  (hacim > 1.5x son 10 bar ortalaması)
        ├── Trend yukarı?     (fiyat > 9 periyotluk EMA)
        └── İkisi de TRUE ──► BUY (varsayılan 1.000 TRY paper emir)
        │
        ▼
analyzer.py + database.py ──► sanal cüzdan güncelle (USDT düş, coin ekle)
        │
        ▼
main.py (app kurulumu + lifecycle + WS) ──► WebSocket /ws üzerinden frontend'e yayınla
```

### Modüler API yapısı

Eski monolitik `app/main.py` FastAPI `APIRouter` modüllerine bölünmüştür. `app/routers/` altında **17** modül dosyası vardır; bunların **14**'si `APIRouter` tanımlar ve `main.py` içinde **14** adet `include_router` kaydı yapılır (2026-10-16 doğrulaması; aşağıdaki tablo eksiksizdir ve `backend/tests/test_readme_router_table.py` ile CI'da doğrulanır). `runtime.py`, `global_radar.py` ve `llm_position_tools.py` `APIRouter` **kullanmaz**: `runtime.py` uzun-ömürlü döngüleri ve yardımcıları taşır (fonksiyonları `main.py` tarafından doğrudan import edilir), `global_radar.py` Binance Global arka plan tarama döngüsünü çalıştırır, `llm_position_tools.py` yalnız LLM araç (tool) şema tanımlarını sağlar.

| Modül | Sorumluluk |
|---|---|
| `app/main.py` | FastAPI kurulumu, CORS, startup/lifecycle, WS endpoint, pozisyon aç/kapa, config |
| `app/state.py` | Paylaşılan `market` + `analyzer` singleton'ları |
| `app/api_common.py` | Ortak runtime yardımcıları (scan log, correlation monitor, guard) |
| `app/routers/runtime.py` | Yayın, alert, strateji tarama, radar, sembol aktivite döngüleri |
| **`app/routers/monitoring.py`** | **Sistemin en kritik parçası: master radar, unified sinyal zarfı, master-surge kapıları, hedef/pending takibi, bildirim üretimi.** Bu modül 2026-09-26 denetimine kadar hiç belgelenmemişti (rapor #107) |
| `app/routers/macd_monitor.py` | MACD / rising-signal izleme döngüsü, kilit-temelli hesaplama |
| `app/routers/auto_paper.py` | Otonom paper pozisyon açma (radar/velocity bildirimlerinden), max-open ve idempotans kuralları |
| `app/routers/velocity.py` | Hız Avcısı aday takibi, microflow/sembol aktivasyonu, otonom paper girişler |
| `app/routers/llm_chat.py` | LLM sohbet, market tarama, chat auto-trade |
| `app/routers/chart_forecast.py` | Grafik için ML/istatistik tahmin uçları (cache'li) |
| `app/routers/llm_position_tools.py` | LLM'nin pozisyon okuma/eylem araçları |
| `app/routers/maintenance.py` | Backfill, replay-parity, strateji replay işleri |
| `app/routers/system.py` | Sağlık, memory, migration sistem rotaları |
| `app/routers/reports.py` | Salt-okunur rapor endpoint'leri |
| `app/routers/binance_trade.py` | Kullanıcı Binance TR işlemleri: Risk Merkezi ayarları, işlem planı (RR önerisi), idempotent pozisyon açma + OCO koruması, anahtar silme |
| `app/routers/global_radar.py` | Binance Global (USDT) spot piyasasını TR ile aynı velocity dedektöründen tarayan görünmez erken-tespit döngüsü (`APIRouter` yok; `main.py` döngüyü başlatır) |
| `app/routers/snapback.py` | Snapback Dip Avcısı (`/api/signals/snapback`) ve makro rejim kalkanı (`/api/signals/macro-regime`) |
| `app/routers/user_prefs.py` | Kullanıcı başına bildirim tercihleri (uygulama-içi, ses, WhatsApp) ve maskeli WhatsApp telefon numarası |
| `app/routers/journal.py` | Kullanıcıya özel işlem günlüğü (scalping disiplin notları, strateji etiketi); salt-not, emir/pozisyon değiştirmez |
| `app/routers/portfolio_band.py` | Üst menü altındaki portföy bandı için tek istekte özet (`/api/portfolio/band`): API anahtarı varsa Binance TR, yoksa paper değerleri; 10 sn önbellek |

Frontend'de `frontend/app/charts/` altında grafik mantığı `chartShared.ts` (format/yerleşim sabitleri) ve `signals.ts` (gösterge/strateji sinyal matematiği) olarak ayrılmıştır.

## Pozisyon Yönetimi (Aktif Stratejiye Göre)

- **LLM_PAPER / CHAT_PREDICTION / VELOCITY_AUTO (aktif):** Alım kararları LLM sohbet, chat-prediction veya otonom Hız Avcısı modüllerinden gelir. Sistem stop'u `HARD_STOP_LOSS_PCT=0.012` (−%1,2), TP `SPOT_PROFIT_TARGET_PCT=0.01` (+%1). LLM yönetilen plan stop/TP/max-hold ve erken başarısızlık/bayat pozisyon kuralları uygulanır.
- **BB_MFI_MEAN_REVERSION:** 2026-09-04 itibarıyla koddan kaldırılmıştır; belgedeki −%8,882 / +%2,317 sabitleri mevcut değildir.
- **Re-entry guard'ları:** Bar cooldown, timeout sonrası 24 saatlik blok, hard-stop sonrası 2 saatlik blok — timeout/hard-stop blokları restart'ta kalıcıdır.
- Not: eski belgedeki −%1 hard stop / +%0.2 break-even / %0.5 trailing modeli hiçbir aktif stratejide kullanılmaz; ölü yapılandırma sabitleri (`TAKE_PROFIT_PCT`, `TRAILING_*`, çok kademeli `TIME_DECAY_TP_*`) config'ten kaldırılmıştır.

## Stack

| Katman   | Teknoloji                                                    |
| -------- | ------------------------------------------------------------ |
| Backend  | Python, FastAPI, WebSocket, PostgreSQL (psycopg/asyncpg)     |
| Veri     | Binance Public WS (1m kline stream, tek bağlantıda birleşik) |
| Analiz   | NumPy (EMA, ortalama hacim)                                  |
| Frontend | Next.js, React, Tailwind                                     |

## Kurulum & Çalıştırma

```powershell
# Backend (port 8004)
cd backend
.\venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8004

# Frontend (port 3004)
cd frontend
npm run dev
```

Veya kök dizinde: `.\start.ps1` (iki servisi birden başlatır)

## Yapılandırma (.env)

| Değişken                                 | Varsayılan | Açıklama                                      |
| ---------------------------------------- | ---------- | --------------------------------------------- |
| Market API                               | public     | Yalnızca herkese açık piyasa verisi kullanılır |
| Başlangıç bakiyesi                       | 10.000 TL  | Sanal paper trading cüzdanı                   |
| Varsayılan paper emir tutarı              | 1.000 TRY   | `DEFAULT_ORDER_USDT` adı geriye dönük uyumluluk içindir |

İnce ayarlar `backend/app/config.py` içinde: sembol evreni, maliyet/likidite filtreleri, `DEFAULT_ORDER_USDT` (1.000 TRY; isim geriye dönük uyumluluk içindir, birim TRY'dür) ve `GAINER_RADAR_INTERVAL_SEC`. Yüksek hacimli gözlem tablolarının saklama süresi `RETENTION_DAYS` (varsayılan 30 gün) ile ayarlanır.

> **2026-09-26 notu — `BACKTEST_ASSUMED_SPREAD_PCT` artık kullanılmıyor.** Bu değişken `config.py` içinde **yoktur**; yalnız bakım dışı araştırma script'leri (`backend/scripts/replay_*.py`) `config`'den okumaya çalışır ve bu satırlar zaten `AttributeError` verir. `.env` dosyanıza yazmanız durumunda hiçbir etkisi olmaz. BB-MFI stop/TP yüzdeleri de 2026-09-04'te kaldırılan `BB_MFI_MEAN_REVERSION` stratejisine aitti ve config'de artık yoktur.

LLM paper giriş/çıkış ve sembol bazlı öğrenme sözleşmesi: [`docs/SCALPER_TRADE_POLICY.md`](docs/SCALPER_TRADE_POLICY.md).

Özel paper scalping agent skill'i: [`.agents/skills/scalper-trade-manager/SKILL.md`](.agents/skills/scalper-trade-manager/SKILL.md).

Kaynaklı araştırma ve uygulama eşlemesi: [`docs/SCALPER_RESEARCH_EVIDENCE.md`](docs/SCALPER_RESEARCH_EVIDENCE.md).

## API

- `GET /health` - durum, paper/public API bilgisi, açık pozisyonlar
- `GET /api/market/top-gainers?refresh=true` - Binance TR public 24 saatlik ticker verisinden ilk 10 TRY top-gainer sembolünü ve 10 dakikalık dinamik aktivasyon durumunu getirir/yeniler.
- `WS /ws` - ticker / signal / portfolio mesajları (frontend bunu dinler)
- `GET /api/market-klines/{symbol}` - frontend ve backend için ortak Binance TR public candle adapter’ı
- `GET /api/trades`, `/api/signals`, `/api/decisions` - `limit`, `offset` ve ilgili sembol/strateji filtreleriyle server-side listeleme
- `POST /api/combined-radar-replay/start` + `GET /api/combined-radar-replay/status` (+ `/report.csv`, `/sweep.csv`) - salt-okunur birleşik radar kapalı-mum tekrarı (Ayarlar sayfasındaki "Radar Replay" panelinin arkası)
- `POST /api/replay-parity-backfill/start` + `GET /api/replay-parity-backfill/status` (+ `/trades.csv`) - canlı/paper parite backfill işi

## Uyarı

Varsayılan çalışma modunda sistem yalnızca paper trading yapar; sanal cüzdanda işlem yapar ve API anahtarı gerektirmez. Gerçek satış yalnız kullanıcı tarafından bilinçli olarak açılan üç katmanlı bir kapının arkasındadır — bkz. [Gerçek satış kapısı](#-gerçek-satış-kapısı-2026-09-26-düzeltmesi).
## Production deployment (Coolify / Docker Compose)

`docker-compose.yaml` sekiz servis tanımlar (2026-10-15 denetim düzeltmesi — eski metin "üç konteyner" diyordu):

| Servis | Görev | Not |
|--------|-------|-----|
| `postgres` | PostgreSQL 17 + pgvector; tüm kalıcı veri (`scalper_postgres_data`) | `pg_isready` healthcheck |
| `backend` | FastAPI + tarayıcı/strateji döngüleri (port 8004, yalnız iç ağ) | `/health` döngü kaydına bakar, kritik döngü ölü/bayat ise **503** (`SCALPER_HEALTH_STALE_SEC`, varsayılan 120); `autoheal=true` etiketi |
| `frontend` | Eski Next.js arayüzü (3004) | |
| `gateway` | nginx: `/api`, `/health`, `/ws` → backend; `/` → frontend; rate-limit, güvenlik başlıkları, gerçek istemci IP'si (`set_real_ip_from`) | Tek dışa açık servis (Traefik → :80). Upstream'ler yeniden başlayınca `depends_on … restart: true` ile kendisi de yeniden başlar |
| `whatsapp-bridge` | Baileys WhatsApp köprüsü (3001, yalnız iç ağ) | Oturum `whatsapp_auth` volume'unda |
| `db-backup` | Günde bir `pg_dump -Fc` → `scalper_pg_backups` volume'u, son 14 dosya (`scripts/pg_backup.sh`) | Postgres ile aynı imaj |
| `autoheal` | `autoheal=true` etiketli unhealthy konteyneri yeniden başlatır (docker socket salt-okunur) | Docker tek başına unhealthy'yi restart ETMEZ |

Hiçbir servis host portu yayımlamaz; `scalper_data` volume'u paper/runtime artefaktları içindir.

**Yedekten geri yükleme** (custom format → `pg_restore`, `psql` DEĞİL; önce backend'i durdurun ki açık bağlantı/yazma olmasın):

```bash
docker compose stop backend
docker compose exec -T db-backup sh -c 'ls -1 /backups'      # dosya adını seç
docker compose exec -T db-backup sh -c 'pg_restore --clean --if-exists --no-owner --no-acl -d "$PGDATABASE" /backups/scalper_<YYYYMMDD_HHMMSS>.dump'
docker compose start backend
```

Off-box kopya için host'ta `docker volume inspect scalper_pg_backups` ile mountpoint'i bulup cron/rsync ile dışarı alın.

### LLM salt-okunur rol (deploy notu — 2026-10-15 denetimi)

LLM'in `read_only_sql` aracı sqlglot AST doğrulamasından geçer (`backend/app/sql_guard.py`), sorgu `READ ONLY` ve `statement_timeout = 5s` ile koşar ve `llm_readonly` rolüne (migration `014_llm_readonly_role.sql`) geçer. Migration rolü ve sütun bazlı SELECT yetkilerini oluşturur; ancak aşağıdakiler **deploy kararıdır** ve otomatik yapılmaz:

- Uygulama DB kullanıcısı (`DATABASE_URL`) hâlâ superuser ise, `pg_read_file` gibi yetkilerin etkisini tam kapatmak için **superuser olmayan** bir kullanıcıya geçilmelidir. Superuser ile LLM rolü yalnızca SQL katmanındaki savunmaya bağlı kalır.
- Migration, uygulama kullanıcısına `llm_readonly` üyeliğini vermeye çalışır; yetki yoksa NOTICE düşer ve `read_only_sql` sorguları rol geçişinde hata verir (kapalı başarısızlık). Bu durumda `GRANT llm_readonly TO <uygulama_kullanıcısı>;` komutunu bir süper kullanıcı ile elle çalıştırın.
- `ALLOWED_COLUMNS` (`sql_guard.py`) ile migration 014'teki GRANT listeleri birlikte güncellenmelidir.

### Otomatik top-gainer sembol aktivasyonu

Backend, `TOP_GAINERS_AUTO_ACTIVATE=true` (varsayılan) iken Binance TR public `/api/v3/ticker/24hr` ve TRY `exchangeInfo` verilerini 10 dakikada bir (`TOP_GAINERS_REFRESH_SEC=600`) kontrol eder. 24 saatlik değişime göre ilk `TOP_GAINERS_LIMIT=10` TRY sembolü analiz evrenine alınır. Açık pozisyon sembolleri yeni listenin dışında kalsa bile sistem tarafından korunur ve yönetilmeye devam eder. Bu akış yalnızca paper/public-data aktivasyonudur; gerçek emir göndermez.

Use `docker-compose.yaml` as the Compose file and point `scalper.erkanerdem.online` to the gateway service on port `80`. Coolify should terminate HTTPS at the domain proxy.

> ### ⚠️ Gerçek satış kapısı (2026-09-26 düzeltmesi)
>
> Önceki sürüm bu bölümde "backend kasıtlı olarak paper-only'dir (`LIVE_TRADING=false`)" diyordu. **Bu yanlıştı ve yanıltıcıydı:** `LIVE_TRADING` değişkeni `backend/app/` altında **hiçbir yerde okunmuyor** (grep ile doğrulandı) — yani güvenlik, var olmayan bir anahtara bağlanmıştı. `docker-compose.yaml` içindeki `LIVE_TRADING: "false"` satırı da tamamen etkisizdir.
>
> Gerçek kapı üç katmanlıdır (`main.py:_real_sell_state` / `_real_sell_state_for`):
>
> 1. **Sunucu üst kapısı** — `ENABLE_REAL_BINANCE_SELL` ortam değişkeni. Tanımlıysa **her şeyi geçersiz kılar**: `"1"/"true"/"yes"/"on"` → satış her zaman açık; başka bir değer → her zaman kapalı.
> 2. **Panel anahtarı** — env hiç tanımlı değilse `llm_settings.binance_real_sell_enabled` (`main.py:2333`) karar verir; UI'dan *Ayarlar → Binance TR* ile açılıp kapatılır.
> 3. **Kullanıcı anahtarı** — `user_binance_keys.real_sell_enabled` (DB, `database.py:4709`). Kullanıcı başına ayrı ayrı kontrol edilir.
>
> `POST /api/binance/sell` bu kapının kapalı olması halinde `403` döner. **Alış tarafı her zaman paper'dır**; gerçek satış yalnız bu üç anahtarın da açık olmasıyla mümkündür ve kullanıcının kimlik doğrulanmış oturumu + kendi API anahtarı gerektirir. Public piyasa verisi için hiçbir kimlik bilgisi gerekmez.

The frontend uses same-origin API and WebSocket URLs in production, so no frontend URL environment variable is required. For a local split deployment, set `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL` at build time.

## Deney disiplini (2026-10-15)

Radar eşikleri ve flag'leri için iki belge:

- Deney kaydı: `docs/DENEY_KAYDI.md`
- Eşik sözleşmesi ve yapısal maliyet sınırı: `docs/RADAR_ESIK_SOZLESMESI.md`

Kural: Hiçbir eşik veya flag değişikliği, `docs/DENEY_KAYDI.md` içinde karşılık gelen bir satır olmadan canlıya çıkmaz.

## Periyodik ölçüm (2026-10-16)

Radar bildirimlerinin gerçek kalitesi tek komutla ölçülür (salt-okunur; `DATABASE_URL` gerekir). Tüm betikler `backend/` klasöründen çalıştırılır; Windows'ta konsol için `PYTHONIOENCODING=utf-8` ayarlayın.

| Betik | Ne ölçer | Örnek |
|---|---|---|
| `scripts/notification_outcomes_report.py` | Bildirim × 5m mum: hit30/60/120, şans tabanı, MFE/MAE, net proxy; hafta/aile/mode/skor/saat kırılımı, karşı-olgusal kapı senaryoları, tekrarsız varyant, precision@k, Spearman | `python scripts/notification_outcomes_report.py --days 30 --out rapor.md --json` |
| `scripts/notification_outcomes_report.py --source signals` | Aynı ölçüm `signals` tablosundan (yalnız `--signals-actions`, varsayılan `BUY_SIGNAL`); sabit hedef %1.5/2/3, `strategy` kırılımı ve her stratejinin tarih aralığı | `python scripts/notification_outcomes_report.py --source signals --days 60 --out sinyal_60g.md` |
| `scripts/horizon_grid_report.py` | H (60–1440 dk) × T × S × maliyet ızgarası, iki çıkış kuralı, şans tabanı, haftalık kararlılık | `python scripts/horizon_grid_report.py --days 30 --out ufuk_30g.md` |
| `scripts/radar_periodic_review.py` | `radar_lift_analysis` + bildirim raporu + `radar_bucket_analysis` → `docs/reviews/RADAR_REVIEW_<tarih>.md` (aktif bayraklar başlıkta, sonda KARAR listesi) | `python scripts/radar_periodic_review.py --days 14` |

Not: `signals` kaydında kaldırılmış stratejiler (PUMP_MONITOR, BB_MFI_*, FISHER_*) eski dönemlere aittir; rapor stratejileri tarih aralığıyla ayrı yazar, "60 gün" sonuçlarını güncel politikayla karıştırmayın. Bildirim günlüğü 2026-09-16'da başlar.

Haftalık çalıştırma (pazartesi 09:00):

- Linux/cron: `0 9 * * 1 cd /srv/sclpragnt/backend && DATABASE_URL=... PYTHONIOENCODING=utf-8 .venv/bin/python scripts/radar_periodic_review.py --days 14`
- Windows Görev Zamanlayıcı: `schtasks /create /tn "RadarReview" /sc weekly /d MON /st 09:00 /tr "cmd /c cd /d D:\PROJELLER\sclpragnt\backend && set DATABASE_URL=... && set PYTHONIOENCODING=utf-8 && .venv\Scripts\python.exe scripts\radar_periodic_review.py --days 14"`

Çıktı kararları yalnız öneridir; eşik/flag değişikliği yine `docs/DENEY_KAYDI.md` satırı gerektirir.
