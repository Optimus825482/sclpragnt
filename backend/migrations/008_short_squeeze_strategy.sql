-- 008_short_squeeze_strategy.sql — Short-Squeeze stratejisi kaynağı (2026-10-10)
--
-- Amaç: "Yükseliş Adayları" listesine short-squeeze stratejisi eklendi. Her
-- adayın HANGİ stratejiden geldiği saklanır → ileride hangisinin daha isabetli
-- olduğu ölçülüp biri bırakılabilir (kullanıcı kararı).
--   strategy: 'daily_momentum' | 'short_squeeze' | 'both'
--
-- Idempotent: CREATE + ALTER ... IF NOT EXISTS (koşan dağıtımda
-- database._ensure_*_schema ile de uygulanır).

ALTER TABLE daily_rising_candidates ADD COLUMN IF NOT EXISTS strategy TEXT;
ALTER TABLE user_daily_watchlist ADD COLUMN IF NOT EXISTS strategy TEXT;

CREATE INDEX IF NOT EXISTS idx_daily_rising_strategy
  ON daily_rising_candidates (strategy, created_at DESC);
