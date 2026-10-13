# Uzun Ufuk (1h/4h/1d) Strateji Taraması + 1d Momentum Doğrulama (2026-10-13)

**ARAŞTIRMA — commit YOK (kullanıcı isteği).** Seçenek (b): uzun ufukla maliyet amortizasyonu.

## Mantık
13 turda tüm bilgi sınıflarının brüt edge'i (~%0.05-0.2) 5dk-1saat ufkunda maliyetin
(%0.35 round-trip) altında kaldı. Uzun ufukta işlem SEYREKLEŞİR → maliyet yıllık amortize olur:
| Frekans | Yıllık maliyet drag |
|---|---|
| günde 1 işlem | %128 |
| haftada 1 | %18.2 |
| ayda 1 | %4.2 |

Yani uzun ufukta gereken edge eşiği ÇOK daha düşük.

## Tarama (1h/4h: 5 strateji ailesi)
1h ve 4h'de sistematik stratejiler (momentum, kırılım, ortalamaya-dönüş, EMA kesişim, RSI):
**hepsi EV negatif**, işlem frekansı yine yüksek (sembol başı ~2/gün). Maliyet amortizasyonu
çalışmadı çünkü sinyaller sık.

## 1d'de İLK GÖRÜNÜŞTE POZİTİF — ama doğrulama ÇÖKTÜ
`S1_mom12` (12 günlük momentum), 1d, hold=6: EV **+2.829%**, kazanma %57.4. 13 turda
ilk pozitif sinyal → acımasız doğrulama (`verify_1d_momentum.py`):

| Test | Sonuç | Yorum |
|---|---|---|
| TÜM EV (doğrulama seti) | **−0.175%** | dedup/filtre farkıyla pozitif kayboldu |
| **3-fold** | −2.81 / −1.41 / **+3.69** | **KARARSIZ** — yalnız son fold pozitif |
| Gün-gün | 33/72 | ~yazı-tura |
| Sembol yoğunlaşması | en büyük %2.4 | iyi dağılmış |
| **LONG / SHORT** | **+3.12 / −6.43** | **tek bacak (long) taşıyor** |
| **Permütasyon** | p = **1.0** | tesadüften farksız |
| Maliyet | 0→+0.18, 0.35→−0.18 | başabaş ~%0.20 |

### Kök neden: alfa DEĞİL, beta
Tek pozitif fold sonuncusu (son dönem) ve **long bacak +3.12 / short −6.43**. Yani
"12 gün yükselen coin al" stratejisi, **boğa piyasasında long** olduğu için kazandı —
short bacak felaket. Bu **piyasa betası** (yükselen piyasaya maruz kalma), seçici alfa
değil. 90 günlük veri tek bir boğa rejimi içeriyor; fold-kararsızlığı bunu doğruluyor.

## KARAR
**GEÇMEDİ.** 1d momentum, doğrulamada (3-fold, permütasyon, long/short ayrımı) çöktü;
taşıdığı şey **boğa betası**, sürdürülebilir edge değil. 1h/4h stratejileri de negatif.

Bu, **14. tur** ve kök neden aynı: ölçülebilir sinyal uzayı tükendi. Uzun ufuk
maliyeti amortize ediyor ama **bunu aşacak (beta-üstü) bir sinyal yok**.

## Dürüst kapanış (seçenek b sonucu)
Uzun ufuk **doğru sezgidir** (maliyet matematiği bunu gösteriyor) ama tek başına
yeterli değil: gereken şey uzun ufukta **beta-üstü alfa**. Denenen momentum-stratejileri
(yükselen piyasada long) bunu sağlamıyor. Gerçek alfa için ya:
- **kesitsel (cross-sectional) nötrleme** — long/short sepet, piyasa betası elimine,
- **piyasa-nötr** (pairs/cointegration) — beta sıfır,
- **farklı verme modeli** (arbitraj/market-making)
gerekir. Bunlar kâğıt üstünde "hangi sinyal" değil, **portföy inşası** işidir.

## Yeniden üretim
```
python backend/scripts/research_long_horizon.py --tf 1d --hold 6
python backend/scripts/verify_1d_momentum.py --hold 6
```
