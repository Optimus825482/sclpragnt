-- 030: SİNYAL SÜRE / STOP İSTATİSTİĞİ + BİLDİRİM İŞLEM PLANI (2026-10-27).
-- app/signal_eta.py geçmiş (push'u gitmiş) sinyalleri 1 dk mumlarla yeniden oynatır (24 saat penceresi):
--   hits[eşik]       = brüt eşiğe (%3,6 / 5 / 8 / 10) İLK ulaşma dakikası (null = ulaşmadı),
--   mae_before[eşik] = o ana kadarki en büyük düşüş (%, NEGATİF saklanır; null = ulaşmadı).
-- signal_eta_stats kova (radar / rising:<kind> / ma_buy:<tf>) x eşik başına özeti tutar (günde bir yeniden hesaplanır).
-- notification_trade_plans bildirim anında dondurulan işlem planını saklar (bildirim kaydıyla birlikte okunur).
-- Yalnız ekleme (expand); idempotent.
CREATE TABLE IF NOT EXISTS signal_eta_samples (
  source_kind TEXT NOT NULL,
  ref_id BIGINT NOT NULL,
  bucket TEXT NOT NULL,
  symbol TEXT NOT NULL,
  signal_ts DOUBLE PRECISION NOT NULL,
  entry_price DOUBLE PRECISION,
  hits JSONB NOT NULL,
  mae_before JSONB NOT NULL,
  measured_at DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (source_kind, ref_id)
);
CREATE INDEX IF NOT EXISTS idx_signal_eta_samples_bucket ON signal_eta_samples (bucket, signal_ts);

CREATE TABLE IF NOT EXISTS signal_eta_stats (
  bucket TEXT NOT NULL,
  threshold DOUBLE PRECISION NOT NULL,
  n INT NOT NULL,
  hit_rate DOUBLE PRECISION,
  p50_min DOUBLE PRECISION,
  p75_min DOUBLE PRECISION,
  mae_p80_pct DOUBLE PRECISION,
  updated_at DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (bucket, threshold)
);

CREATE TABLE IF NOT EXISTS notification_trade_plans (
  notification_key TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  bucket TEXT,
  plan JSONB NOT NULL,
  created_at DOUBLE PRECISION NOT NULL
);
