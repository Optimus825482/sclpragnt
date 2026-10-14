-- 009_potential_target.sql — Potansiyel üst sınır sütunu (2026-10-10)
--
-- Amaç: "Yükseliş Adayları" listesinde gösterilen hedef (~%6) SCALPING için
-- kalibre edilmişti; pump coinler (%100+) için yanıltıcıydı. Ayrı bir
-- "potansiyel" sütunu eklendi = 30 günlük zirve / fib bazlı üst sınır.
--   potential_pct: beklenen maksimum yükseliş (%) — scalping tavanından BAĞIMSIZ.
--
-- Idempotent: ALTER ... IF NOT EXISTS (koşan dağıtımda database._ensure_* ile de).

ALTER TABLE daily_rising_candidates ADD COLUMN IF NOT EXISTS potential_pct DOUBLE PRECISION;
ALTER TABLE user_daily_watchlist ADD COLUMN IF NOT EXISTS potential_pct DOUBLE PRECISION;
