-- 2026-11-28: Bildirim sonrası TEPE takibi.
--
-- Neden: Monitor satırı "bildirimden sonra en fazla ne kadar çıktı" bilgisini
-- tutmuyordu; kullanıcı ancak satır kapandığında görebiliyordu. Ayrıca tepe
-- oluşurken (dönüş beklemeden) bilgilendirme yapılamıyordu.
--
-- peak_price / peak_pct : watch (bildirim) anından itibaren görülen en yüksek fiyat
-- peak_at              : tepenin görüldüğü epoch saniye
-- peak_notified_pct    : en son bildirilen eşik (3/5/8/12/20) — spam koruması
ALTER TABLE large_move_early_watch
  ADD COLUMN IF NOT EXISTS peak_price DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS peak_pct DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS peak_at DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS peak_notified_pct DOUBLE PRECISION;
