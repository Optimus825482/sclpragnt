# TV Mekanizmaları — Aksak Noktaları Kapatıp YENİDEN (17b–e) (2026-10-13)

**ARAŞTIRMA — commit YOK.** Eleştiri haklıydı: 17. turdaki harness aksıyordu. Bu turda
5 aksak noktayı tek tek kapattım ve yeniden test ettim. Sonuç: **edge yine yok — ama artık
bunu sağlam testlerle söylüyorum (kestirme değil).**

## Kapatılan 5 aksak nokta
| # | 17. tur aksaklığı | 17b–e düzeltmesi |
|---|---|---|
| 1 | Sabit 12-bar tut → kazananı koşturamıyor | Bar-içi çıkış simülatörü (trailing / SL-TP / ters-sinyal / max-hold) |
| 2 | Stop/hedef yok → düşük win, asimetri yok | ATR tabanlı SL/TP/trailing |
| 3 | MTF trend filtresi yok | HTF EMA50 trend onayı (yalnız kapanmış HTF barı) |
| 4 | Haksız benchmark (buy&hold ham EV) | (a) **aynı çıkış kurallı rastgele giriş**, (b) **maruziyet düzeltmesi** (return/bar-in-market) |
| 5 | Tek parametre (curve-fit riski) | trail × max_hold **plato yüzeyi** + sınır-monotonluk testi |

Scriptler: `research_tv_exits.py` (17b), `research_tv_exits2.py` (17c), `research_tv_exposure.py`
(17d), `research_tv_m3.py` (17e). Look-ahead yok: karar bar kapanışı → giriş **ertesi açılış**;
stop/hedef bar high/low ile; aynı barda SL+TP mümkünse **SL varsayılır** (kötümser).

## Bulgu 1 — Çıkış kuralları trend mekanizmalarını KURTARMADI
4h, long/short net EV (orta kolonlar), 17. tur sabit-tut'a karşı:
- `atrtrail` (kazananı koştur) ve `combo` (trailing+ters sinyal) **daha kötüleştirdi** (whipsaw):
  M3 SuperTrend hold12 +0.82 → atrtrail −0.50.
- `sl_tp` (asimetrik R/R) da çoğunda negatif.
- Yani "doğru çıkış mantığı eksikti" hipotezi **çürüdü**.

## Bulgu 2 — Adil kontrol: giriş zamanlamasında alfa YOK
Long-only, gross (maliyetsiz), gerçek vs **aynı çıkış kurallı rastgele giriş**:

| tf | mek | gerçek vs rastgele (gross EV) |
|---|---|---|
| 4h | M1…M6 | fark −0.20 / −0.15 / −0.10 / −0.14 / −1.01 / **+0.21** |
| 1h | M1…M6 | −0.11 / **−0.33** / +0.01 / −0.20 / +0.08 / −0.24 |

Farklar ~0 ve çoğu negatif → mekanizmaların girişleri rastgele girişten ayrışmıyor.

## Bulgu 3 — Maruziyet düzeltmesi: en adil ölçü, hâlâ buy&hold'un altında
"Maruz kalırken bar başına getiri" (aynı getiri, daha az risk/sermaye):

| tf | b&h (bar/get) | En iyi mekanizma | b&h'yi geçen? |
|---|---|---|---|
| 4h | 0.0811 | M6 0.0682 | **hiçbiri** |
| 1h | 0.0362 | **M3 0.0407** | yalnız M3 (sınırda) |
| 15m | 0.0089 | M5 0.0250 | M5, M1 |

M3 SuperTrend 1h tek "geçen" aday oldu → odaklı doğrulamaya soktum (aşağıda).

## Bulgu 4 — Tek aday (M3 SuperTrend) 4 testte de düştü
`research_tv_m3.py`:

| Test | 1h | 4h | Yorum |
|---|---|---|---|
| **Anlamlılık** (gerçek−rastgele, 300×) | t = **−0.31**, 121/300 | t = **−0.28**, 123/300 | **ANLAMSIZ** — rastgeleden farksız |
| **Plato şekli** | 4/4 adım sınıra monoton | 4/4 sınıra monoton | **BETA İŞARETİ**: stop gevşedikçe buy&hold'a yakınsıyor (iç optimum = gerçek sinyal, sınır = beta) |
| **Maliyet sonrası** maruz-bar | 0.0409 − 0.0434 = **−0.0025 NEGATİF** | +0.0113 | 1h'de maliyet öldürüyor |
| **Sembol dağılımı** | 48/80 poz. ama top-3 = %50 | 16/34 poz., **top-3 = %97.6** | 4h aşırı kırılgan (tek sembol BANKTRY) |

M3'ün görünen "üstünlüğü": (i) rastgeleden farksız (t≈−0.3), (ii) parametre uzayında iç
optimum değil sınır-monoton (yani tam da stop'u kaldırdıkça buy&hold'a yakınsayan **beta
profili**), (iii) 1h'de maliyet sonrası negatif, (iv) 4h'de tek sembole bağlı.

## KARAR
**TV mekanizmaları → üretime ALINMAZ — aksak noktalar kapatıldıktan sonra da edge yok.**
Eleştiri haklıydı (ilk harness aksıyordu) ama aksaklıklar giderildiğinde sonuç değişmedi:
- Doğru çıkış mantığı → mekanizmalar daha da kötüleşti (whipsaw).
- Adil kontrolde giriş zamanlaması rastgeleden ayrışmıyor.
- Maruziyet düzeltmesinde hiçbiri buy&hold'u geçmiyor; tek sınır-üstü "aday" (M3 1h)
  anlamlılık/plato/maliyet/dağılım testlerinde beta+tek-sembol+gürültü çıktı.

Bu, 14/16/17. turların bulgusunu **daha sağlam kanıtla** doğrular. Üretim edge'i taşıyan
tek istisna hâlâ **USD residual lead-lag**.

## Yeniden üretim
```
python backend/scripts/research_tv_exits.py    --tf 4h     # 17b çıkış modları
python backend/scripts/research_tv_exits2.py   --tf 4h     # 17c long-only adil + plato + maliyet
python backend/scripts/research_tv_exposure.py --tf 1h     # 17d maruziyet + rastgele kontrol
python backend/scripts/research_tv_m3.py       --tf 1h     # 17e M3 odaklı doğrulama
```
