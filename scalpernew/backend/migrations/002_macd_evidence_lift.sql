-- 002 — MACD MONITOR kanıt katmanı: taban (baseline) + MFE/MAE + öncü skoru.
--
-- Gerekçe (outputs/macd_monitor_erken_sinyal_yol_haritasi.md §2 A2/A3):
-- `avg_pct` tek başına iyi/kötü demez. Aynı pencerede evrenin ortalama getirisi
-- bilinmeden "lift" hesaplanamaz. Bu migration iki şey ekler:
--   1) `macd_market_baseline` — 5m kova × ufuk bazında EVREN ortalaması/medyanı
--      ve pozitif oranı. Alarmın lift'i = alarm getirisi − aynı kova tabanı.
--   2) Alarm satırına MFE/MAE (%): alarm sonrası 30 dk içindeki en yüksek/en
--      düşük hareket — kâr potansiyeli ve maksimum ters hareket ölçüsü.
--
-- Sinyal DAVRANIŞINI değiştirmez; yalnızca ölçüm kalitesini artırır.

ALTER TABLE macd_monitor_alerts ADD COLUMN IF NOT EXISTS mfe_pct DOUBLE PRECISION;
ALTER TABLE macd_monitor_alerts ADD COLUMN IF NOT EXISTS mae_pct DOUBLE PRECISION;
ALTER TABLE macd_monitor_alerts ADD COLUMN IF NOT EXISTS early_score INTEGER;

CREATE TABLE IF NOT EXISTS macd_market_baseline (
  bucket_ts BIGINT NOT NULL,
  horizon TEXT NOT NULL,
  avg_pct DOUBLE PRECISION NOT NULL,
  med_pct DOUBLE PRECISION NOT NULL,
  hit_rate DOUBLE PRECISION NOT NULL,
  n_symbols INTEGER NOT NULL,
  filled_at DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (bucket_ts, horizon)
);

CREATE INDEX IF NOT EXISTS macd_market_baseline_ts_idx ON macd_market_baseline(bucket_ts DESC);
