# Order-Book Tarihsel Veri + Funding 730g Ölçümü (2026-10-13)

**ARAŞTIRMA — canlıya alınmadı.**

## 1) Order-book tarihsel veri: VAR (kullanıcı haklıydı)

Daha önce "SPOT'ta order-book geçmişi yok" demiştim — bu SPOT için doğru. Ancak
**USDⓈ-M Futures'ta VAR:**

| Arşiv | Durum | Derinlik |
|---|---|---|
| **futures `bookDepth`** (günlük) | ✅ 200 OK | **600+ gün** (2025-02'ye kadar) |
| futures bookTicker / depth | ❌ 404 | — |
| futures aggTrades / trades / klines / metrics | ✅ | 600+ gün |
| spot bookDepth / depth / bookTicker | ❌ 404 | — |

**Format:** `timestamp (sn), percentage, depth, notional` — **bid negatif pct (−0.2…−5%),
ask pozitif (+0.2…+5%)**. 30 sn'de bir, **2880 nokta/gün**, ~540 KB/gün/BTCUSDT.
URL: `https://data.binance.vision/data/futures/um/daily/bookDepth/{SYM}/{SYM}-bookDepth-{YYYY-MM-DD}.zip`

**Sonuç: L2 derinlik sinyali GERİYE DÖNÜK TEST EDİLEBİLİR** (BTC/ETH gibi futures
sembollerinde). Not: işlem yaptığımız TRY spot evreninin futures karşılığı sınırlı;
sinyalin TRY'ye taşınabilirliği ayrı soru.

## 2) bookDepth mikro-yapı ön testi (BTCUSDT, 15 gün, 37.144 eşleşme)
| Özellik | corr(fwd 5m) | corr(fwd 15m) |
|---|---|---|
| Statik imbalance `(bid−ask)/(bid+ask)` | **+0.031** | +0.029 |
| Imbalance **değişimi** (order-flow proxy) | +0.013 | +0.007 |

- Bid-wall LONG (imbalance üst %15): **EV −0.354%** (negatif).
- Yani L2 imbalance sinyali **zayıf ve maliyetin altında**. (Önceki turda EURİSKE
  örneklemde bulduğum "tek gün −0.43" örneklem yanılgısıydı; 37K noktada +0.03.)

## 3) A1 FUNDING — 730 günle ölçüldü
2.189 funding noktası (2 yıl):
| Bant | n | Taker EV |
|---|---|---|
| Üst %10 funding (kalabalık long) | 61 | −0.262 |
| Alt %10 funding | 262 | −0.346 |
| Üst %50 / alt %50 | 323 / 553 | −0.348 / −0.351 |

Hiçbir bant pozitif değil; üst-%10 fold'ları kararsız (−0.27/+0.03/+0.20). **GEÇMEDİ.**

## KARAR
- **Order-book verisi var** ama ham L2 imbalance (statik veya flow) sinyali zayıf,
  maliyetin altında. Kapsamlı test (600 gün, bookTicker/aggTrades ile birlikte,
  mikro-fiyat/kısa ufuk) yapılmaya DEĞER ama ön test beklentiyi düşük tutuyor.
- **Funding** 730 günle de geçmedi.
- 11. kez aynı kök neden: sinyal bilgisi maliyetin altında.

## Sonraki adım (isteğe bağlı, uzun)
`bookDepth` 600 günlük arşivi indirip (BTC/ETH + TRY karşılığı olan futures semboller),
imbalance/derinlik-boşluğu/depth-slope gibi zengin mikro-yapı özelliklerini walk-forward
+ maliyetle tara. Bu, tek script + birkaç saatlik indirme işi. Ön test sonucu bunun
"kâra çevirmek" değil "edge var mı" sorusunu kesinleştireceğini gösteriyor.

## Yeniden üretim
Scriptler: `backend/scripts/research_new_channels_backtest.py` (funding/fg/cross-venue)
+ bu turdaki bookDepth ön testi (inline). Rapor: `work/new_channels_backtest.json`.
