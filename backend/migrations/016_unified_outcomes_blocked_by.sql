-- 016: BİRLEŞİK ADAY JOURNAL'INA `blocked_by` (2026-10-16).
-- AMAÇ: BTC rejim kalkanı (BTC_BEAR_REGIME_SHIELD) ve diğer kapıların engellediği adayların
-- SONRADAN gerçekten hedefe ulaşıp ulaşmadığını ölçmek (scripts/radar_shield_analysis.py).
-- Önceden journal engellenen satırları da yazıyordu ama NEDENİNİ saklamıyordu; geçmişten
-- "kalkan neyi kaçırdı" ölçülemiyordu.
-- Anlamı: '' = kapıdan GEÇTİ (biliniyor) · dolu = engel nedeni · NULL = eski satır (kayıt öncesi,
-- analizde kullanılmaz). Idempotent; yalnız kolon ekler, mevcut veriye dokunmaz.
ALTER TABLE unified_candidate_outcomes ADD COLUMN IF NOT EXISTS blocked_by TEXT;
