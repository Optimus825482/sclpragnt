-- 023: TARİHSEL İŞLEM AKIŞI (dakikalık mikro-yapı) — yalnız araştırma (2026-10-17).
-- Binance TR'nin 310 TRY marketi Binance global TRY marketleriyle aynıdır (aynı aggTrade id/fiyat/zaman);
-- data.binance.vision aggTrades arşivi = Binance TR'nin kendi işlem geçmişi. scripts/backfill_trade_flow.py
-- arşivi (ve günün kuyruğunu REST'ten) dakikaya toplayıp buraya yazar. Canlı yazıcı YOK; retention
-- döngüsü bu tabloyu budamaz. Yalnız işlem olan dakikalar saklanır (minute_open_ms = dakika açılışı, UTC ms).
-- Büyük işlem eşikleri: big ≥ 10.000 TRY, whale ≥ 50.000 TRY (işlem başına quote tutarı).
-- buy = agresif alıcı (is_buyer_maker = False), sell = agresif satıcı (is_buyer_maker = True).
-- Idempotent.
CREATE TABLE IF NOT EXISTS historical_trade_flow (
  symbol TEXT NOT NULL,
  minute_open_ms BIGINT NOT NULL,
  n_trades INTEGER NOT NULL,
  buy_base DOUBLE PRECISION NOT NULL DEFAULT 0,
  sell_base DOUBLE PRECISION NOT NULL DEFAULT 0,
  buy_quote DOUBLE PRECISION NOT NULL DEFAULT 0,
  sell_quote DOUBLE PRECISION NOT NULL DEFAULT 0,
  vwap DOUBLE PRECISION,
  max_trade_quote DOUBLE PRECISION NOT NULL DEFAULT 0,
  big_buy_quote DOUBLE PRECISION NOT NULL DEFAULT 0,
  big_sell_quote DOUBLE PRECISION NOT NULL DEFAULT 0,
  big_buy_n INTEGER NOT NULL DEFAULT 0,
  big_sell_n INTEGER NOT NULL DEFAULT 0,
  whale_buy_quote DOUBLE PRECISION NOT NULL DEFAULT 0,
  whale_sell_quote DOUBLE PRECISION NOT NULL DEFAULT 0,
  first_agg_id BIGINT,
  last_agg_id BIGINT,
  PRIMARY KEY (symbol, minute_open_ms)
);
