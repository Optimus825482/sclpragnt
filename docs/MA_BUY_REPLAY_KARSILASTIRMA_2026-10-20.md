# MA BUY replay — 7 / 30 / 90 gün karşılaştırması (canlı sembol seçimiyle), 2026-10-20

Üç koşu da aynı mantıkla: 310 TRY çifti, her 10 dk 24 sa yükselenler ilk 50, her saat aktivite filtresi
(canlı koddaki fonksiyonlarla), MA sinyali yalnız o anda AKTİF sembolde sayılır. Mum verisi `historical_candles`
arşivi (1m / 5m / 15m; 30m ve 1h 15m'den kurulur). Kural: SMA 7/20/99, StochRSI K ≤ 80 (M1 hariç). Ayrıntılı raporlar:
`MA_BUY_REPLAY_CANLI_EVREN_{7g,30g,90g}_2026-10-20.md`.

## Sinyal sayısı ve "bir sonraki sinyale kadar" medyan MFE

| TF | 7 gün | 30 gün | 90 gün |
|---|---:|---:|---:|
| M5 | 250 sinyal · %2,31 | 1.558 · %3,37 | 4.520 · %3,99 |
| M15 | 132 · %3,05 | 766 · %4,70 | 2.166 · %6,87 |
| M30 | 61 · %3,69 | 353 · %6,24 | 1.068 · %11,03 |
| H1 | 26 · %5,64 | 158 · %8,59 | 471 · %15,93 |

Bu ölçüt ufuk uzadıkça büyür: "sonraki sinyal" M30'da medyan 5 gün, H1'de 10 gün sonra geliyor; o kadar sürede
en yüksek fiyat doğal olarak uzaklaşıyor. Hedef kalibrasyonu için sabit ufuklar esas alınmalı.

## Sabit ufuklarda medyan en yüksek yükseliş (90 gün)

| TF | 15 dk | 1 sa | 4 sa | 24 sa |
|---|---:|---:|---:|---:|
| M5 | %0,48 | %1,08 | %2,11 | %4,93 |
| M15 | %0,50 | %1,04 | %2,07 | %4,51 |
| M30 | — | %0,99 | %2,17 | %4,38 |
| H1 | — | %1,23 | %2,36 | %4,75 |

7 ve 30 günlük koşularda aynı tablo ±%0,3 içinde (1 sa ≈ %1,0–1,3; 4 sa ≈ %1,9–2,5; 24 sa ≈ %3,8–4,9): sabit ufuk
ölçütü dönemden bağımsız, kararlı.

## Hedefe dokunma (sonraki sinyale kadar, 90 gün)

| TF | Hedef | Dokunma oranı | ≥%2 | ≥%3 |
|---|---:|---:|---:|---:|
| M5 | %1,5 | %73 | %67 | %57 |
| M15 | %2,0 | %78 | %78 | %70 |
| M30 | %2,5 | %85 | %88 | %81 |
| H1 | %3,0 | %87 | %91 | %87 |

## Evren davranışı (90 gün)

- 2.160 saatlik anlık görüntü; 310 çiftin hepsi en az bir kez izlenen evrene girdi.
- Saat başına AKTİF sembol: ortalama 11,6 (en az 0, en çok 33). Aktif küme yalnız 1 saatte boş kaldı.
- 192.405 ham MA sinyalinden 8.225'i (%4,3) sistemin o anda taradığı sembolde oluştu; sabit listeli replay bu
  elemeyi yapmadığı için canlıyla karşılaştırılamaz.

## Dürüst sınırlar

- MFE "görülen en yüksek fiyat"tır; çıkış kuralı (TP/SL/iz süren stop) simüle edilmedi, komisyon düşülmedi.
- 24 sa değişim/hacim 5m mumlardan türetildi (canlıda borsa ticker'ı); açık paper pozisyonlarının evrene eklenmesi yok.
- Aktivite kararı yalnız izlenen (ilk 50) sembollerde — canlıda da izlenmeyen sembol WARMING kalır.
