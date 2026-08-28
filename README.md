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
executor.py ──► sanal cüzdan güncelle (USDT düş, coin ekle)
        │
        ▼
main.py ──► WebSocket /ws üzerinden frontend'e yayınla
```

## Pozisyon Yönetimi (Aktif Stratejiye Göre)

- **BB_MFI_MEAN_REVERSION (varsayılan):** Hard stop −%8.882 (`BB_MFI_STOP_LOSS_PCT`), take profit +%2.317 (`BB_MFI_TAKE_PROFIT_PCT`), teyitli sell sinyali çıkışı (varsayılan 2 ardışık bar) ve LLM yönetilen plan stop/TP/max-hold.
- **Diğer (legacy) stratejiler:** Sistem stop'u, RR hedefine ulaşınca ATR trailing ve erken başarısızlık/bayat pozisyon kuralları.
- **Re-entry guard'ları:** Bar cooldown, timeout sonrası 24 saatlik blok, hard-stop sonrası 2 saatlik blok — timeout/hard-stop blokları restart'ta kalıcıdır.
- Not: eski belgedeki −%1 hard stop / +%0.2 break-even / %0.5 trailing modeli hiçbir aktif stratejide kullanılmaz; `TAKE_PROFIT_PCT` ve `TRAILING_*` sabitleri ölü yapılandırmadır.

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

İnce ayarlar `backend/app/config.py` içinde: sembol evreni, maliyet/likidite filtreleri, `DEFAULT_ORDER_USDT` (1.000 TRY; isim geriye dönük uyumluluk içindir, birim TRY'dır), BB-MFI stop/TP yüzdeleri, `BACKTEST_ASSUMED_SPREAD_PCT` (varsayılan 0,1%) ve `GAINER_RADAR_INTERVAL_SEC`. Yüksek hacimli gözlem tablolarının saklama süresi `RETENTION_DAYS` (varsayılan 30 gün) ile ayarlanır.

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

Custom backtest çıkış modeli `strategy_definition.exit_policy` ile seçilir. `mode` değerleri `conditions_only`, `conditions_plus_protection` veya `protection_only` olabilir; ayrıca `use_stop_loss`, `use_take_profit`, `use_trailing_stop`, `trailing_stop_pct`, `use_max_hold` ve `max_hold_bars` alanları desteklenir. Böylece koşullu çıkış seçildiğinde sistem zorla TP/SL uygulamaz.
- `.well-known` - alan doğrulama dosyaları için mount

## Uyarı

Sistem yalnızca paper trading modunda çalışır; gerçek emir göndermez ve API anahtarı gerektirmez.
## Production deployment (Coolify / Docker Compose)

The repository is deployable as three containers: `frontend`, `backend`, and an Nginx gateway. The gateway serves the frontend and proxies `/api`, `/health`, and `/ws` to the backend. Persistent runtime data is stored in PostgreSQL; the named `scalper_data` volume is reserved for paper/runtime artifacts.

### Otomatik top-gainer sembol aktivasyonu

Backend, `TOP_GAINERS_AUTO_ACTIVATE=true` (varsayılan) iken Binance TR public `/api/v3/ticker/24hr` ve TRY `exchangeInfo` verilerini 10 dakikada bir (`TOP_GAINERS_REFRESH_SEC=600`) kontrol eder. 24 saatlik değişime göre ilk `TOP_GAINERS_LIMIT=10` TRY sembolü analiz evrenine alınır. Açık pozisyon sembolleri yeni listenin dışında kalsa bile sistem tarafından korunur ve yönetilmeye devam eder. Bu akış yalnızca paper/public-data aktivasyonudur; gerçek emir göndermez.

Use `docker-compose.yaml` as the Compose file and point `scalper.erkanerdem.online` to the gateway service/port `80`. Coolify should terminate HTTPS at the domain proxy. The backend is deliberately paper-only (`LIVE_TRADING=false`); no Binance credentials are required for public market data.

The frontend uses same-origin API and WebSocket URLs in production, so no frontend URL environment variable is required. For a local split deployment, set `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL` at build time.
