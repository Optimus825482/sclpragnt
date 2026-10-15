-- 015 — KULLANICI ARAYÜZ TERCİHLERİ (2026-10-15)
-- Kullanıcı menüsünde gizlenen öğeler (cihazlar arası aynı menü).
-- Idempotent: CREATE TABLE IF NOT EXISTS. Yalnız kullanıcıya özgü, hassas veri yok.
CREATE TABLE IF NOT EXISTS user_ui_prefs (
  user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  hidden_menu TEXT NOT NULL DEFAULT '[]',
  updated_at DOUBLE PRECISION NOT NULL
);
