# Geçmiş vadeli işlem verisi (2026-10-17)

Binance USDT-M perp arşivinden (data.binance.vision) 90 gün (2026-07-19 → 2026-10-16) yerel veritabanına yazıldı.
Bu veri Binance TR TRY defteri değil; küresel likidite ve pozisyonlanma vekili. Yalnız araştırma, canlı yazıcı yok.

## Tablolar

| tablo | içerik | satır | perp | gün |
|---|---|---|---|---|
| `futures_symbol_map` | TRY tabanı → perp (×1000 çarpanlılar, LUNA→LUNA2) | 294 | — | — |
| `hist_futures_metrics` | 5 dk açık pozisyon (OI), üst trader L/S, hesap L/S, taker L/S hacim oranı | 7 503 935 | 291 | 90 |
| `hist_futures_bookdepth` | 5 dk dilim kapanışındaki ±1…5 % derinlik (adet + notional, geniş biçim) | 7 332 621 | 290 | 89 |
| `hist_funding_rate` | fonlama oranı + mark fiyatı | 137 320 | 290 | 90 |

- 16 tabanın perp'i yok (ACM, AMP, ATM, AUDIO, BAR, CITY, DODO, FDUSD, JUV, LAZIO, PORTO, PSG, U, USD1, USDC, USDT); RAD, RAY, STRAX arşivde boş.
- 2026-10-08 bookDepth günü arşivde yok.
- **Uyarı:** 2026-10-15 ~13:40 UTC'de Binance metrics dosyalarında toplu sıfır OI var (4 149 sıfır satırın 3 793'ü). Backtest'te `sum_open_interest > 0` filtresi şart.
- bookDepth ham 25 sn görüntü yerine 5 dk dilim kapanışı olarak saklandı (ileriye bakış yok; `--bucket-min` ile değişir).

## Gerçek TRY defter geçmişi (ücretli)

Tardis.dev'in "binance" borsası 369 `*try` sembolü içeriyor; ücretsiz örnekler (her ayın 1. günü) BTCTRY/ETHTRY/SOLTRY için indirildi (`backend/work/futures_hist/tardis_samples/`, 25 kademe defter görüntüsü). Fiyatlar Binance TR 5 dk kapanışlarıyla %0,1–0,2 içinde uyuşuyor.

| sağlayıcı | sunduğu | fiyat (2026-10-17 sayfadan; sözleşmeden önce doğrulayın) |
|---|---|---|
| Tardis.dev | Binance spot L2 artımlı defter, 5/25 kademe görüntü, trades; TRY dahil; 2019'dan | Spot Solo $900/ay, Pro $1 350, Academic $450; min. $300 |
| CoinAPI Flat Files | Binance spot defter görüntüsü 50, derinlik bantları | Snapshot 50 $24/GiB (kademeli düşer); TRY kapsamı doğrulanmadı |
| Kaiko | 30 sn ham defter görüntüsü | teklif; TRY doğrulanmadı |
| Amberdata | Binance defter görüntüleri | teklif; TRY doğrulanmadı |

## Yeniden çalıştırma

```
cd backend
PYTHONIOENCODING=utf-8 DATABASE_URL=... .venv/Scripts/python.exe scripts/backfill_futures_hist.py --days 90
```
# Tarihsel futures bağlamı — doğrulama (2026-10-17 18:37 UTC)

## Sembol eşleme
- TRY sembolü eşlenen: **294**, farklı perp: **294** (TRY TRADING taban sayısı 310)
- Yeniden adlandırılan/çarpanlı: BONKTRY→1000BONKUSDT(x1000), FLOKITRY→1000FLOKIUSDT(x1000), LUNATRY→LUNA2USDT(x1), LUNCTRY→1000LUNCUSDT(x1000), PEPETRY→1000PEPEUSDT(x1000), SHIBTRY→1000SHIBUSDT(x1000), XECTRY→1000XECUSDT(x1000)

## Kapsam (tablo bazında)
| tablo | satır | perp | gün (farklı) | min..max (UTC) | boyut |
|---|---|---|---|---|---|
| hist_futures_metrics | 7,503,935 | 291 | 90 | 07-19 00:00..10-16 23:55 | 1072 MB |
| hist_futures_bookdepth | 7,332,621 | 290 | 89 | 07-19 00:04..10-16 23:59 | 1852 MB |
| hist_funding_rate | 137,320 | 290 | 90 | 07-19 00:00..10-16 20:00 | 27 MB |

- Veritabanı toplam boyutu: **21 GB**
- Perp başına metrics gün sayısı dağılımı (gün: perp sayısı): 90: 289, 74: 1, 46: 1
- Perp başına bookDepth gün sayısı dağılımı: 89: 289, 45: 1

## Büyük 5 sembol sağlık kontrolü ve defter dengesizliği (quick look)
Dengesizlik = (alış notional − satış notional) / toplam; +1 = tüm derinlik alış tarafında.

| perp | OI>0 | derinlik monoton | funding ±0,5 % içinde | bd satır | imb ±1% ort / std / p5 / p95 | imb ±2% ort / std / p5 / p95 |
|---|---|---|---|---|---|---|
| BTCUSDT | HAYIR (14) | evet | evet (270) | 25329 | +0.054 / 0.287 / -0.274 / +0.901 | +0.047 / 0.194 / -0.188 / +0.463 |
| ETHUSDT | HAYIR (19) | evet | evet (270) | 25329 | +0.095 / 0.304 / -0.187 / +0.998 | +0.090 / 0.243 / -0.118 / +0.766 |
| SOLUSDT | HAYIR (19) | evet | evet (270) | 25329 | +0.087 / 0.255 / -0.103 / +0.990 | +0.105 / 0.212 / -0.072 / +0.688 |
| XRPUSDT | HAYIR (22) | evet | evet (270) | 25329 | +0.113 / 0.261 / -0.038 / +0.998 | +0.115 / 0.197 / -0.022 / +0.563 |
| BNBUSDT | HAYIR (11) | evet | evet (270) | 25329 | +0.109 / 0.295 / -0.180 / +0.996 | +0.106 / 0.250 / -0.127 / +0.997 |

## Genel tutarlılık (tüm perp'ler)
- OI <= 0 veya NULL metrics satırı: 4149
- |funding| > 0,5 % satır: 327
- bookDepth derinlik-monoton ihlali (satır): 0
