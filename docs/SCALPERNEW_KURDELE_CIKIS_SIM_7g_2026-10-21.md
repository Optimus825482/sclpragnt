# scalpernew MA kurdele kuralı — 7 günlük gerçekleşebilir net (2026-10-21 01:26)

Kural: `scalpernew/backend/app/ema_ribbon.py` (SMA 7/20/99 kesişimi, dilim şartları, sıkışıklık/durağan/ölü çubuk elekleri, StochRSI ≤ 80 M15 hariç). Evren: her 10 dk 24 sa yükselenler ilk 40 + saatlik aktivite filtresi, endeksli çiftler hariç (304 çift; saatlik ortalama aktif 8.2). Çıkış: iz süren stop tetik %2 / aralık %1, stop {'5m': 4.0, '15m': 2.0, '30m': 5.0, '1h': 4.0}, tutma {'5m': 150.0, '15m': 150.0, '30m': 270.0, '1h': 480.0} dk, komisyon 0.1125%/bacak + kayma 0.025%. Aynı mumda stop ve hedef görülürse stop (kötümser).

| Varyant | TF | Ham sinyal | Taranan anda | Kazanan | Ort. net | Medyan net | Toplam net | Çıkış nedenleri |
|---|---|---:|---:|---:|---:|---:|---:|---|
| canlı (hedefte satış kapalı) | M5 | 44 | 17 | 41% | -0.65% | -0.29% | -11% | trailing_stop 8, max_duration 5, stop_loss 3, open 1 |
| canlı (hedefte satış kapalı) | M15 | 155 | 50 | 42% | -0.52% | -1.67% | -26% | stop_loss 24, trailing_stop 18, max_duration 8 |
| canlı (hedefte satış kapalı) | M30 | 45 | 6 | 0% | -4.01% | -4.61% | -24% | max_duration 3, stop_loss 3 |
| canlı (hedefte satış kapalı) | H1 | 22 | 5 | 60% | +0.04% | +1.13% | +0% | max_duration 2, trailing_stop 2, stop_loss 1 |
| hedefte satış açık | M5 | 44 | 17 | 41% | -0.62% | -0.29% | -10% | max_duration 5, trailing_stop 5, take_profit 3, stop_loss 3, open 1 |
| hedefte satış açık | M15 | 155 | 50 | 42% | -0.52% | -1.67% | -26% | stop_loss 24, trailing_stop 18, max_duration 8 |
| hedefte satış açık | M30 | 45 | 6 | 0% | -4.01% | -4.61% | -24% | max_duration 3, stop_loss 3 |
| hedefte satış açık | H1 | 22 | 5 | 60% | +0.04% | +1.13% | +0% | max_duration 2, trailing_stop 2, stop_loss 1 |

## Dürüst sınırlar

- Giriş sinyal mumunun kapanışı; canlıda 180 sn tazelik penceresi ve 90 sn tarama kadansı var, burada her uygun mum sayılır.
- Paper'ın diğer giriş kapıları (LLM hakemi, MTF uyumu, sessiz saat, tekilleştirme, maks 8 pozisyon, likidite) uygulanmadı; canlıda açılan işlem daha az olur. Kâr hedefin %90'ında iz süren aralığın yarıya inmesi simüle edilmedi.
- scalpernew'in kendi backtest betiği sabit 'bugünkü ilk 40' listesi ve hedef/stop ızgarasında örneklem içi arama kullanır; oradaki artı sonuçlar bu ölçümle karşılaştırılamaz.
