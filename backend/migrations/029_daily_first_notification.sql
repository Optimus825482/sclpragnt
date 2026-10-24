-- 029: GÜNÜN İLK BİLDİRİMİ İZLEYİCİSİ (2026-10-25).
-- Her sembol için Europe/Istanbul takvim gününün İLK (push denenmiş) bildirimi kaydedilir
-- (app/daily_first_notification.py yazar; Raporlar > "Günün ilk bildirimi" sekmesi okur).
-- İlk bildirim anından gün sonuna (23:59:59) kadar 1 dk mumlarla izlenir:
--   mfe_pct = ilk fiyattan en yüksek `high`'a yükseliş (%, >= 0), mfe_ts = o mumun açılış anı;
--   mae_pct = ilk fiyattan en düşük `low`'a düşüş (%, <= 0, NEGATİF saklanır), mae_ts = o mumun açılış anı.
-- Sembol `push_daily_counter.normalize_symbol` kuralıyla normalize edilir (BTC_TRY → BTCTRY).
-- `first_price` boş kalabilir (bildirimde fiyat yoksa ilk mumun açılışından doldurulur).
-- Yalnız ekleme (expand); idempotent.
CREATE TABLE IF NOT EXISTS daily_first_notification (
  id BIGSERIAL PRIMARY KEY,
  symbol TEXT NOT NULL,
  day_key TEXT NOT NULL,
  first_notification_id BIGINT,
  first_ts DOUBLE PRECISION NOT NULL,
  first_price DOUBLE PRECISION,
  mfe_pct DOUBLE PRECISION,
  mfe_ts DOUBLE PRECISION,
  mae_pct DOUBLE PRECISION,
  mae_ts DOUBLE PRECISION,
  last_tracked_ts DOUBLE PRECISION,
  finalized BOOLEAN NOT NULL DEFAULT FALSE,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL,
  UNIQUE (symbol, day_key)
);
CREATE INDEX IF NOT EXISTS idx_daily_first_notification_day ON daily_first_notification (day_key);
CREATE INDEX IF NOT EXISTS idx_daily_first_notification_open ON daily_first_notification (finalized) WHERE NOT finalized;
