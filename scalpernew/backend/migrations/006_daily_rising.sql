-- 006_daily_rising.sql — Günlük Momentum Adayları (2026-10-10)
--
-- Amaç: OGN/MAGIC gibi günlük pump adaylarını KALICI olarak saklamak ve
-- önerildiği andaki fiyat ile anlık fiyatı karşılaştırarak takip etmek.
-- Backtest (2670 gözlem): ret_8h>=+2 & ATR%>=0.5 & ADX>=25 & slope>=0.3.
--
-- Tablo, koşan dağıtımda `database._ensure_daily_rising_schema` (memoize DDL)
-- ile de idempotent oluşturulur; bu dosya temiz kurulum (fresh install) içindir.

CREATE TABLE IF NOT EXISTS daily_rising_candidates (
  id BIGSERIAL PRIMARY KEY,
  created_at DOUBLE PRECISION NOT NULL,
  symbol TEXT NOT NULL,
  price DOUBLE PRECISION,              -- önerildiği andaki fiyat (giriş referansı)
  target_pct DOUBLE PRECISION,         -- uygulama hedefi (TP)
  ceiling_pct DOUBLE PRECISION,        -- beklenen maksimum yükseliş (koşucu/tavan)
  ceiling_price DOUBLE PRECISION,      -- tavan fiyatı
  velocity_score DOUBLE PRECISION,
  ret_8h DOUBLE PRECISION,
  adx DOUBLE PRECISION,
  atr_pct DOUBLE PRECISION,
  slope DOUBLE PRECISION,
  spread_pct DOUBLE PRECISION,
  horizon_minutes INTEGER,
  status TEXT NOT NULL DEFAULT 'pending',   -- pending | touched | expired
  mfe_pct DOUBLE PRECISION,            -- gerçekleşen maksimum lehte hareket (%)
  mae_pct DOUBLE PRECISION,            -- gerçekleşen maksimum aleyhte hareket (%)
  peak_at DOUBLE PRECISION,
  evaluated_at DOUBLE PRECISION,
  notified BOOLEAN NOT NULL DEFAULT FALSE,
  auto_paper_trade_id INTEGER,
  details JSONB
);

CREATE INDEX IF NOT EXISTS idx_daily_rising_created ON daily_rising_candidates (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_daily_rising_symbol ON daily_rising_candidates (symbol);
CREATE INDEX IF NOT EXISTS idx_daily_rising_pending ON daily_rising_candidates (status)
  WHERE status = 'pending';
