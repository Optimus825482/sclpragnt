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

Eski 7.000+ satırlık `app/main.py` monoliti FastAPI `APIRouter` modüllerine bölünmüştür. `app/routers/` altında **11** router dosyası var ve **11** adet `include_router` kaydı yapılır (2026-09-26 denetimiyle doğrulandı; aşağıdaki tablo eksiksizdir):

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
- `POST /api/strategy/replay` + `GET /api/strategy/replay/{job_id}` - salt-okunur kapalı-mum karar tekrarı (`/signal-replay` sayfasının arkası)
- `.well-known` - alan doğrulama dosyaları için mount

## Uyarı

Varsayılan çalışma modunda sistem yalnızca paper trading yapar; sanal cüzdanda işlem yapar ve API anahtarı gerektirmez. Gerçek satış yalnız kullanıcı tarafından bilinçli olarak açılan üç katmanlı bir kapının arkasındadır — bkz. [Gerçek satış kapısı](#-gerçek-satış-kapısı-2026-09-26-düzeltmesi).
## Production deployment (Coolify / Docker Compose)

The repository is deployable as three containers: `frontend`, `backend`, and an Nginx gateway. The gateway serves the frontend and proxies `/api`, `/health`, and `/ws` to the backend. Persistent runtime data is stored in PostgreSQL; the named `scalper_data` volume is reserved for paper/runtime artifacts.

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
