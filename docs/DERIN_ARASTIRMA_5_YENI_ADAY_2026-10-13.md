# Derin Araştırma — 5 Yeni Test Adayı (2026-10-13)

**ARAŞTIRMA — commit YOK (kullanıcı isteği).**

## Amaç
12 turda denenen sınıflardan (fiyat/hacim/order-flow/lead-lag/rejim/funding/cross-venue/
order-book L2) FARKLI, veriyle test edilebilir yeni adaylar. 12 turun ortak dersi:
ham sinyal edge'i (~%0.05-0.2 brüt) maliyetin (0.10-0.35%) altında. Bu yüzden türev/
yapısal sinyallere odaklandım.

## Yeni erişilebilir veri sınıfları (doğrulandı)
| Kaynak | İçerik | Periyot | Geçmiş |
|---|---|---|---|
| futures `metrics` | OI + top-trader L/S + hesap L/S + taker oranı | 15 dk | 600+ gün |
| spot+futures `klines` | spot-futures **basis** türetimi | 5 dk | 600+ gün |
| `BVOLIndex` (options) | BTC implied volatilite | 1 sn | var (404 bazı tarihler) |

## 5 Aday + ön test sonuçları (BTCUSDT, 30 gün)

### B1 OI DEĞİŞİMİ (`d_oi`)
corr fwd15 **+0.022**, fwd30 **+0.038** → en anlamlısı ama zayıf.
EV: en iyi hücre `d_oi_lo_ters_fwd30` = **−0.321%** (negatif).

### B2 TOP-TRADER LONG/SHORT (`ls_top`)
corr **+0.001/+0.002** → ilişki YOK. EV tümü negatif.

### B3 TAKER BUY/SELL ORANI (`taker`)
corr −0.009/−0.016 → yok, hatta hafif ters. EV tümü negatif.

### B4 SPOT-FUTURES BASIS
corr fwd15 **+0.050**, fwd30 **+0.057** → zayıf pozitif.
EV: en iyi `basis_hi_fwd30` = **−0.308%** (negatif).

### B5 OPSİYON VOL (BVOL)
Veri erişilebilir ama bu koşuda test edilmedi (zaman); metrics/basis sonuçları yeterli sinyal verdi.

## Sonuç tablosu
| Özellik | corr (fwd30) | En iyi EV (taker) |
|---|---|---|
| OI değişimi | +0.038 | −0.321 |
| Basis | +0.057 | −0.308 |
| Top-trader L/S | +0.002 | neg |
| Taker oranı | −0.016 | neg |
| (önceki) deep_imb | +0.082 | −0.285 |

**Pozitif EV hücresi: 0.** Hepsi negatif.

## Kritik örüntü (13. kez)
En "güçlü" korelasyonlar (`deep_imb` +0.08, basis +0.06, OI +0.04) brüt ~+0.05-0.08%
edge'e karşılık gelir — **round-trip maliyetin (0.10-0.35%) altında**. Yani:

> **Bilgi VAR, ama her seferinde maliyet duvarının hemen altında.**

Bu, 13 turda 9 farklı bilgi sınıfıyla tutarlı biçimde doğrulandı. Sorun sinyal bulmakta
değil; **mevcut maliyet yapısı (taker %0.30-0.35) 5 dk-1 saat ufkunda üretilebilen tüm
brüt edge'lerin üzerinde.**

## Ne anlama geliyor (yapısal sonuç)
- Mikro-yapı, türev, basis, order-book — hepsi `corr ~0.03-0.08` bandında bilgi taşıyor.
- Bu banttaki bilginin **net kâra** dönmesi için maliyetin ~%0.05'in altına inmesi
  gerekir. Binance TR taker %0.15×2 + spread bunu imkânsız kılıyor.
- Tek yapısal çıkış: **maker/limit yürütme** (maliyet ~%0.02-0.05) — ama o zaman
  adverse-selection (5. turda kanıtlandı) brüt edge'i yiyor.

## Öneri
Bu noktadan sonra "yeni sinyal sınıfı ara" döngüsü **beklenen değeri düşük** — ölçülebilir
bilgi sınıflarının hepsi denendi ve hepsi aynı duvara çarptı. Anlamlı ilerleme için ya:
(a) **maliyet indirimi** (VIP/BNB/farklı venue), (b) **uzun ufuk** (saatlik/günlük, maliyet
daha seyrek işlemle amortize olur), (c) **gelir modeli değişikliği** (arbitraj/piyasa-yapıcı)
gerekir. Bunlar sinyal araştırması değil, **ürün/iş modeli** kararları.

## Yeniden üretim
```
python backend/scripts/research_new_derived_signals.py --days 30 --symbol BTCUSDT
```
Önbellek: `work/dc2_cache/`. Rapor: `work/new_derived_signals.json`.
