# scalpernew tarama yapısı ve bildirim adaylarının ölçümü (2026-10-17)

## Özet

- **scalpernew, bu uygulamanın 14 Ekim civarındaki eski bir kopyası.** Tarama çekirdeği (Hız Avcısı `velocity.py`, unified tarama, master_surge) satır satır aynı; modlar da aynı kuraldan çıkıyor (RSI'ya göre `trend_devam` / `v_donusu` / `notr`).
- **Fark, taramadan sonraki eleme katmanlarında.** scalpernew'de bildirim politikası (`notification_policy.py`), kapalı modlar (`notr`, `v_donusu`), ≥2 kaynak + Hız teyit kuralı, ölçülmüş hedef kalibrasyonu, aşırı alım kararı, BTC rejim kalkanı ve aday özellik kaydı yok. Likidite tabanının altındaki semboller bizde sessizce düşüyor, orada `likidite_tabani` nedeniyle izleme listesine yazılıyor.
- **Sonuç bizim bulgularımızla aynı yönde:** scalpernew'in 398 adayı gerçekçi dolumla net negatif ve aynı sembolde rastgele girişten kötü. En kötü dilim, bizim kapattığımız `notr` modu.
- **Bizim canlı politikamızdan geçecek 27 aday** (= gölge kural, ≥2 kaynak ∧ Hız ∧ trend_devam) en iyi dilim: net 60 dk −0,09, rastgele girişe göre +0,49 puan. Ancak n=27 ve güven aralığı ±1,09; anlamlı değil.

## Ölçü

Önceki çalışmalarla aynı (`docs/CIKIS_YAPISI_SIMULASYONU_2026-10-17.md`): 60 sn gecikme, %0,15 kayma, bacak başına %0,1125 ücret, SL %3, aynı barda stop önce. Rastgele taban: aynı sembol, ±3 gün, bildirimlerden ≥ 2 sa uzak 20 an. Betik: `backend/scripts/scalpernew_csv_eval.py`.

## 1. scalpernew bildirimleri

| küme | n | /gün | isabet (ufuk) | isabet 60 dk | net ufuk | net 60 dk [±%95] | net izleyen | ham 60 dk sürüklenme | net60 − rastgele |
|---|---|---|---|---|---|---|---|---|---|
| scalpernew — tümü | 390 | 198 | %9.0 | %23.8 | -0.66 | -1.05 ±0.24 | -0.88 | -0.86 | -0.46 |
| scalpernew — push | 60 | 31 | %18.3 | %41.7 | -0.69 | -0.99 ±0.72 | -0.87 | -0.79 | -0.41 |
| scalpernew — panel | 330 | 168 | %7.3 | %20.6 | -0.66 | -1.07 ±0.25 | -0.88 | -0.88 | -0.47 |
| scalpernew — mod notr | 107 | 55 | %7.5 | %28.0 | -1.16 | -1.51 ±0.46 | -1.11 | -1.10 | -0.92 |
| scalpernew — mod trend_devam | 275 | 140 | %9.8 | %22.5 | -0.45 | -0.89 ±0.28 | -0.80 | -0.81 | -0.29 |
| scalpernew — mod unified | 6 | 4 | %0.0 | %16.7 | -0.63 | -0.31 ±1.79 | -0.31 | +1.43 | +0.41 |
| scalpernew — mod v_donusu | 2 | 10 | %0.0 | %0.0 | -2.19 | -2.23 ±2.21 | -0.33 | -2.09 | -1.53 |
| scalpernew — 1 kaynak | 334 | 170 | %8.4 | %22.2 | -0.71 | -1.14 ±0.25 | -0.97 | -0.91 | -0.55 |
| scalpernew — 2 kaynak | 2 | 1 | %0.0 | %50.0 | -1.04 | +0.22 ±2.05 | +0.31 | +0.27 | +0.88 |
| scalpernew — 3+ kaynak | 54 | 29 | %13.0 | %33.3 | -0.37 | -0.58 ±0.73 | -0.31 | -0.64 | +0.03 |
| scalpernew — BİZİM TEYİT KURALINDAN GEÇEN | 50 | 27 | %14.0 | %36.0 | -0.36 | -0.58 ±0.76 | -0.28 | -0.85 | +0.02 |
| scalpernew — teyit kuralına takılan | 340 | 173 | %8.2 | %22.1 | -0.70 | -1.12 ±0.25 | -0.96 | -0.86 | -0.53 |
| scalpernew — BİZİM TÜM CANLI POLİTİKAMIZDAN GEÇEN | 27 | 15 | %14.8 | %40.7 | +0.01 | -0.09 ±1.09 | -0.37 | -0.29 | +0.49 |
| scalpernew — bizde kapalı modlar (notr, v_donusu) | 109 | 56 | %7.3 | %27.5 | -1.18 | -1.52 ±0.45 | -1.09 | -1.12 | -0.94 |
| scalpernew — gölge kural (≥2 ∧ trend_devam) | 27 | 15 | %14.8 | %40.7 | +0.01 | -0.09 ±1.09 | -0.37 | -0.29 | +0.49 |

## 2. Aynı dönemde karşılaştırma (15.10 22:42 → 17.10 14:53)

| küme | n | /gün | isabet (ufuk) | isabet 60 dk | net ufuk | net 60 dk [±%95] | net izleyen | ham 60 dk sürüklenme | net60 − rastgele |
|---|---|---|---|---|---|---|---|---|---|
| scalpernew — çakışan dönem | 318 | 191 | %8.2 | %23.3 | -0.72 | -1.07 ±0.26 | -0.93 | -0.95 | -0.48 |
| bizim prod — aynı dönem | 83 | 50 | %12.0 | %31.3 | -0.70 | -1.07 ±0.57 | -0.59 | -1.21 | -0.54 |
| scalpernew çakışan — teyit kuralından geçen | 38 | 24 | %7.9 | %31.6 | -0.51 | -0.75 ±0.85 | -0.35 | -0.89 | -0.13 |
| bizim prod — teyit kuralından geçen (mod bilinmiyor) | 4 | 3 | %25.0 | %25.0 | -1.31 | -0.98 ±2.72 | +0.11 | -1.10 | -0.77 |

Ortak sembol 31, yalnız scalpernew 45, yalnız bizim 0.

Gecikmesiz, bildirim fiyatından ölçülen ufuk-içi dokunuş: %13.8 (60 sn gecikme + kayma ile: %9.0).

## 3. scalpernew'in kendi sonucu × bizim ölçüm (ufuk içinde hedefe değdi mi)

| scalpernew durumu | bizim: ulaştı | bizim: ulaşmadı |
|---|---|---|
| BAŞARISIZ | 0 | 21 |
| KISMİ | 5 | 154 |
| TAMAMEN BAŞARILI | 30 | 56 |
| ÖLÇÜLEMEDİ | 0 | 124 |

## scalpernew'in kendi başarı etiketi neden iyimser

- "TAMAMEN BAŞARILI" satırlarının dokunuş dakikası medyanı 10,8; "KISMİ" satırlarınınki 43,8. Ufuk 5–15 dk olduğu halde etiket daha uzun pencereye bakıyor.
- Gecikmesiz, bildirim fiyatından ölçülen ufuk içi dokunuş %13,8. 60 sn gecikme ve kaymayla %9,0'a iniyor.
- Uygulamanın kendi `net_pct` ortalaması −0,92 (267 ölçülmüş satır). Bizim 60 dk net ölçümümüz −1,05. İki ölçü aynı sonucu veriyor.

## Ne yapılmalı

- scalpernew'e eklenebilecek en değerli şey bizim politika katmanı: `notr` ve `v_donusu` modlarını kapatmak, tek kaynaklı push'u kesmek. Bu, adayların %93'ünü eliyor ve kalanın ortalaması belirgin şekilde daha iyi.
- Kalan dilim bile güvenilir biçimde net pozitif değil. Gölge kural ölçümü (~31 Ekim) ve geçmiş mikro yapı verisi tamamlanınca yeniden bakılmalı.
