-- 021: BİRLEŞİK ADAY JOURNAL'INA `features` (2026-10-17).
-- Taker alış payı, emir defteri dengesizliği, mikro yapı (balina/CVD), spread, mod, RSI/MFI gibi
-- aday anı özellikleri (app/candidate_features.py, JSON metin). Mum verisinde olmayan bu alanlar
-- ileride desen analizinde kullanılacak (docs/CIKIS_DESEN_ANALIZI_2026-10-17.md §5).
-- NULL = eski satır. Idempotent.
ALTER TABLE unified_candidate_outcomes ADD COLUMN IF NOT EXISTS features TEXT;
