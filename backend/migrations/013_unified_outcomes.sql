-- 013: BİRLEŞİK ADAY SONUÇ JOURNAL'I (Faz 2).
-- Amaç: pulse/snapback/short-squeeze/master-surge ve birleşik scan_score'un
-- GERÇEK isabetini ölçmek. Her birleşik tarama turunda üretilen aday satırları
-- journal'a yazılır; ufuk penceresi dolduğunda 1m mumlarla MFE/MAE/hit doldurulur.
CREATE TABLE IF NOT EXISTS unified_candidate_outcomes (
  id BIGSERIAL PRIMARY KEY,
  symbol TEXT NOT NULL,
  horizon_minutes INTEGER NOT NULL DEFAULT 0,
  sources TEXT NOT NULL DEFAULT '[]',        -- JSON string array, örn. ["velocity","pulse"]
  scan_score DOUBLE PRECISION,
  entry_price DOUBLE PRECISION NOT NULL,
  ceiling_pct DOUBLE PRECISION,
  target_pct DOUBLE PRECISION,
  detected_at DOUBLE PRECISION NOT NULL,
  mfe_pct DOUBLE PRECISION,
  mae_pct DOUBLE PRECISION,
  hit BOOLEAN,
  outcome_filled_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_unified_outcomes_pending ON unified_candidate_outcomes(detected_at) WHERE outcome_filled_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_unified_outcomes_sym_time ON unified_candidate_outcomes(symbol, detected_at DESC);
