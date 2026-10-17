-- 020: historical_candles'a TAKER ALIŞ HACMİ (2026-10-17).
-- Binance TR kline'ı 12 kolon döner: [9] takerBuyBaseVolume, [10] takerBuyQuoteVolume. Tablo bunları
-- saklamıyordu → rescan/desen analizlerinde "agresif alıcı payı" (canlı velocity'nin taker teyidi) ölçülemiyordu
-- (docs/RESCAN_HARNESS.md sapma tablosu; docs/CIKIS_DESEN_ANALIZI_2026-10-17.md sıradaki deney).
-- NULL = eski satır (scripts/backfill_historical_candles.py --refill-taker ile doldurulur).
-- Idempotent; yalnız kolon ekler.
ALTER TABLE historical_candles ADD COLUMN IF NOT EXISTS taker_buy_base_volume DOUBLE PRECISION;
ALTER TABLE historical_candles ADD COLUMN IF NOT EXISTS taker_buy_quote_volume DOUBLE PRECISION;
