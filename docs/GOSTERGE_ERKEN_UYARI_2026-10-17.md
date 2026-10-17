# Erken Uyarı Çalışması — TradingView rehberindeki göstergeler (klasik + smart money) LUNA tipi yükselişten ÖNCE ayırt edici mi? (2026-10-17)

**Soru:** Rehberdeki ~100 klasik + ~20 smart-money göstergesiyle (a) analizin duyarlılığı/hedefi iyileşir mi, (b) Hız Avcısı'ndan (HA) **daha erken** ya da **daha iyi** bir erken-uyarı öncüsü kurulabilir mi, (c) herhangi biri maliyet sonrası net-pozitif olur mu? Ham çıktılar `backend/work/indearly/`, kütüphane `app/rescan/indicators_ext.py`.

## 0. Kısa cevap

**Karar: HAYIR.** Rehberdeki göstergelerle (a) HA'dan **daha erken** kullanılabilir bir öncü kurulamadı (rehber fikirlerinden yalnız `chop_drop` zayıf bir erken-kapsama eğilimi gösteriyor ama kesinlik ×1,5, net = rastgele), (b) hiçbir sinyal örneklem dışında net-pozitif olmadı, (c) analizin duyarlılığına katkı küçük (çok değişkenli modelde +0,003 AUC t0'da, +0,010 t0−10'da). "Daha isabetli" görünen adaylar var, ama aynı sonuç MEVCUT özelliklerle de çıkıyor (KONTROL adayları) → kazanç rehber göstergelerine atfedilemiyor ve net sonuç yine rastgele girişten ayrışmıyor.

| soru | sonuç (örneklem dışı: Blok1, Blok2, Blok3-dışı; TEST ayrıca) |
|---|---|
| **Yeni göstergeler olay ÖNCESİ ayırt edici mi?** | t0'da (ilk yeşil mumdan hemen önce) 401 özelliğin 237'si FWER<0,05 (|AUC−½| > 0,016); ama en güçlüleri (AUC 0,32–0,36) olayın "küçük düşüşten sonra başlaması"nın yeniden ifadesi: mevcut `ret1/ret10` (AUC 0,33) ile aynı bant; MA'larda dip-kontrollü artık AUC 0,44–0,57 (≈ ½), osilatörlerde 0,38–0,46 (aralık-içi konum; doğrusal kontrol tam almıyor). **t0−15'te aynı özellikler 0,50–0,51** (bilgi yok). t0−10'da anlamlı 126 özellikten ilk 25'in 14'ü oynaklık/genişleme ölçüsü (`15m.atr_ratio` 0,570, `1m.hv20`, `mass_index`, `kc_width`, `donch_width`: AUC 0,54–0,57; mevcut ATR14% 0,545–0,554), 9'u "yükselen rejim" (fiyat VWAP/bulut/KC üstünde, SuperTrend toplamı yüksek, açık düşüş FVG az: AUC 0,53–0,54 ya da ters yönde 0,46–0,47), 2'si hacim/momentum; **yönlü bir öncü (osilatör dönüşü, birikim, yapı) yok**. İşaretler 3 blokta tutarlı. |
| **Rehberin öncü fikirleri** | t0−10'da (5m lift, q): süpürme+geri alma 1,09 (0,29), FVG teması 0,98, OB teması 1,10 (0,055), birikim ıraksaması OBV/CMF/CVD 0,88–0,91 (ters yön), sıkışma 1,26 / sıkışma bitişi 1,25, choppiness düşüşü 1,04, SuperTrend kümesi 1,03, Fisher 0,84 ve TSI dönüşü 0,76 (ters yön); tüm 5m fikirlerde en yüksek lift 1,34 (`hv_expand` = yine oynaklık). t0'daki yüksek lift'ler (1m CCI<−100 ×2,07, Williams %R ×1,74, TD9 ×2,31) olay başladıktan sonraki dip izleri. Sinyal olarak süpürüldüğünde (13 fikir) günde 40–3 600 tetik (çoğu doygun), 60 dk önden kesinlik taban ×0,6–×2,4, t0 öncesi yakalama sayı-eşleşmiş sıfırın ×0,6–×2,1'i (en iyi `squeeze_release` ×2,1; `chop_drop` ve `sweep_reclaim` ×1,6; `acc_div_*` ≈ ×0,9–1,0). |
| **Çok değişkenli (tek tek eşik yerine model)** | HistGradientBoosting, blok-dışı bırakma: t0'da mevcut 154 özellik AUC 0,772 → +kütüphane 0,775 (+0,003); t0−10'da 0,630 → 0,641 (+0,010; blok bazında +0,003/+0,014/+0,014). Kütüphane küçük ama tutarlı ek bilgi veriyor; t0−10'daki tahmin gücü yine zayıf (AUC 0,64). |
| **Aday sinyaller (fold-B eğitiminde seçilen 6 + 3 KONTROL)** | Seçilen koşullar: 15m TRIX > 0,29, 1m Ichimoku bulut kalınlığı, 5m Donchian genişliği, 5m px_TEMA, 15m çapalı-VWAP uzaklığı + PVT eğimi, 15m bulut uzaklığı + 1m choppiness — hepsi **güçlü yükselen / oynak rejim** filtresi. Üç bağımsız blokta kararlı: günde 22–113 sinyal, 60 dk içinde olay başlama payı **%6,5–14 (taban %0,9–1,5)**, hit60@1,5 şans farkı **+5…+15 pp** (çoğu +9…+15; HA'da +4…+6 pp, kesinlik %6,6–7,3). **Ama:** (i) KONTROL adayları (yalnız MEVCUT 154 özellik, aynı yöntem) aynı ya da daha iyi (X2: kesinlik %12–14, şans farkı +12…+15 pp) → kazanç rehber göstergelerinden değil; (ii) t0'dan önce yakalama %4–15 (sıfır %1–3) iken HA %26–33 (sıfır %6–7), yani kapsama 2–5 kat düşük; (iii) şans farkı büyük ölçüde oynaklık rejimini yansıtıyor — net, koşulsuz rastgele girişten ayrışmıyor (aşağı bak). |
| **HA'dan ERKEN mi?** | **Hayır (tek zayıf istisna dışında).** Kütüphane ve KONTROL adaylarında, ortak yakalanan olaylarda sinyalin HA'dan önce gelme payı her blokta %4–26 (< %50); medyan öncelik farkı −15…−50 dk (HA önce). Rehber fikirlerinden yalnız `chop_drop` (5m, choppiness yüksekten düşüyor) "kanıtlı erken uyarı" ölçütünü (t0 öncesi yakalama > sayı-eşleşmiş sıfır×1,5 **ve** ortak olayların >%50'sinde HA'dan önce) üç blokta da geçiyor: t0 öncesi yakalama %52–56 (sıfır %33–35, ×1,5–1,6), HA'dan önce gelme %55–63 (medyan +10…+20 dk). Ama günde 1 600–2 200 tetik (sembol-saatlerin ≈ %20'si), 60 dk önden kesinlik %1,4–2,0 (taban %0,9–1,5; ×1,4–1,6) ve net koşulsuz rastgeleyle aynı (−0,45…−0,50 ↔ −0,45…−0,51) → kullanılabilir bir erken uyarı değil, zayıf bir istatistiksel eğilim. Diğer doygun rehber sinyallerinde (TEST'te "HA'dan erken" %46–71) bu üstünlük yapay: sinyal her yerde tetiklendiği için HA'dan önce gelmesi bilgi taşımıyor (t0 öncesi yakalama ≈ sıfır); `sweep_reclaim` 1/3, `squeeze_release` 2/3 blokta ölçütü sağlıyor. |
| **Net-pozitif mi?** | **Hayır.** 22 sinyalin hiçbirinde, TEST ve üç blokta (Blok1, Blok2, Blok3-dışı) TP1,5/SL3/T60, TP2,0/SL3/T60 ya da izleyen 1,0/0,8 neti pozitif değil (gerçekçi doluş: 60 sn, %0,15 kayma, %0,1125/bacak). Örneklem dışı blok netleri: adaylar TP1,5 −0,70…−0,39, izleyen −0,67…−0,32; koşulsuz rastgele giriş −0,51…−0,45 (TP1,5); HA −0,54…−0,50. Rastgeleye göre en iyi fark yalnız KONTROL X2'de (TP1,5 +0,08 pp, izleyen +0,16 pp, Blok1) — maliyet tabanının çok altında. |
| **LUNATRY 17 Ekim 01:00** | 6 kütüphane adayı + 3 KONTROL adayının **hiçbiri** 00:00–04:00 arasında LUNATRY'de tetiklenmedi (5m satırları 01:00–01:25 eksik → düz doldurulmuş, sembol likit değil). Rehber fikirlerinden `fvg_bull_tap` (00:05'ten itibaren 19 tetik), `vortex_cross_up3` (00:00–00:35), `st_cluster_flip` (00:25–00:30), `acc_div_*` (00:00…) tetiklendi ama bunlar günde binlerce kez tetiklenen doygun sinyaller. HA için 17 Ekim verisi yok (`rescan_90g_nogate.jsonl` 16 Ekim 23:55'te bitiyor). |

**Pratik sonuç:** Rehberdeki göstergeleri canlı puanlamaya/erken-uyarıya eklemek net sonucu değiştirmiyor. Tek tutarlı bilgi **oynaklık genişlemesi** (ATR oranı, hv, KC/Donchian genişliği) ve **güçlü yükselen rejim**; ikisi de mevcut özelliklerle (ATR14%, EMA50/99 açıklığı) zaten elde ediliyor ve HA'nın seçtiği kümeyle örtüşüyor. Yönlü bir öncü (süpürme, FVG/OB, birikim ıraksaması, sıkışma, SuperTrend/Vortex/Fisher/TSI dönüşü) 5m'de t0−10'da şanstan anlamlı biçimde ayrışmıyor.


## 1. Kütüphane (`app/rescan/indicators_ext.py`, 31 birim testi, nedensellik + kesme testleri)

`compute_all(arr, tf)` her zaman diliminde **134** (1m: 133) özellik üretir; çalışmada 5m + 1m + 15m = **401** sütun. Aileler: flow 15, loc 11, ma 17, osc 28, smc 32, trend 34, vol 4 (zaman dilimi başına).

**Eklenenler:** ALMA, WMA, Hull, DEMA, TEMA, KAMA, McGinley, LSMA + standart hata bandı; OBV, A/D, CMF, Chaikin osilatörü, Klinger, Ease of Movement, Elder Force, PVT, hacim osilatörü, taker CVD (+eğim), emir akışı dengesizliği z-skoru; CMO, Connors RSI, Stokastik %K/%D, StochRSI (mevcut modül sarmalandı), Williams %R, Ultimate, Awesome, TSI, TRIX, KST, Fisher, RVI, Balance of Power, CCI, DPO, SMI Ergodic, Coppock; Vortex, Parabolik SAR, SuperTrend (+3'lü küme), Ichimoku (bulut konumu, Tenkan/Kijun kesişimi, Chikou), Donchian (+iç-bar kırılımı), Keltner, sıkışma (BB/KC), Choppiness, Mass Index, ATR oranı, tarihsel oynaklık, Chaikin oynaklığı, göreli oynaklık endeksi; oturum VWAP uzaklığı, 24 sa dibinden çapalı VWAP, hacim profili POC (24 sa, 50 kutu; 1m hariç); SMC: fraktal salınımlar (onay gecikmeli), BOS/CHoCH durumu, likidite süpürme + geri alma, eşit dip/tepe, FVG (yeni/açık/temas), order block (mesafe/temas), yer değiştirme (displacement), TD Sequential kurulum sayacı.

**Zaten vardı (tekrarlanmadı):** EMA(7/20/50/99) uzaklık+eğim+fan, RSI14, MFI14, ATR14%, Bollinger genişlik/%B, MACD hist(+eğim), ADX/±DI, Aroon, doğrusal regresyon eğimi, ret1…20, hacim oranı, 24 sa yüksek/alçak uzaklığı, range_pos24, yeşil/higher-low koşuları, drawdown12, 27 taker özelliği; StochRSI modülü (`stochrsi.py`), RQK (`rqk.py`); mum fitil reddi z-skoru (`technical_analysis._wick_rejection_zscore`).

## 2. Yöntem

- **Olaylar:** `work/pattern90/events.csv` / `events.pkl` — 90 günde 4 662 olay; birincil kümesiz küme (kept_primary=1) ve özellikleri tam olanlar: **4552 olay**. t0 = koşunun ilk mumu; karar anı = t0'dan hemen önce kapanan bar. Anlık görüntüler: **t0−15, t0−10, t0−5, t0** (hep o ana dek KAPANMIŞ barlar; 1m ve 15m özellikleri 5m karar anına son kapanmış 1m/15m barından eşlenir).
- **Taban:** eşleşmiş — aynı sembol + aynı gün, olay başına ≤ 40 rastgele geçerli an (toplam 182003), olayla aynı ofsetler. Geçerli an: ısınma ≥ 300 bar, 24 sa quote ≥ 5M TRY, olay koşusu dışı.
- **İstatistik:** her özellik için **grup-içi AUC** (olay, kendi 40 tabanının kaçından büyük; gruplar üzerinde ortalama), standartlaştırılmış fark d (uçlar %1 winsor), **grup-içi permütasyon** (her grupta 'olay' etiketi grubun 41 üyesinden rastgele seçilir; 1000 permütasyon) → çift taraflı p, **FWER** (max-|AUC−½| dağılımına göre, 401 özellik ailesi) ve **Benjamini–Hochberg q**. FWER eşiği t0'da |AUC−½| > 0,016. Permütasyon gruplar arası bağımlılığı (aynı gün dalgaları) hesaba katmaz → blok tutarlılığı (3 ayrı 30 günlük blokta aynı işaret) ve dip-kontrollü artık AUC ayrıca verilir.
- **Dip kontrolü:** olaylar küçük bir düşüşten sonra başlıyor (90 günlük çalışma). 'AUC artık': özellik, 19 mevcut fiyat/oynaklık/taker özelliğine (ret1…20, ATR, %B, EMA uzaklığı, RSI, taker) taban satırlarında doğrusal regresyonla bağlanıp artığın AUC'si — 0,5'e yakınsa özellik 'dip + oynaklık'tan fazla bilgi taşımıyor demektir.
- **Aday sinyaller:** fold-B EĞİTİM dönemi (2–17 Ekim) verisinden seçildi (etiket = 'karar anından sonraki 60 dk içinde aynı sembolde olay başlıyor'; eğitimde 13 pozitif bar/olay + geçerli diğer barlardan %12 örnek); açgözlü AND (olasılık oranı en yüksek; olay-düzeyi geri çağırma ve tahmini sinyal/gün kısıtlı), eşikler pozitif dağılımın kuantillerinde. Sonra diğer tüm dönemlerde **DOKUNULMADAN** değerlendirildi. Rehberin 13 öncü fikri ayrıca ÖNCEDEN BELİRLENMİŞ koşullarla (veri-seçimsiz; yalnız eşikleri taban kuantilleri) 5m'de süpürüldü.
- **Süpürme:** 5m karar ızgarasında, sembol başına cooldown 12 bar (60 dk), geçerli an ve ileri sonuç ölçülebilir olmalı (pattern90 süpürmesiyle aynı). **Ölçüler:** sinyal/gün; 60 dk içinde olay başlama payı (taban = tüm geçerli anlarda aynı ölçü); hit60@1,5 (60 dk MFE ≥ %1,5) ve şans farkı (null3: aynı sembol, ±1 sa dilimi, son 30 dk aralık+getiri benzer; gün-kümeli ±%95); `exit_sim` net (60 sn gecikme, %0,15 kayma, %0,1125/bacak ücret; TP1,5/SL3/T60 ve izleyen 1,0/0,8; gün-kümeli t) ve KOŞULSUZ rastgele giriş (tüm geçerli anlardan 150 bin tekdüze) ile aynı çıkış (sinyal−rastgele farkı gün-kümeli SE'lerle); olay yakalama = t0'dan ÖNCE (t0−60 dk … t0) ilk sinyal (sıfır = aynı sembolde aynı sayıda serbestçe yerleştirilmiş rastgele sinyal); öncelik = t0 − ilk sinyal; HA karşılaştırması = [t0−60, t0+90 dk] penceresinde ilk HA tıkı (canlı-benzeri: rank ≤ 10, aşırı alımda değil).
- **Dönemler:** EĞİTİM = 2–17 Eki (seçim burada → örneklem İÇİ); TEST = 29 Tem–1 Eki; Blok1/2 = 19 Tem–17 Ağu / 18 Ağu–16 Eyl; Blok3 dışı = 17 Eyl–1 Eki (Blok3'ün eğitimle örtüşmeyen kısmı). Test/Blok1/Blok2/Blok3-dışı **örneklem dışı**, birbirleriyle örtüşmez (TEST = Blok1 + Blok2 + Blok3-dışı'nın 29 Tem sonrası birleşimi → bağımsız 3 deney: Blok1, Blok2, Blok3-dışı).

## 3. Sıralama: yeni göstergeler olay öncesinde ayırt edici mi?

### t0 (karar anı: ilk yeşil mumdan hemen önce) — ilk 25 (|AUC−½|), 401 özellik (5m+1m+15m), eşleşmiş taban

FWER p<0,05: **237** özellik; BH q<0,10: **326** özellik (olay 4552, taban 182003).

| # | özellik | aile | AUC | d | q (BH) | FWER p | AUC blok1 / blok2 / blok3 | blok işareti | AUC artık (dip-kontrollü) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `1m.px_wma` | ma | 0,318 | -0,55 | 0,001 | <0,001 | 0,311 / 0,305 / 0,332 | 3/3 aynı | 0,510 |
| 2 | `5m.crsi` | osc | 0,319 | -0,61 | 0,001 | <0,001 | 0,316 / 0,309 / 0,329 | 3/3 aynı | 0,380 |
| 3 | `5m.px_alma` | ma | 0,321 | -0,54 | 0,001 | <0,001 | 0,313 / 0,309 / 0,335 | 3/3 aynı | 0,484 |
| 4 | `5m.disp_body_atr` | smc | 0,324 | -0,54 | 0,001 | <0,001 | 0,322 / 0,318 / 0,331 | 3/3 aynı | 0,460 |
| 5 | `1m.px_kama` | ma | 0,325 | -0,55 | 0,001 | <0,001 | 0,316 / 0,317 / 0,336 | 3/3 aynı | 0,438 |
| 6 | `1m.slope_dema` | ma | 0,326 | -0,52 | 0,001 | <0,001 | 0,319 / 0,314 / 0,339 | 3/3 aynı | 0,499 |
| 7 | `1m.slope_tema` | ma | 0,327 | -0,53 | 0,001 | <0,001 | 0,322 / 0,317 / 0,339 | 3/3 aynı | 0,497 |
| 8 | `1m.cci20` | osc | 0,329 | -0,57 | 0,001 | <0,001 | 0,319 / 0,318 / 0,345 | 3/3 aynı | 0,404 |
| 9 | `1m.slope_alma` | ma | 0,339 | -0,49 | 0,001 | <0,001 | 0,337 / 0,326 / 0,351 | 3/3 aynı | 0,495 |
| 10 | `1m.px_mcg` | ma | 0,340 | -0,47 | 0,001 | <0,001 | 0,336 / 0,326 / 0,354 | 3/3 aynı | 0,507 |
| 11 | `1m.willr14` | osc | 0,341 | -0,54 | 0,001 | <0,001 | 0,337 / 0,335 / 0,349 | 3/3 aynı | 0,404 |
| 12 | `1m.slope_kama` | ma | 0,341 | -0,45 | 0,001 | <0,001 | 0,333 / 0,334 / 0,352 | 3/3 aynı | 0,573 |
| 13 | `1m.psar_dist` | trend | 0,343 | -0,49 | 0,001 | <0,001 | 0,343 / 0,325 / 0,358 | 3/3 aynı | 0,474 |
| 14 | `1m.donch_pos20` | trend | 0,343 | -0,53 | 0,001 | <0,001 | 0,333 / 0,336 / 0,355 | 3/3 aynı | 0,406 |
| 15 | `1m.kc_pos` | trend | 0,345 | -0,39 | 0,001 | <0,001 | 0,338 / 0,337 / 0,356 | 3/3 aynı | 0,494 |
| 16 | `1m.px_dema` | ma | 0,346 | -0,48 | 0,001 | <0,001 | 0,345 / 0,336 / 0,356 | 3/3 aynı | 0,505 |
| 17 | `1m.slope_wma` | ma | 0,347 | -0,47 | 0,001 | <0,001 | 0,338 / 0,336 / 0,361 | 3/3 aynı | 0,501 |
| 18 | `1m.stoch_k` | osc | 0,349 | -0,50 | 0,001 | <0,001 | 0,346 / 0,343 / 0,357 | 3/3 aynı | 0,419 |
| 19 | `1m.ms_dist_sh` | smc | 0,350 | -0,43 | 0,001 | <0,001 | 0,355 / 0,336 / 0,358 | 3/3 aynı | 0,540 |
| 20 | `1m.tsi_sig_diff` | osc | 0,353 | -0,44 | 0,001 | <0,001 | 0,346 / 0,345 / 0,364 | 3/3 aynı | 0,462 |
| 21 | `1m.st_dist` | trend | 0,355 | -0,42 | 0,001 | <0,001 | 0,351 / 0,343 / 0,367 | 3/3 aynı | 0,472 |
| 22 | `1m.st_cluster_sum` | trend | 0,355 | -0,51 | 0,001 | <0,001 | 0,352 / 0,347 / 0,364 | 3/3 aynı | 0,420 |
| 23 | `1m.slope_mcg` | ma | 0,357 | -0,45 | 0,001 | <0,001 | 0,352 / 0,345 / 0,371 | 3/3 aynı | 0,473 |
| 24 | `5m.px_tema` | ma | 0,359 | -0,41 | 0,001 | <0,001 | 0,354 / 0,344 / 0,375 | 3/3 aynı | 0,505 |
| 25 | `1m.fisher` | osc | 0,359 | -0,46 | 0,001 | <0,001 | 0,358 / 0,352 / 0,366 | 3/3 aynı | 0,437 |

Referans (MEVCUT fiyat/taker özellikleri, aynı eşleşmiş AUC): `1m.ret10` 0,33, `5m.ret1` 0,33, `1m.ret5` 0,33, `1m.rsi14` 0,35, `5m.px_ema7` 0,35.

Aile özeti:

| aile | özellik | q<0,10 | FWER<0,05 | en güçlü (|AUC−½|) |
|---|---|---|---|---|
| flow | 45 | 37 | 32 | `1m.efi13` (0,379) |
| loc | 11 | 9 | 5 | `5m.poc_dist` (0,473) |
| ma | 51 | 47 | 42 | `1m.px_wma` (0,318) |
| osc | 84 | 73 | 61 | `5m.crsi` (0,319) |
| smc | 96 | 67 | 34 | `5m.disp_body_atr` (0,324) |
| trend | 102 | 83 | 53 | `1m.psar_dist` (0,343) |
| vol | 12 | 10 | 10 | `1m.rvi_vol` (0,397) |

### t0−10 dk — ilk 25 (|AUC−½|), 401 özellik (5m+1m+15m), eşleşmiş taban

FWER p<0,05: **126** özellik; BH q<0,10: **241** özellik (olay 4552, taban 182003).

| # | özellik | aile | AUC | d | q (BH) | FWER p | AUC blok1 / blok2 / blok3 | blok işareti | AUC artık (dip-kontrollü) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `15m.atr_ratio` | vol | 0,570 | 0,23 | 0,003 | <0,001 | 0,551 / 0,587 / 0,567 | 3/3 aynı | 0,570 |
| 2 | `1m.hv20` | vol | 0,558 | 0,15 | 0,003 | <0,001 | 0,553 / 0,562 / 0,557 | 3/3 aynı | 0,533 |
| 3 | `15m.chaikin_vol` | vol | 0,556 | 0,17 | 0,003 | <0,001 | 0,540 / 0,563 / 0,560 | 3/3 aynı | 0,544 |
| 4 | `15m.mass_index` | trend | 0,555 | 0,20 | 0,003 | <0,001 | 0,535 / 0,573 / 0,553 | 3/3 aynı | 0,557 |
| 5 | `1m.lsma_se_pct` | ma | 0,555 | 0,14 | 0,003 | <0,001 | 0,556 / 0,553 / 0,555 | 3/3 aynı | 0,522 |
| 6 | `5m.mass_index` | trend | 0,554 | 0,21 | 0,003 | <0,001 | 0,543 / 0,556 / 0,558 | 3/3 aynı | 0,547 |
| 7 | `5m.atr_ratio` | vol | 0,554 | 0,21 | 0,003 | <0,001 | 0,550 / 0,560 / 0,551 | 3/3 aynı | 0,546 |
| 8 | `5m.kc_width` | trend | 0,551 | 0,10 | 0,003 | <0,001 | 0,544 / 0,558 / 0,550 | 3/3 aynı | 0,528 |
| 9 | `1m.kc_width` | trend | 0,549 | 0,12 | 0,003 | <0,001 | 0,540 / 0,557 / 0,548 | 3/3 aynı | 0,508 |
| 10 | `1m.donch_width20` | trend | 0,549 | 0,13 | 0,003 | <0,001 | 0,548 / 0,551 / 0,547 | 3/3 aynı | 0,510 |
| 11 | `5m.bb_kc_ratio` | trend | 0,458 | -0,13 | 0,003 | <0,001 | 0,456 / 0,458 / 0,459 | 3/3 aynı | 0,470 |
| 12 | `5m.fvg_bear_open` | smc | 0,459 | -0,15 | 0,003 | <0,001 | 0,470 / 0,454 / 0,458 | 3/3 aynı | 0,475 |
| 13 | `15m.fvg_bear_open` | smc | 0,460 | -0,13 | 0,003 | <0,001 | 0,464 / 0,447 / 0,467 | 3/3 aynı | 0,474 |
| 14 | `1m.mass_index` | trend | 0,539 | 0,15 | 0,003 | <0,001 | 0,541 / 0,540 / 0,539 | 3/3 aynı | 0,521 |
| 15 | `5m.chaikin_vol` | vol | 0,539 | 0,11 | 0,003 | <0,001 | 0,544 / 0,537 / 0,538 | 3/3 aynı | 0,528 |
| 16 | `5m.hv20` | vol | 0,537 | 0,11 | 0,003 | <0,001 | 0,532 / 0,543 / 0,536 | 3/3 aynı | 0,514 |
| 17 | `15m.vwap_dist` | loc | 0,536 | 0,09 | 0,003 | <0,001 | 0,526 / 0,553 / 0,528 | 3/3 aynı | 0,524 |
| 18 | `15m.st_cluster_sum` | trend | 0,536 | 0,14 | 0,003 | <0,001 | 0,526 / 0,548 / 0,531 | 3/3 aynı | 0,534 |
| 19 | `5m.vwap_dist` | loc | 0,534 | 0,08 | 0,003 | <0,001 | 0,524 / 0,549 / 0,527 | 3/3 aynı | 0,524 |
| 20 | `1m.vwap_dist` | loc | 0,534 | 0,08 | 0,003 | <0,001 | 0,524 / 0,549 / 0,527 | 3/3 aynı | 0,524 |
| 21 | `15m.ichi_cloud_pos` | trend | 0,534 | 0,13 | 0,003 | <0,001 | 0,537 / 0,540 / 0,526 | 3/3 aynı | 0,531 |
| 22 | `15m.kc_pos` | trend | 0,533 | 0,13 | 0,003 | <0,001 | 0,528 / 0,547 / 0,524 | 3/3 aynı | 0,524 |
| 23 | `15m.vol_osc` | flow | 0,532 | 0,13 | 0,003 | <0,001 | 0,530 / 0,542 / 0,526 | 3/3 aynı | 0,525 |
| 24 | `15m.vi_minus` | trend | 0,468 | -0,13 | 0,003 | <0,001 | 0,473 / 0,467 / 0,467 | 3/3 aynı | 0,471 |
| 25 | `15m.smi_erg` | osc | 0,531 | 0,14 | 0,003 | <0,001 | 0,525 / 0,546 / 0,523 | 3/3 aynı | 0,530 |

Referans (MEVCUT fiyat/taker özellikleri, aynı eşleşmiş AUC): `1m.atr14_pct` 0,55, `5m.atr14_pct` 0,55, `5m.vol_ratio3` 0,54, `5m.rsi14` 0,52, `5m.ret20` 0,52.

Aile özeti:

| aile | özellik | q<0,10 | FWER<0,05 | en güçlü (|AUC−½|) |
|---|---|---|---|---|
| flow | 45 | 14 | 6 | `15m.vol_osc` (0,532) |
| loc | 11 | 11 | 9 | `15m.vwap_dist` (0,536) |
| ma | 51 | 40 | 20 | `1m.lsma_se_pct` (0,555) |
| osc | 84 | 57 | 30 | `15m.smi_erg` (0,531) |
| smc | 96 | 42 | 15 | `5m.fvg_bear_open` (0,459) |
| trend | 102 | 67 | 38 | `15m.mass_index` (0,555) |
| vol | 12 | 10 | 8 | `15m.atr_ratio` (0,570) |

### En güçlü 10 özelliğin ofset profili (AUC; t0'daki en güçlüler)

| özellik | AUC t0−15 | t0−10 | t0−5 | t0 |
|---|---|---|---|---|
| `1m.px_wma` | 0,506 | 0,486 | 0,438* | 0,318* |
| `5m.crsi` | 0,505 | 0,487 | 0,433* | 0,319* |
| `5m.px_alma` | 0,507 | 0,487 | 0,437* | 0,321* |
| `5m.disp_body_atr` | 0,501 | 0,480* | 0,430* | 0,324* |
| `1m.px_kama` | 0,502 | 0,486 | 0,439* | 0,325* |
| `1m.slope_dema` | 0,503 | 0,484 | 0,440* | 0,326* |
| `1m.slope_tema` | 0,500 | 0,481* | 0,437* | 0,327* |
| `1m.cci20` | 0,507 | 0,490 | 0,443* | 0,329* |
| `1m.slope_alma` | 0,500 | 0,482* | 0,438* | 0,339* |
| `1m.px_mcg` | 0,514 | 0,496 | 0,450* | 0,340* |

(* = o kayıtta FWER p < 0,05)

### Anlamlı özellik sayısı (FWER p<0,05) ofsete göre

| ofset | FWER<0,05 | q<0,10 | FWER eşiği (|AUC−½|) |
|---|---|---|---|
| t0−15 | 139 | 223 | 0,016 |
| t0−10 | 126 | 241 | 0,016 |
| t0−5 | 189 | 294 | 0,016 |
| t0 | 237 | 326 | 0,016 |

## 3b. Çok değişkenli test — kütüphane mevcut 154 özelliğin ÜSTÜNE bilgi ekliyor mu?

HistGradientBoosting (150 ağaç, 15 yaprak), olay vs eşleşmiş taban (olay başına 12), **blok-dışı bırakma** (iki 30 günlük blokla eğit, üçüncüde test; 3 kat). AUC = test bloğunda tüm satırlar; grup-içi = olay skorunun kendi tabanlarından büyük olma payı. Satırlar: mevcut `pattern_study` 154 özellik / mevcut + kütüphane (401) / yalnız kütüphane.

| an | özellik kümesi | Blok1 | Blok2 | Blok3 | ortalama | grup-içi ortalama |
|---|---|---|---|---|---|---|
| t0 | mevcut 154 | 0,776 | 0,778 | 0,762 | 0,772 | 0,768 |
| t0 | mevcut + kütüphane | 0,778 | 0,785 | 0,763 | 0,775 | 0,773 |
| t0 | yalnız kütüphane | 0,757 | 0,769 | 0,749 | 0,758 | 0,759 |
| t0−10 dk | mevcut 154 | 0,629 | 0,636 | 0,626 | 0,630 | 0,629 |
| t0−10 dk | mevcut + kütüphane | 0,632 | 0,650 | 0,640 | 0,641 | 0,639 |
| t0−10 dk | yalnız kütüphane | 0,601 | 0,629 | 0,619 | 0,616 | 0,612 |

Katkı (t0): kütüphane eklenince AUC farkı blok bazında +0,002, +0,006, +0,000 (ortalama +0,003).

Katkı (t0−10 dk): kütüphane eklenince AUC farkı blok bazında +0,003, +0,014, +0,014 (ortalama +0,010).

## 4. Rehberin öncü fikirleri (önceden belirlenmiş koşullar)

Her satır: koşul olay anlarında (t0 ya da t0−10) taban anlarına göre ne sıklıkta sağlanıyor. lift = olay payı / taban payı; q = BH (aile = tüm fikir × zaman dilimi satırları). Eşikler taban kuantilleri (olay bilgisi içermez).

### t0 — en anlamlı 25 (tüm zaman dilimleri)

| zaman dilimi | fikir | olaylarda var | tabanda var | lift | AUC | q (BH) |
|---|---|---|---|---|---|---|
| 1m | st_cluster_flip (3 SuperTrend kümesi yukarı döndü) | 2,0% | 6,1% | 0,32 | 0,479 | 0,002 |
| 1m | psar_flip_up3 (PSAR yukarı ≤3 bar) | 3,6% | 8,8% | 0,41 | 0,474 | 0,002 |
| 1m | td_buy9 (TD 9 alış kurulumu tamam) | 2,3% | 1,0% | 2,31 | 0,507 | 0,002 |
| 1m | td_buy7 (TD alış sayacı ≥7) | 8,9% | 4,3% | 2,09 | 0,523 | 0,002 |
| 1m | cci_os (CCI < −100) | 40,3% | 19,5% | 2,07 | 0,604 | 0,002 |
| 1m | st_flip_up3 (SuperTrend yukarı ≤3 bar) | 3,8% | 7,9% | 0,49 | 0,480 | 0,002 |
| 1m | ichi_tk_cross_up (Tenkan/Kijun yukarı kesişim) | 1,3% | 2,5% | 0,52 | 0,494 | 0,002 |
| 1m | choch_up (yapı dönüşü ≤6 bar) | 6,2% | 12,0% | 0,52 | 0,471 | 0,002 |
| 5m | fisher_turn (Fisher < −1 ve yukarı dönüyor) | 5,6% | 9,9% | 0,56 | 0,478 | 0,002 |
| 1m | disp_up (son 5 barda yukarı yer değiştirme) | 8,9% | 15,8% | 0,57 | 0,466 | 0,002 |
| 1m | sweep_reclaim (düşük süpürme + geri alma ≤3 bar) | 4,3% | 2,4% | 1,77 | 0,509 | 0,002 |
| 1m | willr_os (Williams %R < −85) | 40,6% | 23,3% | 1,74 | 0,586 | 0,002 |
| 1m | stoch_cross_os (Stoch K>D, K<25) | 15,2% | 9,0% | 1,68 | 0,531 | 0,002 |
| 5m | willr_os (Williams %R < −85) | 29,8% | 18,3% | 1,63 | 0,557 | 0,002 |
| 1m | stochrsi_cross_os (StochRSI K>D, K<20) | 12,0% | 7,5% | 1,61 | 0,523 | 0,002 |
| 1m | cvd_ofi (CVD↑ ve OFI z>1) | 8,5% | 13,5% | 0,63 | 0,475 | 0,002 |
| 5m | tsi_turn (TSI düşük bölgede sinyali yukarı kesti) | 4,3% | 6,7% | 0,64 | 0,488 | 0,002 |
| 5m | stochrsi_cross_os (StochRSI K>D, K<20) | 5,7% | 8,9% | 0,64 | 0,484 | 0,002 |
| 1m | vortex_cross_up3 (VI+ > VI− kesişimi ≤3 bar) | 8,7% | 13,5% | 0,65 | 0,476 | 0,002 |
| 5m | cci_os (CCI < −100) | 28,3% | 18,4% | 1,53 | 0,549 | 0,002 |
| 5m | ao_turn (AO<0 ve artıyor) | 15,6% | 23,4% | 0,67 | 0,461 | 0,002 |
| 1m | acc_div_obv (OBV↑, fiyat yatay) | 9,5% | 14,1% | 0,68 | 0,477 | 0,002 |
| 5m | cvd_ofi (CVD↑ ve OFI z>1) | 7,4% | 10,5% | 0,71 | 0,485 | 0,002 |
| 5m | psar_flip_up3 (PSAR yukarı ≤3 bar) | 7,4% | 10,3% | 0,72 | 0,485 | 0,002 |
| 5m | st_flip_up3 (SuperTrend yukarı ≤3 bar) | 3,8% | 5,3% | 0,72 | 0,493 | 0,002 |

### t0−10 dk — en anlamlı 25 (tüm zaman dilimleri)

| zaman dilimi | fikir | olaylarda var | tabanda var | lift | AUC | q (BH) |
|---|---|---|---|---|---|---|
| 5m | hv_expand (ATR(7)/ATR(50) > 1,3) | 26,6% | 20,0% | 1,34 | 0,533 | 0,004 |
| 5m | tsi_turn (TSI düşük bölgede sinyali yukarı kesti) | 5,1% | 6,7% | 0,76 | 0,492 | 0,004 |
| 15m | hv_expand (ATR(7)/ATR(50) > 1,3) | 33,0% | 25,3% | 1,31 | 0,539 | 0,004 |
| 5m | squeeze_on (BB, KC içinde) | 7,3% | 5,8% | 1,26 | 0,508 | 0,004 |
| 5m | squeeze_release (sıkışma son 6 barda bitti) | 8,1% | 6,5% | 1,25 | 0,508 | 0,004 |
| 5m | stochrsi_cross_os (StochRSI K>D, K<20) | 7,1% | 8,8% | 0,80 | 0,491 | 0,004 |
| 15m | squeeze_on (BB, KC içinde) | 11,4% | 9,3% | 1,23 | 0,511 | 0,004 |
| 15m | fisher_turn (Fisher < −1 ve yukarı dönüyor) | 7,6% | 9,3% | 0,81 | 0,491 | 0,004 |
| 15m | below_vwap (VWAP altı, alt %10) | 8,2% | 10,0% | 0,82 | 0,491 | 0,004 |
| 5m | below_vwap (VWAP altı, alt %10) | 8,2% | 10,0% | 0,82 | 0,491 | 0,004 |
| 1m | below_vwap (VWAP altı, alt %10) | 8,3% | 10,0% | 0,83 | 0,491 | 0,004 |
| 15m | disp_up (son 5 barda yukarı yer değiştirme) | 20,8% | 17,4% | 1,20 | 0,517 | 0,004 |
| 5m | fisher_turn (Fisher < −1 ve yukarı dönüyor) | 8,3% | 9,8% | 0,84 | 0,492 | 0,004 |
| 1m | below_avwap (çapalı VWAP altı) | 30,2% | 35,6% | 0,85 | 0,473 | 0,004 |
| 15m | ao_turn (AO<0 ve artıyor) | 17,2% | 20,2% | 0,85 | 0,485 | 0,004 |
| 5m | disp_up (son 5 barda yukarı yer değiştirme) | 18,7% | 15,9% | 1,18 | 0,514 | 0,004 |
| 15m | willr_os (Williams %R < −85) | 13,6% | 15,8% | 0,86 | 0,489 | 0,004 |
| 15m | below_avwap (çapalı VWAP altı) | 30,6% | 35,5% | 0,86 | 0,475 | 0,004 |
| 5m | below_avwap (çapalı VWAP altı) | 30,7% | 35,7% | 0,86 | 0,475 | 0,004 |
| 5m | ao_turn (AO<0 ve artıyor) | 20,0% | 23,2% | 0,86 | 0,484 | 0,004 |
| 5m | ofi_sell (OFI z<−1: taker satış baskın) | 14,2% | 16,3% | 0,87 | 0,490 | 0,004 |
| 5m | ob_active (aktif yükseliş OB var) | 63,5% | 58,6% | 1,08 | 0,524 | 0,004 |
| 15m | fvg_bull_open (açık yükseliş FVG var) | 72,9% | 70,7% | 1,03 | 0,511 | 0,004 |
| 15m | tsi_turn (TSI düşük bölgede sinyali yukarı kesti) | 5,4% | 6,7% | 0,81 | 0,494 | 0,007 |
| 15m | st_flip_up3 (SuperTrend yukarı ≤3 bar) | 5,0% | 4,1% | 1,21 | 0,504 | 0,007 |

### 5m — tüm fikirler, t0−10 dk (sinyal olarak süpürülen 13 fikir bölüm 6'dadır)

| zaman dilimi | fikir | olaylarda var | tabanda var | lift | AUC | q (BH) |
|---|---|---|---|---|---|---|
| 5m | hv_expand (ATR(7)/ATR(50) > 1,3) | 26,6% | 20,0% | 1,34 | 0,533 | 0,004 |
| 5m | tsi_turn (TSI düşük bölgede sinyali yukarı kesti) | 5,1% | 6,7% | 0,76 | 0,492 | 0,004 |
| 5m | squeeze_on (BB, KC içinde) | 7,3% | 5,8% | 1,26 | 0,508 | 0,004 |
| 5m | squeeze_release (sıkışma son 6 barda bitti) | 8,1% | 6,5% | 1,25 | 0,508 | 0,004 |
| 5m | stochrsi_cross_os (StochRSI K>D, K<20) | 7,1% | 8,8% | 0,80 | 0,491 | 0,004 |
| 5m | below_vwap (VWAP altı, alt %10) | 8,2% | 10,0% | 0,82 | 0,491 | 0,004 |
| 5m | fisher_turn (Fisher < −1 ve yukarı dönüyor) | 8,3% | 9,8% | 0,84 | 0,492 | 0,004 |
| 5m | disp_up (son 5 barda yukarı yer değiştirme) | 18,7% | 15,9% | 1,18 | 0,514 | 0,004 |
| 5m | below_avwap (çapalı VWAP altı) | 30,7% | 35,7% | 0,86 | 0,475 | 0,004 |
| 5m | ao_turn (AO<0 ve artıyor) | 20,0% | 23,2% | 0,86 | 0,484 | 0,004 |
| 5m | ofi_sell (OFI z<−1: taker satış baskın) | 14,2% | 16,3% | 0,87 | 0,490 | 0,004 |
| 5m | ob_active (aktif yükseliş OB var) | 63,5% | 58,6% | 1,08 | 0,524 | 0,004 |
| 5m | acc_div_cmf (CMF↑, fiyat yatay) | 12,3% | 13,9% | 0,88 | 0,492 | 0,007 |
| 5m | acc_div_cvd (CVD↑, fiyat yatay) | 14,5% | 15,8% | 0,91 | 0,493 | 0,025 |
| 5m | stoch_cross_os (Stoch K>D, K<25) | 8,3% | 9,4% | 0,89 | 0,495 | 0,027 |
| 5m | ob_tap (yükseliş OB teması) | 12,0% | 10,9% | 1,10 | 0,505 | 0,055 |
| 5m | acc_div_obv (OBV↑, fiyat yatay) | 11,9% | 13,1% | 0,91 | 0,494 | 0,055 |
| 5m | willr_os (Williams %R < −85) | 16,9% | 17,9% | 0,94 | 0,495 | 0,135 |
| 5m | chop_drop (choppiness yüksekten düşüyor) | 26,2% | 25,1% | 1,04 | 0,506 | 0,144 |
| 5m | cvd_ofi (CVD↑ ve OFI z>1) | 10,0% | 10,7% | 0,93 | 0,496 | 0,165 |
| 5m | sweep_reclaim (düşük süpürme + geri alma ≤3 bar) | 4,6% | 4,2% | 1,09 | 0,502 | 0,292 |
| 5m | td_buy7 (TD alış sayacı ≥7) | 4,5% | 4,8% | 0,93 | 0,498 | 0,397 |
| 5m | cci_os (CCI < −100) | 17,4% | 18,1% | 0,96 | 0,497 | 0,417 |
| 5m | fvg_bull_tap (yükseliş FVG teması) | 28,8% | 29,3% | 0,98 | 0,497 | 0,523 |
| 5m | td_buy9 (TD 9 alış kurulumu tamam) | 1,0% | 1,1% | 0,89 | 0,499 | 0,555 |
| 5m | st_flip_up3 (SuperTrend yukarı ≤3 bar) | 5,2% | 5,5% | 0,96 | 0,499 | 0,555 |
| 5m | fvg_bull_open (açık yükseliş FVG var) | 72,0% | 71,6% | 1,01 | 0,502 | 0,635 |
| 5m | st_cluster_flip (3 SuperTrend kümesi yukarı döndü) | 5,6% | 5,4% | 1,03 | 0,501 | 0,669 |
| 5m | sweep_eql (eşit diplerin süpürülmesi) | 0,3% | 0,3% | 0,91 | 0,500 | 0,754 |
| 5m | choch_up (yapı dönüşü ≤6 bar) | 12,1% | 12,0% | 1,01 | 0,501 | 0,824 |
| 5m | ichi_tk_cross_up (Tenkan/Kijun yukarı kesişim) | 2,5% | 2,5% | 1,01 | 0,500 | 0,920 |
| 5m | psar_flip_up3 (PSAR yukarı ≤3 bar) | 10,4% | 10,3% | 1,01 | 0,500 | 0,920 |
| 5m | vortex_cross_up3 (VI+ > VI− kesişimi ≤3 bar) | 15,3% | 15,3% | 1,00 | 0,500 | 0,964 |

## 5. Aday erken-uyarı sinyalleri (fold-B EĞİTİMİNDE seçildi, diğer dönemlerde dokunulmadan ölçüldü)

Eğitim: 125703 satır, 10665 pozitif bar (828 olay), geçerli an/gün ≈ 60932. Tek özellik en iyi eğitim AUC'leri: `g:5m.atr14_pct` 0,84, `15m.kc_width` 0,84, `5m.kc_width` 0,84, `g:3m.atr14_pct` 0,84, `g:1m.atr14_pct` 0,82, `5m.hv20` 0,81, `1m.kc_width` 0,81, `5m.donch_width20` 0,81.

### C1 — tek koşul (tüm aileler)

Koşul: `15m.trix` > 0.2914. Eğitim: LR 13.6, bar-TPR 10,0%, olay geri çağırma 11,7%, tahmini ≤ 449 sinyal/gün.

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 54 (n 820) | 12,2% (1,1%) | 59,1% | +14,5 ±3,8 pp | -0,46 (t -6,8) | +0,07 (t 1,0) | -0,43 (t -6,4) | 11,1% (2,0%) | 26% (n 115) |
| TEST (29 Tem–1 Eki, fold B) | 64 (n 4155) | 11,2% (1,2%) | 60,0% | +12,7 ±1,8 pp | -0,52 (t -16,1) | -0,04 (t -1,1) | -0,49 (t -17,4) | 12,3% (2,5%) | 25% (n 619) |
| Blok1 (19 Tem–17 Ağu) | 51 (n 1477) | 12,1% (0,9%) | 64,7% | +11,8 ±2,6 pp | -0,52 (t -9,2) | -0,01 (t -0,3) | -0,46 (t -9,3) | 14,4% (2,3%) | 23% (n 218) |
| Blok2 (18 Ağu–16 Eyl) | 58 (n 1743) | 10,4% (1,1%) | 55,5% | +11,8 ±2,5 pp | -0,62 (t -16,5) | -0,13 (t -3,0) | -0,58 (t -17,4) | 10,7% (2,5%) | 26% (n 257) |
| Blok3 dışı (17 Eyl–1 Eki) | 88 (n 1325) | 10,9% (1,5%) | 61,2% | +14,1 ±2,2 pp | -0,42 (t -7,9) | +0,03 (t 0,4) | -0,41 (t -10,1) | 12,2% (2,3%) | 26% (n 197) |

LUNATRY 17 Ekim 01:00 (t0) — bu sinyalin 00:00–04:00 arası tetik saatleri: YOK.

### C2 — 2 koşul (tüm aileler)

Koşul: `15m.trix` > 0.2914 **VE** `1m.ichi_cloud_thick` > 1.269. Eğitim: LR 17.3, bar-TPR 3,9%, olay geri çağırma 8,3%, tahmini ≤ 136 sinyal/gün.

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 32 (n 485) | 12,2% (1,1%) | 64,5% | +15,3 ±3,9 pp | -0,50 (t -5,0) | +0,02 (t 0,2) | -0,55 (t -6,1) | 6,9% (1,3%) | 17% (n 102) |
| TEST (29 Tem–1 Eki, fold B) | 38 (n 2478) | 11,4% (1,2%) | 64,9% | +12,6 ±2,2 pp | -0,51 (t -11,0) | -0,03 (t -0,6) | -0,44 (t -10,3) | 7,7% (1,7%) | 14% (n 530) |
| Blok1 (19 Tem–17 Ağu) | 34 (n 986) | 12,6% (0,9%) | 68,8% | +11,2 ±3,1 pp | -0,48 (t -6,8) | +0,03 (t 0,4) | -0,43 (t -5,6) | 10,8% (1,6%) | 16% (n 192) |
| Blok2 (18 Ağu–16 Eyl) | 33 (n 1004) | 9,7% (1,1%) | 60,8% | +12,7 ±3,9 pp | -0,61 (t -8,5) | -0,12 (t -1,6) | -0,52 (t -7,7) | 5,8% (1,8%) | 12% (n 214) |
| Blok3 dışı (17 Eyl–1 Eki) | 50 (n 753) | 11,8% (1,5%) | 65,6% | +12,9 ±2,9 pp | -0,43 (t -4,6) | +0,02 (t 0,2) | -0,38 (t -4,8) | 7,6% (1,3%) | 14% (n 172) |

LUNATRY 17 Ekim 01:00 (t0) — bu sinyalin 00:00–04:00 arası tetik saatleri: YOK.

### C3 — 3 koşul (tüm aileler)

Koşul: `15m.trix` > 0.2914 **VE** `5m.donch_width20` > 9.529 **VE** `1m.ms_since_choch_up` <= 59. Eğitim: LR 21.6, bar-TPR 3,5%, olay geri çağırma 6,4%, tahmini ≤ 99 sinyal/gün.

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 20 (n 302) | 15,6% (1,1%) | 66,2% | +11,6 ±5,8 pp | -0,54 (t -5,3) | -0,02 (t -0,2) | -0,46 (t -5,7) | 5,7% (1,0%) | 19% (n 73) |
| TEST (29 Tem–1 Eki, fold B) | 26 (n 1716) | 12,1% (1,2%) | 67,6% | +8,7 ±2,5 pp | -0,56 (t -11,8) | -0,08 (t -1,6) | -0,46 (t -8,8) | 5,6% (1,0%) | 12% (n 366) |
| Blok1 (19 Tem–17 Ağu) | 26 (n 763) | 13,0% (0,9%) | 71,7% | +8,8 ±2,8 pp | -0,51 (t -7,9) | -0,00 (t -0,1) | -0,50 (t -7,4) | 8,2% (1,2%) | 11% (n 151) |
| Blok2 (18 Ağu–16 Eyl) | 22 (n 656) | 10,4% (1,1%) | 63,4% | +9,8 ±5,0 pp | -0,70 (t -9,7) | -0,21 (t -2,9) | -0,60 (t -6,8) | 4,0% (0,7%) | 12% (n 136) |
| Blok3 dışı (17 Eyl–1 Eki) | 33 (n 491) | 13,0% (1,5%) | 67,0% | +6,0 ±3,9 pp | -0,48 (t -5,0) | -0,03 (t -0,3) | -0,32 (t -3,1) | 5,6% (1,4%) | 12% (n 113) |

LUNATRY 17 Ekim 01:00 (t0) — bu sinyalin 00:00–04:00 arası tetik saatleri: YOK.

### C4 — 2 koşul: osilatör + hareketli ortalama

Koşul: `15m.trix` > 0.2914 **VE** `5m.px_tema` > 0.813. Eğitim: LR 21.3, bar-TPR 2,3%, olay geri çağırma 8,1%, tahmini ≤ 65 sinyal/gün.

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 30 (n 452) | 12,8% (1,1%) | 56,2% | +9,5 ±6,6 pp | -0,67 (t -6,8) | -0,15 (t -1,5) | -0,64 (t -6,3) | 7,4% (1,3%) | 26% (n 100) |
| TEST (29 Tem–1 Eki, fold B) | 35 (n 2269) | 10,0% (1,2%) | 61,0% | +11,1 ±2,0 pp | -0,52 (t -11,5) | -0,04 (t -0,8) | -0,49 (t -13,1) | 6,4% (1,0%) | 19% (n 489) |
| Blok1 (19 Tem–17 Ağu) | 30 (n 868) | 11,6% (0,9%) | 64,7% | +9,0 ±3,1 pp | -0,56 (t -7,1) | -0,05 (t -0,7) | -0,53 (t -6,7) | 8,9% (1,2%) | 17% (n 177) |
| Blok2 (18 Ağu–16 Eyl) | 30 (n 894) | 9,1% (1,1%) | 57,6% | +11,0 ±3,5 pp | -0,58 (t -8,6) | -0,09 (t -1,3) | -0,57 (t -10,4) | 5,1% (0,8%) | 24% (n 190) |
| Blok3 dışı (17 Eyl–1 Eki) | 49 (n 732) | 9,3% (1,5%) | 60,7% | +11,8 ±3,4 pp | -0,43 (t -5,4) | +0,01 (t 0,2) | -0,40 (t -7,6) | 6,0% (1,3%) | 15% (n 164) |

LUNATRY 17 Ekim 01:00 (t0) — bu sinyalin 00:00–04:00 arası tetik saatleri: YOK.

### C5 — 2 koşul: akış (hacim/CVD) + konum (VWAP/POC)

Koşul: `15m.avwap_dist` > 4.6 **VE** `5m.pvt_slope12` > 0.004423. Eğitim: LR 13.2, bar-TPR 4,1%, olay geri çağırma 9,8%, tahmini ≤ 189 sinyal/gün.

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 59 (n 902) | 6,8% (1,1%) | 51,7% | +4,9 ±3,5 pp | -0,59 (t -6,6) | -0,06 (t -0,7) | -0,57 (t -7,2) | 7,6% (2,2%) | 22% (n 276) |
| TEST (29 Tem–1 Eki, fold B) | 74 (n 4838) | 7,2% (1,2%) | 55,4% | +6,3 ±2,2 pp | -0,48 (t -13,2) | +0,00 (t 0,0) | -0,48 (t -15,0) | 9,7% (2,3%) | 23% (n 1580) |
| Blok1 (19 Tem–17 Ağu) | 49 (n 1425) | 9,5% (0,9%) | 63,3% | +6,3 ±2,6 pp | -0,47 (t -8,0) | +0,03 (t 0,6) | -0,44 (t -7,3) | 11,8% (2,6%) | 19% (n 464) |
| Blok2 (18 Ağu–16 Eyl) | 71 (n 2115) | 6,8% (1,1%) | 54,1% | +8,4 ±3,3 pp | -0,46 (t -8,0) | +0,02 (t 0,4) | -0,47 (t -9,9) | 8,8% (2,1%) | 26% (n 707) |
| Blok3 dışı (17 Eyl–1 Eki) | 113 (n 1688) | 6,5% (1,5%) | 51,8% | +4,7 ±2,0 pp | -0,53 (t -8,9) | -0,08 (t -1,2) | -0,51 (t -9,4) | 9,4% (2,3%) | 24% (n 545) |

LUNATRY 17 Ekim 01:00 (t0) — bu sinyalin 00:00–04:00 arası tetik saatleri: YOK.

### C6 — 2 koşul: yapı (SMC) + trend + oynaklık

Koşul: `15m.ichi_cloud_dist` > 8.705 **VE** `1m.chop14` > 52.53. Eğitim: LR 15.6, bar-TPR 2,7%, olay geri çağırma 10,3%, tahmini ≤ 104 sinyal/gün.

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 46 (n 704) | 9,9% (1,1%) | 58,0% | +11,8 ±3,1 pp | -0,67 (t -9,7) | -0,15 (t -2,1) | -0,68 (t -9,8) | 8,7% (2,1%) | 10% (n 173) |
| TEST (29 Tem–1 Eki, fold B) | 56 (n 3666) | 9,6% (1,2%) | 60,8% | +13,2 ±1,8 pp | -0,53 (t -15,1) | -0,04 (t -1,2) | -0,52 (t -15,6) | 9,8% (1,8%) | 11% (n 885) |
| Blok1 (19 Tem–17 Ağu) | 45 (n 1300) | 10,7% (0,9%) | 65,5% | +12,7 ±2,2 pp | -0,50 (t -10,2) | +0,01 (t 0,2) | -0,52 (t -9,3) | 12,2% (1,2%) | 10% (n 274) |
| Blok2 (18 Ağu–16 Eyl) | 52 (n 1571) | 10,0% (1,1%) | 57,2% | +12,5 ±3,0 pp | -0,57 (t -10,0) | -0,08 (t -1,4) | -0,54 (t -11,1) | 9,6% (1,7%) | 12% (n 387) |
| Blok3 dışı (17 Eyl–1 Eki) | 77 (n 1154) | 8,1% (1,5%) | 59,9% | +12,9 ±2,7 pp | -0,55 (t -8,7) | -0,10 (t -1,4) | -0,55 (t -8,5) | 8,0% (2,1%) | 11% (n 292) |

LUNATRY 17 Ekim 01:00 (t0) — bu sinyalin 00:00–04:00 arası tetik saatleri: YOK.

### X1 — KONTROL tek koşul (yalnız MEVCUT 154 özellik)

Koşul: `g:5m.ema50_99` > 2.055. Eğitim: LR 12.8, bar-TPR 10,0%, olay geri çağırma 12,1%, tahmini ≤ 476 sinyal/gün.

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 58 (n 887) | 10,8% (1,1%) | 58,7% | +12,8 ±3,6 pp | -0,52 (t -5,9) | -0,00 (t -0,0) | -0,45 (t -4,7) | 11,7% (2,9%) | 24% (n 140) |
| TEST (29 Tem–1 Eki, fold B) | 70 (n 4572) | 10,7% (1,2%) | 61,4% | +13,6 ±1,9 pp | -0,52 (t -17,0) | -0,04 (t -1,1) | -0,48 (t -17,5) | 13,1% (2,2%) | 19% (n 752) |
| Blok1 (19 Tem–17 Ağu) | 55 (n 1591) | 11,7% (0,9%) | 66,9% | +13,3 ±1,9 pp | -0,43 (t -9,0) | +0,08 (t 1,6) | -0,40 (t -10,2) | 15,3% (2,6%) | 17% (n 252) |
| Blok2 (18 Ağu–16 Eyl) | 64 (n 1924) | 9,8% (1,1%) | 58,3% | +14,1 ±2,8 pp | -0,59 (t -13,3) | -0,10 (t -2,2) | -0,51 (t -11,3) | 11,2% (1,8%) | 21% (n 320) |
| Blok3 dışı (17 Eyl–1 Eki) | 98 (n 1477) | 10,6% (1,5%) | 60,8% | +13,5 ±2,0 pp | -0,49 (t -8,8) | -0,04 (t -0,6) | -0,48 (t -10,0) | 13,1% (2,3%) | 18% (n 244) |

LUNATRY 17 Ekim 01:00 (t0) — bu sinyalin 00:00–04:00 arası tetik saatleri: YOK.

### X2 — KONTROL 2 koşul (yalnız MEVCUT 154 özellik)

Koşul: `g:5m.ema50_99` > 2.055 **VE** `g:3m.dist_low24_pct` > 23.58. Eğitim: LR 16.9, bar-TPR 6,1%, olay geri çağırma 8,1%, tahmini ≤ 220 sinyal/gün.

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 32 (n 493) | 12,6% (1,1%) | 68,0% | +17,3 ±6,3 pp | -0,48 (t -3,7) | +0,04 (t 0,3) | -0,49 (t -4,3) | 8,1% (1,2%) | 15% (n 91) |
| TEST (29 Tem–1 Eki, fold B) | 41 (n 2633) | 13,1% (1,2%) | 68,6% | +13,5 ±2,1 pp | -0,44 (t -12,2) | +0,04 (t 1,1) | -0,41 (t -12,0) | 9,0% (1,8%) | 16% (n 504) |
| Blok1 (19 Tem–17 Ağu) | 36 (n 1031) | 14,2% (0,9%) | 72,7% | +12,2 ±2,3 pp | -0,43 (t -8,2) | +0,08 (t 1,5) | -0,36 (t -6,8) | 12,1% (2,2%) | 16% (n 189) |
| Blok2 (18 Ağu–16 Eyl) | 34 (n 1023) | 12,1% (1,1%) | 65,5% | +15,0 ±4,0 pp | -0,47 (t -7,7) | +0,02 (t 0,3) | -0,43 (t -7,6) | 7,1% (1,8%) | 17% (n 201) |
| Blok3 dışı (17 Eyl–1 Eki) | 57 (n 859) | 12,3% (1,5%) | 68,5% | +13,8 ±2,6 pp | -0,39 (t -6,1) | +0,06 (t 0,8) | -0,39 (t -6,5) | 8,7% (1,3%) | 15% (n 160) |

LUNATRY 17 Ekim 01:00 (t0) — bu sinyalin 00:00–04:00 arası tetik saatleri: YOK.

### X3 — KONTROL 3 koşul (yalnız MEVCUT 154 özellik)

Koşul: `g:5m.ema50_99` > 2.055 **VE** `g:5m.hl_run` > 2 **VE** `g:1m.vol_ratio3` > 0.655. Eğitim: LR 26.4, bar-TPR 1,0%, olay geri çağırma 6,3%, tahmini ≤ 24 sinyal/gün.

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 25 (n 378) | 11,6% (1,1%) | 60,6% | +13,0 ±5,8 pp | -0,45 (t -4,1) | +0,08 (t 0,7) | -0,46 (t -4,3) | 5,5% (1,4%) | 10% (n 108) |
| TEST (29 Tem–1 Eki, fold B) | 31 (n 2040) | 9,9% (1,2%) | 61,4% | +10,0 ±2,2 pp | -0,59 (t -10,8) | -0,11 (t -1,9) | -0,56 (t -10,8) | 5,6% (1,2%) | 8% (n 567) |
| Blok1 (19 Tem–17 Ağu) | 26 (n 752) | 10,8% (0,9%) | 66,5% | +9,3 ±3,3 pp | -0,51 (t -6,0) | -0,01 (t -0,1) | -0,41 (t -5,3) | 7,0% (0,9%) | 5% (n 194) |
| Blok2 (18 Ağu–16 Eyl) | 28 (n 830) | 8,8% (1,1%) | 58,2% | +10,5 ±2,8 pp | -0,61 (t -7,8) | -0,12 (t -1,5) | -0,56 (t -6,8) | 4,5% (1,1%) | 12% (n 236) |
| Blok3 dışı (17 Eyl–1 Eki) | 44 (n 663) | 9,4% (1,5%) | 60,5% | +9,5 ±5,1 pp | -0,62 (t -5,8) | -0,17 (t -1,6) | -0,67 (t -8,0) | 5,5% (1,2%) | 4% (n 186) |

LUNATRY 17 Ekim 01:00 (t0) — bu sinyalin 00:00–04:00 arası tetik saatleri: YOK.

### Hız Avcısı (referans, aynı değerlendirme yolu)

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 222 (n 3381) | 6,0% (1,1%) | 46,5% | +5,3 ±2,2 pp | -0,57 (t -15,9) | -0,05 (t -1,2) | -0,53 (t -14,2) | 24,8% (6,4%) | 0% (n 604) |
| TEST (29 Tem–1 Eki, fold B) | 235 (n 15277) | 6,9% (1,2%) | 48,1% | +5,2 ±2,0 pp | -0,53 (t -28,9) | -0,04 (t -1,9) | -0,54 (t -34,8) | 27,9% (6,3%) | 0% (n 2832) |
| Blok1 (19 Tem–17 Ağu) | 205 (n 5934) | 6,6% (0,9%) | 48,6% | +3,9 ±2,0 pp | -0,54 (t -20,2) | -0,04 (t -1,3) | -0,54 (t -22,0) | 32,7% (6,9%) | 0% (n 952) |
| Blok2 (18 Ağu–16 Eyl) | 226 (n 6766) | 6,6% (1,1%) | 47,0% | +4,5 ±2,2 pp | -0,50 (t -18,9) | -0,02 (t -0,5) | -0,55 (t -24,5) | 26,2% (6,2%) | 0% (n 1275) |
| Blok3 dışı (17 Eyl–1 Eki) | 284 (n 4262) | 7,3% (1,5%) | 48,8% | +6,0 ±1,6 pp | -0,54 (t -15,2) | -0,10 (t -2,0) | -0,54 (t -17,5) | 26,3% (6,9%) | 0% (n 881) |

LUNATRY 17 Ekim 00:00–04:00 HA tıkları (canlı-benzeri): YOK.

## 6. Rehberin 13 öncü fikri sinyal olarak (5m, önceden belirlenmiş koşul, tüm dönemler örneklem dışı sayılır)

### sweep_reclaim (düşük süpürme + geri alma ≤3 bar)

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 498 (n 7591) | 2,3% (1,1%) | 16,8% | +1,5 ±2,1 pp | -0,54 (t -16,4) | -0,02 (t -0,5) | -0,55 (t -16,7) | 17,8% (11,5%) | 52% (n 184) |
| TEST (29 Tem–1 Eki, fold B) | 463 (n 30123) | 2,2% (1,2%) | 18,1% | +2,5 ±1,5 pp | -0,49 (t -26,2) | -0,00 (t -0,2) | -0,50 (t -28,4) | 15,9% (10,2%) | 56% (n 772) |
| Blok1 (19 Tem–17 Ağu) | 378 (n 10974) | 1,7% (0,9%) | 15,0% | -0,1 ±1,2 pp | -0,52 (t -31,2) | -0,01 (t -0,7) | -0,52 (t -34,4) | 14,4% (11,6%) | 52% (n 247) |
| Blok2 (18 Ağu–16 Eyl) | 479 (n 14356) | 2,0% (1,1%) | 17,7% | +2,6 ±1,8 pp | -0,50 (t -18,3) | -0,01 (t -0,2) | -0,51 (t -21,0) | 15,6% (10,4%) | 59% (n 339) |
| Blok3 dışı (17 Eyl–1 Eki) | 559 (n 8378) | 2,7% (1,5%) | 20,6% | +4,2 ±1,5 pp | -0,44 (t -10,3) | +0,01 (t 0,2) | -0,45 (t -10,5) | 17,0% (8,8%) | 54% (n 261) |

LUNATRY 17 Ekim tetik saatleri (00:00–04:00): 04:00.

### sweep_eql (eşit diplerin süpürülmesi)

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 42 (n 640) | 3,0% (1,1%) | 15,6% | -0,7 ±2,9 pp | -0,57 (t -10,0) | -0,04 (t -0,7) | -0,59 (t -11,3) | 1,8% (0,8%) | 62% (n 21) |
| TEST (29 Tem–1 Eki, fold B) | 40 (n 2618) | 2,1% (1,2%) | 17,5% | +1,7 ±1,7 pp | -0,53 (t -15,4) | -0,04 (t -1,2) | -0,54 (t -16,8) | 1,4% (1,1%) | 60% (n 72) |
| Blok1 (19 Tem–17 Ağu) | 35 (n 1029) | 1,5% (0,9%) | 15,8% | +0,2 ±1,9 pp | -0,56 (t -14,1) | -0,05 (t -1,2) | -0,56 (t -14,8) | 1,3% (1,4%) | 50% (n 24) |
| Blok2 (18 Ağu–16 Eyl) | 40 (n 1189) | 2,1% (1,1%) | 17,3% | +1,8 ±2,6 pp | -0,51 (t -9,5) | -0,02 (t -0,3) | -0,53 (t -11,6) | 1,6% (1,0%) | 67% (n 30) |
| Blok3 dışı (17 Eyl–1 Eki) | 48 (n 718) | 3,1% (1,5%) | 19,5% | +3,2 ±4,2 pp | -0,50 (t -6,9) | -0,05 (t -0,7) | -0,53 (t -6,8) | 1,4% (0,6%) | 62% (n 26) |

LUNATRY 17 Ekim tetik saatleri (00:00–04:00): YOK.

### fvg_bull_tap (yükseliş FVG teması)

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 4025 (n 61377) | 0,9% (1,1%) | 11,4% | -0,4 ±1,4 pp | -0,53 (t -22,0) | -0,00 (t -0,1) | -0,53 (t -22,3) | 64,5% (51,6%) | 58% (n 567) |
| TEST (29 Tem–1 Eki, fold B) | 3623 (n 235496) | 1,0% (1,2%) | 12,8% | +0,4 ±1,3 pp | -0,50 (t -36,3) | -0,02 (t -0,8) | -0,51 (t -37,0) | 62,4% (52,1%) | 54% (n 2630) |
| Blok1 (19 Tem–17 Ağu) | 3079 (n 89280) | 0,8% (0,9%) | 10,2% | -0,8 ±1,0 pp | -0,52 (t -53,5) | -0,02 (t -1,1) | -0,53 (t -53,9) | 57,9% (52,4%) | 51% (n 860) |
| Blok2 (18 Ağu–16 Eyl) | 3740 (n 112189) | 1,0% (1,1%) | 12,9% | +0,8 ±1,6 pp | -0,51 (t -23,5) | -0,02 (t -0,7) | -0,52 (t -24,3) | 62,7% (53,9%) | 56% (n 1189) |
| Blok3 dışı (17 Eyl–1 Eki) | 4219 (n 63287) | 1,3% (1,5%) | 15,0% | +2,2 ±1,7 pp | -0,46 (t -15,5) | -0,01 (t -0,3) | -0,47 (t -15,6) | 64,9% (49,9%) | 56% (n 830) |

LUNATRY 17 Ekim tetik saatleri (00:00–04:00): 00:05, 00:20, 00:25, 00:35, 00:45, 00:50, 00:55, 01:00, 01:05, 01:15, 02:05, 02:10, 02:15, 02:20, 02:25, 02:30, 02:35, 02:40, 02:45.

### ob_tap (yükseliş OB teması)

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 1182 (n 18021) | 1,4% (1,1%) | 13,7% | -0,7 ±1,2 pp | -0,53 (t -28,2) | -0,01 (t -0,2) | -0,54 (t -26,4) | 26,0% (20,0%) | 45% (n 320) |
| TEST (29 Tem–1 Eki, fold B) | 1212 (n 78800) | 1,5% (1,2%) | 15,4% | +1,3 ±1,2 pp | -0,48 (t -28,1) | +0,00 (t 0,2) | -0,49 (t -29,9) | 29,1% (23,2%) | 47% (n 1502) |
| Blok1 (19 Tem–17 Ağu) | 1075 (n 31174) | 1,2% (0,9%) | 12,6% | -0,5 ±1,0 pp | -0,51 (t -39,4) | -0,00 (t -0,1) | -0,52 (t -42,4) | 29,2% (23,7%) | 39% (n 548) |
| Blok2 (18 Ağu–16 Eyl) | 1235 (n 37045) | 1,4% (1,1%) | 15,6% | +0,6 ±1,7 pp | -0,48 (t -18,3) | +0,01 (t 0,3) | -0,49 (t -19,8) | 29,2% (21,9%) | 50% (n 639) |
| Blok3 dışı (17 Eyl–1 Eki) | 1373 (n 20600) | 1,7% (1,5%) | 17,4% | +2,7 ±1,7 pp | -0,45 (t -11,0) | +0,00 (t 0,0) | -0,46 (t -11,5) | 28,1% (23,9%) | 49% (n 466) |

LUNATRY 17 Ekim tetik saatleri (00:00–04:00): 01:40.

### acc_div_obv (OBV↑, fiyat yatay)

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 2503 (n 38164) | 0,8% (1,1%) | 10,8% | +0,8 ±1,4 pp | -0,53 (t -23,0) | -0,00 (t -0,1) | -0,53 (t -23,3) | 36,3% (35,4%) | 68% (n 370) |
| TEST (29 Tem–1 Eki, fold B) | 2259 (n 146815) | 0,9% (1,2%) | 11,8% | +1,4 ±1,3 pp | -0,51 (t -36,6) | -0,03 (t -1,5) | -0,52 (t -37,8) | 34,5% (36,0%) | 64% (n 1673) |
| Blok1 (19 Tem–17 Ağu) | 1960 (n 56839) | 0,7% (0,9%) | 9,2% | -0,4 ±1,1 pp | -0,53 (t -60,6) | -0,03 (t -2,1) | -0,55 (t -61,3) | 33,2% (33,9%) | 64% (n 549) |
| Blok2 (18 Ağu–16 Eyl) | 2323 (n 69693) | 0,9% (1,1%) | 11,8% | +1,3 ±1,6 pp | -0,52 (t -23,0) | -0,03 (t -1,0) | -0,53 (t -24,0) | 34,6% (37,1%) | 66% (n 773) |
| Blok3 dışı (17 Eyl–1 Eki) | 2592 (n 38877) | 1,1% (1,5%) | 14,3% | +3,1 ±1,6 pp | -0,47 (t -15,8) | -0,03 (t -0,6) | -0,48 (t -16,3) | 37,0% (35,2%) | 65% (n 527) |

LUNATRY 17 Ekim tetik saatleri (00:00–04:00): 00:00, 01:05, 02:40, 02:45, 03:10, 03:15, 03:25, 03:40.

### acc_div_cmf (CMF↑, fiyat yatay)

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 2228 (n 33977) | 0,8% (1,1%) | 10,6% | +0,2 ±1,3 pp | -0,53 (t -25,9) | -0,00 (t -0,1) | -0,53 (t -26,1) | 29,5% (30,4%) | 62% (n 305) |
| TEST (29 Tem–1 Eki, fold B) | 2072 (n 134661) | 0,8% (1,2%) | 11,6% | +1,4 ±1,3 pp | -0,50 (t -34,8) | -0,02 (t -0,9) | -0,51 (t -35,9) | 29,2% (32,3%) | 62% (n 1365) |
| Blok1 (19 Tem–17 Ağu) | 1804 (n 52329) | 0,6% (0,9%) | 8,7% | -0,5 ±1,0 pp | -0,53 (t -49,2) | -0,02 (t -1,6) | -0,54 (t -51,9) | 26,7% (33,0%) | 57% (n 434) |
| Blok2 (18 Ağu–16 Eyl) | 2147 (n 64424) | 0,8% (1,1%) | 11,8% | +1,6 ±1,8 pp | -0,51 (t -21,3) | -0,02 (t -0,6) | -0,52 (t -22,0) | 28,9% (31,4%) | 62% (n 613) |
| Blok3 dışı (17 Eyl–1 Eki) | 2344 (n 35167) | 1,1% (1,5%) | 14,0% | +2,6 ±1,6 pp | -0,46 (t -16,0) | -0,01 (t -0,3) | -0,47 (t -16,6) | 32,7% (33,3%) | 65% (n 453) |

LUNATRY 17 Ekim tetik saatleri (00:00–04:00): 00:00, 02:40, 02:45, 02:50, 02:55, 03:00, 03:05, 03:10, 03:15.

### acc_div_cvd (CVD↑, fiyat yatay)

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 2580 (n 39343) | 0,7% (1,1%) | 9,9% | +0,1 ±1,2 pp | -0,53 (t -22,1) | -0,01 (t -0,2) | -0,54 (t -22,5) | 30,9% (36,9%) | 74% (n 290) |
| TEST (29 Tem–1 Eki, fold B) | 2451 (n 159346) | 0,8% (1,2%) | 11,2% | +1,3 ±1,5 pp | -0,50 (t -35,4) | -0,02 (t -0,8) | -0,51 (t -36,1) | 33,2% (36,6%) | 71% (n 1437) |
| Blok1 (19 Tem–17 Ağu) | 2193 (n 63590) | 0,5% (0,9%) | 8,5% | -0,5 ±1,1 pp | -0,52 (t -56,1) | -0,01 (t -0,6) | -0,53 (t -58,2) | 30,4% (36,6%) | 68% (n 456) |
| Blok2 (18 Ağu–16 Eyl) | 2540 (n 76187) | 0,8% (1,1%) | 11,4% | +1,4 ±1,6 pp | -0,51 (t -22,0) | -0,02 (t -0,6) | -0,52 (t -22,5) | 34,2% (37,1%) | 72% (n 678) |
| Blok3 dışı (17 Eyl–1 Eki) | 2702 (n 40524) | 1,1% (1,5%) | 13,7% | +3,0 ±1,4 pp | -0,46 (t -15,2) | -0,01 (t -0,3) | -0,47 (t -15,5) | 34,5% (36,6%) | 72% (n 448) |

LUNATRY 17 Ekim tetik saatleri (00:00–04:00): 00:00, 03:05, 03:10, 03:15, 03:25, 03:30, 03:35, 03:40, 03:45, 03:50, 03:55.

### squeeze_release (sıkışma son 6 barda bitti)

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 303 (n 4627) | 3,1% (1,1%) | 21,0% | +2,9 ±2,7 pp | -0,53 (t -14,7) | -0,00 (t -0,1) | -0,53 (t -15,0) | 13,2% (7,6%) | 48% (n 170) |
| TEST (29 Tem–1 Eki, fold B) | 336 (n 21829) | 2,8% (1,2%) | 21,8% | +3,4 ±1,6 pp | -0,48 (t -27,7) | +0,00 (t 0,1) | -0,51 (t -30,9) | 16,6% (8,0%) | 50% (n 949) |
| Blok1 (19 Tem–17 Ağu) | 287 (n 8310) | 2,5% (0,9%) | 20,0% | +1,7 ±1,2 pp | -0,49 (t -32,6) | +0,02 (t 1,0) | -0,51 (t -34,5) | 17,1% (9,4%) | 43% (n 339) |
| Blok2 (18 Ağu–16 Eyl) | 346 (n 10372) | 2,7% (1,1%) | 21,5% | +2,8 ±2,2 pp | -0,48 (t -17,1) | +0,01 (t 0,2) | -0,51 (t -20,0) | 16,9% (7,8%) | 54% (n 433) |
| Blok3 dışı (17 Eyl–1 Eki) | 386 (n 5797) | 3,3% (1,5%) | 23,7% | +4,7 ±1,6 pp | -0,46 (t -12,7) | -0,01 (t -0,2) | -0,47 (t -12,8) | 15,9% (7,2%) | 50% (n 284) |

LUNATRY 17 Ekim tetik saatleri (00:00–04:00): YOK.

### chop_drop (choppiness yüksekten düşüyor)

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 1917 (n 29239) | 1,7% (1,1%) | 15,6% | +1,7 ±1,3 pp | -0,52 (t -21,0) | +0,00 (t 0,1) | -0,52 (t -20,8) | 55,9% (32,4%) | 64% (n 504) |
| TEST (29 Tem–1 Eki, fold B) | 1863 (n 121063) | 1,7% (1,2%) | 16,7% | +2,1 ±1,5 pp | -0,48 (t -31,7) | -0,00 (t -0,1) | -0,50 (t -33,0) | 53,9% (34,5%) | 60% (n 2374) |
| Blok1 (19 Tem–17 Ağu) | 1569 (n 45502) | 1,4% (0,9%) | 14,5% | +1,0 ±1,2 pp | -0,50 (t -49,7) | +0,00 (t 0,3) | -0,52 (t -50,7) | 55,6% (35,2%) | 55% (n 815) |
| Blok2 (18 Ağu–16 Eyl) | 1899 (n 56964) | 1,6% (1,1%) | 16,4% | +2,6 ±1,8 pp | -0,50 (t -21,4) | -0,01 (t -0,2) | -0,51 (t -22,7) | 51,6% (33,2%) | 63% (n 1047) |
| Blok3 dışı (17 Eyl–1 Eki) | 2229 (n 33439) | 2,0% (1,5%) | 18,9% | +3,9 ±1,4 pp | -0,45 (t -12,6) | -0,00 (t -0,1) | -0,46 (t -12,8) | 54,6% (34,4%) | 61% (n 745) |

LUNATRY 17 Ekim tetik saatleri (00:00–04:00): 03:40, 03:50.

### st_cluster_flip (3 SuperTrend kümesi yukarı döndü)

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 1873 (n 28561) | 0,9% (1,1%) | 12,3% | -0,8 ±1,2 pp | -0,55 (t -17,3) | -0,03 (t -0,7) | -0,55 (t -17,3) | 32,0% (27,3%) | 47% (n 549) |
| TEST (29 Tem–1 Eki, fold B) | 1739 (n 113059) | 1,1% (1,2%) | 13,6% | -0,3 ±1,3 pp | -0,54 (t -36,1) | -0,06 (t -2,9) | -0,55 (t -36,4) | 34,4% (29,4%) | 46% (n 2533) |
| Blok1 (19 Tem–17 Ağu) | 1448 (n 41991) | 0,9% (0,9%) | 11,1% | -1,6 ±1,1 pp | -0,57 (t -52,4) | -0,06 (t -4,1) | -0,58 (t -54,3) | 31,6% (28,7%) | 43% (n 833) |
| Blok2 (18 Ağu–16 Eyl) | 1794 (n 53810) | 1,1% (1,1%) | 13,6% | -0,5 ±1,8 pp | -0,55 (t -21,4) | -0,06 (t -1,8) | -0,56 (t -22,2) | 35,1% (31,1%) | 47% (n 1156) |
| Blok3 dışı (17 Eyl–1 Eki) | 2053 (n 30792) | 1,4% (1,5%) | 15,8% | +1,1 ±1,6 pp | -0,50 (t -18,7) | -0,05 (t -1,3) | -0,51 (t -17,8) | 35,6% (28,1%) | 46% (n 794) |

LUNATRY 17 Ekim tetik saatleri (00:00–04:00): 00:25, 00:30.

### vortex_cross_up3 (VI+ > VI− kesişimi ≤3 bar)

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 2240 (n 34167) | 1,1% (1,1%) | 12,9% | +0,4 ±1,6 pp | -0,53 (t -23,1) | -0,01 (t -0,2) | -0,53 (t -22,3) | 43,0% (36,2%) | 62% (n 519) |
| TEST (29 Tem–1 Eki, fold B) | 2098 (n 136385) | 1,2% (1,2%) | 13,8% | +1,1 ±1,4 pp | -0,52 (t -33,4) | -0,03 (t -1,7) | -0,53 (t -34,7) | 43,7% (34,9%) | 61% (n 2356) |
| Blok1 (19 Tem–17 Ağu) | 1787 (n 51821) | 1,0% (0,9%) | 11,4% | +0,0 ±1,2 pp | -0,54 (t -61,2) | -0,03 (t -2,4) | -0,55 (t -59,7) | 45,0% (34,8%) | 57% (n 815) |
| Blok2 (18 Ağu–16 Eyl) | 2166 (n 64981) | 1,1% (1,1%) | 13,7% | +0,4 ±1,6 pp | -0,52 (t -22,5) | -0,04 (t -1,2) | -0,54 (t -23,6) | 42,5% (35,4%) | 63% (n 1048) |
| Blok3 dışı (17 Eyl–1 Eki) | 2435 (n 36527) | 1,5% (1,5%) | 16,1% | +3,1 ±1,8 pp | -0,48 (t -12,9) | -0,04 (t -0,7) | -0,50 (t -13,3) | 45,1% (34,1%) | 61% (n 731) |

LUNATRY 17 Ekim tetik saatleri (00:00–04:00): 00:00, 00:15, 00:20, 00:25, 00:30, 00:35, 03:20, 03:25, 03:30.

### fisher_turn (Fisher < −1 ve yukarı dönüyor)

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 2157 (n 32901) | 1,1% (1,1%) | 11,9% | -0,0 ±1,6 pp | -0,54 (t -18,3) | -0,02 (t -0,5) | -0,55 (t -18,7) | 39,3% (32,1%) | 65% (n 372) |
| TEST (29 Tem–1 Eki, fold B) | 1907 (n 123931) | 1,0% (1,2%) | 12,9% | +0,8 ±1,2 pp | -0,47 (t -29,5) | +0,01 (t 0,6) | -0,48 (t -30,6) | 34,1% (34,3%) | 65% (n 1548) |
| Blok1 (19 Tem–17 Ağu) | 1711 (n 49620) | 0,8% (0,9%) | 10,3% | -0,4 ±1,2 pp | -0,50 (t -53,7) | +0,01 (t 0,6) | -0,51 (t -51,1) | 35,6% (34,5%) | 62% (n 554) |
| Blok2 (18 Ağu–16 Eyl) | 1957 (n 58702) | 1,0% (1,1%) | 13,0% | +1,2 ±1,4 pp | -0,46 (t -21,0) | +0,03 (t 0,9) | -0,47 (t -22,3) | 33,1% (35,4%) | 67% (n 674) |
| Blok3 dışı (17 Eyl–1 Eki) | 2134 (n 32006) | 1,3% (1,5%) | 15,0% | +2,1 ±1,8 pp | -0,46 (t -10,2) | -0,01 (t -0,1) | -0,47 (t -10,5) | 35,2% (32,9%) | 67% (n 489) |

LUNATRY 17 Ekim tetik saatleri (00:00–04:00): 02:50.

### tsi_turn (TSI düşük bölgede sinyali yukarı kesti)

| dönem | sinyal/gün | 60 dk içinde olay (taban) | hit60@1,5 | şans farkı (null3) | net TP1,5/SL3 | sinyal − koşulsuz rastgele | net iz 1,0/0,8 | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|---|---|---|
| EĞİTİM (2–17 Eki, fold B) | 1003 (n 15299) | 0,8% (1,1%) | 11,5% | -0,8 ±2,1 pp | -0,57 (t -15,9) | -0,05 (t -1,1) | -0,57 (t -15,3) | 13,8% (18,0%) | 70% (n 119) |
| TEST (29 Tem–1 Eki, fold B) | 802 (n 52117) | 0,8% (1,2%) | 11,1% | -0,6 ±1,3 pp | -0,49 (t -21,2) | -0,00 (t -0,2) | -0,49 (t -22,0) | 10,8% (16,7%) | 65% (n 484) |
| Blok1 (19 Tem–17 Ağu) | 749 (n 21719) | 0,7% (0,9%) | 8,9% | -1,3 ±1,1 pp | -0,50 (t -47,1) | +0,00 (t 0,1) | -0,51 (t -54,4) | 13,8% (15,3%) | 68% (n 196) |
| Blok2 (18 Ağu–16 Eyl) | 846 (n 25389) | 0,7% (1,1%) | 11,3% | -1,4 ±1,5 pp | -0,48 (t -17,4) | +0,01 (t 0,3) | -0,49 (t -17,7) | 10,7% (17,0%) | 67% (n 222) |
| Blok3 dışı (17 Eyl–1 Eki) | 812 (n 12186) | 0,9% (1,5%) | 13,2% | +0,4 ±2,3 pp | -0,48 (t -6,1) | -0,03 (t -0,4) | -0,48 (t -6,4) | 9,2% (16,4%) | 65% (n 130) |

LUNATRY 17 Ekim tetik saatleri (00:00–04:00): YOK.

## 7. Özet ve karar tablosu

### 7a. TEST dönemi (29 Tem–1 Eki, örneklem dışı) — tüm sinyaller

| sinyal | sinyal/gün | 60 dk önden kesinlik (taban 1,2%) | hit60@1,5 şans farkı | net TP1,5/SL3 (koşulsuz rastgele -0,48) | t0'dan önce yakalama (sıfır) | HA'dan erken (ortak olay) |
|---|---|---|---|---|---|---|
| tek koşul (tüm aileler) | 64 | 11,2% (×9,5) | +12,7 ±1,8 pp | -0,52 (t -16,1) | 12,3% (2,5%) | 25% (n 619) |
| 2 koşul (tüm aileler) | 38 | 11,4% (×9,7) | +12,6 ±2,2 pp | -0,51 (t -11,0) | 7,7% (1,7%) | 14% (n 530) |
| 3 koşul (tüm aileler) | 26 | 12,1% (×10,3) | +8,7 ±2,5 pp | -0,56 (t -11,8) | 5,6% (1,0%) | 12% (n 366) |
| 2 koşul: osilatör + hareketli ortalama | 35 | 10,0% (×8,6) | +11,1 ±2,0 pp | -0,52 (t -11,5) | 6,4% (1,0%) | 19% (n 489) |
| 2 koşul: akış (hacim/CVD) + konum (VWAP/POC) | 74 | 7,2% (×6,2) | +6,3 ±2,2 pp | -0,48 (t -13,2) | 9,7% (2,3%) | 23% (n 1580) |
| 2 koşul: yapı (SMC) + trend + oynaklık | 56 | 9,6% (×8,2) | +13,2 ±1,8 pp | -0,53 (t -15,1) | 9,8% (1,8%) | 11% (n 885) |
| KONTROL tek koşul (yalnız MEVCUT 154 özellik) | 70 | 10,7% (×9,2) | +13,6 ±1,9 pp | -0,52 (t -17,0) | 13,1% (2,2%) | 19% (n 752) |
| KONTROL 2 koşul (yalnız MEVCUT 154 özellik) | 41 | 13,1% (×11,1) | +13,5 ±2,1 pp | -0,44 (t -12,2) | 9,0% (1,8%) | 16% (n 504) |
| KONTROL 3 koşul (yalnız MEVCUT 154 özellik) | 31 | 9,9% (×8,4) | +10,0 ±2,2 pp | -0,59 (t -10,8) | 5,6% (1,2%) | 8% (n 567) |
| sweep_reclaim (düşük süpürme + geri alma ≤3 bar) | 463 | 2,2% (×1,8) | +2,5 ±1,5 pp | -0,49 (t -26,2) | 15,9% (10,2%) | 56% (n 772) |
| sweep_eql (eşit diplerin süpürülmesi) | 40 | 2,1% (×1,8) | +1,7 ±1,7 pp | -0,53 (t -15,4) | 1,4% (1,1%) | 60% (n 72) |
| fvg_bull_tap (yükseliş FVG teması) | 3623 | 1,0% (×0,9) | +0,4 ±1,3 pp | -0,50 (t -36,3) | 62,4% (52,1%) | 54% (n 2630) |
| ob_tap (yükseliş OB teması) | 1212 | 1,5% (×1,2) | +1,3 ±1,2 pp | -0,48 (t -28,1) | 29,1% (23,2%) | 47% (n 1502) |
| acc_div_obv (OBV↑, fiyat yatay) | 2259 | 0,9% (×0,8) | +1,4 ±1,3 pp | -0,51 (t -36,6) | 34,5% (36,0%) | 64% (n 1673) |
| acc_div_cmf (CMF↑, fiyat yatay) | 2072 | 0,8% (×0,7) | +1,4 ±1,3 pp | -0,50 (t -34,8) | 29,2% (32,3%) | 62% (n 1365) |
| acc_div_cvd (CVD↑, fiyat yatay) | 2451 | 0,8% (×0,7) | +1,3 ±1,5 pp | -0,50 (t -35,4) | 33,2% (36,6%) | 71% (n 1437) |
| squeeze_release (sıkışma son 6 barda bitti) | 336 | 2,8% (×2,4) | +3,4 ±1,6 pp | -0,48 (t -27,7) | 16,6% (8,0%) | 50% (n 949) |
| chop_drop (choppiness yüksekten düşüyor) | 1863 | 1,7% (×1,4) | +2,1 ±1,5 pp | -0,48 (t -31,7) | 53,9% (34,5%) | 60% (n 2374) |
| st_cluster_flip (3 SuperTrend kümesi yukarı döndü) | 1739 | 1,1% (×1,0) | -0,3 ±1,3 pp | -0,54 (t -36,1) | 34,4% (29,4%) | 46% (n 2533) |
| vortex_cross_up3 (VI+ > VI− kesişimi ≤3 bar) | 2098 | 1,2% (×1,0) | +1,1 ±1,4 pp | -0,52 (t -33,4) | 43,7% (34,9%) | 61% (n 2356) |
| fisher_turn (Fisher < −1 ve yukarı dönüyor) | 1907 | 1,0% (×0,9) | +0,8 ±1,2 pp | -0,47 (t -29,5) | 34,1% (34,3%) | 65% (n 1548) |
| tsi_turn (TSI düşük bölgede sinyali yukarı kesti) | 802 | 0,8% (×0,6) | -0,6 ±1,3 pp | -0,49 (t -21,2) | 10,8% (16,7%) | 65% (n 484) |
| Hız Avcısı (canlı-benzeri, bölüm başı) | 235 | 6,9% (×5,8) | +5,2 ±2,0 pp | -0,53 (t -28,9) | 27,9% (6,3%) | 0% (n 2832) |

### 7b. Üç bağımsız örneklem-dışı blokta (Blok1, Blok2, Blok3-dışı) koşulun sağlandığı blok sayısı (3/3 = her blokta)

| sinyal | şans farkı > 0 | şans farkı > HA'nınki | net(TP1,5) > 0 | net(TP1,5) > koşulsuz rastgele | trailing net > 0 | t0'dan önce yakalama > sıfır×1,5 | 60 dk önden kesinlik ≥ HA'nınki | HA'dan erken (ortak olayların >%50'si) | KANITLI ERKEN UYARI (6. ve 8. birlikte) |
|---|---|---|---|---|---|---|---|---|---|
| tek koşul (tüm aileler) | 3/3 ✓ | 3/3 ✓ | 0/3 | 1/3 | 0/3 | 3/3 ✓ | 3/3 ✓ | 0/3 | 0/3 |
| 2 koşul (tüm aileler) | 3/3 ✓ | 3/3 ✓ | 0/3 | 2/3 | 0/3 | 3/3 ✓ | 3/3 ✓ | 0/3 | 0/3 |
| 3 koşul (tüm aileler) | 3/3 ✓ | 2/3 | 0/3 | 0/3 | 0/3 | 3/3 ✓ | 3/3 ✓ | 0/3 | 0/3 |
| 2 koşul: osilatör + hareketli ortalama | 3/3 ✓ | 3/3 ✓ | 0/3 | 1/3 | 0/3 | 3/3 ✓ | 3/3 ✓ | 0/3 | 0/3 |
| 2 koşul: akış (hacim/CVD) + konum (VWAP/POC) | 3/3 ✓ | 2/3 | 0/3 | 2/3 | 0/3 | 3/3 ✓ | 2/3 | 0/3 | 0/3 |
| 2 koşul: yapı (SMC) + trend + oynaklık | 3/3 ✓ | 3/3 ✓ | 0/3 | 1/3 | 0/3 | 3/3 ✓ | 3/3 ✓ | 0/3 | 0/3 |
| KONTROL tek koşul (yalnız MEVCUT 154 özellik) | 3/3 ✓ | 3/3 ✓ | 0/3 | 1/3 | 0/3 | 3/3 ✓ | 3/3 ✓ | 0/3 | 0/3 |
| KONTROL 2 koşul (yalnız MEVCUT 154 özellik) | 3/3 ✓ | 3/3 ✓ | 0/3 | 3/3 ✓ | 0/3 | 3/3 ✓ | 3/3 ✓ | 0/3 | 0/3 |
| KONTROL 3 koşul (yalnız MEVCUT 154 özellik) | 3/3 ✓ | 3/3 ✓ | 0/3 | 0/3 | 0/3 | 3/3 ✓ | 3/3 ✓ | 0/3 | 0/3 |
| sweep_reclaim (düşük süpürme + geri alma ≤3 bar) | 2/3 | 0/3 | 0/3 | 1/3 | 0/3 | 1/3 | 0/3 | 3/3 ✓ | 1/3 |
| sweep_eql (eşit diplerin süpürülmesi) | 3/3 ✓ | 0/3 | 0/3 | 0/3 | 0/3 | 2/3 | 0/3 | 2/3 | 2/3 |
| fvg_bull_tap (yükseliş FVG teması) | 2/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 ✓ | 0/3 |
| ob_tap (yükseliş OB teması) | 2/3 | 0/3 | 0/3 | 2/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| acc_div_obv (OBV↑, fiyat yatay) | 2/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 ✓ | 0/3 |
| acc_div_cmf (CMF↑, fiyat yatay) | 2/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 ✓ | 0/3 |
| acc_div_cvd (CVD↑, fiyat yatay) | 2/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 ✓ | 0/3 |
| squeeze_release (sıkışma son 6 barda bitti) | 3/3 ✓ | 0/3 | 0/3 | 2/3 | 0/3 | 3/3 ✓ | 0/3 | 2/3 | 2/3 |
| chop_drop (choppiness yüksekten düşüyor) | 3/3 ✓ | 0/3 | 0/3 | 1/3 | 0/3 | 3/3 ✓ | 0/3 | 3/3 ✓ | 3/3 ✓ |
| st_cluster_flip (3 SuperTrend kümesi yukarı döndü) | 1/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| vortex_cross_up3 (VI+ > VI− kesişimi ≤3 bar) | 3/3 ✓ | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 ✓ | 0/3 |
| fisher_turn (Fisher < −1 ve yukarı dönüyor) | 2/3 | 0/3 | 0/3 | 2/3 | 0/3 | 0/3 | 0/3 | 3/3 ✓ | 0/3 |
| tsi_turn (TSI düşük bölgede sinyali yukarı kesti) | 1/3 | 0/3 | 0/3 | 2/3 | 0/3 | 0/3 | 0/3 | 3/3 ✓ | 0/3 |
| Hız Avcısı (canlı-benzeri, bölüm başı) | 3/3 ✓ | 0/3 | 0/3 | 0/3 | 0/3 | 3/3 ✓ | 3/3 ✓ | 0/3 | 0/3 |


## 8. Sınırlar ve dürüstlük notları

1. **Tek 90 günlük rejim, bağımsız deney sayısı küçük.** Blok1/Blok2/Blok3-dışı üç bağımsız örneklem-dışı deneydir; TEST (29 Tem–1 Eki) bunların birleşimiyle örtüşür. Olaylar günlere kümelenir (geniş yükseliş günleri); grup-içi permütasyon p/FWER/q aynı gün dalgalarını (gruplar arası bağımlılığı) hesaba katmaz → q-değerleri iyimser; bu yüzden 3 blokta işaret tutarlılığı ve dip-kontrollü AUC ayrıca verildi. 1000 permütasyonla p ≥ 1/1001, bu yüzden güçlü özelliklerin q'su tabanda (0,001–0,003) birleşiyor; sıralama |AUC−½| ile yapıldı.
2. **Olay tanımı geleceğe bağlıdır** (≥ %4 kapanış kazancı, %70 yeşil, geri çekilme ≤ %1,5, ilk mum yeşil). t0 anlık görüntüsü "ilk yeşil mumdan hemen önce"dir; t0'daki güçlü AUC'ler olayın başladığı küçük düşüşün izidir, canlıda t0'da "bu düşüş olay olacak" demek mümkün değil. Gerçek erken-uyarı testi t0−10/t0−15 ve "60 dk içinde olay" etiketli sinyal süpürmesidir.
3. **Dip kontrolü yaklaşık:** artık AUC, 19 mevcut özelliğe doğrusal regresyonla alındı. Doğrusal olmayan dip/aralık ilişkileri (osilatörlerin aralık-içi konumu) tam çıkarılamaz; osilatörlerdeki 0,38–0,46 artık AUC kısmen bunun kalıntısıdır. Çok değişkenli HistGradientBoosting testi bu sınırı aşan bağımsız bir kontroldür.
4. **Parametreler ayarlanmadı.** Her gösterge klasik varsayılanlarıyla (RSI-benzeri 14, TSI 25/13, KST 10/15/20/30, SuperTrend 10/3 + (11,2),(12,3),(10,1), Ichimoku 9/26/52, SMC: fraktal 3/3, FVG ≥ 0,25·ATR, OB geriye bakış 5 bar, yer değiştirme 1,5·ATR, süpürme geri alma ≤ 3 bar) ve tek zaman diliminde (1m/5m/15m) denendi. SMC kavramları mekanik yaklaşıklıklardır (diskresyoner "order block"/"likidite" yorumlarını birebir temsil etmez). 30 dk / 1 sa / 4 sa grafikler, çok-zaman-dilimi onayı ve parametre taraması denenmedi; rehberin birçok aracı daha uzun zaman dilimleri için tasarlanmıştır.
5. **Sinyal seçimi:** açgözlü AND, eşikler pozitif dağılımın kuantillerinde (9 düzey × 2 yön), üst 50–60 özellik, 15 günlük eğitim (828 olay, 10 665 pozitif bar; pozitifler bar düzeyinde ardışık/bağımlı). Seçilen adaylar oynaklık/yükselen-rejim filtreleri çıktı; KONTROL adayları (aynı yöntem, yalnız mevcut özellikler) eşdeğer → seçim yöntemi rehber göstergelerinin katkısını izole ediyor, ama farklı bir arama (ör. ağaç toplulukları) farklı sonuç verebilir. Eğitim etiketi 60 dk-önden olay olduğundan seçilen koşullar t0'a yakın ve sonrasındaki barları da kapsar; doğrudan "t0'dan ≥ 30 dk önce" etiketiyle ayrı bir seçim yapılmadı.
6. **Karşılaştırma HA ile eşit sinyal oranında değildir:** HA günde ~235 bölüm, adaylar 22–113, rehber fikirleri 40–3 600. Kesinlik ve kapsama arasındaki ödünleşim nedeniyle "HA'dan daha isabetli" ve "HA'dan daha az kapsayıcı" aynı anda doğru. Doygun sinyallerde (günde yüzlerce–binlerce) "rastgele giriş" tabanı (≥ 2 sa uzaklık kuralı) kalan sakin anlara sapar; bu yüzden ana taban olarak KOŞULSUZ rastgele giriş (150 bin tekdüze geçerli an) ve sayı-eşleşmiş serbest yerleştirme (olay yakalama sıfırı) kullanıldı. "HA'dan erken" ölçüsü doygun sinyallerde yapay biçimde yüksektir (yukarıda açıklandı); bu yüzden "kanıtlı erken uyarı" ölçütü iki koşulu birlikte ister. HA için `ha_ticks` (canlı-benzeri: rank ≤ 10, aşırı alımda değil) kullanıldı; HA metrikleri bölüm başı satırlardandır.
7. **`exit_sim` varsayımları kötümser/sabit:** 60 sn gecikme, %0,15 kayma, bacak başına %0,1125; giriş 1 dk barın açılışı; çıkış TP1,5 / TP2,0 / izleyen 1,0-0,8 (SL 3, T60). Limit emirle (maker) doluş, sinyale özel çıkış yapısı ya da daha az kayma denenmedi; önceki çalışmalarda (`docs/CIKIS_YAPISI_SIMULASYONU_2026-10-17.md`, `docs/STOCHRSI_LIMIT_GIRIS_2026-10-17.md`) limit giriş ve çıkış yapıları iyimser doluşta bile net-pozitif hücre vermedi.
8. **Şans farkı (null3)** yalnız son 30 dk aralığı/getirisi ve ±1 sa saat dilimini eşler; 24 sa oynaklık/momentum rejimini eşlemez. Oynak/yükselen rejim adaylarında hit60 farkının büyük, netin sıfır olmasının nedeni budur (aynı rejim hem MFE'yi hem MAE'yi büyütür).
9. **Veri:** HA verisi (`rescan_90g_nogate.jsonl`) 16 Ekim 23:55'te biter; LUNATRY 17 Ekim satırı için HA karşılaştırması yoktur. 1m özellikleri 304 likit sembol için vardır (2 sembol 1m yok → NaN, geçerli an dışı). 5m'nin %33'ü sıfır hacimli doldurulmuş satırdır; POC/VWAP/akış göstergeleri bu satırlarda zayıftır. Emir defteri / funding / açık pozisyon (OI) kanalları bu çalışmada yoktur; CVD yalnız taker kline alanlarından türetildi (mevcut `tk_share*` ile affin eşdeğer; CVD'nin yeni olan kısmı fiyatla ıraksama ve uzun ufuk).
10. **Çoklu test:** 401 özellik × 4 ofset + 99 fikir-satırı (33 fikir × 3 zaman dilimi) × 4 ofset + 9 aday × 5 dönem × 3 çıkış. FWER yalnız özellik ailesi içindedir; aday/sinyal tablosunda düzeltme yoktur (ama sonuç zaten olumsuzdur, yani çoklu test sonucu aşağı değil yukarı yanlı etkiler).

**Yeniden üretim:** `PYTHONIOENCODING=utf-8 DATABASE_URL=… .venv/Scripts/python.exe scripts/indearly_study.py --cache-dir <p90cache> --fx-dir <scratch>/indearly --out-dir work/indearly --stages feat,snap,rank,multi,select,sweep,eval,report` (önbellek `pattern90_study.py` ile üretilir; özellik aşaması 3 işçiyle ≈ 6 dk, sıralama ≈ 4 dk, eval ≈ 9 dk). Testler: `tests/test_indicators_ext.py` (31 test; el hesaplı fixture + nedensellik + kesme eşitliği).
