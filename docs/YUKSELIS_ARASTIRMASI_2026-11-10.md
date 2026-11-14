# Yükseliş Sinyali Araştırması — Mevcut Sistemin Dışında Ne Yapılabilir?

**Tarih:** 2026-11-10
**Veri:** `scalper` DB, 411.375 `velocity_candidates`, 57,5M 1m mum, 331 sembol
**Amaç:** Mevcut stratejilerin dışında yükseliş tespiti için kullanılmamış boyutlar

---

## 0. ⚠ ÖNCE: Mevcut sistemin ana skoru ÖLÜ

Bu, tüm araştırmanın zeminini değiştiriyor:

```
velocity_score ile net_pct korelasyonu: r = 0.0002   (411.375 aday)
```

**Tam sıfır.** Skor, sonucu hiç öngörmüyor.

Göreli sıralama (aynı 30 dk penceresinde, 1.038 kova):

| sıralama ölçütü | en yüksek çeyrek | en düşük çeyrek | FARK | doğru yön |
|---|---|---|---|---|
| `velocity_score` | −0,589% | −0,371% | **−0,218%** | %38,2 |
| `atr_pct` | −0,529% | −0,421% | −0,108% | %44,0 |

`velocity_score` **TERS** çalışıyor: skoru yüksek olan daha çok kaybediyor.
Yalnız %38,2 kovada doğru yönde (rastgele %50 olurdu).

> **Sonuç:** Skoru iyileştirmek (eşik, ağırlık, kalibrasyon) boşuna. Sinyalin
> kendisi bilgi taşımıyor. Yeni bir boyut gerekiyor.

---

## 1. Mevcut strateji envanteri (kod taraması)

| Modül | Sinyal türü | Veri |
|---|---|---|
| `velocity.py` | Hız sıçraması (5/15/30/60dk) | 1m mum |
| `rising_signals.py` | KDJ dip, SuperTrend, EMA50 sekmesi | 1m/5m mum |
| `momentum_scan.py` | 1 saatlik momentum (hacim+VWAP+dip) | 15m mum |
| `early_discovery.py` | Erken keşif (miniTicker) | canlı tick |
| `snapback_service.py` | Mean-reversion dip avcısı | mum |
| `lead_lag_signal.py` | Global→TR artık gecikme | Global+TR mum |
| `microflow.py` | Emir defteri mikroyapı | depth |
| `combined_radar.py` | Yukarıdakilerin birleşimi | karışık |

**Hepsi aynı şeyi yapıyor:** tek sembolün kendi geçmişine bakıp "yükseldi mi /
yükselecek mi" diyor. Yani **time-series** (tek seri) yaklaşımı.

---

## 2. Kullanılmayan boyutlar (kod taraması — dosya sayısı)

| boyut | dosya | durum |
|---|---|---|
| `cross_sectional` (göreli güç) | **0** | ❌ HİÇ YOK |
| `correlation_matrix` | **0** | ❌ HİÇ YOK |
| `sector` / tema gruplama | **0** | ❌ HİÇ YOK |
| `relative_strength` | **0** | ❌ HİÇ YOK |
| `hour_of_day` | **0** | ❌ HİÇ YOK |
| `day_of_week` | **0** | ❌ HİÇ YOK |
| `liquidity_sweep` / `stop_hunt` | **0** | ❌ HİÇ YOK |
| `volatility_breakout` | **0** | ❌ HİÇ YOK |
| `vwap_deviation` | **0** | ❌ HİÇ YOK |
| derivatives (funding/OI) | 6 | ⚠ VAR ama sadece **filtre**, sinyal değil |

---

## 3. Araştırma: literatür ne diyor

### Cross-sectional (göreli) momentum — en umut verici

Kripto momentum literatürü (Starkiller Capital 2023; Gbadebo 2026) tutarlı
şekilde şunu söylüyor:

- **Time-series momentum** (mevcut sistemimiz) → yıllık %31,96
- **Cross-sectional momentum** (göreli sıralama) → daha düşük getiri, %55 max drawdown
- Yüksek kripto korelasyonu cross-sectional avantajı **azaltıyor**

⚠ **Uyarı:** referans uygulamalardan biri Sharpe **−0,12**, 4.860 işlem
(screamer docs). Yani bu fikir de otomatik kazanç değil.

**Neden yine de denenmeli:** bizim sorunumuz farklı. Biz "hangi coin yükselecek"
diye tek tek bakıyoruz ve skorumuz ölü (r=0,0002). Göreli güç, **aynı anda**
"bu coin diğerlerinden daha mı güçlü" sorusunu sorar — farklı bir bilgi kaynağı.

### Diğer literatür boyutları

| boyut | kanıt | bizde var mı |
|---|---|---|
| Taker buy volume / order flow | "agresif alım kalıcı bilgi taşır" | ⚠ kısmi (microflow) |
| Funding rate / perpetual-spot basis | "kalabalık pozisyon sonraki getiriyi değiştirir" | ⚠ sadece filtre |
| Volatility / liquidity / return tails | "risk primi kontratlar arası değişir" | ⚠ kısmi |
| UTC seans ayrımı | "intraday bilgi günlük kapanışta kaybolur" | ❌ yok |

---

## 4. Ölçülen boyutlar (bu oturumda test edildi)

### 4a. Saat bazlı zamanlama — ❌ ZAYIF

`velocity_candidates.net_pct`, TR saati (24 saat, her biri >15.000 aday):

| en iyi 3 saat | ort | en kötü 3 saat | ort |
|---|---|---|---|
| 05:00 | −0,317% | 19:00 | −0,624% |
| 08:00 | −0,338% | 11:00 | −0,529% |
| 09:00 | −0,344% | 03:00 | −0,528% |

**Tüm 24 saat negatif.** En iyi ile en kötü arası 0,307 puan — ama ikisi de
zarar. Zamanlama tek başına kurtarmıyor, sadece kaybı azaltıyor.

### 4b. Göreli sıralama (velocity_score) — ❌ TERS

Bkz. bölüm 0. r = 0,0002; ters yönde çalışıyor.

### 4c. ATR (volatilite) — ✅ TEK ÇALIŞAN BOYUT

Önceki ölçüm (`RADAR_BACKTEST_ANALIZI`): `atr_pct ≥ 1,0` → +0,32/−0,46 fark.
Gerçek mum replay'i (2 seed): **+0,320% / +0,314%**. Bu tek boyut.

---

## 5. Öneri — test edilmeye değer 3 hipotez

Öncelik sırası, her biri **ölçülebilir** ve **mevcut kodda olmayan**:

### H1: Göreli güç (cross-sectional rank) ⭐ en yüksek öncelik
Aynı 30 dk pencerede tüm adayları **kendi geçmiş getirisine göre** sırala
(velocity_score değil — gerçek fiyat hareketi). "En güçlü %20" gerçekten
diğerlerinden daha mı iyi?

- Ölçüm: aynı kova içinde üst/alt çeyrek net_pct farkı
- Veri: zaten var (`velocity_candidates` + `historical_candles`)
- Başarı eşiği: fark > +0,20% **ve** doğru yön > %55 kova

### H2: Göreli güç + BTC rejimi
BTC 200 periyot MA üstünde mi? Rejim, H1'in yönünü değiştiriyor mu?

- Literatür bunu vurguluyor (regime conditioning)
- Ölçüm: H1 farkını rejime göre ayır

### H3: Funding/OI aşırılığı (ters sinyal)
Aşırı pozitif funding = kalabalık long = düşüş riski. Şu an sadece "kötüyse
engelle" filtresi; **ters yönlü sinyal** olarak kullanılmıyor.

- Veri: `derivatives_service` çalışıyor
- Sınır: sadece futures'ı olan semboller

---

## 6. Sınırlar (dürüst)

- Literatürdeki cross-sectional strateji örneklerinden biri Sharpe −0,12.
  **Bu fikir kazanç garantisi değil.**
- Bizim örneklemimiz 4 ay (2026-06-27 → 2026-10-27), tek borsa (Binance TR),
  tek piyasa rejimi. `RADAR_14GUN_TEST` uyarısı geçerli: kısa pencere yanıltır.
- `velocity_candidates.net_pct` gerçekleşmiş sonuç değil, **backtest etiketi**.
  Gerçek dolum/slippage yok.
- 331 sembolün tamamı likit değil; göreli sıralama ince hacimli coinlerde
  gürültülü olabilir.

---

## 7. H1 TESTİ — SONUÇ: ❌ REDDEDİLDİ

`backend/scripts/relstrength_test.py` (120.000 aday) + `combo_atr_rel.py` (40.000)

### Tek başına göreli güç

| sinyal | TRAIN fark | TEST fark | TEST yön | eşik (+0,20 / %55) |
|---|---|---|---|---|
| **ret15** | +0,096% | **+0,144%** | **%55,9** | ❌ yakın ama geçmedi |
| ret30 | +0,121% | +0,004% | %48,4 | ❌ |
| ret60 | +0,024% | −0,073% | %48,4 | ❌ |
| ret120 | −0,046% | −0,075% | %38,7 | ❌ (ters) |
| `velocity_score` | **−0,197%** | **−0,087%** | **%38,7** | ❌ (TERS) |

`ret15` **yön olarak tutarlı** (TRAIN +0,096 → TEST +0,144, yön %55,9) ama:
- Fark eşiğin altında (+0,144 < +0,20)
- **Mutlak seviye zarar:** TEST'te en iyi çeyrek bile −0,221%

Yani ayrıştırıyor, kâr ettirmiyor.

### ATR + göreli güç birlikte — DAHA KÖTÜ

ATR ≥ 1,0 geçen adaylar arasında ret15 sıralaması:

| set | üst yarım | alt yarım | fark | yön |
|---|---|---|---|---|
| TRAIN (437 kova) | −0,487% | −0,400% | **−0,087%** | %42,2 |
| TEST (188 kova) | −0,701% | −0,330% | **−0,371%** | %35,2 |

**TERS.** ATR filtresiyle birlikte göreli güç zarar veriyor. Yön %35,2 —
yani üç kovadan ikisinden fazlasında yüksek ret15 daha kötü sonuçlanmış.

### Neden reddedildi

1. Bağımsız sinyal olarak eşiği geçmedi (+0,144 < +0,20)
2. Mutlak getiri hâlâ negatif — filtre olarak kullanılsa kâr etmez
3. ATR ile birleşince **işaret değiştiriyor** (ters çalışıyor) → etkileşim zararlı
4. ret30/60/120 hep zayıf veya ters → "göreli güç" fikri bu veride tutarlı değil

**Karar:** `ret15` göreli güç filtresi SİSTEME EKLENMEYECEK.

---

## 8. Neden `velocity_score` ölü? (teşhis)

`velocity_score` ile `atr_pct` karşılaştırması:

| sinyal | r (korelasyon) | göreli yön | mutlak ayrıştırma |
|---|---|---|---|
| `velocity_score` | **0,0002** | %38,7 (ters) | yok |
| `atr_pct` | — | %44,0 (zayıf) | **var** (≥1.0 → +0,32%) |

Skor muhtemelen **geçmiş hareketi** ölçüyor (ne kadar hızlı yükseldiyse skor o
kadar yüksek) — ki bu, kısa vadede **mean-reversion** demek. Yani yüksek skor =
"çok yükselmiş, düşecek". Ters çalışması bununla tutarlı.

`atr_pct` ise **hareket potansiyelini** ölçüyor (ne kadar oynak) — yön değil,
genlik. Genlik tahmini işe yarıyor, yön tahmini yaramıyor.

---

## 9. Sıradaki adımlar (test edilmemiş, umut verici sıralaması)

| # | hipotez | neden umut verici | sınır |
|---|---|---|---|
| 1 | **ATR eşiğini yükselt (1,5 / 2,0 / 2,5)** | Tek çalışan boyut bu; eşik optimizasyonu henüz yapılmadı | Örneklem daralır (n=26-63) |
| 2 | **ATR + zamanlama (saat filtresi)** | Saat 05-09 arası 0,3 puan daha iyi; ATR ile birleşimi test edilmedi | Saat etkisi zayıf |
| 3 | Funding/OI ters sinyal | Kalabalık pozisyon = ters risk; hiç denenmedi | Sadece futures sembolleri |
| 4 | Taker buy volume / order flow | Literatür destekli; `microflow` var ama sinyal üretmiyor | Veri saklanmıyor olabilir |
| 5 | Cross-sectional *portföy* (long-short) | Literatür; bizde long-only var | TR spot'ta short yok |

**Öncelik: 1 ve 2.** İkisi de mevcut veriyle, mevcut altyapıyla ölçülebilir.

---

## 10. ⚠ EN ÖNEMLİ BULGU: ATR filtresi ÇIKIŞ MODELİNE BAĞIMLI

`min_atr_pct = 1.0` ayarının arkasındaki ölçüm **trailing çıkışına** dayanıyor.
`velocity_candidates.net_pct` ise **sabit TP/SL** simülasyonu. İkisi **zıt** sonuç
veriyor:

| çıkış modeli | filtre yok | ATR ≥ 1,0 | ATR ≥ 2,0 | ATR ≥ 4,0 |
|---|---|---|---|---|
| **sabit TP1.5/SL5, 60 dk** (`net_pct`) | −0,465% | **−0,592%** | **−0,769%** | −0,279% |
| **trailing gap0.3, 240 dk** (gerçek mum) | +0,046% | **+0,421%** | — | — |

**Zıt yönde.** Sebep:

`net_pct` çıkış dağılımı (411.375 aday):

| çıkış | oran | ATR≥1 | ATR≥2 |
|---|---|---|---|
| SL vurdu | %39,4 | **%52,0** | **%53,6** |
| TP vurdu | %36,1 | %43,8 | %42,4 |
| Süre doldu | %24,5 | — | — |

Oynak coin, **%5'lik sabit stopu 60 dk içinde daha sık deliyor** (SL oranı
%39,4 → %53,6). Sabit modelde ATR zarar getiriyor.

Trailing modelinde tersi: oynak coin **daha çok tepe yapıyor**, trailing o
tepeden kâr ediyor. Aynı özellik (oynaklık), farklı çıkış kuralında **ters**
sonuç üretiyor.

### Sonuç ve kısıt

> **`min_atr_pct = 1.0` YALNIZCA trailing aktifken geçerli.**
> Sabit TP/SL'ye dönülürse (veya trailing kapanırsa) bu ayar **zarar verir.**

Sistemde `trailing_enabled = True`, `tp_cancel_on_trail` açık olduğu için
gerçekleşmiş işlemlerde trailing baskın (`trailing_stop` 368 işlem +1,500%;
`take_profit` 125 işlem +2,771%). Yani ayar **şu anki yapılandırmada doğru.**

**Bu bağımlılık testle kilitlenmeli:** `trailing_enabled=False` yapılırsa
`min_atr_pct` otomatik 0'a düşmeli veya uyarı vermeli. Aksi halde biri
trailing'i kapatır, ATR filtresi sessizce zarar verir.

---

## 11. Yönetici özeti

| bulgu | durum |
|---|---|
| `velocity_score` bilgi taşımıyor (r=0,0002) | ❌ ölü, ters çalışıyor |
| Göreli güç (ret15) ayrıştırıyor ama kâr ettirmiyor | ❌ reddedildi |
| Göreli güç + ATR birlikte | ❌ ters çalışıyor, zararlı |
| Saat filtresi | ❌ tüm saatler negatif, 0,3 puan fark yetersiz |
| **ATR filtresi (trailing ile)** | ✅ tek çalışan boyut: +0,32% |
| **ATR filtresi çıkış modeline bağımlı** | ⚠ KRİTİK kısıt, kilitlenmeli |

**Tek gerçek kazanç ATR'de. Yön tahmini değil, genlik tahmini.**

---

## 12. ATR eşik taraması (`scripts/atr_threshold_sweep.py`)

Gerçek 1m mum + **trailing çıkışı** (üretim modeli), `net_pct` kullanılmadı.
4 bağımsız seed (7, 11, 23, 42, 77) toplandı:

| atr eşiği | ort (seed ort.) | sd | ort n | min n | kabul |
|---|---|---|---|---|---|
| 0,0 | +0,018% | — | 1495 | — | %99,7 |
| 1,0 | **+0,364%** | 0,168 | 114 | 101 | ~%13 |
| 1,2 | +0,449% | 0,268 | 72 | 64 | ~%8 |
| **1,5** | **+0,647%** | 0,406 | 38 | 29 | ~%5 |
| 1,8 | +0,608% | 0,352 | 21 | 16 | ~%3 |
| 2,0 | +0,810% | — | ~20 | 11 | ~%2 |

### Karar: **1,0'da kalındı**

Gerekçe:
- 1,5 en yüksek ortalamayı veriyor (+0,647 vs +0,364) **ama** sd 2,4 kat büyük
  (0,406 vs 0,168) ve örneklem **3 kat küçük** (38 vs 114).
- Aynı güven düzeyi için 1,5'te **9 kat fazla işlem** gerekir.
- 1,8+ örneklem 16-21'e düşüyor — tek bir aykırı işlem ortalamayı çevirir.
- Aylık ~%5 kabul oranı, 20 sembollük evrende günde ~1 işlem demek; pratik değil.

**1,0 en iyi risk/örneklem dengesi.** 1,5 istenirse panelden ayarlanabilir
(kanıt hazır) ama varsayılan 1,0 kalmalı.

---

## 13. H3: Funding rate testi — ❌ MARJINAL, eklenmedi

`scripts/funding_signal_test.py` (40.000 eşleşen aday, TRAIN/TEST 70/30).

`futures_funding` tablosu TR sembolü + funding taşıyor (290 sembol, 519.887
velocity adayıyla kesişim). Sistemde funding şu an yalnız "kötüyse engelle"
filtresi; ters sinyal olarak hiç kullanılmıyor — ilk kez test edildi.

### Sonuç: yön DOĞRU, etki ÇOK KÜÇÜK

| funding dilimi | TRAIN ort | TEST ort | TEST kazanan |
|---|---|---|---|
| < −0,0291% | −0,282% | −0,301% | %40,7 |
| −0,0291 … +0,005% | −0,612% | −0,233% | %42,0 |
| **> +0,005%** | −0,571% | **−0,663%** | **%29,9** |

**Ters sinyal hipotezi doğrulandı:** pozitif funding (kalabalık long) en kötü
sonucu veriyor (−0,663%, kazanan yalnız %29,9). İki sette de tutarlı.

**Ama filtre olarak değeri marjinal:**

| | TEST ort | n |
|---|---|---|
| filtre yok | −0,254% | 12.000 |
| funding ≤ +0,005% | −0,233% | 11.331 |
| **kazanç** | **+0,021 puan** | %94,4 kaldı |

En iyi dilim bile **negatif** (−0,233%). Tek başına kâr ettirmiyor.

### ATR + funding birlikte — ek katkı yok

| kombinasyon | TEST n | TEST ort |
|---|---|---|
| atr≥1,0 | 1.219 | −0,442% |
| atr≥1,0 + funding≤0,005 | 1.195 | −0,455% |
| atr≥1,5 | 338 | −0,143% |
| atr≥1,5 + funding≤0,005 | 338 | −0,143% |

Funding **hiçbir şey eklemiyor**; hatta atr≥1,0'da hafif kötüleştiriyor.

> **Karar: funding filtresi SİSTEME EKLENMEYECEK.** Yön bilgisi doğru ama
> büyüklük (+0,021) gürültü seviyesinde. Karmaşıklık eklemeye değmez.

⚠ Not: bu tabloda `atr≥1,0` negatif çıkıyor (−0,442) çünkü `net_pct` = sabit
TP/SL simülasyonu kullanılıyor. §10'daki çıkış-modeli bağımlılığı burada da
geçerli: ATR'nin gerçek faydası **trailing** çıkışında görünür (§12).

---

## 14. Güncel öneri sıralaması

| # | hipotez | durum |
|---|---|---|
| 1 | ATR eşiği optimizasyonu | ✅ yapıldı — **1,0 doğru**, 1,5 panelden denenebilir |
| 2 | Funding ters sinyal | ❌ test edildi, marjinal (+0,021) |
| 3 | Saat filtresi | ❌ test edildi, zayıf |
| 4 | Göreli güç (ret15) | ❌ test edildi, reddedildi |
| 5 | **Taker buy volume / order flow** | ⬜ HENÜZ TEST EDİLMEDİ — sıradaki |
| 6 | **Cross-sectional long-short portföy** | ⬜ test edilmedi (TR spot'ta short yok) |
