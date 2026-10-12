# Rejim-Güdümlü Yüksek-TF Sinyal Araştırması — 2026-10-12

Devam: [VERI_KANALI_ARASTIRMASI_2026-10-12.md](VERI_KANALI_ARASTIRMASI_2026-10-12.md)

## Hipotez (kullanıcı kararı)
Dört tur negatif sonuç sonrası tamamen farklı hipotez: **(a) ufku 5 dk yerine 1 SAAT'e çıkar,
(b) TREND/ARALIK rejimine göre AYRI sinyal kullan.** Klasik görüş: trendde kırılım-devam,
aralıkta ortalamaya-dönüş kârlıdır; tek tip sinyal ikisini de yapmaya çalışınca ikisinde de
kaybeder. Bu, "rejim koşullaması edge yaratır mı?" sorusunun doğrudan testidir.

## Yöntem
`scripts/research_regime_signals.py`
- **Veri:** 59 likit TRY sembolü × 250 gün **1 saat** klines (TR native `api.binance.me`).
- **Rejim:** kanonik Wilder ADX(14) + Choppiness(14) + EMA50/EMA200 (1h).
  TREND = ADX≥25 & Choppiness<38; ARALIK = ADX<20.
- **Sinyaller:** trend_kırılım (24 bar zirve aşımı), trend_dip (EMA20 dokunuşu),
  aralık_dip (24 bar alt %20 bandı = ortalamaya dönüş), aralık_kırılım.
- **Çıkış:** ATR(14) tabanlı SL/TP + maks tutma; **komisyon+kayma düşülmüş** (net).
  Bar-içi belirsizlikte kötümser (aynı barda SL ve TP → SL önce).
- **Ölçüm:** 33.354 sinyal, walk-forward (ilk %60 / son %40) + 3-fold + sembol yoğunlaşma
  + parametre taraması (48 kombinasyon). Look-ahead kilidi: `tests/test_research_regime_signals.py`.

## Bulgular — rejim ayrımı GERÇEK ama edge'e dönmüyor
33.354 sinyalin sınav kümesindeki EV'si (baz −0.323%):

| Sinyal | Rejim | n | EV/işlem | Kazanma | t |
|---|---|---|---|---|---|
| trend_kırılım | TREND | 997 | −0.350% | 34.3% | −0.28 |
| trend_dip | TREND | 824 | **−1.085%** | 28.9% | **−7.01** |
| aralık_dip | RANGE | 10.202 | **−0.270%** | 36.7% | **+3.43** |
| aralık_kırılım | RANGE | 1.345 | −0.245% | 33.9% | +0.94 |

**Rejim koşullaması işe yarıyor:** aynı aile sinyaller rejime göre keskin ayrışıyor —
aralık_dip (RANGE) bazdan **+0.053 puan iyi ve anlamlı** (t=+3.43), trend_dip (TREND) bazdan
**çok daha kötü** (−1.085%, t=−7.01). Yani "trendde kırılım-devam, aralıkta ortalamaya-dönüş"
yönü DOĞRU, fark gerçek ve istatistiksel olarak anlamlı.

**Ama hiçbiri pozitife dönmüyor:** en iyi hücre aralık_dip hâlâ −0.270%. 48 parametre
kombinasyonunun **hiçbiri** pozitif değil (en iyi −0.202%, sl1.5/tp6.0/mh48).

## Sağlamlık (aşırı-uydurma değil — bu sefer gerçek sinyal)
- **3-fold:** −0.232 / −0.279 / −0.302 → **kararlı** negatif (işaret değişmiyor, önceki
  turların aksine tutarlı — yani bu bir gürültü değil, sistematik negatif beklenti).
- **Sembol yoğunlaşması:** mükemmel dağılım — en büyük pay **%2.4** (önceki turlarda %20–24
  idi). Tek/beş sembol çıkarınca EV değişmiyor (−0.267→−0.236). Yani sonuç evrensel.
- **Maliyet sonrası ölçüm:** brüt pozitif görünen hiçbir hücre yok; komisyon+kayma dahil.

## KARAR
**NO_REGIME_EDGE** — Rejim koşullaması sinyalleri gerçekten ayrıştırıyor (hipotez yönü doğru,
t=3.43) ama **hiçbir rejim×sinyal kombinasyonu pozitif EV üretmiyor** ve 1h ufku bunu
değiştirmiyor. Uygulanacak giriş kuralı yok.

## Beş turun özeti
| Katman | Ufuk | Sonuç |
|---|---|---|
| Çıkış geometrisi (SL 3.0→1.0) | 5 dk | Kaybı ~%50 azalttı ✅ UYGULANDI |
| Giriş seçici | 5 dk | `NO_ENTRY_EDGE` |
| Fiyat-mum feature'ları | 5 dk | `NO_FEATURE_EDGE` |
| Order-flow / lead-lag | 5 dk | `NO_CHANNEL_EDGE` |
| **Rejim-güdümlü sinyal** | **1 saat** | `NO_REGIME_EDGE` (hipotez yönü doğru, EV negatif) |

**Net sonuç:** Rejim koşullaması ve ufuk değişikliği, sinyalin ayrışma gücünü artırıyor ama
**sistemik negatif beklentiyi pozitife çevirmiyor.** Ölçülebilir hipotez uzayının (5dk/1h,
tek/çok faktör, fiyat/hacim/order-flow/lead-lag/rejim) tamamı tükendi. Motorun sinyalleri
komisyon sonrası yapısal olarak kayıp üretiyor.

**Pozitife dönüş için gereken:** Maliyet yapısını değiştiren bir yeniden tasarım —
maker/limit emir ile komisyonu ~%0'a çekip backtest'i bununla tekrarlamak (mevcut tüm
hesaplar ~%0.3 round-trip taker maliyeti içeriyor ve sinyaller bu eşiğin çok altında).
Bu, hem ölçüm hem ürün tarafında köklü bir değişikliktir.

## Yeniden üretim
```
python backend/scripts/research_regime_signals.py --days 250 --top 60 --fetch
python backend/scripts/research_regime_signals.py --days 250 --top 60   # önbellekten
```
Rapor: `work/rss_full.json`, önbellek: `work/regime_cache.json` (gitignore).
