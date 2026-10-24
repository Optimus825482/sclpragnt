-- 028: SEMBOL BAŞINA GÜNLÜK PUSH SAYACI (2026-10-24).
-- Her web push bildirimi, ilgili coin için "bugün kaçıncı bildirim" sayacını taşır (app/push_daily_counter.py).
-- Sayaç sembol + Europe/Istanbul takvim günü başına tutulur; zaman dilimi / tarama türü / kaynak AYRIMI YOKTUR.
-- Kalıcı tablo: süreç yeniden başlasa da gün içi sayım sıfırlanmaz. Yalnız ekleme (expand); idempotent.
CREATE TABLE IF NOT EXISTS push_daily_counter (
  symbol TEXT NOT NULL,
  day_key TEXT NOT NULL,
  count INTEGER NOT NULL DEFAULT 0,
  updated_at DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (symbol, day_key)
);
