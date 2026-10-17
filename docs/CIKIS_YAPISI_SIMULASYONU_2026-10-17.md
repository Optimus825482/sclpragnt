# Çıkış Yapısı Çalışması — gerçekçi doluşla (gecikme + kayma) çıkış sinyali kârlı yapar mı? (2026-10-17)

Bu rapor `backend/scripts/exit_sim_study.py` tarafından üretilmiştir (simülatör: `app/rescan/exit_sim.py`, testli: `tests/test_exit_sim.py`). Çalışma çevrimdışıdır; canlı koda bağlanmaz.
## 0. Özet ve karar
- Senaryo 60 sn / %0.15 — 90 günde sinyal ortalaması: HA: net>0 hücre 0/60, en iyi 90 gün neti -0.51 (`trail act0.5 gap0.8 SL3 T30`); E: net>0 hücre 0/60, en iyi 90 gün neti -0.45 (`fixed TP1.5 SL3 T60`); G: net>0 hücre 0/60, en iyi 90 gün neti -0.32 (`fixed TP1.5 SL3 T60`).
- Senaryo 0 sn / %0.05 — 90 günde sinyal ortalaması: HA: net>0 hücre 0/60, en iyi 90 gün neti -0.32 (`trail act0.5 gap0.8 SL3 T30`); E: net>0 hücre 0/60, en iyi 90 gün neti -0.25 (`trail act0.5 gap0.4 SL3 T120`); G: net>0 hücre 0/60, en iyi 90 gün neti -0.14 (`fixed TPcand SL1.5 T60`).
- Aynı çıkışlı rastgele girişlerde (birincil senaryo) ortalama net -0.53: yani sinyal yokken bile kayıp ≈ maliyet tabanı (ücret 0,225 + kayma; kaymalı bacaklar için ≈ 0,3'e kadar).
- HA brüt sürüklenme (ücretsiz, çıkış kuralsız): +60 dk ortalama -0.156% (t -5.3), rastgele -0.004%, oynaklık-eşl. +0.006%; +120 dk -0.284% — sinyalden sonra fiyat ORTALAMA OLARAK DÜŞÜYOR (medyan -0.37%). Hız Avcısı'nın 'şansın +4–6 pp üstü' isabeti büyük olasılıkla yüksek dağılımdan (sağ kuyruk) geliyor, yönlü kazançtan değil; ızgaradaki hiçbir uzun-yön çıkış yapısı bu negatif sürüklenmeyi kâra çeviremedi.
- G (tek desen B|all|G, 71 desenden sonradan seçilmiş) +60 dk sürüklenme +0.214% (t +3.1; oynaklık-eşl. rastgele +0.059%); bloklara göre B1 -0.084%, B2 +0.299%, B3 +0.364% — tutarsız; ortalama kenar maliyet tabanının (ücret 0,225 + kayma) altında kalıyor.
- Walk-forward (birincil senaryo, 12 kaynak×seçim×OOS satırı): OOS ortalaması > 0: 0; OOS net %95 alt sınırı > 0: 0; ayrıca aynı çıkışlı rastgele girişi anlamlı geçen: 0.
- **Karar: HAYIR.** Gerçekçi doluşla (60 sn gecikme + %0,15 kayma + %0,1125/bacak ücret) hiçbir çıkış yapısı, hiçbir kaynakta (HA, E, G) örneklem dışında net-pozitif değil; iyimser doluşta (0 sn / %0,05) bile 90 günlük en iyi hücre negatif. Walk-forward OOS satırlarında sinyal−rastgele (aynı çıkış) farkı: HA -0.08…+0.03; E +0.04…+0.05; G +0.14…+0.28 (E/G sonradan seçilmiş desenler → iyimser) — HA'da çıkış yapısı sinyale değer katmıyor; E/G'de rastgeleye göre küçük bir üstünlük var ama net-pozitife yetmiyor. Ortak sorun: brüt kenar (≈ 0 / negatif sürüklenme, G'de küçük pozitif) maliyet tabanının altında.


## 1. Yöntem
- **Soru:** Dört önceki çalışma (docs/DOGRULAMA_90G_2026-10-17.md, docs/CIKIS_DESEN_ANALIZI_90G_2026-10-17.md) Hız Avcısı'nın (HA) sinyalinin gerçek olduğunu (şansın +4–6 pp üstünde) ama sabit TP / SL −3 / maliyet 0,225 ve **iyimser doluşla** (sinyal fiyatından giriş, gecikme yok, kayma yok) her yapılandırmada net negatif olduğunu gösterdi. Burada **çıkış yapısı** gerçekçi doluşla ölçülür.
- **Giriş:** sinyal anı + gecikme (0 / 60 / 120 sn) sonrasındaki ilk 1 dk barın AÇILIŞI × (1 + kayma %0,05 / %0,15). Yüzdeler (TP, SL, tetik, iz) dolan giriş fiyatına göredir. Bacak başına ücret %0,1125 (iki bacak). Birincil senaryo: **60 sn / %0,15** (gerçekçi); iyimser 0 sn / %0,05; kötümser 120 sn / %0,15.
- **Çıkış (1 dk yolunda, kötümser bar-içi sıra):** bir barda önce STOP kontrolü (önceki barlardan gelen seviye), sonra TP, en son en-yüksek (HWM) güncellemesi; yeni izleyen stop bir sonraki bardan geçerli. Stop doluşu min(stop, bar açılışı) × (1 − kayma) (boşluk → açılıştan); TP doluşu tam TP fiyatı (pozitif kayma yok); zaman stopu son barın kapanışı × (1 − kayma). Aynı barda stop ve TP görülürse stop kazanır.
- **Izgara (60 hücre):** (a) sabit TP {aday hedefi, 1,5} × SL {1,5; 3} × zaman {30, 60, 120} dk = 12; (b) izleyen stop: tetik {0,5; 1,0; 1,5} × iz {0,4; 0,8; 1,2} × SL {1,5; 3} (60 dk) + SL 3 için 30 / 120 dk = 36; (c) ATR-izleyen: iz = k × ATR14(5m)% , k {1; 1,5; 2}, tetik 1,0, SL {1,5; 3}, 60 dk = 6; (d) başabaş (+%0,6'da stop = giriş) × TP {aday, 1,5} × SL {1,5; 3} = 4; (e) başabaş+izleyen (tetik 1,0, iz 0,8) × SL {1,5; 3} = 2. Zaman stopu tüm hücrelerde var. Aday hedefi E/G desenlerinde yok → yedek %4,0 (HA'da aday `target_pct`).
- **Sinyal kümeleri (90 gün, üç 30 günlük blok: B1 20 Tem–18 Ağu, B2 19 Ağu–17 Eyl, B3 18 Eyl–16 Eki, İstanbul günü):** **HA** = rescan canlı-benzeri alt küme (rank ≤ 10, aşırı alımda değil, bağımsız 60 dk bölümler; `work/rescan_90g_nogate.jsonl`). **E / G** = 'oynak dip' desen aileleri (`work/pattern90/patterns.json`, sinyaller `work/pattern90/sig/*.npz`; E: 6 desen, hepsi ≤ 163 sinyal/gün; G: yalnız B|all|G, 110 sinyal/gün — diğer dört G deseni günde 500–1 800 sinyal verdiği için 'seçici' değil, hariç); her desen yalnız **kendi test aralığında** (eğitim penceresi dışı, yani örneklem dışı) alınır, desenler arası (sembol, 60 dk) tekilleştirilir. Karar anı = 5 dk barın kapanışı.
- **Rastgele-giriş tabanı (aynı çıkışlar):** her sinyal için aynı sembol, aynı blok, aynı İstanbul saati diliminde, herhangi bir sinyalden (HA'nın TÜM satırları + E/G sinyalleri) ≥ 2 sa uzak, 2 rastgele 5 dk-hizalı an (kind=rnd). Ek olarak **oynaklığı eşleşmiş** taban (kind=rndv): aynı sembol/blok, ≥ 2 sa uzak, son 30 dk yüksek-düşük aralığı ±%25 (en az 0,4 pt) içinde (en az 8 aday yoksa atlanır). Fark = sinyal ortalaması − taban ortalaması. Rastgele girişte aday hedefi, eşleştiği sinyalinkini miras alır.
- **İstatistik:** ortalama net %'si; t ve %95 aralık **gün-kümeli** standart hata ile (aynı gün içindeki işlemler ilişkili); fark SE'si iki grubun SE'lerinin karekökü (muhafazakâr). Kazanç/kayıp = kazanan/kaybeden işlemlerin ortalaması. Çıkış payları: TP / SL / iz / başabaş / zaman (%).
- **Walk-forward:** en iyi hücre eğitim bloğunda (n ≥ 100, ortalama net) seçilir, sonraki bloklarda DOKUNULMADAN ölçülür.

## 2. Örneklem
| kaynak | tür | B1 | B2 | B3 | toplam |
|---|---|---|---|---|---|
| HA | sinyal | 6110 | 6797 | 7436 | 20343 |
| HA | rastgele | 12220 | 13496 | 14872 | 40588 |
| HA | rastgele (oynaklık eşl.) | 9152 | 11632 | 12550 | 33334 |
| E | sinyal | 4201 | 5757 | 5399 | 15357 |
| E | rastgele | 8402 | 11370 | 10798 | 30570 |
| E | rastgele (oynaklık eşl.) | 5066 | 8714 | 8264 | 22044 |
| G | sinyal | 1912 | 3268 | 1952 | 7132 |
| G | rastgele | 3824 | 6474 | 3904 | 14202 |
| G | rastgele (oynaklık eşl.) | 2214 | 4706 | 2796 | 9716 |

Giriş sapması (dolan bar açılışı / sinyal fiyatı − 1, yüzde; ortalama / medyan; yalnız fiyatı olan sinyaller): HA 0 sn: -0.017 / +0.000; HA 60 sn: -0.037 / +0.000; HA 120 sn: -0.041 / +0.000

## 3. Izgara geneli (birincil senaryo 60 sn / %0.15)
| kaynak | blok | hücre sayısı | net>0 hücre | ortalama hücre neti | en iyi hücre neti (iç-örneklem) | rastgele ort. (aynı hücreler) | sinyal−rastgele ort. |
|---|---|---|---|---|---|---|---|
| HA | B1 | 60 | 0 | -0.55 | -0.52 | -0.56 | +0.01 |
| HA | B2 | 60 | 0 | -0.53 | -0.48 | -0.52 | -0.00 |
| HA | B3 | 60 | 0 | -0.55 | -0.51 | -0.51 | -0.04 |
| HA | 90 gün | 60 | 0 | -0.54 | -0.51 | -0.53 | -0.01 |
| E | B1 | 60 | 0 | -0.49 | -0.45 | -0.57 | +0.08 |
| E | B2 | 60 | 0 | -0.48 | -0.43 | -0.51 | +0.04 |
| E | B3 | 60 | 0 | -0.49 | -0.44 | -0.52 | +0.03 |
| E | 90 gün | 60 | 0 | -0.48 | -0.45 | -0.53 | +0.05 |
| G | B1 | 60 | 0 | -0.47 | -0.42 | -0.58 | +0.11 |
| G | B2 | 60 | 0 | -0.41 | -0.33 | -0.50 | +0.10 |
| G | B3 | 60 | 0 | -0.28 | -0.19 | -0.51 | +0.23 |
| G | 90 gün | 60 | 0 | -0.39 | -0.32 | -0.53 | +0.14 |

### 3b. Brüt sürüklenme (ücret, kayma, çıkış kuralı YOK; giriş = 60 sn gecikmeli bar açılışı; ortalama % [medyan]; t = gün-kümeli)

| kaynak | blok | tür | +5 dk | +15 dk | +30 dk | +60 dk | +120 dk |
|---|---|---|---|---|---|---|---|
| HA | B1 | sinyal | -0.025 (t -1.4) [+0.000] | -0.078 (t -2.1) [-0.091] | -0.087 (t -2.3) [-0.197] | -0.180 (t -3.1) [-0.382] | -0.356 (t -3.4) [-0.648] |
| HA | B1 | rastgele | -0.006 (t -2.2) [+0.000] | -0.002 (t -0.4) [+0.000] | -0.017 (t -2.0) [+0.000] | -0.028 (t -2.4) [+0.000] | -0.022 (t -1.2) [+0.000] |
| HA | B1 | rastgele-oyn. | -0.014 (t -2.6) [+0.000] | -0.032 (t -3.0) [+0.000] | -0.064 (t -4.5) [+0.000] | -0.089 (t -4.3) [+0.000] | -0.101 (t -3.4) [-0.089] |
| HA | B2 | sinyal | -0.008 (t -0.6) [+0.000] | -0.015 (t -0.6) [-0.010] | -0.063 (t -1.9) [-0.160] | -0.110 (t -2.4) [-0.280] | -0.269 (t -3.9) [-0.526] |
| HA | B2 | rastgele | +0.003 (t +1.1) [+0.000] | -0.005 (t -0.7) [+0.000] | -0.005 (t -0.5) [+0.000] | +0.001 (t +0.1) [+0.000] | +0.051 (t +1.3) [+0.000] |
| HA | B2 | rastgele-oyn. | +0.006 (t +0.6) [+0.000] | +0.021 (t +0.9) [+0.000] | +0.048 (t +1.7) [+0.000] | +0.078 (t +2.4) [+0.000] | +0.066 (t +1.1) [+0.000] |
| HA | B3 | sinyal | -0.011 (t -1.0) [+0.000] | -0.041 (t -1.8) [-0.103] | -0.094 (t -2.6) [-0.266] | -0.178 (t -3.6) [-0.419] | -0.238 (t -3.0) [-0.641] |
| HA | B3 | rastgele | +0.004 (t +1.1) [+0.000] | +0.003 (t +0.3) [+0.000] | +0.008 (t +0.7) [+0.000] | +0.012 (t +0.6) [+0.000] | +0.050 (t +1.2) [+0.000] |
| HA | B3 | rastgele-oyn. | +0.008 (t +0.9) [+0.000] | +0.012 (t +0.6) [+0.000] | +0.015 (t +0.5) [+0.000] | +0.008 (t +0.2) [+0.000] | -0.024 (t -0.3) [+0.000] |
| HA | 90 gün | sinyal | -0.015 (t -1.7) [+0.000] | -0.044 (t -2.6) [-0.073] | -0.082 (t -3.9) [-0.206] | -0.156 (t -5.3) [-0.370] | -0.284 (t -5.8) [-0.614] |
| HA | 90 gün | rastgele | +0.001 (t +0.3) [+0.000] | -0.001 (t -0.3) [+0.000] | -0.004 (t -0.6) [+0.000] | -0.004 (t -0.3) [+0.000] | +0.028 (t +1.3) [+0.000] |
| HA | 90 gün | rastgele-oyn. | +0.001 (t +0.2) [+0.000] | +0.003 (t +0.3) [+0.000] | +0.005 (t +0.3) [+0.000] | +0.006 (t +0.3) [+0.000] | -0.014 (t -0.4) [+0.000] |
| E | B1 | sinyal | +0.029 (t +1.1) [+0.000] | -0.028 (t -0.6) [+0.000] | -0.127 (t -2.0) [+0.000] | -0.219 (t -2.9) [-0.252] | -0.398 (t -2.8) [-0.546] |
| E | B1 | rastgele | -0.009 (t -2.8) [+0.000] | -0.016 (t -2.9) [+0.000] | -0.029 (t -3.4) [+0.000] | -0.047 (t -3.4) [+0.000] | -0.055 (t -2.3) [+0.000] |
| E | B1 | rastgele-oyn. | -0.024 (t -2.8) [+0.000] | -0.062 (t -4.3) [+0.000] | -0.092 (t -4.5) [+0.000] | -0.133 (t -4.2) [-0.096] | -0.123 (t -2.5) [-0.153] |
| E | B2 | sinyal | +0.087 (t +1.4) [+0.000] | +0.135 (t +1.7) [+0.000] | +0.109 (t +1.6) [+0.000] | +0.091 (t +1.0) [+0.000] | -0.001 (t -0.0) [-0.036] |
| E | B2 | rastgele | +0.008 (t +1.9) [+0.000] | +0.017 (t +1.8) [+0.000] | +0.002 (t +0.2) [+0.000] | +0.013 (t +0.6) [+0.000] | +0.068 (t +1.6) [+0.000] |
| E | B2 | rastgele-oyn. | +0.003 (t +0.2) [+0.000] | +0.005 (t +0.2) [+0.000] | +0.021 (t +0.7) [+0.000] | +0.086 (t +2.4) [+0.000] | +0.116 (t +1.8) [+0.000] |
| E | B3 | sinyal | +0.027 (t +1.0) [+0.000] | +0.066 (t +1.7) [+0.000] | +0.017 (t +0.3) [+0.000] | +0.040 (t +0.7) [-0.061] | +0.051 (t +0.5) [-0.256] |
| E | B3 | rastgele | -0.002 (t -0.5) [+0.000] | -0.001 (t -0.1) [+0.000] | +0.005 (t +0.4) [+0.000] | +0.005 (t +0.2) [+0.000] | +0.038 (t +0.9) [+0.000] |
| E | B3 | rastgele-oyn. | +0.007 (t +0.8) [+0.000] | +0.018 (t +0.9) [+0.000] | +0.022 (t +0.7) [+0.000] | -0.000 (t -0.0) [+0.000] | -0.021 (t -0.3) [-0.013] |
| E | 90 gün | sinyal | +0.050 (t +1.8) [+0.000] | +0.066 (t +1.8) [+0.000] | +0.012 (t +0.3) [+0.000] | -0.012 (t -0.2) [+0.000] | -0.091 (t -1.2) [-0.257] |
| E | 90 gün | rastgele | +0.000 (t +0.0) [+0.000] | +0.002 (t +0.3) [+0.000] | -0.005 (t -0.8) [+0.000] | -0.006 (t -0.5) [+0.000] | +0.024 (t +1.0) [+0.000] |
| E | 90 gün | rastgele-oyn. | -0.002 (t -0.4) [+0.000] | -0.006 (t -0.4) [+0.000] | -0.004 (t -0.2) [+0.000] | +0.003 (t +0.1) [+0.000] | +0.010 (t +0.2) [+0.000] |
| G | B1 | sinyal | +0.041 (t +1.1) [+0.000] | +0.048 (t +0.9) [+0.000] | -0.086 (t -1.1) [+0.000] | -0.084 (t -0.7) [+0.000] | -0.215 (t -1.0) [-0.290] |
| G | B1 | rastgele | -0.004 (t -0.8) [+0.000] | +0.003 (t +0.3) [+0.000] | -0.008 (t -0.6) [+0.000] | -0.048 (t -2.7) [+0.000] | -0.047 (t -1.5) [+0.000] |
| G | B1 | rastgele-oyn. | +0.001 (t +0.1) [+0.000] | -0.030 (t -1.5) [+0.000] | -0.087 (t -2.7) [+0.000] | -0.123 (t -2.7) [-0.051] | -0.091 (t -1.5) [+0.000] |
| G | B2 | sinyal | +0.168 (t +2.2) [+0.014] | +0.161 (t +1.7) [+0.085] | +0.226 (t +2.6) [+0.215] | +0.299 (t +3.1) [+0.372] | +0.328 (t +2.3) [+0.242] |
| G | B2 | rastgele | +0.001 (t +0.3) [+0.000] | +0.011 (t +1.1) [+0.000] | +0.015 (t +1.2) [+0.000] | +0.019 (t +0.9) [+0.000] | +0.092 (t +2.4) [+0.000] |
| G | B2 | rastgele-oyn. | +0.009 (t +0.9) [+0.000] | +0.036 (t +1.4) [+0.000] | +0.062 (t +1.6) [+0.000] | +0.157 (t +4.4) [+0.094] | +0.165 (t +2.4) [+0.060] |
| G | B3 | sinyal | +0.053 (t +1.4) [+0.000] | +0.145 (t +2.6) [+0.176] | +0.267 (t +3.9) [+0.282] | +0.364 (t +3.6) [+0.363] | +0.403 (t +2.5) [+0.134] |
| G | B3 | rastgele | -0.007 (t -1.2) [+0.000] | +0.003 (t +0.3) [+0.000] | -0.002 (t -0.1) [+0.000] | +0.000 (t +0.0) [+0.000] | +0.049 (t +0.9) [+0.000] |
| G | B3 | rastgele-oyn. | +0.020 (t +1.8) [+0.000] | +0.051 (t +1.7) [+0.000] | +0.050 (t +1.1) [+0.000] | +0.039 (t +0.7) [+0.000] | +0.004 (t +0.0) [+0.000] |
| G | 90 gün | sinyal | +0.102 (t +2.4) [+0.000] | +0.126 (t +2.5) [+0.050] | +0.153 (t +2.8) [+0.161] | +0.214 (t +3.1) [+0.226] | +0.203 (t +1.9) [+0.000] |
| G | 90 gün | rastgele | -0.002 (t -0.8) [+0.000] | +0.007 (t +1.1) [+0.000] | +0.004 (t +0.5) [+0.000] | -0.004 (t -0.3) [+0.000] | +0.043 (t +1.7) [+0.000] |
| G | 90 gün | rastgele-oyn. | +0.010 (t +1.5) [+0.000] | +0.025 (t +1.6) [+0.000] | +0.025 (t +1.0) [+0.000] | +0.059 (t +2.1) [+0.000] | +0.060 (t +1.2) [+0.000] |

Fark (sinyal − rastgele) ortalama sürüklenme, 90 gün:

| kaynak | +5 dk | +15 dk | +30 dk | +60 dk | +120 dk |
|---|---|---|---|---|---|
| HA | rastgele -0.015 ±0.017; oyn. -0.016 ±0.019 | rastgele -0.042 ±0.034; oyn. -0.047 ±0.041 | rastgele -0.078 ±0.043; oyn. -0.087 ±0.053 | rastgele -0.152 ±0.061; oyn. -0.162 ±0.072 | rastgele -0.312 ±0.105; oyn. -0.270 ±0.122 |
| E | rastgele +0.050 ±0.055; oyn. +0.052 ±0.056 | rastgele +0.064 ±0.074; oyn. +0.072 ±0.078 | rastgele +0.018 ±0.078; oyn. +0.017 ±0.085 | rastgele -0.005 ±0.098; oyn. -0.015 ±0.106 | rastgele -0.115 ±0.154; oyn. -0.101 ±0.168 |
| G | rastgele +0.105 ±0.082; oyn. +0.092 ±0.083 | rastgele +0.120 ±0.099; oyn. +0.101 ±0.103 | rastgele +0.149 ±0.107; oyn. +0.129 ±0.117 | rastgele +0.218 ±0.137; oyn. +0.155 ±0.145 | rastgele +0.160 ±0.212; oyn. +0.142 ±0.227 |

## 4. Aile bazında en iyi hücreler — blok tabloları (birincil senaryo; **iç-örneklem**: hücre 90 günün tamamında ortalama neti en yüksek olandan seçildi, yani iyimser)
Sütunlar: n | net ort. % | t (gün-kümeli) | kazanma % | ort. kazanç/kayıp | çıkış payı TP/SL/iz/başabaş/zaman %.

### HA

**sabit TP/SL — fixed TP1.5 SL1.5 T30**

| blok | tür | n | net ort. | t | kazanma % | kazanç/kayıp | çıkış payı |
|---|---|---|---|---|---|---|---|
| B1 | sinyal | 6110 | -0.55 | -27.9 | 36.8 | +1.13/-1.52 | 31 / 41 / 0 / 0 / 28 |
| B1 | rastgele | 12220 | -0.55 | -63.9 | 16.5 | +0.55/-0.77 | 4 / 6 / 0 / 0 / 90 |
| B1 | rastgele-oynaklık | 9152 | -0.59 | -36.2 | 23.1 | +0.67/-0.97 | 8 / 14 / 0 / 0 / 78 |
| B1 | **fark: sinyal−rastgele** | | +0.00 [-0.04; +0.05] | | | | |
| B1 | **fark: sinyal−rastgele(oynaklık)** | | +0.04 [-0.01; +0.09] | | | | |
| B2 | sinyal | 6797 | -0.50 | -31.6 | 37.7 | +1.08/-1.45 | 30 / 37 / 0 / 0 / 33 |
| B2 | rastgele | 13496 | -0.53 | -45.3 | 18.2 | +0.51/-0.76 | 4 / 6 / 0 / 0 / 90 |
| B2 | rastgele-oynaklık | 11632 | -0.50 | -17.3 | 28.6 | +0.68/-0.97 | 10 / 14 / 0 / 0 / 77 |
| B2 | **fark: sinyal−rastgele** | | +0.03 [-0.00; +0.07] | | | | |
| B2 | **fark: sinyal−rastgele(oynaklık)** | | +0.00 [-0.06; +0.07] | | | | |
| B3 | sinyal | 7436 | -0.52 | -28.9 | 37.8 | +1.10/-1.51 | 31 / 39 / 0 / 0 / 30 |
| B3 | rastgele | 14872 | -0.51 | -43.7 | 19.6 | +0.53/-0.77 | 4 / 6 / 0 / 0 / 90 |
| B3 | rastgele-oynaklık | 12550 | -0.51 | -18.1 | 27.7 | +0.66/-0.95 | 9 / 14 / 0 / 0 / 77 |
| B3 | **fark: sinyal−rastgele** | | -0.01 [-0.05; +0.03] | | | | |
| B3 | **fark: sinyal−rastgele(oynaklık)** | | -0.01 [-0.08; +0.05] | | | | |
| 90 gün | sinyal | 20343 | -0.52 | -49.4 | 37.5 | +1.11/-1.49 | 30 / 39 / 0 / 0 / 31 |
| 90 gün | rastgele | 40588 | -0.53 | -80.8 | 18.2 | +0.53/-0.77 | 4 / 6 / 0 / 0 / 90 |
| 90 gün | rastgele-oynaklık | 33334 | -0.53 | -33.2 | 26.8 | +0.67/-0.96 | 9 / 14 / 0 / 0 / 77 |
| 90 gün | **fark: sinyal−rastgele** | | +0.01 [-0.01; +0.03] | | | | |
| 90 gün | **fark: sinyal−rastgele(oynaklık)** | | +0.01 [-0.03; +0.04] | | | | |

**izleyen stop — trail act0.5 gap0.8 SL3 T30**

| blok | tür | n | net ort. | t | kazanma % | kazanç/kayıp | çıkış payı |
|---|---|---|---|---|---|---|---|
| B1 | sinyal | 6110 | -0.52 | -28.5 | 30.8 | +1.03/-1.21 | 0 / 10 / 58 / 0 / 32 |
| B1 | rastgele | 12220 | -0.54 | -67.0 | 15.5 | +0.48/-0.73 | 0 / 0 / 9 / 0 / 91 |
| B1 | rastgele-oynaklık | 9152 | -0.58 | -41.6 | 20.7 | +0.55/-0.87 | 0 / 1 / 20 / 0 / 79 |
| B1 | **fark: sinyal−rastgele** | | +0.02 [-0.02; +0.06] | | | | |
| B1 | **fark: sinyal−rastgele(oynaklık)** | | +0.06 [+0.01; +0.10] | | | | |
| B2 | sinyal | 6797 | -0.50 | -30.9 | 31.4 | +0.94/-1.15 | 0 / 8 / 56 / 0 / 36 |
| B2 | rastgele | 13496 | -0.53 | -47.5 | 17.1 | +0.47/-0.74 | 0 / 0 / 9 / 0 / 91 |
| B2 | rastgele-oynaklık | 11632 | -0.48 | -17.6 | 26.1 | +0.59/-0.86 | 0 / 1 / 20 / 0 / 79 |
| B2 | **fark: sinyal−rastgele** | | +0.03 [-0.01; +0.07] | | | | |
| B2 | **fark: sinyal−rastgele(oynaklık)** | | -0.01 [-0.08; +0.05] | | | | |
| B3 | sinyal | 7436 | -0.52 | -28.2 | 32.5 | +1.00/-1.25 | 0 / 9 / 55 / 0 / 36 |
| B3 | rastgele | 14872 | -0.52 | -47.3 | 18.5 | +0.47/-0.74 | 0 / 0 / 8 / 0 / 91 |
| B3 | rastgele-oynaklık | 12550 | -0.51 | -18.3 | 25.0 | +0.57/-0.87 | 0 / 1 / 21 / 0 / 79 |
| B3 | **fark: sinyal−rastgele** | | -0.00 [-0.04; +0.04] | | | | |
| B3 | **fark: sinyal−rastgele(oynaklık)** | | -0.01 [-0.08; +0.05] | | | | |
| 90 gün | sinyal | 20343 | -0.51 | -49.7 | 31.6 | +0.99/-1.20 | 0 / 9 / 56 / 0 / 35 |
| 90 gün | rastgele | 40588 | -0.53 | -87.1 | 17.1 | +0.47/-0.74 | 0 / 0 / 9 / 0 / 91 |
| 90 gün | rastgele-oynaklık | 33334 | -0.52 | -33.9 | 24.2 | +0.57/-0.87 | 0 / 1 / 20 / 0 / 79 |
| 90 gün | **fark: sinyal−rastgele** | | +0.02 [-0.01; +0.04] | | | | |
| 90 gün | **fark: sinyal−rastgele(oynaklık)** | | +0.01 [-0.03; +0.04] | | | | |

**ATR-izleyen — atr k1 act1 SL1.5 T60**

| blok | tür | n | net ort. | t | kazanma % | kazanç/kayıp | çıkış payı |
|---|---|---|---|---|---|---|---|
| B1 | sinyal | 6110 | -0.57 | -24.9 | 33.1 | +1.34/-1.52 | 0 / 44 / 43 / 0 / 12 |
| B1 | rastgele | 12220 | -0.58 | -51.3 | 24.5 | +0.54/-0.94 | 0 / 13 / 15 / 0 / 72 |
| B1 | rastgele-oynaklık | 9152 | -0.65 | -36.4 | 28.7 | +0.62/-1.16 | 0 / 24 / 22 / 0 / 54 |
| B1 | **fark: sinyal−rastgele** | | +0.00 [-0.05; +0.05] | | | | |
| B1 | **fark: sinyal−rastgele(oynaklık)** | | +0.08 [+0.02; +0.13] | | | | |
| B2 | sinyal | 6797 | -0.54 | -25.4 | 34.8 | +1.16/-1.45 | 0 / 42 / 44 / 0 / 14 |
| B2 | rastgele | 13496 | -0.53 | -29.1 | 27.4 | +0.56/-0.94 | 0 / 14 / 16 / 0 / 70 |
| B2 | rastgele-oynaklık | 11632 | -0.50 | -16.0 | 37.1 | +0.65/-1.18 | 0 / 23 / 26 / 0 / 51 |
| B2 | **fark: sinyal−rastgele** | | -0.01 [-0.06; +0.05] | | | | |
| B2 | **fark: sinyal−rastgele(oynaklık)** | | -0.04 [-0.11; +0.04] | | | | |
| B3 | sinyal | 7436 | -0.53 | -23.2 | 34.9 | +1.25/-1.49 | 0 / 44 / 44 / 0 / 12 |
| B3 | rastgele | 14872 | -0.53 | -30.1 | 28.5 | +0.55/-0.96 | 0 / 14 / 17 / 0 / 69 |
| B3 | rastgele-oynaklık | 12550 | -0.55 | -15.4 | 34.9 | +0.65/-1.19 | 0 / 25 / 25 / 0 / 50 |
| B3 | **fark: sinyal−rastgele** | | -0.01 [-0.06; +0.05] | | | | |
| B3 | **fark: sinyal−rastgele(oynaklık)** | | +0.01 [-0.07; +0.10] | | | | |
| 90 gün | sinyal | 20343 | -0.55 | -41.6 | 34.3 | +1.25/-1.48 | 0 / 43 / 44 / 0 / 13 |
| 90 gün | rastgele | 40588 | -0.54 | -55.9 | 26.9 | +0.55/-0.95 | 0 / 14 / 16 / 0 / 70 |
| 90 gün | rastgele-oynaklık | 33334 | -0.56 | -29.2 | 34.0 | +0.64/-1.18 | 0 / 24 / 24 / 0 / 51 |
| 90 gün | **fark: sinyal−rastgele** | | -0.00 [-0.04; +0.03] | | | | |
| 90 gün | **fark: sinyal−rastgele(oynaklık)** | | +0.01 [-0.03; +0.06] | | | | |

**başabaş — be0.6 TP1.5 SL1.5 T60**

| blok | tür | n | net ort. | t | kazanma % | kazanç/kayıp | çıkış payı |
|---|---|---|---|---|---|---|---|
| B1 | sinyal | 6110 | -0.56 | -33.7 | 27.2 | +1.22/-1.22 | 26 / 36 / 0 / 30 / 8 |
| B1 | rastgele | 12220 | -0.56 | -47.6 | 20.2 | +0.72/-0.88 | 8 / 12 / 0 / 12 / 67 |
| B1 | rastgele-oynaklık | 9152 | -0.62 | -33.6 | 21.9 | +0.89/-1.04 | 13 / 22 / 0 / 22 / 43 |
| B1 | **fark: sinyal−rastgele** | | -0.00 [-0.04; +0.04] | | | | |
| B1 | **fark: sinyal−rastgele(oynaklık)** | | +0.06 [+0.01; +0.11] | | | | |
| B2 | sinyal | 6797 | -0.51 | -29.0 | 28.2 | +1.22/-1.18 | 27 / 35 / 0 / 30 / 9 |
| B2 | rastgele | 13496 | -0.53 | -28.6 | 22.5 | +0.70/-0.88 | 9 / 13 / 0 / 12 / 66 |
| B2 | rastgele-oynaklık | 11632 | -0.48 | -15.2 | 29.1 | +0.88/-1.05 | 16 / 22 / 0 / 20 / 42 |
| B2 | **fark: sinyal−rastgele** | | +0.02 [-0.03; +0.07] | | | | |
| B2 | **fark: sinyal−rastgele(oynaklık)** | | -0.02 [-0.09; +0.05] | | | | |
| B3 | sinyal | 7436 | -0.51 | -31.9 | 29.4 | +1.22/-1.23 | 28 / 36 / 0 / 28 / 8 |
| B3 | rastgele | 14872 | -0.51 | -28.7 | 23.8 | +0.73/-0.90 | 9 / 13 / 0 / 12 / 65 |
| B3 | rastgele-oynaklık | 12550 | -0.52 | -17.2 | 26.7 | +0.91/-1.04 | 15 / 23 / 0 / 22 / 40 |
| B3 | **fark: sinyal−rastgele** | | -0.00 [-0.05; +0.04] | | | | |
| B3 | **fark: sinyal−rastgele(oynaklık)** | | +0.01 [-0.06; +0.08] | | | | |
| 90 gün | sinyal | 20343 | -0.52 | -52.0 | 28.4 | +1.22/-1.21 | 27 / 36 / 0 / 29 / 8 |
| 90 gün | rastgele | 40588 | -0.53 | -53.8 | 22.3 | +0.72/-0.89 | 9 / 13 / 0 / 12 / 66 |
| 90 gün | rastgele-oynaklık | 33334 | -0.53 | -30.1 | 26.2 | +0.89/-1.04 | 15 / 22 / 0 / 21 / 42 |
| 90 gün | **fark: sinyal−rastgele** | | +0.01 [-0.02; +0.03] | | | | |
| 90 gün | **fark: sinyal−rastgele(oynaklık)** | | +0.01 [-0.03; +0.05] | | | | |

### E

**sabit TP/SL — fixed TP1.5 SL3 T60**

| blok | tür | n | net ort. | t | kazanma % | kazanç/kayıp | çıkış payı |
|---|---|---|---|---|---|---|---|
| B1 | sinyal | 4201 | -0.45 | -14.0 | 52.9 | +1.20/-2.31 | 48 / 23 / 0 / 0 / 29 |
| B1 | rastgele | 8402 | -0.54 | -37.6 | 22.9 | +0.71/-0.91 | 9 / 1 / 0 / 0 / 90 |
| B1 | rastgele-oynaklık | 5066 | -0.59 | -17.2 | 27.3 | +0.89/-1.14 | 15 / 2 / 0 / 0 / 83 |
| B1 | **fark: sinyal−rastgele** | | +0.09 [+0.02; +0.16] | | | | |
| B1 | **fark: sinyal−rastgele(oynaklık)** | | +0.14 [+0.04; +0.23] | | | | |
| B2 | sinyal | 5757 | -0.44 | -11.6 | 51.2 | +1.16/-2.13 | 45 / 21 / 0 / 0 / 34 |
| B2 | rastgele | 11370 | -0.49 | -24.1 | 26.1 | +0.70/-0.91 | 10 / 1 / 0 / 0 / 89 |
| B2 | rastgele-oynaklık | 8714 | -0.42 | -12.5 | 36.4 | +0.88/-1.16 | 20 / 3 / 0 / 0 / 77 |
| B2 | **fark: sinyal−rastgele** | | +0.04 [-0.04; +0.13] | | | | |
| B2 | **fark: sinyal−rastgele(oynaklık)** | | -0.03 [-0.13; +0.07] | | | | |
| B3 | sinyal | 5399 | -0.44 | -11.6 | 50.1 | +1.16/-2.05 | 44 / 19 / 0 / 0 / 37 |
| B3 | rastgele | 10798 | -0.50 | -22.1 | 27.3 | +0.74/-0.96 | 11 / 1 / 0 / 0 / 88 |
| B3 | rastgele-oynaklık | 8264 | -0.47 | -13.8 | 33.9 | +0.88/-1.16 | 19 / 3 / 0 / 0 / 79 |
| B3 | **fark: sinyal−rastgele** | | +0.05 [-0.03; +0.14] | | | | |
| B3 | **fark: sinyal−rastgele(oynaklık)** | | +0.03 [-0.07; +0.13] | | | | |
| 90 gün | sinyal | 15357 | -0.45 | -20.7 | 51.3 | +1.17/-2.15 | 45 / 21 / 0 / 0 / 34 |
| 90 gün | rastgele | 30570 | -0.50 | -42.7 | 25.7 | +0.72/-0.93 | 10 / 1 / 0 / 0 / 89 |
| 90 gün | rastgele-oynaklık | 22044 | -0.48 | -22.4 | 33.4 | +0.88/-1.16 | 18 / 3 / 0 / 0 / 79 |
| 90 gün | **fark: sinyal−rastgele** | | +0.06 [+0.01; +0.11] | | | | |
| 90 gün | **fark: sinyal−rastgele(oynaklık)** | | +0.03 [-0.03; +0.09] | | | | |

**izleyen stop — trail act0.5 gap0.4 SL3 T60**

| blok | tür | n | net ort. | t | kazanma % | kazanç/kayıp | çıkış payı |
|---|---|---|---|---|---|---|---|
| B1 | sinyal | 4201 | -0.45 | -17.0 | 40.8 | +0.73/-1.27 | 0 / 14 / 74 / 0 / 12 |
| B1 | rastgele | 8402 | -0.55 | -41.8 | 21.4 | +0.47/-0.82 | 0 / 1 / 30 / 0 / 69 |
| B1 | rastgele-oynaklık | 5066 | -0.59 | -27.3 | 25.9 | +0.48/-0.96 | 0 / 2 / 46 / 0 / 52 |
| B1 | **fark: sinyal−rastgele** | | +0.09 [+0.04; +0.15] | | | | |
| B1 | **fark: sinyal−rastgele(oynaklık)** | | +0.14 [+0.07; +0.20] | | | | |
| B2 | sinyal | 5757 | -0.46 | -13.9 | 40.4 | +0.68/-1.24 | 0 / 14 / 72 / 0 / 14 |
| B2 | rastgele | 11370 | -0.50 | -30.4 | 24.3 | +0.48/-0.81 | 0 / 1 / 31 / 0 / 68 |
| B2 | rastgele-oynaklık | 8714 | -0.45 | -16.0 | 32.4 | +0.56/-0.94 | 0 / 3 / 48 / 0 / 49 |
| B2 | **fark: sinyal−rastgele** | | +0.04 [-0.03; +0.11] | | | | |
| B2 | **fark: sinyal−rastgele(oynaklık)** | | -0.01 [-0.09; +0.08] | | | | |
| B3 | sinyal | 5399 | -0.46 | -16.0 | 40.0 | +0.64/-1.20 | 0 / 12 / 72 / 0 / 16 |
| B3 | rastgele | 10798 | -0.52 | -29.4 | 24.9 | +0.49/-0.85 | 0 / 1 / 34 / 0 / 64 |
| B3 | rastgele-oynaklık | 8264 | -0.51 | -17.2 | 29.9 | +0.50/-0.94 | 0 / 2 / 50 / 0 / 48 |
| B3 | **fark: sinyal−rastgele** | | +0.05 [-0.01; +0.12] | | | | |
| B3 | **fark: sinyal−rastgele(oynaklık)** | | +0.05 [-0.03; +0.13] | | | | |
| 90 gün | sinyal | 15357 | -0.46 | -26.0 | 40.4 | +0.68/-1.23 | 0 / 13 / 73 / 0 / 14 |
| 90 gün | rastgele | 30570 | -0.52 | -53.9 | 23.7 | +0.48/-0.83 | 0 / 1 / 32 / 0 / 67 |
| 90 gün | rastgele-oynaklık | 22044 | -0.51 | -28.7 | 30.0 | +0.52/-0.95 | 0 / 3 / 48 / 0 / 49 |
| 90 gün | **fark: sinyal−rastgele** | | +0.06 [+0.02; +0.10] | | | | |
| 90 gün | **fark: sinyal−rastgele(oynaklık)** | | +0.05 [-0.00; +0.10] | | | | |

**ATR-izleyen — atr k1 act1 SL3 T60**

| blok | tür | n | net ort. | t | kazanma % | kazanç/kayıp | çıkış payı |
|---|---|---|---|---|---|---|---|
| B1 | sinyal | 4201 | -0.52 | -14.8 | 35.9 | +1.71/-1.77 | 0 / 20 / 55 / 0 / 25 |
| B1 | rastgele | 8402 | -0.56 | -38.3 | 24.8 | +0.52/-0.91 | 0 / 1 / 16 / 0 / 83 |
| B1 | rastgele-oynaklık | 5066 | -0.64 | -22.8 | 28.3 | +0.60/-1.12 | 0 / 2 / 24 / 0 / 74 |
| B1 | **fark: sinyal−rastgele** | | +0.04 [-0.04; +0.11] | | | | |
| B1 | **fark: sinyal−rastgele(oynaklık)** | | +0.12 [+0.03; +0.20] | | | | |
| B2 | sinyal | 5757 | -0.48 | -12.1 | 39.8 | +1.33/-1.68 | 0 / 18 / 50 / 0 / 32 |
| B2 | rastgele | 11370 | -0.51 | -25.8 | 27.4 | +0.55/-0.90 | 0 / 1 / 17 / 0 / 82 |
| B2 | rastgele-oynaklık | 8714 | -0.46 | -14.0 | 37.4 | +0.67/-1.13 | 0 / 3 / 27 / 0 / 70 |
| B2 | **fark: sinyal−rastgele** | | +0.02 [-0.06; +0.11] | | | | |
| B2 | **fark: sinyal−rastgele(oynaklık)** | | -0.03 [-0.13; +0.08] | | | | |
| B3 | sinyal | 5399 | -0.50 | -12.5 | 38.0 | +1.37/-1.64 | 0 / 17 / 49 / 0 / 34 |
| B3 | rastgele | 10798 | -0.52 | -25.2 | 29.1 | +0.56/-0.96 | 0 / 1 / 18 / 0 / 81 |
| B3 | rastgele-oynaklık | 8264 | -0.51 | -15.4 | 35.3 | +0.64/-1.15 | 0 / 3 / 25 / 0 / 73 |
| B3 | **fark: sinyal−rastgele** | | +0.02 [-0.07; +0.11] | | | | |
| B3 | **fark: sinyal−rastgele(oynaklık)** | | +0.02 [-0.09; +0.12] | | | | |
| 90 gün | sinyal | 15357 | -0.50 | -22.0 | 38.1 | +1.44/-1.69 | 0 / 18 / 51 / 0 / 31 |
| 90 gün | rastgele | 30570 | -0.53 | -46.7 | 27.3 | +0.55/-0.93 | 0 / 1 / 17 / 0 / 82 |
| 90 gün | rastgele-oynaklık | 22044 | -0.52 | -25.3 | 34.5 | +0.65/-1.13 | 0 / 3 / 25 / 0 / 72 |
| 90 gün | **fark: sinyal−rastgele** | | +0.03 [-0.02; +0.08] | | | | |
| 90 gün | **fark: sinyal−rastgele(oynaklık)** | | +0.02 [-0.04; +0.08] | | | | |

**başabaş — be0.6 TP1.5 SL3 T60**

| blok | tür | n | net ort. | t | kazanma % | kazanç/kayıp | çıkış payı |
|---|---|---|---|---|---|---|---|
| B1 | sinyal | 4201 | -0.46 | -15.0 | 33.9 | +1.22/-1.32 | 32 / 15 / 0 / 38 / 15 |
| B1 | rastgele | 8402 | -0.55 | -39.5 | 19.3 | +0.72/-0.86 | 8 / 1 / 0 / 13 / 78 |
| B1 | rastgele-oynaklık | 5066 | -0.59 | -19.5 | 20.9 | +0.93/-1.00 | 13 / 2 / 0 / 24 / 61 |
| B1 | **fark: sinyal−rastgele** | | +0.09 [+0.03; +0.16] | | | | |
| B1 | **fark: sinyal−rastgele(oynaklık)** | | +0.14 [+0.05; +0.22] | | | | |
| B2 | sinyal | 5757 | -0.44 | -12.9 | 35.0 | +1.18/-1.31 | 31 / 15 / 0 / 35 / 19 |
| B2 | rastgele | 11370 | -0.50 | -25.8 | 22.7 | +0.70/-0.85 | 9 / 1 / 0 / 12 / 78 |
| B2 | rastgele-oynaklık | 8714 | -0.45 | -14.5 | 28.8 | +0.90/-1.00 | 17 / 3 / 0 / 21 / 59 |
| B2 | **fark: sinyal−rastgele** | | +0.06 [-0.02; +0.14] | | | | |
| B2 | **fark: sinyal−rastgele(oynaklık)** | | +0.01 [-0.08; +0.10] | | | | |
| B3 | sinyal | 5399 | -0.45 | -13.9 | 33.1 | +1.20/-1.27 | 30 / 13 / 0 / 36 / 20 |
| B3 | rastgele | 10798 | -0.50 | -23.0 | 24.2 | +0.75/-0.90 | 10 / 1 / 0 / 13 / 76 |
| B3 | rastgele-oynaklık | 8264 | -0.49 | -17.2 | 26.9 | +0.92/-1.01 | 16 / 2 / 0 / 23 / 59 |
| B3 | **fark: sinyal−rastgele** | | +0.05 [-0.03; +0.13] | | | | |
| B3 | **fark: sinyal−rastgele(oynaklık)** | | +0.04 [-0.05; +0.12] | | | | |
| 90 gün | sinyal | 15357 | -0.45 | -23.6 | 34.0 | +1.20/-1.30 | 31 / 14 / 0 / 36 / 18 |
| 90 gün | rastgele | 30570 | -0.51 | -45.0 | 22.3 | +0.72/-0.87 | 9 / 1 / 0 / 13 / 77 |
| 90 gün | rastgele-oynaklık | 22044 | -0.50 | -26.6 | 26.3 | +0.91/-1.00 | 15 / 3 / 0 / 22 / 60 |
| 90 gün | **fark: sinyal−rastgele** | | +0.07 [+0.02; +0.11] | | | | |
| 90 gün | **fark: sinyal−rastgele(oynaklık)** | | +0.05 [-0.00; +0.10] | | | | |

### G

**sabit TP/SL — fixed TP1.5 SL3 T60**

| blok | tür | n | net ort. | t | kazanma % | kazanç/kayıp | çıkış payı |
|---|---|---|---|---|---|---|---|
| B1 | sinyal | 1912 | -0.44 | -9.9 | 52.1 | +1.18/-2.21 | 46 / 22 / 0 / 0 / 32 |
| B1 | rastgele | 3824 | -0.54 | -27.6 | 22.8 | +0.75/-0.92 | 10 / 1 / 0 / 0 / 89 |
| B1 | rastgele-oynaklık | 2214 | -0.58 | -13.9 | 29.8 | +0.90/-1.21 | 18 / 3 / 0 / 0 / 80 |
| B1 | **fark: sinyal−rastgele** | | +0.09 [-0.00; +0.19] | | | | |
| B1 | **fark: sinyal−rastgele(oynaklık)** | | +0.14 [+0.02; +0.26] | | | | |
| B2 | sinyal | 3268 | -0.33 | -5.8 | 54.3 | +1.10/-2.03 | 43 / 19 / 0 / 0 / 37 |
| B2 | rastgele | 6474 | -0.49 | -22.2 | 25.2 | +0.70/-0.89 | 9 / 1 / 0 / 0 / 90 |
| B2 | rastgele-oynaklık | 4706 | -0.35 | -10.2 | 39.7 | +0.86/-1.14 | 21 / 3 / 0 / 0 / 76 |
| B2 | **fark: sinyal−rastgele** | | +0.16 [+0.04; +0.28] | | | | |
| B2 | **fark: sinyal−rastgele(oynaklık)** | | +0.02 [-0.11; +0.15] | | | | |
| B3 | sinyal | 1952 | -0.19 | -3.1 | 56.4 | +1.12/-1.89 | 46 / 16 / 0 / 0 / 38 |
| B3 | rastgele | 3904 | -0.50 | -16.1 | 27.7 | +0.72/-0.96 | 11 / 2 / 0 / 0 / 88 |
| B3 | rastgele-oynaklık | 2796 | -0.45 | -9.5 | 34.2 | +0.91/-1.15 | 20 / 2 / 0 / 0 / 78 |
| B3 | **fark: sinyal−rastgele** | | +0.30 [+0.17; +0.44] | | | | |
| B3 | **fark: sinyal−rastgele(oynaklık)** | | +0.25 [+0.10; +0.40] | | | | |
| 90 gün | sinyal | 7132 | -0.32 | -8.8 | 54.3 | +1.13/-2.05 | 45 / 19 / 0 / 0 / 36 |
| 90 gün | rastgele | 14202 | -0.50 | -35.2 | 25.2 | +0.72/-0.91 | 10 / 1 / 0 / 0 / 89 |
| 90 gün | rastgele-oynaklık | 9716 | -0.43 | -16.5 | 35.8 | +0.88/-1.16 | 20 / 3 / 0 / 0 / 77 |
| 90 gün | **fark: sinyal−rastgele** | | +0.18 [+0.10; +0.26] | | | | |
| 90 gün | **fark: sinyal−rastgele(oynaklık)** | | +0.11 [+0.02; +0.19] | | | | |

**izleyen stop — trail act1.5 gap0.4 SL3 T60**

| blok | tür | n | net ort. | t | kazanma % | kazanç/kayıp | çıkış payı |
|---|---|---|---|---|---|---|---|
| B1 | sinyal | 1912 | -0.49 | -11.8 | 48.0 | +1.24/-2.08 | 0 / 22 / 44 / 0 / 34 |
| B1 | rastgele | 3824 | -0.57 | -30.9 | 21.4 | +0.66/-0.91 | 0 / 1 / 8 / 0 / 91 |
| B1 | rastgele-oynaklık | 2214 | -0.66 | -17.0 | 26.2 | +0.78/-1.17 | 0 / 3 / 15 / 0 / 82 |
| B1 | **fark: sinyal−rastgele** | | +0.08 [-0.00; +0.17] | | | | |
| B1 | **fark: sinyal−rastgele(oynaklık)** | | +0.17 [+0.06; +0.28] | | | | |
| B2 | sinyal | 3268 | -0.34 | -5.7 | 53.0 | +1.13/-2.00 | 0 / 19 / 41 / 0 / 40 |
| B2 | rastgele | 6474 | -0.50 | -21.8 | 24.8 | +0.68/-0.88 | 0 / 1 / 8 / 0 / 91 |
| B2 | rastgele-oynaklık | 4706 | -0.38 | -10.5 | 39.0 | +0.79/-1.13 | 0 / 3 / 17 / 0 / 80 |
| B2 | **fark: sinyal−rastgele** | | +0.16 [+0.03; +0.28] | | | | |
| B2 | **fark: sinyal−rastgele(oynaklık)** | | +0.04 [-0.10; +0.18] | | | | |
| B3 | sinyal | 1952 | -0.22 | -3.6 | 55.0 | +1.12/-1.85 | 0 / 16 / 44 / 0 / 40 |
| B3 | rastgele | 3904 | -0.51 | -16.8 | 27.4 | +0.67/-0.96 | 0 / 2 / 8 / 0 / 90 |
| B3 | rastgele-oynaklık | 2796 | -0.48 | -9.6 | 33.4 | +0.83/-1.14 | 0 / 2 / 17 / 0 / 81 |
| B3 | **fark: sinyal−rastgele** | | +0.29 [+0.16; +0.43] | | | | |
| B3 | **fark: sinyal−rastgele(oynaklık)** | | +0.26 [+0.11; +0.42] | | | | |
| 90 gün | sinyal | 7132 | -0.35 | -9.4 | 52.2 | +1.15/-1.98 | 0 / 19 / 42 / 0 / 39 |
| 90 gün | rastgele | 14202 | -0.52 | -35.7 | 24.6 | +0.67/-0.91 | 0 / 1 / 8 / 0 / 91 |
| 90 gün | rastgele-oynaklık | 9716 | -0.47 | -17.1 | 34.5 | +0.80/-1.15 | 0 / 3 / 17 / 0 / 81 |
| 90 gün | **fark: sinyal−rastgele** | | +0.17 [+0.10; +0.25] | | | | |
| 90 gün | **fark: sinyal−rastgele(oynaklık)** | | +0.13 [+0.04; +0.22] | | | | |

**ATR-izleyen — atr k1 act1 SL3 T60**

| blok | tür | n | net ort. | t | kazanma % | kazanç/kayıp | çıkış payı |
|---|---|---|---|---|---|---|---|
| B1 | sinyal | 1912 | -0.52 | -13.0 | 35.5 | +1.74/-1.75 | 0 / 20 / 50 / 0 / 30 |
| B1 | rastgele | 3824 | -0.56 | -31.4 | 23.7 | +0.57/-0.91 | 0 / 1 / 16 / 0 / 83 |
| B1 | rastgele-oynaklık | 2214 | -0.67 | -17.7 | 26.8 | +0.63/-1.15 | 0 / 3 / 25 / 0 / 72 |
| B1 | **fark: sinyal−rastgele** | | +0.05 [-0.04; +0.13] | | | | |
| B1 | **fark: sinyal−rastgele(oynaklık)** | | +0.16 [+0.05; +0.26] | | | | |
| B2 | sinyal | 3268 | -0.41 | -6.2 | 43.0 | +1.28/-1.68 | 0 / 17 / 46 / 0 / 37 |
| B2 | rastgele | 6474 | -0.50 | -22.7 | 26.8 | +0.58/-0.89 | 0 / 1 / 16 / 0 / 83 |
| B2 | rastgele-oynaklık | 4706 | -0.40 | -11.4 | 40.3 | +0.66/-1.11 | 0 / 3 / 26 / 0 / 71 |
| B2 | **fark: sinyal−rastgele** | | +0.09 [-0.05; +0.23] | | | | |
| B2 | **fark: sinyal−rastgele(oynaklık)** | | -0.01 [-0.16; +0.13] | | | | |
| B3 | sinyal | 1952 | -0.27 | -4.5 | 44.9 | +1.30/-1.54 | 0 / 14 / 49 / 0 / 37 |
| B3 | rastgele | 3904 | -0.51 | -17.0 | 29.7 | +0.56/-0.97 | 0 / 2 / 18 / 0 / 81 |
| B3 | rastgele-oynaklık | 2796 | -0.48 | -9.3 | 35.8 | +0.68/-1.12 | 0 / 2 / 26 / 0 / 71 |
| B3 | **fark: sinyal−rastgele** | | +0.25 [+0.11; +0.38] | | | | |
| B3 | **fark: sinyal−rastgele(oynaklık)** | | +0.21 [+0.05; +0.36] | | | | |
| 90 gün | sinyal | 7132 | -0.40 | -10.3 | 41.5 | +1.39/-1.66 | 0 / 17 / 48 / 0 / 35 |
| 90 gün | rastgele | 14202 | -0.52 | -36.8 | 26.7 | +0.57/-0.92 | 0 / 1 / 16 / 0 / 83 |
| 90 gün | rastgele-oynaklık | 9716 | -0.48 | -17.6 | 36.0 | +0.66/-1.12 | 0 / 3 / 26 / 0 / 72 |
| 90 gün | **fark: sinyal−rastgele** | | +0.12 [+0.04; +0.20] | | | | |
| 90 gün | **fark: sinyal−rastgele(oynaklık)** | | +0.08 [-0.01; +0.18] | | | | |

**başabaş — be0.6 TP1.5 SL3 T60**

| blok | tür | n | net ort. | t | kazanma % | kazanç/kayıp | çıkış payı |
|---|---|---|---|---|---|---|---|
| B1 | sinyal | 1912 | -0.42 | -15.4 | 36.4 | +1.19/-1.35 | 33 / 15 / 0 / 33 / 19 |
| B1 | rastgele | 3824 | -0.54 | -27.7 | 19.9 | +0.77/-0.86 | 9 / 1 / 0 / 12 / 77 |
| B1 | rastgele-oynaklık | 2214 | -0.58 | -15.6 | 23.8 | +0.97/-1.07 | 16 / 3 / 0 / 21 / 60 |
| B1 | **fark: sinyal−rastgele** | | +0.12 [+0.05; +0.18] | | | | |
| B1 | **fark: sinyal−rastgele(oynaklık)** | | +0.16 [+0.07; +0.25] | | | | |
| B2 | sinyal | 3268 | -0.36 | -5.6 | 39.1 | +1.11/-1.31 | 32 / 14 / 0 / 30 / 24 |
| B2 | rastgele | 6474 | -0.50 | -23.2 | 22.4 | +0.70/-0.84 | 8 / 1 / 0 / 11 / 80 |
| B2 | rastgele-oynaklık | 4706 | -0.38 | -11.2 | 32.5 | +0.88/-0.98 | 18 / 3 / 0 / 20 / 60 |
| B2 | **fark: sinyal−rastgele** | | +0.14 [+0.00; +0.27] | | | | |
| B2 | **fark: sinyal−rastgele(oynaklık)** | | +0.02 [-0.12; +0.16] | | | | |
| B3 | sinyal | 1952 | -0.22 | -4.5 | 40.2 | +1.14/-1.14 | 34 / 11 / 0 / 33 / 23 |
| B3 | rastgele | 3904 | -0.50 | -17.5 | 24.7 | +0.74/-0.91 | 10 / 2 / 0 / 12 / 76 |
| B3 | rastgele-oynaklık | 2796 | -0.45 | -10.8 | 27.6 | +0.95/-0.98 | 17 / 2 / 0 / 24 / 57 |
| B3 | **fark: sinyal−rastgele** | | +0.28 [+0.16; +0.39] | | | | |
| B3 | **fark: sinyal−rastgele(oynaklık)** | | +0.23 [+0.10; +0.35] | | | | |
| 90 gün | sinyal | 7132 | -0.34 | -9.4 | 38.7 | +1.14/-1.27 | 33 / 14 / 0 / 32 / 22 |
| 90 gün | rastgele | 14202 | -0.51 | -37.1 | 22.4 | +0.73/-0.86 | 9 / 1 / 0 / 12 / 78 |
| 90 gün | rastgele-oynaklık | 9716 | -0.44 | -18.4 | 29.1 | +0.91/-1.00 | 17 / 2 / 0 / 21 / 59 |
| 90 gün | **fark: sinyal−rastgele** | | +0.17 [+0.09; +0.24] | | | | |
| 90 gün | **fark: sinyal−rastgele(oynaklık)** | | +0.11 [+0.02; +0.19] | | | | |

## 5. Walk-forward (eğitim bloğunda seç → sonraki blokta dokunmadan ölç)
Seçim ölçütü: eğitim bloğunda sinyal ortalama neti (n ≥ 100). 'Sinyal−rastgele' aynı hücrede, aynı blokta; aralıklar %95 (gün-kümeli SE). Son sütun: aynı OOS blokta hücrelerin kaçı net>0 (seçimsiz kıyas).

### Senaryo 60 sn / %0.15

| kaynak | seçim | seçilen hücre | eğitim n / net | OOS blok | OOS n | OOS net [%95] | t | rastgele net | sinyal−rastgele [%95] | sinyal−rastgele(oynaklık) [%95] | OOS'ta net>0 hücre |
|---|---|---|---|---|---|---|---|---|---|---|---|
| HA | B1 → | trail act0.5 gap0.8 SL3 T30 | 6110 / -0.52 | B2 | 6797 | -0.50 [-0.53; -0.47] | -30.9 | -0.53 | +0.03 [-0.01; +0.07] | -0.01 [-0.08; +0.05] | 0/60 |
| HA | B1 → | trail act0.5 gap0.8 SL3 T30 | 6110 / -0.52 | B3 | 7436 | -0.52 [-0.56; -0.48] | -28.2 | -0.52 | -0.00 [-0.04; +0.04] | -0.01 [-0.08; +0.05] | 0/60 |
| HA | B1 → | trail act0.5 gap0.8 SL3 T30 | 6110 / -0.52 | B2+B3 | 14233 | -0.51 [-0.53; -0.48] | -40.9 | -0.52 | +0.01 [-0.01; +0.04] | -0.01 [-0.06; +0.03] | 0/60 |
| HA | B2 → | fixed TPcand SL1.5 T120 | 6797 / -0.48 | B3 | 7436 | -0.58 [-0.64; -0.52] | -19.2 | -0.50 | -0.08 [-0.17; +0.02] | +0.01 [-0.13; +0.14] | 0/60 |
| E | B1 → | trail act0.5 gap0.4 SL3 T60 | 4201 / -0.45 | B2 | 5757 | -0.46 [-0.53; -0.40] | -13.9 | -0.50 | +0.04 [-0.03; +0.11] | -0.01 [-0.09; +0.08] | 0/60 |
| E | B1 → | trail act0.5 gap0.4 SL3 T60 | 4201 / -0.45 | B3 | 5399 | -0.46 [-0.52; -0.40] | -16.0 | -0.52 | +0.05 [-0.01; +0.12] | +0.05 [-0.03; +0.13] | 0/60 |
| E | B1 → | trail act0.5 gap0.4 SL3 T60 | 4201 / -0.45 | B2+B3 | 11156 | -0.46 [-0.50; -0.42] | -20.9 | -0.51 | +0.05 [-0.00; +0.10] | +0.02 [-0.04; +0.08] | 0/60 |
| E | B2 → | be0.6 TPcand SL3 T60 | 5757 / -0.43 | B3 | 5399 | -0.48 [-0.55; -0.41] | -12.7 | -0.53 | +0.05 [-0.04; +0.13] | +0.05 [-0.04; +0.15] | 0/60 |
| G | B1 → | be0.6 TP1.5 SL3 T60 | 1912 / -0.42 | B2 | 3268 | -0.36 [-0.49; -0.23] | -5.6 | -0.50 | +0.14 [+0.00; +0.27] | +0.02 [-0.12; +0.16] | 0/60 |
| G | B1 → | be0.6 TP1.5 SL3 T60 | 1912 / -0.42 | B3 | 1952 | -0.22 [-0.32; -0.13] | -4.5 | -0.50 | +0.28 [+0.16; +0.39] | +0.23 [+0.10; +0.35] | 0/60 |
| G | B1 → | be0.6 TP1.5 SL3 T60 | 1912 / -0.42 | B2+B3 | 5220 | -0.31 [-0.40; -0.21] | -6.4 | -0.50 | +0.19 [+0.09; +0.29] | +0.10 [-0.01; +0.20] | 0/60 |
| G | B2 → | fixed TP1.5 SL3 T120 | 3268 / -0.33 | B3 | 1952 | -0.26 [-0.41; -0.10] | -3.3 | -0.45 | +0.20 [+0.02; +0.38] | +0.22 [-0.01; +0.45] | 0/60 |

### Senaryo 0 sn / %0.05

| kaynak | seçim | seçilen hücre | eğitim n / net | OOS blok | OOS n | OOS net [%95] | t | rastgele net | sinyal−rastgele [%95] | sinyal−rastgele(oynaklık) [%95] | OOS'ta net>0 hücre |
|---|---|---|---|---|---|---|---|---|---|---|---|
| HA | B1 → | trail act0.5 gap0.8 SL3 T30 | 6110 / -0.32 | B2 | 6797 | -0.32 [-0.36; -0.29] | -17.9 | -0.33 | +0.01 [-0.03; +0.05] | -0.04 [-0.10; +0.03] | 0/60 |
| HA | B1 → | trail act0.5 gap0.8 SL3 T30 | 6110 / -0.32 | B3 | 7436 | -0.31 [-0.35; -0.27] | -14.7 | -0.31 | +0.00 [-0.04; +0.05] | -0.00 [-0.07; +0.06] | 0/60 |
| HA | B1 → | trail act0.5 gap0.8 SL3 T30 | 6110 / -0.32 | B2+B3 | 14233 | -0.32 [-0.34; -0.29] | -22.6 | -0.32 | +0.01 [-0.03; +0.04] | -0.02 [-0.07; +0.03] | 0/60 |
| HA | B2 → | trail act0.5 gap0.8 SL3 T30 | 6797 / -0.32 | B3 | 7436 | -0.31 [-0.35; -0.27] | -14.7 | -0.31 | +0.00 [-0.04; +0.05] | -0.00 [-0.07; +0.06] | 0/60 |
| E | B1 → | trail act1.5 gap0.8 SL1.5 T60 | 4201 / -0.23 | B2 | 5757 | -0.30 [-0.38; -0.21] | -6.6 | -0.34 | +0.04 [-0.06; +0.14] | +0.02 [-0.10; +0.13] | 0/60 |
| E | B1 → | trail act1.5 gap0.8 SL1.5 T60 | 4201 / -0.23 | B3 | 5399 | -0.30 [-0.35; -0.24] | -10.6 | -0.34 | +0.04 [-0.03; +0.11] | +0.06 [-0.03; +0.15] | 0/60 |
| E | B1 → | trail act1.5 gap0.8 SL1.5 T60 | 4201 / -0.23 | B2+B3 | 11156 | -0.30 [-0.35; -0.24] | -11.0 | -0.34 | +0.04 [-0.02; +0.10] | +0.04 [-0.03; +0.11] | 0/60 |
| E | B2 → | trail act0.5 gap0.4 SL3 T120 | 5757 / -0.24 | B3 | 5399 | -0.26 [-0.33; -0.19] | -7.3 | -0.28 | +0.02 [-0.06; +0.11] | +0.06 [-0.05; +0.17] | 0/60 |
| G | B1 → | fixed TPcand SL1.5 T60 | 1912 / -0.18 | B2 | 3268 | -0.19 [-0.36; -0.01] | -2.1 | -0.33 | +0.14 [-0.04; +0.33] | +0.06 [-0.13; +0.26] | 0/60 |
| G | B1 → | fixed TPcand SL1.5 T60 | 1912 / -0.18 | B3 | 1952 | -0.03 [-0.14; +0.09] | -0.5 | -0.33 | +0.30 [+0.18; +0.43] | +0.30 [+0.14; +0.47] | 2/60 |
| G | B1 → | fixed TPcand SL1.5 T60 | 1912 / -0.18 | B2+B3 | 5220 | -0.13 [-0.26; +0.00] | -1.9 | -0.33 | +0.20 [+0.07; +0.34] | +0.15 [+0.01; +0.30] | 0/60 |
| G | B2 → | be0.6 TPcand SL3 T60 | 3268 / -0.17 | B3 | 1952 | -0.04 [-0.14; +0.07] | -0.7 | -0.33 | +0.29 [+0.17; +0.41] | +0.24 [+0.10; +0.38] | 2/60 |

### Senaryo 120 sn / %0.15

| kaynak | seçim | seçilen hücre | eğitim n / net | OOS blok | OOS n | OOS net [%95] | t | rastgele net | sinyal−rastgele [%95] | sinyal−rastgele(oynaklık) [%95] | OOS'ta net>0 hücre |
|---|---|---|---|---|---|---|---|---|---|---|---|
| HA | B1 → | fixed TP1.5 SL3 T60 | 6110 / -0.52 | B2 | 6797 | -0.51 [-0.57; -0.44] | -15.8 | -0.51 | +0.00 [-0.07; +0.07] | -0.10 [-0.18; -0.02] | 0/60 |
| HA | B1 → | fixed TP1.5 SL3 T60 | 6110 / -0.52 | B3 | 7436 | -0.55 [-0.59; -0.50] | -23.1 | -0.49 | -0.06 [-0.12; +0.00] | -0.06 [-0.15; +0.02] | 0/60 |
| HA | B1 → | fixed TP1.5 SL3 T60 | 6110 / -0.52 | B2+B3 | 14233 | -0.53 [-0.57; -0.49] | -26.2 | -0.50 | -0.03 [-0.08; +0.02] | -0.08 [-0.14; -0.02] | 0/60 |
| HA | B2 → | fixed TPcand SL1.5 T120 | 6797 / -0.47 | B3 | 7436 | -0.57 [-0.63; -0.52] | -19.6 | -0.50 | -0.07 [-0.16; +0.02] | +0.02 [-0.12; +0.15] | 0/60 |
| E | B1 → | fixed TP1.5 SL3 T60 | 4201 / -0.47 | B2 | 5757 | -0.37 [-0.50; -0.24] | -5.5 | -0.49 | +0.13 [-0.01; +0.26] | +0.06 [-0.09; +0.20] | 0/60 |
| E | B1 → | fixed TP1.5 SL3 T60 | 4201 / -0.47 | B3 | 5399 | -0.47 [-0.55; -0.39] | -11.5 | -0.49 | +0.03 [-0.07; +0.12] | +0.01 [-0.10; +0.12] | 0/60 |
| E | B1 → | fixed TP1.5 SL3 T60 | 4201 / -0.47 | B2+B3 | 11156 | -0.42 [-0.50; -0.33] | -9.9 | -0.49 | +0.08 [-0.01; +0.17] | +0.03 [-0.06; +0.13] | 0/60 |
| E | B2 → | trail act1 gap0.8 SL3 T60 | 5757 / -0.35 | B3 | 5399 | -0.48 [-0.55; -0.40] | -13.0 | -0.52 | +0.04 [-0.04; +0.13] | +0.05 [-0.05; +0.15] | 0/60 |
| G | B1 → | fixed TP1.5 SL1.5 T120 | 1912 / -0.45 | B2 | 3268 | -0.31 [-0.40; -0.21] | -6.3 | -0.49 | +0.18 [+0.06; +0.30] | +0.13 [+0.01; +0.25] | 0/60 |
| G | B1 → | fixed TP1.5 SL1.5 T120 | 1912 / -0.45 | B3 | 1952 | -0.28 [-0.39; -0.18] | -5.2 | -0.48 | +0.20 [+0.06; +0.33] | +0.23 [+0.06; +0.39] | 0/60 |
| G | B1 → | fixed TP1.5 SL1.5 T120 | 1912 / -0.45 | B2+B3 | 5220 | -0.30 [-0.37; -0.23] | -8.2 | -0.49 | +0.19 [+0.10; +0.28] | +0.17 [+0.07; +0.27] | 0/60 |
| G | B2 → | trail act1.5 gap0.4 SL3 T60 | 3268 / -0.17 | B3 | 1952 | -0.21 [-0.34; -0.07] | -2.9 | -0.51 | +0.30 [+0.15; +0.45] | +0.28 [+0.11; +0.45] | 0/60 |

### Aile bazında walk-forward (birincil senaryo; her ailenin B1-en-iyisi → B2, B3)

| kaynak | aile | seçilen hücre (B1) | B1 net | B2 net [%95] | B3 net [%95] | B2 sinyal−rastgele | B3 sinyal−rastgele |
|---|---|---|---|---|---|---|---|
| HA | sabit TP/SL | fixed TPcand SL3 T120 | -0.53 | -0.53 [-0.62; -0.43] | -0.64 [-0.73; -0.55] | -0.04 [-0.17; +0.08] | -0.17 [-0.29; -0.05] |
| HA | izleyen stop | trail act0.5 gap0.8 SL3 T30 | -0.52 | -0.50 [-0.53; -0.47] | -0.52 [-0.56; -0.48] | +0.03 [-0.01; +0.07] | -0.00 [-0.04; +0.04] |
| HA | ATR-izleyen | atr k1 act1 SL3 T60 | -0.57 | -0.56 [-0.61; -0.51] | -0.57 [-0.63; -0.52] | -0.05 [-0.11; +0.02] | -0.06 [-0.13; +0.01] |
| HA | başabaş | be0.6 TPcand SL3 T60 | -0.54 | -0.50 [-0.55; -0.45] | -0.55 [-0.61; -0.50] | +0.02 [-0.04; +0.09] | -0.04 [-0.11; +0.02] |
| E | sabit TP/SL | fixed TP1.5 SL3 T60 | -0.45 | -0.44 [-0.52; -0.37] | -0.44 [-0.52; -0.37] | +0.04 [-0.04; +0.13] | +0.05 [-0.03; +0.14] |
| E | izleyen stop | trail act0.5 gap0.4 SL3 T60 | -0.45 | -0.46 [-0.53; -0.40] | -0.46 [-0.52; -0.40] | +0.04 [-0.03; +0.11] | +0.05 [-0.01; +0.12] |
| E | ATR-izleyen | atr k1 act1 SL1.5 T60 | -0.51 | -0.50 [-0.57; -0.42] | -0.50 [-0.56; -0.44] | +0.03 [-0.05; +0.12] | +0.04 [-0.04; +0.11] |
| E | başabaş | be0.6 TP1.5 SL3 T60 | -0.46 | -0.44 [-0.50; -0.37] | -0.45 [-0.52; -0.39] | +0.06 [-0.02; +0.14] | +0.05 [-0.03; +0.13] |
| G | sabit TP/SL | fixed TP1.5 SL1.5 T60 | -0.44 | -0.41 [-0.55; -0.26] | -0.30 [-0.40; -0.21] | +0.11 [-0.04; +0.26] | +0.20 [+0.10; +0.31] |
| G | izleyen stop | trail act1 gap0.8 SL3 T60 | -0.44 | -0.37 [-0.50; -0.24] | -0.23 [-0.34; -0.12] | +0.14 [+0.00; +0.27] | +0.29 [+0.17; +0.42] |
| G | ATR-izleyen | atr k1 act1 SL3 T60 | -0.52 | -0.41 [-0.54; -0.28] | -0.27 [-0.39; -0.15] | +0.09 [-0.05; +0.23] | +0.25 [+0.11; +0.38] |
| G | başabaş | be0.6 TP1.5 SL3 T60 | -0.42 | -0.36 [-0.49; -0.23] | -0.22 [-0.32; -0.13] | +0.14 [+0.00; +0.27] | +0.28 [+0.16; +0.39] |

### Alternatif seçim: eğitimde 'sinyal−rastgele' farkı en büyük hücre (birincil senaryo)

| kaynak | seçim | hücre | eğitim fark | OOS blok | OOS net [%95] | OOS sinyal−rastgele [%95] |
|---|---|---|---|---|---|---|
| HA | B1 → | fixed TPcand SL1.5 T120 | +0.06 | B2 | -0.48 [-0.56; -0.40] | +0.04 [-0.07; +0.15] |
| HA | B1 → | fixed TPcand SL1.5 T120 | +0.06 | B3 | -0.58 [-0.64; -0.52] | -0.08 [-0.17; +0.02] |
| HA | B1 → | fixed TPcand SL1.5 T120 | +0.06 | B2+B3 | -0.53 [-0.58; -0.48] | -0.02 [-0.09; +0.05] |
| HA | B2 → | fixed TPcand SL1.5 T60 | +0.05 | B3 | -0.57 [-0.62; -0.52] | -0.04 [-0.11; +0.02] |
| E | B1 → | be0.6+trail act1 gap0.8 SL1.5 T60 | +0.13 | B2 | -0.48 [-0.55; -0.41] | +0.06 [-0.02; +0.13] |
| E | B1 → | be0.6+trail act1 gap0.8 SL1.5 T60 | +0.13 | B3 | -0.49 [-0.54; -0.45] | +0.05 [-0.01; +0.11] |
| E | B1 → | be0.6+trail act1 gap0.8 SL1.5 T60 | +0.13 | B2+B3 | -0.49 [-0.53; -0.45] | +0.05 [+0.00; +0.10] |
| E | B2 → | be0.6 TPcand SL3 T60 | +0.09 | B3 | -0.48 [-0.55; -0.41] | +0.05 [-0.04; +0.13] |
| G | B1 → | trail act1 gap0.8 SL1.5 T60 | +0.18 | B2 | -0.44 [-0.58; -0.30] | +0.09 [-0.05; +0.24] |
| G | B1 → | trail act1 gap0.8 SL1.5 T60 | +0.18 | B3 | -0.32 [-0.41; -0.22] | +0.22 [+0.11; +0.32] |
| G | B1 → | trail act1 gap0.8 SL1.5 T60 | +0.18 | B2+B3 | -0.39 [-0.49; -0.29] | +0.14 [+0.03; +0.24] |
| G | B2 → | trail act1.5 gap0.8 SL3 T60 | +0.16 | B3 | -0.23 [-0.35; -0.10] | +0.29 [+0.15; +0.43] |

## 6. Gecikme / kayma duyarlılığı (seçilen hücreler)
Not: gecikmeyi 0 → 120 sn artırmak net'i bozmuyor, HA ve G'de hafif iyileştiriyor (HA'da dolan açılış, sinyal fiyatının ortalama %0,04 altında: fiyat sinyal barından sonra biraz geri çekiliyor); kayma %0,05 → %0,15 ise net'i her hücrede ≈ 0,2 puan düşürüyor (giriş + stop/zaman çıkışı).

Seçilen hücreler = HA'da B1+B2 üzerinde (birincil senaryo) aile başına en iyi hücre + B1-en-iyi (walk-forward) + her kaynak için B1-en-iyi. Bu hücreler `chosen_cells.json`'a DONDURULUR ve canlı ileri testte (rapor 8) aynen kullanılır.

**HA — fixed TPcand SL1.5 T120** (B1+B2 en iyi sabit TP/SL (net -0.51))

| senaryo | B1 net | B2 net | B3 net | 90 gün net [%95] | 90 gün rastgele | 90 gün sinyal−rastgele [%95] |
|---|---|---|---|---|---|---|
| 0 sn / %0.05 | -0.38 | -0.33 | -0.40 | -0.37 [-0.41; -0.33] | -0.34 | -0.03 [-0.08; +0.02] |
| 0 sn / %0.15 | -0.56 | -0.50 | -0.57 | -0.55 [-0.58; -0.51] | -0.54 | -0.01 [-0.06; +0.05] |
| 60 sn / %0.05 | -0.36 | -0.30 | -0.40 | -0.36 [-0.40; -0.32] | -0.34 | -0.02 [-0.07; +0.04] |
| 60 sn / %0.15 | -0.54 | -0.48 | -0.58 | -0.53 [-0.57; -0.49] | -0.54 | +0.00 [-0.05; +0.06] |
| 120 sn / %0.05 | -0.34 | -0.29 | -0.41 | -0.35 [-0.39; -0.31] | -0.34 | -0.01 [-0.07; +0.05] |
| 120 sn / %0.15 | -0.52 | -0.47 | -0.57 | -0.52 [-0.56; -0.48] | -0.54 | +0.02 [-0.04; +0.07] |

**HA — trail act0.5 gap0.8 SL3 T30** (B1+B2 en iyi izleyen stop (net -0.51))

| senaryo | B1 net | B2 net | B3 net | 90 gün net [%95] | 90 gün rastgele | 90 gün sinyal−rastgele [%95] |
|---|---|---|---|---|---|---|
| 0 sn / %0.05 | -0.32 | -0.32 | -0.31 | -0.32 [-0.34; -0.30] | -0.33 | +0.01 [-0.01; +0.04] |
| 0 sn / %0.15 | -0.52 | -0.53 | -0.52 | -0.52 [-0.54; -0.50] | -0.53 | +0.01 [-0.02; +0.03] |
| 60 sn / %0.05 | -0.33 | -0.29 | -0.32 | -0.31 [-0.33; -0.29] | -0.33 | +0.02 [-0.01; +0.04] |
| 60 sn / %0.15 | -0.52 | -0.50 | -0.52 | -0.51 [-0.53; -0.49] | -0.53 | +0.02 [-0.01; +0.04] |
| 120 sn / %0.05 | -0.32 | -0.29 | -0.31 | -0.30 [-0.32; -0.28] | -0.33 | +0.02 [+0.00; +0.05] |
| 120 sn / %0.15 | -0.53 | -0.50 | -0.51 | -0.51 [-0.53; -0.49] | -0.53 | +0.02 [-0.01; +0.04] |

**HA — atr k1 act1 SL1.5 T60** (B1+B2 en iyi ATR-izleyen (net -0.56))

| senaryo | B1 net | B2 net | B3 net | 90 gün net [%95] | 90 gün rastgele | 90 gün sinyal−rastgele [%95] |
|---|---|---|---|---|---|---|
| 0 sn / %0.05 | -0.38 | -0.35 | -0.34 | -0.36 [-0.38; -0.33] | -0.34 | -0.02 [-0.05; +0.02] |
| 0 sn / %0.15 | -0.59 | -0.55 | -0.55 | -0.56 [-0.59; -0.53] | -0.54 | -0.02 [-0.05; +0.02] |
| 60 sn / %0.05 | -0.38 | -0.34 | -0.33 | -0.35 [-0.38; -0.32] | -0.34 | -0.01 [-0.04; +0.02] |
| 60 sn / %0.15 | -0.57 | -0.54 | -0.53 | -0.55 [-0.57; -0.52] | -0.54 | -0.00 [-0.04; +0.03] |
| 120 sn / %0.05 | -0.36 | -0.32 | -0.35 | -0.34 [-0.37; -0.31] | -0.34 | -0.00 [-0.03; +0.03] |
| 120 sn / %0.15 | -0.55 | -0.52 | -0.54 | -0.54 [-0.56; -0.51] | -0.54 | +0.01 [-0.03; +0.04] |

**HA — be0.6 TPcand SL3 T60** (B1+B2 en iyi başabaş (net -0.52))

| senaryo | B1 net | B2 net | B3 net | 90 gün net [%95] | 90 gün rastgele | 90 gün sinyal−rastgele [%95] |
|---|---|---|---|---|---|---|
| 0 sn / %0.05 | -0.37 | -0.33 | -0.36 | -0.35 [-0.38; -0.32] | -0.33 | -0.02 [-0.05; +0.02] |
| 0 sn / %0.15 | -0.55 | -0.52 | -0.55 | -0.54 [-0.57; -0.51] | -0.53 | -0.01 [-0.04; +0.03] |
| 60 sn / %0.05 | -0.34 | -0.32 | -0.37 | -0.35 [-0.37; -0.32] | -0.33 | -0.01 [-0.05; +0.02] |
| 60 sn / %0.15 | -0.54 | -0.50 | -0.55 | -0.53 [-0.56; -0.50] | -0.53 | -0.00 [-0.04; +0.03] |
| 120 sn / %0.05 | -0.36 | -0.33 | -0.34 | -0.34 [-0.37; -0.31] | -0.33 | -0.01 [-0.05; +0.03] |
| 120 sn / %0.15 | -0.55 | -0.51 | -0.52 | -0.52 [-0.56; -0.49] | -0.53 | +0.00 [-0.03; +0.04] |

**E — fixed TP1.5 SL3 T60** (B1+B2 en iyi sabit TP/SL (net -0.45))

| senaryo | B1 net | B2 net | B3 net | 90 gün net [%95] | 90 gün rastgele | 90 gün sinyal−rastgele [%95] |
|---|---|---|---|---|---|---|
| 0 sn / %0.05 | -0.27 | -0.31 | -0.30 | -0.29 [-0.34; -0.24] | -0.32 | +0.02 [-0.03; +0.08] |
| 0 sn / %0.15 | -0.42 | -0.46 | -0.45 | -0.45 [-0.50; -0.39] | -0.51 | +0.06 [+0.00; +0.12] |
| 60 sn / %0.05 | -0.30 | -0.28 | -0.30 | -0.29 [-0.33; -0.25] | -0.32 | +0.02 [-0.02; +0.07] |
| 60 sn / %0.15 | -0.45 | -0.44 | -0.44 | -0.45 [-0.49; -0.40] | -0.50 | +0.06 [+0.01; +0.11] |
| 120 sn / %0.05 | -0.33 | -0.21 | -0.29 | -0.27 [-0.33; -0.21] | -0.32 | +0.04 [-0.02; +0.11] |
| 120 sn / %0.15 | -0.47 | -0.37 | -0.47 | -0.43 [-0.49; -0.37] | -0.51 | +0.08 [+0.01; +0.14] |

**E — trail act0.5 gap0.8 SL3 T60** (B1+B2 en iyi izleyen stop (net -0.45))

| senaryo | B1 net | B2 net | B3 net | 90 gün net [%95] | 90 gün rastgele | 90 gün sinyal−rastgele [%95] |
|---|---|---|---|---|---|---|
| 0 sn / %0.05 | -0.26 | -0.24 | -0.29 | -0.26 [-0.31; -0.22] | -0.33 | +0.07 [+0.02; +0.12] |
| 0 sn / %0.15 | -0.46 | -0.45 | -0.48 | -0.46 [-0.50; -0.42] | -0.53 | +0.07 [+0.02; +0.12] |
| 60 sn / %0.05 | -0.25 | -0.24 | -0.29 | -0.26 [-0.30; -0.22] | -0.33 | +0.07 [+0.03; +0.12] |
| 60 sn / %0.15 | -0.46 | -0.45 | -0.48 | -0.46 [-0.50; -0.43] | -0.53 | +0.07 [+0.02; +0.11] |
| 120 sn / %0.05 | -0.30 | -0.15 | -0.29 | -0.24 [-0.31; -0.17] | -0.33 | +0.09 [+0.02; +0.17] |
| 120 sn / %0.15 | -0.49 | -0.35 | -0.49 | -0.44 [-0.51; -0.37] | -0.53 | +0.10 [+0.02; +0.17] |

**E — atr k1 act1 SL3 T60** (B1+B2 en iyi ATR-izleyen (net -0.50))

| senaryo | B1 net | B2 net | B3 net | 90 gün net [%95] | 90 gün rastgele | 90 gün sinyal−rastgele [%95] |
|---|---|---|---|---|---|---|
| 0 sn / %0.05 | -0.31 | -0.29 | -0.30 | -0.30 [-0.35; -0.24] | -0.33 | +0.03 [-0.03; +0.09] |
| 0 sn / %0.15 | -0.51 | -0.49 | -0.50 | -0.50 [-0.55; -0.44] | -0.53 | +0.03 [-0.03; +0.09] |
| 60 sn / %0.05 | -0.32 | -0.27 | -0.29 | -0.29 [-0.34; -0.25] | -0.33 | +0.03 [-0.02; +0.08] |
| 60 sn / %0.15 | -0.52 | -0.48 | -0.50 | -0.50 [-0.54; -0.45] | -0.53 | +0.03 [-0.02; +0.08] |
| 120 sn / %0.05 | -0.38 | -0.18 | -0.30 | -0.28 [-0.36; -0.20] | -0.33 | +0.05 [-0.03; +0.13] |
| 120 sn / %0.15 | -0.57 | -0.38 | -0.50 | -0.47 [-0.55; -0.39] | -0.52 | +0.05 [-0.03; +0.14] |

**E — be0.6 TP1.5 SL3 T60** (B1+B2 en iyi başabaş (net -0.45))

| senaryo | B1 net | B2 net | B3 net | 90 gün net [%95] | 90 gün rastgele | 90 gün sinyal−rastgele [%95] |
|---|---|---|---|---|---|---|
| 0 sn / %0.05 | -0.29 | -0.27 | -0.28 | -0.28 [-0.32; -0.24] | -0.32 | +0.04 [-0.00; +0.09] |
| 0 sn / %0.15 | -0.45 | -0.44 | -0.45 | -0.45 [-0.49; -0.41] | -0.51 | +0.06 [+0.02; +0.11] |
| 60 sn / %0.05 | -0.30 | -0.27 | -0.30 | -0.29 [-0.32; -0.25] | -0.32 | +0.03 [-0.01; +0.08] |
| 60 sn / %0.15 | -0.46 | -0.44 | -0.45 | -0.45 [-0.49; -0.41] | -0.51 | +0.07 [+0.02; +0.11] |
| 120 sn / %0.05 | -0.33 | -0.22 | -0.30 | -0.28 [-0.33; -0.23] | -0.32 | +0.05 [-0.01; +0.10] |
| 120 sn / %0.15 | -0.48 | -0.38 | -0.47 | -0.44 [-0.49; -0.39] | -0.51 | +0.07 [+0.02; +0.13] |

**E — trail act0.5 gap0.4 SL3 T60** (B1 en iyi (walk-forward seçimi))

| senaryo | B1 net | B2 net | B3 net | 90 gün net [%95] | 90 gün rastgele | 90 gün sinyal−rastgele [%95] |
|---|---|---|---|---|---|---|
| 0 sn / %0.05 | -0.26 | -0.25 | -0.26 | -0.25 [-0.30; -0.21] | -0.32 | +0.06 [+0.02; +0.11] |
| 0 sn / %0.15 | -0.45 | -0.45 | -0.46 | -0.45 [-0.49; -0.41] | -0.52 | +0.06 [+0.02; +0.11] |
| 60 sn / %0.05 | -0.25 | -0.25 | -0.27 | -0.26 [-0.29; -0.22] | -0.32 | +0.06 [+0.02; +0.10] |
| 60 sn / %0.15 | -0.45 | -0.46 | -0.46 | -0.46 [-0.49; -0.42] | -0.52 | +0.06 [+0.02; +0.10] |
| 120 sn / %0.05 | -0.30 | -0.17 | -0.27 | -0.24 [-0.31; -0.17] | -0.32 | +0.08 [+0.01; +0.15] |
| 120 sn / %0.15 | -0.50 | -0.37 | -0.48 | -0.44 [-0.51; -0.37] | -0.52 | +0.08 [+0.01; +0.15] |

**G — fixed TP1.5 SL3 T60** (B1+B2 en iyi sabit TP/SL (net -0.37))

| senaryo | B1 net | B2 net | B3 net | 90 gün net [%95] | 90 gün rastgele | 90 gün sinyal−rastgele [%95] |
|---|---|---|---|---|---|---|
| 0 sn / %0.05 | -0.26 | -0.22 | -0.03 | -0.18 [-0.27; -0.08] | -0.32 | +0.14 [+0.04; +0.24] |
| 0 sn / %0.15 | -0.39 | -0.38 | -0.18 | -0.33 [-0.42; -0.23] | -0.50 | +0.18 [+0.08; +0.28] |
| 60 sn / %0.05 | -0.29 | -0.17 | -0.05 | -0.17 [-0.24; -0.10] | -0.31 | +0.14 [+0.07; +0.22] |
| 60 sn / %0.15 | -0.44 | -0.33 | -0.19 | -0.32 [-0.40; -0.25] | -0.50 | +0.18 [+0.10; +0.26] |
| 120 sn / %0.05 | -0.34 | -0.05 | -0.03 | -0.12 [-0.21; -0.04] | -0.31 | +0.19 [+0.10; +0.28] |
| 120 sn / %0.15 | -0.46 | -0.21 | -0.18 | -0.27 [-0.36; -0.18] | -0.50 | +0.23 [+0.14; +0.33] |

**G — trail act1 gap0.8 SL3 T60** (B1+B2 en iyi izleyen stop (net -0.39))

| senaryo | B1 net | B2 net | B3 net | 90 gün net [%95] | 90 gün rastgele | 90 gün sinyal−rastgele [%95] |
|---|---|---|---|---|---|---|
| 0 sn / %0.05 | -0.23 | -0.18 | -0.01 | -0.15 [-0.25; -0.05] | -0.33 | +0.18 [+0.07; +0.29] |
| 0 sn / %0.15 | -0.41 | -0.39 | -0.19 | -0.34 [-0.44; -0.24] | -0.53 | +0.19 [+0.08; +0.30] |
| 60 sn / %0.05 | -0.24 | -0.15 | -0.04 | -0.15 [-0.22; -0.08] | -0.33 | +0.18 [+0.11; +0.26] |
| 60 sn / %0.15 | -0.44 | -0.37 | -0.23 | -0.35 [-0.42; -0.27] | -0.53 | +0.18 [+0.10; +0.26] |
| 120 sn / %0.05 | -0.31 | +0.01 | -0.01 | -0.08 [-0.20; +0.03] | -0.33 | +0.24 [+0.12; +0.36] |
| 120 sn / %0.15 | -0.51 | -0.19 | -0.21 | -0.28 [-0.40; -0.16] | -0.53 | +0.25 [+0.12; +0.37] |

**G — atr k1 act1 SL3 T60** (B1+B2 en iyi ATR-izleyen (net -0.45))

| senaryo | B1 net | B2 net | B3 net | 90 gün net [%95] | 90 gün rastgele | 90 gün sinyal−rastgele [%95] |
|---|---|---|---|---|---|---|
| 0 sn / %0.05 | -0.28 | -0.23 | -0.04 | -0.19 [-0.30; -0.08] | -0.32 | +0.13 [+0.01; +0.24] |
| 0 sn / %0.15 | -0.46 | -0.43 | -0.23 | -0.39 [-0.49; -0.28] | -0.52 | +0.13 [+0.02; +0.25] |
| 60 sn / %0.05 | -0.33 | -0.19 | -0.07 | -0.19 [-0.27; -0.12] | -0.32 | +0.12 [+0.04; +0.20] |
| 60 sn / %0.15 | -0.52 | -0.41 | -0.27 | -0.40 [-0.47; -0.32] | -0.52 | +0.12 [+0.04; +0.20] |
| 120 sn / %0.05 | -0.37 | -0.03 | -0.06 | -0.13 [-0.25; -0.01] | -0.31 | +0.18 [+0.06; +0.31] |
| 120 sn / %0.15 | -0.56 | -0.23 | -0.26 | -0.33 [-0.45; -0.21] | -0.51 | +0.19 [+0.06; +0.31] |

**G — be0.6 TP1.5 SL3 T60** (B1+B2 en iyi başabaş (net -0.38))

| senaryo | B1 net | B2 net | B3 net | 90 gün net [%95] | 90 gün rastgele | 90 gün sinyal−rastgele [%95] |
|---|---|---|---|---|---|---|
| 0 sn / %0.05 | -0.24 | -0.21 | -0.07 | -0.18 [-0.26; -0.09] | -0.32 | +0.14 [+0.05; +0.23] |
| 0 sn / %0.15 | -0.40 | -0.37 | -0.22 | -0.34 [-0.43; -0.24] | -0.51 | +0.17 [+0.08; +0.27] |
| 60 sn / %0.05 | -0.28 | -0.20 | -0.07 | -0.18 [-0.25; -0.12] | -0.32 | +0.13 [+0.06; +0.21] |
| 60 sn / %0.15 | -0.42 | -0.36 | -0.22 | -0.34 [-0.41; -0.27] | -0.51 | +0.17 [+0.09; +0.24] |
| 120 sn / %0.05 | -0.30 | -0.07 | -0.08 | -0.13 [-0.20; -0.07] | -0.32 | +0.18 [+0.12; +0.25] |
| 120 sn / %0.15 | -0.45 | -0.24 | -0.23 | -0.29 [-0.36; -0.22] | -0.51 | +0.21 [+0.14; +0.29] |

## 7. Karar (otomatik kural)
Kural: bir (kaynak, seçim) OOS'ta **net>0** sayılması için birincil senaryoda OOS net %95 alt sınırı > 0 olmalı; **şansı geçmesi** için de sinyal−rastgele(aynı çıkış) alt sınırı > 0.
- Birincil senaryoda walk-forward satırı: 12; OOS ortalaması > 0 olan: 0; OOS net alt sınırı > 0 olan: 0; ayrıca şansı da geçen: 0.
- **Hiçbir (kaynak, seçim, OOS blok) kombinasyonu hem net-pozitif (alt sınır > 0) hem de aynı çıkışlı rastgele girişten anlamlı biçimde iyi değil.**

## 8. Canlı ileri test
Canlı sinyaller (journal + gerçek bildirimler) için komut (backend/ içinden): `python scripts/exit_sim_study.py --source live --since 2026-09-18 --cache-dir <scratch>/exitsim_live` → `work/exitsim/report_live_2026-09-18.md`; donmuş hücreler `work/exitsim/chosen_cells.json`. **31 Ekim'de yeniden koşmak için:** önce yeni mumları çekin (`python scripts/fast_backfill_klines.py --days 20 --timeframe 1m`, sonra `--timeframe 5m`), sonra `python scripts/exit_sim_study.py --source live --since 2026-10-17 --cache-dir <yeni-boş-klasör>` (since = bu çalışmanın veri sonu; böylece 18 Eyl–17 Eki bölümüyle çakışmayan SAF ileri dönem ölçülür; hücreler aynen donmuş listeden okunur).

Otomatik özet (birincil senaryo, HA'dan donmuş 4 hücre): 

| canlı kaynak | n | donmuş hücrede net>0 | en iyi donmuş hücre neti [%95] | sinyal−rastgele aralığı (donmuş hücreler) | tüm ızgarada net>0 |
|---|---|---|---|---|---|
| CANLI_ADAY | 6299 | 0/4 | be0.6 TPcand SL3 T60: -0.49 [-0.54; -0.44] | +0.01 … +0.06 | 0/60 |
| BILDIRIM_hepsi | 3459 | 0/4 | trail act0.5 gap0.8 SL3 T30: -0.52 [-0.59; -0.45] | +0.04 … +0.04 | 0/60 |
| BILDIRIM_global_lead_lag | 717 | 0/4 | trail act0.5 gap0.8 SL3 T30: -0.68 [-0.79; -0.57] | -0.20 … -0.15 | 0/60 |
| BILDIRIM_llm_ikinci_goz | 258 | 0/4 | atr k1 act1 SL1.5 T60: -0.56 [-0.71; -0.40] | -0.21 … -0.05 | 0/60 |
| BILDIRIM_notr | 385 | 0/4 | trail act0.5 gap0.8 SL3 T30: -0.61 [-0.82; -0.40] | -0.34 … -0.05 | 0/60 |
| BILDIRIM_trend_devam | 984 | 0/4 | atr k1 act1 SL1.5 T60: -0.31 [-0.46; -0.16] | +0.20 … +0.28 | 0/60 |
| BILDIRIM_unified | 1090 | 0/4 | be0.6 TPcand SL3 T60: -0.47 [-0.62; -0.32] | +0.03 … +0.05 | 0/60 |


Kaynak: canlı `velocity_candidates` (non-rescan, passes, rank ≤ 10; 60 dk bölümler) ve gerçek `monitoring_notifications` (hepsi; mod bazında). 1 dk mumlar DB'den. Hücreler `chosen_cells.json`'dan (backtest koşusunun B1+B2 / B1 seçimleri; donmuş). Senaryolar: 0/60/120 sn × %0,05 / %0,15; birincil 60 sn / %0.15.
Rastgele taban: aynı sembol, aynı İstanbul saati, herhangi bir canlı sinyalden ≥ 2 sa uzak (rnd) ve oynaklığı eşleşmiş (rndv); canlı dönem boyunca. Veri sonu nedeniyle 125 dk'dan yakın sinyaller atılır (sonuçtan bağımsız).

### Örneklem
| kaynak | sinyal n | rastgele n | rastgele(oyn.) n |
|---|---|---|---|
| CANLI_ADAY | 6299 | 12598 | 11904 |
| BILDIRIM_hepsi | 3459 | 6918 | 5754 |
| BILDIRIM_bilinmiyor | 4 | 8 | 8 |
| BILDIRIM_global_lead_lag | 717 | 1434 | 1274 |
| BILDIRIM_llm_ikinci_goz | 258 | 516 | 454 |
| BILDIRIM_notr | 385 | 770 | 480 |
| BILDIRIM_trend_devam | 984 | 1968 | 1398 |
| BILDIRIM_unified | 1090 | 2180 | 2110 |
| BILDIRIM_v_donusu | 21 | 42 | 30 |

n < 50 olan kaynaklar (BILDIRIM_bilinmiyor, BILDIRIM_v_donusu) aşağıdaki tablolardan çıkarıldı.

### Donmuş hücreler (HA'da B1+B2'den seçilmiş; birincil senaryo)
| kaynak | hücre | n | net ort. [%95] | t | kazanma % | kazanç/kayıp | çıkış payı TP/SL/iz/başabaş/zaman | rastgele net | sinyal−rastgele [%95] | sinyal−rastgele(oyn.) [%95] |
|---|---|---|---|---|---|---|---|---|---|---|
| CANLI_ADAY | fixed TPcand SL1.5 T120 | 6299 | -0.52 [-0.58; -0.46] | -17.5 | 36.9 | +1.65/-1.78 | 34 / 56 / 0 / 0 / 10 | -0.52 | +0.01 [-0.09; +0.10] | +0.11 [-0.01; +0.22] |
| CANLI_ADAY | trail act0.5 gap0.8 SL3 T30 | 6299 | -0.51 [-0.55; -0.48] | -26.1 | 32.2 | +0.99/-1.23 | 0 / 9 / 55 / 0 / 36 | -0.54 | +0.03 [-0.02; +0.08] | +0.06 [-0.02; +0.14] |
| CANLI_ADAY | atr k1 act1 SL1.5 T60 | 6299 | -0.52 [-0.57; -0.47] | -21.8 | 36.0 | +1.19/-1.48 | 0 / 42 / 44 / 0 / 15 | -0.54 | +0.02 [-0.04; +0.09] | +0.11 [+0.03; +0.18] |
| CANLI_ADAY | be0.6 TPcand SL3 T60 | 6299 | -0.49 [-0.54; -0.44] | -19.9 | 28.4 | +1.56/-1.30 | 24 / 14 / 0 / 37 / 25 | -0.54 | +0.06 [-0.01; +0.13] | +0.10 [+0.02; +0.18] |
| BILDIRIM_hepsi | fixed TPcand SL1.5 T120 | 3459 | -0.55 [-0.65; -0.45] | -10.9 | 29.9 | +2.40/-1.81 | 27 / 65 / 0 / 0 / 8 | -0.59 | +0.04 [-0.09; +0.16] | +0.14 [-0.01; +0.29] |
| BILDIRIM_hepsi | trail act0.5 gap0.8 SL3 T30 | 3459 | -0.52 [-0.59; -0.45] | -14.2 | 33.4 | +1.14/-1.35 | 0 / 14 / 65 / 0 / 21 | -0.56 | +0.04 [-0.04; +0.11] | +0.07 [-0.03; +0.17] |
| BILDIRIM_hepsi | atr k1 act1 SL1.5 T60 | 3459 | -0.53 [-0.61; -0.46] | -13.8 | 31.4 | +1.62/-1.52 | 0 / 48 / 45 / 0 / 7 | -0.57 | +0.04 [-0.05; +0.13] | +0.10 [+0.01; +0.20] |
| BILDIRIM_hepsi | be0.6 TPcand SL3 T60 | 3459 | -0.54 [-0.62; -0.46] | -12.8 | 21.4 | +2.33/-1.32 | 19 / 19 / 0 / 48 / 15 | -0.58 | +0.04 [-0.06; +0.14] | +0.09 [-0.01; +0.20] |
| BILDIRIM_global_lead_lag | fixed TPcand SL1.5 T120 | 717 | -0.72 [-0.87; -0.58] | -9.8 | 24.1 | +2.72/-1.82 | 23 / 71 / 0 / 0 / 6 | -0.53 | -0.20 [-0.39; -0.01] | -0.04 [-0.34; +0.27] |
| BILDIRIM_global_lead_lag | trail act0.5 gap0.8 SL3 T30 | 717 | -0.68 [-0.79; -0.57] | -11.8 | 30.4 | +1.04/-1.43 | 0 / 18 / 65 / 0 / 17 | -0.53 | -0.15 [-0.27; -0.03] | -0.10 [-0.27; +0.07] |
| BILDIRIM_global_lead_lag | atr k1 act1 SL1.5 T60 | 717 | -0.69 [-0.87; -0.52] | -7.7 | 26.6 | +1.63/-1.54 | 0 / 51 / 43 / 0 / 6 | -0.54 | -0.16 [-0.35; +0.03] | -0.04 [-0.25; +0.17] |
| BILDIRIM_global_lead_lag | be0.6 TPcand SL3 T60 | 717 | -0.72 [-0.86; -0.58] | -10.2 | 16.7 | +2.48/-1.37 | 15 / 22 / 0 / 50 / 13 | -0.54 | -0.18 [-0.34; -0.03] | -0.09 [-0.28; +0.09] |
| BILDIRIM_llm_ikinci_goz | fixed TPcand SL1.5 T120 | 258 | -0.62 [-0.82; -0.42] | -6.0 | 27.5 | +2.34/-1.74 | 21 / 63 / 0 / 0 / 16 | -0.49 | -0.13 [-0.37; +0.11] | +0.10 [-0.18; +0.37] |
| BILDIRIM_llm_ikinci_goz | trail act0.5 gap0.8 SL3 T30 | 258 | -0.67 [-0.84; -0.50] | -7.8 | 31.4 | +0.92/-1.40 | 0 / 14 / 55 / 0 / 31 | -0.55 | -0.12 [-0.30; +0.06] | -0.07 [-0.27; +0.14] |
| BILDIRIM_llm_ikinci_goz | atr k1 act1 SL1.5 T60 | 258 | -0.56 [-0.71; -0.40] | -7.1 | 32.2 | +1.39/-1.48 | 0 / 46 / 42 / 0 / 12 | -0.50 | -0.05 [-0.23; +0.12] | +0.09 [-0.11; +0.28] |
| BILDIRIM_llm_ikinci_goz | be0.6 TPcand SL3 T60 | 258 | -0.77 [-0.96; -0.57] | -7.6 | 17.1 | +2.33/-1.40 | 13 / 21 / 0 / 45 / 21 | -0.55 | -0.21 [-0.43; +0.01] | -0.10 [-0.34; +0.14] |
| BILDIRIM_notr | fixed TPcand SL1.5 T120 | 385 | -0.82 [-1.04; -0.60] | -7.4 | 24.2 | +2.53/-1.89 | 24 / 74 / 0 / 0 / 3 | -0.50 | -0.32 [-0.56; -0.08] | -0.00 [-0.28; +0.27] |
| BILDIRIM_notr | trail act0.5 gap0.8 SL3 T30 | 385 | -0.61 [-0.82; -0.40] | -5.7 | 36.6 | +1.11/-1.60 | 0 / 21 / 74 / 0 / 6 | -0.56 | -0.05 [-0.27; +0.17] | +0.02 [-0.31; +0.35] |
| BILDIRIM_notr | atr k1 act1 SL1.5 T60 | 385 | -0.88 [-1.05; -0.72] | -10.6 | 20.8 | +2.17/-1.68 | 0 / 62 / 35 / 0 / 3 | -0.54 | -0.34 [-0.52; -0.17] | -0.10 [-0.31; +0.10] |
| BILDIRIM_notr | be0.6 TPcand SL3 T60 | 385 | -0.69 [-0.88; -0.50] | -7.0 | 18.7 | +2.55/-1.43 | 18 / 24 / 0 / 54 / 3 | -0.54 | -0.15 [-0.35; +0.05] | +0.02 [-0.27; +0.31] |
| BILDIRIM_trend_devam | fixed TPcand SL1.5 T120 | 984 | -0.31 [-0.45; -0.17] | -4.5 | 34.2 | +2.67/-1.86 | 34 / 65 / 0 / 0 / 1 | -0.59 | +0.28 [+0.09; +0.46] | +0.46 [+0.26; +0.66] |
| BILDIRIM_trend_devam | trail act0.5 gap0.8 SL3 T30 | 984 | -0.35 [-0.49; -0.22] | -5.0 | 37.3 | +1.46/-1.43 | 0 / 17 / 74 / 0 / 10 | -0.55 | +0.20 [+0.05; +0.34] | +0.21 [+0.01; +0.40] |
| BILDIRIM_trend_devam | atr k1 act1 SL1.5 T60 | 984 | -0.31 [-0.46; -0.16] | -4.0 | 31.8 | +2.37/-1.56 | 0 / 49 / 49 / 0 / 2 | -0.58 | +0.27 [+0.11; +0.43] | +0.39 [+0.22; +0.55] |
| BILDIRIM_trend_devam | be0.6 TPcand SL3 T60 | 984 | -0.34 [-0.49; -0.19] | -4.5 | 26.0 | +2.60/-1.38 | 25 / 21 / 0 / 48 / 5 | -0.60 | +0.25 [+0.09; +0.42] | +0.28 [+0.10; +0.47] |
| BILDIRIM_unified | fixed TPcand SL1.5 T120 | 1090 | -0.51 [-0.68; -0.35] | -6.2 | 32.8 | +1.98/-1.73 | 26 / 58 / 0 / 0 / 17 | -0.55 | +0.04 [-0.15; +0.23] | +0.19 [-0.00; +0.38] |
| BILDIRIM_unified | trail act0.5 gap0.8 SL3 T30 | 1090 | -0.49 [-0.60; -0.38] | -8.8 | 31.7 | +0.93/-1.14 | 0 / 8 / 57 / 0 / 35 | -0.54 | +0.05 [-0.06; +0.17] | +0.13 [+0.00; +0.26] |
| BILDIRIM_unified | atr k1 act1 SL1.5 T60 | 1090 | -0.50 [-0.61; -0.38] | -8.5 | 38.3 | +0.99/-1.41 | 0 / 39 / 48 / 0 / 13 | -0.52 | +0.03 [-0.10; +0.16] | +0.13 [-0.00; +0.27] |
| BILDIRIM_unified | be0.6 TPcand SL3 T60 | 1090 | -0.47 [-0.62; -0.32] | -6.1 | 22.5 | +1.91/-1.16 | 17 / 12 / 0 / 44 / 26 | -0.52 | +0.05 [-0.11; +0.22] | +0.16 [-0.01; +0.33] |

### Donmuş hücreler — senaryo duyarlılığı (net ort.)

**CANLI_ADAY**

| hücre | 0 sn / %0.05 | 0 sn / %0.15 | 60 sn / %0.05 | 60 sn / %0.15 | 120 sn / %0.05 | 120 sn / %0.15 |
|---|---|---|---|---|---|---|
| fixed TPcand SL1.5 T120 | -0.34 | -0.52 | -0.37 | -0.52 | -0.37 | -0.54 |
| trail act0.5 gap0.8 SL3 T30 | -0.31 | -0.51 | -0.31 | -0.51 | -0.30 | -0.51 |
| atr k1 act1 SL1.5 T60 | -0.31 | -0.51 | -0.33 | -0.52 | -0.33 | -0.53 |
| be0.6 TPcand SL3 T60 | -0.32 | -0.49 | -0.33 | -0.49 | -0.32 | -0.50 |

**BILDIRIM_hepsi**

| hücre | 0 sn / %0.05 | 0 sn / %0.15 | 60 sn / %0.05 | 60 sn / %0.15 | 120 sn / %0.05 | 120 sn / %0.15 |
|---|---|---|---|---|---|---|
| fixed TPcand SL1.5 T120 | -0.42 | -0.57 | -0.39 | -0.55 | -0.39 | -0.54 |
| trail act0.5 gap0.8 SL3 T30 | -0.35 | -0.57 | -0.31 | -0.52 | -0.34 | -0.55 |
| atr k1 act1 SL1.5 T60 | -0.39 | -0.57 | -0.34 | -0.53 | -0.36 | -0.54 |
| be0.6 TPcand SL3 T60 | -0.38 | -0.56 | -0.35 | -0.54 | -0.37 | -0.56 |

**BILDIRIM_global_lead_lag**

| hücre | 0 sn / %0.05 | 0 sn / %0.15 | 60 sn / %0.05 | 60 sn / %0.15 | 120 sn / %0.05 | 120 sn / %0.15 |
|---|---|---|---|---|---|---|
| fixed TPcand SL1.5 T120 | -0.53 | -0.68 | -0.53 | -0.72 | -0.53 | -0.70 |
| trail act0.5 gap0.8 SL3 T30 | -0.48 | -0.71 | -0.45 | -0.68 | -0.50 | -0.70 |
| atr k1 act1 SL1.5 T60 | -0.47 | -0.64 | -0.51 | -0.69 | -0.49 | -0.67 |
| be0.6 TPcand SL3 T60 | -0.57 | -0.72 | -0.52 | -0.72 | -0.51 | -0.70 |

**BILDIRIM_llm_ikinci_goz**

| hücre | 0 sn / %0.05 | 0 sn / %0.15 | 60 sn / %0.05 | 60 sn / %0.15 | 120 sn / %0.05 | 120 sn / %0.15 |
|---|---|---|---|---|---|---|
| fixed TPcand SL1.5 T120 | -0.62 | -0.82 | -0.47 | -0.62 | -0.52 | -0.73 |
| trail act0.5 gap0.8 SL3 T30 | -0.60 | -0.84 | -0.44 | -0.67 | -0.46 | -0.69 |
| atr k1 act1 SL1.5 T60 | -0.60 | -0.79 | -0.38 | -0.56 | -0.40 | -0.61 |
| be0.6 TPcand SL3 T60 | -0.68 | -0.93 | -0.55 | -0.77 | -0.55 | -0.77 |

**BILDIRIM_notr**

| hücre | 0 sn / %0.05 | 0 sn / %0.15 | 60 sn / %0.05 | 60 sn / %0.15 | 120 sn / %0.05 | 120 sn / %0.15 |
|---|---|---|---|---|---|---|
| fixed TPcand SL1.5 T120 | -0.78 | -0.94 | -0.68 | -0.82 | -0.71 | -0.83 |
| trail act0.5 gap0.8 SL3 T30 | -0.56 | -0.78 | -0.40 | -0.61 | -0.52 | -0.72 |
| atr k1 act1 SL1.5 T60 | -0.88 | -1.05 | -0.73 | -0.88 | -0.76 | -0.93 |
| be0.6 TPcand SL3 T60 | -0.55 | -0.77 | -0.46 | -0.69 | -0.62 | -0.77 |

**BILDIRIM_trend_devam**

| hücre | 0 sn / %0.05 | 0 sn / %0.15 | 60 sn / %0.05 | 60 sn / %0.15 | 120 sn / %0.05 | 120 sn / %0.15 |
|---|---|---|---|---|---|---|
| fixed TPcand SL1.5 T120 | -0.27 | -0.42 | -0.19 | -0.31 | -0.20 | -0.32 |
| trail act0.5 gap0.8 SL3 T30 | -0.20 | -0.41 | -0.16 | -0.35 | -0.16 | -0.38 |
| atr k1 act1 SL1.5 T60 | -0.25 | -0.42 | -0.11 | -0.31 | -0.16 | -0.35 |
| be0.6 TPcand SL3 T60 | -0.21 | -0.39 | -0.17 | -0.34 | -0.20 | -0.40 |

**BILDIRIM_unified**

| hücre | 0 sn / %0.05 | 0 sn / %0.15 | 60 sn / %0.05 | 60 sn / %0.15 | 120 sn / %0.05 | 120 sn / %0.15 |
|---|---|---|---|---|---|---|
| fixed TPcand SL1.5 T120 | -0.28 | -0.43 | -0.32 | -0.51 | -0.31 | -0.47 |
| trail act0.5 gap0.8 SL3 T30 | -0.28 | -0.48 | -0.28 | -0.49 | -0.31 | -0.51 |
| atr k1 act1 SL1.5 T60 | -0.24 | -0.44 | -0.28 | -0.50 | -0.29 | -0.47 |
| be0.6 TPcand SL3 T60 | -0.26 | -0.44 | -0.30 | -0.47 | -0.30 | -0.48 |

### Tüm ızgara özeti (birincil senaryo)
| kaynak | hücre sayısı | net>0 hücre | ortalama hücre neti | en iyi hücre | en iyi net [%95] | rastgele ort. | sinyal−rastgele ort. |
|---|---|---|---|---|---|---|---|
| CANLI_ADAY | 60 | 0 | -0.53 | be0.6 TPcand SL1.5 T60 | -0.47 [-0.52; -0.43] | -0.55 | +0.02 |
| BILDIRIM_hepsi | 60 | 0 | -0.56 | trail act0.5 gap0.8 SL1.5 T60 | -0.48 [-0.54; -0.42] | -0.57 | +0.01 |
| BILDIRIM_global_lead_lag | 60 | 0 | -0.70 | be0.6 TP1.5 SL1.5 T60 | -0.59 [-0.73; -0.45] | -0.53 | -0.17 |
| BILDIRIM_llm_ikinci_goz | 60 | 0 | -0.70 | trail act1 gap0.8 SL1.5 T60 | -0.53 [-0.67; -0.40] | -0.51 | -0.19 |
| BILDIRIM_notr | 60 | 0 | -0.79 | be0.6 TP1.5 SL1.5 T60 | -0.51 [-0.62; -0.39] | -0.54 | -0.25 |
| BILDIRIM_trend_devam | 60 | 0 | -0.39 | trail act0.5 gap1.2 SL3 T120 | -0.31 [-0.47; -0.15] | -0.58 | +0.19 |
| BILDIRIM_unified | 60 | 0 | -0.50 | trail act1 gap1.2 SL3 T120 | -0.42 [-0.64; -0.19] | -0.53 | +0.04 |

Not: bu bölümdeki 'en iyi hücre' iç-örneklemdir; yalnız donmuş hücreler ileri testtir.

## Ek A — Tam ızgara (birincil senaryo; net ort. / t; B1 B2 B3; 90 gün sinyal−rastgele)

### HA

| hücre | aile | n (90 gün) | net 90g | t | B1 | B2 | B3 | rastgele 90g | sinyal−rastgele 90g [%95] | sinyal−rastgele(oyn.) 90g |
|---|---|---|---|---|---|---|---|---|---|---|
| fixed TPcand SL1.5 T30 | fixed | 20343 | -0.54 | -42.5 | -0.55 | -0.51 | -0.56 | -0.54 | -0.00 [-0.03; +0.03] | +0.01 |
| fixed TPcand SL1.5 T60 | fixed | 20343 | -0.53 | -32.6 | -0.55 | -0.49 | -0.57 | -0.55 | +0.01 [-0.02; +0.05] | +0.03 |
| fixed TPcand SL1.5 T120 | fixed | 20343 | -0.53 | -26.5 | -0.54 | -0.48 | -0.58 | -0.54 | +0.00 [-0.05; +0.06] | +0.06 |
| fixed TPcand SL3 T30 | fixed | 20343 | -0.56 | -35.3 | -0.54 | -0.52 | -0.61 | -0.52 | -0.03 [-0.07; -0.00] | -0.05 |
| fixed TPcand SL3 T60 | fixed | 20343 | -0.56 | -28.0 | -0.54 | -0.51 | -0.62 | -0.52 | -0.04 [-0.08; +0.01] | -0.05 |
| fixed TPcand SL3 T120 | fixed | 20343 | -0.57 | -21.6 | -0.53 | -0.53 | -0.64 | -0.50 | -0.07 [-0.14; -0.01] | -0.04 |
| fixed TP1.5 SL1.5 T30 | fixed | 20343 | -0.52 | -49.4 | -0.55 | -0.50 | -0.52 | -0.53 | +0.01 [-0.01; +0.03] | +0.01 |
| fixed TP1.5 SL1.5 T60 | fixed | 20343 | -0.52 | -41.9 | -0.55 | -0.49 | -0.53 | -0.53 | +0.00 [-0.03; +0.04] | +0.00 |
| fixed TP1.5 SL1.5 T120 | fixed | 20343 | -0.53 | -39.0 | -0.55 | -0.50 | -0.53 | -0.50 | -0.02 [-0.07; +0.02] | +0.01 |
| fixed TP1.5 SL3 T30 | fixed | 20343 | -0.53 | -40.8 | -0.53 | -0.49 | -0.55 | -0.52 | -0.01 [-0.04; +0.02] | -0.03 |
| fixed TP1.5 SL3 T60 | fixed | 20343 | -0.54 | -34.3 | -0.54 | -0.50 | -0.56 | -0.50 | -0.03 [-0.07; +0.00] | -0.06 |
| fixed TP1.5 SL3 T120 | fixed | 20343 | -0.55 | -28.9 | -0.56 | -0.51 | -0.57 | -0.47 | -0.08 [-0.13; -0.03] | -0.07 |
| trail act0.5 gap0.4 SL1.5 T60 | trail | 20343 | -0.53 | -65.2 | -0.55 | -0.53 | -0.51 | -0.54 | +0.01 [-0.02; +0.03] | +0.01 |
| trail act0.5 gap0.8 SL1.5 T60 | trail | 20343 | -0.53 | -54.9 | -0.55 | -0.52 | -0.51 | -0.55 | +0.02 [-0.00; +0.05] | +0.04 |
| trail act0.5 gap1.2 SL1.5 T60 | trail | 20343 | -0.53 | -45.3 | -0.56 | -0.53 | -0.51 | -0.56 | +0.03 [-0.00; +0.06] | +0.05 |
| trail act1 gap0.4 SL1.5 T60 | trail | 20343 | -0.54 | -51.6 | -0.55 | -0.53 | -0.52 | -0.54 | +0.01 [-0.02; +0.03] | +0.01 |
| trail act1 gap0.8 SL1.5 T60 | trail | 20343 | -0.53 | -46.3 | -0.55 | -0.53 | -0.51 | -0.55 | +0.02 [-0.01; +0.05] | +0.03 |
| trail act1 gap1.2 SL1.5 T60 | trail | 20343 | -0.53 | -41.9 | -0.56 | -0.53 | -0.52 | -0.56 | +0.02 [-0.01; +0.06] | +0.04 |
| trail act1.5 gap0.4 SL1.5 T60 | trail | 20343 | -0.54 | -45.1 | -0.56 | -0.53 | -0.53 | -0.55 | +0.01 [-0.03; +0.04] | +0.02 |
| trail act1.5 gap0.8 SL1.5 T60 | trail | 20343 | -0.54 | -41.5 | -0.56 | -0.52 | -0.53 | -0.55 | +0.02 [-0.02; +0.05] | +0.03 |
| trail act1.5 gap1.2 SL1.5 T60 | trail | 20343 | -0.54 | -39.7 | -0.57 | -0.52 | -0.53 | -0.56 | +0.01 [-0.02; +0.05] | +0.03 |
| trail act0.5 gap0.4 SL3 T60 | trail | 20343 | -0.53 | -48.8 | -0.52 | -0.52 | -0.53 | -0.51 | -0.01 [-0.04; +0.01] | -0.04 |
| trail act0.5 gap0.8 SL3 T60 | trail | 20343 | -0.52 | -43.1 | -0.53 | -0.52 | -0.53 | -0.53 | +0.01 [-0.02; +0.04] | -0.00 |
| trail act0.5 gap1.2 SL3 T60 | trail | 20343 | -0.53 | -37.2 | -0.53 | -0.52 | -0.53 | -0.54 | +0.01 [-0.02; +0.04] | +0.01 |
| trail act1 gap0.4 SL3 T60 | trail | 20343 | -0.55 | -42.3 | -0.55 | -0.54 | -0.55 | -0.52 | -0.03 [-0.06; +0.00] | -0.05 |
| trail act1 gap0.8 SL3 T60 | trail | 20343 | -0.54 | -39.6 | -0.54 | -0.54 | -0.55 | -0.53 | -0.01 [-0.05; +0.02] | -0.02 |
| trail act1 gap1.2 SL3 T60 | trail | 20343 | -0.55 | -37.1 | -0.54 | -0.54 | -0.55 | -0.54 | -0.01 [-0.05; +0.02] | -0.01 |
| trail act1.5 gap0.4 SL3 T60 | trail | 20343 | -0.56 | -36.8 | -0.56 | -0.54 | -0.57 | -0.52 | -0.04 [-0.07; -0.00] | -0.05 |
| trail act1.5 gap0.8 SL3 T60 | trail | 20343 | -0.55 | -34.8 | -0.55 | -0.53 | -0.57 | -0.53 | -0.02 [-0.06; +0.01] | -0.03 |
| trail act1.5 gap1.2 SL3 T60 | trail | 20343 | -0.56 | -33.9 | -0.56 | -0.54 | -0.57 | -0.53 | -0.02 [-0.06; +0.01] | -0.03 |
| trail act0.5 gap0.4 SL3 T30 | trail | 20343 | -0.52 | -57.4 | -0.52 | -0.50 | -0.53 | -0.52 | +0.00 [-0.02; +0.03] | -0.02 |
| trail act0.5 gap0.8 SL3 T30 | trail | 20343 | -0.51 | -49.7 | -0.52 | -0.50 | -0.52 | -0.53 | +0.02 [-0.01; +0.04] | +0.01 |
| trail act0.5 gap1.2 SL3 T30 | trail | 20343 | -0.52 | -44.7 | -0.52 | -0.50 | -0.53 | -0.53 | +0.01 [-0.01; +0.04] | +0.01 |
| trail act1 gap0.4 SL3 T30 | trail | 20343 | -0.54 | -46.7 | -0.54 | -0.52 | -0.55 | -0.52 | -0.01 [-0.04; +0.01] | -0.03 |
| trail act1 gap0.8 SL3 T30 | trail | 20343 | -0.53 | -44.1 | -0.53 | -0.52 | -0.55 | -0.53 | -0.01 [-0.03; +0.02] | -0.02 |
| trail act1 gap1.2 SL3 T30 | trail | 20343 | -0.54 | -41.9 | -0.53 | -0.52 | -0.55 | -0.53 | -0.01 [-0.03; +0.02] | -0.01 |
| trail act1.5 gap0.4 SL3 T30 | trail | 20343 | -0.54 | -41.8 | -0.55 | -0.53 | -0.56 | -0.53 | -0.02 [-0.05; +0.01] | -0.03 |
| trail act1.5 gap0.8 SL3 T30 | trail | 20343 | -0.54 | -39.6 | -0.54 | -0.52 | -0.56 | -0.53 | -0.01 [-0.04; +0.01] | -0.02 |
| trail act1.5 gap1.2 SL3 T30 | trail | 20343 | -0.54 | -38.8 | -0.54 | -0.53 | -0.56 | -0.53 | -0.02 [-0.05; +0.01] | -0.02 |
| trail act0.5 gap0.4 SL3 T120 | trail | 20343 | -0.53 | -45.2 | -0.53 | -0.54 | -0.54 | -0.49 | -0.04 [-0.08; -0.01] | -0.03 |
| trail act0.5 gap0.8 SL3 T120 | trail | 20343 | -0.53 | -41.0 | -0.54 | -0.54 | -0.53 | -0.51 | -0.02 [-0.06; +0.02] | +0.01 |
| trail act0.5 gap1.2 SL3 T120 | trail | 20343 | -0.54 | -35.3 | -0.54 | -0.54 | -0.54 | -0.53 | -0.01 [-0.06; +0.04] | +0.04 |
| trail act1 gap0.4 SL3 T120 | trail | 20343 | -0.56 | -36.9 | -0.56 | -0.56 | -0.55 | -0.49 | -0.06 [-0.11; -0.02] | -0.04 |
| trail act1 gap0.8 SL3 T120 | trail | 20343 | -0.56 | -34.9 | -0.56 | -0.56 | -0.55 | -0.51 | -0.05 [-0.09; +0.00] | -0.01 |
| trail act1 gap1.2 SL3 T120 | trail | 20343 | -0.56 | -32.2 | -0.55 | -0.56 | -0.56 | -0.52 | -0.04 [-0.09; +0.01] | +0.02 |
| trail act1.5 gap0.4 SL3 T120 | trail | 20343 | -0.58 | -31.6 | -0.58 | -0.56 | -0.58 | -0.50 | -0.08 [-0.13; -0.03] | -0.04 |
| trail act1.5 gap0.8 SL3 T120 | trail | 20343 | -0.57 | -29.7 | -0.57 | -0.55 | -0.58 | -0.51 | -0.06 [-0.11; -0.01] | -0.02 |
| trail act1.5 gap1.2 SL3 T120 | trail | 20343 | -0.57 | -28.5 | -0.58 | -0.56 | -0.59 | -0.52 | -0.05 [-0.11; +0.00] | -0.00 |
| atr k1 act1 SL1.5 T60 | atr | 20343 | -0.55 | -41.6 | -0.57 | -0.54 | -0.53 | -0.54 | -0.00 [-0.04; +0.03] | +0.01 |
| atr k1.5 act1 SL1.5 T60 | atr | 20343 | -0.56 | -38.1 | -0.59 | -0.55 | -0.55 | -0.55 | -0.01 [-0.05; +0.02] | +0.01 |
| atr k2 act1 SL1.5 T60 | atr | 20343 | -0.56 | -33.3 | -0.60 | -0.54 | -0.55 | -0.55 | -0.01 [-0.05; +0.03] | +0.02 |
| atr k1 act1 SL3 T60 | atr | 20343 | -0.57 | -36.0 | -0.57 | -0.56 | -0.57 | -0.52 | -0.05 [-0.08; -0.01] | -0.06 |
| atr k1.5 act1 SL3 T60 | atr | 20343 | -0.58 | -31.4 | -0.59 | -0.57 | -0.59 | -0.53 | -0.06 [-0.10; -0.02] | -0.06 |
| atr k2 act1 SL3 T60 | atr | 20343 | -0.60 | -29.1 | -0.62 | -0.57 | -0.60 | -0.53 | -0.07 [-0.11; -0.02] | -0.07 |
| be0.6 TPcand SL1.5 T60 | be | 20343 | -0.53 | -43.1 | -0.55 | -0.50 | -0.53 | -0.55 | +0.02 [-0.01; +0.05] | +0.04 |
| be0.6 TPcand SL3 T60 | be | 20343 | -0.53 | -35.2 | -0.54 | -0.50 | -0.55 | -0.53 | -0.00 [-0.04; +0.03] | -0.01 |
| be0.6 TP1.5 SL1.5 T60 | be | 20343 | -0.52 | -52.0 | -0.56 | -0.51 | -0.51 | -0.53 | +0.01 [-0.02; +0.03] | +0.01 |
| be0.6 TP1.5 SL3 T60 | be | 20343 | -0.53 | -41.0 | -0.54 | -0.51 | -0.53 | -0.51 | -0.02 [-0.05; +0.01] | -0.04 |
| be0.6+trail act1 gap0.8 SL1.5 T60 | be_trail | 20343 | -0.53 | -53.0 | -0.56 | -0.52 | -0.51 | -0.55 | +0.02 [-0.00; +0.05] | +0.03 |
| be0.6+trail act1 gap0.8 SL3 T60 | be_trail | 20343 | -0.53 | -42.2 | -0.54 | -0.52 | -0.53 | -0.53 | -0.00 [-0.03; +0.03] | -0.01 |

### E

| hücre | aile | n (90 gün) | net 90g | t | B1 | B2 | B3 | rastgele 90g | sinyal−rastgele 90g [%95] | sinyal−rastgele(oyn.) 90g |
|---|---|---|---|---|---|---|---|---|---|---|
| fixed TPcand SL1.5 T30 | fixed | 15357 | -0.50 | -27.1 | -0.51 | -0.49 | -0.51 | -0.54 | +0.04 [-0.00; +0.08] | +0.05 |
| fixed TPcand SL1.5 T60 | fixed | 15357 | -0.50 | -23.4 | -0.52 | -0.47 | -0.51 | -0.55 | +0.06 [+0.01; +0.10] | +0.07 |
| fixed TPcand SL1.5 T120 | fixed | 15357 | -0.52 | -18.3 | -0.53 | -0.49 | -0.54 | -0.55 | +0.03 [-0.04; +0.10] | +0.08 |
| fixed TPcand SL3 T30 | fixed | 15357 | -0.51 | -22.5 | -0.53 | -0.48 | -0.51 | -0.53 | +0.02 [-0.02; +0.07] | +0.02 |
| fixed TPcand SL3 T60 | fixed | 15357 | -0.49 | -18.0 | -0.53 | -0.45 | -0.50 | -0.53 | +0.04 [-0.02; +0.10] | +0.03 |
| fixed TPcand SL3 T120 | fixed | 15357 | -0.52 | -14.1 | -0.56 | -0.49 | -0.52 | -0.51 | -0.02 [-0.10; +0.07] | +0.01 |
| fixed TP1.5 SL1.5 T30 | fixed | 15357 | -0.47 | -29.5 | -0.46 | -0.49 | -0.47 | -0.53 | +0.06 [+0.02; +0.09] | +0.06 |
| fixed TP1.5 SL1.5 T60 | fixed | 15357 | -0.46 | -27.2 | -0.46 | -0.47 | -0.45 | -0.53 | +0.07 [+0.03; +0.11] | +0.07 |
| fixed TP1.5 SL1.5 T120 | fixed | 15357 | -0.47 | -24.4 | -0.45 | -0.48 | -0.47 | -0.51 | +0.04 [-0.01; +0.09] | +0.07 |
| fixed TP1.5 SL3 T30 | fixed | 15357 | -0.47 | -24.4 | -0.46 | -0.48 | -0.47 | -0.52 | +0.05 [+0.01; +0.09] | +0.03 |
| fixed TP1.5 SL3 T60 | fixed | 15357 | -0.45 | -20.7 | -0.45 | -0.44 | -0.44 | -0.50 | +0.06 [+0.01; +0.11] | +0.03 |
| fixed TP1.5 SL3 T120 | fixed | 15357 | -0.45 | -17.8 | -0.46 | -0.45 | -0.46 | -0.47 | +0.01 [-0.05; +0.08] | +0.01 |
| trail act0.5 gap0.4 SL1.5 T60 | trail | 15357 | -0.48 | -31.7 | -0.46 | -0.49 | -0.48 | -0.54 | +0.06 [+0.02; +0.09] | +0.07 |
| trail act0.5 gap0.8 SL1.5 T60 | trail | 15357 | -0.49 | -28.8 | -0.47 | -0.49 | -0.50 | -0.55 | +0.07 [+0.03; +0.11] | +0.09 |
| trail act0.5 gap1.2 SL1.5 T60 | trail | 15357 | -0.49 | -27.2 | -0.49 | -0.49 | -0.50 | -0.56 | +0.07 [+0.03; +0.11] | +0.09 |
| trail act1 gap0.4 SL1.5 T60 | trail | 15357 | -0.48 | -27.8 | -0.48 | -0.48 | -0.48 | -0.54 | +0.06 [+0.02; +0.10] | +0.08 |
| trail act1 gap0.8 SL1.5 T60 | trail | 15357 | -0.48 | -26.4 | -0.48 | -0.48 | -0.49 | -0.56 | +0.07 [+0.03; +0.11] | +0.09 |
| trail act1 gap1.2 SL1.5 T60 | trail | 15357 | -0.49 | -25.8 | -0.49 | -0.49 | -0.50 | -0.56 | +0.07 [+0.02; +0.11] | +0.09 |
| trail act1.5 gap0.4 SL1.5 T60 | trail | 15357 | -0.48 | -27.4 | -0.48 | -0.50 | -0.47 | -0.55 | +0.06 [+0.02; +0.11] | +0.08 |
| trail act1.5 gap0.8 SL1.5 T60 | trail | 15357 | -0.49 | -26.2 | -0.48 | -0.50 | -0.48 | -0.56 | +0.06 [+0.02; +0.11] | +0.08 |
| trail act1.5 gap1.2 SL1.5 T60 | trail | 15357 | -0.49 | -25.8 | -0.50 | -0.50 | -0.49 | -0.56 | +0.07 [+0.02; +0.11] | +0.09 |
| trail act0.5 gap0.4 SL3 T60 | trail | 15357 | -0.46 | -26.0 | -0.45 | -0.46 | -0.46 | -0.52 | +0.06 [+0.02; +0.10] | +0.05 |
| trail act0.5 gap0.8 SL3 T60 | trail | 15357 | -0.46 | -23.5 | -0.46 | -0.45 | -0.48 | -0.53 | +0.07 [+0.02; +0.11] | +0.07 |
| trail act0.5 gap1.2 SL3 T60 | trail | 15357 | -0.47 | -22.6 | -0.48 | -0.45 | -0.49 | -0.54 | +0.07 [+0.02; +0.12] | +0.07 |
| trail act1 gap0.4 SL3 T60 | trail | 15357 | -0.46 | -22.5 | -0.47 | -0.45 | -0.47 | -0.52 | +0.06 [+0.01; +0.10] | +0.04 |
| trail act1 gap0.8 SL3 T60 | trail | 15357 | -0.47 | -21.6 | -0.47 | -0.45 | -0.48 | -0.53 | +0.07 [+0.02; +0.11] | +0.06 |
| trail act1 gap1.2 SL3 T60 | trail | 15357 | -0.48 | -21.9 | -0.49 | -0.46 | -0.49 | -0.54 | +0.06 [+0.01; +0.11] | +0.06 |
| trail act1.5 gap0.4 SL3 T60 | trail | 15357 | -0.47 | -22.1 | -0.49 | -0.47 | -0.47 | -0.53 | +0.05 [+0.00; +0.10] | +0.04 |
| trail act1.5 gap0.8 SL3 T60 | trail | 15357 | -0.48 | -21.3 | -0.48 | -0.48 | -0.47 | -0.53 | +0.05 [+0.00; +0.10] | +0.05 |
| trail act1.5 gap1.2 SL3 T60 | trail | 15357 | -0.48 | -21.7 | -0.50 | -0.47 | -0.48 | -0.54 | +0.05 [+0.01; +0.10] | +0.05 |
| trail act0.5 gap0.4 SL3 T30 | trail | 15357 | -0.47 | -27.3 | -0.46 | -0.49 | -0.47 | -0.52 | +0.05 [+0.02; +0.09] | +0.04 |
| trail act0.5 gap0.8 SL3 T30 | trail | 15357 | -0.48 | -25.6 | -0.46 | -0.48 | -0.49 | -0.53 | +0.05 [+0.01; +0.09] | +0.05 |
| trail act0.5 gap1.2 SL3 T30 | trail | 15357 | -0.49 | -24.7 | -0.49 | -0.48 | -0.49 | -0.53 | +0.05 [+0.01; +0.09] | +0.05 |
| trail act1 gap0.4 SL3 T30 | trail | 15357 | -0.48 | -25.7 | -0.48 | -0.49 | -0.48 | -0.52 | +0.04 [+0.00; +0.08] | +0.03 |
| trail act1 gap0.8 SL3 T30 | trail | 15357 | -0.49 | -24.6 | -0.48 | -0.49 | -0.49 | -0.53 | +0.04 [+0.00; +0.08] | +0.04 |
| trail act1 gap1.2 SL3 T30 | trail | 15357 | -0.49 | -24.2 | -0.49 | -0.49 | -0.50 | -0.53 | +0.04 [-0.00; +0.08] | +0.04 |
| trail act1.5 gap0.4 SL3 T30 | trail | 15357 | -0.50 | -25.7 | -0.49 | -0.51 | -0.49 | -0.53 | +0.03 [-0.01; +0.07] | +0.02 |
| trail act1.5 gap0.8 SL3 T30 | trail | 15357 | -0.50 | -24.6 | -0.49 | -0.51 | -0.50 | -0.53 | +0.03 [-0.01; +0.07] | +0.02 |
| trail act1.5 gap1.2 SL3 T30 | trail | 15357 | -0.50 | -24.0 | -0.50 | -0.51 | -0.50 | -0.53 | +0.03 [-0.01; +0.07] | +0.03 |
| trail act0.5 gap0.4 SL3 T120 | trail | 15357 | -0.46 | -25.1 | -0.46 | -0.46 | -0.46 | -0.49 | +0.03 [-0.01; +0.08] | +0.05 |
| trail act0.5 gap0.8 SL3 T120 | trail | 15357 | -0.47 | -23.5 | -0.47 | -0.46 | -0.48 | -0.52 | +0.05 [-0.00; +0.10] | +0.08 |
| trail act0.5 gap1.2 SL3 T120 | trail | 15357 | -0.48 | -23.4 | -0.50 | -0.46 | -0.49 | -0.53 | +0.05 [-0.00; +0.11] | +0.10 |
| trail act1 gap0.4 SL3 T120 | trail | 15357 | -0.47 | -21.1 | -0.48 | -0.45 | -0.48 | -0.50 | +0.03 [-0.03; +0.08] | +0.04 |
| trail act1 gap0.8 SL3 T120 | trail | 15357 | -0.47 | -21.1 | -0.49 | -0.46 | -0.48 | -0.51 | +0.04 [-0.02; +0.10] | +0.07 |
| trail act1 gap1.2 SL3 T120 | trail | 15357 | -0.49 | -21.1 | -0.50 | -0.47 | -0.50 | -0.53 | +0.04 [-0.02; +0.10] | +0.08 |
| trail act1.5 gap0.4 SL3 T120 | trail | 15357 | -0.49 | -18.5 | -0.49 | -0.48 | -0.49 | -0.50 | +0.01 [-0.05; +0.08] | +0.04 |
| trail act1.5 gap0.8 SL3 T120 | trail | 15357 | -0.49 | -18.6 | -0.49 | -0.50 | -0.49 | -0.51 | +0.02 [-0.05; +0.09] | +0.05 |
| trail act1.5 gap1.2 SL3 T120 | trail | 15357 | -0.50 | -18.4 | -0.50 | -0.50 | -0.50 | -0.53 | +0.03 [-0.04; +0.09] | +0.07 |
| atr k1 act1 SL1.5 T60 | atr | 15357 | -0.50 | -25.1 | -0.51 | -0.50 | -0.50 | -0.55 | +0.05 [+0.00; +0.09] | +0.07 |
| atr k1.5 act1 SL1.5 T60 | atr | 15357 | -0.53 | -24.3 | -0.54 | -0.51 | -0.53 | -0.55 | +0.02 [-0.02; +0.07] | +0.05 |
| atr k2 act1 SL1.5 T60 | atr | 15357 | -0.52 | -23.4 | -0.54 | -0.51 | -0.53 | -0.56 | +0.03 [-0.02; +0.08] | +0.06 |
| atr k1 act1 SL3 T60 | atr | 15357 | -0.50 | -22.0 | -0.52 | -0.48 | -0.50 | -0.53 | +0.03 [-0.02; +0.08] | +0.02 |
| atr k1.5 act1 SL3 T60 | atr | 15357 | -0.53 | -20.7 | -0.54 | -0.51 | -0.54 | -0.53 | +0.00 [-0.05; +0.06] | +0.00 |
| atr k2 act1 SL3 T60 | atr | 15357 | -0.53 | -20.5 | -0.56 | -0.52 | -0.53 | -0.53 | +0.00 [-0.06; +0.06] | +0.01 |
| be0.6 TPcand SL1.5 T60 | be | 15357 | -0.49 | -25.8 | -0.50 | -0.47 | -0.50 | -0.56 | +0.08 [+0.03; +0.12] | +0.10 |
| be0.6 TPcand SL3 T60 | be | 15357 | -0.46 | -21.0 | -0.49 | -0.43 | -0.48 | -0.54 | +0.08 [+0.03; +0.13] | +0.08 |
| be0.6 TP1.5 SL1.5 T60 | be | 15357 | -0.47 | -30.8 | -0.47 | -0.47 | -0.47 | -0.54 | +0.06 [+0.03; +0.10] | +0.07 |
| be0.6 TP1.5 SL3 T60 | be | 15357 | -0.45 | -23.6 | -0.46 | -0.44 | -0.45 | -0.51 | +0.07 [+0.02; +0.11] | +0.05 |
| be0.6+trail act1 gap0.8 SL1.5 T60 | be_trail | 15357 | -0.48 | -28.4 | -0.47 | -0.48 | -0.49 | -0.56 | +0.07 [+0.03; +0.11] | +0.09 |
| be0.6+trail act1 gap0.8 SL3 T60 | be_trail | 15357 | -0.46 | -23.4 | -0.46 | -0.46 | -0.48 | -0.53 | +0.07 [+0.02; +0.11] | +0.07 |

### G

| hücre | aile | n (90 gün) | net 90g | t | B1 | B2 | B3 | rastgele 90g | sinyal−rastgele 90g [%95] | sinyal−rastgele(oyn.) 90g |
|---|---|---|---|---|---|---|---|---|---|---|
| fixed TPcand SL1.5 T30 | fixed | 7132 | -0.42 | -11.2 | -0.48 | -0.44 | -0.35 | -0.53 | +0.11 [+0.03; +0.19] | +0.12 |
| fixed TPcand SL1.5 T60 | fixed | 7132 | -0.39 | -9.4 | -0.45 | -0.41 | -0.30 | -0.56 | +0.17 [+0.08; +0.25] | +0.16 |
| fixed TPcand SL1.5 T120 | fixed | 7132 | -0.42 | -8.7 | -0.47 | -0.44 | -0.36 | -0.54 | +0.12 [+0.01; +0.22] | +0.13 |
| fixed TPcand SL3 T30 | fixed | 7132 | -0.39 | -10.0 | -0.48 | -0.41 | -0.27 | -0.52 | +0.13 [+0.05; +0.21] | +0.11 |
| fixed TPcand SL3 T60 | fixed | 7132 | -0.34 | -7.7 | -0.45 | -0.35 | -0.20 | -0.53 | +0.19 [+0.10; +0.28] | +0.13 |
| fixed TPcand SL3 T120 | fixed | 7132 | -0.37 | -7.1 | -0.47 | -0.36 | -0.29 | -0.49 | +0.11 [-0.00; +0.23] | +0.10 |
| fixed TP1.5 SL1.5 T30 | fixed | 7132 | -0.43 | -11.5 | -0.46 | -0.46 | -0.35 | -0.53 | +0.10 [+0.02; +0.17] | +0.08 |
| fixed TP1.5 SL1.5 T60 | fixed | 7132 | -0.39 | -10.0 | -0.44 | -0.41 | -0.30 | -0.53 | +0.15 [+0.06; +0.23] | +0.12 |
| fixed TP1.5 SL1.5 T120 | fixed | 7132 | -0.41 | -9.4 | -0.44 | -0.42 | -0.35 | -0.51 | +0.11 [+0.01; +0.20] | +0.11 |
| fixed TP1.5 SL3 T30 | fixed | 7132 | -0.39 | -10.1 | -0.46 | -0.42 | -0.27 | -0.51 | +0.12 [+0.05; +0.20] | +0.08 |
| fixed TP1.5 SL3 T60 | fixed | 7132 | -0.32 | -8.8 | -0.44 | -0.33 | -0.19 | -0.50 | +0.18 [+0.10; +0.26] | +0.11 |
| fixed TP1.5 SL3 T120 | fixed | 7132 | -0.35 | -8.7 | -0.46 | -0.33 | -0.26 | -0.46 | +0.11 [+0.02; +0.20] | +0.09 |
| trail act0.5 gap0.4 SL1.5 T60 | trail | 7132 | -0.44 | -12.3 | -0.48 | -0.47 | -0.36 | -0.54 | +0.10 [+0.02; +0.17] | +0.09 |
| trail act0.5 gap0.8 SL1.5 T60 | trail | 7132 | -0.42 | -11.4 | -0.46 | -0.44 | -0.34 | -0.55 | +0.13 [+0.06; +0.21] | +0.14 |
| trail act0.5 gap1.2 SL1.5 T60 | trail | 7132 | -0.42 | -10.4 | -0.49 | -0.44 | -0.31 | -0.56 | +0.15 [+0.06; +0.23] | +0.15 |
| trail act1 gap0.4 SL1.5 T60 | trail | 7132 | -0.42 | -11.7 | -0.46 | -0.45 | -0.32 | -0.55 | +0.13 [+0.05; +0.20] | +0.12 |
| trail act1 gap0.8 SL1.5 T60 | trail | 7132 | -0.41 | -10.9 | -0.45 | -0.44 | -0.32 | -0.56 | +0.15 [+0.07; +0.23] | +0.15 |
| trail act1 gap1.2 SL1.5 T60 | trail | 7132 | -0.41 | -10.3 | -0.48 | -0.43 | -0.31 | -0.57 | +0.15 [+0.07; +0.24] | +0.15 |
| trail act1.5 gap0.4 SL1.5 T60 | trail | 7132 | -0.40 | -10.6 | -0.48 | -0.41 | -0.32 | -0.55 | +0.15 [+0.07; +0.23] | +0.15 |
| trail act1.5 gap0.8 SL1.5 T60 | trail | 7132 | -0.40 | -10.3 | -0.48 | -0.41 | -0.32 | -0.56 | +0.15 [+0.07; +0.24] | +0.16 |
| trail act1.5 gap1.2 SL1.5 T60 | trail | 7132 | -0.41 | -9.8 | -0.48 | -0.42 | -0.32 | -0.56 | +0.15 [+0.07; +0.24] | +0.16 |
| trail act0.5 gap0.4 SL3 T60 | trail | 7132 | -0.38 | -10.4 | -0.47 | -0.41 | -0.25 | -0.51 | +0.13 [+0.06; +0.21] | +0.08 |
| trail act0.5 gap0.8 SL3 T60 | trail | 7132 | -0.36 | -9.6 | -0.45 | -0.38 | -0.25 | -0.53 | +0.16 [+0.09; +0.24] | +0.13 |
| trail act0.5 gap1.2 SL3 T60 | trail | 7132 | -0.36 | -8.5 | -0.47 | -0.38 | -0.22 | -0.54 | +0.18 [+0.09; +0.27] | +0.14 |
| trail act1 gap0.4 SL3 T60 | trail | 7132 | -0.36 | -10.1 | -0.45 | -0.38 | -0.23 | -0.52 | +0.16 [+0.09; +0.24] | +0.11 |
| trail act1 gap0.8 SL3 T60 | trail | 7132 | -0.35 | -9.3 | -0.44 | -0.37 | -0.23 | -0.53 | +0.18 [+0.10; +0.26] | +0.14 |
| trail act1 gap1.2 SL3 T60 | trail | 7132 | -0.35 | -8.8 | -0.45 | -0.37 | -0.22 | -0.54 | +0.19 [+0.10; +0.27] | +0.14 |
| trail act1.5 gap0.4 SL3 T60 | trail | 7132 | -0.35 | -9.4 | -0.49 | -0.34 | -0.22 | -0.52 | +0.17 [+0.10; +0.25] | +0.13 |
| trail act1.5 gap0.8 SL3 T60 | trail | 7132 | -0.35 | -9.0 | -0.48 | -0.34 | -0.23 | -0.53 | +0.18 [+0.10; +0.26] | +0.13 |
| trail act1.5 gap1.2 SL3 T60 | trail | 7132 | -0.36 | -8.6 | -0.48 | -0.36 | -0.23 | -0.53 | +0.18 [+0.09; +0.26] | +0.14 |
| trail act0.5 gap0.4 SL3 T30 | trail | 7132 | -0.41 | -11.0 | -0.47 | -0.46 | -0.29 | -0.51 | +0.10 [+0.03; +0.18] | +0.07 |
| trail act0.5 gap0.8 SL3 T30 | trail | 7132 | -0.41 | -10.8 | -0.46 | -0.44 | -0.29 | -0.52 | +0.11 [+0.04; +0.19] | +0.10 |
| trail act0.5 gap1.2 SL3 T30 | trail | 7132 | -0.40 | -10.0 | -0.48 | -0.44 | -0.27 | -0.52 | +0.12 [+0.04; +0.20] | +0.10 |
| trail act1 gap0.4 SL3 T30 | trail | 7132 | -0.40 | -10.7 | -0.46 | -0.45 | -0.27 | -0.52 | +0.11 [+0.04; +0.19] | +0.09 |
| trail act1 gap0.8 SL3 T30 | trail | 7132 | -0.40 | -10.3 | -0.46 | -0.44 | -0.28 | -0.52 | +0.12 [+0.04; +0.20] | +0.10 |
| trail act1 gap1.2 SL3 T30 | trail | 7132 | -0.40 | -9.8 | -0.47 | -0.44 | -0.28 | -0.52 | +0.12 [+0.04; +0.20] | +0.10 |
| trail act1.5 gap0.4 SL3 T30 | trail | 7132 | -0.40 | -10.5 | -0.50 | -0.42 | -0.27 | -0.52 | +0.12 [+0.04; +0.19] | +0.09 |
| trail act1.5 gap0.8 SL3 T30 | trail | 7132 | -0.40 | -10.3 | -0.49 | -0.42 | -0.28 | -0.52 | +0.12 [+0.04; +0.20] | +0.10 |
| trail act1.5 gap1.2 SL3 T30 | trail | 7132 | -0.41 | -9.8 | -0.49 | -0.43 | -0.28 | -0.52 | +0.11 [+0.03; +0.20] | +0.10 |
| trail act0.5 gap0.4 SL3 T120 | trail | 7132 | -0.38 | -9.9 | -0.48 | -0.39 | -0.26 | -0.48 | +0.11 [+0.02; +0.19] | +0.09 |
| trail act0.5 gap0.8 SL3 T120 | trail | 7132 | -0.36 | -9.3 | -0.47 | -0.37 | -0.25 | -0.50 | +0.14 [+0.05; +0.22] | +0.15 |
| trail act0.5 gap1.2 SL3 T120 | trail | 7132 | -0.37 | -8.6 | -0.49 | -0.37 | -0.25 | -0.52 | +0.15 [+0.05; +0.24] | +0.17 |
| trail act1 gap0.4 SL3 T120 | trail | 7132 | -0.37 | -9.2 | -0.45 | -0.38 | -0.26 | -0.48 | +0.12 [+0.03; +0.20] | +0.11 |
| trail act1 gap0.8 SL3 T120 | trail | 7132 | -0.36 | -8.5 | -0.44 | -0.38 | -0.26 | -0.50 | +0.14 [+0.04; +0.23] | +0.15 |
| trail act1 gap1.2 SL3 T120 | trail | 7132 | -0.37 | -8.2 | -0.46 | -0.38 | -0.27 | -0.52 | +0.14 [+0.04; +0.24] | +0.17 |
| trail act1.5 gap0.4 SL3 T120 | trail | 7132 | -0.37 | -9.3 | -0.51 | -0.35 | -0.28 | -0.49 | +0.11 [+0.02; +0.20] | +0.12 |
| trail act1.5 gap0.8 SL3 T120 | trail | 7132 | -0.38 | -8.9 | -0.50 | -0.36 | -0.28 | -0.50 | +0.12 [+0.03; +0.22] | +0.14 |
| trail act1.5 gap1.2 SL3 T120 | trail | 7132 | -0.39 | -8.6 | -0.50 | -0.39 | -0.30 | -0.51 | +0.12 [+0.01; +0.22] | +0.15 |
| atr k1 act1 SL1.5 T60 | atr | 7132 | -0.44 | -11.9 | -0.52 | -0.45 | -0.36 | -0.55 | +0.10 [+0.02; +0.18] | +0.11 |
| atr k1.5 act1 SL1.5 T60 | atr | 7132 | -0.46 | -11.4 | -0.54 | -0.46 | -0.37 | -0.55 | +0.10 [+0.01; +0.18] | +0.10 |
| atr k2 act1 SL1.5 T60 | atr | 7132 | -0.45 | -11.2 | -0.53 | -0.46 | -0.36 | -0.56 | +0.11 [+0.02; +0.19] | +0.12 |
| atr k1 act1 SL3 T60 | atr | 7132 | -0.40 | -10.3 | -0.52 | -0.41 | -0.27 | -0.52 | +0.12 [+0.04; +0.20] | +0.08 |
| atr k1.5 act1 SL3 T60 | atr | 7132 | -0.42 | -10.0 | -0.54 | -0.42 | -0.29 | -0.52 | +0.11 [+0.02; +0.19] | +0.07 |
| atr k2 act1 SL3 T60 | atr | 7132 | -0.41 | -9.3 | -0.53 | -0.42 | -0.28 | -0.53 | +0.12 [+0.03; +0.21] | +0.09 |
| be0.6 TPcand SL1.5 T60 | be | 7132 | -0.41 | -10.5 | -0.47 | -0.43 | -0.32 | -0.56 | +0.15 [+0.07; +0.23] | +0.15 |
| be0.6 TPcand SL3 T60 | be | 7132 | -0.35 | -8.5 | -0.46 | -0.36 | -0.22 | -0.54 | +0.19 [+0.10; +0.27] | +0.14 |
| be0.6 TP1.5 SL1.5 T60 | be | 7132 | -0.41 | -10.9 | -0.44 | -0.44 | -0.33 | -0.54 | +0.13 [+0.05; +0.21] | +0.11 |
| be0.6 TP1.5 SL3 T60 | be | 7132 | -0.34 | -9.4 | -0.42 | -0.36 | -0.22 | -0.51 | +0.17 [+0.09; +0.24] | +0.11 |
| be0.6+trail act1 gap0.8 SL1.5 T60 | be_trail | 7132 | -0.42 | -11.5 | -0.46 | -0.45 | -0.34 | -0.56 | +0.13 [+0.06; +0.21] | +0.14 |
| be0.6+trail act1 gap0.8 SL3 T60 | be_trail | 7132 | -0.36 | -9.8 | -0.45 | -0.38 | -0.25 | -0.53 | +0.17 [+0.09; +0.24] | +0.13 |
## Sınırlar
- Mum çözünürlüğü 1 dk: bar-içi sıra bilinmiyor → stop-önce kuralı (kötümser); gerçek tick sırası bazı izleyen-stop çıkışlarını iyileştirebilir ya da kötüleştirebilir.
- Kayma sabit (%0,05 / %0,15), sembole/likiditeye bağlı değil; emir defteri derinliği, pozisyon büyüklüğü, kısmi doluş modellenmedi. Sıfır hacimli (düz) 1 dk barlar eksik veri değil gerçek 'işlem yok'tur; likit olmayan sembollerde doluş varsayımı iyimser olabilir.
- HA rescan canlıyı birebir üretmez (docs/RESCAN_HARNESS.md); canlı journal'da aşırı-alım etiketi yok (kapı `block` modunda zaten eleniyor varsayıldı). Canlı dönem 18 Eyl–17 Eki, B3 ile ÇAKIŞIR: 'ileri' yalnız hücrelerin B1+B2'de donmasından sonraki dönem anlamında; bağımsız saf ileri dönem için 31 Ekim yeniden koşusu (bölüm 8).
- E ve G desenleri 71 desenden sonradan, geçmiş performansa bakılarak seçildi (çoklu karşılaştırma / seçilim yanlılığı); her biri yalnız kendi test aralığında ölçüldü, ama G'nin olumlu farkı hâlâ iyimser sayılmalı. 90 gün tek piyasa dönemi; bloklar bağımsız değil (gün-kümeli SE kullanıldı).
- 'Sinyal−rastgele' SE'leri bağımsız varsayımla birleştirildi (muhafazakâr). Oynaklık-eşleşmiş tabanda adaylar yetersizse sinyal atlandı (kapsam bölüm 2'de).
- Hücre ızgarası 60; en iyi hücre seçimi iç-örneklemde iyimserdir — kanıt walk-forward (bölüm 5) ve canlı ileri test (bölüm 8) satırlarıdır.

