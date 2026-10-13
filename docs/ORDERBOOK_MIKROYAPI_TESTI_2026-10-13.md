# Order-Book Mikro-Yapı Kapsamlı Testi (2026-10-13)

**ARAŞTIRMA — canlıya alınmadı.** Kullanıcı onayıyla ("OK") yapıldı.

## Yöntem
`backend/scripts/research_orderbook_micro.py` — Binance **futures `bookDepth`** günlük
arşivi (600+ gün kaynak; burada 20 gün, BTCUSDT) + futures 5m klines. Yerel önbellek
(`work/ob_cache/`), ikinci koşu ağa gitmez. **28.537 kayıt** (30 sn'lik snapshot → 5m/15m/30m
ileri getiri eşleşmesi).

**Zengin özellikler** (ham imbalance'ın ötesi):
`near_imb` (−0.2%/+0.2%), `deep_imb` (−5%/+5%), `full_imb` (tüm bantlar),
`slope_asym` (derinlik eğimi asimetrisi), `d_imb` (imbalance değişimi = order-flow),
`skew` (yakın−derin).

## Bulgular
### Korelasyon (özellik × ileri getiri ufku)
| Özellik | fwd5m | fwd15m | fwd30m |
|---|---|---|---|
| near_imb | +0.017 | +0.014 | +0.013 |
| **deep_imb** | +0.034 | +0.058 | **+0.082** |
| **full_imb** | +0.035 | +0.056 | **+0.080** |
| **slope_asym** | +0.033 | +0.057 | **+0.083** |
| d_imb (flow) | 0.000 | 0.001 | 0.000 |
| skew | −0.004 | −0.020 | −0.035 |

**İlginç:** derin ve toplam order-book dengesizliği 30 dk ufkunda pozitif korelasyon
(+0.08) — yakın seviyeden (+0.01) belirgin biçimde güçlü. Yani "yakın değil derin likidite"
sinyal taşıyor. Ama mutlak büyüklük zayıf.

### Walk-forward EV (sınav, taker %0.35)
En iyi hücreler:
| Hücre | n | Net EV | Kazanma |
|---|---|---|---|
| full_imb↑ fwd30 | 656 | −0.285% | 6.1% |
| deep_imb↑ fwd30 | 744 | −0.291% | 5.4% |
| slope_asym↑ fwd30 | 752 | −0.291% | 5.6% |

**Pozitif hücre: 0/36.** Hiçbir özellik×yön×ufuk kombinasyonu taker maliyeti geçmedi.

## Kritik nüans: brüt edge VAR ama maliyetin altında
`full_imb↑ fwd30` net −0.285% (taker dahil) → **brüt +0.065%**; maker ile −0.035%.
Yani order-book sinyali **sıfırdan biraz iyi** ama brüt edge ~+0.06%, round-trip maliyet
(0.10–0.35%) onun üstünde. **Edge var, maliyet duvarına takılıyor** — 11 turun tablosuyla
tutarlı.

## KARAR
**GEÇMEDİ.** Order-book tarihsel verisiyle (kullanıcı haklıydı, veri gerçekten var) zengin
mikro-yapı özellikleri test edildi; hiçbiri maliyeti geçmedi. Brüt edge ~+0.06% küçük
olması nedeniyle: (a) maker/limit yürütme + (b) daha uzun ufukta birkaç özelliğin
birleşimi ile *belki* sıfıra yakın bir bant; ama kâra çeviren bir konfig yok.

**Not:** Bu test BTCUSDT futures üzerinde. İşlem yaptığımız TRY spot evrenine
taşınabilirlik ayrıca zayıf (majör/futures sinyali TRY alt-coinlere doğrudan geçmez).

## 12 turun özeti
Denenen tüm bilgi sınıfları (fiyat, hacim, order-flow, lead-lag, rejim, funding,
cross-venue, **order-book L2 derinliği**) brüt edge ~0.05–0.2% üretti; hepsi
round-trip maliyetin (0.10–0.35%) ALTINDA. Tek ölçülebilir kazanım: çıkış SL 3.0→1.0.

## Yeniden üretim
```
python backend/scripts/research_orderbook_micro.py --days 20 --symbols BTCUSDT
```
Önbellek: `work/ob_cache/`. Rapor: `work/orderbook_micro.json`.
