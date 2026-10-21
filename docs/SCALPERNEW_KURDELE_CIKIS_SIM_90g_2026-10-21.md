# scalpernew MA kurdele kuralı — 90 günlük gerçekleşebilir net (2026-10-21 02:01)

Kural: `scalpernew/backend/app/ema_ribbon.py` (SMA 7/20/99 kesişimi, dilim şartları, sıkışıklık/durağan/ölü çubuk elekleri, StochRSI ≤ 80 M15 hariç). Evren: her 10 dk 24 sa yükselenler ilk 40 + saatlik aktivite filtresi, endeksli çiftler hariç (304 çift; saatlik ortalama aktif 10.7). Çıkış: iz süren stop tetik %2 / aralık %1, stop {'5m': 4.0, '15m': 2.0, '30m': 5.0, '1h': 4.0}, tutma {'5m': 150.0, '15m': 150.0, '30m': 270.0, '1h': 480.0} dk, komisyon 0.1125%/bacak + kayma 0.025%. Aynı mumda stop ve hedef görülürse stop (kötümser).

| Varyant | TF | Ham sinyal | Taranan anda | Kazanan | Ort. net | Medyan net | Toplam net | Çıkış nedenleri |
|---|---|---:|---:|---:|---:|---:|---:|---|
| canlı (hedefte satış kapalı) | M5 | 1018 | 329 | 56% | -0.39% | +0.81% | -129% | trailing_stop 175, max_duration 87, stop_loss 66, open 1 |
| canlı (hedefte satış kapalı) | M15 | 3042 | 876 | 47% | -0.31% | -0.60% | -268% | stop_loss 388, trailing_stop 383, max_duration 105 |
| canlı (hedefte satış kapalı) | M30 | 1479 | 114 | 55% | -0.80% | +0.76% | -91% | trailing_stop 58, max_duration 36, stop_loss 20 |
| canlı (hedefte satış kapalı) | H1 | 514 | 49 | 55% | -0.55% | +0.83% | -27% | trailing_stop 25, stop_loss 16, max_duration 8 |
| hedefte satış açık | M5 | 1018 | 329 | 56% | -0.39% | +0.81% | -129% | trailing_stop 124, max_duration 87, stop_loss 66, take_profit 51, open 1 |
| hedefte satış açık | M15 | 3042 | 876 | 47% | -0.34% | -0.60% | -294% | stop_loss 388, trailing_stop 356, max_duration 104, take_profit 28 |
| hedefte satış açık | M30 | 1479 | 114 | 55% | -0.80% | +0.76% | -91% | trailing_stop 58, max_duration 36, stop_loss 20 |
| hedefte satış açık | H1 | 514 | 49 | 55% | -0.58% | +0.83% | -29% | trailing_stop 24, stop_loss 16, max_duration 8, take_profit 1 |

## Dürüst sınırlar

- Giriş sinyal mumunun kapanışı; canlıda 180 sn tazelik penceresi ve 90 sn tarama kadansı var, burada her uygun mum sayılır.
- Paper'ın diğer giriş kapıları (LLM hakemi, MTF uyumu, sessiz saat, tekilleştirme, maks 8 pozisyon, likidite) uygulanmadı; canlıda açılan işlem daha az olur. Kâr hedefin %90'ında iz süren aralığın yarıya inmesi simüle edilmedi.
- scalpernew'in kendi backtest betiği sabit 'bugünkü ilk 40' listesi ve hedef/stop ızgarasında örneklem içi arama kullanır; oradaki artı sonuçlar bu ölçümle karşılaştırılamaz.
