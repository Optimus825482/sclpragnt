-- 025: BİLDİRİMDE DÜRÜST SAYILAR (2026-10-18).
-- `hit_prob_calibrated`  : kalibre "tahmini isabet" (0–1) = σ(1,106 − 0,675·ln ATR% − 1,402·ln(hedef/ATR) + 0,059·[ufuk≥15]);
--                          kaynak docs/SKOR_DENETIMI_2026-10-18.md §6.1, hesap app/notify_metrics.py. NULL = model kapalı / eski satır.
-- `breakeven_hit_prob`   : başabaş isabet (0–1) = kayıp / (kazanç + kayıp); kazanç = hedef − TP maliyeti, kayıp = SL + stop maliyeti.
-- `ml_hit_probability` AYNEN kalır (ölçüm); ham ML % artık yalnız ölçüm içindir, kullanıcıya gösterilmez.
-- Idempotent; yalnız kolon ekler (expand).
ALTER TABLE monitoring_notifications ADD COLUMN IF NOT EXISTS hit_prob_calibrated DOUBLE PRECISION;
ALTER TABLE monitoring_notifications ADD COLUMN IF NOT EXISTS breakeven_hit_prob DOUBLE PRECISION;
