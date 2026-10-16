-- 018 — KULLANICI ARAYÜZ TERCİHLERİ: FAVORİLER + SABİTLENEN İZLEME LİSTESİ (2026-10-17)
-- Her biri JSON metin: [{"symbol":"BTCTRY","price":123.4,"at":1760000000.0}, ...] (en çok 30 öğe, uygulamada doğrulanır).
-- Expand adımı: yalnız yeni kolonlar; eski kod bu şemada çalışmaya devam eder.
-- Idempotent: ADD COLUMN IF NOT EXISTS.
ALTER TABLE user_ui_prefs ADD COLUMN IF NOT EXISTS favorites TEXT NOT NULL DEFAULT '[]';
ALTER TABLE user_ui_prefs ADD COLUMN IF NOT EXISTS pinned TEXT NOT NULL DEFAULT '[]';
