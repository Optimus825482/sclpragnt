-- 017 — BINANCE TR KULLANICI İŞLEMİ (2026-10-16)
-- user_risk_settings: Risk Merkezi (tek emirde serbest TRY bakiyesinin en fazla %'si, standart RR).
-- order_requests: client_order_id ile İDEMPOTENT emir kaydı. (user_id, client_order_id) birincil anahtar;
--   INSERT ... ON CONFLICT DO NOTHING ile aynı id'li ikinci istek gerçek emir üretmez (yeniden başlatma/çok işçi güvenli).
-- Idempotent: CREATE TABLE IF NOT EXISTS. Hassas veri yok (anahtar/secret tutulmaz).
CREATE TABLE IF NOT EXISTS user_risk_settings (
  user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  max_position_pct DOUBLE PRECISION NOT NULL DEFAULT 20,
  default_rr DOUBLE PRECISION NOT NULL DEFAULT 2,
  updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS order_requests (
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  client_order_id TEXT NOT NULL,
  status TEXT NOT NULL,
  symbol TEXT,
  request JSONB,
  result JSONB,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (user_id, client_order_id)
);
CREATE INDEX IF NOT EXISTS idx_order_requests_created ON order_requests(created_at);
