# USD Lead-Lag Sinyal Araştırması — 2026-10-12

Devam: [FIZIBILITE_orderbook_limit_2026-10-12.md](FIZIBILITE_orderbook_limit_2026-10-12.md)

## Kullanıcı önerisi
> "Binance Global public APIsindeki aynı sembolün USD varyasyonunu kullanalım; sonuçta TRY ile
> USD grafikleri aynı şekilde hareket ediyor."

Fikir: sinyali **derin/likit USD piyasasından** üret (730 gün geçmişli), işlemi **TRY çiftiyle**
yap. Bu, daha önce test edilen basit `g_ret1` (Global momentum) kanalından farklı: burada
sinyali USD'den üretip TRY'ye taşıyoruz ve **eşzamanlı hareketi arındırıyoruz**.

## Yöntem
`scripts/research_usd_leadlag.py` — `channel_cache.json` (118 sembol × TR+Global 5m, hizalı).
1. **Korelasyon** (önerme doğrulaması).
2. **Gerçek öncülük:** `GL[i]`'yi aynı-bar `TRY[i]` hareketine regres et → **residual**.
   `residual → TRY[i+1..]` korelasyonu > 0 ise USD, TRY'nin geleceğini öngörüyor (eşzamanlılık
   değil). Beta yalnız eğitimde fit edilir.
3. **Maliyet sonrası:** taker / maker(naif) / **maker + gerçek limit dolgu** + gün-gün + yoğunlaşma.

## Bulgular

### 1) Önerme DOĞRU — USD, TRY'nin gerçek vekili
| Ölçüm | Değer |
|---|---|
| Aynı-bar getiri korelasyonu (GL ↔ TRY) | **0.865** (medyan sembol 0.82; en likitler 0.98) |
| Fiyat oranı | sabit ~49 (USDTRY kuru) |

Yani USD grafiği TRY hareketinin gerçek bir vekili — önerme veriyle doğrulandı.

### 2) GERÇEK ÖNCÜLÜK VAR (yedi turun ilk mekanizmalı sinyali)
Eşzamanlı hareket arındırıldıktan sonra **residual → ileri TRY getirisi** korelasyonu:

| Ufuk | Residual korelasyon |
|---|---|
| 1 bar (5 dk) | **+0.165** |
| 3 bar (15 dk) | +0.122 |
| 6 bar (30 dk) | +0.096 |
| 12 bar (60 dk) | +0.065 |

**Mekanizma gerçek:** USD piyasası, TRY'nin henüz yansıtmadığı bilgiyi taşıyor (likidite/gecikme
farkı). Bu, önceki turlardaki gürültü seviyesindeki sinyallerden **niteliksel olarak farklı** —
112 sembolde tutarlı, yoğunlaşma yalnız %1.8 (tek sembole bağlı değil).

### 3) AMA MALİYET SINIRINDA — net hâlâ negatif
| Eşik | n | Brüt (15dk) | Taker net | Maker naif | **Maker + gerçek limit** | Maker win |
|---|---|---|---|---|---|---|
| p90 | 6891 | +0.188% | −0.162% | +0.148% | **−0.453%** | 52.1% |
| p85 | 8963 | +0.158% | −0.192% | +0.118% | **−0.456%** | 50.6% |
| p80 | 10612 | +0.131% | −0.219% | +0.091% | **−0.462%** | 48.9% |

- **Taker:** hep negatif (brüt +0.19%, maliyet %0.35).
- **Naif maker:** ilk kez **pozitif** (+0.15, win %52) — çünkü brüt edge maliyete çok yakın.
- **Maker + gerçek limit dolgu:** **−0.45%'a çöküyor** — limitin dolduğu işlemler (fiyatın
  düştüğü kötü işlemler) sinyali öldürüyor. (5. turdaki adverse-selection tuzağının aynısı.)

### 4) Gün-gün stabilite: taker ile 0/4 gün pozitif
`{20733: −0.221, 20734: −0.205, 20735: −0.148, 20736: −0.175}`

## KARAR
**`USD_LEADLAG_REAL_BUT_COST_BOUND`**

USD→TRY lead-lag, **yedi turda ilk kez mekanizması olan gerçek bir sinyal** (residual korelasyon
+0.165, 112 sembolde tutarlı). Ancak brüt edge (+0.13–0.19%) ile yürütme maliyeti (%0.30 taker /
maker+adverse-selection) neredeyse eşit: naif maker'da pozitife döner gibi görünse de, **gerçek
limit dolgusu bunu −0.45%'a çeviriyor.**

**Bu bulgu, "USD'yi kullan" önerisinin kısmen haklı olduğunu gösterir** — sinyal bilgisi gerçek ve
yönü doğru. Sorun sinyal değil, **maliyet duvarı**: edge, maliyetin hemen altında sıkışıyor.
_Not: Bu koşu 118 sembol × ~4 günlük 5m penceresiyle yapıldı (channel_cache kapsamı). Daha uzun
pencere + daha yüksek likidite filtresi (yalnız spread<%0.05 semboller) yeni bir kalibrasyon
ekseni — ama temel örüntü (brüt≈maliyet) yedi turda tutarlı olduğu için beklenti düşük._

## Yedi turun özeti
| # | Katman | Sonuç |
|---|---|---|
| 1 | Çıkış geometrisi (SL 3.0→1.0) | Kaybı ~%50 azalttı ✅ UYGULANDI |
| 2 | Giriş seçici | NO_ENTRY_EDGE |
| 3 | Fiyat-mum feature'ları | NO_FEATURE_EDGE |
| 4 | Order-flow / lead-lag kanalları | NO_CHANNEL_EDGE |
| 5 | Rejim + 1 sa ufuk | NO_REGIME_EDGE |
| 6 | Maker / maliyet mimarisi | NO_MAKER_EDGE |
| 7 | **USD lead-lag (eşzamanlılık arındırılmış)** | **REAL_BUT_COST_BOUND** (ilk gerçek sinyal, edge≈maliyet) |

## Yeniden üretim
```
python backend/scripts/research_usd_leadlag.py
```
Rapor: `work/usd_leadlag_research.json` (gitignore).
Kilitler: `tests/test_research_usd_leadlag.py` (look-ahead/parite/maliyet, mutasyonla doğrulandı).
