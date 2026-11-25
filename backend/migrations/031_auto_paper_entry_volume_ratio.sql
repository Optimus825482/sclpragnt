-- 031: Otonom paper işlemlerine GİRİŞ HACİM ORANI.
--
-- NEDEN: kalibrasyon kovaları (strateji × saat × hacim bandı) geçmiş işlemlerden
-- öğreniyor; ancak `auto_paper_trades` giriş hacim oranını SAKLAMIYORDU. Bu
-- yüzden tarih kovalarının tamamı "unknown" bandına düşüyor, canlı giriş ise
-- gerçek hacim bandıyla geldiğinde tam eşleşme bulunamıyordu.
--
-- Değer, canlı giriş yolunun kullandığı AYNI tanımdır
-- (`analyzer._entry_volume_ratio`: 5m son hacim / önceki 20 mumun ortalaması).
-- Kolon NULL kalabilir (sembol yeni/veri yok) — bu durumda kova yine "unknown".

ALTER TABLE auto_paper_trades
  ADD COLUMN IF NOT EXISTS entry_volume_ratio DOUBLE PRECISION;
