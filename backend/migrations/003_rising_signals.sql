-- 003 — Yükseliş sinyalleri kanıt tablosu (R2, 2026-09-14)
--
-- NEDEN AYRI TABLO: yükseliş sinyalleri MACD MONITOR'ün kanıtlanmış öncülerinden
-- (dip + 20-bar zirveye yakınlık) türetilir. Bunları `velocity_candidates` /
-- `monitoring_notifications` akışına karıştırmak `get_velocity_calibration_stats`
-- ve `live_hit_pct` (eşik besleyicisi) istatistiklerini kirletirdi.
--
-- İsabet ölçümü bu tablodan yapılır; Raporlar > "YÜKSELİŞ EĞİLİMİ" sekmesi
-- (GET /api/reports/rising-signals) burayı okur.
--
-- `kind`: 'erken'   → dip-turn + yakınlık (kırılım ÖNCESİ; 1.47-1.67x lift reçetesi)
--         'yukselis'→ güç ≥ eşik VE yeşil TF ≥ eşik (panel sınıfı)

CREATE TABLE IF NOT EXISTS rising_alerts (
  id BIGSERIAL PRIMARY KEY,
  created_at DOUBLE PRECISION NOT NULL,
  symbol TEXT NOT NULL,
  kind TEXT NOT NULL,
  score DOUBLE PRECISION,
  early_score INTEGER,
  strength DOUBLE PRECISION,
  green INTEGER,
  proximity DOUBLE PRECISION,
  gap_atr DOUBLE PRECISION,
  signals JSONB,
  price DOUBLE PRECISION,
  expected_price DOUBLE PRECISION,
  target_pct DOUBLE PRECISION,
  tf TEXT,
  source TEXT,
  notified BOOLEAN NOT NULL DEFAULT FALSE,
  sent_via_push BOOLEAN NOT NULL DEFAULT FALSE,
  auto_paper_trade_id INTEGER,
  outcome_state TEXT NOT NULL DEFAULT 'pending',
  mfe_pct DOUBLE PRECISION,
  mae_pct DOUBLE PRECISION,
  peak_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS rising_alerts_created_idx ON rising_alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS rising_alerts_symbol_idx ON rising_alerts(symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS rising_alerts_kind_idx ON rising_alerts(kind, created_at DESC);
CREATE INDEX IF NOT EXISTS rising_alerts_pending_idx ON rising_alerts(outcome_state) WHERE outcome_state = 'pending';
