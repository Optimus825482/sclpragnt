# Altcoin rotasyonu — uzun vadede (4 sa / 1 g / 3 g) net kenar var mı?

*Çevrimdışı araştırma, 2026-10-17; canlı koda ve DB'ye dokunmaz. Kod: `backend/scripts/rotation_study.py`, saf yardımcılar `backend/app/rescan/rotation.py` (+ `tests/test_rotation.py`). Ham çıktı: `work/rotation/results*.json`, `configs*.csv`.*

## Karar

**Rotasyon fikirleri (BTC'ye göre göreli güç, genişlik kapısı, altseason kapısı, 2–4 hafta momentum→dönüş) 4 sa–3 g ufkunda da net kenar üretmiyor; ufku uzatmak maliyet duvarını alçaltıyor ama seçim sinyalinin kenarını büyütmüyor.** 96 konfigürasyon × 2 evren (24 sa quote ≥5 M ve ≥50 M TRY) × 2 maliyet senaryosu (taker / maker) denendi; aşağıdaki ana sayılar taker (piyasa emri) senaryosudur; tüm dönemde net pozitif olan konfig sayısı ana evrende 2/96, likit evrende 5/96; hiçbiri BTCTRY al-tut'u (+31%) geçmiyor (en iyi tek konfig +28,8%, 76 gün, likit evren, seçim önyargılı; EW al-tut +26% ile aynı düzeyde — piyasa bu 89 günde zaten yükseldi, pozitif görünenler büyük olasılıkla piyasa betası). Yürüyen-ileri seçim (parametreler yalnız önceki bloklarla seçildi) B2+B3'te ana evrende net -15,1% (DSR 0,001); likit evrende +18,9% (DSR 0,010) — ama aynı iki blokta BTCTRY al-tut +29%, EW(≥50 M) al-tut +17%. Hiçbir konfig DSR 0,95'e yaklaşmıyor (en yüksek DSR 0,005, N=384); gözlenen en iyi günlük Sharpe 0,111 şansla beklenen en iyiden (0,374) düşük. Sinyalin yönü ters: en güçlü RS sepeti (A, k=10, 1 g) tüm dönemde brüt -60% yaparken aynı evrende rastgele 10'lu sepet brüt +38% yapıyor (medyan EW'ye göre kenar günde -1,58%, maliyetten ÖNCE) → 'güçlüyü al' bu evrende negatif seçim; olası açıklama: pompalanmış ince TRY çiftleri geri veriyor (bu bir hipotez, ayrıca sınanmadı). Dönüş (dip alma) sepetinin EW'ye göre kenarı likit evrende 3 g tutmada ≈ sıfır (medyan -0,01%/gün); net artı veren birkaç konfig beta + şans ve ~%20'lik düşüşle geliyor, hayatta kalma yanlılığı da bu sepeti özellikle şişiriyor. **Sınır:** 89 gün yalnız 3 rejim bloğu (düşüş trendi yok) ve 3 g tutma için ≈30 bağımsız dönem demek; küçük bir kenar bu veriyle ne kanıtlanabilir ne çürütülebilir — ama canlıya taşınacak düzeyde bir kanıt yok. Maliyet tarafı: 4 sa'te rastgele sepet bile günde ≈%3 maliyet öder (devir ~11/gün), 3 g'de ≈%0,15 — yani ufuk uzayınca duvar düşüyor, fakat net sonuçlar 'BTC/EW al-tut'u geçemeyen piyasa betasına' benziyor.

## Özet tablo

Net = ücret %0,1125 + kayma %0,15 / bacak sonrası. Hücre: net getiri · maks. düşüş · günlük devir (alış+satış toplamı, portföy payı). Son sütun: B2+B3 OOS günlük Sharpe / DSR (N=384).

| Strateji | B1 07-20..08-18 | B2 08-19..09-17 | B3 09-18..10-16 | OOS Sharpe / DSR |
|---|---|---|---|---|
| BTCTRY al-tut (1 gidiş-dönüş maliyetli) | +0,9% · DD -6% | +19,7% · DD -7% | +8,2% · DD -7% | — |
| EW evren al-tut, ≥5 M | -3,1% · DD -8% | +15,8% · DD -11% | +12,0% · DD -13% | — |
| EW evren al-tut, ≥50 M | -1,9% · DD -19% | +8,6% · DD -23% | +7,9% · DD -15% | — |
| Yürüyen-ileri, ≥5 M, tüm konfiglerden | (eğitim) | -1,0% · DD -20% · devir 0,3 | -14,2% · DD -34% · devir 0,2 | -0,057 / 0,001 |
| Yürüyen-ileri, ≥5 M, yalnız A momentum | (eğitim) | -66,6% · DD -71% · devir 3,2 | -7,9% · DD -26% · devir 0,6 | -0,339 / 0,000 |
| Yürüyen-ileri, ≥5 M, yalnız A2 kalıntı-RS | (eğitim) | -20,4% · DD -35% · devir 0,5 | -19,5% · DD -46% · devir 0,4 | -0,119 / 0,000 |
| Yürüyen-ileri, ≥5 M, yalnız B breadth kapı | (eğitim) | -47,8% · DD -54% · devir 2,6 | -5,8% · DD -21% · devir 0,3 | -0,289 / 0,000 |
| Yürüyen-ileri, ≥5 M, yalnız B altseason kapı | (eğitim) | -18,0% · DD -29% · devir 1,2 | -37,1% · DD -58% · devir 2,0 | -0,161 / 0,000 |
| Yürüyen-ileri, ≥5 M, yalnız C dönüş | (eğitim) | +6,3% · DD -17% · devir 0,6 | -2,2% · DD -20% · devir 0,6 | 0,037 / 0,005 |
| Yürüyen-ileri, ≥50 M, tüm konfiglerden | (eğitim) | +11,4% · DD -16% · devir 0,4 | +6,7% · DD -22% · devir 0,4 | 0,100 / 0,010 |
| Yürüyen-ileri, ≥50 M, yalnız A momentum | (eğitim) | -66,9% · DD -72% · devir 3,1 | -7,8% · DD -24% · devir 0,6 | -0,337 / 0,000 |
| Yürüyen-ileri, ≥50 M, yalnız A2 kalıntı-RS | (eğitim) | -8,7% · DD -26% · devir 0,6 | -6,5% · DD -25% · devir 0,6 | -0,063 / 0,000 |
| Yürüyen-ileri, ≥50 M, yalnız B breadth kapı | (eğitim) | -16,4% · DD -31% · devir 0,8 | -3,3% · DD -18% · devir 0,4 | -0,107 / 0,000 |
| Yürüyen-ileri, ≥50 M, yalnız B altseason kapı | (eğitim) | -3,5% · DD -6% · devir 0,0 | -2,4% · DD -20% · devir 0,3 | -0,014 / 0,001 |
| Yürüyen-ileri, ≥50 M, yalnız C dönüş | (eğitim) | +12,3% · DD -18% · devir 0,4 | -5,2% · DD -22% · devir 0,4 | 0,048 / 0,004 |

B1: seçim için öncesinde veri olmadığından yalnız eğitimde kullanıldı. DSR: gözlem = günlük getiri, deneme sayısı N=384 (96 konfig × 2 evren × 2 maliyet senaryosu), konfigler arası Sharpe varyansı 0,0158 (ana) / 0,0177 (likit). 0,5 ≈ şans; ≥0,95 güçlü kanıt.

## Örneklem uyarısı

* 89 değerlendirme günü (07-20..10-16; B3 yalnız 29 gün) ve yalnız 3 rejim: B1 yatay (EW -2,6%), B2 güçlü yükseliş (BTC +20%), B3 ılımlı yükseliş (BTC +9%). Düşüş trendi hiç yok.
* Bağımsız gözlem: 1 g tutmada ≈ 89 günlük getiri (kesitsel olarak piyasayla ortak), 3 g tutmada ≈ 30 çakışmayan dönem, 4 sa tutmada 500+ dönem ama güçlü otokorelasyonlu. 3 g için 3 kayık kol çakışan getiriler üretir; günlük serideki gözlemler bağımsız değil → DSR iyimser.
* N=384 deneme için şans eseri beklenen en iyi günlük Sharpe ≈ 0,374; gözlenen en yüksek günlük Sharpe 0,111 (yıllık 2,1). Gözlenen Sharpe'ın bu eşikten %95 güvenle ayrılması için gereken süre (MinTRL) ≈ sonsuz (gözlenen Sharpe eşiğin altında).

## Yürüyen-ileri ayrıntı (B2 ← B1'de seç, B3 ← B1+B2'de seç; ölçüt günlük Sharpe, ≥15 gün)

**Ana evren (24 sa quote ≥5 M TRY)** — ortalama 198 geçerli sembol

| Blok | Seçilen konfig (aile/skor/L/k/tutma/kapı/yön) | Eğitim Sharpe (yıllık) | Net | Brüt | Devir/gün | MaxDD |
|---|---|---|---|---|---|---|
| B2 | `D_long_bot/rs/L14/k10/3g/none/bot` | 2,4 | -1,0% | +1,4% | 0,30 | -20% |
| B3 | `D_long_top/rs/L28/k10/3g/none/top` | 2,2 | -14,2% | -12,9% | 0,19 | -34% |

**Likit evren (≥50 M TRY)** — ortalama 48 geçerli sembol

| Blok | Seçilen konfig (aile/skor/L/k/tutma/kapı/yön) | Eğitim Sharpe (yıllık) | Net | Brüt | Devir/gün | MaxDD |
|---|---|---|---|---|---|---|
| B2 | `D_long_bot/rs/L14/k10/3g/none/bot` | 2,7 | +11,4% | +15,4% | 0,44 | -16% |
| B3 | `D_long_bot/rs/L14/k10/3g/none/bot` | 2,4 | +6,7% | +9,9% | 0,39 | -22% |

## Aile × tutma özeti (tüm konfigler, tüm kullanılabilir dönem)

Brüt kenar = sepet getirisi − aynı saatlerde EW evren getirisi (günlük, %); maliyet = devir × %0,2625 (günlük, %). Kenar < maliyet ise yapı net negatiftir.

**Ana evren (≥5 M)**

| Aile | Tutma | Konfig | Net>0 | Medyan net (tüm dönem) | En iyi net | Medyan brüt kenar/gün | Medyan maliyet/gün | Medyan devir/gün |
|---|---|---|---|---|---|---|---|---|
| A2_resid_top | 1g | 6 | 0 | -77,7% | -56,2% | -1,61% | 0,30% | 1,14 |
| A2_resid_top | 3g | 6 | 0 | -50,3% | -33,4% | -0,96% | 0,16% | 0,59 |
| A_rs_top | 4s | 6 | 0 | -88,4% | -71,9% | -1,80% | 0,80% | 3,04 |
| A_rs_top | 1g | 6 | 0 | -78,5% | -59,3% | -1,58% | 0,30% | 1,14 |
| A_rs_top | 3g | 6 | 0 | -53,2% | -31,7% | -0,99% | 0,15% | 0,59 |
| B_alt_gate | 4s | 6 | 0 | -61,1% | -32,2% | -0,93% | 0,41% | 1,56 |
| B_alt_gate | 1g | 6 | 0 | -52,3% | -40,3% | -0,78% | 0,16% | 0,60 |
| B_alt_gate | 3g | 6 | 0 | -36,8% | -22,0% | -0,57% | 0,08% | 0,29 |
| B_breadth_gate | 4s | 6 | 0 | -68,0% | -52,6% | -0,83% | 0,65% | 2,48 |
| B_breadth_gate | 1g | 6 | 0 | -38,2% | -20,6% | -0,51% | 0,19% | 0,73 |
| B_breadth_gate | 3g | 6 | 0 | -26,9% | -18,2% | -0,43% | 0,08% | 0,30 |
| C_rev_bot | 4s | 6 | 0 | -63,9% | -45,5% | -0,48% | 0,89% | 3,38 |
| C_rev_bot | 1g | 6 | 0 | -39,8% | -31,1% | -0,57% | 0,32% | 1,20 |
| C_rev_bot | 3g | 6 | 0 | -18,4% | -4,9% | -0,42% | 0,15% | 0,58 |
| D_long | 1g | 6 | 1 | -11,7% | 3,5% | -0,49% | 0,13% | 0,50 |
| D_long | 3g | 6 | 1 | -5,1% | 2,6% | -0,45% | 0,07% | 0,26 |

**Likit evren (≥50 M)**

| Aile | Tutma | Konfig | Net>0 | Medyan net (tüm dönem) | En iyi net | Medyan brüt kenar/gün | Medyan maliyet/gün | Medyan devir/gün |
|---|---|---|---|---|---|---|---|---|
| A2_resid_top | 1g | 6 | 0 | -81,4% | -67,2% | -1,58% | 0,30% | 1,13 |
| A2_resid_top | 3g | 6 | 0 | -49,3% | -31,1% | -0,67% | 0,15% | 0,58 |
| A_rs_top | 4s | 6 | 0 | -88,7% | -73,4% | -1,55% | 0,75% | 2,86 |
| A_rs_top | 1g | 6 | 0 | -82,6% | -68,1% | -1,54% | 0,30% | 1,14 |
| A_rs_top | 3g | 6 | 0 | -55,9% | -34,5% | -0,77% | 0,15% | 0,58 |
| B_alt_gate | 4s | 6 | 0 | -44,3% | -23,1% | -0,54% | 0,26% | 0,99 |
| B_alt_gate | 1g | 6 | 0 | -33,2% | -22,9% | -0,36% | 0,10% | 0,38 |
| B_alt_gate | 3g | 6 | 0 | -24,0% | -15,9% | -0,22% | 0,05% | 0,19 |
| B_breadth_gate | 4s | 6 | 0 | -72,4% | -55,8% | -0,84% | 0,68% | 2,59 |
| B_breadth_gate | 1g | 6 | 0 | -47,7% | -28,0% | -0,56% | 0,22% | 0,83 |
| B_breadth_gate | 3g | 6 | 0 | -24,2% | -4,8% | -0,32% | 0,09% | 0,34 |
| C_rev_bot | 4s | 6 | 0 | -66,1% | -41,0% | -0,25% | 0,79% | 3,00 |
| C_rev_bot | 1g | 6 | 0 | -37,4% | -2,6% | -0,14% | 0,30% | 1,13 |
| C_rev_bot | 3g | 6 | 2 | -11,9% | 10,0% | -0,01% | 0,14% | 0,54 |
| D_long | 1g | 6 | 1 | -8,8% | 3,6% | -0,09% | 0,21% | 0,82 |
| D_long | 3g | 6 | 2 | -2,5% | 28,8% | -0,13% | 0,10% | 0,38 |

## Sıfır-beceri kontrolü (rastgele k sembol, aynı evren/tutma/maliyet; 5 tohum ortalaması, ~89 gün)

| Sepet | Tutma | Ana: net | Ana: brüt | Ana: devir/gün | Likit: net | Likit: brüt | Likit: devir/gün |
|---|---|---|---|---|---|---|---|
| rastgele k10 | 1g | -11,6% | +38,3% | 1,9 | -41,2% | -12,6% | 1,7 |
| rastgele k10 | 3g | +15,6% | +33,7% | 0,6 | -2,6% | +11,4% | 0,6 |
| rastgele k10 | 4s | -92,3% | +10,8% | 11,4 | -91,1% | -16,5% | 9,5 |
| rastgele k5 | 1g | -30,7% | +9,5% | 1,9 | -47,8% | -19,6% | 1,8 |
| rastgele k5 | 3g | +3,6% | +20,2% | 0,6 | +0,2% | +15,7% | 0,6 |
| rastgele k5 | 4s | -93,4% | +2,6% | 11,7 | -94,0% | -25,0% | 10,8 |

Okuma: 4 sa tutmada rastgele sepet bile günde ~10 kat devirle (günde ≈%3 maliyet) %90+ kaybeder → 4 sa ufku maliyet yüzünden baştan ölü. Üst/alt-k sepetlerin brüt getirisini bu satırlarla kıyaslayın.

## En iyi 10 konfig (tüm dönem net) — yalnız bilgi; seçim önyargısı nedeniyle güvenilmez

**Ana evren**

| Konfig | Gün | Net | Brüt | MaxDD | B1 | B2 | B3 | Günlük Sharpe | DSR(N) |
|---|---|---|---|---|---|---|---|---|---|
| `D_long_top/rs/L14/k10/1g/none/top` | 76 | +3,5% | +15,2% | -33% | -17,5% | +6,7% | +17,6% | 0,034 | 0,001 |
| `D_long_bot/rs/L14/k10/3g/none/bot` | 76 | +2,6% | +9,3% | -25% | +6,5% | -1,0% | -2,7% | 0,026 | 0,001 |
| `D_long_top/rs/L14/k10/3g/none/top` | 76 | -2,1% | +4,0% | -27% | -7,2% | +6,5% | -0,9% | 0,017 | 0,001 |
| `D_long_top/rs/L28/k10/3g/none/top` | 62 | -3,8% | -0,4% | -34% | +2,5% | +9,4% | -14,2% | 0,001 | 0,002 |
| `D_long_top/rs/L28/k10/1g/none/top` | 62 | -4,3% | +2,3% | -39% | +4,9% | +4,9% | -13,0% | 0,006 | 0,002 |
| `C_rev_bot/rs/L1/k10/3g/none/bot` | 89 | -4,9% | +9,0% | -21% | -8,5% | +6,3% | -2,2% | -0,005 | 0,000 |
| `D_long_bot/rs/L28/k10/3g/none/bot` | 62 | -6,3% | -2,8% | -23% | -1,2% | -4,7% | -0,4% | -0,019 | 0,001 |
| `D_long_bot/rs/L21/k10/3g/none/bot` | 69 | -7,9% | -3,2% | -21% | -9,4% | +1,8% | -0,1% | -0,025 | 0,001 |
| `D_long_bot/rs/L28/k10/1g/none/bot` | 62 | -9,3% | -3,1% | -23% | -1,9% | -7,0% | -0,6% | -0,038 | 0,001 |
| `C_rev_bot/rs/L3/k10/3g/none/bot` | 87 | -13,6% | -1,2% | -26% | -20,8% | +13,2% | -3,6% | -0,038 | 0,000 |

**Likit evren**

| Konfig | Gün | Net | Brüt | MaxDD | B1 | B2 | B3 | Günlük Sharpe | DSR(N) |
|---|---|---|---|---|---|---|---|---|---|
| `D_long_bot/rs/L14/k10/3g/none/bot` | 76 | +28,8% | +39,9% | -22% | +8,4% | +11,4% | +6,7% | 0,111 | 0,005 |
| `C_rev_bot/rs/L3/k10/3g/none/bot` | 87 | +10,0% | +24,2% | -21% | -3,6% | +14,3% | -0,1% | 0,048 | 0,000 |
| `D_long_bot/rs/L28/k10/3g/none/bot` | 62 | +9,4% | +17,5% | -23% | -0,8% | +3,3% | +6,8% | 0,062 | 0,004 |
| `C_rev_bot/rs/L7/k10/3g/none/bot` | 83 | +5,8% | +16,3% | -22% | -0,6% | +12,3% | -5,2% | 0,037 | 0,000 |
| `D_long_top/rs/L28/k10/1g/none/top` | 62 | +3,6% | +14,5% | -31% | +4,5% | -5,8% | +5,3% | 0,035 | 0,002 |
| `C_rev_bot/rs/L1/k10/3g/none/bot` | 89 | -1,6% | +11,8% | -20% | -6,0% | +5,6% | -0,8% | 0,009 | 0,000 |
| `D_long_bot/rs/L14/k10/1g/none/bot` | 76 | -2,1% | +17,6% | -30% | -7,8% | +14,0% | -6,8% | 0,010 | 0,000 |
| `D_long_top/rs/L28/k10/3g/none/top` | 62 | -2,3% | +2,6% | -27% | +2,1% | -3,4% | -0,9% | 0,008 | 0,001 |
| `C_rev_bot/rs/L7/k10/1g/none/bot` | 83 | -2,6% | +20,0% | -24% | -14,9% | +20,2% | -4,9% | 0,009 | 0,000 |
| `D_long_bot/rs/L21/k10/3g/none/bot` | 69 | -2,8% | +5,0% | -22% | -11,2% | +9,4% | +0,2% | 0,002 | 0,001 |

## İki maliyet senaryosu: (a) piyasa emri (taker) ve (b) bekleyen limit (maker)

(a) bacak başına ücret %0,1125 + kayma %0,15 = %0,2625 (gidiş-dönüş %0,525). (b) bacak başına maker %0,0675, kayma YOK = %0,0675 (gidiş-dönüş %0,135). (b) aynı dolum fiyatını ve aynı zamanlamayı varsayar: limit emrinin HER ZAMAN dolduğu kabul edilir.

| Senaryo | Evren | Net>0 konfig | En yüksek DSR | Yürüyen-ileri OOS (B2+B3) net / DSR | Rastgele k10 3 g net | Rastgele k10 4 sa net |
|---|---|---|---|---|---|---|
| (a) taker | ≥5 M | 2/96 | 0,002 | -15,1% / 0,001 | +15,6% | -92,3% |
| (a) taker | ≥50 M | 5/96 | 0,005 | +18,9% / 0,010 | -2,6% | -91,1% |
| (b) maker | ≥5 M | 5/96 | 0,012 | -12,6% / 0,004 | +28,8% | -44,1% |
| (b) maker | ≥50 M | 12/96 | 0,026 | +24,7% / 0,039 | +7,6% | -52,9% |

Okuma: maker maliyeti net sonuçları iyileştirir ama kenar yaratmaz — en yüksek DSR hâlâ ≤ 0,026 (N=384), likit evrende yürüyen-ileri OOS +24,7% iken aynı iki blokta BTCTRY al-tut (maliyetsiz) +31%. Momentum (A) sepetleri maker'da da rastgele sepetin gerisinde. 4 sa tutma maker'da bile günde ~11 kat devirle ≈%0,75/gün öder ve rastgele sepet −%44..−%61 kaybeder.

**Maker dolum riski (modellenmedi, sonucu aşağı çeker):** (1) Bekleyen limit, fiyat emre dokunmadan kaçarsa dolmaz; rotasyon yeniden dengesinde alınacak (yükselen) isimlerde dolmama olasılığı yüksek, satılacak (düşen) isimlerde dolum olasılığı yüksek → seçilim: dolan emirler ortalamada kaybettiren taraf (adverse selection). (2) Dolmayan emir ya zincirleme gecikme (sinyal bayatlar) ya da piyasa emrine dönüş (taker maliyeti) demek. (3) Yarı-dolum sepeti bozar. Dolayısıyla (b) sonuçları kenar üst sınırıdır; (b) bile pozitif DSR üretmediği için gerçek dolumla durum daha kötüdür.

## Yöntem

* **Veri:** `historical_candles` 15m (salt-okunur), 308 sembol; TR günü 07-19 ısınma, 07-20..10-16 değerlendirme; saatlik barlara toplandı. Karar saat barının kapanışında (yalnız geçmiş); dolum karardan sonra 1 adet 15 dk barın AÇILIŞI (≈15 dk gecikme), alışta ve satışta.
* **Maliyet:** bacak başına ücret %0,1125 + kayma %0,15 = %0,2625 (exit_sim.py sözleşmesi; gidiş-dönüş %0,525). Maliyet **devir temelli**: yeniden dengede yalnız |Δw| × bacak maliyeti ödenir (sepet devam ederse maliyet yok). Spot, long-only, kaldıraçsız; kapı kapalıyken nakit.
* **Evren:** karar anında son 24 sa quote hacmi ≥ 5 M TRY (ana) veya ≥ 50 M TRY (likit) olan semboller (nedensel); pegli/durağan çiftler çıkarıldı (FDUSDTRY, MAVTRY, USD1TRY, USDCTRY, USDTTRY, UTRY, ZAMATRY).
* **Skor:** `rs` = L günlük getiri − BTCTRY L günlük getirisi (L ∈ {1,3,7} g; kesitsel sıralaması ham momentumla AYNIDIR, çünkü BTC çıkarımı sabittir) · `resid` = getiri − β·BTC getirisi (β: 7 g saatlik log-getiri betası; gerçekten farklı sıralama) · uzun geri bakış L ∈ {14,21,28} g (momentum ve dönüş).
* **Kapılar:** `breadth` = 24 sa EMA üstündeki sembol payı > 0,5 (breadth.pct_above) · `alt` = EW alt-sepet 7 g getirisi > BTCTRY 7 g getirisi (altseason benzeri; breadth.ew_index). Kapı kapalıyken nakit.
* **Tutma / yeniden denge:** 4 sa (her 4 sa), 1 g (TR gece yarısı), 3 g (3 kayık kol, 24 sa arayla; her kol 3 günde bir yeniden dengelenir, sermayenin 1/3'ü). k ∈ {5,10}, eşit ağırlık.
* **EW evren getirisi (kenar hesabında):** karar anındaki geçerli evrenin saatlik eşit-ağırlıklı ortalaması; üyelik hacim eşiğine bağlı olduğundan dinamiktir (hacim patlayan çiftler girer). Bu yüzden al-tut EW (blok başı evren, sabit) ayrıca verilir; ikisi birbirinden sapabilir (özellikle ≥50 M).
* **Konfigürasyonlar (96):** A momentum top-k · A2 beta-ayarlı kalıntı · B breadth/alt kapılı · C kısa dönüş bottom-k · D 14–28 g momentum/dönüş.
* **Yürüyen-ileri:** B2 için B1'de, B3 için B1+B2'de günlük Sharpe'ı en yüksek konfig seçilir (≥15 gün veri şartı; 14–28 g geri bakışlar B1'de veri olmadığı için yalnız B3 seçiminde yarışabilir). Seçilen konfig sonraki blokta DEĞERLENDİRİLİR; B1 yalnız eğitimdir.
* **DSR:** Bailey & López de Prado (2014); günlük net getiri serisi, çarpıklık/basıklık dâhil; deneme sayısı N=384, Sharpe varyansı konfigler arası kesitten. Testli saf kod: `rotation.deflated_sharpe`, `rotation.min_track_record`.
* **Doğrulama:** `simulate_sleeve` / `topk_weights` birim testli; ayrıca bir konfigin (A, L3, k10, 1 g) brüt getirisi bağımsız bir döngüyle yeniden hesaplandı ve tam eşleşti (−%59,73).

## Sınırlamalar (yorumu etkiler)

1. **Hayatta kalma yanlılığı:** adaylar yalnız bugün işlem gören semboller; delist olan/çöken çiftler yok. Bu yanlılık **bottom-k (dönüş) sepetini ve genel olarak long-only sonuçlarını iyimser** yapar (bugün hâlâ var olan düşenler toparlananlardır). Negatif sonuç gerçekte daha da negatif olur; pozitif görünen sonuçlar daha az güvenilirdir.
2. **Kısa örneklem / rejim:** 89 gün, 3 blok, düşüş trendi yok; piyasa yukarı gitti (long-only için kolay dönem). 2–4 hafta momentum→dönüş yapısı ancak 2–3 bağımsız pencerede ölçülebildi (28 g geri bakışta 62 kullanılabilir gün).
3. **Çakışma:** 3 g tutma kolları ve günlük bileşik getiriler otokorelasyonlu; DSR'deki 'gözlem sayısı' bağımsız gözlemden fazla → DSR iyimser.
4. **İnce defter:** TRY çiftlerinde (özellikle ≥5 M eşiğinde) gerçek spread/derinlik %0,15 kaymadan kötü olabilir; momentum sepeti pompalanmış küçük çiftleri seçer. Simülasyon last-trade `open` fiyatından 15 dk gecikmeli dolum varsayar; gerçek dolum sonuçları aşağı çeker. 'Kenar yok' sonucu bu yüzden iyimser bir üst sınırdır.
5. **RS ≡ momentum:** BTC'ye göre göreli güç kesitte ham momentumla aynı sıralamayı verir; gerçek ayrım yalnız beta-ayarlı `resid` ve kapılarla gelir. 'BTC dominansı düşerken alt seçimi' fikri `alt` kapısıyla yaklaşıldı (gerçek BTC.D yok).
6. **Fiyat gürültüsü:** saatlik getirilerin medyanı 0 (ince defterler); fiyat last-trade'tir, bid-ask sıçraması kısa ufuk getirilerini şişirir; 1 g–3 g tutmada azalır ama sıfır değildir.
7. **Blok uzunlukları:** veri 07-19 00:00 TR'de başlıyor; B1'de L=7 g için ilk 7 gün özellik yok (kullanılabilir gün sayıları tablolarda 'Gün' sütununda). B3 = 29 gün.

## Yeniden üretim

```
cd backend
DATABASE_URL=postgresql://... python scripts/rotation_study.py --stages data      # DB -> work/rotation/cache/candles15m.npz (salt-okunur)
python scripts/rotation_study.py --stages run --trials-mult 4                     # ana evren, taker  -> results.json, configs.csv
python scripts/rotation_study.py --stages run --trials-mult 4 --min-quote 50000000 --tag _likit   # likit evren -> results_likit.json
python scripts/rotation_study.py --stages run --trials-mult 4 --scenario maker --tag _maker   # (ve --min-quote 50000000 --tag _likit_maker)
python scripts/rotation_study.py --stages report                                  # -> report.md
```
