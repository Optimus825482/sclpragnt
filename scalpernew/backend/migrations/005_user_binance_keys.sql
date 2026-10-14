-- 005 — KULLANICI BAZLI BINANCE API ANAHTARLARI (2026-09-19)
--
-- NEDEN: Binance TR sayfası admin'e özeldi; tek global anahtar seti
-- (llm_settings.binance_api_key_encrypted / binance_api_secret_encrypted)
-- tüm işlemleri adminin Binance hesabından yapıyordu. Sayfa tüm
-- kullanıcılara açılırken her kullanıcı KENDİ hesabıyla işlem yapmalı.
--
-- ÇÖZÜM: users.id başına Fernet ile şifrelenmiş key/secret satırı.
-- - user_id PRIMARY KEY (her kullanıcı en fazla bir anahtar seti)
-- - ON DELETE CASCADE: kullanıcı silinince anahtarları da gider
-- - Geriye uyum: admin için kullanıcı satırı yoksa eski global
--   llm_settings anahtarları fallback olarak kullanılır (main.py).
--
-- Idempotent: CREATE TABLE IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS user_binance_keys (
  user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  api_key_encrypted TEXT NOT NULL,
  api_secret_encrypted TEXT NOT NULL,
  real_sell_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);
