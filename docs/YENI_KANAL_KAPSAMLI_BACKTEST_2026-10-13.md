# Yeni Bilgi Sınıfı — Kapsamlı Backtest (2026-10-13)

Devam: [YENI_KANAL_ON_TESTI_2026-10-13.md](YENI_KANAL_ON_TESTI_2026-10-13.md)

Araç: `backend/scripts/research_new_channels_backtest.py` — walk-forward (ilk %60
eğitim / %40 sınav), taker+maker maliyet, 3-fold, eşleştirilmiş t-testi.

## Sonuçlar

### A3 CROSS-VENUE (OKX BTC-USDT → BTCTRY) — anlamlı örneklem, BAŞARISIZ
OKX 5m geçmişi sayfalanarak **17.300 bar** çekildi; 3.250 eşleşen aday.
| Akış | n | Taker EV | Maker EV | 3-fold |
|---|---|---|---|---|
| Sinyal (OKX +hareket → TRY LONG) | 637 | **−0.356%** | −0.106% | −0.346/−0.355/−0.355 |
| Baz (tüm barlar) | 2754 | −0.351% | — | — |

Sinyal EV ≈ baz EV (−0.356 vs −0.351) → **öncülük edge YARATMIYOR**; 3-fold kararlı
negatif; kazanma %1.1. **GEÇMEDİ.**

### A1 FUNDING — veri penceresi yetersiz, SONUÇSUZ
Funding 8-saatlik (60 günde yalnız **179 nokta**). Eğitim-eşiği sınavda hiç sinyal
üretmedi (n=0). Daha uzun pencere (120-180 gün) gerekir; mevcut 60 günle ölçülemez.

### A2 FEAR&GREED — veri penceresi yetersiz, SONUÇSUZ
1d BTCTRY serisi sqlite'ta yalnız **30 gün**; F&G ile kesişim 5-6 nokta. Ölçülemez.

## KARAR
**Hiçbiri geçmedi.** A3 (tek anlamlı örneklem) net negatif — cross-venue öncülük
BTC→TRY'de edge üretmiyor. A1/A2 veri penceresi darlığından sonuçsuz; daha uzun
geçmiş biriktirilirse veya haftalık/aylık ufukta yeniden kurulursa test edilebilir.

Bu, **10. kez** aynı kök nedeni pekiştiriyor: denenen hiçbir bilgi sınıfı (fiyat,
hacim, order-flow, lead-lag, rejim, funding, cross-venue) maliyeti aşamadı.

## Notlar
- Cron/zamanlama KURULMADI (gereksiz). Script elle veya istenirse çağrılır:
  `python backend/scripts/research_new_channels_backtest.py --days 60`
- 1d veri serisi uzatılırsa (BKZ: `fill` döngüsü / sqlite 1d kapsamı) A1/A2 yeniden
  koşulmaya değer kısa vadeli iş.
- Rapor: `work/new_channels_backtest.json`.
