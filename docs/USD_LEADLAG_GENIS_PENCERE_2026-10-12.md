# USD Lead-Lag — Geniş Pencere Doğrulaması (45 gün) — 2026-10-12

Devam: [USD_LEADLAG_ARASTIRMASI_2026-10-12.md](USD_LEADLAG_ARASTIRMASI_2026-10-12.md)

## Neden bu koşu
Önceki USD lead-lag bulgusu ("residual +0.165 gerçek ama kararsız") yalnız **~6 günlük**
JSON cache'e dayanıyordu. Yedi turun yargıları için bu pencere çok dardı. Kullanıcı onayıyla
(`A`) veri **45 güne** çıkarıldı ve test tekrarlandı.

## Veri
- **SQLite** (`work/market_cache.sqlite`, kullanıcı tercihi: JSON cache değil):
  60 likit sembol × 60 gün 5m. TR = `XTRY`, Global = `XUSDT`.
- **773.113 kayıt** (önceki: ~200 bin, 6 gün). Hizalama `open_time` ile.

## Sonuç: dar pencere yanıltıcıydı — geniş pencere kesin "kararlı negatif" verdi

| Ölçüm | 6 gün (eski) | **45 gün (yeni)** |
|---|---|---|
| Aynı-bar korelasyon (GL↔TRY) | 0.865 | 0.890 |
| Residual→fwd (1 bar) | +0.165 | **+0.144** |
| Residual→fwd (3 bar) | +0.122 | +0.098 |
| Residual→fwd (6/12 bar) | +0.096 / — | +0.073 / +0.053 |
| 3-fold net (Global %0.10) | kararsız (ilk fold −0.147) | **−0.066 / −0.061 / −0.052** |
| Gün-gün pozitif | 2/4 | **2/19** |

Maliyet senaryoları (45 gün):

| Eşik | n | Brüt 15dk | Taker TR | Global %0.10 | Maker naif | Limit net |
|---|---|---|---|---|---|---|
| p90 | 21432 | +0.165% | −0.185% | −0.035% | +0.125% | −0.687% |
| p85 | 29727 | +0.128% | −0.222% | −0.072% | +0.088% | −0.698% |
| p80 | 36395 | +0.108% | −0.242% | −0.092% | +0.068% | −0.704% |

## Hüküm
**`REAL_BUT_COST_BOUND` — doğrulandı ve bu kez KARARLI NEGATİF.**
- USD lead-lag öncülüğü **gerçek** ve 45 günde de ayakta (residual +0.144).
- Ancak net EV **üç fold'un üçünde de negatif ve tutarlı** (−0.05…−0.07); gün-gün yalnız
  **2/19** pozitif.
- Önceki 6 günlük "ilk fold pozitif görüntüsü" **gürültüymüş** — geniş pencerede kayboldu.
- Maker-naif pozitif (+0.09…+0.13) ama **gerçek limit dolgusu −0.69** (adverse selection).

## Anlamı
Dar pencereye güvenmek bizi yanlış yöne götürecekti. Geniş pencere, yedi turdur görülen
örüntüyü kesinleştirdi: **sinyal gerçek, ham edge ~%0.10–0.17, maliyet tabanı (taker VEYA
maker+adverse-selection) bunun üstünde.** Bu sinyal ailesi mevcut TRY/spot + ücret yapısında
kârlı, kararlı otonom işlem üretmiyor.

## Not: uygulama etkilenmedi
Bu koşu ayrı bir SQLite dosyasında çalıştı. Canlı sistemin PostgreSQL'i (velocity=21462,
bekleyen kilit 0) ve Binance TR API (200 OK) sağlıklı doğrulandı.

## Yeniden üretim
```
python backend/scripts/fetch_sqlite_wide.py --days 60 --top 60
python backend/scripts/research_usd_leadlag_sqlite.py --days 45
```
Kilitler: `tests/test_research_usd_leadlag_sqlite.py` (Pearson/beta/hizalama/fold-kapısı).
