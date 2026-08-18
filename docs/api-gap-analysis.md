# Binance TR API — Boşluk Analizi ve İyileştirme Fırsatları

> **Oluşturulma:** 2026-08-18  
> **Amaç:** Mevcut API kullanımındaki eksik/hatalı noktaları tespit etmek ve dokümante edilmemiş API yeteneklerinden faydalanma fırsatlarını belirlemek

---

## 1. Mevcut Kullanımdaki Sorunlar

### 1.1 ⚠️ `/api/v1/klines` — Endpoint Sürüm Uyuşmazlığı

| | |
|---|---|
| **Dosya** | `binance_tr_public.py:80` |
| **Mevcut** | `_get_json("/api/v1/klines", params)` |
| **Beklenen** | `_get_json("/api/v3/klines", params)` (global Binance standardı) |

**Durum:** Binance TR, `/api/v1/klines` endpoint'ini destekliyor olabilir (bazı TR API'leri eski sürümleri korur). Ancak:
- Global Binance API'de kline endpoint'i **v3**'tür
- v1 desteği her an kaldırılabilir
- Taşınabilirlik sorunu: başka bir Binance API'sine geçişte kırılır

**Öneri:** `/api/v3/klines` ile test edip, çalışıyorsa geçiş yap. Çalışmıyorsa `/api/v1/klines`'in dokümante edildiğini teyit et.

---

### 1.2 ⚠️ `exchangeInfo` Filters Kullanılmıyor

| | |
|---|---|
| **Dosya** | `binance_tr_public.py:101-108` |
| **Mevcut** | Sadece `status == "TRADING"` ve `quoteAsset == "TRY"` filtresi |
| **Eksik** | `filters` array'indeki limitler kontrol edilmiyor |

`exchangeInfo` yanıtındaki her sembol için şu kritik filtreler mevcut:

```json
{
  "symbol": "BTCTRY",
  "filters": [
    {"filterType": "PRICE_FILTER", "minPrice": "0.01", "tickSize": "0.01"},
    {"filterType": "LOT_SIZE", "minQty": "0.00001", "stepSize": "0.00001"},
    {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"}
  ]
}
```

**Etkisi:**
- `MIN_NOTIONAL` → 10 TRY altı emirler reddedilir. Uygulama `MIN_NOTIONAL = 10.0` hardcoded kullanıyor ama **her sembol için farklı olabilir**. Örn: bazı yeni TRY paritelerinde min notional 100 TRY olabilir.
- `PRICE_FILTER` tickSize → emir fiyatının tick size'a uymaması durumunda paper simülasyonda bile hatalı sonuç.
- `LOT_SIZE` stepSize → miktar yuvarlaması yapılmazsa paper/gerçek emir uyuşmazlığı.

**Öneri:** `trading_symbols()` fonksiyonuna her sembol için filters bilgisini de döndürecek bir `trading_symbols_with_filters()` varyantı ekle. Entry order hesaplamasında minNotional ve stepSize kullan.

---

### 1.3 ⚡ `ticker/24hr` — Optimize Edilmemiş Ağır Çağrı

| | |
|---|---|
| **Dosya** | `market_data.py:192-232` |
| **Mevcut** | Her 10 saniyede **tüm TRY sembolleri** için full payload |
| **Sorun** | 300+ TRY paritesinde her çağrı ~150KB+ veri |

Binance API'si `symbol` parametresi ile tek veya birden çok sembol filtrelenebilir:

```
GET /api/v3/ticker/24hr?symbols=["BTCTRY","ETHTRY"]
```

Ya da tekil:
```
GET /api/v3/ticker/24hr?symbol=BTCTRY
```

**Öneri:** Sadece **aktif olarak izlenen semboller** için ticker çek. Pasif/izlenmeyen semboller için saatlik yeterli.

---

### 1.4 ⚡ Kullanılmayan ticker/24hr Alanları

Her çağrıda `highPrice`, `lowPrice`, `openPrice`, `volume`, `count`, `bidPrice`, `askPrice` gibi kullanılmayan alanlar da geliyor. Özellikle:
- `bidPrice`/`askPrice` → WS depth'ten zaten alınıyor, REST fallback olarak kullanılabilir
- `count` → işlem sayısı, aktivite metriklerinde kullanılabilir

---

### 1.5 🔄 WebSocket Stream Listesi Gereksiz Geniş

| | |
|---|---|
| **Dosya** | `market_data.py:242-263` |
| **Mevcut** | Her sembol için **tüm timeframe'ler** + depth + aggTrade |
| **Sorun** | `3m`, `30m` gibi aktif stratejide kullanılmayan timeframe'ler de abone |

`_all_timeframes()` set'i `["1m","3m","5m","15m","30m","1h","4h"]` + config'deki tüm strateji timeframe'lerini içeriyor. Ama aktif strateji sadece bir timeframe kullanıyor.

**Öneri:** Sadece aktif stratejinin ihtiyaç duyduğu timeframe'lere abone ol. Analiz/R&D için ihtiyaç duyulan timeframe'leri ayrı bir "research" bağlantısında tut.

---

### 1.6 🔒 API Key Kullanılmaması (Paper-Only — Kasıtlı)

Uygulama yalnızca public endpoint'leri kullanıyor. Bu paper-only mod için doğru. Ancak ileride auth gerektiren endpoint'lere geçiş için altyapı yok:
- `BINANCE_API_KEY` / `BINANCE_API_SECRET` config'de tanımlı ama hiç kullanılmıyor
- HMAC imzalama fonksiyonu yok
- `security.py`'de auth endpoint yok

**Öneri:** Eğer paper-only kalınacaksa, config'deki API_KEY/SECRET alanlarını kaldır veya "yalnızca public" ibaresi ekle. Gerçek trading'e geçiş planı varsa imzalama altyapısını şimdiden hazırla.

---

## 2. Kullanılabilecek Ek API Yetenekleri

### 2.1 `GET /api/v3/ticker/price` — Hafif Fiyat Endpoint'i

```
GET /api/v3/ticker/price?symbol=BTCTRY
→ {"symbol":"BTCTRY","price":"850000"}
```

**Avantaj:** `ticker/24hr`'dan çok daha hafif (~100 byte vs ~2KB). Sadece son fiyat gereken durumlarda rate limit dostu.

**Kullanım senaryosu:** Portföy değerleme (sadece price lazım, 24h verileri değil), hızlı spread hesaplama (`price` + `bookTicker` ile).

---

### 2.2 `GET /api/v3/ticker/bookTicker` — En İyi Bid/Ask

```
GET /api/v3/ticker/bookTicker?symbol=BTCTRY
→ {"symbol":"BTCTRY","bidPrice":"849500","bidQty":"0.5","askPrice":"850000","askQty":"1.2"}
```

**Avantaj:** Depth'ten (5 seviye) çok daha hafif, spread hesaplama için ideal.

**Kullanım senaryosu:** REST fallback olarak WS depth kesildiğinde spread/likidite kontrolü.

---

### 2.3 `GET /api/v3/avgPrice` — Ortalama İşlem Fiyatı

```
GET /api/v3/avgPrice?symbol=BTCTRY
→ {"mins":5,"price":"849750"}
```

**Avantaj:** Son 5 dakikanın ağırlıklı ortalama fiyatı.

**Kullanım senaryosu:** Büyük emir simülasyonu (slippage tahmini), "adil fiyat" karşılaştırması.

---

### 2.4 `GET /api/v3/klines` UIKlines — Optimize Kline

Global Binance, `UIKlines` endpoint'i ile **sadece open, high, low, close, volume** döndüren optimize edilmiş bir kline varyantı sunar (gereksiz alanlar olmadan).

**Kullanım senaryosu:** Geçmiş veri çekme işlemlerini hızlandırma.

---

### 2.5 WebSocket `{symbol}@bookTicker` — Hafif OrderBook Stream'i

```
wss://.../btctry@bookTicker
→ {"u":4009,"s":"BTCTRY","b":"849500","B":"0.5","a":"850000","A":"1.2"}
```

**Avantaj:** `depth5@100ms`'den çok daha az bant genişliği. Sadece en iyi bid/ask.

**Kullanım senaryosu:** `depth5`'e alternatif — spread hesaplama için 5 seviye derinlik gerekmiyorsa.

---

### 2.6 WebSocket `{symbol}@trade` — Raw Trade Stream'i

`@aggTrade` aggregated trade'leri verir; `@trade` ise **ham işlem akışını** verir. Daha yüksek frekanslı veri.

**Kullanım senaryosu:** Volume profile, VWAP hesaplama, işlem akışı analizi.

---

### 2.7 `GET /api/v3/trades` — Historical Trades

```
GET /api/v3/trades?symbol=BTCTRY&limit=100
→ [{id, price, qty, quoteQty, time, isBuyerMaker, isBestMatch}]
```

**Avantaj:** Son işlemlerin listesi. Likidite analizi ve spread gerçekleşme kontrolü için.

**Kullanım senaryosu:** Likidite doğrulaması, slippage analizi.

---

## 3. Yeni Modül/Özellik Fırsatları

### 3.1 📊 Rate Limit Monitor Modülü

Binance TR API'sinin rate limit'leri dokümantasyonda belirtilmiştir:
- `ticker/24hr`: ~50 request/dakika (tahmini)
- `klines`: ~1200 request/dakika
- `depth`: ~100 request/dakika
- `exchangeInfo`: ~20 request/dakika
- WebSocket: bağlantı başına ~1024 stream

**Modül:** Her API çağrısında `X-MBX-ORDER-COUNT-*`, `X-MBX-USED-WEIGHT-*` (veya TR eşdeğeri) header'larını loglayan, limit aşımı durumunda backoff uygulayan bir **RateLimitTracker**.

**Değer:** Üretimde rate limit aşımını önler, çağrı optimizasyonu için veri sağlar.

---

### 3.2 🔍 Sembol Filter Doğrulama Modülü

`exchangeInfo` → `filters` verisini kullanarak:
- Min notional doğrulaması
- Lot size step yuvarlaması
- Price tick size yuvarlaması

**Modül:** `backend/app/symbol_filter.py` — `validate_order(symbol, price, quantity) -> (adjusted_price, adjusted_quantity, warnings)`

**Değer:** Paper simülasyonda bile gerçekçi emir validasyonu; gerçek trading'e geçişte sıfır değişiklik.

---

### 3.3 📈 Market Microstructure Analyzer

Şu an depth5 + aggTrade verileri toplanıyor ama **derin analiz yapılmıyor**:
- Spread zaman serisi analizi
- Order book imbalance trend'i
- Likidite şok tespiti
- Buy/sell pressure metrikleri

**Modül:** `backend/app/microstructure.py` — var olan `market_data.orderflow` verisini kullanarak metrik üretimi.

**Değer:** Giriş/çıkış kararlarını iyileştirecek ek sinyaller.

---

### 3.4 🔄 API Health Dashboard

Tüm API endpoint'lerinin ve WS bağlantılarının sağlığını izleyen bir dashboard.

**Veriler (zaten toplanıyor):**
- `market_data.rest_last_event_at`, `rest_last_error`
- `market_data.ws_last_event_at`, `ws_last_error`
- `market_data.connection_generation`

**Modül:** Frontend'de `/system-health` sayfasına API health sekmesi ekle.

**Değer:** Operasyonel görünürlük, hata ayıklama kolaylığı.

---

## 4. Öncelik Sıralaması

| # | Bulgu | Öncelik | Tahmini Efor |
|---|-------|---------|-------------|
| 1 | `exchangeInfo` filters kullanımı (lot size + min notional) | **Yüksek** | 2-3 saat |
| 2 | `ticker/24hr`'a symbol filtresi ekleme | **Yüksek** | 1 saat |
| 3 | API Rate Limit Monitor | **Orta** | 3-4 saat |
| 4 | `/api/v1/klines` → v3 uyumluluk testi | **Orta** | 0.5 saat |
| 5 | `bookTicker` WS stream'i ekleme | **Orta** | 1-2 saat |
| 6 | Microstructure Analyzer modülü | **Düşük** | 4-6 saat |
| 7 | API Health Dashboard | **Düşük** | 2-3 saat |
| 8 | `/api/v3/avgPrice` ve `/api/v3/ticker/price` ekleme | **Düşük** | 1 saat |
| 9 | Sembol Filter Doğrulama modülü | **Düşük** | 2-3 saat |
