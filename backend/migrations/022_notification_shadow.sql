-- 022: GÖLGE BİLDİRİM KAYDI (2026-10-17).
-- Canlı karardan bağımsız olarak "gölge" kurala (ilk kural: ≥2 kaynak ∧ mod = trend_devam) uyan her
-- bildirim adayı, canlı politikanın kararıyla birlikte yazılır (live_blocked_reason: '' = canlıda gitti).
-- 2–3 hafta sonra sonuçları mum verisiyle ölçülür (docs/TEYIT_UNSURLARI_ANALIZI_2026-10-17.md).
-- Idempotent.
CREATE TABLE IF NOT EXISTS notification_shadow (
  id BIGSERIAL PRIMARY KEY,
  detected_at DOUBLE PRECISION NOT NULL,
  symbol TEXT NOT NULL,
  price DOUBLE PRECISION,
  target_pct DOUBLE PRECISION,
  expected_price DOUBLE PRECISION,
  horizon_minutes INTEGER,
  mode TEXT,
  sources TEXT,
  score DOUBLE PRECISION,
  live_blocked_reason TEXT NOT NULL DEFAULT '',
  shadow_rule TEXT NOT NULL,
  created_at DOUBLE PRECISION NOT NULL,
  UNIQUE (symbol, detected_at, shadow_rule)
);
CREATE INDEX IF NOT EXISTS notification_shadow_time_idx ON notification_shadow (detected_at);
