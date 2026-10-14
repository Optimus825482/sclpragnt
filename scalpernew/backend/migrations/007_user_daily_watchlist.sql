-- 007_user_daily_watchlist.sql — Kullanıcıya özel günlük yükseliş takip listesi (2026-10-10)
--
-- Amaç: Manuel tarama sonucu bulunan adayları KULLANICI ONAYIYLA o kullanıcıya
-- özel takip listesine eklemek. Her kullanıcı kendi listesini görür/yönetir.
--
-- Kimlik: `username` (lowercase) — security.request_user/session_user bu alanı
-- döndürür. `push_subscriptions.username` ile aynı kimlik deseni.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS + koşan dağıtımda
-- database._ensure_user_daily_watchlist_schema (memoize DDL) ile de oluşturulur.

CREATE TABLE IF NOT EXISTS user_daily_watchlist (
  id BIGSERIAL PRIMARY KEY,
  username TEXT NOT NULL,
  symbol TEXT NOT NULL,
  added_at DOUBLE PRECISION NOT NULL,
  entry_price DOUBLE PRECISION,          -- onaylandığı andaki fiyat (referans)
  ceiling_pct DOUBLE PRECISION,
  ceiling_price DOUBLE PRECISION,
  ret_8h DOUBLE PRECISION,
  adx DOUBLE PRECISION,
  slope DOUBLE PRECISION,
  atr_pct DOUBLE PRECISION,
  velocity_score DOUBLE PRECISION,
  source TEXT DEFAULT 'manual_scan',     -- manual_scan | auto
  active BOOLEAN NOT NULL DEFAULT TRUE,
  note TEXT,
  UNIQUE(username, symbol)
);

CREATE INDEX IF NOT EXISTS idx_user_daily_watchlist_user
  ON user_daily_watchlist (username, active, added_at DESC);
