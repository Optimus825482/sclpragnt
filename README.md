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
        └── İkisi de TRUE ──► BUY (50 USDT)
        │
        ▼
executor.py ──► sanal cüzdan güncelle (USDT düş, coin ekle)
        │
        ▼
main.py ──► WebSocket /ws üzerinden frontend'e yayınla
```

## Pozisyon Yönetimi (Trailing Stop)

- **Giriş:** Hacim patlaması + fiyat > EMA(9) → 50 USDT ile LONG
- **Hard Stop:** Fiyat girişin %1 altına düşerse kapat
- **Take Profit:** Fiyat girişin %2 üstüne çıkarsa kapat
- **Break-even:** Fiyat girişin %0.2 üstüne çıkınca stop giriş fiyatına taşınır (zarar imkansızlaşır)
- **Trailing:** Fiyat zirveden %0.5 düşerse kapat (trend devam ettikçe kar büyür)

## Stack

| Katman   | Teknoloji                                                    |
| -------- | ------------------------------------------------------------ |
| Backend  | Python, FastAPI, WebSocket, SQLite (aiosqlite)               |
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

İnce ayarlar `backend/app/config.py` içinde: `SYMBOLS` (17 coin), `VOLUME_SPIKE_THRESHOLD` (1.5x), `DEFAULT_ORDER_USDT` (50), stop/tp/trailing yüzdeleri.

## API

- `GET /health` - durum, paper/public API bilgisi, açık pozisyonlar
- `WS /ws` - ticker / signal / portfolio mesajları (frontend bunu dinler)
- `.well-known` - alan doğrulama dosyaları için mount

## Uyarı

Sistem yalnızca paper trading modunda çalışır; gerçek emir göndermez ve API anahtarı gerektirmez.
## Production deployment (Coolify / Docker Compose)

The repository is deployable as three containers: `frontend`, `backend`, and an Nginx gateway. The gateway serves the frontend and proxies `/api`, `/health`, and `/ws` to the backend. SQLite is stored in the named `scalper_data` volume and survives container recreation.

Use `docker-compose.yaml` as the Compose file and point `scalper.erkanerdem.online` to the gateway service/port `80`. Coolify should terminate HTTPS at the domain proxy. The backend is deliberately paper-only (`LIVE_TRADING=false`); no Binance credentials are required for public market data.

The frontend uses same-origin API and WebSocket URLs in production, so no frontend URL environment variable is required. For a local split deployment, set `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL` at build time.
