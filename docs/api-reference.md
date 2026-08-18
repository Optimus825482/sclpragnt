# Binance TR API Referansı — Scalper Agent V4

> **Oluşturulma:** 2026-08-18  
> **Kapsam:** Uygulamanın kullandığı tüm Binance TR public API endpoint'leri ve WebSocket stream'leri  
> **Kaynak:** `backend/app/binance_tr_public.py`, `backend/app/market_data.py`

---

## REST API Endpoint'leri

Uygulama **yalnızca public (API anahtarı gerektirmeyen)** endpoint'leri kullanır. Paper-only modda çalışır; hiçbir auth gerektiren endpoint (order, account) kullanılmaz.

Tüm REST çağrıları `_get_json()` yardımcısı (`binance_tr_public.py:48`) üzerinden yapılır:
- Base URL: `https://api.binance.me`
- Retry: 4 attempt, exponential backoff (0.35s → 4.0s), 429/5xx için
- Timeout: 15 saniye
- User-Agent: `scalperagent-v4`

---

### 1. `GET /api/v3/exchangeInfo`

| Alan | Değer |
|------|-------|
| **Dosya** | `binance_tr_public.py:101-108` |
| **Fonksiyon** | `trading_symbols(quote_asset="TRY")` |
| **Parametreler** | Yok (query string boş) |
| **Kullanım** | TRY quote asset'i ile TRADING statüsündeki tüm sembolleri listeler |
| **Çağrı frekansı** | `bootstrap_symbol_activity()` → saatlik (config: `TOP_GAINERS_REFRESH_SEC`) |
| **Rate limit etkisi** | Düşük (ağır payload, az çağrı) |

**Yanıt kullanımı:**
```python
payload = await asyncio.to_thread(_get_json, "/api/v3/exchangeInfo", {})
return sorted({
    str(item["symbol"]).upper()
    for item in payload.get("symbols", [])
    if item.get("status") == "TRADING" and item.get("quoteAsset") == quote_asset.upper()
})
```

**Not:** `symbols` array'indeki her sembol için şu alanlar mevcut ama **kullanılmıyor**:
- `baseAsset`, `quoteAsset` → sadece TRY filtresi
- `filters` (PRICE_FILTER, LOT_SIZE, MIN_NOTIONAL) → **kullanılmıyor** ⚠️
- `icebergAllowed`, `ocoAllowed` → kullanılmıyor
- `orderTypes` → kullanılmıyor
- `permissions` → kullanılmıyor

---

### 2. `GET /api/v1/klines`

| Alan | Değer |
|------|-------|
| **Dosya** | `binance_tr_public.py:73-80` |
| **Fonksiyon** | `klines(symbol, interval, limit, start_time_ms, end_time_ms)` |
| **Parametreler** | `symbol`, `interval`, `limit` (varsayılan 500), `startTime?`, `endTime?` |
| **Kullanım** | Geçmiş mum verisi çekme (tarihsel backfill + backtest) |
| **Çağrı frekansı** | `fetch_historical_data()` → her sembol × timeframe için 1 kez (başlangıçta), backtest'lerde isteğe bağlı |

**Yanıt formatı:** Her mum `[open_time, open, high, low, close, volume, close_time, quote_volume, trades, taker_buy_volume, taker_buy_quote_volume, ignore]`

**Not:** Binance TR dokümantasyonunda endpoint `/api/v3/klines` olarak geçer — burada `/api/v1/klines` kullanılması **olası bir hata** ⚠️.

---

### 3. `GET /api/v3/ticker/24hr`

| Alan | Değer |
|------|-------|
| **Dosya** | `binance_tr_public.py:111-112` |
| **Fonksiyon** | `ticker_24h()` |
| **Parametreler** | Yok (tüm semboller için) |
| **Kullanım** | 24 saatlik hacim/fiyat değişimi, Top Gainer radar'ı, likidite filtresi |
| **Çağrı frekansı** | `refresh_24h_tickers()` → her 10 saniyede bir |

**Yanıt alanları (kullanılanlar):**
- `symbol`, `lastPrice`, `quoteVolume`, `priceChangePercent`
- **Kullanılmayanlar:** `highPrice`, `lowPrice`, `volume`, `bidPrice`, `askPrice`, `openPrice`, `prevClosePrice`, `weightedAvgPrice`, `count`

**Not:** Her 10 saniyede tüm semboller için full payload çekmek, özellikle çok sayıda TRY paritesi varsa (~300+) gereksiz bant genişliği kullanımına yol açar. `symbol` parametresi ile sadece aktif semboller filtrelenebilir.

---

### 4. `GET /api/v3/depth`

| Alan | Değer |
|------|-------|
| **Dosya** | `binance_tr_public.py:114-129` |
| **Fonksiyon** | `orderbook(symbol, limit=5)` |
| **Parametreler** | `symbol`, `limit` (1-5, varsayılan 5) |
| **Kullanım** | Anlık likidite kontrolü (REST fallback), `run_portfolio_backtest.py` |
| **Çağrı frekansı** | Düşük (sadece backtest ve manuel tetiklemelerde) |

**Yanıt kullanımı:** `bids[0][0]` (en iyi alış), `asks[0][0]` (en iyi satış), `bids[0:5]`, `asks[0:5]`

---

## WebSocket Stream'leri

Uygulama **combined stream** endpoint'ini tek bir bağlantıda birleştirerek kullanır.

| Alan | Değer |
|------|-------|
| **Base URL** | `wss://stream-cloud.binance.tr/stream?streams=...` |
| **Dosya** | `market_data.py:81, 242-263` |
| **Bağlantı yönetimi** | Generation-based (yeni sembol/timeframe setinde tüm bağlantılar yeniden kurulur) |
| **Maks. stream/bağlantı** | 180 |

### Abone olunan stream tipleri

Her aktif sembol için 3 stream:

#### 5. `{symbol}@kline_{interval}`

| Alan | Değer |
|------|-------|
| **Kullanım** | Gerçek zamanlı mum verisi — strateji sinyali, trailing stop, broadcast |
| **Timeframe'ler** | `1m, 3m, 5m, 15m, 30m, 1h, 4h` + config'de aktif olanlar |
| **İşleme** | `market_data.py:364-427` (`_process_kline`) |
| **Kapanmış mum** | `candle["x"] == True` → kalıcı kayıt |
| **Açık mum** | Sadece ticker fiyatı güncellemesi |

#### 6. `{symbol}@depth5@100ms`

| Alan | Değer |
|------|-------|
| **Kullanım** | Emir defteri derinliği → spread, likidite, orderflow imbalance |
| **Frekans** | 100ms (en hızlı) |
| **İşleme** | `market_data.py:478-504` (`_process_orderbook`) |
| **Kullanılan alanlar** | `bid_qty` (top 5), `ask_qty` (top 5), spread, imbalance |

#### 7. `{symbol}@aggTrade`

| Alan | Değer |
|------|-------|
| **Kullanım** | Son işlem fiyatı/yönü → ticker güncelleme, akış yönü |
| **İşleme** | `market_data.py:370-378` |
| **Kullanılan alanlar** | `p` (fiyat), `q` (miktar), `m` (maker: true=sell) |

---

## API Çağrı Frekans Özeti

| Endpoint | Frekans | Veri hacmi |
|----------|---------|------------|
| `GET /api/v3/ticker/24hr` | Her 10 sn | ~300 sembol → büyük |
| `GET /api/v1/klines` | Başlangıç + backtest | Orta |
| `GET /api/v3/exchangeInfo` | Saatlik | Büyük (tek sefer) |
| `GET /api/v3/depth` | Manuel/backtest | Düşük |
| WS kline streams | Sürekli | Orta (her sembol × her tf) |
| WS depth5 stream | Sürekli (100ms) | Yüksek |
| WS aggTrade stream | Sürekli | Orta |

---

## Binance TR API ile Global Binance API Farkları

Binance TR, global Binance API ile çoğunlukla uyumludur ancak şu farklar vardır:

1. **Base URL:** `api.binance.me` (TR) vs `api.binance.com` (Global)
2. **WS URL:** `stream-cloud.binance.tr` (TR) vs `stream.binance.com` (Global)
3. **TR'ye özel semboller:** `_TRY` suffix'i (örn. `BTCTRY`) — globalde `BTCUSDT`
4. **Rate limit'ler:** TR'de genelde daha cömert (dokümante edilmemiş)
5. **Kline endpoint:** TR'de `/api/v1/klines`, globalde `/api/v3/klines` — **uygulama global v3 yerine TR v1 kullanıyor**

---

## Riskler ve Sınırlamalar

| Risk | Detay |
|------|-------|
| **Rate limiting** | `ticker/24hr` her 10 sn'de ~300 sembol çekiyor — rate limit'e takılma riski |
| **WS bağlantı kopması** | Generation-based reconnect var ama backoff jitter yok |
| **`/api/v1/klines`** | Binance TR'ye özel, global API ile uyumsuz — taşınabilirlik sorunu |
| **exchangeInfo filtresi** | Sadece `TRADING` + `TRY` — `filters` (min notional, lot size) göz ardı ediliyor |
| **Depth limit hep 5** | Daha derin likidite analizi için yetersiz olabilir |
