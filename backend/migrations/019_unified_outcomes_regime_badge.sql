-- 019: BİRLEŞİK ADAY JOURNAL'INA `regime_badge` (2026-10-17).
-- RADAR_SHIELD_MODE=badge ile BTC rejim kalkanı artık adayı ENGELLEMEZ (blocked_by=''), bildirim
-- "⚠ BTC REJİM" rozetiyle gider. Rozetli (kalkan açıkken giden) ve rozetsiz bildirimlerin sonuçlarını
-- ayrı ölçebilmek için (scripts/radar_shield_analysis.py grup 'shield_badge') rozet ayrı kolonda tutulur.
-- Anlamı: NULL/'' = kalkan kapalıydı ya da eski satır · 'BTC_BEAR_REGIME_SHIELD' = kalkan açıkken rozetle geçti.
-- Idempotent; yalnız kolon ekler.
ALTER TABLE unified_candidate_outcomes ADD COLUMN IF NOT EXISTS regime_badge TEXT;
