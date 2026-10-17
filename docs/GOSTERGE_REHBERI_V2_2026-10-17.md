# Erken Uyarı v2 — rehberin YENİ (★) göstergeleri (2026-10-17, çevrimdışı)

**Soru:** Güncellenen TradingView rehberindeki, tek sembol OHLCV + taker hacminden hesaplanabilen ve ilk kütüphanede (`indicators_ext.py`) olmayan ★ maddeler (MA şeridi, PMO, AC, Special K, SMI, Woodies CCI, RCI, Chandelier, RSI ıraksaması, otomatik Fibonacci/OTE, iFVG, Breaker, BPR, CISD, Turtle Soup, ORB, Judas, killzone, çift dip, Wyckoff, VSA, mum formasyonları, Range Filter, QQE MOD, Squeeze Momentum, UT Bot, Cipher B, Waddah, WaveTrend, Laguerre RSI, MAMA, Schaff, FRAMA vb. — 365 özellik / zaman dilimi) LUNA tipi yükselişten ÖNCE ayırt edici mi, çok değişkenli bilgiyi artırıyor mu, tek başına sinyal olarak ya da Hız Avcısı (HA) süzgeci olarak net-pozitif mi? Kod: `app/rescan/indicators_ext2.py` (+`tests/test_indicators_ext2.py`), hatlar: `scripts/indearly2_study.py`, `scripts/indfilter2_feats.py`, `scripts/indfilter2_study.py`, `scripts/indearly2_report.py`. Ham çıktılar bu klasörde.

## 0. Kısa cevap

**Karar: HAYIR.** Yeni ★ göstergeler de ilk kütüphane gibi iki boyuttan (oynaklık/aralık genişliği + "yükselen rejim") ibaret bilgi taşıyor; çok değişkenli modele katkıları küçük (t0−10'da +0,014 AUC), önceden belirlenmiş 20 topluluk/SMC sinyalinin HİÇBİRİ üç örneklem-dışı blokta (gerçekçi doluşla: 60 sn gecikme, %0,15 kayma, %0,1125/bacak) net-pozitif değil (en iyisi Wyckoff spring, B2'de −0,36 %; koşulsuz rastgele −0,49 %), tek "erken-uyarı ölçütü"nü geçen sinyal (`RVOL(günün saati)>3 + yeşil mum`) günde 1 150–1 690 tetikleyen, kesinliği %1,3–1,9 olan ve neti −0,51…−0,56 % olan zayıf bir hacim-genişleme eğilimi; HA süzgeci olarak da hiçbir kural HA'yı net-pozitif yapmıyor (B1'de seçilen en iyi kural bile B2/B3'te −0,43/−0,58 %). Bu, önceki çalışmanın (134 sütunluk kütüphane) sonucunu değiştirmiyor.

| soru | örneklem dışı sonuç (B1, B2, B3; seçim yalnız eğitim/B1'de) |
|---|---|
| **a) Olay öncesi ayırt edicilik** (düşüş+oynaklık kontrolü sonrası, kısmi r; 967 yeni özellik) | **t0−10:** 67 özellik FWER<0,05, 213 BH q<0,05, 194'ü 3/3 blokta aynı işaretli; ama en güçlü \|r\| yalnız **0,032** (günlük aralık/ADR, saat kosinüsü, Range-Filter/Gauss/regresyon kanal genişliği: olay ÖNCESİ NEGATİF = sakin/dar aralıktan çıkış; 15m RMI, HA-RSI, RCI, WT, pd_pos: POZİTİF 0,02–0,026 = yükselen rejim). Aynı yöntemle ESKİ kütüphanenin en güçlüsü 0,048 (`15m.atr_ratio`). **t0:** 260 FWER, 498 q<0,05; en güçlü 0,065 (1m `ssl_state`, Woodies CCI, Laguerre RSI, RCI9: düşüş izi; eski: `5m.crsi` −0,082). Yönlü yeni öncüler (RSI ıraksaması, iFVG, Breaker, CISD, spring, çift dip, OTE …) hiç öne çıkmıyor: önceden belirlenmiş 20 sinyal bayrağının hepsi t0−10'da \|r\| ≤ 0,012 (FWER eşiği 0,015; yalnız `ce_flip_up` q<0,05 ve TERS işaretli), t0'da en büyüğü 0,031 (`rvol_green`, negatif). |
| **b) Çok değişkenli artış** (HistGradientBoosting, blok-dışı, AUC) | t0: mevcut154 **0,773** → +eski **0,774** (+0,002) → +yeni **0,779** (+0,006; B1/B2/B3 +0,003/+0,009/+0,005) → +eski+yeni 0,775 (+0,003). t0−10: **0,629** → +eski 0,637 (+0,007) → +yeni **0,644** (+0,014; +0,012/+0,020/+0,010) → +eski+yeni 0,645 (+0,015). Saat/seans özellikleri çıkarılınca kazanç aynı (+0,013) → kazanç zaman-etkisinden değil, ama t0−10'da mutlak AUC hâlâ yalnız 0,64. |
| **c) Önceden belirlenmiş 20 sinyal** (5m, 60 dk cooldown) | **0/20** sinyal hiçbir blokta net-pozitif değil: net TP1,5 −0,36…−0,66 % (koşulsuz −0,51/−0,49/−0,49; HA −0,54/−0,50/−0,56), izleyen 1,0/0,8 −0,38…−0,67 %. hit60@1,5 şans farkı kararsız (B1'de çoğu ≤0; en tutarlı `sqz_rel_up` +2,3/+3,4/+3,5 pp, HA +3,9/+4,5/+5,7). t0 öncesi yakalama sayı-eşleşmiş sıfırın ×1,5'ini VE HA'dan-önce-gelme >%50'yi 3/3 blokta yalnız `rvol_green` sağlıyor (yakalama %39–50 ↔ sıfır %20–27; HA'dan önce %53–64, medyan +5…+10 dk) — fakat kesinlik %1,3–1,9 (taban %0,9–1,3) ve net −0,51…−0,56. |
| **d) HA süzgeci** (net−taban, ATR-kontrollü kısmi Spearman; kural arama B1→B2,B3) | 664 yeni özellikten 193'ü q<0,05 (180'i 3/3 blok) ama hepsi "uzamış/aşırı genişlemiş giriş daha kötü" ekseni (`tl_res_dist` −0,068, `rvol_tod` −0,047, `lrc_pos`, `medch_pos`, `ribbon_px`, `coral_dist` ≈ −0,04; eski kütüphane en iyi −0,047 → yeni bilgi yok); hit ile net'in işareti ters (ikisi de anlamlı 168 özelliğin 161'inde). B1'de seçilen 10 kuraldan 2'si (`15m.tl_sup_dist<=4,28`, `15m.psy12>58,3`) üç blokta HA net'ini iyileştirdi (Δ +0,10/+0,06/+0,01 ve +0,20/+0,08/+0,04) ama tutulan net hâlâ −0,35…−0,61 %; 300 aday kural içinde (n≥30) HİÇBİRİ hiçbir blokta net>0 değil (en iyi blok neti −0,35/−0,40/−0,51). |

**Dürüst yorum.** (i) 967 özelliğin çoğu aynı göstergenin 3 zaman dilimindeki kopyası ve birbirine bağımlı; "anlamlı özellik sayısı" bağımsız kanıt sayısı değildir. (ii) Çok değişkenli kazanç gerçek ama küçük; sinyale dönüştürüldüğünde (c) maliyeti (≈ %0,5 gidiş-dönüş) karşılamıyor. (iii) En umut verici yönler — sıkışma çıkışı (`sqz_rel_up`: kesinlik %2,4–2,8 ↔ taban %0,9–1,3, t0 öncesi yakalama %11–12 ↔ sıfır %4–7), `ts_long`/`spring` (net −0,36…−0,49) — yine de net-pozitiften ≥0,36 puan uzak ve HA'nın (kesinlik %6,6, yakalama %26–33) gerisinde. (iv) LUNATRY 17.10: `wae_up`/`utbot_buy` 00:10, `ifvg_bull` 00:15, `rvol_green` 01:10'dan itibaren tetikledi; bunlar günde binlerce sinyalin arasında olduğundan kullanılabilir ayırt edicilik sağlamıyor.

## 1. Yöntem (önceki çalışma hatlarının yeniden kullanımı)

* **Kütüphane** `indicators_ext2.py`: 365 özellik/zaman dilimi, `x2.` önekli, tümü nedensel (testler: gelecek barlarını bozma ve kesilmiş-dizi = önek, 1m/5m/15m; el hesaplı Aroon osilatörü, RCI, Laguerre RSI, günün-saatine göre RVOL, önceki gün H/L, ORB, CISD, iFVG, Chandelier, Range Filter). Pivot tabanlı her şey `right` bar SONRA onaylı (RSI ıraksaması 3/3, Fibonacci/OTE/Premium-Discount 5/5, trend çizgisi ve çift/üçlü dip 4/4). Gün tabanlı özellikler tamamlanmış günleri kullanır (UTC günü ve TR günü 00:00 Europe/Istanbul). Yaklaşık/vekil tanımlar: Jurik MA (everget yaklaşımı), Kase DevStop, QQE MOD (mavi = RSI-MA−50 > Bollinger üst bandı ∧ 2. QQE çizgisi−50 > 3), Cipher B yeşil nokta (WT dip kesişimi + para akışı artışı), Breaker (OB'nin tepesi önceki 20 barın en yükseğini süpürmüşse; iOB = süpürme şartı yok), killzone saatleri EDT varsayımıyla UTC. Varsayılan parametreler: Squeeze 20/2/1,5, WT 9/12 (−53/−60), UT Bot a=1 ATR10, Range Filter 100/3, SSL 10, Schaff 23/50/10, Laguerre γ=0,5, Chandelier 22/3, Waddah 150/20/40. HA süzgeci özellikleri için ayrıca `--verify 40` ile 40 olay x 666 özellik kesilmiş-seri nedensellik testi: 0 fark.
* **Veri/hat:** pattern90 önbelleği (306 sembol, 5m doldurulmuş ızgara, 1m ham, 4 552 olay, eşleşmiş taban — olay başına ≤20 taban satırı), olay anlarında (t0−15…t0) ve tüm 5m ızgarada özellik; yeni özellikler 5m (tam 365), 1m ve 15m (gün/seans ailesi hariç, 301'er) = 967 sütun. Ham tam ızgara diske yazılmadı (yalnız anlık görüntü + sinyal süpürmesi; önbellek: scratchpad/indearly2).
* **a) Sıralama:** eşleşmiş grup-içi AUC (ham) ve **kısmi korelasyon**: aynı olay-taban kümesi içinde, 19 kontrol (ret1…20, ATR%, %B, EMA uzaklıkları, RSI, 1m getiriler, taker, hacim oranı, drawdown — "düşüş+oynaklık") doğrusal sabitlenerek olay göstergesi ile özellik korelasyonu; permütasyon (1 000, kümede rastgele üye 'olay'), max-\|r\| ile FWER, BH q, blok bazlı r ve işaret tutarlılığı. Not: ilk denemede kontrole göre "artık AUC" kullanıldı; seyrek 0/1 bayraklarda artık, bağları kontrol terimiyle bozduğundan kontrolün kendi AUC'sini (≈0,64/0,35) yansıttı (sahte); bu yüzden birincil istatistik kısmi r, artık AUC yalnız sürekli özelliklerde (412) tabloda duruyor.
* **b)** Aynı blok-dışı bırakma HGB (150 iterasyon, 15 yaprak), taban olay başına ≤12; özellik kümeleri mevcut154 / +eski 401 / +yeni 967 / ikisi birden / tek başına.
* **c)** Sinyal = yeni 5m bayrağı = 1 (tanım standart varsayılan, eşik/ayar YOK); geçerlilik, 60 dk cooldown (12 bar), exit_sim (TP1,5/SL3/T60 ve izleyen 1,0/0,8; 60 sn gecikme, %0,15 kayma, %0,1125/bacak), null3 (hit şans farkı), koşulsuz tekdüze örnek (150 bin an), sinyal sayısı kadar "≥2 sa uzak" rastgele giriş, sayı-eşleşmiş serbest sıfır (olay yakalama), HA ticks. **Blok sınırları** pattern90 hattındakilerdir (B1 19 Tem–17 Ağu, B2 18 Ağu–16 Eyl, B3 17 Eyl–17 Eki: HA süzgecindeki bloklardan 1 gün kaymış); sinyaller önceden belirlendiği için B3'ün tamamı kullanıldı.
* **d)** `indfilter_study.py` yöntemi: Study (HA 20 343 olay, 3 blok, oynaklık-eşleşmiş rastgele taban), ATR+hedef/ATR kontrollü kısmi Spearman (gün-küme-dayanıklı t, BH q), kural arama (özellik × yön × 3 eşik; B1'de seç, B2/B3'te dokunmadan), aşırı-uyum tanısı. Sinyal bayrakları (+ son-k-bar sürümleri) ayrıca HA süzgeci olarak denendi.

## 2. Dikkat edilecek sınırlar

* 'rastgele (≥2 sa uzak)' sütunu yoğun sinyallerde (günde >1 000) dejenere (kalan anlar az ve sapmalı; örn. `qqe_mod` −1,0) — karşılaştırma için 'koşulsuz' sütununu kullanın; seyrek sinyallerde ikisi de benzer.
* Tek sembol göstergeleri; breadth/BTC-göreli/türev/Lorentzian başka ajanların kapsamında. Nadaraya-Watson = mevcut `rqk.py`, atlandı.
* 30 günlük yüksek/alçak (52 hafta vekili) B1'in ilk haftalarında yarım pencere (en az 7 gün şartı); 1m/15m'de gün/seans ailesi hesaplanmadı (5m'de var).
* Çok sayıda özellik/test: permütasyon p'leri BH/FWER ile düzeltildi ama özellikler yüksek korelasyonlu; yeni sonuçların tamamı önceki çalışmayla aynı yönde (küçük ek bilgi, net yok). Taban alt kümesi (≤20/olay) nedeniyle eski kütüphane rakamları önceki rapordan hafifçe farklı (aynı yöntemle yeniden hesaplandı).

---

## 3. Ayrıntılar (otomatik tablolar; `scripts/indearly2_report.py` ile üretilir)

### A. Özellik sıralaması

#### t0−10 — olay 4552, taban 91028, permütasyon 1000

Ham (kontrolsüz) eşleşmiş AUC: FWER<0,05 **211**, BH q<0,10 **491** özellik (FWER eşiği |AUC−½|>0.016). **Kısmi korelasyon** (olay göstergesi ile özellik arasında, aynı eşleşme kümesi içinde, düşüş+oynaklık kontrolleri doğrusal sabitlenerek): FWER<0,05 **67**, BH q<0,05 **213**, q<0,10 **267** özellik (FWER eşiği |r|>0.0149). Kısmi r, seyrek 0/1 bayraklarda da yanlı değildir; AUC'nin artığı yalnız sürekli özelliklerde (412) anlamlıdır.

Kısmi |r| ile en güçlü 25 yeni özellik (AUC ½ = bilgi yok; kısmi r > 0: olayda yüksek):

| özellik | aile | AUC ham | kısmi r | q | blok r B1 / B2 / B3 | işaret tutarlılığı | AUC artık (kontrol sonrası) | NaN payı |
|---|---|---|---|---|---|---|---|---|
| 5m.day_range_adr_utc | gün/seans | 0.489 | -0.0317 | 0.008 | -0.018 / -0.052 / -0.026 | 3/3 | 0.456 | 2% |
| 5m.hour_cos | gün/seans | 0.452 | -0.0315 | 0.008 | -0.021 / -0.030 / -0.038 | 3/3 | 0.454 | 0% |
| 5m.rf_band | topluluk | 0.432 | -0.0304 | 0.008 | -0.025 / -0.048 / -0.026 | 3/3 | 0.421 | 0% |
| 15m.gc_width | topluluk | 0.429 | -0.0287 | 0.008 | -0.023 / -0.044 / -0.024 | 3/3 | 0.428 | 1% |
| 15m.gc_above_upper | topluluk | 0.537 | +0.0264 | 0.008 | +0.035 / +0.029 / +0.018 | 3/3 | – (seyrek/ayrık) | 1% |
| 15m.rmi | ileri | 0.531 | +0.0264 | 0.008 | +0.021 / +0.034 / +0.023 | 3/3 | 0.530 | 0% |
| 15m.harsi | topluluk | 0.535 | +0.0259 | 0.008 | +0.020 / +0.035 / +0.021 | 3/3 | 0.529 | 0% |
| 15m.rci_mean | temel | 0.533 | +0.0250 | 0.008 | +0.025 / +0.032 / +0.018 | 3/3 | 0.525 | 0% |
| 15m.v_depth_atr | formasyon | 0.478 | -0.0241 | 0.008 | -0.026 / -0.024 / -0.022 | 3/3 | – (seyrek/ayrık) | 0% |
| 5m.day_range_adr_tr | gün/seans | 0.515 | -0.0232 | 0.008 | -0.015 / -0.042 / -0.014 | 3/3 | 0.475 | 2% |
| 15m.wt1 | topluluk | 0.531 | +0.0228 | 0.008 | +0.015 / +0.025 / +0.025 | 3/3 | 0.531 | 0% |
| 5m.gc_above_upper | topluluk | 0.535 | +0.0226 | 0.008 | +0.015 / +0.022 / +0.027 | 3/3 | – (seyrek/ayrık) | 0% |
| 15m.wt2 | topluluk | 0.528 | +0.0219 | 0.008 | +0.014 / +0.024 / +0.024 | 3/3 | 0.529 | 0% |
| 15m.pd_pos | pivot (Fib/trend/dip) | 0.536 | +0.0211 | 0.008 | +0.022 / +0.021 / +0.021 | 3/3 | 0.525 | 2% |
| 15m.pd_discount | pivot (Fib/trend/dip) | 0.466 | -0.0211 | 0.008 | -0.011 / -0.024 / -0.025 | 3/3 | – (seyrek/ayrık) | 2% |
| 15m.aroon_up | temel | 0.523 | +0.0204 | 0.008 | +0.014 / +0.025 / +0.018 | 3/3 | – (seyrek/ayrık) | 0% |
| 15m.rci26 | temel | 0.531 | +0.0204 | 0.008 | +0.016 / +0.030 / +0.013 | 3/3 | 0.529 | 0% |
| 15m.ribbon_align | temel | 0.534 | +0.0201 | 0.008 | +0.024 / +0.022 / +0.015 | 3/3 | – (seyrek/ayrık) | 0% |
| 5m.lrc_width | temel | 0.468 | -0.0198 | 0.008 | -0.015 / -0.031 / -0.016 | 3/3 | 0.439 | 0% |
| 5m.rmi | ileri | 0.533 | +0.0198 | 0.008 | +0.006 / +0.027 / +0.024 | 3/3 | 0.526 | 0% |
| 5m.kz_nypm | gün/seans | 0.484 | -0.0198 | 0.008 | -0.023 / -0.026 / -0.013 | 3/3 | – (seyrek/ayrık) | 0% |
| 15m.rf_band | topluluk | 0.452 | -0.0197 | 0.008 | -0.011 / -0.039 / -0.022 | 3/3 | 0.455 | 1% |
| 5m.brk_bull_dist | SMC | 0.478 | -0.0196 | 0.008 | -0.013 / -0.021 / -0.022 | 3/3 | – (seyrek/ayrık) | 0% |
| 5m.rsidiv_bear_r12 | pivot (Fib/trend/dip) | 0.516 | +0.0194 | 0.008 | +0.017 / +0.021 / +0.019 | 3/3 | – (seyrek/ayrık) | 0% |
| 15m.fib_near | pivot (Fib/trend/dip) | 0.530 | +0.0192 | 0.008 | +0.019 / +0.024 / +0.014 | 3/3 | 0.518 | 2% |

q<0,05 **ve** üç blokta aynı işaret: **194** özellik; bunlardan |r| > FWER eşiği olan: 66.

Aile bazında:

| aile | özellik | q<0,05 | …ve 3/3 blok | en güçlü |
|---|---|---|---|---|
| temel | 228 | 68 | 57 | 15m.rci_mean (r +0.025) |
| topluluk | 222 | 42 | 39 | 5m.rf_band (r -0.030) |
| ileri | 177 | 25 | 24 | 15m.rmi (r +0.026) |
| SMC | 132 | 25 | 22 | 5m.brk_bull_dist (r -0.020) |
| pivot (Fib/trend/dip) | 78 | 10 | 10 | 15m.pd_pos (r +0.021) |
| formasyon | 66 | 14 | 13 | 15m.v_depth_atr (r -0.024) |
| gün/seans | 64 | 29 | 29 | 5m.day_range_adr_utc (r -0.032) |

Karşılaştırma — ESKİ kütüphane (aynı yöntem, 401 özellik): q<0,05 **85**; en güçlü |r|: 15m.atr_ratio +0.048; 15m.mass_index +0.039; 5m.mass_index +0.037; 5m.atr_ratio +0.035; 1m.mass_index +0.029; 15m.chaikin_vol +0.027. Yeni kütüphanenin en güçlü |r|: 5m.day_range_adr_utc -0.032; 5m.hour_cos -0.031; 5m.rf_band -0.030; 15m.gc_width -0.029; 15m.gc_above_upper +0.026; 15m.rmi +0.026.

#### t0 — olay 4552, taban 91028, permütasyon 1000

Ham (kontrolsüz) eşleşmiş AUC: FWER<0,05 **448**, BH q<0,10 **763** özellik (FWER eşiği |AUC−½|>0.016). **Kısmi korelasyon** (olay göstergesi ile özellik arasında, aynı eşleşme kümesi içinde, düşüş+oynaklık kontrolleri doğrusal sabitlenerek): FWER<0,05 **260**, BH q<0,05 **498**, q<0,10 **572** özellik (FWER eşiği |r|>0.0149). Kısmi r, seyrek 0/1 bayraklarda da yanlı değildir; AUC'nin artığı yalnız sürekli özelliklerde (412) anlamlıdır.

Kısmi |r| ile en güçlü 25 yeni özellik (AUC ½ = bilgi yok; kısmi r > 0: olayda yüksek):

| özellik | aile | AUC ham | kısmi r | q | blok r B1 / B2 / B3 | işaret tutarlılığı | AUC artık (kontrol sonrası) | NaN payı |
|---|---|---|---|---|---|---|---|---|
| 1m.ssl_state | topluluk | 0.366 | -0.0646 | 0.003 | -0.056 / -0.059 / -0.071 | 3/3 | – (seyrek/ayrık) | 0% |
| 1m.wcci14 | temel | 0.327 | -0.0639 | 0.003 | -0.070 / -0.059 / -0.060 | 3/3 | 0.397 | 0% |
| 1m.lrsi | ileri | 0.352 | -0.0625 | 0.003 | -0.064 / -0.055 / -0.066 | 3/3 | 0.409 | 0% |
| 1m.wcci6 | temel | 0.350 | -0.0623 | 0.003 | -0.064 / -0.059 / -0.061 | 3/3 | 0.407 | 0% |
| 1m.rci9 | temel | 0.345 | -0.0621 | 0.003 | -0.063 / -0.058 / -0.061 | 3/3 | 0.411 | 0% |
| 1m.tdi_band_pos | topluluk | 0.347 | -0.0599 | 0.003 | -0.064 / -0.052 / -0.059 | 3/3 | 0.412 | 0% |
| 1m.pd_deep_discount | pivot (Fib/trend/dip) | 0.616 | +0.0592 | 0.003 | +0.067 / +0.060 / +0.052 | 3/3 | – (seyrek/ayrık) | 4% |
| 1m.wt1 | topluluk | 0.354 | -0.0581 | 0.003 | -0.061 / -0.053 / -0.057 | 3/3 | 0.413 | 0% |
| 5m.wcci_diff | temel | 0.446 | -0.0558 | 0.003 | -0.058 / -0.052 / -0.055 | 3/3 | 0.425 | 0% |
| 1m.pd_pos | pivot (Fib/trend/dip) | 0.349 | -0.0515 | 0.003 | -0.053 / -0.050 / -0.050 | 3/3 | 0.423 | 4% |
| 1m.r2s_14 | ileri | 0.361 | -0.0510 | 0.003 | -0.056 / -0.045 / -0.050 | 3/3 | 0.429 | 0% |
| 5m.wcci6 | temel | 0.358 | -0.0507 | 0.003 | -0.053 / -0.049 / -0.048 | 3/3 | 0.430 | 0% |
| 1m.stc | ileri | 0.377 | -0.0481 | 0.003 | -0.056 / -0.042 / -0.046 | 3/3 | 0.429 | 0% |
| 1m.vs_state | temel | 0.384 | -0.0479 | 0.003 | -0.047 / -0.047 / -0.047 | 3/3 | – (seyrek/ayrık) | 0% |
| 5m.rmi | ileri | 0.503 | +0.0473 | 0.003 | +0.043 / +0.048 / +0.044 | 3/3 | 0.563 | 0% |
| 1m.rci_mean | temel | 0.379 | -0.0472 | 0.003 | -0.044 / -0.048 / -0.048 | 3/3 | 0.433 | 0% |
| 5m.wt2 | topluluk | 0.508 | +0.0472 | 0.003 | +0.053 / +0.045 / +0.040 | 3/3 | 0.561 | 0% |
| 5m.impulse | ileri | 0.370 | -0.0470 | 0.003 | -0.048 / -0.046 / -0.045 | 3/3 | – (seyrek/ayrık) | 0% |
| 1m.wt_diff | topluluk | 0.387 | -0.0463 | 0.003 | -0.051 / -0.043 / -0.043 | 3/3 | 0.432 | 0% |
| 5m.harsi_body | topluluk | 0.402 | -0.0460 | 0.003 | -0.045 / -0.048 / -0.039 | 3/3 | 0.440 | 0% |
| 1m.pd_discount | pivot (Fib/trend/dip) | 0.611 | +0.0459 | 0.003 | +0.040 / +0.047 / +0.046 | 3/3 | – (seyrek/ayrık) | 4% |
| 1m.impulse | ileri | 0.381 | -0.0455 | 0.003 | -0.048 / -0.043 / -0.043 | 3/3 | – (seyrek/ayrık) | 0% |
| 5m.wt1 | topluluk | 0.481 | +0.0449 | 0.003 | +0.051 / +0.042 / +0.039 | 3/3 | 0.557 | 0% |
| 1m.smi | temel | 0.357 | -0.0446 | 0.003 | -0.047 / -0.038 / -0.047 | 3/3 | 0.425 | 0% |
| 1m.rf_dist | topluluk | 0.342 | -0.0445 | 0.003 | -0.040 / -0.045 / -0.048 | 3/3 | 0.444 | 0% |

q<0,05 **ve** üç blokta aynı işaret: **469** özellik; bunlardan |r| > FWER eşiği olan: 259.

Aile bazında:

| aile | özellik | q<0,05 | …ve 3/3 blok | en güçlü |
|---|---|---|---|---|
| temel | 228 | 129 | 123 | 1m.wcci14 (r -0.064) |
| topluluk | 222 | 124 | 118 | 1m.ssl_state (r -0.065) |
| ileri | 177 | 94 | 89 | 1m.lrsi (r -0.063) |
| SMC | 132 | 59 | 56 | 5m.cisd_dn (r +0.031) |
| pivot (Fib/trend/dip) | 78 | 29 | 25 | 1m.pd_deep_discount (r +0.059) |
| formasyon | 66 | 28 | 26 | 5m.vsa_nodemand (r -0.036) |
| gün/seans | 64 | 35 | 32 | 5m.day_range_adr_utc (r -0.035) |

Karşılaştırma — ESKİ kütüphane (aynı yöntem, 401 özellik): q<0,05 **221**; en güçlü |r|: 5m.crsi -0.082; 1m.willr14 -0.063; 1m.donch_pos20 -0.062; 1m.cci20 -0.059; 1m.st_cluster_sum -0.054; 5m.smi_erg +0.054. Yeni kütüphanenin en güçlü |r|: 1m.ssl_state -0.065; 1m.wcci14 -0.064; 1m.lrsi -0.063; 1m.wcci6 -0.062; 1m.rci9 -0.062; 1m.tdi_band_pos -0.060.


### B. Çok değişkenli artış

#### t0

| özellik kümesi | AUC blok-dışı B1 / B2 / B3 | ort. | grup-içi AUC | Δ vs mevcut154 ort. (blok bazlı) |
|---|---|---|---|---|
| mevcut 154 | 0.775 / 0.779 / 0.764 | 0.773 | 0.770 / 0.778 / 0.763 | +0.000 (+0.000 / +0.000 / +0.000) |
| + eski kütüphane | 0.776 / 0.781 / 0.766 | 0.774 | 0.774 / 0.781 / 0.765 | +0.002 (+0.002 / +0.002 / +0.001) |
| + yeni kütüphane | 0.778 / 0.789 / 0.769 | 0.779 | 0.774 / 0.785 / 0.771 | +0.006 (+0.003 / +0.009 / +0.005) |
| + eski + yeni | 0.776 / 0.784 / 0.765 | 0.775 | 0.774 / 0.783 / 0.766 | +0.003 (+0.002 / +0.005 / +0.001) |
| yalnız yeni | 0.755 / 0.765 / 0.742 | 0.754 | 0.757 / 0.764 / 0.745 | -0.019 (-0.019 / -0.015 / -0.022) |
| yalnız eski | 0.758 / 0.767 / 0.752 | 0.759 | 0.756 / 0.769 / 0.751 | -0.014 (-0.017 / -0.012 / -0.013) |

#### t0−10

| özellik kümesi | AUC blok-dışı B1 / B2 / B3 | ort. | grup-içi AUC | Δ vs mevcut154 ort. (blok bazlı) |
|---|---|---|---|---|
| mevcut 154 | 0.622 / 0.636 / 0.630 | 0.629 | 0.617 / 0.635 / 0.627 | +0.000 (+0.000 / +0.000 / +0.000) |
| + eski kütüphane | 0.628 / 0.648 / 0.635 | 0.637 | 0.624 / 0.647 / 0.634 | +0.007 (+0.006 / +0.011 / +0.005) |
| + yeni kütüphane | 0.635 / 0.656 / 0.640 | 0.644 | 0.629 / 0.660 / 0.643 | +0.014 (+0.012 / +0.020 / +0.010) |
| + eski + yeni | 0.639 / 0.660 / 0.635 | 0.645 | 0.633 / 0.659 / 0.633 | +0.015 (+0.017 / +0.024 / +0.005) |
| yalnız yeni | 0.629 / 0.658 / 0.633 | 0.640 | 0.630 / 0.658 / 0.635 | +0.010 (+0.007 / +0.022 / +0.002) |
| yalnız eski | 0.604 / 0.628 / 0.615 | 0.616 | 0.598 / 0.627 / 0.610 | -0.014 (-0.018 / -0.008 / -0.015) |

#### t0 — kesit (kazanç saat/seans özelliklerinden mi?)

| özellik kümesi | AUC B1 / B2 / B3 | ort. | Δ vs mevcut154 |
|---|---|---|---|
| mevcut 154 | 0.775 / 0.779 / 0.764 | 0.773 | +0.000 |
| + yeni (saat/seans-zaman özellikleri HARİÇ) | 0.776 / 0.785 / 0.766 | 0.776 | +0.003 |
| + yeni (gün/seans ailesi HARİÇ) | 0.776 / 0.784 / 0.767 | 0.776 | +0.003 |
| + yalnız saat/seans-zaman özellikleri | 0.775 / 0.779 / 0.762 | 0.772 | -0.001 |
| + yeni (hepsi) | 0.778 / 0.789 / 0.769 | 0.779 | +0.006 |

#### t0−10 — kesit (kazanç saat/seans özelliklerinden mi?)

| özellik kümesi | AUC B1 / B2 / B3 | ort. | Δ vs mevcut154 |
|---|---|---|---|
| mevcut 154 | 0.622 / 0.636 / 0.630 | 0.629 | +0.000 |
| + yeni (saat/seans-zaman özellikleri HARİÇ) | 0.635 / 0.655 / 0.637 | 0.642 | +0.013 |
| + yeni (gün/seans ailesi HARİÇ) | 0.634 / 0.651 / 0.638 | 0.641 | +0.011 |
| + yalnız saat/seans-zaman özellikleri | 0.624 / 0.641 / 0.628 | 0.631 | +0.001 |
| + yeni (hepsi) | 0.635 / 0.656 / 0.640 | 0.644 | +0.014 |


### C. Önceden belirlenmiş sinyaller

Net = exit_sim (60 sn gecikme, %0,15 kayma, %0,1125/bacak) ortalaması, % cinsinden. 'rastgele' = aynı sembollerde sinyal sayısı kadar, sinyalden ≥2 sa uzak rastgele giriş; 'koşulsuz' = tüm geçerli anlardan tekdüze örnek.

| sinyal | blok | n | sinyal/gün | 60 dk önden kesinlik | taban | hit60@1,5 | şans (null3) | lift pp ± SE | net TP1,5 | rastgele (≥2 sa uzak) | koşulsuz | net izleyen | rastg. | koşulsuz |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sqz_rel_up | B1 | 5788 | 199.6 | 2.4% | 0.9% | 18.8% | 17.1% | +2.3 ± 0.7 | -0.51 | -0.54 | -0.51 | -0.53 | -0.55 | -0.52 |
| sqz_rel_up | B2 | 7597 | 253.2 | 2.4% | 1.1% | 20.5% | 17.0% | +3.4 ± 1.1 | -0.50 | -0.52 | -0.49 | -0.53 | -0.53 | -0.50 |
| sqz_rel_up | B3 | 7810 | 258.2 | 2.8% | 1.3% | 21.1% | 17.3% | +3.5 ± 0.8 | -0.53 | -0.53 | -0.49 | -0.54 | -0.53 | -0.49 |
| wt_os53 | B1 | 23763 | 819.4 | 0.8% | 0.9% | 9.9% | 12.2% | -2.0 ± 0.5 | -0.47 | -0.25 | -0.51 | -0.48 | -0.27 | -0.52 |
| wt_os53 | B2 | 28501 | 950.0 | 0.9% | 1.1% | 13.4% | 14.2% | -0.9 ± 0.9 | -0.41 | -0.19 | -0.49 | -0.42 | -0.22 | -0.50 |
| wt_os53 | B3 | 31600 | 1044.6 | 1.0% | 1.3% | 13.6% | 15.0% | -1.6 ± 0.7 | -0.47 | -0.18 | -0.49 | -0.48 | -0.20 | -0.49 |
| qqe_mod | B1 | 41640 | 1435.9 | 0.9% | 0.9% | 11.3% | 12.6% | -1.6 ± 0.6 | -0.57 | -1.00 | -0.51 | -0.58 | -0.99 | -0.52 |
| qqe_mod | B2 | 52384 | 1746.1 | 1.1% | 1.1% | 13.6% | 13.5% | +0.3 ± 0.9 | -0.55 | -1.06 | -0.49 | -0.56 | -1.06 | -0.50 |
| qqe_mod | B3 | 56572 | 1870.1 | 1.2% | 1.3% | 14.6% | 13.7% | +0.9 ± 0.7 | -0.52 | -1.10 | -0.49 | -0.53 | -1.09 | -0.49 |
| wae_up | B1 | 60438 | 2084.1 | 0.9% | 0.9% | 11.3% | 11.4% | -0.7 ± 0.6 | -0.56 | -1.07 | -0.51 | -0.57 | -1.07 | -0.52 |
| wae_up | B2 | 75601 | 2520.0 | 1.1% | 1.1% | 13.6% | 12.4% | +1.0 ± 0.9 | -0.54 | -1.15 | -0.49 | -0.55 | -1.14 | -0.50 |
| wae_up | B3 | 81310 | 2687.9 | 1.2% | 1.3% | 14.3% | 12.8% | +1.0 ± 0.7 | -0.53 | -1.13 | -0.49 | -0.53 | -1.12 | -0.49 |
| utbot_buy | B1 | 74068 | 2554.1 | 0.8% | 0.9% | 10.8% | 11.0% | -0.8 ± 0.5 | -0.54 | -0.72 | -0.51 | -0.55 | -0.72 | -0.52 |
| utbot_buy | B2 | 91983 | 3066.1 | 1.0% | 1.1% | 13.6% | 12.1% | +1.5 ± 0.9 | -0.51 | -0.68 | -0.49 | -0.52 | -0.66 | -0.50 |
| utbot_buy | B3 | 101569 | 3357.7 | 1.2% | 1.3% | 13.6% | 12.6% | +1.4 ± 0.7 | -0.52 | -0.66 | -0.49 | -0.53 | -0.65 | -0.49 |
| ssl_flip_up | B1 | 63103 | 2176.0 | 0.8% | 0.9% | 10.3% | 10.3% | -0.1 ± 0.5 | -0.55 | -0.75 | -0.51 | -0.56 | -0.77 | -0.52 |
| ssl_flip_up | B2 | 78044 | 2601.5 | 0.9% | 1.1% | 12.7% | 11.3% | +2.2 ± 0.8 | -0.53 | -0.63 | -0.49 | -0.54 | -0.62 | -0.50 |
| ssl_flip_up | B3 | 85307 | 2820.1 | 1.1% | 1.3% | 13.1% | 11.8% | +0.8 ± 0.7 | -0.53 | -0.77 | -0.49 | -0.53 | -0.77 | -0.49 |
| rf_buy | B1 | 23536 | 811.6 | 1.2% | 0.9% | 14.0% | 15.9% | -2.4 ± 0.7 | -0.57 | -0.69 | -0.51 | -0.59 | -0.70 | -0.52 |
| rf_buy | B2 | 29954 | 998.5 | 1.3% | 1.1% | 16.4% | 17.3% | -1.3 ± 0.9 | -0.53 | -0.67 | -0.49 | -0.55 | -0.69 | -0.50 |
| rf_buy | B3 | 32253 | 1066.2 | 1.4% | 1.3% | 17.2% | 18.0% | -1.3 ± 0.8 | -0.56 | -0.66 | -0.49 | -0.56 | -0.67 | -0.49 |
| lrsi_up20 | B1 | 55488 | 1913.4 | 0.9% | 0.9% | 10.6% | 10.7% | -0.3 ± 0.5 | -0.52 | -0.22 | -0.51 | -0.53 | -0.26 | -0.52 |
| lrsi_up20 | B2 | 67983 | 2266.1 | 0.9% | 1.1% | 12.9% | 11.8% | +0.8 ± 0.8 | -0.51 | -0.05 | -0.49 | -0.52 | -0.09 | -0.50 |
| lrsi_up20 | B3 | 74667 | 2468.3 | 1.2% | 1.3% | 13.6% | 12.3% | +1.2 ± 0.7 | -0.52 | -0.09 | -0.49 | -0.52 | -0.10 | -0.49 |
| stc_up25 | B1 | 48043 | 1656.7 | 0.9% | 0.9% | 10.9% | 11.6% | -0.3 ± 0.5 | -0.54 | -0.68 | -0.51 | -0.55 | -0.68 | -0.52 |
| stc_up25 | B2 | 59570 | 1985.7 | 1.0% | 1.1% | 13.1% | 12.7% | +0.6 ± 0.7 | -0.54 | -0.64 | -0.49 | -0.55 | -0.65 | -0.50 |
| stc_up25 | B3 | 64106 | 2119.2 | 1.2% | 1.3% | 14.0% | 13.1% | +0.5 ± 0.7 | -0.53 | -0.63 | -0.49 | -0.53 | -0.62 | -0.49 |
| ce_flip_up | B1 | 62594 | 2158.4 | 0.7% | 0.9% | 10.0% | 11.5% | -1.7 ± 0.5 | -0.53 | -0.87 | -0.51 | -0.54 | -0.89 | -0.52 |
| ce_flip_up | B2 | 77967 | 2598.9 | 0.9% | 1.1% | 12.9% | 13.2% | +0.2 ± 0.8 | -0.50 | -0.78 | -0.49 | -0.52 | -0.80 | -0.50 |
| ce_flip_up | B3 | 84997 | 2809.8 | 1.0% | 1.3% | 13.0% | 13.0% | -0.4 ± 0.7 | -0.52 | -0.85 | -0.49 | -0.52 | -0.85 | -0.49 |
| ts_long | B1 | 14026 | 483.7 | 1.8% | 0.9% | 14.6% | 15.5% | -1.2 ± 0.6 | -0.49 | -0.37 | -0.51 | -0.50 | -0.39 | -0.52 |
| ts_long | B2 | 18679 | 622.6 | 1.7% | 1.1% | 17.1% | 16.8% | +0.9 ± 1.0 | -0.44 | -0.32 | -0.49 | -0.46 | -0.34 | -0.50 |
| ts_long | B3 | 21784 | 720.1 | 2.1% | 1.3% | 18.2% | 17.8% | +0.5 ± 0.9 | -0.46 | -0.31 | -0.49 | -0.47 | -0.31 | -0.49 |
| spring | B1 | 3650 | 125.9 | 1.8% | 0.9% | 15.0% | 17.7% | -3.1 ± 0.6 | -0.47 | -0.47 | -0.51 | -0.50 | -0.48 | -0.52 |
| spring | B2 | 5246 | 174.9 | 1.8% | 1.1% | 20.4% | 19.8% | +0.7 ± 1.3 | -0.36 | -0.44 | -0.49 | -0.38 | -0.45 | -0.50 |
| spring | B3 | 5926 | 195.9 | 2.1% | 1.3% | 18.5% | 20.7% | -2.2 ± 1.0 | -0.47 | -0.42 | -0.49 | -0.48 | -0.43 | -0.49 |
| dbot_break | B1 | 4989 | 172.0 | 1.2% | 0.9% | 14.7% | 14.7% | +0.1 ± 0.6 | -0.58 | -0.55 | -0.51 | -0.59 | -0.56 | -0.52 |
| dbot_break | B2 | 5663 | 188.8 | 1.4% | 1.1% | 15.1% | 15.0% | +0.7 ± 0.8 | -0.55 | -0.52 | -0.49 | -0.58 | -0.53 | -0.50 |
| dbot_break | B3 | 6116 | 202.2 | 1.4% | 1.3% | 15.6% | 15.0% | +1.0 ± 0.9 | -0.58 | -0.51 | -0.49 | -0.59 | -0.51 | -0.49 |
| ifvg_bull | B1 | 58505 | 2017.4 | 0.8% | 0.9% | 10.6% | 11.0% | -0.1 ± 0.5 | -0.55 | -0.81 | -0.51 | -0.56 | -0.82 | -0.52 |
| ifvg_bull | B2 | 76276 | 2542.5 | 1.0% | 1.1% | 13.0% | 12.0% | +0.8 ± 0.7 | -0.53 | -0.78 | -0.49 | -0.54 | -0.80 | -0.50 |
| ifvg_bull | B3 | 86028 | 2843.9 | 1.1% | 1.3% | 13.3% | 12.4% | +1.1 ± 0.6 | -0.53 | -0.89 | -0.49 | -0.53 | -0.89 | -0.49 |
| brk_bull | B1 | 8620 | 297.2 | 1.3% | 0.9% | 15.7% | 15.7% | +0.3 ± 0.8 | -0.50 | -0.55 | -0.51 | -0.52 | -0.56 | -0.52 |
| brk_bull | B2 | 10254 | 341.8 | 1.6% | 1.1% | 18.1% | 15.8% | +2.5 ± 1.0 | -0.47 | -0.53 | -0.49 | -0.49 | -0.53 | -0.50 |
| brk_bull | B3 | 10207 | 337.4 | 1.8% | 1.3% | 17.7% | 15.6% | +1.7 ± 0.8 | -0.48 | -0.52 | -0.49 | -0.49 | -0.53 | -0.49 |
| ote_tap | B1 | 26249 | 905.1 | 1.2% | 0.9% | 12.5% | 12.9% | -0.7 ± 0.6 | -0.49 | -0.46 | -0.51 | -0.50 | -0.47 | -0.52 |
| ote_tap | B2 | 32358 | 1078.6 | 1.3% | 1.1% | 14.8% | 13.4% | +1.9 ± 0.8 | -0.49 | -0.41 | -0.49 | -0.50 | -0.42 | -0.50 |
| ote_tap | B3 | 36633 | 1211.0 | 1.5% | 1.3% | 15.1% | 14.2% | +0.7 ± 0.7 | -0.49 | -0.41 | -0.49 | -0.50 | -0.41 | -0.49 |
| orb_utc | B1 | 4292 | 148.0 | 1.1% | 0.9% | 13.2% | 14.4% | -1.2 ± 0.6 | -0.58 | -0.53 | -0.51 | -0.60 | -0.54 | -0.52 |
| orb_utc | B2 | 5486 | 182.9 | 1.0% | 1.1% | 14.6% | 15.7% | -0.6 ± 1.1 | -0.57 | -0.53 | -0.49 | -0.60 | -0.55 | -0.50 |
| orb_utc | B3 | 5949 | 196.7 | 1.2% | 1.3% | 14.7% | 15.4% | -0.3 ± 0.8 | -0.66 | -0.53 | -0.49 | -0.67 | -0.54 | -0.49 |
| orb_tr | B1 | 4311 | 148.7 | 0.6% | 0.9% | 10.8% | 13.5% | -2.5 ± 0.7 | -0.62 | -0.52 | -0.51 | -0.64 | -0.54 | -0.52 |
| orb_tr | B2 | 5388 | 179.6 | 0.8% | 1.1% | 12.7% | 15.0% | -2.3 ± 0.9 | -0.65 | -0.52 | -0.49 | -0.67 | -0.53 | -0.50 |
| orb_tr | B3 | 6399 | 211.5 | 0.9% | 1.3% | 11.4% | 13.8% | -2.9 ± 0.8 | -0.51 | -0.55 | -0.49 | -0.51 | -0.54 | -0.49 |
| rvol_green | B1 | 33409 | 1152.0 | 1.3% | 0.9% | 15.3% | 15.4% | -0.3 ± 0.7 | -0.56 | -0.55 | -0.51 | -0.57 | -0.57 | -0.52 |
| rvol_green | B2 | 46080 | 1536.0 | 1.8% | 1.1% | 19.5% | 16.9% | +2.9 ± 1.0 | -0.51 | -0.56 | -0.49 | -0.52 | -0.58 | -0.50 |
| rvol_green | B3 | 51022 | 1686.7 | 1.9% | 1.3% | 19.7% | 17.4% | +2.3 ± 0.8 | -0.52 | -0.56 | -0.49 | -0.53 | -0.57 | -0.49 |
| vmc_green | B1 | 12087 | 416.8 | 0.9% | 0.9% | 10.3% | 12.9% | -2.6 ± 0.5 | -0.49 | -0.39 | -0.51 | -0.50 | -0.42 | -0.52 |
| vmc_green | B2 | 14694 | 489.8 | 0.9% | 1.1% | 13.2% | 14.5% | -1.9 ± 0.8 | -0.45 | -0.35 | -0.49 | -0.46 | -0.37 | -0.50 |
| vmc_green | B3 | 17121 | 566.0 | 1.2% | 1.3% | 14.3% | 15.6% | -1.6 ± 1.0 | -0.47 | -0.34 | -0.49 | -0.49 | -0.34 | -0.49 |
| HA | B1 | 5934 | 204.6 | 6.6% | 0.9% | 48.6% | 44.9% | +3.9 ± 1.0 | -0.54 | -0.57 | -0.51 | -0.54 | -0.59 | -0.52 |
| HA | B2 | 6766 | 225.5 | 6.6% | 1.1% | 47.0% | 42.1% | +4.5 ± 1.1 | -0.50 | -0.52 | -0.49 | -0.55 | -0.55 | -0.50 |
| HA | B3 | 7643 | 252.7 | 6.7% | 1.3% | 47.8% | 42.2% | +5.7 ± 1.1 | -0.56 | -0.54 | -0.49 | -0.54 | -0.56 | -0.49 |


Olay yakalama ve Hız Avcısı'na (HA) göre öncelik:

| sinyal | blok | olay | t0 öncesi yakalama | sayı-eşleşmiş sıfır | t0 sonrası dâhil | HA t0 öncesi | ort. öncelik (dk, medyan) | ortak olay | HA'dan önce gelme payı | medyan fark dk |
|---|---|---|---|---|---|---|---|---|---|---|
| sqz_rel_up | B1 | 1095 | 11.9% | 6.9% | 26.7% | 39.2% | 35 | 312 | 42.3% | -5 |
| sqz_rel_up | B2 | 1583 | 10.7% | 5.2% | 26.9% | 30.6% | 35 | 413 | 49.2% | +0 |
| sqz_rel_up | B3 | 1874 | 10.7% | 4.4% | 24.5% | 30.6% | 35 | 405 | 47.4% | +0 |
| wt_os53 | B1 | 1095 | 16.5% | 17.9% | 26.0% | 39.2% | 35 | 231 | 69.3% | +25 |
| wt_os53 | B2 | 1583 | 15.5% | 18.9% | 23.2% | 30.6% | 35 | 278 | 73.0% | +25 |
| wt_os53 | B3 | 1874 | 15.2% | 18.9% | 23.7% | 30.6% | 30 | 334 | 74.9% | +30 |
| qqe_mod | B1 | 1095 | 34.3% | 31.1% | 83.7% | 39.2% | 35 | 857 | 50.4% | +5 |
| qqe_mod | B2 | 1583 | 34.5% | 29.7% | 86.5% | 30.6% | 35 | 1154 | 56.2% | +5 |
| qqe_mod | B3 | 1874 | 33.5% | 27.7% | 87.7% | 30.6% | 35 | 1348 | 54.3% | +5 |
| wae_up | B1 | 1095 | 48.5% | 42.8% | 94.2% | 39.2% | 35 | 927 | 59.0% | +10 |
| wae_up | B2 | 1583 | 49.5% | 37.3% | 96.5% | 30.6% | 35 | 1250 | 65.7% | +15 |
| wae_up | B3 | 1874 | 49.8% | 42.3% | 95.4% | 30.6% | 35 | 1445 | 65.5% | +15 |
| utbot_buy | B1 | 1095 | 54.8% | 48.3% | 94.9% | 39.2% | 35 | 926 | 61.0% | +10 |
| utbot_buy | B2 | 1583 | 56.2% | 44.9% | 94.3% | 30.6% | 35 | 1232 | 67.1% | +20 |
| utbot_buy | B3 | 1874 | 58.4% | 46.9% | 94.8% | 30.6% | 35 | 1454 | 67.0% | +20 |
| ssl_flip_up | B1 | 1095 | 46.2% | 42.5% | 86.0% | 39.2% | 35 | 830 | 61.3% | +10 |
| ssl_flip_up | B2 | 1583 | 42.9% | 39.2% | 83.8% | 30.6% | 35 | 1080 | 66.5% | +15 |
| ssl_flip_up | B3 | 1874 | 46.3% | 39.8% | 86.4% | 30.6% | 35 | 1319 | 65.1% | +15 |
| rf_buy | B1 | 1095 | 23.8% | 17.4% | 69.9% | 39.2% | 35 | 721 | 47.9% | +0 |
| rf_buy | B2 | 1583 | 23.4% | 16.9% | 69.1% | 30.6% | 35 | 944 | 51.3% | +5 |
| rf_buy | B3 | 1874 | 23.5% | 16.9% | 70.9% | 30.6% | 30 | 1125 | 50.8% | +5 |
| lrsi_up20 | B1 | 1095 | 41.9% | 38.3% | 73.1% | 39.2% | 35 | 710 | 63.2% | +15 |
| lrsi_up20 | B2 | 1583 | 38.0% | 36.1% | 67.7% | 30.6% | 35 | 897 | 65.3% | +15 |
| lrsi_up20 | B3 | 1874 | 43.5% | 36.8% | 72.1% | 30.6% | 35 | 1103 | 65.7% | +20 |
| stc_up25 | B1 | 1095 | 37.7% | 33.1% | 78.4% | 39.2% | 35 | 780 | 56.9% | +5 |
| stc_up25 | B2 | 1583 | 36.8% | 31.3% | 78.6% | 30.6% | 35 | 1050 | 60.5% | +10 |
| stc_up25 | B3 | 1874 | 38.5% | 33.4% | 80.3% | 30.6% | 35 | 1240 | 61.3% | +10 |
| ce_flip_up | B1 | 1095 | 35.5% | 38.0% | 78.1% | 39.2% | 35 | 823 | 53.1% | +5 |
| ce_flip_up | B2 | 1583 | 39.9% | 39.2% | 76.4% | 30.6% | 35 | 1071 | 57.0% | +10 |
| ce_flip_up | B3 | 1874 | 40.9% | 39.7% | 79.8% | 30.6% | 30 | 1288 | 58.7% | +10 |
| ts_long | B1 | 1095 | 20.2% | 13.8% | 25.3% | 39.2% | 30 | 274 | 60.9% | +20 |
| ts_long | B2 | 1583 | 17.7% | 14.2% | 23.1% | 30.6% | 35 | 320 | 62.2% | +20 |
| ts_long | B3 | 1874 | 20.4% | 11.7% | 26.3% | 30.6% | 30 | 445 | 60.9% | +20 |
| spring | B1 | 1095 | 5.0% | 4.3% | 7.1% | 39.2% | 35 | 78 | 62.8% | +25 |
| spring | B2 | 1583 | 5.3% | 4.0% | 7.3% | 30.6% | 30 | 97 | 58.8% | +25 |
| spring | B3 | 1874 | 5.6% | 4.2% | 7.1% | 30.6% | 30 | 103 | 60.2% | +20 |
| dbot_break | B1 | 1095 | 5.1% | 4.1% | 16.1% | 39.2% | 32 | 172 | 57.0% | +5 |
| dbot_break | B2 | 1583 | 4.9% | 4.1% | 12.7% | 30.6% | 30 | 197 | 56.9% | +5 |
| dbot_break | B3 | 1874 | 4.1% | 3.2% | 12.8% | 30.6% | 35 | 211 | 51.2% | +5 |
| ifvg_bull | B1 | 1095 | 42.3% | 37.8% | 81.1% | 39.2% | 35 | 796 | 61.6% | +15 |
| ifvg_bull | B2 | 1583 | 43.6% | 39.5% | 83.2% | 30.6% | 35 | 1081 | 67.0% | +15 |
| ifvg_bull | B3 | 1874 | 45.1% | 41.0% | 84.6% | 30.6% | 30 | 1288 | 65.6% | +15 |
| brk_bull | B1 | 1095 | 9.6% | 6.4% | 15.9% | 39.2% | 30 | 250 | 35.2% | -10 |
| brk_bull | B2 | 1583 | 9.2% | 6.1% | 15.9% | 30.6% | 30 | 290 | 34.5% | -10 |
| brk_bull | B3 | 1874 | 8.8% | 6.1% | 14.4% | 30.6% | 30 | 339 | 37.2% | -10 |
| ote_tap | B1 | 1095 | 25.5% | 20.6% | 34.6% | 39.2% | 35 | 447 | 49.2% | +0 |
| ote_tap | B2 | 1583 | 22.4% | 20.0% | 29.8% | 30.6% | 30 | 497 | 53.9% | +15 |
| ote_tap | B3 | 1874 | 25.1% | 20.1% | 33.1% | 30.6% | 35 | 687 | 51.2% | +5 |
| orb_utc | B1 | 1095 | 4.0% | 2.5% | 14.6% | 39.2% | 35 | 164 | 43.9% | +0 |
| orb_utc | B2 | 1583 | 3.5% | 3.1% | 16.0% | 30.6% | 32 | 216 | 56.5% | +5 |
| orb_utc | B3 | 1874 | 3.7% | 4.2% | 14.9% | 30.6% | 35 | 237 | 54.4% | +5 |
| orb_tr | B1 | 1095 | 2.3% | 3.5% | 11.0% | 39.2% | 35 | 127 | 44.9% | +0 |
| orb_tr | B2 | 1583 | 2.3% | 3.5% | 11.1% | 30.6% | 35 | 160 | 51.9% | +5 |
| orb_tr | B3 | 1874 | 2.9% | 3.2% | 10.1% | 30.6% | 25 | 167 | 53.3% | +5 |
| rvol_green | B1 | 1095 | 39.3% | 20.3% | 72.3% | 39.2% | 35 | 754 | 52.9% | +5 |
| rvol_green | B2 | 1583 | 50.2% | 26.8% | 87.3% | 30.6% | 35 | 1170 | 63.6% | +10 |
| rvol_green | B3 | 1874 | 50.4% | 25.5% | 89.8% | 30.6% | 35 | 1413 | 63.6% | +10 |
| vmc_green | B1 | 1095 | 9.6% | 8.9% | 16.4% | 39.2% | 40 | 142 | 67.6% | +20 |
| vmc_green | B2 | 1583 | 8.2% | 11.0% | 13.0% | 30.6% | 35 | 155 | 70.3% | +30 |
| vmc_green | B3 | 1874 | 9.4% | 9.9% | 15.7% | 30.6% | 35 | 219 | 73.1% | +20 |
| HA | B1 | 1095 | 32.7% | 6.9% | 74.6% | 39.2% | 30 | 952 | 0.0% | +0 |
| HA | B2 | 1583 | 26.2% | 6.2% | 69.9% | 30.6% | 35 | 1275 | 0.0% | +0 |
| HA | B3 | 1874 | 25.7% | 6.7% | 68.1% | 30.6% | 30 | 1485 | 0.0% | +0 |


Özet:

| sinyal | tanım | net>0 (TP1,5) blok | net>0 (izleyen) blok | net TP1,5 B1 / B2 / B3 | hit lift pp B1 / B2 / B3 | erken-uyarı ölçütü (t0 öncesi yakalama > sıfır x1,5 VE HA'dan önce > %50) |
|---|---|---|---|---|---|---|
| sqz_rel_up | Squeeze Momentum (LazyBear) yukarı salım | 0/3 | 0/3 | -0.51 / -0.50 / -0.53 | +2.3 / +3.4 / +3.5 | 0/3 |
| wt_os53 | WaveTrend WT1>WT2 kesişimi, WT2 <= -53 | 0/3 | 0/3 | -0.47 / -0.41 / -0.47 | -2.0 / -0.9 / -1.6 | 0/3 |
| qqe_mod | QQE MOD mavi çubuk başlangıcı | 0/3 | 0/3 | -0.57 / -0.55 / -0.52 | -1.6 / +0.3 / +0.9 | 0/3 |
| wae_up | Waddah Attar patlama yukarı başlangıcı | 0/3 | 0/3 | -0.56 / -0.54 / -0.53 | -0.7 / +1.0 / +1.0 | 0/3 |
| utbot_buy | UT Bot AL (a=1, ATR10) | 0/3 | 0/3 | -0.54 / -0.51 / -0.52 | -0.8 / +1.5 / +1.4 | 0/3 |
| ssl_flip_up | SSL kanalı yukarı dönüş (SMA10) | 0/3 | 0/3 | -0.55 / -0.53 / -0.53 | -0.1 / +2.2 / +0.8 | 0/3 |
| rf_buy | Range Filter AL (100, 3) | 0/3 | 0/3 | -0.57 / -0.53 / -0.56 | -2.4 / -1.3 / -1.3 | 0/3 |
| lrsi_up20 | Laguerre RSI 0,2 yukarı kesişim | 0/3 | 0/3 | -0.52 / -0.51 / -0.52 | -0.3 / +0.8 / +1.2 | 0/3 |
| stc_up25 | Schaff Trend Cycle 25 yukarı kesişim | 0/3 | 0/3 | -0.54 / -0.54 / -0.53 | -0.3 / +0.6 / +0.5 | 0/3 |
| ce_flip_up | Chandelier Exit yön -> long | 0/3 | 0/3 | -0.53 / -0.50 / -0.52 | -1.7 / +0.2 / -0.4 | 0/3 |
| ts_long | Turtle Soup long (20 bar alçak süpürme + geri kapanış) | 0/3 | 0/3 | -0.49 / -0.44 / -0.46 | -1.2 / +0.9 / +0.5 | 1/3 |
| spring | Wyckoff spring (dar aralık alçak süpürme + hacimli geri alma) | 0/3 | 0/3 | -0.47 / -0.36 / -0.47 | -3.1 / +0.7 / -2.2 | 0/3 |
| dbot_break | Çift dip yaka çizgisi kırılımı | 0/3 | 0/3 | -0.58 / -0.55 / -0.58 | +0.1 / +0.7 / +1.0 | 0/3 |
| ifvg_bull | Inversion FVG (yükseliş) oluştu | 0/3 | 0/3 | -0.55 / -0.53 / -0.53 | -0.1 / +0.8 / +1.1 | 0/3 |
| brk_bull | Yükseliş Breaker Block teması | 0/3 | 0/3 | -0.50 / -0.47 / -0.48 | +0.3 / +2.5 / +1.7 | 0/3 |
| ote_tap | OTE bölgesine (62-79%) ilk giriş (yükseliş bacağı) | 0/3 | 0/3 | -0.49 / -0.49 / -0.49 | -0.7 / +1.9 / +0.7 | 0/3 |
| orb_utc | ORB 30 dk yukarı kırılım (UTC günü) | 0/3 | 0/3 | -0.58 / -0.57 / -0.66 | -1.2 / -0.6 / -0.3 | 0/3 |
| orb_tr | ORB 30 dk yukarı kırılım (TR günü) | 0/3 | 0/3 | -0.62 / -0.65 / -0.51 | -2.5 / -2.3 / -2.9 | 0/3 |
| rvol_green | RVOL(günün saati) > 3 ve yeşil mum | 0/3 | 0/3 | -0.56 / -0.51 / -0.52 | -0.3 / +2.9 / +2.3 | 3/3 |
| vmc_green | Cipher B yeşil nokta (WT dip kesişimi + para akışı yukarı) | 0/3 | 0/3 | -0.49 / -0.45 / -0.47 | -2.6 / -1.9 / -1.6 | 0/3 |
| HA | Hız Avcısı | 0/3 | 0/3 | -0.54 / -0.50 / -0.56 | +3.9 / +4.5 / +5.7 | 0/3 |


LUNATRY 17.10 01:00–05:00 (TR) 5m sinyal anları (cooldown öncesi ilk 8):

| sinyal | tetik saatleri |
|---|---|
| sqz_rel_up | – |
| wt_os53 | – |
| qqe_mod | – |
| wae_up | 00:10, 01:05 |
| utbot_buy | 00:10, 01:05, 03:00 |
| ssl_flip_up | 03:00 |
| rf_buy | 02:50 |
| lrsi_up20 | 03:00 |
| stc_up25 | 03:30 |
| ce_flip_up | 02:10, 02:20, 02:30, 02:40, 02:50, 03:00, 03:10, 03:20 |
| ts_long | – |
| spring | – |
| dbot_break | – |
| ifvg_bull | 00:15, 00:35, 01:05 |
| brk_bull | – |
| ote_tap | 02:40 |
| orb_utc | – |
| orb_tr | 00:35 |
| rvol_green | 01:10, 01:15, 01:20, 01:25, 01:35, 01:40, 01:45, 01:50 |
| vmc_green | – |


### D. HA süzgeci

HA olayı 20343, geçerli 20343, yeni özellik 664.

| sonuç | özellik | q<0,05 | q<0,01 |
|---|---|---|---|
| net (ham) | 664 | 188 | 144 |
| net (ATR-kontrollü) | 664 | 162 | 117 |
| net−taban (ATR-kontrollü) | 664 | 193 | 106 |
| hit (ATR-kontrollü) | 664 | 418 | 356 |
| hit−taban (ATR-kontrollü) | 664 | 420 | 356 |


En güçlü 15 yeni özellik (ATR-kontrollü net−taban |t|):

| özellik | aile | kapsam | ATR-kont. r(net−taban) [t] | q | ATR-kont. r(net) [t] | ATR-kont. r(hit) [t] | blok r(net−taban) | işaret uyumu |
|---|---|---|---|---|---|---|---|---|
| 5m.tl_res_dist | pivot (Fib/trend/dip) | 43% | -0.068 [-5.7] | 0.000 | -0.076 [-6.7] | +0.029 [+2.9] | -0.077 / -0.092 / -0.041 | 3/3 |
| 5m.rvol_tod | temel | 97% | -0.047 [-5.7] | 0.000 | -0.026 [-3.2] | +0.038 [+5.3] | -0.035 / -0.048 / -0.052 | 3/3 |
| 5m.rvol_tod_log | temel | 97% | -0.047 [-5.7] | 0.000 | -0.026 [-3.2] | +0.038 [+5.3] | -0.035 / -0.048 / -0.052 | 3/3 |
| 5m.lrc_pos | temel | 100% | -0.042 [-5.5] | 0.000 | -0.044 [-5.6] | +0.062 [+9.2] | -0.046 / -0.041 / -0.042 | 3/3 |
| 5m.medch_pos | temel | 100% | -0.042 [-5.4] | 0.000 | -0.048 [-6.0] | +0.086 [+12.2] | -0.040 / -0.039 / -0.046 | 3/3 |
| 5m.starc_pos | ileri | 100% | -0.033 [-5.1] | 0.000 | -0.040 [-5.7] | +0.063 [+10.4] | -0.039 / -0.022 / -0.040 | 3/3 |
| 5m.rvol_tod_max3 | temel | 100% | -0.044 [-5.0] | 0.000 | -0.020 [-2.4] | +0.029 [+3.3] | -0.039 / -0.048 / -0.035 | 3/3 |
| 5m.ribbon_px | temel | 100% | -0.043 [-5.0] | 0.000 | -0.049 [-5.8] | +0.081 [+10.7] | -0.037 / -0.045 / -0.045 | 3/3 |
| 5m.pgo14 | ileri | 100% | -0.038 [-5.0] | 0.000 | -0.047 [-5.8] | +0.080 [+11.6] | -0.037 / -0.035 / -0.042 | 3/3 |
| 5m.coral_dist | topluluk | 100% | -0.043 [-5.0] | 0.000 | -0.052 [-5.9] | +0.083 [+10.8] | -0.034 / -0.051 / -0.046 | 3/3 |
| 5m.ha_body_atr | topluluk | 100% | -0.032 [-4.9] | 0.000 | -0.038 [-5.7] | +0.062 [+9.3] | -0.044 / -0.018 / -0.036 | 3/3 |
| 5m.pvi_slope12 | temel | 100% | -0.040 [-4.8] | 0.000 | -0.049 [-5.9] | +0.065 [+9.7] | -0.026 / -0.052 / -0.043 | 3/3 |
| 5m.bull_power | temel | 100% | -0.041 [-4.8] | 0.000 | -0.047 [-5.7] | +0.094 [+12.9] | -0.028 / -0.047 / -0.049 | 3/3 |
| 15m.rvol_tod_max3 | temel | 100% | -0.040 [-4.7] | 0.000 | -0.015 [-1.9] | +0.014 [+1.7] | -0.033 / -0.046 / -0.030 | 3/3 |
| 5m.pdl_sweep_r12_utc | gün/seans | 100% | +0.031 [+4.7] | 0.000 | +0.027 [+4.0] | -0.000 [-0.0] | +0.011 / +0.037 / +0.044 | 3/3 |

q<0,05 ve 3/3 blokta aynı işaret: **180** özellik; en güçlüleri: 5m.tl_res_dist (r -0.068); 5m.rvol_tod (r -0.047); 5m.rvol_tod_log (r -0.047); 5m.lrc_pos (r -0.042); 5m.medch_pos (r -0.042); 5m.starc_pos (r -0.033); 5m.rvol_tod_max3 (r -0.044); 5m.ribbon_px (r -0.043)


Önceden belirlenmiş sinyal bayrakları HA süzgeci olarak (tutulan = bayrak 1; Δ = tutulan − hepsi, aynı blok; %):

| bayrak | tutulan pay | n B1 / B2 / B3 | Δ(net−taban) B1 / B2 / B3 | Δ(net) B1 / B2 / B3 |
|---|---|---|---|---|
| 15m.ce_flip_up_r3 | 23.2% | 1362 / 1613 / 1737 | -0.00 / -0.07 / -0.05 | +0.03 / -0.03 / -0.03 |
| 15m.dbot_break_r12 | 8.0% | 475 / 572 / 577 | -0.11 / -0.01 / -0.05 | -0.04 / +0.05 / -0.08 |
| 15m.lrsi_cross_up20_r3 | 15.7% | 934 / 1012 / 1239 | +0.02 / +0.08 / -0.04 | +0.04 / +0.02 / -0.00 |
| 15m.qqe_blue_on_r3 | 15.6% | 993 / 1065 / 1125 | -0.10 / -0.07 / -0.01 | -0.03 / -0.06 / +0.03 |
| 15m.rf_buy_r6 | 27.3% | 1641 / 1842 / 2062 | +0.01 / -0.06 / -0.11 | +0.01 / -0.03 / -0.12 |
| 15m.spring_r12 | 3.7% | 182 / 289 / 280 | -0.08 / +0.15 / +0.40 | -0.08 / +0.01 / +0.36 |
| 15m.sqzm_rel_up_r3 | 5.1% | 310 / 357 / 378 | +0.10 / -0.08 / -0.04 | +0.15 / -0.05 / -0.03 |
| 15m.ssl_flip_up_r3 | 19.0% | 1180 / 1234 / 1461 | -0.14 / -0.07 / -0.03 | -0.06 / -0.11 / +0.02 |
| 15m.stc_cross_up25_r3 | 14.3% | 878 / 954 / 1086 | +0.04 / -0.07 / -0.03 | +0.08 / -0.05 / -0.01 |
| 15m.ts20_long_r6 | 10.5% | 603 / 691 / 833 | +0.11 / +0.22 / +0.04 | +0.02 / +0.11 / +0.04 |
| 15m.utb_buy_r6 | 52.0% | 3183 / 3508 / 3879 | -0.01 / -0.00 / -0.07 | +0.02 / -0.01 / -0.05 |
| 15m.wt_cross_up_os53_r3 | 3.0% | 202 / 190 / 219 | -0.14 / -0.15 / -0.06 | -0.15 / -0.19 / -0.02 |
| 5m.brk_bull_tap | 4.2% | 341 / 261 / 253 | -0.10 / +0.12 / +0.04 | -0.02 / +0.05 / +0.04 |
| 5m.ce_flip_up | 9.6% | 538 / 650 / 773 | -0.00 / -0.04 / -0.16 | -0.02 / -0.08 / -0.04 |
| 5m.ce_flip_up_r3 | 30.3% | 1725 / 2132 / 2308 | -0.07 / +0.02 / -0.08 | -0.00 / +0.00 / -0.01 |
| 5m.dbot_break | 1.3% | 106 / 75 / 81 | -0.22 / -0.48 / +0.19 | -0.23 / -0.37 / +0.29 |
| 5m.dbot_break_r12 | 8.2% | 586 / 551 / 536 | +0.03 / -0.17 / -0.07 | +0.09 / -0.15 / -0.04 |
| 5m.ifvg_bull_new | 11.8% | 656 / 758 / 984 | +0.11 / -0.04 / -0.10 | +0.05 / -0.09 / -0.02 |
| 5m.lrsi_cross_up20 | 7.1% | 416 / 458 / 568 | +0.15 / -0.11 / +0.11 | -0.06 / -0.09 / +0.06 |
| 5m.lrsi_cross_up20_r3 | 24.2% | 1432 / 1624 / 1869 | -0.00 / +0.03 / +0.07 | -0.04 / +0.00 / +0.07 |
| 5m.orb30_tr_up_first | 0.8% | 42 / 59 / 61 | -0.15 / -0.27 / -0.34 | -0.12 / -0.35 / -0.32 |
| 5m.orb30_utc_up_first | 0.8% | 50 / 53 / 52 | +0.16 / -0.23 / -0.70 | +0.32 / -0.39 / -0.56 |
| 5m.ote_long_tap | 1.6% | 92 / 91 / 133 | +0.08 / +0.24 / +0.09 | +0.02 / +0.14 / +0.03 |
| 5m.qqe_blue_on | 8.5% | 495 / 595 / 633 | -0.21 / -0.05 / -0.02 | -0.17 / -0.03 / +0.05 |
| 5m.qqe_blue_on_r3 | 25.3% | 1514 / 1789 / 1851 | -0.09 / -0.06 / +0.09 | +0.00 / -0.04 / +0.14 |
| 5m.rf_buy | 8.0% | 422 / 555 / 660 | +0.03 / +0.04 / -0.04 | +0.04 / +0.11 / -0.01 |
| 5m.rf_buy_r6 | 34.2% | 2019 / 2336 / 2599 | -0.09 / -0.02 / -0.03 | -0.03 / +0.01 / +0.00 |
| 5m.rvol_tod_green3 | 35.7% | 1793 / 2462 / 2999 | -0.04 / +0.02 / -0.07 | -0.05 / +0.05 / -0.05 |
| 5m.spring | 0.5% | 27 / 41 / 38 | -0.27 / +0.03 / -0.34 | -0.32 / -0.00 / -0.19 |
| 5m.spring_r12 | 4.0% | 190 / 293 / 331 | -0.15 / +0.18 / +0.02 | -0.17 / +0.14 / -0.03 |
| 5m.sqzm_rel_up | 1.9% | 115 / 152 / 126 | +0.37 / +0.14 / +0.08 | +0.31 / +0.24 / +0.14 |
| 5m.sqzm_rel_up_r3 | 5.6% | 340 / 413 / 392 | +0.08 / +0.07 / -0.02 | +0.15 / +0.07 / -0.01 |
| 5m.ssl_flip_up | 9.6% | 604 / 609 / 749 | +0.03 / +0.13 / -0.01 | -0.07 / +0.10 / +0.01 |
| 5m.ssl_flip_up_r3 | 32.5% | 1980 / 2197 / 2444 | -0.02 / +0.06 / -0.03 | -0.02 / +0.02 / +0.01 |
| 5m.stc_cross_up25 | 7.5% | 442 / 498 / 584 | -0.07 / +0.24 / -0.02 | -0.14 / +0.22 / +0.02 |
| 5m.stc_cross_up25_r3 | 24.0% | 1458 / 1651 / 1772 | -0.08 / +0.10 / +0.07 | -0.04 / +0.06 / +0.10 |
| 5m.ts20_long | 1.7% | 101 / 117 / 126 | -0.17 / +0.23 / +0.30 | -0.13 / +0.11 / +0.29 |
| 5m.ts20_long_r6 | 10.6% | 610 / 697 / 845 | -0.05 / -0.02 / +0.11 | -0.09 / -0.08 / +0.08 |
| 5m.utb_buy | 11.4% | 750 / 683 / 877 | -0.05 / +0.02 / +0.22 | -0.13 / -0.01 / +0.18 |
| 5m.utb_buy_r6 | 63.4% | 3906 / 4253 / 4737 | -0.04 / +0.01 / +0.01 | -0.01 / -0.01 / +0.04 |
| 5m.vmc_green_mf | 0.6% | 39 / 29 / 53 | -0.33 / +0.49 / +0.03 | -0.26 / +0.28 / +0.08 |
| 5m.wae_expl_up_on | 12.1% | 756 / 769 / 941 | -0.03 / +0.09 / +0.03 | -0.09 / +0.04 / +0.03 |
| 5m.wt_cross_up_os53 | 1.0% | 59 / 62 / 81 | -0.03 / +0.31 / +0.04 | +0.02 / +0.22 / +0.01 |
| 5m.wt_cross_up_os53_r3 | 5.4% | 332 / 333 / 432 | +0.22 / +0.03 / +0.14 | +0.08 / -0.12 / +0.09 |


Kural arama — B1'de seçildi (hedef A: net−taban, N: ham net), B2/B3 DOKUNULMADAN:

| kural | koşul | seçim t | n B1 / B2 / B3 | net tutulan | net hepsi | Δ net | Δ(net−taban) |
|---|---|---|---|---|---|---|---|
| A1 | `5m.sk > 52.69` | 3.0 (n 2037) | 2037 / 2366 / 2759 | -0.43 / -0.53 / -0.67 | -0.54 / -0.51 / -0.62 | +0.11 / -0.02 / -0.04 | +0.29 / -0.06 / +0.05 |
| A2 | `15m.ribbon_width > 2.406` | 2.8 (n 2037) | 2037 / 2100 / 2500 | -0.45 / -0.55 / -0.60 | -0.54 / -0.51 / -0.62 | +0.09 / -0.04 / +0.02 | +0.29 / -0.07 / +0.13 |
| A3 | `15m.utad_r12 > 1e-09` | 2.6 (n 1694) | 1694 / 2060 / 2253 | -0.42 / -0.54 / -0.62 | -0.54 / -0.51 / -0.62 | +0.12 / -0.03 / -0.00 | +0.17 / -0.05 / +0.02 |
| A4 | `15m.ce_dist > 2.334` | 2.6 (n 2034) | 2034 / 2437 / 2658 | -0.47 / -0.45 / -0.64 | -0.54 / -0.51 / -0.62 | +0.07 / +0.06 / -0.02 | +0.17 / +0.07 / +0.06 |
| A5 | `15m.bbtrend > 1.973` | 2.5 (n 2037) | 2037 / 2397 / 2726 | -0.41 / -0.47 / -0.63 | -0.54 / -0.51 / -0.62 | +0.13 / +0.04 / -0.01 | +0.23 / +0.07 / +0.01 |
| N1 | `5m.t3_dist <= 0.6022` | 2.5 (n 2037) | 2037 / 2027 / 2048 | -0.40 / -0.52 / -0.62 | -0.54 / -0.51 / -0.62 | +0.14 / -0.00 / +0.00 | +0.15 / -0.03 / +0.01 |
| N2 | `15m.vmc_mf > 7.269` | 2.5 (n 2037) | 2037 / 2581 / 2740 | -0.37 / -0.46 / -0.65 | -0.54 / -0.51 / -0.62 | +0.17 / +0.06 / -0.03 | +0.17 / +0.03 / +0.00 |
| N3 | `15m.tl_sup_dist <= 4.284` | 2.3 (n 2467) | 2467 / 2810 / 3039 | -0.44 / -0.45 / -0.61 | -0.54 / -0.51 / -0.62 | +0.10 / +0.06 / +0.01 | +0.05 / +0.07 / -0.03 |
| N4 | `15m.psy12 > 58.33` | 2.3 (n 1247) | 1247 / 1704 / 1764 | -0.35 / -0.43 / -0.58 | -0.54 / -0.51 / -0.62 | +0.20 / +0.08 / +0.04 | +0.20 / +0.07 / +0.08 |
| N5 | `5m.osma_chg <= 0.04827` | 2.2 (n 3055) | 3055 / 3294 / 3409 | -0.44 / -0.53 / -0.61 | -0.54 / -0.51 / -0.62 | +0.10 / -0.01 / +0.02 | +0.08 / -0.04 / -0.00 |


Aşırı uyum tanısı (B1'de en iyi 50 aday kuralın seçim-dışı ortalama Δ'sı):

| hedef | aday | OOS en iyi-50 ort. Δ | pozitif pay | tüm adaylar ort. Δ | pozitif pay |
|---|---|---|---|---|---|
| net−taban | 2149 | +0.02 | 76.0% | +0.00 | 50.4% |
| ham net | 2149 | +0.00 | 50.0% | -0.00 | 50.2% |


B1'de en yüksek skorlu 300 aday kuraldan (her blokta n≥30): **tüm üç blokta** HA net'ini (hepsine göre) artıran 98; üç blokta mutlak net>0 olan 0. (Bağımsız yazı-tura beklentisi ≈ 12%.)

| kural | n | net B1 / B2 / B3 | Δ net B1 / B2 / B3 |
|---|---|---|---|
| `5m.tl_res_dist <= 1.959` | 1264 / 1498 / 1655 | -0.42 / -0.40 / -0.51 | +0.12 / +0.12 / +0.11 |
| `5m.tl_res_dist <= 3.188` | 1685 / 1995 / 2190 | -0.47 / -0.45 / -0.56 | +0.07 / +0.06 / +0.06 |
| `5m.cisd_dn_r6 > 1e-09` | 1113 / 1267 / 1512 | -0.44 / -0.46 / -0.51 | +0.10 / +0.05 / +0.11 |
| `5m.medch_pos <= 0.35` | 2039 / 2120 / 2379 | -0.47 / -0.47 / -0.55 | +0.07 / +0.05 / +0.07 |
| `15m.aroon_osc_chg5 <= -4` | 2099 / 2376 / 2754 | -0.48 / -0.47 / -0.56 | +0.06 / +0.04 / +0.06 |
| `15m.psy12 > 58.33` | 1247 / 1704 / 1764 | -0.35 / -0.43 / -0.58 | +0.20 / +0.08 / +0.04 |
| `5m.coral_dist <= 0.833` | 2037 / 2156 / 2397 | -0.48 / -0.48 / -0.56 | +0.06 / +0.04 / +0.06 |
| `5m.pvi_slope12 <= 1.43` | 3055 / 3450 / 3619 | -0.49 / -0.48 / -0.53 | +0.05 / +0.04 / +0.10 |
| `5m.tl_sup_dist <= 2.954` | 2409 / 2801 / 2907 | -0.48 / -0.46 / -0.58 | +0.06 / +0.05 / +0.04 |
| `5m.coral_dist <= 1.521` | 3055 / 3284 / 3545 | -0.46 / -0.48 / -0.53 | +0.08 / +0.04 / +0.10 |

---

### A. Özellik sıralaması

#### t0−10 — olay 4552, taban 91028, permütasyon 1000

Ham (kontrolsüz) eşleşmiş AUC: FWER<0,05 **211**, BH q<0,10 **491** özellik (FWER eşiği |AUC−½|>0.016). **Kısmi korelasyon** (olay göstergesi ile özellik arasında, aynı eşleşme kümesi içinde, düşüş+oynaklık kontrolleri doğrusal sabitlenerek): FWER<0,05 **67**, BH q<0,05 **213**, q<0,10 **267** özellik (FWER eşiği |r|>0.0149). Kısmi r, seyrek 0/1 bayraklarda da yanlı değildir; AUC'nin artığı yalnız sürekli özelliklerde (412) anlamlıdır.

Kısmi |r| ile en güçlü 25 yeni özellik (AUC ½ = bilgi yok; kısmi r > 0: olayda yüksek):

| özellik | aile | AUC ham | kısmi r | q | blok r B1 / B2 / B3 | işaret tutarlılığı | AUC artık (kontrol sonrası) | NaN payı |
|---|---|---|---|---|---|---|---|---|
| 5m.day_range_adr_utc | gün/seans | 0.489 | -0.0317 | 0.008 | -0.018 / -0.052 / -0.026 | 3/3 | 0.456 | 2% |
| 5m.hour_cos | gün/seans | 0.452 | -0.0315 | 0.008 | -0.021 / -0.030 / -0.038 | 3/3 | 0.454 | 0% |
| 5m.rf_band | topluluk | 0.432 | -0.0304 | 0.008 | -0.025 / -0.048 / -0.026 | 3/3 | 0.421 | 0% |
| 15m.gc_width | topluluk | 0.429 | -0.0287 | 0.008 | -0.023 / -0.044 / -0.024 | 3/3 | 0.428 | 1% |
| 15m.gc_above_upper | topluluk | 0.537 | +0.0264 | 0.008 | +0.035 / +0.029 / +0.018 | 3/3 | – (seyrek/ayrık) | 1% |
| 15m.rmi | ileri | 0.531 | +0.0264 | 0.008 | +0.021 / +0.034 / +0.023 | 3/3 | 0.530 | 0% |
| 15m.harsi | topluluk | 0.535 | +0.0259 | 0.008 | +0.020 / +0.035 / +0.021 | 3/3 | 0.529 | 0% |
| 15m.rci_mean | temel | 0.533 | +0.0250 | 0.008 | +0.025 / +0.032 / +0.018 | 3/3 | 0.525 | 0% |
| 15m.v_depth_atr | formasyon | 0.478 | -0.0241 | 0.008 | -0.026 / -0.024 / -0.022 | 3/3 | – (seyrek/ayrık) | 0% |
| 5m.day_range_adr_tr | gün/seans | 0.515 | -0.0232 | 0.008 | -0.015 / -0.042 / -0.014 | 3/3 | 0.475 | 2% |
| 15m.wt1 | topluluk | 0.531 | +0.0228 | 0.008 | +0.015 / +0.025 / +0.025 | 3/3 | 0.531 | 0% |
| 5m.gc_above_upper | topluluk | 0.535 | +0.0226 | 0.008 | +0.015 / +0.022 / +0.027 | 3/3 | – (seyrek/ayrık) | 0% |
| 15m.wt2 | topluluk | 0.528 | +0.0219 | 0.008 | +0.014 / +0.024 / +0.024 | 3/3 | 0.529 | 0% |
| 15m.pd_pos | pivot (Fib/trend/dip) | 0.536 | +0.0211 | 0.008 | +0.022 / +0.021 / +0.021 | 3/3 | 0.525 | 2% |
| 15m.pd_discount | pivot (Fib/trend/dip) | 0.466 | -0.0211 | 0.008 | -0.011 / -0.024 / -0.025 | 3/3 | – (seyrek/ayrık) | 2% |
| 15m.aroon_up | temel | 0.523 | +0.0204 | 0.008 | +0.014 / +0.025 / +0.018 | 3/3 | – (seyrek/ayrık) | 0% |
| 15m.rci26 | temel | 0.531 | +0.0204 | 0.008 | +0.016 / +0.030 / +0.013 | 3/3 | 0.529 | 0% |
| 15m.ribbon_align | temel | 0.534 | +0.0201 | 0.008 | +0.024 / +0.022 / +0.015 | 3/3 | – (seyrek/ayrık) | 0% |
| 5m.lrc_width | temel | 0.468 | -0.0198 | 0.008 | -0.015 / -0.031 / -0.016 | 3/3 | 0.439 | 0% |
| 5m.rmi | ileri | 0.533 | +0.0198 | 0.008 | +0.006 / +0.027 / +0.024 | 3/3 | 0.526 | 0% |
| 5m.kz_nypm | gün/seans | 0.484 | -0.0198 | 0.008 | -0.023 / -0.026 / -0.013 | 3/3 | – (seyrek/ayrık) | 0% |
| 15m.rf_band | topluluk | 0.452 | -0.0197 | 0.008 | -0.011 / -0.039 / -0.022 | 3/3 | 0.455 | 1% |
| 5m.brk_bull_dist | SMC | 0.478 | -0.0196 | 0.008 | -0.013 / -0.021 / -0.022 | 3/3 | – (seyrek/ayrık) | 0% |
| 5m.rsidiv_bear_r12 | pivot (Fib/trend/dip) | 0.516 | +0.0194 | 0.008 | +0.017 / +0.021 / +0.019 | 3/3 | – (seyrek/ayrık) | 0% |
| 15m.fib_near | pivot (Fib/trend/dip) | 0.530 | +0.0192 | 0.008 | +0.019 / +0.024 / +0.014 | 3/3 | 0.518 | 2% |

q<0,05 **ve** üç blokta aynı işaret: **194** özellik; bunlardan |r| > FWER eşiği olan: 66.

Aile bazında:

| aile | özellik | q<0,05 | …ve 3/3 blok | en güçlü |
|---|---|---|---|---|
| temel | 228 | 68 | 57 | 15m.rci_mean (r +0.025) |
| topluluk | 222 | 42 | 39 | 5m.rf_band (r -0.030) |
| ileri | 177 | 25 | 24 | 15m.rmi (r +0.026) |
| SMC | 132 | 25 | 22 | 5m.brk_bull_dist (r -0.020) |
| pivot (Fib/trend/dip) | 78 | 10 | 10 | 15m.pd_pos (r +0.021) |
| formasyon | 66 | 14 | 13 | 15m.v_depth_atr (r -0.024) |
| gün/seans | 64 | 29 | 29 | 5m.day_range_adr_utc (r -0.032) |

Karşılaştırma — ESKİ kütüphane (aynı yöntem, 401 özellik): q<0,05 **85**; en güçlü |r|: 15m.atr_ratio +0.048; 15m.mass_index +0.039; 5m.mass_index +0.037; 5m.atr_ratio +0.035; 1m.mass_index +0.029; 15m.chaikin_vol +0.027. Yeni kütüphanenin en güçlü |r|: 5m.day_range_adr_utc -0.032; 5m.hour_cos -0.031; 5m.rf_band -0.030; 15m.gc_width -0.029; 15m.gc_above_upper +0.026; 15m.rmi +0.026.

#### t0 — olay 4552, taban 91028, permütasyon 1000

Ham (kontrolsüz) eşleşmiş AUC: FWER<0,05 **448**, BH q<0,10 **763** özellik (FWER eşiği |AUC−½|>0.016). **Kısmi korelasyon** (olay göstergesi ile özellik arasında, aynı eşleşme kümesi içinde, düşüş+oynaklık kontrolleri doğrusal sabitlenerek): FWER<0,05 **260**, BH q<0,05 **498**, q<0,10 **572** özellik (FWER eşiği |r|>0.0149). Kısmi r, seyrek 0/1 bayraklarda da yanlı değildir; AUC'nin artığı yalnız sürekli özelliklerde (412) anlamlıdır.

Kısmi |r| ile en güçlü 25 yeni özellik (AUC ½ = bilgi yok; kısmi r > 0: olayda yüksek):

| özellik | aile | AUC ham | kısmi r | q | blok r B1 / B2 / B3 | işaret tutarlılığı | AUC artık (kontrol sonrası) | NaN payı |
|---|---|---|---|---|---|---|---|---|
| 1m.ssl_state | topluluk | 0.366 | -0.0646 | 0.003 | -0.056 / -0.059 / -0.071 | 3/3 | – (seyrek/ayrık) | 0% |
| 1m.wcci14 | temel | 0.327 | -0.0639 | 0.003 | -0.070 / -0.059 / -0.060 | 3/3 | 0.397 | 0% |
| 1m.lrsi | ileri | 0.352 | -0.0625 | 0.003 | -0.064 / -0.055 / -0.066 | 3/3 | 0.409 | 0% |
| 1m.wcci6 | temel | 0.350 | -0.0623 | 0.003 | -0.064 / -0.059 / -0.061 | 3/3 | 0.407 | 0% |
| 1m.rci9 | temel | 0.345 | -0.0621 | 0.003 | -0.063 / -0.058 / -0.061 | 3/3 | 0.411 | 0% |
| 1m.tdi_band_pos | topluluk | 0.347 | -0.0599 | 0.003 | -0.064 / -0.052 / -0.059 | 3/3 | 0.412 | 0% |
| 1m.pd_deep_discount | pivot (Fib/trend/dip) | 0.616 | +0.0592 | 0.003 | +0.067 / +0.060 / +0.052 | 3/3 | – (seyrek/ayrık) | 4% |
| 1m.wt1 | topluluk | 0.354 | -0.0581 | 0.003 | -0.061 / -0.053 / -0.057 | 3/3 | 0.413 | 0% |
| 5m.wcci_diff | temel | 0.446 | -0.0558 | 0.003 | -0.058 / -0.052 / -0.055 | 3/3 | 0.425 | 0% |
| 1m.pd_pos | pivot (Fib/trend/dip) | 0.349 | -0.0515 | 0.003 | -0.053 / -0.050 / -0.050 | 3/3 | 0.423 | 4% |
| 1m.r2s_14 | ileri | 0.361 | -0.0510 | 0.003 | -0.056 / -0.045 / -0.050 | 3/3 | 0.429 | 0% |
| 5m.wcci6 | temel | 0.358 | -0.0507 | 0.003 | -0.053 / -0.049 / -0.048 | 3/3 | 0.430 | 0% |
| 1m.stc | ileri | 0.377 | -0.0481 | 0.003 | -0.056 / -0.042 / -0.046 | 3/3 | 0.429 | 0% |
| 1m.vs_state | temel | 0.384 | -0.0479 | 0.003 | -0.047 / -0.047 / -0.047 | 3/3 | – (seyrek/ayrık) | 0% |
| 5m.rmi | ileri | 0.503 | +0.0473 | 0.003 | +0.043 / +0.048 / +0.044 | 3/3 | 0.563 | 0% |
| 1m.rci_mean | temel | 0.379 | -0.0472 | 0.003 | -0.044 / -0.048 / -0.048 | 3/3 | 0.433 | 0% |
| 5m.wt2 | topluluk | 0.508 | +0.0472 | 0.003 | +0.053 / +0.045 / +0.040 | 3/3 | 0.561 | 0% |
| 5m.impulse | ileri | 0.370 | -0.0470 | 0.003 | -0.048 / -0.046 / -0.045 | 3/3 | – (seyrek/ayrık) | 0% |
| 1m.wt_diff | topluluk | 0.387 | -0.0463 | 0.003 | -0.051 / -0.043 / -0.043 | 3/3 | 0.432 | 0% |
| 5m.harsi_body | topluluk | 0.402 | -0.0460 | 0.003 | -0.045 / -0.048 / -0.039 | 3/3 | 0.440 | 0% |
| 1m.pd_discount | pivot (Fib/trend/dip) | 0.611 | +0.0459 | 0.003 | +0.040 / +0.047 / +0.046 | 3/3 | – (seyrek/ayrık) | 4% |
| 1m.impulse | ileri | 0.381 | -0.0455 | 0.003 | -0.048 / -0.043 / -0.043 | 3/3 | – (seyrek/ayrık) | 0% |
| 5m.wt1 | topluluk | 0.481 | +0.0449 | 0.003 | +0.051 / +0.042 / +0.039 | 3/3 | 0.557 | 0% |
| 1m.smi | temel | 0.357 | -0.0446 | 0.003 | -0.047 / -0.038 / -0.047 | 3/3 | 0.425 | 0% |
| 1m.rf_dist | topluluk | 0.342 | -0.0445 | 0.003 | -0.040 / -0.045 / -0.048 | 3/3 | 0.444 | 0% |

q<0,05 **ve** üç blokta aynı işaret: **469** özellik; bunlardan |r| > FWER eşiği olan: 259.

Aile bazında:

| aile | özellik | q<0,05 | …ve 3/3 blok | en güçlü |
|---|---|---|---|---|
| temel | 228 | 129 | 123 | 1m.wcci14 (r -0.064) |
| topluluk | 222 | 124 | 118 | 1m.ssl_state (r -0.065) |
| ileri | 177 | 94 | 89 | 1m.lrsi (r -0.063) |
| SMC | 132 | 59 | 56 | 5m.cisd_dn (r +0.031) |
| pivot (Fib/trend/dip) | 78 | 29 | 25 | 1m.pd_deep_discount (r +0.059) |
| formasyon | 66 | 28 | 26 | 5m.vsa_nodemand (r -0.036) |
| gün/seans | 64 | 35 | 32 | 5m.day_range_adr_utc (r -0.035) |

Karşılaştırma — ESKİ kütüphane (aynı yöntem, 401 özellik): q<0,05 **221**; en güçlü |r|: 5m.crsi -0.082; 1m.willr14 -0.063; 1m.donch_pos20 -0.062; 1m.cci20 -0.059; 1m.st_cluster_sum -0.054; 5m.smi_erg +0.054. Yeni kütüphanenin en güçlü |r|: 1m.ssl_state -0.065; 1m.wcci14 -0.064; 1m.lrsi -0.063; 1m.wcci6 -0.062; 1m.rci9 -0.062; 1m.tdi_band_pos -0.060.


### B. Çok değişkenli artış

#### t0

| özellik kümesi | AUC blok-dışı B1 / B2 / B3 | ort. | grup-içi AUC | Δ vs mevcut154 ort. (blok bazlı) |
|---|---|---|---|---|
| mevcut 154 | 0.775 / 0.779 / 0.764 | 0.773 | 0.770 / 0.778 / 0.763 | +0.000 (+0.000 / +0.000 / +0.000) |
| + eski kütüphane | 0.776 / 0.781 / 0.766 | 0.774 | 0.774 / 0.781 / 0.765 | +0.002 (+0.002 / +0.002 / +0.001) |
| + yeni kütüphane | 0.778 / 0.789 / 0.769 | 0.779 | 0.774 / 0.785 / 0.771 | +0.006 (+0.003 / +0.009 / +0.005) |
| + eski + yeni | 0.776 / 0.784 / 0.765 | 0.775 | 0.774 / 0.783 / 0.766 | +0.003 (+0.002 / +0.005 / +0.001) |
| yalnız yeni | 0.755 / 0.765 / 0.742 | 0.754 | 0.757 / 0.764 / 0.745 | -0.019 (-0.019 / -0.015 / -0.022) |
| yalnız eski | 0.758 / 0.767 / 0.752 | 0.759 | 0.756 / 0.769 / 0.751 | -0.014 (-0.017 / -0.012 / -0.013) |

#### t0−10

| özellik kümesi | AUC blok-dışı B1 / B2 / B3 | ort. | grup-içi AUC | Δ vs mevcut154 ort. (blok bazlı) |
|---|---|---|---|---|
| mevcut 154 | 0.622 / 0.636 / 0.630 | 0.629 | 0.617 / 0.635 / 0.627 | +0.000 (+0.000 / +0.000 / +0.000) |
| + eski kütüphane | 0.628 / 0.648 / 0.635 | 0.637 | 0.624 / 0.647 / 0.634 | +0.007 (+0.006 / +0.011 / +0.005) |
| + yeni kütüphane | 0.635 / 0.656 / 0.640 | 0.644 | 0.629 / 0.660 / 0.643 | +0.014 (+0.012 / +0.020 / +0.010) |
| + eski + yeni | 0.639 / 0.660 / 0.635 | 0.645 | 0.633 / 0.659 / 0.633 | +0.015 (+0.017 / +0.024 / +0.005) |
| yalnız yeni | 0.629 / 0.658 / 0.633 | 0.640 | 0.630 / 0.658 / 0.635 | +0.010 (+0.007 / +0.022 / +0.002) |
| yalnız eski | 0.604 / 0.628 / 0.615 | 0.616 | 0.598 / 0.627 / 0.610 | -0.014 (-0.018 / -0.008 / -0.015) |

#### t0 — kesit (kazanç saat/seans özelliklerinden mi?)

| özellik kümesi | AUC B1 / B2 / B3 | ort. | Δ vs mevcut154 |
|---|---|---|---|
| mevcut 154 | 0.775 / 0.779 / 0.764 | 0.773 | +0.000 |
| + yeni (saat/seans-zaman özellikleri HARİÇ) | 0.776 / 0.785 / 0.766 | 0.776 | +0.003 |
| + yeni (gün/seans ailesi HARİÇ) | 0.776 / 0.784 / 0.767 | 0.776 | +0.003 |
| + yalnız saat/seans-zaman özellikleri | 0.775 / 0.779 / 0.762 | 0.772 | -0.001 |
| + yeni (hepsi) | 0.778 / 0.789 / 0.769 | 0.779 | +0.006 |

#### t0−10 — kesit (kazanç saat/seans özelliklerinden mi?)

| özellik kümesi | AUC B1 / B2 / B3 | ort. | Δ vs mevcut154 |
|---|---|---|---|
| mevcut 154 | 0.622 / 0.636 / 0.630 | 0.629 | +0.000 |
| + yeni (saat/seans-zaman özellikleri HARİÇ) | 0.635 / 0.655 / 0.637 | 0.642 | +0.013 |
| + yeni (gün/seans ailesi HARİÇ) | 0.634 / 0.651 / 0.638 | 0.641 | +0.011 |
| + yalnız saat/seans-zaman özellikleri | 0.624 / 0.641 / 0.628 | 0.631 | +0.001 |
| + yeni (hepsi) | 0.635 / 0.656 / 0.640 | 0.644 | +0.014 |


### C. Önceden belirlenmiş sinyaller

Net = exit_sim (60 sn gecikme, %0,15 kayma, %0,1125/bacak) ortalaması, % cinsinden. 'rastgele' = aynı sembollerde sinyal sayısı kadar, sinyalden ≥2 sa uzak rastgele giriş; 'koşulsuz' = tüm geçerli anlardan tekdüze örnek.

| sinyal | blok | n | sinyal/gün | 60 dk önden kesinlik | taban | hit60@1,5 | şans (null3) | lift pp ± SE | net TP1,5 | rastgele (≥2 sa uzak) | koşulsuz | net izleyen | rastg. | koşulsuz |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sqz_rel_up | B1 | 5788 | 199.6 | 2.4% | 0.9% | 18.8% | 17.1% | +2.3 ± 0.7 | -0.51 | -0.54 | -0.51 | -0.53 | -0.55 | -0.52 |
| sqz_rel_up | B2 | 7597 | 253.2 | 2.4% | 1.1% | 20.5% | 17.0% | +3.4 ± 1.1 | -0.50 | -0.52 | -0.49 | -0.53 | -0.53 | -0.50 |
| sqz_rel_up | B3 | 7810 | 258.2 | 2.8% | 1.3% | 21.1% | 17.3% | +3.5 ± 0.8 | -0.53 | -0.53 | -0.49 | -0.54 | -0.53 | -0.49 |
| wt_os53 | B1 | 23763 | 819.4 | 0.8% | 0.9% | 9.9% | 12.2% | -2.0 ± 0.5 | -0.47 | -0.25 | -0.51 | -0.48 | -0.27 | -0.52 |
| wt_os53 | B2 | 28501 | 950.0 | 0.9% | 1.1% | 13.4% | 14.2% | -0.9 ± 0.9 | -0.41 | -0.19 | -0.49 | -0.42 | -0.22 | -0.50 |
| wt_os53 | B3 | 31600 | 1044.6 | 1.0% | 1.3% | 13.6% | 15.0% | -1.6 ± 0.7 | -0.47 | -0.18 | -0.49 | -0.48 | -0.20 | -0.49 |
| qqe_mod | B1 | 41640 | 1435.9 | 0.9% | 0.9% | 11.3% | 12.6% | -1.6 ± 0.6 | -0.57 | -1.00 | -0.51 | -0.58 | -0.99 | -0.52 |
| qqe_mod | B2 | 52384 | 1746.1 | 1.1% | 1.1% | 13.6% | 13.5% | +0.3 ± 0.9 | -0.55 | -1.06 | -0.49 | -0.56 | -1.06 | -0.50 |
| qqe_mod | B3 | 56572 | 1870.1 | 1.2% | 1.3% | 14.6% | 13.7% | +0.9 ± 0.7 | -0.52 | -1.10 | -0.49 | -0.53 | -1.09 | -0.49 |
| wae_up | B1 | 60438 | 2084.1 | 0.9% | 0.9% | 11.3% | 11.4% | -0.7 ± 0.6 | -0.56 | -1.07 | -0.51 | -0.57 | -1.07 | -0.52 |
| wae_up | B2 | 75601 | 2520.0 | 1.1% | 1.1% | 13.6% | 12.4% | +1.0 ± 0.9 | -0.54 | -1.15 | -0.49 | -0.55 | -1.14 | -0.50 |
| wae_up | B3 | 81310 | 2687.9 | 1.2% | 1.3% | 14.3% | 12.8% | +1.0 ± 0.7 | -0.53 | -1.13 | -0.49 | -0.53 | -1.12 | -0.49 |
| utbot_buy | B1 | 74068 | 2554.1 | 0.8% | 0.9% | 10.8% | 11.0% | -0.8 ± 0.5 | -0.54 | -0.72 | -0.51 | -0.55 | -0.72 | -0.52 |
| utbot_buy | B2 | 91983 | 3066.1 | 1.0% | 1.1% | 13.6% | 12.1% | +1.5 ± 0.9 | -0.51 | -0.68 | -0.49 | -0.52 | -0.66 | -0.50 |
| utbot_buy | B3 | 101569 | 3357.7 | 1.2% | 1.3% | 13.6% | 12.6% | +1.4 ± 0.7 | -0.52 | -0.66 | -0.49 | -0.53 | -0.65 | -0.49 |
| ssl_flip_up | B1 | 63103 | 2176.0 | 0.8% | 0.9% | 10.3% | 10.3% | -0.1 ± 0.5 | -0.55 | -0.75 | -0.51 | -0.56 | -0.77 | -0.52 |
| ssl_flip_up | B2 | 78044 | 2601.5 | 0.9% | 1.1% | 12.7% | 11.3% | +2.2 ± 0.8 | -0.53 | -0.63 | -0.49 | -0.54 | -0.62 | -0.50 |
| ssl_flip_up | B3 | 85307 | 2820.1 | 1.1% | 1.3% | 13.1% | 11.8% | +0.8 ± 0.7 | -0.53 | -0.77 | -0.49 | -0.53 | -0.77 | -0.49 |
| rf_buy | B1 | 23536 | 811.6 | 1.2% | 0.9% | 14.0% | 15.9% | -2.4 ± 0.7 | -0.57 | -0.69 | -0.51 | -0.59 | -0.70 | -0.52 |
| rf_buy | B2 | 29954 | 998.5 | 1.3% | 1.1% | 16.4% | 17.3% | -1.3 ± 0.9 | -0.53 | -0.67 | -0.49 | -0.55 | -0.69 | -0.50 |
| rf_buy | B3 | 32253 | 1066.2 | 1.4% | 1.3% | 17.2% | 18.0% | -1.3 ± 0.8 | -0.56 | -0.66 | -0.49 | -0.56 | -0.67 | -0.49 |
| lrsi_up20 | B1 | 55488 | 1913.4 | 0.9% | 0.9% | 10.6% | 10.7% | -0.3 ± 0.5 | -0.52 | -0.22 | -0.51 | -0.53 | -0.26 | -0.52 |
| lrsi_up20 | B2 | 67983 | 2266.1 | 0.9% | 1.1% | 12.9% | 11.8% | +0.8 ± 0.8 | -0.51 | -0.05 | -0.49 | -0.52 | -0.09 | -0.50 |
| lrsi_up20 | B3 | 74667 | 2468.3 | 1.2% | 1.3% | 13.6% | 12.3% | +1.2 ± 0.7 | -0.52 | -0.09 | -0.49 | -0.52 | -0.10 | -0.49 |
| stc_up25 | B1 | 48043 | 1656.7 | 0.9% | 0.9% | 10.9% | 11.6% | -0.3 ± 0.5 | -0.54 | -0.68 | -0.51 | -0.55 | -0.68 | -0.52 |
| stc_up25 | B2 | 59570 | 1985.7 | 1.0% | 1.1% | 13.1% | 12.7% | +0.6 ± 0.7 | -0.54 | -0.64 | -0.49 | -0.55 | -0.65 | -0.50 |
| stc_up25 | B3 | 64106 | 2119.2 | 1.2% | 1.3% | 14.0% | 13.1% | +0.5 ± 0.7 | -0.53 | -0.63 | -0.49 | -0.53 | -0.62 | -0.49 |
| ce_flip_up | B1 | 62594 | 2158.4 | 0.7% | 0.9% | 10.0% | 11.5% | -1.7 ± 0.5 | -0.53 | -0.87 | -0.51 | -0.54 | -0.89 | -0.52 |
| ce_flip_up | B2 | 77967 | 2598.9 | 0.9% | 1.1% | 12.9% | 13.2% | +0.2 ± 0.8 | -0.50 | -0.78 | -0.49 | -0.52 | -0.80 | -0.50 |
| ce_flip_up | B3 | 84997 | 2809.8 | 1.0% | 1.3% | 13.0% | 13.0% | -0.4 ± 0.7 | -0.52 | -0.85 | -0.49 | -0.52 | -0.85 | -0.49 |
| ts_long | B1 | 14026 | 483.7 | 1.8% | 0.9% | 14.6% | 15.5% | -1.2 ± 0.6 | -0.49 | -0.37 | -0.51 | -0.50 | -0.39 | -0.52 |
| ts_long | B2 | 18679 | 622.6 | 1.7% | 1.1% | 17.1% | 16.8% | +0.9 ± 1.0 | -0.44 | -0.32 | -0.49 | -0.46 | -0.34 | -0.50 |
| ts_long | B3 | 21784 | 720.1 | 2.1% | 1.3% | 18.2% | 17.8% | +0.5 ± 0.9 | -0.46 | -0.31 | -0.49 | -0.47 | -0.31 | -0.49 |
| spring | B1 | 3650 | 125.9 | 1.8% | 0.9% | 15.0% | 17.7% | -3.1 ± 0.6 | -0.47 | -0.47 | -0.51 | -0.50 | -0.48 | -0.52 |
| spring | B2 | 5246 | 174.9 | 1.8% | 1.1% | 20.4% | 19.8% | +0.7 ± 1.3 | -0.36 | -0.44 | -0.49 | -0.38 | -0.45 | -0.50 |
| spring | B3 | 5926 | 195.9 | 2.1% | 1.3% | 18.5% | 20.7% | -2.2 ± 1.0 | -0.47 | -0.42 | -0.49 | -0.48 | -0.43 | -0.49 |
| dbot_break | B1 | 4989 | 172.0 | 1.2% | 0.9% | 14.7% | 14.7% | +0.1 ± 0.6 | -0.58 | -0.55 | -0.51 | -0.59 | -0.56 | -0.52 |
| dbot_break | B2 | 5663 | 188.8 | 1.4% | 1.1% | 15.1% | 15.0% | +0.7 ± 0.8 | -0.55 | -0.52 | -0.49 | -0.58 | -0.53 | -0.50 |
| dbot_break | B3 | 6116 | 202.2 | 1.4% | 1.3% | 15.6% | 15.0% | +1.0 ± 0.9 | -0.58 | -0.51 | -0.49 | -0.59 | -0.51 | -0.49 |
| ifvg_bull | B1 | 58505 | 2017.4 | 0.8% | 0.9% | 10.6% | 11.0% | -0.1 ± 0.5 | -0.55 | -0.81 | -0.51 | -0.56 | -0.82 | -0.52 |
| ifvg_bull | B2 | 76276 | 2542.5 | 1.0% | 1.1% | 13.0% | 12.0% | +0.8 ± 0.7 | -0.53 | -0.78 | -0.49 | -0.54 | -0.80 | -0.50 |
| ifvg_bull | B3 | 86028 | 2843.9 | 1.1% | 1.3% | 13.3% | 12.4% | +1.1 ± 0.6 | -0.53 | -0.89 | -0.49 | -0.53 | -0.89 | -0.49 |
| brk_bull | B1 | 8620 | 297.2 | 1.3% | 0.9% | 15.7% | 15.7% | +0.3 ± 0.8 | -0.50 | -0.55 | -0.51 | -0.52 | -0.56 | -0.52 |
| brk_bull | B2 | 10254 | 341.8 | 1.6% | 1.1% | 18.1% | 15.8% | +2.5 ± 1.0 | -0.47 | -0.53 | -0.49 | -0.49 | -0.53 | -0.50 |
| brk_bull | B3 | 10207 | 337.4 | 1.8% | 1.3% | 17.7% | 15.6% | +1.7 ± 0.8 | -0.48 | -0.52 | -0.49 | -0.49 | -0.53 | -0.49 |
| ote_tap | B1 | 26249 | 905.1 | 1.2% | 0.9% | 12.5% | 12.9% | -0.7 ± 0.6 | -0.49 | -0.46 | -0.51 | -0.50 | -0.47 | -0.52 |
| ote_tap | B2 | 32358 | 1078.6 | 1.3% | 1.1% | 14.8% | 13.4% | +1.9 ± 0.8 | -0.49 | -0.41 | -0.49 | -0.50 | -0.42 | -0.50 |
| ote_tap | B3 | 36633 | 1211.0 | 1.5% | 1.3% | 15.1% | 14.2% | +0.7 ± 0.7 | -0.49 | -0.41 | -0.49 | -0.50 | -0.41 | -0.49 |
| orb_utc | B1 | 4292 | 148.0 | 1.1% | 0.9% | 13.2% | 14.4% | -1.2 ± 0.6 | -0.58 | -0.53 | -0.51 | -0.60 | -0.54 | -0.52 |
| orb_utc | B2 | 5486 | 182.9 | 1.0% | 1.1% | 14.6% | 15.7% | -0.6 ± 1.1 | -0.57 | -0.53 | -0.49 | -0.60 | -0.55 | -0.50 |
| orb_utc | B3 | 5949 | 196.7 | 1.2% | 1.3% | 14.7% | 15.4% | -0.3 ± 0.8 | -0.66 | -0.53 | -0.49 | -0.67 | -0.54 | -0.49 |
| orb_tr | B1 | 4311 | 148.7 | 0.6% | 0.9% | 10.8% | 13.5% | -2.5 ± 0.7 | -0.62 | -0.52 | -0.51 | -0.64 | -0.54 | -0.52 |
| orb_tr | B2 | 5388 | 179.6 | 0.8% | 1.1% | 12.7% | 15.0% | -2.3 ± 0.9 | -0.65 | -0.52 | -0.49 | -0.67 | -0.53 | -0.50 |
| orb_tr | B3 | 6399 | 211.5 | 0.9% | 1.3% | 11.4% | 13.8% | -2.9 ± 0.8 | -0.51 | -0.55 | -0.49 | -0.51 | -0.54 | -0.49 |
| rvol_green | B1 | 33409 | 1152.0 | 1.3% | 0.9% | 15.3% | 15.4% | -0.3 ± 0.7 | -0.56 | -0.55 | -0.51 | -0.57 | -0.57 | -0.52 |
| rvol_green | B2 | 46080 | 1536.0 | 1.8% | 1.1% | 19.5% | 16.9% | +2.9 ± 1.0 | -0.51 | -0.56 | -0.49 | -0.52 | -0.58 | -0.50 |
| rvol_green | B3 | 51022 | 1686.7 | 1.9% | 1.3% | 19.7% | 17.4% | +2.3 ± 0.8 | -0.52 | -0.56 | -0.49 | -0.53 | -0.57 | -0.49 |
| vmc_green | B1 | 12087 | 416.8 | 0.9% | 0.9% | 10.3% | 12.9% | -2.6 ± 0.5 | -0.49 | -0.39 | -0.51 | -0.50 | -0.42 | -0.52 |
| vmc_green | B2 | 14694 | 489.8 | 0.9% | 1.1% | 13.2% | 14.5% | -1.9 ± 0.8 | -0.45 | -0.35 | -0.49 | -0.46 | -0.37 | -0.50 |
| vmc_green | B3 | 17121 | 566.0 | 1.2% | 1.3% | 14.3% | 15.6% | -1.6 ± 1.0 | -0.47 | -0.34 | -0.49 | -0.49 | -0.34 | -0.49 |
| HA | B1 | 5934 | 204.6 | 6.6% | 0.9% | 48.6% | 44.9% | +3.9 ± 1.0 | -0.54 | -0.57 | -0.51 | -0.54 | -0.59 | -0.52 |
| HA | B2 | 6766 | 225.5 | 6.6% | 1.1% | 47.0% | 42.1% | +4.5 ± 1.1 | -0.50 | -0.52 | -0.49 | -0.55 | -0.55 | -0.50 |
| HA | B3 | 7643 | 252.7 | 6.7% | 1.3% | 47.8% | 42.2% | +5.7 ± 1.1 | -0.56 | -0.54 | -0.49 | -0.54 | -0.56 | -0.49 |


Olay yakalama ve Hız Avcısı'na (HA) göre öncelik:

| sinyal | blok | olay | t0 öncesi yakalama | sayı-eşleşmiş sıfır | t0 sonrası dâhil | HA t0 öncesi | ort. öncelik (dk, medyan) | ortak olay | HA'dan önce gelme payı | medyan fark dk |
|---|---|---|---|---|---|---|---|---|---|---|
| sqz_rel_up | B1 | 1095 | 11.9% | 6.9% | 26.7% | 39.2% | 35 | 312 | 42.3% | -5 |
| sqz_rel_up | B2 | 1583 | 10.7% | 5.2% | 26.9% | 30.6% | 35 | 413 | 49.2% | +0 |
| sqz_rel_up | B3 | 1874 | 10.7% | 4.4% | 24.5% | 30.6% | 35 | 405 | 47.4% | +0 |
| wt_os53 | B1 | 1095 | 16.5% | 17.9% | 26.0% | 39.2% | 35 | 231 | 69.3% | +25 |
| wt_os53 | B2 | 1583 | 15.5% | 18.9% | 23.2% | 30.6% | 35 | 278 | 73.0% | +25 |
| wt_os53 | B3 | 1874 | 15.2% | 18.9% | 23.7% | 30.6% | 30 | 334 | 74.9% | +30 |
| qqe_mod | B1 | 1095 | 34.3% | 31.1% | 83.7% | 39.2% | 35 | 857 | 50.4% | +5 |
| qqe_mod | B2 | 1583 | 34.5% | 29.7% | 86.5% | 30.6% | 35 | 1154 | 56.2% | +5 |
| qqe_mod | B3 | 1874 | 33.5% | 27.7% | 87.7% | 30.6% | 35 | 1348 | 54.3% | +5 |
| wae_up | B1 | 1095 | 48.5% | 42.8% | 94.2% | 39.2% | 35 | 927 | 59.0% | +10 |
| wae_up | B2 | 1583 | 49.5% | 37.3% | 96.5% | 30.6% | 35 | 1250 | 65.7% | +15 |
| wae_up | B3 | 1874 | 49.8% | 42.3% | 95.4% | 30.6% | 35 | 1445 | 65.5% | +15 |
| utbot_buy | B1 | 1095 | 54.8% | 48.3% | 94.9% | 39.2% | 35 | 926 | 61.0% | +10 |
| utbot_buy | B2 | 1583 | 56.2% | 44.9% | 94.3% | 30.6% | 35 | 1232 | 67.1% | +20 |
| utbot_buy | B3 | 1874 | 58.4% | 46.9% | 94.8% | 30.6% | 35 | 1454 | 67.0% | +20 |
| ssl_flip_up | B1 | 1095 | 46.2% | 42.5% | 86.0% | 39.2% | 35 | 830 | 61.3% | +10 |
| ssl_flip_up | B2 | 1583 | 42.9% | 39.2% | 83.8% | 30.6% | 35 | 1080 | 66.5% | +15 |
| ssl_flip_up | B3 | 1874 | 46.3% | 39.8% | 86.4% | 30.6% | 35 | 1319 | 65.1% | +15 |
| rf_buy | B1 | 1095 | 23.8% | 17.4% | 69.9% | 39.2% | 35 | 721 | 47.9% | +0 |
| rf_buy | B2 | 1583 | 23.4% | 16.9% | 69.1% | 30.6% | 35 | 944 | 51.3% | +5 |
| rf_buy | B3 | 1874 | 23.5% | 16.9% | 70.9% | 30.6% | 30 | 1125 | 50.8% | +5 |
| lrsi_up20 | B1 | 1095 | 41.9% | 38.3% | 73.1% | 39.2% | 35 | 710 | 63.2% | +15 |
| lrsi_up20 | B2 | 1583 | 38.0% | 36.1% | 67.7% | 30.6% | 35 | 897 | 65.3% | +15 |
| lrsi_up20 | B3 | 1874 | 43.5% | 36.8% | 72.1% | 30.6% | 35 | 1103 | 65.7% | +20 |
| stc_up25 | B1 | 1095 | 37.7% | 33.1% | 78.4% | 39.2% | 35 | 780 | 56.9% | +5 |
| stc_up25 | B2 | 1583 | 36.8% | 31.3% | 78.6% | 30.6% | 35 | 1050 | 60.5% | +10 |
| stc_up25 | B3 | 1874 | 38.5% | 33.4% | 80.3% | 30.6% | 35 | 1240 | 61.3% | +10 |
| ce_flip_up | B1 | 1095 | 35.5% | 38.0% | 78.1% | 39.2% | 35 | 823 | 53.1% | +5 |
| ce_flip_up | B2 | 1583 | 39.9% | 39.2% | 76.4% | 30.6% | 35 | 1071 | 57.0% | +10 |
| ce_flip_up | B3 | 1874 | 40.9% | 39.7% | 79.8% | 30.6% | 30 | 1288 | 58.7% | +10 |
| ts_long | B1 | 1095 | 20.2% | 13.8% | 25.3% | 39.2% | 30 | 274 | 60.9% | +20 |
| ts_long | B2 | 1583 | 17.7% | 14.2% | 23.1% | 30.6% | 35 | 320 | 62.2% | +20 |
| ts_long | B3 | 1874 | 20.4% | 11.7% | 26.3% | 30.6% | 30 | 445 | 60.9% | +20 |
| spring | B1 | 1095 | 5.0% | 4.3% | 7.1% | 39.2% | 35 | 78 | 62.8% | +25 |
| spring | B2 | 1583 | 5.3% | 4.0% | 7.3% | 30.6% | 30 | 97 | 58.8% | +25 |
| spring | B3 | 1874 | 5.6% | 4.2% | 7.1% | 30.6% | 30 | 103 | 60.2% | +20 |
| dbot_break | B1 | 1095 | 5.1% | 4.1% | 16.1% | 39.2% | 32 | 172 | 57.0% | +5 |
| dbot_break | B2 | 1583 | 4.9% | 4.1% | 12.7% | 30.6% | 30 | 197 | 56.9% | +5 |
| dbot_break | B3 | 1874 | 4.1% | 3.2% | 12.8% | 30.6% | 35 | 211 | 51.2% | +5 |
| ifvg_bull | B1 | 1095 | 42.3% | 37.8% | 81.1% | 39.2% | 35 | 796 | 61.6% | +15 |
| ifvg_bull | B2 | 1583 | 43.6% | 39.5% | 83.2% | 30.6% | 35 | 1081 | 67.0% | +15 |
| ifvg_bull | B3 | 1874 | 45.1% | 41.0% | 84.6% | 30.6% | 30 | 1288 | 65.6% | +15 |
| brk_bull | B1 | 1095 | 9.6% | 6.4% | 15.9% | 39.2% | 30 | 250 | 35.2% | -10 |
| brk_bull | B2 | 1583 | 9.2% | 6.1% | 15.9% | 30.6% | 30 | 290 | 34.5% | -10 |
| brk_bull | B3 | 1874 | 8.8% | 6.1% | 14.4% | 30.6% | 30 | 339 | 37.2% | -10 |
| ote_tap | B1 | 1095 | 25.5% | 20.6% | 34.6% | 39.2% | 35 | 447 | 49.2% | +0 |
| ote_tap | B2 | 1583 | 22.4% | 20.0% | 29.8% | 30.6% | 30 | 497 | 53.9% | +15 |
| ote_tap | B3 | 1874 | 25.1% | 20.1% | 33.1% | 30.6% | 35 | 687 | 51.2% | +5 |
| orb_utc | B1 | 1095 | 4.0% | 2.5% | 14.6% | 39.2% | 35 | 164 | 43.9% | +0 |
| orb_utc | B2 | 1583 | 3.5% | 3.1% | 16.0% | 30.6% | 32 | 216 | 56.5% | +5 |
| orb_utc | B3 | 1874 | 3.7% | 4.2% | 14.9% | 30.6% | 35 | 237 | 54.4% | +5 |
| orb_tr | B1 | 1095 | 2.3% | 3.5% | 11.0% | 39.2% | 35 | 127 | 44.9% | +0 |
| orb_tr | B2 | 1583 | 2.3% | 3.5% | 11.1% | 30.6% | 35 | 160 | 51.9% | +5 |
| orb_tr | B3 | 1874 | 2.9% | 3.2% | 10.1% | 30.6% | 25 | 167 | 53.3% | +5 |
| rvol_green | B1 | 1095 | 39.3% | 20.3% | 72.3% | 39.2% | 35 | 754 | 52.9% | +5 |
| rvol_green | B2 | 1583 | 50.2% | 26.8% | 87.3% | 30.6% | 35 | 1170 | 63.6% | +10 |
| rvol_green | B3 | 1874 | 50.4% | 25.5% | 89.8% | 30.6% | 35 | 1413 | 63.6% | +10 |
| vmc_green | B1 | 1095 | 9.6% | 8.9% | 16.4% | 39.2% | 40 | 142 | 67.6% | +20 |
| vmc_green | B2 | 1583 | 8.2% | 11.0% | 13.0% | 30.6% | 35 | 155 | 70.3% | +30 |
| vmc_green | B3 | 1874 | 9.4% | 9.9% | 15.7% | 30.6% | 35 | 219 | 73.1% | +20 |
| HA | B1 | 1095 | 32.7% | 6.9% | 74.6% | 39.2% | 30 | 952 | 0.0% | +0 |
| HA | B2 | 1583 | 26.2% | 6.2% | 69.9% | 30.6% | 35 | 1275 | 0.0% | +0 |
| HA | B3 | 1874 | 25.7% | 6.7% | 68.1% | 30.6% | 30 | 1485 | 0.0% | +0 |


Özet:

| sinyal | tanım | net>0 (TP1,5) blok | net>0 (izleyen) blok | net TP1,5 B1 / B2 / B3 | hit lift pp B1 / B2 / B3 | erken-uyarı ölçütü (t0 öncesi yakalama > sıfır x1,5 VE HA'dan önce > %50) |
|---|---|---|---|---|---|---|
| sqz_rel_up | Squeeze Momentum (LazyBear) yukarı salım | 0/3 | 0/3 | -0.51 / -0.50 / -0.53 | +2.3 / +3.4 / +3.5 | 0/3 |
| wt_os53 | WaveTrend WT1>WT2 kesişimi, WT2 <= -53 | 0/3 | 0/3 | -0.47 / -0.41 / -0.47 | -2.0 / -0.9 / -1.6 | 0/3 |
| qqe_mod | QQE MOD mavi çubuk başlangıcı | 0/3 | 0/3 | -0.57 / -0.55 / -0.52 | -1.6 / +0.3 / +0.9 | 0/3 |
| wae_up | Waddah Attar patlama yukarı başlangıcı | 0/3 | 0/3 | -0.56 / -0.54 / -0.53 | -0.7 / +1.0 / +1.0 | 0/3 |
| utbot_buy | UT Bot AL (a=1, ATR10) | 0/3 | 0/3 | -0.54 / -0.51 / -0.52 | -0.8 / +1.5 / +1.4 | 0/3 |
| ssl_flip_up | SSL kanalı yukarı dönüş (SMA10) | 0/3 | 0/3 | -0.55 / -0.53 / -0.53 | -0.1 / +2.2 / +0.8 | 0/3 |
| rf_buy | Range Filter AL (100, 3) | 0/3 | 0/3 | -0.57 / -0.53 / -0.56 | -2.4 / -1.3 / -1.3 | 0/3 |
| lrsi_up20 | Laguerre RSI 0,2 yukarı kesişim | 0/3 | 0/3 | -0.52 / -0.51 / -0.52 | -0.3 / +0.8 / +1.2 | 0/3 |
| stc_up25 | Schaff Trend Cycle 25 yukarı kesişim | 0/3 | 0/3 | -0.54 / -0.54 / -0.53 | -0.3 / +0.6 / +0.5 | 0/3 |
| ce_flip_up | Chandelier Exit yön -> long | 0/3 | 0/3 | -0.53 / -0.50 / -0.52 | -1.7 / +0.2 / -0.4 | 0/3 |
| ts_long | Turtle Soup long (20 bar alçak süpürme + geri kapanış) | 0/3 | 0/3 | -0.49 / -0.44 / -0.46 | -1.2 / +0.9 / +0.5 | 1/3 |
| spring | Wyckoff spring (dar aralık alçak süpürme + hacimli geri alma) | 0/3 | 0/3 | -0.47 / -0.36 / -0.47 | -3.1 / +0.7 / -2.2 | 0/3 |
| dbot_break | Çift dip yaka çizgisi kırılımı | 0/3 | 0/3 | -0.58 / -0.55 / -0.58 | +0.1 / +0.7 / +1.0 | 0/3 |
| ifvg_bull | Inversion FVG (yükseliş) oluştu | 0/3 | 0/3 | -0.55 / -0.53 / -0.53 | -0.1 / +0.8 / +1.1 | 0/3 |
| brk_bull | Yükseliş Breaker Block teması | 0/3 | 0/3 | -0.50 / -0.47 / -0.48 | +0.3 / +2.5 / +1.7 | 0/3 |
| ote_tap | OTE bölgesine (62-79%) ilk giriş (yükseliş bacağı) | 0/3 | 0/3 | -0.49 / -0.49 / -0.49 | -0.7 / +1.9 / +0.7 | 0/3 |
| orb_utc | ORB 30 dk yukarı kırılım (UTC günü) | 0/3 | 0/3 | -0.58 / -0.57 / -0.66 | -1.2 / -0.6 / -0.3 | 0/3 |
| orb_tr | ORB 30 dk yukarı kırılım (TR günü) | 0/3 | 0/3 | -0.62 / -0.65 / -0.51 | -2.5 / -2.3 / -2.9 | 0/3 |
| rvol_green | RVOL(günün saati) > 3 ve yeşil mum | 0/3 | 0/3 | -0.56 / -0.51 / -0.52 | -0.3 / +2.9 / +2.3 | 3/3 |
| vmc_green | Cipher B yeşil nokta (WT dip kesişimi + para akışı yukarı) | 0/3 | 0/3 | -0.49 / -0.45 / -0.47 | -2.6 / -1.9 / -1.6 | 0/3 |
| HA | Hız Avcısı | 0/3 | 0/3 | -0.54 / -0.50 / -0.56 | +3.9 / +4.5 / +5.7 | 0/3 |


LUNATRY 17.10 01:00–05:00 (TR) 5m sinyal anları (cooldown öncesi ilk 8):

| sinyal | tetik saatleri |
|---|---|
| sqz_rel_up | – |
| wt_os53 | – |
| qqe_mod | – |
| wae_up | 00:10, 01:05 |
| utbot_buy | 00:10, 01:05, 03:00 |
| ssl_flip_up | 03:00 |
| rf_buy | 02:50 |
| lrsi_up20 | 03:00 |
| stc_up25 | 03:30 |
| ce_flip_up | 02:10, 02:20, 02:30, 02:40, 02:50, 03:00, 03:10, 03:20 |
| ts_long | – |
| spring | – |
| dbot_break | – |
| ifvg_bull | 00:15, 00:35, 01:05 |
| brk_bull | – |
| ote_tap | 02:40 |
| orb_utc | – |
| orb_tr | 00:35 |
| rvol_green | 01:10, 01:15, 01:20, 01:25, 01:35, 01:40, 01:45, 01:50 |
| vmc_green | – |


### D. HA süzgeci

HA olayı 20343, geçerli 20343, yeni özellik 664.

| sonuç | özellik | q<0,05 | q<0,01 |
|---|---|---|---|
| net (ham) | 664 | 188 | 144 |
| net (ATR-kontrollü) | 664 | 162 | 117 |
| net−taban (ATR-kontrollü) | 664 | 193 | 106 |
| hit (ATR-kontrollü) | 664 | 418 | 356 |
| hit−taban (ATR-kontrollü) | 664 | 420 | 356 |


En güçlü 15 yeni özellik (ATR-kontrollü net−taban |t|):

| özellik | aile | kapsam | ATR-kont. r(net−taban) [t] | q | ATR-kont. r(net) [t] | ATR-kont. r(hit) [t] | blok r(net−taban) | işaret uyumu |
|---|---|---|---|---|---|---|---|---|
| 5m.tl_res_dist | pivot (Fib/trend/dip) | 43% | -0.068 [-5.7] | 0.000 | -0.076 [-6.7] | +0.029 [+2.9] | -0.077 / -0.092 / -0.041 | 3/3 |
| 5m.rvol_tod | temel | 97% | -0.047 [-5.7] | 0.000 | -0.026 [-3.2] | +0.038 [+5.3] | -0.035 / -0.048 / -0.052 | 3/3 |
| 5m.rvol_tod_log | temel | 97% | -0.047 [-5.7] | 0.000 | -0.026 [-3.2] | +0.038 [+5.3] | -0.035 / -0.048 / -0.052 | 3/3 |
| 5m.lrc_pos | temel | 100% | -0.042 [-5.5] | 0.000 | -0.044 [-5.6] | +0.062 [+9.2] | -0.046 / -0.041 / -0.042 | 3/3 |
| 5m.medch_pos | temel | 100% | -0.042 [-5.4] | 0.000 | -0.048 [-6.0] | +0.086 [+12.2] | -0.040 / -0.039 / -0.046 | 3/3 |
| 5m.starc_pos | ileri | 100% | -0.033 [-5.1] | 0.000 | -0.040 [-5.7] | +0.063 [+10.4] | -0.039 / -0.022 / -0.040 | 3/3 |
| 5m.rvol_tod_max3 | temel | 100% | -0.044 [-5.0] | 0.000 | -0.020 [-2.4] | +0.029 [+3.3] | -0.039 / -0.048 / -0.035 | 3/3 |
| 5m.ribbon_px | temel | 100% | -0.043 [-5.0] | 0.000 | -0.049 [-5.8] | +0.081 [+10.7] | -0.037 / -0.045 / -0.045 | 3/3 |
| 5m.pgo14 | ileri | 100% | -0.038 [-5.0] | 0.000 | -0.047 [-5.8] | +0.080 [+11.6] | -0.037 / -0.035 / -0.042 | 3/3 |
| 5m.coral_dist | topluluk | 100% | -0.043 [-5.0] | 0.000 | -0.052 [-5.9] | +0.083 [+10.8] | -0.034 / -0.051 / -0.046 | 3/3 |
| 5m.ha_body_atr | topluluk | 100% | -0.032 [-4.9] | 0.000 | -0.038 [-5.7] | +0.062 [+9.3] | -0.044 / -0.018 / -0.036 | 3/3 |
| 5m.pvi_slope12 | temel | 100% | -0.040 [-4.8] | 0.000 | -0.049 [-5.9] | +0.065 [+9.7] | -0.026 / -0.052 / -0.043 | 3/3 |
| 5m.bull_power | temel | 100% | -0.041 [-4.8] | 0.000 | -0.047 [-5.7] | +0.094 [+12.9] | -0.028 / -0.047 / -0.049 | 3/3 |
| 15m.rvol_tod_max3 | temel | 100% | -0.040 [-4.7] | 0.000 | -0.015 [-1.9] | +0.014 [+1.7] | -0.033 / -0.046 / -0.030 | 3/3 |
| 5m.pdl_sweep_r12_utc | gün/seans | 100% | +0.031 [+4.7] | 0.000 | +0.027 [+4.0] | -0.000 [-0.0] | +0.011 / +0.037 / +0.044 | 3/3 |

q<0,05 ve 3/3 blokta aynı işaret: **180** özellik; en güçlüleri: 5m.tl_res_dist (r -0.068); 5m.rvol_tod (r -0.047); 5m.rvol_tod_log (r -0.047); 5m.lrc_pos (r -0.042); 5m.medch_pos (r -0.042); 5m.starc_pos (r -0.033); 5m.rvol_tod_max3 (r -0.044); 5m.ribbon_px (r -0.043)


Önceden belirlenmiş sinyal bayrakları HA süzgeci olarak (tutulan = bayrak 1; Δ = tutulan − hepsi, aynı blok; %):

| bayrak | tutulan pay | n B1 / B2 / B3 | Δ(net−taban) B1 / B2 / B3 | Δ(net) B1 / B2 / B3 |
|---|---|---|---|---|
| 15m.ce_flip_up_r3 | 23.2% | 1362 / 1613 / 1737 | -0.00 / -0.07 / -0.05 | +0.03 / -0.03 / -0.03 |
| 15m.dbot_break_r12 | 8.0% | 475 / 572 / 577 | -0.11 / -0.01 / -0.05 | -0.04 / +0.05 / -0.08 |
| 15m.lrsi_cross_up20_r3 | 15.7% | 934 / 1012 / 1239 | +0.02 / +0.08 / -0.04 | +0.04 / +0.02 / -0.00 |
| 15m.qqe_blue_on_r3 | 15.6% | 993 / 1065 / 1125 | -0.10 / -0.07 / -0.01 | -0.03 / -0.06 / +0.03 |
| 15m.rf_buy_r6 | 27.3% | 1641 / 1842 / 2062 | +0.01 / -0.06 / -0.11 | +0.01 / -0.03 / -0.12 |
| 15m.spring_r12 | 3.7% | 182 / 289 / 280 | -0.08 / +0.15 / +0.40 | -0.08 / +0.01 / +0.36 |
| 15m.sqzm_rel_up_r3 | 5.1% | 310 / 357 / 378 | +0.10 / -0.08 / -0.04 | +0.15 / -0.05 / -0.03 |
| 15m.ssl_flip_up_r3 | 19.0% | 1180 / 1234 / 1461 | -0.14 / -0.07 / -0.03 | -0.06 / -0.11 / +0.02 |
| 15m.stc_cross_up25_r3 | 14.3% | 878 / 954 / 1086 | +0.04 / -0.07 / -0.03 | +0.08 / -0.05 / -0.01 |
| 15m.ts20_long_r6 | 10.5% | 603 / 691 / 833 | +0.11 / +0.22 / +0.04 | +0.02 / +0.11 / +0.04 |
| 15m.utb_buy_r6 | 52.0% | 3183 / 3508 / 3879 | -0.01 / -0.00 / -0.07 | +0.02 / -0.01 / -0.05 |
| 15m.wt_cross_up_os53_r3 | 3.0% | 202 / 190 / 219 | -0.14 / -0.15 / -0.06 | -0.15 / -0.19 / -0.02 |
| 5m.brk_bull_tap | 4.2% | 341 / 261 / 253 | -0.10 / +0.12 / +0.04 | -0.02 / +0.05 / +0.04 |
| 5m.ce_flip_up | 9.6% | 538 / 650 / 773 | -0.00 / -0.04 / -0.16 | -0.02 / -0.08 / -0.04 |
| 5m.ce_flip_up_r3 | 30.3% | 1725 / 2132 / 2308 | -0.07 / +0.02 / -0.08 | -0.00 / +0.00 / -0.01 |
| 5m.dbot_break | 1.3% | 106 / 75 / 81 | -0.22 / -0.48 / +0.19 | -0.23 / -0.37 / +0.29 |
| 5m.dbot_break_r12 | 8.2% | 586 / 551 / 536 | +0.03 / -0.17 / -0.07 | +0.09 / -0.15 / -0.04 |
| 5m.ifvg_bull_new | 11.8% | 656 / 758 / 984 | +0.11 / -0.04 / -0.10 | +0.05 / -0.09 / -0.02 |
| 5m.lrsi_cross_up20 | 7.1% | 416 / 458 / 568 | +0.15 / -0.11 / +0.11 | -0.06 / -0.09 / +0.06 |
| 5m.lrsi_cross_up20_r3 | 24.2% | 1432 / 1624 / 1869 | -0.00 / +0.03 / +0.07 | -0.04 / +0.00 / +0.07 |
| 5m.orb30_tr_up_first | 0.8% | 42 / 59 / 61 | -0.15 / -0.27 / -0.34 | -0.12 / -0.35 / -0.32 |
| 5m.orb30_utc_up_first | 0.8% | 50 / 53 / 52 | +0.16 / -0.23 / -0.70 | +0.32 / -0.39 / -0.56 |
| 5m.ote_long_tap | 1.6% | 92 / 91 / 133 | +0.08 / +0.24 / +0.09 | +0.02 / +0.14 / +0.03 |
| 5m.qqe_blue_on | 8.5% | 495 / 595 / 633 | -0.21 / -0.05 / -0.02 | -0.17 / -0.03 / +0.05 |
| 5m.qqe_blue_on_r3 | 25.3% | 1514 / 1789 / 1851 | -0.09 / -0.06 / +0.09 | +0.00 / -0.04 / +0.14 |
| 5m.rf_buy | 8.0% | 422 / 555 / 660 | +0.03 / +0.04 / -0.04 | +0.04 / +0.11 / -0.01 |
| 5m.rf_buy_r6 | 34.2% | 2019 / 2336 / 2599 | -0.09 / -0.02 / -0.03 | -0.03 / +0.01 / +0.00 |
| 5m.rvol_tod_green3 | 35.7% | 1793 / 2462 / 2999 | -0.04 / +0.02 / -0.07 | -0.05 / +0.05 / -0.05 |
| 5m.spring | 0.5% | 27 / 41 / 38 | -0.27 / +0.03 / -0.34 | -0.32 / -0.00 / -0.19 |
| 5m.spring_r12 | 4.0% | 190 / 293 / 331 | -0.15 / +0.18 / +0.02 | -0.17 / +0.14 / -0.03 |
| 5m.sqzm_rel_up | 1.9% | 115 / 152 / 126 | +0.37 / +0.14 / +0.08 | +0.31 / +0.24 / +0.14 |
| 5m.sqzm_rel_up_r3 | 5.6% | 340 / 413 / 392 | +0.08 / +0.07 / -0.02 | +0.15 / +0.07 / -0.01 |
| 5m.ssl_flip_up | 9.6% | 604 / 609 / 749 | +0.03 / +0.13 / -0.01 | -0.07 / +0.10 / +0.01 |
| 5m.ssl_flip_up_r3 | 32.5% | 1980 / 2197 / 2444 | -0.02 / +0.06 / -0.03 | -0.02 / +0.02 / +0.01 |
| 5m.stc_cross_up25 | 7.5% | 442 / 498 / 584 | -0.07 / +0.24 / -0.02 | -0.14 / +0.22 / +0.02 |
| 5m.stc_cross_up25_r3 | 24.0% | 1458 / 1651 / 1772 | -0.08 / +0.10 / +0.07 | -0.04 / +0.06 / +0.10 |
| 5m.ts20_long | 1.7% | 101 / 117 / 126 | -0.17 / +0.23 / +0.30 | -0.13 / +0.11 / +0.29 |
| 5m.ts20_long_r6 | 10.6% | 610 / 697 / 845 | -0.05 / -0.02 / +0.11 | -0.09 / -0.08 / +0.08 |
| 5m.utb_buy | 11.4% | 750 / 683 / 877 | -0.05 / +0.02 / +0.22 | -0.13 / -0.01 / +0.18 |
| 5m.utb_buy_r6 | 63.4% | 3906 / 4253 / 4737 | -0.04 / +0.01 / +0.01 | -0.01 / -0.01 / +0.04 |
| 5m.vmc_green_mf | 0.6% | 39 / 29 / 53 | -0.33 / +0.49 / +0.03 | -0.26 / +0.28 / +0.08 |
| 5m.wae_expl_up_on | 12.1% | 756 / 769 / 941 | -0.03 / +0.09 / +0.03 | -0.09 / +0.04 / +0.03 |
| 5m.wt_cross_up_os53 | 1.0% | 59 / 62 / 81 | -0.03 / +0.31 / +0.04 | +0.02 / +0.22 / +0.01 |
| 5m.wt_cross_up_os53_r3 | 5.4% | 332 / 333 / 432 | +0.22 / +0.03 / +0.14 | +0.08 / -0.12 / +0.09 |


Kural arama — B1'de seçildi (hedef A: net−taban, N: ham net), B2/B3 DOKUNULMADAN:

| kural | koşul | seçim t | n B1 / B2 / B3 | net tutulan | net hepsi | Δ net | Δ(net−taban) |
|---|---|---|---|---|---|---|---|
| A1 | `5m.sk > 52.69` | 3.0 (n 2037) | 2037 / 2366 / 2759 | -0.43 / -0.53 / -0.67 | -0.54 / -0.51 / -0.62 | +0.11 / -0.02 / -0.04 | +0.29 / -0.06 / +0.05 |
| A2 | `15m.ribbon_width > 2.406` | 2.8 (n 2037) | 2037 / 2100 / 2500 | -0.45 / -0.55 / -0.60 | -0.54 / -0.51 / -0.62 | +0.09 / -0.04 / +0.02 | +0.29 / -0.07 / +0.13 |
| A3 | `15m.utad_r12 > 1e-09` | 2.6 (n 1694) | 1694 / 2060 / 2253 | -0.42 / -0.54 / -0.62 | -0.54 / -0.51 / -0.62 | +0.12 / -0.03 / -0.00 | +0.17 / -0.05 / +0.02 |
| A4 | `15m.ce_dist > 2.334` | 2.6 (n 2034) | 2034 / 2437 / 2658 | -0.47 / -0.45 / -0.64 | -0.54 / -0.51 / -0.62 | +0.07 / +0.06 / -0.02 | +0.17 / +0.07 / +0.06 |
| A5 | `15m.bbtrend > 1.973` | 2.5 (n 2037) | 2037 / 2397 / 2726 | -0.41 / -0.47 / -0.63 | -0.54 / -0.51 / -0.62 | +0.13 / +0.04 / -0.01 | +0.23 / +0.07 / +0.01 |
| N1 | `5m.t3_dist <= 0.6022` | 2.5 (n 2037) | 2037 / 2027 / 2048 | -0.40 / -0.52 / -0.62 | -0.54 / -0.51 / -0.62 | +0.14 / -0.00 / +0.00 | +0.15 / -0.03 / +0.01 |
| N2 | `15m.vmc_mf > 7.269` | 2.5 (n 2037) | 2037 / 2581 / 2740 | -0.37 / -0.46 / -0.65 | -0.54 / -0.51 / -0.62 | +0.17 / +0.06 / -0.03 | +0.17 / +0.03 / +0.00 |
| N3 | `15m.tl_sup_dist <= 4.284` | 2.3 (n 2467) | 2467 / 2810 / 3039 | -0.44 / -0.45 / -0.61 | -0.54 / -0.51 / -0.62 | +0.10 / +0.06 / +0.01 | +0.05 / +0.07 / -0.03 |
| N4 | `15m.psy12 > 58.33` | 2.3 (n 1247) | 1247 / 1704 / 1764 | -0.35 / -0.43 / -0.58 | -0.54 / -0.51 / -0.62 | +0.20 / +0.08 / +0.04 | +0.20 / +0.07 / +0.08 |
| N5 | `5m.osma_chg <= 0.04827` | 2.2 (n 3055) | 3055 / 3294 / 3409 | -0.44 / -0.53 / -0.61 | -0.54 / -0.51 / -0.62 | +0.10 / -0.01 / +0.02 | +0.08 / -0.04 / -0.00 |


Aşırı uyum tanısı (B1'de en iyi 50 aday kuralın seçim-dışı ortalama Δ'sı):

| hedef | aday | OOS en iyi-50 ort. Δ | pozitif pay | tüm adaylar ort. Δ | pozitif pay |
|---|---|---|---|---|---|
| net−taban | 2149 | +0.02 | 76.0% | +0.00 | 50.4% |
| ham net | 2149 | +0.00 | 50.0% | -0.00 | 50.2% |


B1'de en yüksek skorlu 300 aday kuraldan (her blokta n≥30): **tüm üç blokta** HA net'ini (hepsine göre) artıran 98; üç blokta mutlak net>0 olan 0. (Bağımsız yazı-tura beklentisi ≈ 12%.)

| kural | n | net B1 / B2 / B3 | Δ net B1 / B2 / B3 |
|---|---|---|---|
| `5m.tl_res_dist <= 1.959` | 1264 / 1498 / 1655 | -0.42 / -0.40 / -0.51 | +0.12 / +0.12 / +0.11 |
| `5m.tl_res_dist <= 3.188` | 1685 / 1995 / 2190 | -0.47 / -0.45 / -0.56 | +0.07 / +0.06 / +0.06 |
| `5m.cisd_dn_r6 > 1e-09` | 1113 / 1267 / 1512 | -0.44 / -0.46 / -0.51 | +0.10 / +0.05 / +0.11 |
| `5m.medch_pos <= 0.35` | 2039 / 2120 / 2379 | -0.47 / -0.47 / -0.55 | +0.07 / +0.05 / +0.07 |
| `15m.aroon_osc_chg5 <= -4` | 2099 / 2376 / 2754 | -0.48 / -0.47 / -0.56 | +0.06 / +0.04 / +0.06 |
| `15m.psy12 > 58.33` | 1247 / 1704 / 1764 | -0.35 / -0.43 / -0.58 | +0.20 / +0.08 / +0.04 |
| `5m.coral_dist <= 0.833` | 2037 / 2156 / 2397 | -0.48 / -0.48 / -0.56 | +0.06 / +0.04 / +0.06 |
| `5m.pvi_slope12 <= 1.43` | 3055 / 3450 / 3619 | -0.49 / -0.48 / -0.53 | +0.05 / +0.04 / +0.10 |
| `5m.tl_sup_dist <= 2.954` | 2409 / 2801 / 2907 | -0.48 / -0.46 / -0.58 | +0.06 / +0.05 / +0.04 |
| `5m.coral_dist <= 1.521` | 3055 / 3284 / 3545 | -0.46 / -0.48 / -0.53 | +0.08 / +0.04 / +0.10 |
