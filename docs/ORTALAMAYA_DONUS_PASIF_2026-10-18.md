# Ortalamaya dönüş + pasif (limit) icra — Binance TR TRY spot, uzun-yönlü
*Oluşturma: 2026-10-17. Çevrimdışı araştırma (canlı kod / DB yazımı / commit YOK). Veri: 2026-07-19 → 2026-10-17 (90 gün, TR günleri); bloklar B1 07-20..08-18, B2 08-19..09-17, B3 09-18..10-16.*

## Karar

**Sonuç: kenar yok — ölüm kriterini geçen yapılandırma 0/5544** (maker M0 0, M1 0, M2 0, taker 0). Net > 0 olan hücre sayısı blok başına B1 19, B2 21, B3 1 (/5544); hiçbir hücre iki blokta birden pozitif değil. Yürüyen-ileri (parametreler yalnız geçmiş bloklarla seçilerek) en iyi OOS: BD|5M / M0 (en iyimser dolum varsayımı) -0.023%/işlem (SE 0.048, n=10175) — sıfırdan ayırt edilemez ama pozitif de değil; katı dolum (M1) ile en iyisi -0.155% (BD|5M); en yüksek DSR 0.000. **Mekanizma:** (1) Sinyallerde GÖRELİ bilgi var: BD (baz-kapılı Bollinger/MFI) üç blokta da ATR'si eşleşmiş rastgele girişten ~+0,2–0,3 pp iyi, AD/CD benzer yönde; limitsiz (tetik kapanışından) 60 dk brüt sürüklenme ≥5M evrende A +0.10%, B +0.17%, C +0.08%, D +0.21%, AD +0.27%, BD +0.32%, CD +0.30% (rastgele ortalama +0.01%). (2) Ama bu sürüklenmeyi ucuz icra yakalamıyor: taker (0,525% gidiş-dönüş) maliyeti aşıyor; limit alış ise ters seçilimle sürüklenmenin büyük kısmını kaçırıyor — BD|5M'de limit %31 doluyor, dolanların 60 dk getirisi -0.06%, dolmayanlarınki +0.50% (rastgele girişte -0.26% / +0.28%: etkinin büyük kısmı mekanik, ama sinyalin ekstra getirisi dolmayanlarda birikiyor; D|5M'de dolum %34). (3) Brüt kenar maker maliyetinin (≈ 0,135% + stop/zaman çıkışı taker payı) altında kalıyor: referans yapılandırmada maker brüt çoğunlukla −0,05…−0,38% (tek istisna BD|50M M0, +0,02%). **Sınırlar:** yalnız 90 gün ve tek rejim (BTCTRY blok getirileri B1 +1,6%, B2 +20,5%, B3 +8,5%; ayı bloğu YOK) — pozitif bloklar boğa ayına denk; dolum modeli kuyruk önceliğini bilmez (M0 iyimser üst sınır, M1/M2 katı alt sınır — gerçek dolum ikisi arasında); evren ex-post 304 likit sembol (hafif sağ-kalım yanlılığı); olaylar bağımsız işlem varsayılır (eşzamanlı sermaye kısıtı / sepet modellenmedi).

## Özet tablo

YİS = yürüyen-ileri seçim: B2 parametreleri B1'den, B3'ünkiler B1+B2'den seçildi (en yüksek eğitim net ortalaması); OOS = B2+B3 birleşimi (59 gün). Net = işlem başına yüzde (ücret + kayma sonrası, yalnız DOLAN işlemler). ± gün-kümeli SE. Fark SE'si bağımsız-SE (muhafazakâr).

| Tetik|evren | Sinyal | Geçen yapılandırma (396) | YİS OOS net/işlem % — M0 (dokunma, iyimser) | YİS OOS net % — M1 (vwap-giriş) | Rastgele (aynı icra, M1) | Fark (M1 − rastgele) | DSR (M1) | YİS OOS net % — taker giriş |
|---|---|---|---|---|---|---|---|---|
| A|5M | 113.371 | 0 | -0.212 ± 0.028 (n=57084) | -0.337 ± 0.030 (n=53759) | -0.380 | +0.043 (+1.0 SE) | 0.000 | -0.322 ± 0.030 |
| A|50M | 27.866 | 0 | -0.280 ± 0.023 (n=12218) | -0.408 ± 0.016 (n=12418) | -0.441 | +0.032 (+1.5 SE) | 0.000 | -0.362 ± 0.015 |
| B|5M | 50.608 | 0 | -0.164 ± 0.050 (n=23922) | -0.288 ± 0.045 (n=16283) | -0.347 | +0.058 (+1.1 SE) | 0.000 | -0.311 ± 0.040 |
| B|50M | 9.398 | 0 | -0.120 ± 0.044 (n=3928) | -0.238 ± 0.045 (n=4758) | -0.351 | +0.112 (+2.2 SE) | 0.000 | -0.295 ± 0.039 |
| C|5M | 20.325 | 0 | -0.324 ± 0.103 (n=3904) | -0.321 ± 0.094 (n=6057) | -0.370 | +0.049 (+0.5 SE) | 0.000 | -0.384 ± 0.070 |
| C|50M | 5.532 | 0 | -0.240 ± 0.078 (n=2657) | -0.336 ± 0.086 (n=2312) | -0.420 | +0.084 (+0.8 SE) | 0.000 | -0.387 ± 0.076 |
| D|5M | 273.799 | 0 | -0.116 ± 0.029 (n=112088) | -0.287 ± 0.027 (n=61546) | -0.353 | +0.066 (+1.6 SE) | 0.000 | -0.278 ± 0.028 |
| D|50M | 67.500 | 0 | -0.205 ± 0.024 (n=34351) | -0.310 ± 0.026 (n=35277) | -0.343 | +0.033 (+0.9 SE) | 0.000 | -0.349 ± 0.026 |
| AD|5M | 55.792 | 0 | -0.069 ± 0.031 (n=23865) | -0.286 ± 0.029 (n=16794) | -0.361 | +0.075 (+1.7 SE) | 0.000 | -0.214 ± 0.033 |
| AD|50M | 12.449 | 0 | -0.191 ± 0.021 (n=6602) | -0.325 ± 0.023 (n=5711) | -0.426 | +0.101 (+3.0 SE) | 0.000 | -0.308 ± 0.026 |
| BD|5M | 25.665 | 0 | -0.023 ± 0.048 (n=10175) | -0.155 ± 0.056 (n=4317) | -0.364 | +0.209 (+3.1 SE) | 0.000 | -0.196 ± 0.044 |
| BD|50M | 4.162 | 0 | -0.048 ± 0.053 (n=689) | -0.213 ± 0.070 (n=731) | -0.361 | +0.148 (+1.8 SE) | 0.000 | -0.238 ± 0.051 |
| CD|5M | 3.481 | 0 | -0.074 ± 0.069 (n=1544) | -0.208 ± 0.078 (n=558) | -0.409 | +0.201 (+2.1 SE) | 0.000 | -0.259 ± 0.070 |
| CD|50M | 1.265 | 0 | -0.177 ± 0.076 (n=583) | -0.324 ± 0.083 (n=559) | -0.365 | +0.041 (+0.4 SE) | 0.000 | -0.319 ± 0.064 |

**Ölüm kriteri** (≥ 2/3 blokta net > 0 ∧ eşleştirilmiş rastgeleden ≥ 2 SE yüksek): 0 / 5544 hücre geçti (maker M0 0/1512, M1 0/1512, M2 0/1512, taker 0/1008). Toplam deneme (grup × yapılandırma) = 5544; DSR bu sayıya göre.

## Yöntem

**Veri.** `historical_candles` 1m/5m (önbellek `p90cache`, 304 likit sembol), `historical_trade_flow` dakika VWAP'ı, `hist_futures_metrics` (OI, OI notional) + `futures_symbol_map` (çarpan); baz = 1e4·ln(perp/spot), perp = OI notional/OI/çarpan, spot = TRY/USDTTRY; z = 24 sa (288 bar) kayan z; metrics satırı `ts_ms` 5 dk diliminin BAŞLANGICIDIR, değer ts+5 dk'da bilinir → satır ts=T, ot[i]=T olan 5 dk muma bağlanır ve karar t_dec = ot+5 dk'dır (`flow_futures.align_metric_rows`; testle doğrulandı). Yalnız okuma.

**Tetikler (önceden belirlendi, veri madenciliği yok).** Karar 5 dk kapanışında (t_dec = ot+5 dk); tetik başına sembol bazında 1 sa (12 bar) soğuma. A: 15 dk getirisi kesitte alt %10 ∧ 60 dk eşit-ağırlık piyasa getirisi ≥ 0; B: kapanış < Bollinger(20, 2) alt bant ∧ MFI14 < 20; C: yeni 24 sa dip, ≤ 3 bar içinde önceki dibin üstünde ilk kapanış; D: baz z kesitte üst %20; AD/BD/CD: A/B/C ∧ D (baz kapısı). Evren: 24 sa TRY hacmi ≥ 5M ve ≥ 50M (kesit sıralaması ve rastgele havuz o evrende); pegli çiftler (MAV, USDC, USDT, U) dışlandı.

**Giriş (pasif).** Limit alış = tetik kapanışı × (1 − d), d ∈ {0, %0,1, %0,3}; emir t_dec'te konur, V ∈ {5, 15} dk geçerli. Dolum: sonraki 1 dk barlardan ilkinde LOW ≤ limit (M0, iyimser) ya da dakika VWAP ≤ limit (M1/M2, katı; `historical_trade_flow`, işlem yoksa dolmaz). Dolum fiyatı = limit (açılış daha iyiyse bile — kötümser). Maker ücreti %0,0675, kayma yok.

**Çıkış.** Kâr al = LİMİT satış entry×(1+T), T ∈ {0,4; 0,8; 1,2}%: HIGH ≥ seviye (M0, M1) ya da VWAP ≥ seviye (M2); maker %0,0675; dolum barında değerlendirilmez. Koruyucu: stop %2/%3 (dolum barı dâhil, LOW ≤ stop; aynı barda TP+stop → stop; boşlukta açılıştan) ve zaman stopu 60/120/240 dk (dolumdan itibaren) piyasa emri: taker %0,1125 + %0,15 kayma. Kontrol: çıkış motoru `exit_sim.simulate` ile aynı sonucu verir (testte rastgele yollarla, 3 çıkış türü).

**Karşılaştırmalar.** (1) Taker: aynı sinyaller, bir sonraki dakika açılışı × 1,0015, taker %0,1125; TK1 = TP maker, TK2 = TP de piyasa. (2) ATR14(5m)'si eşleşmiş rastgele giriş: aynı sembol/blok/evren içinde olay başına 2 çekiliş (ATR sıra penceresi ±%5), aynı icra, aynı çıkış. Fark SE'si iki ortalamanın bağımsız gün-kümeli SE'lerinden (muhafazakâr).

**İstatistik.** İşlem başına net %, gün-kümeli SE (gün = TR günü; `exit_sim.cluster_se` ile aynı sayı, testli). Bloklar: B1 07-20..08-18 (30 g), B2 08-19..09-17 (30 g), B3 09-18..10-16 (29 g); 07-19 ısınma. Yürüyen-ileri: B2 ← B1, B3 ← B1+B2 (en yüksek eğitim net ortalaması, eğitimde n ≥ 100); kip (M0/M1/M2) dünya varsayımı olduğu için ayrı seçilir. Deflated Sharpe: Bailey & López de Prado, deneme = bütün hücreler.

## 1. Ölüm kriteri ayrıntısı

Hücre = (tetik × evren) × (maker 324 + taker 72) = 5544. İstatistiksel beklenti: farkın ≥ 2 SE olması tek blokta yaklaşık %2,3 (tek yön); ≥ 2/3 blokta bağımsız olsalar ≈ %0,15 → ~8 hücre şans eseri geçebilir (hücreler güçlü korele olduğundan gerçek dağılım daha geniş kuyruklu).

| İcra kipi | Hücre | ≥ 2 blokta net > 0 (rastgele şartı yok) | GEÇEN (net>0 ∧ ≥ 2 SE > rastgele, ≥ 2 blok) |
|---|---|---|---|
| M0 dokunma | 1512 | 0 | 0 |
| M1 vwap-giriş | 1512 | 0 | 0 |
| M2 vwap-giriş+çıkış | 1512 | 0 | 0 |
| taker | 1008 | 0 | 0 |

Blok başına net > 0 olan hücre sayısı: B1: 19/5544, B2: 21/5544, B3: 1/5544. BTCTRY al-tut (blok getirisi): B1 +1.6%, B2 +20.5%, B3 +8.5%.

## 2. Hindsight en iyi hücreler (betimleyici — kenar iddiası DEĞİL)

Tüm günler birleşik (n ≥ 300) net ortalamaya göre ilk 12 hücre. DSR bu hücre seçildikten SONRA, tüm ızgaraya göre indirgenmiş değerdir.

| Grup | Yapılandırma | Net % | n | Blok net B1/B2/B3 | Rastgele B1/B2/B3 | Fark | DSR |
|---|---|---|---|---|---|---|---|
| BD|5M | maker d0 V5 M0 T1.2 SL3 Z240 | -0.025 | 14530 | -0.061 / +0.070 / -0.085 | -0.310 / -0.251 / -0.311 | +0.265 (+5.5 SE) | 0.000 |
| BD|5M | maker d0 V5 M0 T0.8 SL3 Z240 | -0.028 | 14530 | -0.042 / +0.044 / -0.083 | -0.292 / -0.244 / -0.317 | +0.257 (+6.1 SE) | 0.000 |
| BD|50M | maker d0.3 V5 M0 T0.8 SL3 Z240 | -0.033 | 888 | -0.067 / +0.048 / -0.086 | -0.189 / -0.282 / -0.248 | +0.212 (+3.4 SE) | 0.000 |
| BD|50M | maker d0 V5 M0 T0.8 SL3 Z240 | -0.036 | 2698 | -0.076 / +0.006 / -0.047 | -0.307 / -0.304 / -0.300 | +0.267 (+5.7 SE) | 0.000 |
| BD|50M | maker d0 V5 M0 T1.2 SL3 Z240 | -0.038 | 2698 | -0.070 / +0.035 / -0.081 | -0.298 / -0.300 / -0.334 | +0.275 (+4.8 SE) | 0.000 |
| BD|5M | maker d0 V5 M0 T1.2 SL2 Z240 | -0.040 | 14530 | -0.074 / +0.036 / -0.082 | -0.329 / -0.274 / -0.325 | +0.269 (+6.4 SE) | 0.000 |
| BD|5M | maker d0 V5 M0 T0.8 SL2 Z240 | -0.043 | 14530 | -0.052 / +0.009 / -0.085 | -0.309 / -0.267 / -0.331 | +0.259 (+7.2 SE) | 0.000 |
| BD|50M | maker d0.3 V15 M0 T0.8 SL3 Z240 | -0.045 | 1576 | -0.047 / -0.029 / -0.057 | -0.232 / -0.324 / -0.253 | +0.227 (+4.2 SE) | 0.000 |
| BD|50M | maker d0.3 V5 M0 T0.8 SL2 Z240 | -0.045 | 888 | -0.038 / +0.023 / -0.109 | -0.218 / -0.291 / -0.231 | +0.203 (+3.8 SE) | 0.000 |
| BD|50M | maker d0.1 V5 M0 T1.2 SL3 Z240 | -0.052 | 1621 | -0.064 / +0.015 / -0.103 | -0.273 / -0.337 / -0.335 | +0.270 (+3.8 SE) | 0.000 |
| BD|50M | maker d0 V5 M0 T1.2 SL2 Z240 | -0.052 | 2698 | -0.065 / +0.004 / -0.092 | -0.316 / -0.317 / -0.306 | +0.260 (+5.2 SE) | 0.000 |
| BD|5M | maker d0 V5 M0 T1.2 SL3 Z120 | -0.060 | 14530 | -0.084 / +0.023 / -0.119 | -0.338 / -0.303 / -0.349 | +0.270 (+7.4 SE) | 0.000 |

## 3. Yürüyen-ileri ayrıntısı (seçilen yapılandırmalar)

| Grup | Kip | B2 seçimi (B1) | B3 seçimi (B1+B2) | B2 OOS net | B3 OOS net | OOS net ± SE | Rastgele OOS | n | Günlük SR | PSR | DSR |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A|5M | M0 | maker d0 V5 M0 T0.8 SL3 Z240 | maker d0 V5 M0 T0.8 SL3 Z240 | -0.203 | -0.221 | -0.212 ± 0.028 | -0.283 | 57084 | -1.119 | 0.000 | 0.000 |
| A|5M | M1 | maker d0 V15 M1 T0.8 SL3 Z240 | maker d0 V15 M1 T0.8 SL3 Z240 | -0.327 | -0.348 | -0.337 ± 0.030 | -0.380 | 53759 | -1.595 | 0.000 | 0.000 |
| A|5M | M2 | maker d0 V15 M2 T0.4 SL3 Z240 | maker d0 V15 M2 T0.4 SL3 Z240 | -0.389 | -0.414 | -0.402 ± 0.021 | -0.442 | 53759 | -2.608 | 0.000 | 0.000 |
| A|5M | taker | taker TK1 tp-high T0.8 SL3 Z240 | taker TK1 tp-high T0.8 SL3 Z240 | -0.314 | -0.328 | -0.322 ± 0.030 | -0.390 | 83475 | -1.493 | 0.000 | 0.000 |
| A|50M | M0 | maker d0.3 V15 M0 T1.2 SL2 Z240 | maker d0.3 V15 M0 T0.8 SL2 Z240 | -0.288 | -0.274 | -0.280 ± 0.023 | -0.313 | 12218 | -1.776 | 0.000 | 0.000 |
| A|50M | M1 | maker d0.1 V5 M1 T0.8 SL2 Z240 | maker d0 V5 M1 T0.4 SL2 Z240 | -0.428 | -0.396 | -0.408 ± 0.016 | -0.441 | 12418 | -3.261 | 0.000 | 0.000 |
| A|50M | M2 | maker d0 V15 M2 T0.4 SL2 Z240 | maker d0 V15 M2 T0.4 SL2 Z240 | -0.469 | -0.475 | -0.472 ± 0.014 | -0.519 | 16816 | -4.533 | 0.000 | 0.000 |
| A|50M | taker | taker TK1 tp-high T0.4 SL3 Z240 | taker TK1 tp-high T0.4 SL3 Z240 | -0.375 | -0.351 | -0.362 ± 0.015 | -0.411 | 21197 | -3.118 | 0.000 | 0.000 |
| B|5M | M0 | maker d0 V5 M0 T0.8 SL3 Z240 | maker d0 V5 M0 T1.2 SL3 Z240 | -0.095 | -0.230 | -0.164 ± 0.050 | -0.265 | 23922 | -0.287 | 0.008 | 0.000 |
| B|5M | M1 | maker d0 V15 M1 T0.4 SL3 Z240 | maker d0.3 V15 M1 T1.2 SL3 Z240 | -0.241 | -0.382 | -0.288 ± 0.045 | -0.347 | 16283 | -0.564 | 0.000 | 0.000 |
| B|5M | M2 | maker d0 V15 M2 T0.4 SL3 Z240 | maker d0.3 V15 M2 T1.2 SL3 Z240 | -0.275 | -0.428 | -0.326 ± 0.047 | -0.387 | 16283 | -0.659 | 0.000 | 0.000 |
| B|5M | taker | taker TK1 tp-high T0.4 SL3 Z240 | taker TK1 tp-high T0.8 SL3 Z240 | -0.263 | -0.357 | -0.311 ± 0.040 | -0.396 | 35333 | -0.916 | 0.000 | 0.000 |
| B|50M | M0 | maker d0.1 V15 M0 T0.8 SL3 Z240 | maker d0.3 V15 M0 T0.8 SL3 Z240 | -0.104 | -0.140 | -0.120 ± 0.044 | -0.288 | 3928 | -0.191 | 0.066 | 0.000 |
| B|50M | M1 | maker d0 V15 M1 T0.4 SL3 Z240 | maker d0 V5 M1 T0.8 SL3 Z240 | -0.239 | -0.238 | -0.238 ± 0.045 | -0.351 | 4758 | -0.647 | 0.000 | 0.000 |
| B|50M | M2 | maker d0 V15 M2 T0.4 SL2 Z240 | maker d0 V5 M2 T0.8 SL3 Z240 | -0.327 | -0.298 | -0.313 ± 0.044 | -0.415 | 4758 | -0.911 | 0.000 | 0.000 |
| B|50M | taker | taker TK1 tp-high T0.4 SL3 Z240 | taker TK1 tp-high T0.8 SL3 Z240 | -0.263 | -0.322 | -0.295 ± 0.039 | -0.397 | 7071 | -1.002 | 0.000 | 0.000 |
| C|5M | M0 | maker d0.3 V5 M0 T0.8 SL2 Z240 | maker d0.3 V5 M0 T1.2 SL3 Z240 | -0.251 | -0.381 | -0.324 ± 0.103 | -0.319 | 3904 | -0.351 | 0.001 | 0.000 |
| C|5M | M1 | maker d0.1 V5 M1 T1.2 SL3 Z240 | maker d0.1 V5 M1 T1.2 SL3 Z240 | -0.176 | -0.437 | -0.321 ± 0.094 | -0.370 | 6057 | -0.240 | 0.027 | 0.000 |
| C|5M | M2 | maker d0.1 V5 M2 T1.2 SL3 Z240 | maker d0.1 V5 M2 T1.2 SL3 Z240 | -0.229 | -0.487 | -0.372 ± 0.095 | -0.433 | 6057 | -0.338 | 0.003 | 0.000 |
| C|5M | taker | taker TK1 tp-high T0.4 SL3 Z240 | taker TK1 tp-high T1.2 SL3 Z240 | -0.277 | -0.473 | -0.384 ± 0.070 | -0.408 | 14199 | -0.584 | 0.000 | 0.000 |
| C|50M | M0 | maker d0.1 V15 M0 T0.8 SL3 Z240 | maker d0.1 V5 M0 T1.2 SL3 Z240 | -0.191 | -0.285 | -0.240 ± 0.078 | -0.332 | 2657 | -0.237 | 0.026 | 0.000 |
| C|50M | M1 | maker d0.1 V15 M1 T1.2 SL3 Z240 | maker d0.1 V5 M1 T1.2 SL3 Z240 | -0.301 | -0.370 | -0.336 ± 0.086 | -0.420 | 2312 | -0.344 | 0.004 | 0.000 |
| C|50M | M2 | maker d0.1 V5 M2 T1.2 SL3 Z240 | maker d0.1 V5 M2 T1.2 SL3 Z240 | -0.317 | -0.449 | -0.393 ± 0.095 | -0.529 | 2032 | -0.394 | 0.001 | 0.000 |
| C|50M | taker | taker TK1 tp-high T1.2 SL3 Z240 | taker TK1 tp-high T1.2 SL3 Z240 | -0.293 | -0.456 | -0.387 ± 0.076 | -0.459 | 3961 | -0.549 | 0.000 | 0.000 |
| D|5M | M0 | maker d0 V5 M0 T0.8 SL3 Z240 | maker d0 V5 M0 T0.8 SL3 Z240 | -0.102 | -0.129 | -0.116 ± 0.029 | -0.272 | 112088 | -0.516 | 0.000 | 0.000 |
| D|5M | M1 | maker d0 V5 M1 T0.4 SL3 Z240 | maker d0 V5 M1 T0.8 SL3 Z240 | -0.282 | -0.293 | -0.287 ± 0.027 | -0.353 | 61546 | -1.433 | 0.000 | 0.000 |
| D|5M | M2 | maker d0 V15 M2 T0.4 SL3 Z240 | maker d0 V15 M2 T0.4 SL3 Z240 | -0.330 | -0.356 | -0.343 ± 0.024 | -0.400 | 98637 | -1.891 | 0.000 | 0.000 |
| D|5M | taker | taker TK1 tp-high T0.4 SL3 Z240 | taker TK1 tp-high T0.8 SL3 Z240 | -0.275 | -0.282 | -0.278 ± 0.028 | -0.394 | 195306 | -1.356 | 0.000 | 0.000 |
| D|50M | M0 | maker d0 V5 M0 T0.4 SL3 Z240 | maker d0 V5 M0 T0.8 SL3 Z240 | -0.217 | -0.194 | -0.205 ± 0.024 | -0.271 | 34351 | -1.208 | 0.000 | 0.000 |
| D|50M | M1 | maker d0 V15 M1 T0.4 SL3 Z240 | maker d0 V15 M1 T0.8 SL3 Z240 | -0.316 | -0.304 | -0.310 ± 0.026 | -0.343 | 35277 | -1.677 | 0.000 | 0.000 |
| D|50M | M2 | maker d0 V15 M2 T0.4 SL2 Z240 | maker d0 V15 M2 T0.4 SL3 Z240 | -0.388 | -0.371 | -0.379 ± 0.019 | -0.414 | 35277 | -2.641 | 0.000 | 0.000 |
| D|50M | taker | taker TK1 tp-high T0.4 SL3 Z240 | taker TK1 tp-high T0.8 SL3 Z240 | -0.349 | -0.349 | -0.349 ± 0.026 | -0.392 | 51057 | -1.883 | 0.000 | 0.000 |
| AD|5M | M0 | maker d0 V5 M0 T0.8 SL3 Z240 | maker d0 V5 M0 T1.2 SL3 Z240 | -0.087 | -0.052 | -0.069 ± 0.031 | -0.265 | 23865 | -0.421 | 0.000 | 0.000 |
| AD|5M | M1 | maker d0 V15 M1 T0.8 SL3 Z240 | maker d0 V5 M1 T0.8 SL3 Z240 | -0.301 | -0.264 | -0.286 ± 0.029 | -0.361 | 16794 | -1.386 | 0.000 | 0.000 |
| AD|5M | M2 | maker d0 V15 M2 T0.4 SL3 Z240 | maker d0 V15 M2 T0.4 SL3 Z240 | -0.362 | -0.359 | -0.360 ± 0.021 | -0.431 | 20403 | -2.220 | 0.000 | 0.000 |
| AD|5M | taker | taker TK1 tp-high T0.8 SL3 Z240 | taker TK1 tp-high T1.2 SL3 Z240 | -0.226 | -0.203 | -0.214 ± 0.033 | -0.378 | 41321 | -0.941 | 0.000 | 0.000 |
| AD|50M | M0 | maker d0 V5 M0 T0.8 SL2 Z240 | maker d0 V5 M0 T0.8 SL2 Z240 | -0.206 | -0.179 | -0.191 ± 0.021 | -0.327 | 6602 | -1.253 | 0.000 | 0.000 |
| AD|50M | M1 | maker d0 V15 M1 T0.8 SL2 Z240 | maker d0 V5 M1 T0.8 SL3 Z240 | -0.369 | -0.277 | -0.325 ± 0.023 | -0.426 | 5711 | -1.714 | 0.000 | 0.000 |
| AD|50M | M2 | maker d0 V5 M2 T1.2 SL2 Z120 | maker d0 V5 M2 T0.8 SL2 Z120 | -0.458 | -0.413 | -0.433 ± 0.023 | -0.536 | 5005 | -2.311 | 0.000 | 0.000 |
| AD|50M | taker | taker TK1 tp-high T0.8 SL2 Z240 | taker TK1 tp-high T0.8 SL3 Z240 | -0.333 | -0.288 | -0.308 ± 0.026 | -0.411 | 9577 | -1.653 | 0.000 | 0.000 |
| BD|5M | M0 | maker d0 V5 M0 T0.8 SL3 Z240 | maker d0 V5 M0 T1.2 SL3 Z240 | +0.044 | -0.085 | -0.023 ± 0.048 | -0.279 | 10175 | +0.105 | 0.777 | 0.000 |
| BD|5M | M1 | maker d0 V5 M1 T0.8 SL3 Z240 | maker d0.1 V5 M1 T1.2 SL3 Z240 | -0.090 | -0.264 | -0.155 ± 0.056 | -0.364 | 4317 | -0.212 | 0.049 | 0.000 |
| BD|5M | M2 | maker d0 V5 M2 T0.8 SL3 Z240 | maker d0.1 V5 M2 T1.2 SL3 Z240 | -0.130 | -0.309 | -0.197 ± 0.057 | -0.412 | 4317 | -0.304 | 0.008 | 0.000 |
| BD|5M | taker | taker TK1 tp-high T0.8 SL3 Z240 | taker TK1 tp-high T0.8 SL3 Z240 | -0.126 | -0.263 | -0.196 ± 0.044 | -0.409 | 17723 | -0.438 | 0.000 | 0.000 |
| BD|50M | M0 | maker d0.3 V5 M0 T1.2 SL2 Z120 | maker d0.3 V5 M0 T0.8 SL3 Z240 | -0.003 | -0.086 | -0.048 ± 0.053 | -0.257 | 689 | +0.022 | 0.567 | 0.000 |
| BD|50M | M1 | maker d0.3 V5 M1 T1.2 SL2 Z120 | maker d0.1 V5 M1 T0.8 SL3 Z240 | -0.175 | -0.229 | -0.213 ± 0.070 | -0.361 | 731 | -0.336 | 0.003 | 0.000 |
| BD|50M | M2 | maker d0 V5 M2 T0.4 SL2 Z240 | maker d0.1 V5 M2 T1.2 SL3 Z240 | -0.232 | -0.283 | -0.254 ± 0.054 | -0.456 | 1217 | -0.404 | 0.002 | 0.000 |
| BD|50M | taker | taker TK1 tp-high T0.8 SL3 Z240 | taker TK1 tp-high T0.8 SL3 Z240 | -0.199 | -0.269 | -0.238 ± 0.051 | -0.423 | 3108 | -0.573 | 0.000 | 0.000 |
| CD|5M | M0 | maker d0 V5 M0 T1.2 SL3 Z240 | maker d0 V5 M0 T1.2 SL3 Z240 | -0.040 | -0.103 | -0.074 ± 0.069 | -0.285 | 1544 | +0.160 | 0.885 | 0.000 |
| CD|5M | M1 | maker d0.3 V5 M1 T0.8 SL3 Z240 | maker d0.1 V5 M1 T1.2 SL2 Z240 | -0.301 | -0.167 | -0.208 ± 0.078 | -0.409 | 558 | -0.137 | 0.125 | 0.000 |
| CD|5M | M2 | maker d0.3 V5 M2 T1.2 SL3 Z240 | maker d0.1 V5 M2 T1.2 SL2 Z240 | -0.328 | -0.239 | -0.266 ± 0.076 | -0.491 | 558 | -0.146 | 0.114 | 0.000 |
| CD|5M | taker | taker TK1 tp-high T1.2 SL3 Z240 | taker TK1 tp-high T1.2 SL3 Z240 | -0.173 | -0.327 | -0.259 ± 0.070 | -0.403 | 2471 | -0.234 | 0.041 | 0.000 |
| CD|50M | M0 | maker d0.3 V15 M0 T1.2 SL3 Z240 | maker d0 V5 M0 T1.2 SL3 Z240 | -0.471 | -0.051 | -0.177 ± 0.076 | -0.255 | 583 | -0.155 | 0.114 | 0.000 |
| CD|50M | M1 | maker d0.3 V15 M1 T1.2 SL3 Z240 | maker d0 V15 M1 T1.2 SL3 Z240 | -0.609 | -0.215 | -0.324 ± 0.083 | -0.365 | 559 | -0.366 | 0.001 | 0.000 |
| CD|50M | M2 | maker d0.3 V15 M2 T1.2 SL3 Z240 | maker d0 V15 M2 T0.8 SL3 Z240 | -0.659 | -0.308 | -0.404 ± 0.072 | -0.424 | 559 | -0.451 | 0.000 | 0.000 |
| CD|50M | taker | taker TK1 tp-high T0.8 SL3 Z240 | taker TK1 tp-high T1.2 SL3 Z240 | -0.307 | -0.326 | -0.319 ± 0.064 | -0.410 | 955 | -0.307 | 0.008 | 0.000 |

SR varyansı (günlük, tüm hücreler, OOS günleri) = 1.521e+00; deneme sayısı = 5544. Günlük seri: günün işlem başına ortalama neti (işlemsiz gün = 0) — gerçek portföy getirisi değil, sinyal başına kazanç vekili.

## 4. Referans yapılandırma (V=15, d=%0,1, T=%0,8, SL=%3, zaman 120 dk) — icra duyarlılığı

Tüm günler birleşik (gün 1–89). Brüt = ücretsiz getiri (dolum/kayma modeli dâhil), TP/SL = çıkış payları. TK1 = piyasa girişi (+%0,15 kayma, taker) + TP maker; TK2 = TK1 ama TP de piyasa (taker + kayma). 'Rastgele' = ATR eşleşmiş rastgele giriş, aynı icra.

| Grup | İcra | Net % | n (dolan) | Brüt % | Rastgele net % | Blok net B1/B2/B3 | TP / SL payı |
|---|---|---|---|---|---|---|---|
| A|5M | maker M0 dokunma | -0.347 ± 0.018 | 60834 | -0.192 | -0.368 | -0.352 / -0.342 / -0.350 | 53% / 9% |
| A|5M | maker M1 vwap-giriş | -0.409 ± 0.018 | 56505 | -0.253 | -0.426 | -0.424 / -0.401 / -0.407 | 51% / 10% |
| A|5M | maker M2 vwap-giriş+çıkış | -0.471 ± 0.018 | 56505 | -0.313 | -0.483 | -0.501 / -0.455 / -0.466 | 48% / 11% |
| A|5M | taker giriş TK1 | -0.368 ± 0.017 | 113371 | -0.166 | -0.434 | -0.371 / -0.366 / -0.368 | 49% / 7% |
| A|5M | taker her bacak TK2 | -0.464 ± 0.016 | 113371 | -0.240 | -0.526 | -0.464 / -0.463 / -0.466 | 49% / 7% |
| A|50M | maker M0 dokunma | -0.317 ± 0.016 | 20891 | -0.166 | -0.362 | -0.309 / -0.330 / -0.310 | 64% / 15% |
| A|50M | maker M1 vwap-giriş | -0.426 ± 0.017 | 19005 | -0.275 | -0.470 | -0.439 / -0.438 / -0.410 | 61% / 17% |
| A|50M | maker M2 vwap-giriş+çıkış | -0.534 ± 0.019 | 19005 | -0.380 | -0.577 | -0.573 / -0.527 / -0.517 | 57% / 19% |
| A|50M | taker giriş TK1 | -0.398 ± 0.017 | 27866 | -0.201 | -0.448 | -0.390 / -0.399 / -0.401 | 61% / 14% |
| A|50M | taker her bacak TK2 | -0.518 ± 0.016 | 27866 | -0.294 | -0.565 | -0.514 / -0.519 / -0.518 | 61% / 14% |
| B|5M | maker M0 dokunma | -0.294 ± 0.032 | 24445 | -0.136 | -0.376 | -0.314 / -0.217 / -0.353 | 47% / 7% |
| B|5M | maker M1 vwap-giriş | -0.339 ± 0.034 | 22641 | -0.180 | -0.407 | -0.358 / -0.260 / -0.400 | 45% / 8% |
| B|5M | maker M2 vwap-giriş+çıkış | -0.369 ± 0.035 | 22641 | -0.209 | -0.439 | -0.390 / -0.286 / -0.434 | 43% / 8% |
| B|5M | taker giriş TK1 | -0.339 ± 0.025 | 50608 | -0.133 | -0.444 | -0.349 / -0.278 / -0.388 | 41% / 5% |
| B|5M | taker her bacak TK2 | -0.420 ± 0.025 | 50608 | -0.195 | -0.515 | -0.416 / -0.365 / -0.475 | 41% / 5% |
| B|50M | maker M0 dokunma | -0.197 ± 0.032 | 6177 | -0.044 | -0.340 | -0.237 / -0.147 / -0.216 | 59% / 10% |
| B|50M | maker M1 vwap-giriş | -0.284 ± 0.036 | 5512 | -0.129 | -0.406 | -0.330 / -0.239 / -0.293 | 56% / 11% |
| B|50M | maker M2 vwap-giriş+çıkış | -0.340 ± 0.037 | 5512 | -0.184 | -0.468 | -0.392 / -0.291 / -0.350 | 53% / 12% |
| B|50M | taker giriş TK1 | -0.319 ± 0.027 | 9398 | -0.118 | -0.443 | -0.370 / -0.263 / -0.334 | 52% / 9% |
| B|50M | taker her bacak TK2 | -0.421 ± 0.026 | 9398 | -0.197 | -0.536 | -0.460 / -0.371 / -0.440 | 52% / 9% |
| C|5M | maker M0 dokunma | -0.301 ± 0.047 | 13159 | -0.144 | -0.357 | -0.278 / -0.185 / -0.413 | 50% / 9% |
| C|5M | maker M1 vwap-giriş | -0.354 ± 0.049 | 12241 | -0.196 | -0.407 | -0.319 / -0.246 / -0.466 | 48% / 10% |
| C|5M | maker M2 vwap-giriş+çıkış | -0.401 ± 0.050 | 12241 | -0.242 | -0.453 | -0.364 / -0.296 / -0.513 | 45% / 10% |
| C|5M | taker giriş TK1 | -0.411 ± 0.040 | 20325 | -0.206 | -0.445 | -0.421 / -0.287 / -0.505 | 44% / 8% |
| C|5M | taker her bacak TK2 | -0.496 ± 0.039 | 20325 | -0.272 | -0.529 | -0.491 / -0.384 / -0.593 | 44% / 8% |
| C|50M | maker M0 dokunma | -0.266 ± 0.047 | 4208 | -0.113 | -0.336 | -0.231 / -0.214 / -0.329 | 59% / 12% |
| C|50M | maker M1 vwap-giriş | -0.349 ± 0.050 | 3811 | -0.194 | -0.417 | -0.299 / -0.318 / -0.406 | 56% / 13% |
| C|50M | maker M2 vwap-giriş+çıkış | -0.427 ± 0.050 | 3811 | -0.271 | -0.499 | -0.389 / -0.396 / -0.476 | 52% / 14% |
| C|50M | taker giriş TK1 | -0.405 ± 0.042 | 5532 | -0.205 | -0.457 | -0.403 / -0.330 / -0.462 | 53% / 11% |
| C|50M | taker her bacak TK2 | -0.508 ± 0.041 | 5532 | -0.284 | -0.557 | -0.501 / -0.436 / -0.566 | 53% / 11% |
| D|5M | maker M0 dokunma | -0.301 ± 0.018 | 102749 | -0.144 | -0.361 | -0.299 / -0.293 / -0.309 | 50% / 7% |
| D|5M | maker M1 vwap-giriş | -0.357 ± 0.018 | 93742 | -0.199 | -0.401 | -0.353 / -0.349 / -0.366 | 48% / 8% |
| D|5M | maker M2 vwap-giriş+çıkış | -0.405 ± 0.019 | 93742 | -0.246 | -0.444 | -0.404 / -0.396 / -0.414 | 45% / 9% |
| D|5M | taker giriş TK1 | -0.313 ± 0.016 | 273799 | -0.109 | -0.444 | -0.328 / -0.301 / -0.312 | 45% / 5% |
| D|5M | taker her bacak TK2 | -0.401 ± 0.015 | 273799 | -0.176 | -0.521 | -0.403 / -0.393 / -0.406 | 45% / 5% |
| D|50M | maker M0 dokunma | -0.275 ± 0.017 | 39789 | -0.121 | -0.320 | -0.290 / -0.277 / -0.264 | 58% / 11% |
| D|50M | maker M1 vwap-giriş | -0.363 ± 0.017 | 35759 | -0.209 | -0.394 | -0.388 / -0.364 / -0.348 | 55% / 12% |
| D|50M | maker M2 vwap-giriş+çıkış | -0.438 ± 0.018 | 35759 | -0.283 | -0.467 | -0.480 / -0.433 / -0.419 | 52% / 13% |
| D|50M | taker giriş TK1 | -0.377 ± 0.016 | 67500 | -0.176 | -0.436 | -0.395 / -0.367 / -0.376 | 52% / 9% |
| D|50M | taker her bacak TK2 | -0.479 ± 0.015 | 67500 | -0.255 | -0.533 | -0.491 / -0.470 / -0.479 | 52% / 9% |
| AD|5M | maker M0 dokunma | -0.303 ± 0.019 | 21942 | -0.149 | -0.363 | -0.296 / -0.312 / -0.298 | 57% / 10% |
| AD|5M | maker M1 vwap-giriş | -0.384 ± 0.019 | 19857 | -0.229 | -0.421 | -0.386 / -0.391 / -0.376 | 54% / 11% |
| AD|5M | maker M2 vwap-giriş+çıkış | -0.447 ± 0.020 | 19857 | -0.291 | -0.478 | -0.464 / -0.451 / -0.433 | 51% / 12% |
| AD|5M | taker giriş TK1 | -0.261 ± 0.017 | 55792 | -0.061 | -0.428 | -0.262 / -0.265 / -0.256 | 54% / 6% |
| AD|5M | taker her bacak TK2 | -0.366 ± 0.016 | 55792 | -0.142 | -0.520 | -0.363 / -0.371 / -0.364 | 54% / 6% |
| AD|50M | maker M0 dokunma | -0.261 ± 0.021 | 8070 | -0.112 | -0.350 | -0.266 / -0.271 / -0.251 | 67% / 14% |
| AD|50M | maker M1 vwap-giriş | -0.390 ± 0.023 | 7193 | -0.239 | -0.460 | -0.401 / -0.399 / -0.377 | 63% / 17% |
| AD|50M | maker M2 vwap-giriş+çıkış | -0.494 ± 0.025 | 7193 | -0.342 | -0.564 | -0.557 / -0.487 / -0.467 | 59% / 19% |
| AD|50M | taker giriş TK1 | -0.323 ± 0.020 | 12449 | -0.127 | -0.448 | -0.300 / -0.334 / -0.326 | 64% / 13% |
| AD|50M | taker her bacak TK2 | -0.448 ± 0.019 | 12449 | -0.224 | -0.566 | -0.431 / -0.459 / -0.448 | 64% / 13% |
| BD|5M | maker M0 dokunma | -0.203 ± 0.035 | 8866 | -0.047 | -0.388 | -0.220 / -0.106 / -0.282 | 52% / 7% |
| BD|5M | maker M1 vwap-giriş | -0.255 ± 0.038 | 7967 | -0.098 | -0.422 | -0.266 / -0.154 / -0.342 | 50% / 8% |
| BD|5M | maker M2 vwap-giriş+çıkış | -0.291 ± 0.039 | 7967 | -0.133 | -0.456 | -0.304 / -0.193 / -0.373 | 48% / 8% |
| BD|5M | taker giriş TK1 | -0.233 ± 0.026 | 25665 | -0.029 | -0.448 | -0.240 / -0.168 / -0.289 | 46% / 4% |
| BD|5M | taker her bacak TK2 | -0.324 ± 0.025 | 25665 | -0.099 | -0.521 | -0.316 / -0.266 / -0.387 | 46% / 4% |
| BD|50M | maker M0 dokunma | -0.130 ± 0.036 | 2337 | +0.022 | -0.337 | -0.117 / -0.091 / -0.170 | 62% / 9% |
| BD|50M | maker M1 vwap-giriş | -0.216 ± 0.040 | 2041 | -0.063 | -0.400 | -0.205 / -0.180 / -0.253 | 60% / 11% |
| BD|50M | maker M2 vwap-giriş+çıkış | -0.270 ± 0.041 | 2041 | -0.116 | -0.470 | -0.257 / -0.248 / -0.296 | 57% / 12% |
| BD|50M | taker giriş TK1 | -0.268 ± 0.033 | 4162 | -0.068 | -0.447 | -0.240 / -0.239 / -0.309 | 55% / 8% |
| BD|50M | taker her bacak TK2 | -0.376 ± 0.032 | 4162 | -0.152 | -0.543 | -0.341 / -0.351 / -0.417 | 55% / 8% |
| CD|5M | maker M0 dokunma | -0.206 ± 0.048 | 1706 | -0.053 | -0.388 | -0.222 / -0.145 / -0.243 | 58% / 10% |
| CD|5M | maker M1 vwap-giriş | -0.286 ± 0.053 | 1531 | -0.131 | -0.456 | -0.296 / -0.231 / -0.321 | 56% / 11% |
| CD|5M | maker M2 vwap-giriş+çıkış | -0.346 ± 0.054 | 1531 | -0.190 | -0.501 | -0.349 / -0.293 / -0.384 | 53% / 11% |
| CD|5M | taker giriş TK1 | -0.307 ± 0.035 | 3481 | -0.105 | -0.458 | -0.284 / -0.221 / -0.392 | 50% / 8% |
| CD|5M | taker her bacak TK2 | -0.405 ± 0.034 | 3481 | -0.180 | -0.547 | -0.370 / -0.327 / -0.492 | 50% / 8% |
| CD|50M | maker M0 dokunma | -0.231 ± 0.059 | 848 | -0.080 | -0.292 | -0.176 / -0.300 / -0.216 | 63% / 12% |
| CD|50M | maker M1 vwap-giriş | -0.323 ± 0.066 | 758 | -0.171 | -0.360 | -0.250 / -0.425 / -0.299 | 60% / 14% |
| CD|50M | maker M2 vwap-giriş+çıkış | -0.404 ± 0.065 | 758 | -0.250 | -0.450 | -0.307 / -0.522 / -0.384 | 56% / 15% |
| CD|50M | taker giriş TK1 | -0.393 ± 0.043 | 1265 | -0.194 | -0.415 | -0.378 / -0.381 / -0.410 | 54% / 12% |
| CD|50M | taker her bacak TK2 | -0.500 ± 0.041 | 1265 | -0.276 | -0.522 | -0.481 / -0.490 / -0.517 | 54% / 12% |

## 5. Dolum oranı ve ters seçilim (V=15, d=%0,1)

Getiri: tetik kapanışından (P0) emir bitişine kadar (rV: 15. dk kapanışı) ve 60 dk sonrasına (r60), %. 'Dolan' = limit dolanlar, 'dolmayan' = emir süresi bitenler. Ters seçilim: dolanlar, fiyat düşmeye devam eden olaylardır (rV, r60 dolanlarda dolmayanlardan düşük).

| Grup | Kip | Dolum (sinyal) | Dolum (rastgele) | rV dolan | rV dolmayan | r60 dolan | r60 dolmayan | r60 tüm sinyaller ± SE | Rastgele r60 tüm | Rastgele r60 dolan | Rastgele r60 dolmayan |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A|5M | M0 | 54% | 62% | -0.206 | +0.435 | -0.209 | +0.449 | +0.096 ± 0.014 | +0.020 | -0.211 | +0.395 |
| A|5M | M1 | 50% | 58% | -0.268 | +0.448 | -0.266 | +0.457 | +0.096 ± 0.014 | +0.020 | -0.265 | +0.417 |
| A|50M | M0 | 75% | 79% | -0.176 | +0.764 | -0.236 | +0.740 | +0.008 ± 0.021 | -0.056 | -0.262 | +0.733 |
| A|50M | M1 | 68% | 73% | -0.291 | +0.811 | -0.348 | +0.772 | +0.008 ± 0.021 | -0.056 | -0.358 | +0.764 |
| B|5M | M0 | 48% | 53% | -0.214 | +0.349 | -0.093 | +0.417 | +0.170 ± 0.019 | +0.014 | -0.215 | +0.267 |
| B|5M | M1 | 45% | 50% | -0.266 | +0.355 | -0.141 | +0.422 | +0.170 ± 0.019 | +0.014 | -0.243 | +0.267 |
| B|50M | M0 | 66% | 70% | -0.141 | +0.531 | -0.022 | +0.565 | +0.179 ± 0.029 | +0.024 | -0.171 | +0.472 |
| B|50M | M1 | 59% | 64% | -0.238 | +0.552 | -0.109 | +0.589 | +0.179 ± 0.029 | +0.024 | -0.235 | +0.489 |
| C|5M | M0 | 65% | 64% | -0.209 | +0.410 | -0.115 | +0.442 | +0.082 ± 0.028 | +0.019 | -0.194 | +0.401 |
| C|5M | M1 | 60% | 60% | -0.262 | +0.421 | -0.166 | +0.456 | +0.082 ± 0.028 | +0.019 | -0.235 | +0.401 |
| C|50M | M0 | 76% | 75% | -0.166 | +0.568 | -0.071 | +0.576 | +0.084 ± 0.035 | -0.005 | -0.203 | +0.577 |
| C|50M | M1 | 69% | 69% | -0.259 | +0.605 | -0.168 | +0.642 | +0.084 ± 0.035 | -0.005 | -0.284 | +0.606 |
| D|5M | M0 | 38% | 57% | -0.187 | +0.401 | -0.144 | +0.421 | +0.209 ± 0.012 | +0.018 | -0.204 | +0.314 |
| D|5M | M1 | 34% | 54% | -0.245 | +0.402 | -0.200 | +0.422 | +0.209 ± 0.012 | +0.018 | -0.243 | +0.321 |
| D|50M | M0 | 59% | 72% | -0.166 | +0.545 | -0.136 | +0.528 | +0.137 ± 0.016 | +0.008 | -0.179 | +0.476 |
| D|50M | M1 | 53% | 66% | -0.261 | +0.562 | -0.230 | +0.550 | +0.137 ± 0.016 | +0.008 | -0.250 | +0.505 |
| AD|5M | M0 | 39% | 61% | -0.186 | +0.516 | -0.160 | +0.544 | +0.267 ± 0.017 | +0.026 | -0.207 | +0.397 |
| AD|5M | M1 | 36% | 58% | -0.265 | +0.519 | -0.240 | +0.548 | +0.267 ± 0.017 | +0.026 | -0.262 | +0.417 |
| AD|50M | M0 | 65% | 79% | -0.161 | +0.766 | -0.166 | +0.758 | +0.159 ± 0.028 | -0.011 | -0.206 | +0.732 |
| AD|50M | M1 | 58% | 73% | -0.295 | +0.794 | -0.309 | +0.799 | +0.159 ± 0.028 | -0.011 | -0.317 | +0.808 |
| BD|5M | M0 | 35% | 53% | -0.163 | +0.426 | -0.002 | +0.496 | +0.324 ± 0.019 | +0.005 | -0.233 | +0.275 |
| BD|5M | M1 | 31% | 50% | -0.232 | +0.427 | -0.056 | +0.496 | +0.324 ± 0.019 | +0.005 | -0.264 | +0.279 |
| BD|50M | M0 | 56% | 71% | -0.108 | +0.588 | +0.019 | +0.610 | +0.278 ± 0.035 | -0.032 | -0.207 | +0.397 |
| BD|50M | M1 | 49% | 65% | -0.199 | +0.579 | -0.041 | +0.585 | +0.278 ± 0.035 | -0.032 | -0.255 | +0.389 |
| CD|5M | M0 | 49% | 67% | -0.112 | +0.530 | +0.037 | +0.546 | +0.296 ± 0.036 | -0.027 | -0.225 | +0.375 |
| CD|5M | M1 | 44% | 62% | -0.198 | +0.540 | -0.044 | +0.563 | +0.296 ± 0.036 | -0.027 | -0.282 | +0.391 |
| CD|50M | M0 | 67% | 76% | -0.094 | +0.659 | -0.011 | +0.604 | +0.192 ± 0.072 | +0.031 | -0.188 | +0.743 |
| CD|50M | M1 | 60% | 70% | -0.206 | +0.693 | -0.108 | +0.640 | +0.192 ± 0.072 | +0.031 | -0.290 | +0.770 |

## 6. Sertlik, d ve V duyarlılığı (referans çıkış; tüm 14 grup işlem-ağırlıklı)

| Kip | d | V (dk) | Dolum oranı | Net % (sinyal) | Net % (rastgele) | n dolan |
|---|---|---|---|---|---|---|
| M0 dokunma | %0 | 5 | 63% | -0.193 | -0.322 | 423.331 |
| M0 dokunma | %0 | 15 | 74% | -0.214 | -0.331 | 493.366 |
| M0 dokunma | %0.1 | 5 | 30% | -0.289 | -0.355 | 200.459 |
| M0 dokunma | %0.1 | 15 | 47% | -0.299 | -0.359 | 316.021 |
| M0 dokunma | %0.3 | 5 | 16% | -0.265 | -0.318 | 107.162 |
| M0 dokunma | %0.3 | 15 | 31% | -0.267 | -0.317 | 208.114 |
| M1 vwap-giriş | %0 | 5 | 41% | -0.338 | -0.408 | 273.497 |
| M1 vwap-giriş | %0 | 15 | 58% | -0.340 | -0.409 | 391.550 |
| M1 vwap-giriş | %0.1 | 5 | 25% | -0.371 | -0.419 | 168.054 |
| M1 vwap-giriş | %0.1 | 15 | 43% | -0.368 | -0.413 | 288.563 |
| M1 vwap-giriş | %0.3 | 5 | 12% | -0.407 | -0.418 | 82.570 |
| M1 vwap-giriş | %0.3 | 15 | 27% | -0.368 | -0.394 | 182.254 |
| M2 vwap-giriş+çıkış | %0 | 5 | 41% | -0.396 | -0.461 | 273.497 |
| M2 vwap-giriş+çıkış | %0 | 15 | 58% | -0.392 | -0.459 | 391.550 |
| M2 vwap-giriş+çıkış | %0.1 | 5 | 25% | -0.442 | -0.483 | 168.054 |
| M2 vwap-giriş+çıkış | %0.1 | 15 | 43% | -0.427 | -0.468 | 288.563 |
| M2 vwap-giriş+çıkış | %0.3 | 5 | 12% | -0.492 | -0.494 | 82.570 |
| M2 vwap-giriş+çıkış | %0.3 | 15 | 27% | -0.436 | -0.456 | 182.254 |

## 7. Sınırlar ve dürüstlük notları

* **Yalnız 90 gün, tek rejim.** BTCTRY blok getirileri: B1 +1.6%, B2 +20.5%, B3 +8.5%; ayı bloğu yok. Sonuçlar boğa/yatay rejimine koşulludur; ayı rejiminde ortalamaya dönüş (düşen bıçak) çok daha kötü olabilir.
* **Dolum modeli kaba.** M0 (dokunma = dolum) kuyruk önceliğini yok sayar → iyimser; M1/M2 (dakika VWAP'ı) gerçek dolumdan daha az dolum verir → katı. Gerçek dolum oranı arada. Dolum fiyatı limit (kötümser); emir defteri / spread modellenmedi (bid vekili = tetik kapanışı).
* **Ters seçilim doğrudan ölçüldü** (Bölüm 5) ve zaten net sonuca işlenmiş durumda: aynı icra rastgele girişlere de uygulandığı için "dolum = düşüş" etkisi hem sinyalde hem rastgelede var; fark sinyal bilgisidir.
* **Olaylar bağımsız işlem varsayılır**; eşzamanlı pozisyon sınırı, sermaye kısıtı ve sepet birleşimi yok. Günlük Sharpe "işlem başına ortalama net" vekilidir.
* **Evren yanlılığı:** 1m verisi, 90 günde yeterince likit kalan 304 sembol için var (önceden hesaplanmış `liquid.json`); gün içi 24 sa hacim filtresi nedenseldir ama sembol listesi ex-post (hafif sağ-kalım yanlılığı).
* **Çoklu test:** 5544 hücre (7 tetik × 2 evren × (324 maker + 72 taker)); bunların ek olarak seçim sırasında yürüyen-ileri ile daraltılması DSR'a işlendi. Hindsight en iyi hücrenin DSR'ı 0.000.
* **Brüt kenar:** referans tablosunda brüt getiri (ücretsiz, dolum/kayma dâhil) çoğu hücrede NEGATİF; yani sorun yalnız ücret değil: limit dolumunun kendisi (ters seçilim, dolum sonrası negatif sürüklenme ≈ −0,1%) ve koruyucu çıkış kayması brüt değeri eritiyor. Maker ücret avantajı (≈ 0,39 pp/gidiş-dönüş) bunu kapatmaya yetmiyor.
* **Dolum sonrası sürüklenme:** rastgele girişlerde bile dolanların 60 dk getirisi, dolum fiyatı hesaba katıldığında negatif (≈ −0,1%); bu bir dolum-mekaniği/mikroyapı etkisidir (düşüşe dokunan limitler düşüş sürerken dolar) ve eşleştirilmiş rastgele ile karşılaştırma bunu ayıklar.
