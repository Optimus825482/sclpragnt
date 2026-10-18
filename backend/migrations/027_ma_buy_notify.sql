-- 027: MA ŞERİT BUY SİNYALİ → PUSH + OTONOM PAPER (2026-10-18).
-- M1/M5 MA kesişim BUY sinyali artık kullanıcıya push edilir ve otonom paper denenir (app/ma_buy_notify.py).
-- `notified_at` atomik "bildirildi" işaretidir: aynı sinyal mumu (yeniden başlatma dahil) en fazla BİR kez push edilir.
-- Yalnız ekleme (expand); idempotent.
ALTER TABLE ma_buy_signals ADD COLUMN IF NOT EXISTS notified_at DOUBLE PRECISION;
ALTER TABLE ma_buy_signals ADD COLUMN IF NOT EXISTS push_ok BOOLEAN;
ALTER TABLE ma_buy_signals ADD COLUMN IF NOT EXISTS paper_status TEXT;
ALTER TABLE ma_buy_signals ADD COLUMN IF NOT EXISTS paper_trade_id BIGINT;
