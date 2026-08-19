# LLM Forecast Journal

Grafik içindeki `NE OLABİLİR?` düğmesi, işlem emri üretmeyen ve yalnızca public market verisine dayanan kısa bir senaryo tahmini oluşturur.

## Girdi ve çıktı

- Girdi: M1, M5, M15, M30, H1, H4, D1 teknik snapshot'ları; yakın OHLCV fiyat davranışı; aktifse daha önce doğrulanmış forecast dersleri.
- Çıktı: 5 dakika, 15 dakika, 1 saat ve 4 saat için `up`, `down` veya `range`; güven; bozulma seviyesi; ana ve karşı senaryo.
- Her çağrıda tam bağlamın hash'i ve LLM model/prompt sürümü `llm_forecasts` tablosuna yazılır.

## Outcome ölçümü

Arka plan worker'ı yalnız kapanmış 1 dakikalık mum kullanır. Her ufuk tamamlandığında sonuç fiyatı, maksimum olumlu/olumsuz hareket, yön doğruluğu ve bozulma seviyesi kaydedilir. Bir yön hareketi, snapshot ATR'sinden türetilen ve minimum `%0.15` olan eşik üstündeyse `up`/`down`; değilse `range` kabul edilir.

## Öğrenme sınırı

`llm_forecast_lessons` tablosundaki dersler LLM tarafından değil, ölçülmüş outcome'lardan türetilir. Bir dersin aktif olması için en az 12 örnek, kronolojik holdout'ta en az 3 örnek, en az `%55` holdout doğruluğu ve eğitim/holdout doğruluğu arasında en fazla 20 puan fark gerekir. Dersler sadece LLM yorumuna bağlam sağlar; strateji parametresini, risk filtresini veya paper işlemi değiştirmez.

## API

- `POST /api/symbol-analysis/{symbol}/llm/commentary`: Journaled tahmin üretir ve kaydeder.
- `GET /api/symbol-analysis/{symbol}/forecasts`: Tahmin günlüğünü, ölçülen doğruluğu ve evaluator durumunu verir.
