# Yeni Veri Kanalı Araştırması — 2026-10-12

Devam: [BAGIMSIZ_ONNGORUCU_TARAMASI_2026-10-12.md](BAGIMSIZ_ONNGORUCU_TARAMASI_2026-10-12.md)

## Neden
Üç tur (çıkış / giriş seçici / fiyat-mum feature'ları) mevcut veriyle genellenebilir edge
bulamadı (`NO_FEATURE_EDGE`). Sonuç: **yeni veri kanalı** gerekir. İki aday belirlendi ve
gerçek aday geçmişi + gerçek mumlarla ölçüldü.

**Kritik ön koşul:** Kanal hem ERİŞİLEBİLİR hem GERİYE DÖNÜK çekilebilir olmalı — yoksa
backtest edilemez (ileriye dönük kör bahis). İki aday da bu testi geçti (180+ gün geçmiş).

## Alternatif 1 — Order-flow / CVD proxy (`taker_buy` hacmi)
Binance klines 12 alan döner; **9. alan `taker_buy_base`** = agresif ALICI hacmi.
`tbr = taker_buy / hacim` (0-1); CVD ≈ kümülatif (alıcı − satıcı). TRY native, **ek API/
anahtar yok** (`api.binance.me`). Hipotez: yükselişin öncüsü agresif alım.

## Alternatif 2 — Global→TR lead-lag
309 TRY sembolünün Binance Global USDT karşılığı var. TR piyasası daha az likit → Global'de
başlayan hareket TR'ye gecikmeli yansıyabilir. Global 5m getirisi (sinyal anında, hizalı) TR
geleceğini öngörür mü?

## Yöntem
`scripts/research_data_channels.py` — 5.909 gerçek aday (10-06→10-10), TR + Global 5m
klines (118 sembol × 2 borsa, ~25 MB önbellek), sinyal anında **yalnız kapanmış barlardan**
feature'lar, walk-forward (eğitimde eşik → sınavda EV) + eşleştirilmiş t-testi + 3-fold +
leave-one-symbol-out. Look-ahead kilidi: `tests/test_research_data_channels.py`.

## Bulgular (tam örneklem, baz SINAV EV −0.358%)

### Kanal 1 — Order-flow
| Feature | EV/işlem | t |
|---|---|---|
| tbr düşük (kontraryan: satıcı baskın) | −0.170% | **+3.55** |
| cvd_norm düşük | −0.203% | +3.30 |
| div yüksek (fiyat↑ akış↓ diverjans) | −0.231% | +2.94 |

### Kanal 2 — Global lead-lag
| Feature | EV/işlem | t |
|---|---|---|
| g_ret1 yüksek (Global momentum) | −0.178% | **+3.85** |
| ret1 yüksek (TR momentum, kontrol) | −0.155% | +4.26 |
| g_tbr düşük | −0.522% | −4.11 |

**Sonuç:** Her iki kanal da **istatistiksel olarak anlamlı ayrıştırıcı** (t≈3.5–3.9) ama
**hiçbiri EV'yi pozitife çevirmiyor** (en iyi −0.155%, baz −0.358%).

## Titiz doğrulama (aşırı-uydurma koruması)
- **Kombinasyon** (`tbr düşük & g_ret1 yüksek`): EV −0.411, t=−0.29 → sinyaller örtüşünce
  avantaj kayboluyor.
- **3-fold:** fold1 −0.73, fold2 −0.19, fold3 −0.67 → **kararsız**, işaret değiştiriyor.
- **Sembol yoğunlaşması:** makul (en büyük pay %16–20, 45–51 sembol). Tek sembol çıkarınca
  EV −0.178→−0.067 (g_ret1) / −0.170→−0.126 (tbr) — yani edge tek coin'e bağlı DEĞİL, ama
  yine negatif.

## KARAR
**NO_CHANNEL_EDGE** — iki yeni kanal da gerçek ama ZAYIF ayrıştırıcı sinyal taşıyor; portföyü
pozitife çevirmiyor, yalnız kaybı ~0.18–0.20 puan azaltıyor. Kombinasyon ve fold testlerinde
kararsız. **Uygulanacak bir giriş kuralı yok.**

Kod tabanı bunu bağımsız olarak doğruluyor: `config.py:381` — "CVD işareti dokunuşu anlamlı
ayırmıyor (negatif %14.4 vs pozitif %15.0) → nötr; çarpan sabiti kaldırıldı."

## Değerlendirme (dört turun toplamı)
| Katman | Sonuç | Durum |
|---|---|---|
| Çıkış geometrisi (SL 3.0→1.0) | Kaybı ~%50 azalttı | ✅ UYGULANDI (6bc2ee6) |
| Giriş seçici (skor/rank/ATR/ML) | Edge yok, skor tersine | NO_ENTRY_EDGE (3128cec) |
| Fiyat-mum feature'ları | Edge yok | NO_FEATURE_EDGE (53b4f5b) |
| Order-flow / lead-lag kanalları | Zayıf, pozitife dönmüyor | NO_CHANNEL_EDGE (bu tur) |

**Net sonuç:** Ölçülebilir tüm veri kanalları denendi. Motorun ürettiği sinyaller, mevcut
veriyle (fiyat + hacim + taker-buy + Global lead-lag, 5 dk ufuk) **sistemik olarak negatif
beklentili**. Pozitife dönüş için gereken, bu sinyalin KENDİSİNİN yeniden tasarlanması —
örneğin (a) farklı ufuk/rejim (günlük yerine saatlik, trend vs range), (b) sinyal üretim
eşiğinin veri-güdümlü kalibrasyonu, (c) tamamen farklı bir hipotez (mean-reversion, funding
taşıma, sepet-arbitraj). Bu, ayrı bir ürün kararıdır.

## Yeniden üretim
```
python backend/scripts/research_data_channels.py --hours 340 --fetch   # önbellek bir kez
python backend/scripts/research_data_channels.py --hours 340           # önbellekten hızlı
```
Rapor: `work/data_channel_research.json`, önbellek: `work/channel_cache.json` (gitignore).
