-- 032: İşlem kalitesi ölçümleri + OI girişi.
--
-- NEDEN (2026-11-25, Sinyal İzleme kanıtı):
--   * stop_loss çıkışları ortalama -4,22% ile kapanıyor; SL/TP oranı 0,64 iken
--     stop ~1,7% olmalı. Fark "stop aşımı" mı yoksa "stop çok dar" mı — MAE
--     (max adverse excursion) olmadan ayırt edilemiyor.
--   * `min_oi_change_pct` kanıtta EN GÜÇLÜ filtre (ATR'nin 2,5 katı) ama
--     girişteki OI değişimi DB'ye yazılmadığı için sayaçlar "ölçülemiyor".

ALTER TABLE auto_paper_trades
  ADD COLUMN IF NOT EXISTS max_adverse_pct DOUBLE PRECISION;

ALTER TABLE auto_paper_trades
  ADD COLUMN IF NOT EXISTS max_favorable_pct DOUBLE PRECISION;

ALTER TABLE auto_paper_trades
  ADD COLUMN IF NOT EXISTS oi_change_pct DOUBLE PRECISION;
