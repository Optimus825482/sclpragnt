-- 026: MA ŞERİT BUY SİNYAL KAYDI (2026-10-18).
-- Aktif sembollerde 5 dk mumlarda "MA şerit BUY" kuralı (app/ma_buy_signals.py, grafikteki rozetle aynı) tetiklenince bir satır
-- yazılır; sinyalden 15 dk sonra en yüksek yükseliş vb. ölçüm doldurulur. Yalnız yönetici sayfası içindir (karar/emir YOK).
-- Tek satır = (sembol, zaman dilimi, sinyal mumu); iki kural aynı mumda olursa `rules` virgüllü birlikte tutulur. Idempotent.
CREATE TABLE IF NOT EXISTS ma_buy_signals (
  id BIGSERIAL PRIMARY KEY,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL DEFAULT '5m',
  bar_open_ms BIGINT NOT NULL,
  bar_close_ms BIGINT NOT NULL,
  detected_at DOUBLE PRECISION NOT NULL,
  rules TEXT NOT NULL,
  signal_price DOUBLE PRECISION NOT NULL,
  ema_fast DOUBLE PRECISION,
  ema_mid DOUBLE PRECISION,
  ema_slow DOUBLE PRECISION,
  status TEXT NOT NULL DEFAULT 'open',
  max_rise_5m_pct DOUBLE PRECISION,
  max_rise_10m_pct DOUBLE PRECISION,
  max_rise_15m_pct DOUBLE PRECISION,
  max_drop_15m_pct DOUBLE PRECISION,
  close_15m_pct DOUBLE PRECISION,
  peak_bar_minutes INTEGER,
  evaluated_at DOUBLE PRECISION,
  eval_attempts INTEGER NOT NULL DEFAULT 0,
  UNIQUE (symbol, timeframe, bar_open_ms)
);
CREATE INDEX IF NOT EXISTS ma_buy_signals_close_idx ON ma_buy_signals (bar_close_ms DESC);
CREATE INDEX IF NOT EXISTS ma_buy_signals_status_idx ON ma_buy_signals (status, bar_close_ms);
