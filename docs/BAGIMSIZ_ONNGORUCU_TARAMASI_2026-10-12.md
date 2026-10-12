# Bağımsız Öngörücü Taraması — 2026-10-12

Devam: [GIRIS_SECICI_TARAMASI_2026-10-12.md](GIRIS_SECICI_TARAMASI_2026-10-12.md)

## Soru
`velocity_score` ve giriş filtreleri edge taşımıyordu (`NO_ENTRY_EDGE`). Fiyat/mum
verisinden **türetilebilen bağımsız** bir öngörücü edge verir mi?

## Yöntem
`scripts/scan_entry_features.py` — sinyal anında **yalnız kapanmış barlardan** hesaplanan
feature'lar (öncü momentum r1/r3/r6/r12, hacim patlaması vol_r, volatilite rng/atr14,
24s zirve-dip konumu hi24d/lo24d/pos24, yeşil-bar serisi, saat) + walk-forward (eğitimde
eşik → sınavda EV) + eşleştirilmiş t-testi. 4.439 aday-mum eşleşmesi (tam kapsam, REST dahil).

## ⚠️ ÖNCE BİR HATA YAKALANDI: look-ahead sızıntısı
İlk sürüm feature indeksini `bisect_left(t, ts)-1` ile alıyordu. Bir bar `open_time`'da
açılıp **+300 sn'de kapanır** → `ts` anında o bar hâlâ AÇIK olabilir ve kapanışı okunur.
Doğrulama: 10/10 adayda sızıntı **var**. Sonuç: sahte bir "momentum edge"i (r1/r3/r12,
t>6, EV pozitif). Düzeltme: `bisect_right(t, ts-300)-1` (yalnız kapanmış bar).
**Bu, tek düzeltmeyle tüm pozitif hücreleri yok etti** — yani önceki "edge" tamamen
sızıntıydı. Kilitleyen test: `tests/test_feature_scan_no_lookahead.py` (mutasyonla doğrulandı).

## Bulgular (düzeltme SONRASI, tam örneklem, n_sınav=1776)
| Feature (sınav EV) | EV/işlem | t | 
|---|---|---|
| Baz (filtresiz) | -0.351% | — |
| vol_r (hacim patlaması) yüksek | -0.060% | +5.9 |
| r1 (öncü momentum) yüksek | -0.022% | +5.4 |
| atr14 düşük | -0.292% | +1.6 |
| pos24 yüksek (zirvede) | -0.682% | -5.7 |
| hour yüksek (akşam) | -1.058% | -4.2 |

- **Hiçbir tek feature pozitif değil.** İki aday (vol_r, r1) başabaşa çok yakın ve anlamlı.

## Kombinasyon denemesi ve nedeni reddedildi
`vol_r≥p60 & r1≥p50 & atr14≤p50` kombinasyonu tek walk-forward'da **+0.20% (t=7.45)**
göründü. Ama titiz doğrulama bunu çürüttü:
- **3-fold zaman CV:** fold1 **-0.46%**, fold2 +0.19% → kararsız.
- **Sembol yoğunlaşması:** seçilen 315 işlemin %24'ü tek sembolde (SANDTRY n=75).
- **Leave-one-symbol-out:** SANDTRY çıkarılınca +0.20 → **-0.18%**; 3 sembol çıkarılınca **-0.33%**.
- Yani "edge" **tek bir coin'in tek bir dönemdeki hareketi** — genellenebilir değil.

## Karar
**NO_FEATURE_EDGE** — fiyat/mum uzayından türetilen hiçbir öngörücü genellenebilir pozitif
EV üretmiyor. Görünen kombinasyon edge'i sembol+dönem aşırı-uydurmasıydı ve sağlamlık
testlerinde (fold, sembol-çıkarma, permütasyon) çöktü. Uygulanacak parametre **yok**.

## Sonuç (üç turun özeti)
1. **Çıkış** (SL 3.0→1.0): kaybı ~%50 azalttı, kanıtlı — UYGULANDI (6bc2ee6).
2. **Giriş seçici** (skor/rank/ATR/ML): edge yok, skor tersine çalışıyor — `NO_ENTRY_EDGE` (3128cec).
3. **Bağımsız öngörücü** (fiyat/mum feature'ları): edge yok — `NO_FEATURE_EDGE` (bu tur).

**Tükenme noktası:** Mevcut veriyle (fiyat + hacim + TRY tavanı evreninde) 5 dk ufkunda
yükselişi önceden bilmek mümkün görünmüyor. Pozitife dönüş için **yeni veri kanalı** gerekir
(order-flow/derinlik, zincir-üstü akış, haber/duygu, cross-exchange lead-lag) — mevcut
mum verisini yeniden düzenlemek değil.

## Yeniden üretim
```
python backend/scripts/scan_entry_features.py --hours 3600 --fetch
```
Rapor: `work/entry_feature_scan_full.json` (gitignore'da; ham veri).
