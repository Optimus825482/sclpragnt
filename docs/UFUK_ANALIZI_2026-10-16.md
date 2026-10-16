# Uzun Ufuk ve Komisyon Analizi — 2026-10-16

**Soru:** Yükselme-potansiyeli bildirimlerinde ufuk büyütülürse (4–24 saat) ya da komisyon BNB ile düşürülürse sistem net kârlı olur mu?
**Veri:** 30 günlük bildirim journal'ı (3597 bildirim, 16 Eylül–16 Ekim) + 303 sembol için 5 dakikalık mumlar (`historical_candles`). 24 saatlik penceresi veri sonunu aşan 74 bildirim düşüldü (n = 3522; bağımsız sembol-gün çifti 990).
**Yöntem:** ufuk H ∈ {60, 120, 240, 480, 720, 1440} dk, hedef T ∈ {1.5, 2, 3, 4, 6, 8} %, stop S ∈ {2, 3, 5} %, maliyet ∈ {0.35, 0.25 (BNB), 0.20} %; iki çıkış kuralı (TP/SL/ufuk sonu; trailing T/2 tetik, T/3 aralık). Stop dolumu: mum açılışı stopun altındaysa açılıştan (ilk sürümde stop fiyatından dolum varsayımı trailing hücrelerini sahte pozitif gösteriyordu; düzeltildi). Şans tabanı: aynı sembolde, 30 dk volatilite/getirisi eşleşmiş rastgele anlar.

## 1. Hedefe ulaşma oranı (MFE_H ≥ T, %)

| H (dk) | 1.5 | 2 | 3 | 4 | 6 | 8 |
|---|---|---|---|---|---|---|
| 60 | 57.7 | 49.8 | 37.8 | 30.2 | 18.9 | 12.9 |
| 240 | 71.3 | 65.4 | 53.9 | 45.6 | 33.4 | 25.1 |
| 720 | 79.2 | 74.2 | 65.1 | 57.7 | 45.5 | 36.5 |
| 1440 | 82.9 | 78.7 | 70.9 | 64.6 | 53.4 | 44.1 |

Medyan MFE 60 dk'da 1.98 → 24 saatte 6.68; **medyan MAE −2.66 → −7.92**. Tutma getirisi (ufuk sonu kapanış) 60 dk −0.49, 24 saat −1.19. Hit yükselirken ters hareket aynı hızla büyüyor.

## 2. Net getiri ızgarası (216 sabit-hedef hücresi + trailing)
- **Ortalama net > 0 ve t > 2 olan hücre: sıfır** — üç maliyet düzeyinde de.
- En az kötü hücre: trailing, H60, T1.5, S2 → net −0.37 / −0.27 / −0.22 (maliyet 0.35 / 0.25 / 0.20).
- T ≥ 3 hücreleri −0.4 … −0.7; 24 saat / T8 / S5 → −0.76.
- Mevcut 60 dk kuralı: net −0.61 (t −13.7), **brüt −0.26** → komisyon sıfır olsa bile negatif.

## 3. Alt kümeler
| Küme | En iyi hücre | Net (0.35 / 0.25) | Dayanıklılık |
|---|---|---|---|
| `trend_devam` + skor ≥95 (n=514) | trailing H60 T1.5 S3 | +0.29 / +0.39 (t 2.9) | ilk yarıda seçip ikinci yarıda ölçünce **−0.00**; gecikmeli dolumda (sonraki mum açılışı) brüt +0.26 → **−0.07**; ONETRY/RADTRY/SANDTRY taşıyor, ilk 5 sembol dışında +0.20 (t 1.3) |
| `unified` H1440 T8 S5 | — | +0.71 (t 4.2) | H38–H40 pozitif, H41–H42 negatif (−0.52, −2.47); yarı-örnekte −0.52 → dönem etkisi |
| `global_lead_lag`, `notr`, `llm_ikinci_goz`, güncel kapılar | — | hepsi negatif (en iyi −0.22) | — |

## 4. Şansa karşı
- 60 dk / T1.5'te dedektör şansın **+9.5 puan** üstünde; 24 saatte düşük hedeflerde fark yok (−0.4 … +0.1) → uzun ufuktaki yüksek hit büyük ölçüde **drift**.
- Tutma getirisi farkı 60–1440 dk'da istatistiksel sıfır. Net fark çoğu hücrede −0.04 … −0.24.
- Örtüşme: 24 saatte bildirimlerin %79'unun aynı sembolde önceki 24 saatte bildirimi var; tekrarsız n = 834.

## 5. Komisyon etkisi (BNB indirimi)
| Küme | 0.35 | 0.25 | 0.20 |
|---|---|---|---|
| Mevcut 60 dk kuralı (tümü) | −0.61 | −0.51 | −0.46 |
| `trend_devam` + skor ≥95, brüt +0.26 | −0.09 | +0.01 | +0.06 |

Yani BNB indirimi tek başına genel sistemi kâra geçirmiyor; yalnız en seçici kümede (günde ~17 bildirim) başabaşa getiriyor, o da gecikmeli dolumda kayboluyor.

## 6. Sonuç
1. **Ufuk büyütmek çözüm değil:** 4–24 saatte hit artıyor ama MAE ve tutma zararı daha hızlı büyüyor; şansa göre ek değer yok.
2. **Komisyon indirimi gerekli ama yeterli değil:** mevcut kural brüt negatif; indirim yalnız `trend_devam + skor ≥95` kümesini sıfıra taşıyor.
3. **Dedektörün değeri 60 dk'da ve isabet tarafında** (+9.5 puan); bunu kâra çevirmenin yolu giriş gecikmesini azaltmak (bildirim → dolum) ve seçiciliği artırmak, ufku değil.
4. **Uygulama tarafı:** Binance TR API'sinde BNB komisyon modunu okuyan/değiştiren uç yok; arayüz komisyon oranlarını ve BNB bakiyesini gösterir, mod Binance TR web ayarlarından değiştirilir.

**Sınırlar:** 30 gün, tek rejim (ikinci yarı belirgin kötü); 5 dk mumda mum-içi sıra bilinmiyor (SL önce); giriş = bildirim fiyatı (gecikmeli dolum ayrı varyant); çoklu karşılaştırma (t > 2 tek başına yeterli değil); şans eşleşmesi bildirimlerin %75–83'ünü kapsıyor.
Ham çıktılar: scratchpad `backtest/horizon/` (horizon_30d.py/.md, grid.csv, entryopen varyantı).
