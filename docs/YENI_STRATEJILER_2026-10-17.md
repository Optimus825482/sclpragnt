# Yeni Erken-Giriş Dedektörleri — Geriye Dönük Ölçüm (2026-10-17)

**Bağlam:** "Merdiven" prototipi (`docs/REJIM_KALKANI_ANALIZI_2026-10-17.md` §4) Hız Avcısı'na (HA) değer katmadı:
tüm hücreler net negatif, şansa göre fark +2–4 pp, HA'ya öncülük medyanı 5–10 dk. Bu çalışma **dört farklı fikri** aynı
ölçüm düzeneğiyle dener. Canlı kod değişmedi; yalnız yeni dosyalar:

- `backend/app/rescan/strategies.py` (saf numpy dedektörler) · `backend/tests/test_rescan_strategies.py` (8 test, geçiyor)
- `backend/scripts/strategy_rescan.py` (ızgara ölçümü)
- Ham çıktı: `backend/work/strategy_rescan.md|json|log` (SL −3), `backend/work/strategy_rescan_sl1.5.md|json|log` (SL −1,5
  duyarlılık), `backend/work/lunatry_1m_1017.json` (LUNATRY 1 dk mumları, Binance public kline).

## 1. Yöntem

- **Veri:** `historical_candles` 5m (306 sembol, 26 Eylül 01:55 – 17 Ekim 02:20) ve 1m (likit 24s-quote'u ≥ 5M TRY olan
  semboller, 16 Ekim ~20:00'de bitiyor). Dedektörler ilk 25–26 saat ısınma/likidite penceresi nedeniyle **27 Eylül
  ~03:00'dan** itibaren sinyal verir → etkin pencere 19,7–19,9 gün. Likidite: 24s quote ≥ 5M TRY, sembol başına 60 dk soğuma,
  sinyal anı = bar kapanışı, giriş = o barın kapanışı (gecikmesiz).
- **Dedektörler** (hücre sayısı ≤ 4 / dedektör):
  1. `ema_fan_5m` — EMA7>EMA20>EMA99 (5m) *yeni* açıldı (k+1 bar önce açık değil), EMA7 son k barda yukarı (k∈{2,3}),
     6 barlık kazanç [g_min∈{0,8; 1,5}, 4] %, RSI14 ≤ 70.
  2. `breakout_compress_5m` — Bollinger(20) genişliğinin son 24 bar ortalaması son 100 barın alt üçte birinde (sıkışma),
     kapanış önceki `hi_lb` ∈ {24, 48} bar zirvesinin üstünde, hacim ≥ vol_min ∈ {1,5; 2,5} × önceki 20 bar ort., RSI ≤ 75,
     3 barlık kazanç ≤ %4.
  3. `rs_vs_btc_5m` — 30 dk getiri − BTCTRY 30 dk getiri ≥ x ∈ {1,0; 1,5} puan, sembol 30 dk getirisi > 0, BTC 30 dk ≤ +%0,2,
     son 3 bar yükselen dip, hacim ≥ vol_min ∈ {1,0; 1,5} × önceki 20 bar, 60 dk kazancı ≤ %5.
  4. `persist_1m` — 1 dk kapanış > EMA9 > EMA21 en az M ∈ {8, 12} dk kesintisiz, EMA21 10 dk eğimi > 0, M dk kazancı
     [g_min ∈ {0,6; 1,0}, 3] %, son M dk dakika-başı hacim ≥ 1,2 × önceki 60 dk, RSI14(1m) ≤ 75.
  5. `persist_1m_5mgrid` — **duyarlılık varyantı**: aynı kural, yalnız 5 dk sınırında kapanan 1m barlarda (neden §3.4'te).
- **Sonuç ölçütleri** (`ladder_rescan.py` ile aynı): TP 1,5 / 2,0, SL −3, maliyet 0,225, ufuk 60 dk (TP/SL aynı barda
  ise SL önce — kötümser). **Trailing varyantı:** tetik %1,0 / iz %0,8 / SL −3 (zirve önceki barlardan, kötümser).
  Şans tabanı: `compute_chance` null3 (aynı sembol, saat dilimi, son 30 dk aralık ve getiri eşleşmiş rastgele anlar), her
  hücrede ≥ 2.000 (çoğunda 3.000) sinyal örneği. HA karşılaştırma kümesi: rescan canlı-benzeri (rank ≤ 10, aşırı alım kapısı
  geçen) 14.390 satır / 4.578 bölüm.
- **Koşulsuz trailing referansı:** likit sembollerde rastgele 5m kapanışlarında (n = 20.000) trailing neti **−0,18**
  (kazanan payı %40). Şans tabanı yalnız sabit TP için var; trailing için sinyal bu −0,18 ile (momentum eşleşmesiz) kıyaslanır.
- **Kıyas çıtası:** HA'nın şansa göre farkı +3,8 / +4,4 pp (REJIM_KALKANI §2), merdiven +2,4–4,1 pp.

## 2. Sonuç tabloları (SL −3; hit60@1,5 / net60 / trailing / şans farkı)

Net'ler % cinsinden, maliyet düşülmüş. t istatistikleri tüm net'lerde −10 ile −23 arası (sıfırdan belirgin negatif), tam
tablo `work/strategy_rescan.md`'de.

### 2.1 `ema_fan_5m`

| hücre | sinyal (/gün) | hit60@1,5 | net@1,5 | net@2,0 | trailing net | **hit−şans** | HA 90 dk içinde geldi · öncülük medyan | HA kapsama | yeni yakalama (n · hit) |
|---|---|---|---|---|---|---|---|---|---|
| k=2, g=0,8 | 6.501 (327) | %22,8 | −0,33 | −0,32 | −0,21 | +1,0 pp | %19 · 15 dk | %25 | 4.892 · %12,9 |
| k=2, g=1,5 | 2.237 (113) | %34,9 | −0,38 | −0,36 | −0,16 | **+2,9 pp** | %39 · 10 dk | %17 | 1.118 · %18,2 |
| k=3, g=0,8 | 6.747 (339) | %22,7 | −0,32 | −0,31 | −0,21 | +0,9 pp | %18 · 20 dk | %24 | 5.137 · %13,1 |
| k=3, g=1,5 | 2.441 (123) | %34,0 | −0,37 | −0,36 | −0,17 | +2,2 pp | %37 · 10 dk | %17 | 1.275 · %17,8 |

### 2.2 `breakout_compress_5m`

| hücre | sinyal (/gün) | hit60@1,5 | net@1,5 | net@2,0 | trailing net | **hit−şans** | HA geldi · öncülük | HA kapsama | yeni yakalama |
|---|---|---|---|---|---|---|---|---|---|
| vol 1,5 · hi 24 | 5.108 (257) | %14,2 | −0,31 | −0,31 | −0,24 | −1,3 pp | %10 · 10 dk | %11 | 4.557 · %9,4 |
| vol 1,5 · hi 48 | 2.906 (146) | %15,6 | −0,31 | −0,30 | −0,22 | −0,4 pp | %11 · 10 dk | %7 | 2.564 · %10,5 |
| vol 2,5 · hi 24 | 3.855 (194) | %14,6 | −0,31 | −0,31 | −0,23 | −1,2 pp | %11 · 10 dk | %9 | 3.411 · %9,3 |
| vol 2,5 · hi 48 | 2.214 (111) | %15,6 | −0,33 | −0,33 | −0,23 | −1,0 pp | %12 · 10 dk | %6 | 1.932 · %10,0 |

Sıkışma kırılımı bu evrende (TRY çiftleri, 5m) **şansın altında**: hit60 %14–16, şans %15–17.

### 2.3 `rs_vs_btc_5m`

| hücre | sinyal (/gün) | hit60@1,5 | net@1,5 | net@2,0 | trailing net | **hit−şans** | HA geldi · öncülük | HA kapsama | yeni yakalama |
|---|---|---|---|---|---|---|---|---|---|
| x 1,0 · vol 1,0 | 7.702 (387) | %29,5 | −0,34 | −0,32 | −0,17 | +0,7 pp | %31 · 5 dk | %45 | 4.969 · %16,2 |
| x 1,0 · vol 1,5 | 6.410 (322) | %29,4 | −0,35 | −0,33 | −0,17 | +1,9 pp | %31 · 5 dk | %38 | 4.124 · %15,7 |
| x 1,5 · vol 1,0 | 4.481 (225) | %36,8 | −0,39 | −0,37 | −0,17 | **+2,4 pp** | %45 · 5 dk | %39 | 2.163 · %18,6 |
| x 1,5 · vol 1,5 | 3.847 (194) | %36,0 | −0,41 | −0,39 | −0,18 | +0,7 pp | %45 · 5 dk | %33 | 1.864 · %17,5 |

### 2.4 `persist_1m` (1 dk, her dakikada değerlendirilir)

| hücre | sinyal (/gün) | hit60@1,5 | net@1,5 | net@2,0 | trailing net | **hit−şans** | HA geldi · öncülük | HA kapsama | yeni yakalama |
|---|---|---|---|---|---|---|---|---|---|
| M 8 · g 0,6 | 9.527 (484) | %30,9 | −0,32 | −0,32 | −0,17 | +3,5 pp | %30 · 5 dk | %56 | 6.294 · %18,1 |
| M 8 · g 1,0 | 4.626 (235) | %40,6 | −0,36 | −0,37 | −0,13 | **+7,1 pp (\*)** | %53 · 5 dk | %48 | 1.983 · %22,0 |
| M 12 · g 0,6 | 7.947 (404) | %27,8 | −0,32 | −0,32 | −0,18 | +1,3 pp | %26 · 5 dk | %39 | 5.600 · %17,2 |
| M 12 · g 1,0 | 4.418 (225) | %35,6 | −0,37 | −0,38 | −0,18 | +4,0 pp (\*) | %42 · 4 dk | %35 | 2.338 · %21,8 |

(\*) Bu iki şans farkı **şişmiş**; §3.4'e bakın.

### 2.5 `persist_1m_5mgrid` (aynı kural, yalnız 5 dk sınırında; giriş/şans tabanı 5m deposuyla birebir hizalı)

| hücre | sinyal (/gün) | hit60@1,5 | net@1,5 | net@2,0 | trailing net | **hit−şans** | HA geldi · öncülük | HA kapsama | yeni yakalama |
|---|---|---|---|---|---|---|---|---|---|
| M 8 · g 0,6 | 4.559 (232) | %33,8 | −0,36 | −0,34 | −0,16 | +2,4 pp | %39 · 5 dk | %31 | 2.545 · %18,2 |
| M 8 · g 1,0 | 2.048 (104) | %43,2 | −0,45 | −0,44 | −0,13 | +2,8 pp | %63 · 5 dk | %22 | 641 · %22,0 |
| M 12 · g 0,6 | 4.150 (211) | %29,6 | −0,33 | −0,32 | −0,17 | +0,2 pp | %28 · 5 dk | %21 | 2.686 · %17,2 |
| M 12 · g 1,0 | 2.145 (109) | %39,3 | −0,34 | −0,34 | −0,10 | **+3,9 pp** | %46 · 5 dk | %17 | 960 · %23,8 |

## 3. Yorum

### 3.1 Kâr var mı? Hayır.
20 hücrenin **hiçbirinde net pozitif yok**: sabit TP/SL −0,31 … −0,45 %/işlem (t −10 … −23). Trailing çıkış sabit TP'den
daha az kötü (−0,10 … −0,24) ama koşulsuz rastgele-giriş trailing referansı da −0,18; yani trailing'in "iyileşmesi" büyük
ölçüde çıkış kuralının kendisinden, sinyalden değil. Trailing'de referansın belirgin üstündeki tek hücreler `persist_1m_5mgrid`
(−0,10 … −0,13, t −2,4 … −2,5: sıfırdan hâlâ ayırt edilebilir negatif) ve `persist_1m` g=1,0 (−0,13). SL'yi −1,5'e çekmek
(simetrik risk, `work/strategy_rescan_sl1.5.md`) sabit-TP net'ini −0,28 … −0,36'ya getiriyor, işareti değiştirmiyor; en iyi
hücre `persist_1m_5mgrid` M=8,g=1,0 trailing −0,06 (t −1,2): sıfırla ayırt edilemez ama pozitif de değil.

### 3.2 HA'nın +4 pp çıtasını geçen var mı? Sağlam biçimde hayır.
- `ema_fan_5m`: en iyi +2,9 pp (g=1,5); düşük eşikte (g=0,8, günde 330 sinyal) +1 pp: şansla ayırt edilemez.
- `breakout_compress_5m`: şansın **altında** (−0,4 … −1,3 pp). Fikir bu evrende çalışmıyor.
- `rs_vs_btc_5m`: en iyi +2,4 pp (x=1,5); ikinci yarı örnekte işaret değiştiriyor (§4).
- `persist_1m`: ham tabloda +7,1 pp ile öne çıkıyor ama bu bir **ölçüm artefaktı** (§3.4); hizalı sürümde +2,8 pp. En iyi
  hizalı hücre (M=12,g=1,0) **+3,9 pp** — HA'nın +3,8/+4,4 pp'ine eşit, üstü değil; 109 sinyal/gün.

### 3.3 Erkenlik
HA adayı sinyalden sonra 90 dk içinde geliyorsa öncülük medyanı hep **4–20 dk** (çoğu 5–10): "yeni bir dedektör HA'dan 20–25 dk
erken" iddiası bu verilerle de desteklenmiyor. HA bölümlerinin kapsaması dedektöre göre %6–%56 (persist_1m %35–56, ama
günde 225–484 sinyal — kapsama büyük ölçüde sinyal bolluğundan). "Yeni yakalama" kümeleri (±90 dk'da HA yok) HA'dan **zayıf**:
hit %9–24, net −0,33 … −0,65.

### 3.4 Şişen şans farkı: 1 dk sinyallerde bağlam kayması
`persist_1m` sinyalleri 5m bar içinde herhangi bir dakikada ateşliyor; şans tabanı ve çıkış değerlendirmesi 5m deposuyla
yapılıyor (`compute_chance` bağlamı "son kapanmış 5m bar" olarak eşliyor). Sinyalde son 8–12 dakikanın hareketi zaten
içeride, eşleşen rastgele anlarda ise yok → fark yapay büyüyor. Aynı kural yalnız 5 dk sınırında değerlendirilince (§2.5)
M=8,g=1,0 hücresi **+7,1 → +2,8 pp**, M=12,g=1,0 **+4,0 → +3,9 pp**, M=8,g=0,6 **+3,5 → +2,4 pp**. Yani ham tablodaki
"+7 pp" güvenilmez; hizalı sayılar esas alınmalı. (Bu 1 dk akışta gerçek bir üstünlük olmadığını kanıtlamaz, yalnız bu düzenekle
ölçülemediğini gösterir; 1 dk deposuyla eşleşmiş bir şans tabanı kurmak ayrı iş.)

### 3.5 BTC kalkanı kırılımı
Üç dedektörde (ema_fan, persist_1m, persist_1m_5mgrid) kalkan AÇIK anların net'i KAPALI'dan **daha iyi** (örn. ema_fan en iyi
−0,29 vs −0,37; persist_1m M=8,g=1,0 −0,33 vs −0,41; persist_1m_5mgrid M=12,g=1,0 trailing −0,01 vs −0,22); `rs_vs_btc_5m`
(−0,36 AÇIK vs −0,30 KAPALI) ve `breakout_compress_5m` (−0,33 vs −0,28) tersi, farklar küçük. Önceki rejim-kalkanı
bulgusuyla uyumlu: BTC EMA200 altı olması altcoin momentum sinyallerini genel olarak kötüleştirmiyor.

## 4. Yarı-örnek kontrolü (böl: 6 Ekim; ilk ~9–10 gün / son ~11 gün)

İki en iyi hücre (net, şans-farkı) için; hit60@1,5 / net / trailing / şans farkı.

| dedektör · hücre | ilk yarı | ikinci yarı | karar |
|---|---|---|---|
| ema_fan k=3,g=0,8 (net en iyi) | n=3.295 · %22,1 · −0,31 · −0,21 · **+2,3 pp** | n=3.452 · %23,2 · −0,34 · −0,21 · **+0,9 pp** | zayıf, azalıyor |
| ema_fan k=2,g=1,5 (fark en iyi) | n=1.057 · %33,2 · −0,35 · −0,17 · +2,6 pp | n=1.180 · %36,4 · −0,40 · −0,16 · +3,2 pp | kararlı ama +3 pp (HA altı) |
| breakout vol 1,5 · hi 48 | n=1.375 · %16,7 · −0,23 · −0,16 · +1,4 pp | n=1.531 · %14,5 · −0,37 · −0,28 · **−2,2 pp** | işaret değiştiriyor |
| rs_vs_btc x 1,0 · vol 1,0 (net en iyi) | n=3.663 · %29,7 · −0,31 · −0,16 · +3,0 pp | n=4.039 · %29,3 · −0,36 · −0,18 · **−0,8 pp** | işaret değiştiriyor |
| rs_vs_btc x 1,5 · vol 1,0 (fark en iyi) | n=2.079 · %38,0 · −0,33 · −0,10 · +3,7 pp | n=2.402 · %35,7 · −0,44 · −0,23 · **−1,1 pp** | işaret değiştiriyor → aşırı uyum |
| persist_1m M=12,g=0,6 (net en iyi) | n=3.807 · %26,7 · −0,32 · −0,21 · +2,2 pp | n=4.140 · %28,9 · −0,31 · −0,16 · +1,5 pp | kararlı, küçük |
| persist_1m M=8,g=1,0 (fark en iyi, **şişmiş**) | n=2.119 · %38,8 · −0,39 · −0,16 · +6,5 pp | n=2.507 · %42,0 · −0,34 · −0,10 · +8,0 pp | iki yarıda da tutarlı — artefakt sistematik |
| persist_1m_5mgrid M=12,g=0,6 (net en iyi) | n=1.965 · %29,2 · −0,30 · −0,18 · +1,8 pp | n=2.185 · %29,9 · −0,35 · −0,16 · −1,7 pp | işaret değiştiriyor |
| persist_1m_5mgrid M=12,g=1,0 (fark en iyi) | n=994 · %39,3 · −0,31 · −0,13 · **+4,3 pp** | n=1.151 · %39,3 · −0,37 · −0,07 · **+2,5 pp** | iki yarıda pozitif, ~+3,5 pp |

Özet: `rs_vs_btc_5m` ve `breakout_compress_5m`'in "iyi" görünen hücreleri ikinci yarıda sıfırın altına düşüyor (aşırı uyum).
Tutarlı kalanlar `ema_fan` g=1,5, `persist_1m` ve `persist_1m_5mgrid` M=12,g=1,0 — hepsi +2,5 … +4,3 pp bandında,
yani HA ile aynı büyüklükte; ikisi de net negatif.

## 5. LUNATRY sağlama (17 Ekim 01:05–01:55; bar kapanış zamanı)

LUNATRY 01:05 kapanışı **2,176**; 01:05–02:20 zirvesi **2,398 (+%10,2)**; 01:05'te 24 sa quote hacmi 9,12M TRY (5M filtresini
geçiyor). Hız Avcısı bu yükselişte bildirim üretmedi (kalkan + MFI 96).

| dedektör | ateşledi mi | saat · giriş · girişten sonraki zirve | 01:05 kapanışına göre giriş gecikmesi |
|---|---|---|---|
| ema_fan_5m (4 hücrenin hepsi) | **evet** | **01:20** · 2,2210 · +%8,0 | +%2,1 |
| rs_vs_btc_5m (4 hücrenin hepsi) | evet | 01:45 · 2,2600 · +%6,1 | +%3,9 |
| persist_1m (M=8..12) | evet | 01:24–01:27 · 2,2250–2,2300 · +%7,5–7,8 | +%2,3–2,5 |
| persist_1m_5mgrid | evet | 01:25–01:50 (M=8,g=0,6 01:25 · 2,2240; M=12,g=1,0 01:50 · 2,2790) | +%2,2–4,7 |
| breakout_compress_5m | **hayır** (4 hücre) | — | — |

(persist_1m için LUNATRY 1m mumları DB'de olmadığından Binance public kline API'den alındı: `work/lunatry_1m_1017.json`.)
Tek örnek ve bu örnek tasarım aşamasında görülmüş durumda — **geriye dönük uydurma riski yüksek**; yalnızca "dedektör
mantığı bu hareketi 15–20 dk içinde, yükselişin ilk %2–4'ünde görüyor" bilgisini verir. Aynı dedektörlerin bu tür her
harekette HA'dan iyi olduğu §2–4'te gösterilemedi.

## 6. Sonuç

1. **Dört fikrin hiçbiri net pozitif değil.** Sabit TP/SL'de tüm hücreler −0,31 … −0,45 %/işlem; SL −1,5'te de aynı işaret;
   trailing çıkışta −0,06 … −0,24 (rastgele giriş referansı −0,18).
2. **HA'nın +4 pp şans farkını sağlam biçimde geçen yok.** En iyi tutarlı hücreler `ema_fan_5m` g=1,5 (+2,2 … +2,9 pp) ve
   `persist_1m_5mgrid` M=12,g=1,0 (+3,9 pp; yarılar +4,3/+2,5) — HA ile aynı bantta. `persist_1m`'in ham +7,1 pp'si bağlam
   kayması artefaktı. `breakout_compress_5m` şansın altında; `rs_vs_btc_5m` ikinci yarıda çöküyor.
3. **Erkenlik kazancı yok:** HA'ya öncülük medyanı 4–20 dk, çoğu 5–10 dk; "yeni yakalama" kümeleri HA'dan zayıf.
4. **Öneri: hiçbirini canlıya almayın.** `ema_fan_5m` ve `persist_1m` LUNATRY tipi hareketleri 15–25 dk içinde görüyor, fakat
   bunu kuralı kârlı yapacak biçimde genelleştiremedik. Bildirim kalitesini artırmak yerine bildirimi **bilgi rozeti** olarak
   (ör. "yükseliş yelpazesi" etiketi) kullanmak ancak aşağıdaki testten sonra düşünülebilir.

## 7. Sırada ne denenebilir

1. **Bayrak olarak değerlendirme (en ucuz, en umut verici):** `persist_1m_5mgrid` (M=12,g=1,0) / `ema_fan` g=1,5 sinyalini
   bağımsız bildirim yerine HA adaylarının **özelliği** yap: HA adayları içinde bu bayrağı taşıyanların hit60'ı taşımayanlardan
   anlamlı yüksek mi? (HA ile örtüşme %17–56: yeterli örneklem var.) Yüksekse HA skoruna ek puan.
2. **Eşleşmiş trailing şans tabanı:** trailing çıkış için null3 benzeri bir taban (şimdi yalnız koşulsuz −0,18 var) ve 1 dk
   deposu üzerinde 1 dk eşleşmeli şans tabanı kurup `persist_1m`'in gerçek farkını bağlam kayması olmadan ölç.
3. **Hedef/stop yapısı:** TP 1,5 / SL −3 yapısal olarak düşmanca (başa baş için ~%72 isabet gerekir; gözlenen %14–43). ATR'ye
   göre ölçekli, sembole özel hedef ve R:R ≥ 1 (TP 2 / SL 1,5) ile aynı sinyalleri yeniden ölç; kısa ufuk (15 dk) da denenmeli.
4. **Daha uzun örneklem:** tüm bulgular tek 20 günlük dönemden; 60+ gün 5m geçmiş (harici kline indirme) ile yarı-örnek
   doğrulaması gerekir. Rejim-bağımlılığı (BTC EMA200 altı günlerin %57'si) tek dönem riskini artırıyor.
5. **Emir defteri / taker alış oranı:** mum verisi yalnız fiyat+hacim; asıl "kalıcı alım" izi taker-buy hacminde (kline'ın
   ek alanları) ve defter dengesizliğinde olabilir. `historical_candles` bu alanları tutmuyor; tutulursa 1. madde için
   güçlü bir aday olur.

**Sınırlar:** 20 günlük tek dönem; her dedektör için 4 hücre (toplam 20) — en iyi hücre seçimi iyimserlik taşır (yarı-örnek
bunu gösteriyor); giriş gecikmesiz, komisyon sabit; çıkış değerlendirmesi 5m mum içi sırayı kötümser (SL önce) ele alır;
şans tabanı örneklemli (±1–2 pp); 1m değerlendirmesi 5m depoyla yapıldığı için bağlam kayması artefaktı oluşuyor (§3.4);
HA kümesi rescan ile yeniden üretilmiş (canlı adayların ~%90'ı); LUNATRY tek örnek. Canlı kod değiştirilmedi.
