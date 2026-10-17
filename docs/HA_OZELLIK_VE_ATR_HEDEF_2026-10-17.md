# Hız Avcısı Adayının Özelliği Olarak Erken-Giriş Bayrakları + ATR'ye Göre Hedef/Stop (2026-10-17)

**Bağlam:** `docs/YENI_STRATEJILER_2026-10-17.md` dört erken-giriş dedektörünü bağımsız sinyal olarak ölçtü; hepsi net
negatifti, şansa göre fark Hız Avcısı (HA) seviyesindeydi (+2…+4 pp). Rapor §7'de iki ucuz takip önerdi:
(1) en tutarlı iki dedektörü (`persist_1m_5mgrid` M=12,g=1,0 ve `ema_fan_5m` g=1,5) HA adayının **özelliği/bayrağı**
olarak değerlendirmek — bayraklı adaylar bayraksızlardan iyi mi, skor bonusu hak ediyor mu; (3) TP 1,5 / SL −3'ün
yapısal düşmanlığını (başa baş için ~%72 isabet) **ATR ölçekli hedef/stop** ve kısa ufukla aşmayı denemek.
Bu çalışma ikisini aynı aday kümesinde ölçer. Canlı kod değişmedi; yeni dosyalar:

- `backend/scripts/ha_feature_lift.py` (bayrak etiketleme, vektörel çıkış ızgarası, rapor)
- `backend/tests/test_ha_feature_lift.py` (10 test: bayrak penceresi, ATR14 = `series.bar_features`, vektörel sabit/trailing
  çıkış == skaler `eval_window` / `trail_window`, istatistik yardımcıları)
- Ham çıktı (work/, git dışı): `ha_feature_lift.md|json|log`, aday başına satırlar `ha_feature_rows.jsonl`, duyarlılık
  koşusu `ha_feature_lift_sens.md|json|log` (k=3, M=8).

## 1. Yöntem

- **Aday kümesi:** `work/rescan_21g_nogate.jsonl` canlı-benzeri HA adayları (rank ≤ 10, aşırı alım kapısı geçen), 60 dk
  bölüm tekilleştirme, dedektör ısınması sonrası (27 Eylül 03:55'ten itibaren), 60 dk sonucu olan **4.497 bölüm**
  (26 Eylül – 16 Ekim). Mum: `historical_candles` 5m (306 sembol), 1m (280 likit sembol; 16 Ekim ~20:00'de bitiyor).
- **Bayrak:** aday anından önceki **90 dk** içinde dedektörün ham sinyali (soğumasız, `cooldown_bars=1`) var mı.
  Duyarlılık: 30 dk penceresi; `ema_fan` k=3 ve `persist` M=8 ayrı koşu. persist bayrağı yalnız 1m verisi olan sembol ve
  anlarda değerlendirilebilir (4.459 aday), ema_fan hepsinde (4.497).
- **Sonuç ölçütleri:** TP = adayın `target_pct`'si, SL −3, maliyet 0,225, ufuk 60 dk (ve 15 dk); `eval_window` kuralı:
  yalnız tick'ten SONRA açılan 5m barlar (forming bar atlanır), aynı barda TP ve SL ise SL önce. Hit = MFE ≥ hedef.
  Şans tabanı `compute_chance` null3 (aynı sembol, saat dilimi, 30 dk aralık ve getiri eşleşmiş rastgele anlar), **tüm 4.497
  bölümde**. Wilson %95, oran farkı için Wald %95, net farkı için Welch t.
- **Çıkış ızgarası:** hedef = k × ATR14(5m)% (k ∈ {1; 1,5; 2}), stop = m × ATR (m ∈ {1; 1,5}), ufuk {15, 60} dk; trailing
  sabit (tetik %1,0 / iz %0,8 / SL −3) ve trailing ATR (tetik 1×ATR / iz 0,8×ATR / SL 1,5×ATR); referans sabit çiftler
  (adayın hedefi/SL3, TP2/SL1,5, TP1,5/SL1,5, TP1/SL1). ATR14 = 14 barlık basit TR ortalaması (`series.bar_features` ile
  aynı), aday anındaki son kapanmış 5m bar. Tüm hücreler N×12 bar matrisinde vektörel; TP=hedef/SL−3/60 dk hücresi skaler
  `CandleStore.eval` ile **0/4.497 uyuşmazlık**.
- Aday anında ATR14(5m)%: medyan **0,91**, çeyrekler 0,64–1,40 → 1×ATR hedef medyan 0,91 (maliyetin ~4 katı), 2×ATR 1,83.

## 2. Bayrak: bayraklı vs bayraksız HA adayları

### 2.1 Ana tablo (TP = adayın hedefi, SL −3, 60 dk)

| dedektör · küme | n | hit15 | hit60 [W95] | MFE | MAE | net60 (t) | şansa göre hit60 |
|---|---|---|---|---|---|---|---|
| **persist** (M=12,g=1,0) · bayraklı | 1.098 | %5,8 | %20,9 [19–23] | +2,40 | −2,25 | −0,48 (t −6,6) | +3,7 pp |
| persist · bayraksız | 3.361 | %7,2 | %20,8 [19–22] | +2,23 | −2,26 | −0,41 (t −10,0) | +3,8 pp |
| **ema_fan** (k=2,g=1,5) · bayraklı | 965 | %6,1 | %19,6 [17–22] | +2,33 | −2,24 | −0,50 (t −6,5) | +2,1 pp |
| ema_fan · bayraksız | 3.532 | %7,0 | %21,1 [20–22] | +2,26 | −2,27 | −0,41 (t −10,2) | +4,3 pp |

Farklar (bayraklı − bayraksız):

| dedektör | bayraklı payı | hit60 farkı [Wald95] | net60 farkı (Welch t) | şans-farkı farkı | öncülük medyanı |
|---|---|---|---|---|---|
| persist | %24,6 | **+0,0 pp** [−2,7…+2,8] | −0,07 (t −0,89) | −0,1 pp | 10 dk |
| ema_fan | %21,5 | **−1,5 pp** [−4,4…+1,3] | −0,09 (t −0,99) | −2,1 pp | 25 dk |

**Okuma:** her iki bayrak da HA adayının sonucunu **değiştirmiyor**. persist bayrağı tam sıfır fark, ema_fan hafif negatif;
net farkları sıfırdan ayırt edilemiyor (|t| < 1). Bayraklı adayların şansa göre farkı da bayraksızlardan yüksek değil
(persist eşit, ema_fan 2 pp düşük) — yani bayrak, HA'nın zaten yakaladığı momentum bağlamının ötesinde bilgi taşımıyor.

### 2.2 Duyarlılık: 30 dk penceresi (daha taze sinyal)

| dedektör | bayraklı n | hit60 bayraklı / bayraksız | hit farkı [Wald95] | net farkı (Welch t) |
|---|---|---|---|---|
| persist | 657 | %17,2 / %21,5 | **−4,3 pp** [−7,4…−1,1] | −0,14 (t −1,40) |
| ema_fan | 549 | %19,7 / %20,9 | −1,3 pp [−4,8…+2,3] | +0,01 (t +0,13) |

Daha taze persist sinyali olan adaylar **daha kötü** (fark aralığı sıfırı dışlıyor): son 30 dk'da 12 dk kesintisiz
yükseliş zaten gerçekleşmişse HA adayı daha "geç" bir giriştir. Bu, bayrağın bonus değil (varsa) hafif ceza yönünde
olduğunu söyler; ama tek alt küme ve çoklu karşılaştırma — ceza önermek için de yeterli değil.

### 2.3 Mod alt kümeleri

| dedektör · mod | bayraklı n · hit60 · net | bayraksız n · hit60 · net | hit farkı [Wald95] | Welch t |
|---|---|---|---|---|
| persist · trend_devam | 791 · %19,0 · −0,41 | 1.935 · %20,1 · −0,39 | −1,1 pp [−4,4…+2,2] | −0,19 |
| persist · notr/v_donusu | 307 · %25,7 · −0,65 | 1.426 · %21,9 · −0,42 | +3,9 pp [−1,5…+9,2] | −1,52 |
| ema_fan · trend_devam | 660 · %19,1 · −0,41 | 2.079 · %19,9 · −0,41 | −0,8 pp [−4,2…+2,7] | +0,02 |
| ema_fan · notr/v_donusu | 305 · %20,7 · −0,68 | 1.453 · %22,9 · −0,41 | −2,3 pp [−7,3…+2,8] | −1,87 |

trend_devam'da iki bayrak da sıfır etkili. notr/v_donusu'nda persist bayrağı hit'i +3,9 pp yukarı çekiyor ama net'i
**−0,23 aşağı** (MAE −2,65: daha derin geri çekilme) — isabet artsa bile kâr yok; aralık sıfırı içeriyor.

### 2.4 Yarı-örnek (böl: 6 Ekim)

| dedektör | yarı | bayraklı n · hit60 · net · şans | bayraksız n · hit60 · net · şans | hit farkı | Welch t |
|---|---|---|---|---|---|
| persist | ilk | 529 · %20,4 · −0,49 · +4,0 pp | 1.451 · %20,7 · −0,43 · +4,0 pp | −0,3 pp | −0,44 |
| persist | ikinci | 569 · %21,3 · −0,48 · +3,5 pp | 1.910 · %20,9 · −0,39 · +3,7 pp | +0,4 pp | −0,78 |
| ema_fan | ilk | 455 · %20,7 · −0,41 · +4,0 pp | 1.528 · %20,6 · −0,46 · +4,0 pp | +0,0 pp | +0,39 |
| ema_fan | ikinci | 510 · %18,6 · −0,57 · +0,5 pp | 2.004 · %21,5 · −0,37 · +4,5 pp | −2,9 pp | −1,71 |

İki yarıda da sıfır etrafında; ema_fan ikinci yarıda negatife kayıyor. Tutarlı bir pozitif fark yok.

### 2.5 Skor üçte-birlikleri × bayrak ("skor bonusu" sorusu)

Bayrak HA skoruna ek puan olarak işe yarayacaksa, skorun açıkladığından **fazlasını** vermeli — yani skor dilimi içinde
bayraklıların isabeti yüksek olmalı.

| skor dilimi | persist: bayraklı hit · bayraksız hit · fark | ema_fan: bayraklı hit · bayraksız hit · fark |
|---|---|---|---|
| alt ⅓ | %18,7 · %16,7 · +2,0 pp (n 284/1.198) | %16,1 · %17,2 · −1,1 pp (n 267/1.232) |
| orta ⅓ | %18,1 · %17,4 · +0,7 pp (n 409/1.079) | %18,6 · %17,1 · +1,4 pp (n 350/1.149) |
| üst ⅓ | %25,2 · %28,8 · **−3,6 pp** (n 405/1.084) | %23,3 · %29,3 · **−6,0 pp** (n 348/1.151) |

Skorun en yüksek üçte-birliğinde (bonusun fiilen sıralamayı değiştireceği yer) bayraklı adaylar **daha kötü**. Düşük
dilimlerdeki +1…+2 pp farklar küçük ve sıralamayı etkilemez. **Skor bonusu olarak işe yaramaz.**

### 2.6 İki bayrağın birleşimi (iki dedektör için de değerlendirilebilir 4.459 aday)

| küme | n | hit60 [W95] | MFE | MAE | net60 (t) | şansa göre |
|---|---|---|---|---|---|---|
| hiçbiri | 2.696 | %20,9 [19–22] | +2,21 | −2,26 | −0,38 (t −8,4) | +4,2 pp |
| yalnız persist | 804 | %22,3 [20–25] | +2,47 | −2,28 | −0,48 (t −5,5) | +4,8 pp |
| yalnız ema_fan | 665 | %20,6 [18–24] | +2,34 | −2,27 | −0,50 (t −5,4) | +2,5 pp |
| ikisi birden | 294 | **%17,0** [13–22] | +2,23 | −2,15 | −0,50 (t −3,7) | +0,9 pp |

İki dedektörün de ateşlediği adaylar en zayıf küme (%17,0; şansa göre +0,9 pp). "Teyit çakışması" fikri de desteklenmiyor;
tersine, iki kural da ateşlediğinde hareket büyük ölçüde geride kalmış görünüyor.

### 2.7 Duyarlılık koşusu: `ema_fan` k=3, `persist` M=8

Bkz. §5 (ayrı koşu, `work/ha_feature_lift_sens.md`): ema_fan aynı; persist M=8 hit60'ı +4,7 pp artırıyor ama net'i
değiştirmiyor (−0,00).

## 3. Çıkış yapısı ızgarası

Tüm 4.497 aday; net % (maliyet düşülmüş), t, kazanan payı (net > 0). ATR hücrelerinde hedef/stop medyanı yüzde olarak.

### 3.1 Tüm adaylar

| hücre | 15 dk: hit · net (t) · kazanan | 60 dk: hit · net (t) · kazanan |
|---|---|---|
| TP 1×ATR · SL 1×ATR (0,91 / 0,91) | %35,9 · −0,321 (−18,7) · %40 | %58,2 · −0,343 (−16,9) · %44 |
| TP 1×ATR · SL 1,5×ATR | %35,9 · −0,369 (−19,4) · %42 | %58,2 · −0,406 (−16,7) · %51 |
| TP 1,5×ATR · SL 1×ATR (1,37 / 0,91) | %24,7 · −0,267 (−13,9) · %37 | %46,9 · −0,315 (−13,2) · %37 |
| TP 1,5×ATR · SL 1,5×ATR | %24,7 · −0,319 (−15,3) · %39 | %46,9 · −0,381 (−13,7) · %44 |
| TP 2×ATR · SL 1×ATR (1,83 / 0,91) | %17,3 · **−0,240** (−11,8) · %36 | %38,0 · −0,310 (−11,8) · %33 |
| TP 2×ATR · SL 1,5×ATR | %17,3 · −0,291 (−13,2) · %37 | %38,0 · −0,380 (−12,5) · %39 |
| trailing ATR (1×/0,8×/SL 1,5×) | −0,147 (−5,3) · %40 (tetik %36) | −0,121 (−3,5) · %48 (tetik %58) |
| sabit: adayın hedefi / SL −3 (referans) | %6,8 · −0,311 (−12,8) · %37 | %20,8 · −0,428 (−12,1) · %38 |
| sabit TP 2 / SL 1,5 | %17,8 · −0,289 (−15,6) · %37 | %37,2 · −0,339 (−14,5) · %38 |
| sabit TP 1,5 / SL 1,5 | %24,8 · −0,324 (−18,9) · %38 | %46,2 · −0,366 (−17,5) · %43 |
| sabit TP 1 / SL 1 | %36,0 · −0,326 (−25,1) · %39 | %57,0 · −0,342 (−23,6) · %43 |
| trailing sabit 1,0 / 0,8 / SL −3 | −0,163 (−5,8) · %42 (tetik %36) | **−0,110** (−3,1) · %56 (tetik %57) |

**Pozitif hücre yok.** 12 ATR hücresinin hepsi −0,24 … −0,41, t −12 … −19. ATR ölçeklemesi sabit hedeften daha iyi
değil: en iyi sabit-TP hücresi (TP 2/SL 1,5, 15 dk: −0,289) ile en iyi ATR hücresi (2×ATR/1×ATR, 15 dk: −0,240) arasındaki
fark 0,05 puan — maliyetin dörtte biri. Hedef küçüldükçe isabet artıyor (1×ATR 60 dk: %58) ama net değişmiyor: kazanılan
0,9 puan maliyet ve kaybedilen −0,9'larla erimiş durumda. Kısa ufuk (15 dk) 60 dk'dan hafif iyi (daha az SL yemesi) ama
işareti değiştirmiyor.

Trailing çıkışlar en az kötü (−0,11 … −0,16), kazanan payı %56'ya kadar çıkıyor ama ortalama kaybeden −3 SL olduğu için net
negatif. Koşulsuz rastgele-giriş trailing referansı (`YENI_STRATEJILER` §1: likit sembollerde rastgele 5m kapanışları,
n=20.000) **−0,18**; HA adayları −0,11 — fark 0,07 puan, HA'nın "şansa göre +4 pp" avantajının para karşılığı yaklaşık
bu kadar ve maliyetin altında.

### 3.2 Bayraklı alt kümelerde aynı ızgara (60 dk; 15 dk benzer)

| alt küme (n) | en iyi ATR hücresi | trailing ATR | trailing sabit | sabit hedef/SL3 |
|---|---|---|---|---|
| tüm (4.497) | 2×/1× −0,310 (t −11,8) | −0,121 (t −3,5) | −0,110 (t −3,1) | −0,428 |
| persist bayraklı (1.098) | 1,5×/1× −0,246 (t −5,2) | **−0,056** (t −0,8) | −0,132 (t −1,8) | −0,481 |
| persist bayraksız (3.361) | 2×/1× −0,326 (t −10,8) | −0,140 (t −3,6) | −0,102 (t −2,6) | −0,406 |
| ema_fan bayraklı (965) | 1,5×/1× −0,298 (t −6,1) | −0,109 (t −1,4) | −0,080 (t −1,0) | −0,495 |
| ema_fan bayraksız (3.532) | 2×/1× −0,312 (t −10,4) | −0,124 (t −3,2) | −0,118 (t −3,0) | −0,410 |
| ikisinden biri (1.769) | 1,5×/1× −0,255 (t −6,7) | −0,077 (t −1,4) | −0,113 (t −2,0) | −0,486 |
| ikisi birden (294) | 1,5×/1× −0,365 (t −4,7) | −0,099 (t −0,7) | −0,076 (t −0,5) | −0,496 |
| trend_devam (2.739) | 2×/1× −0,276 (t −9,3) | **−0,066** (t −1,5) | −0,073 (t −1,5) | −0,409 |

Bayraklı alt kümelerde de **pozitif hücre yok** (n ≥ 30 şartıyla taranan 192 hücrenin hiçbiri). Sıfırla ayırt edilemeyen
en iyi hücreler trailing ATR'de: persist-bayraklı −0,056 (t −0,8), trend_devam −0,066 (t −1,5) — "belki sıfır", "pozitif"
değil; ve 8 alt küme × 24 hücre içinden seçildikleri için iyimser.

## 4. Sonuç ve öneri

1. **Bayrak skor bonusu olarak işe yaramaz.** persist bayrağı hit60 farkı +0,0 pp [−2,7…+2,8], ema_fan −1,5 pp
   [−4,4…+1,3]; net farkları |t| < 1; şansa göre farkta da üstünlük yok; skorun üst üçte-birliğinde bayraklılar 3,6–6,0 pp
   **daha kötü**; iki bayrak birden en zayıf küme (%17,0). Daha taze persist sinyali (30 dk) adayı anlamlı biçimde kötüleştiriyor
   (−4,3 pp [−7,4…−1,1]) — bonus bir yana, "hareket zaten koşmuş" uyarısı. Ceza olarak kullanmak için de tek alt küme/çoklu
   karşılaştırma nedeniyle yeterli kanıt yok; **hiçbir skor değişikliği önerilmez.** Duyarlılık (§5): persist M=8
   bayrağı isabeti tutarlı biçimde +4,7 pp artırıyor ama net kârı sıfır değiştiriyor (daha oynak adaylar: MFE ve MAE
   birlikte büyüyor) — "hedefe dokunma" bonusu olur, "kâr" bonusu olmaz; karar aynı.
2. **ATR ölçekli hedef/stop ile pozitif hücre yok** — açıkça: 12 ATR hücresi × 8 alt küme × 2 ufuk + referanslar, hiçbiri net > 0.
   Sabit TP/SL'den farkı ≤ 0,05 puan. Hedefi küçültmek isabeti %58'e çıkarıyor ama maliyet (0,225) net'i yutuyor.
   Çıkış yapısı "asıl sorun" değil: HA adaylarının 60 dk MFE ortalaması +2,3 ile MAE −2,3 simetrik; giriş anında yön
   kenarı yok, dolayısıyla hiçbir TP/SL kombinasyonu bunu kâra çevirmiyor.
3. **Trailing en az kötü** (−0,06 … −0,16) ve rastgele girişin (−0,18) biraz üstünde; HA'nın tüm "kenarı" ~0,07 puan,
   maliyetin üçte biri. Canlı `AUTO_PAPER_EXIT_PROFILE=kalibre` ölçümüyle (60 g test EV −0,157) uyumlu.
4. **Öneri:** iki dedektörü bayrak/bonus olarak da canlıya almayın; ATR hedef/stop değişikliği yapmayın. Kârlılık arayışı
   giriş seçimi tarafında kalmalı: mum verisiyle (fiyat+hacim) denenen altı fikir (merdiven, 4 dedektör, bayrak) ve çıkış
   ızgarası tükendi. Kalan adaylar `YENI_STRATEJILER` §7'de: emir defteri / taker-buy hacmi (`historical_candles`'ta yok),
   60+ günlük örneklem, 1 dk eşleşmeli şans tabanı. Bunlar olmadan yeni mum-tabanlı dedektör denemesi önerilmez.

## 5. Duyarlılık koşusu (`persist` M=8, `ema_fan` k=3; `--persist-m 8 --ema-k 3`)

Aynı 4.497 aday; bayraklı payı persist %31,6 (1.407), ema_fan %21,3 (960).

| dedektör · küme | n | hit60 [W95] | MFE | MAE | net60 (t) | şansa göre | hit farkı [Wald95] | net farkı (Welch t) |
|---|---|---|---|---|---|---|---|---|
| persist M=8 · bayraklı | 1.407 | %24,0 [22–26] | +2,66 | −2,43 | −0,43 (t −6,3) | +5,0 pp | **+4,7 pp** [+2,0…+7,3] | −0,00 (t −0,04) |
| persist M=8 · bayraksız | 3.052 | %19,4 [18–21] | +2,10 | −2,18 | −0,42 (t −10,2) | +3,2 pp | | |
| ema_fan k=3 · bayraklı | 960 | %19,7 | +2,34 | −2,24 | −0,45 | +2,3 pp | −1,4 pp [−4,3…+1,4] | −0,03 (t −0,39) |
| ema_fan k=3 · bayraksız | 3.537 | %21,1 | +2,26 | −2,27 | −0,42 | +4,3 pp | | |

`ema_fan` k=3, k=2 ile aynı: sıfır/hafif negatif. **`persist` M=8 farklı davranıyor:** bayraklı adayların hit60'ı +4,7 pp
yüksek, iki yarıda da tutarlı (ilk +4,3 pp, ikinci +5,0 pp), trend_devam +4,0 pp [+0,8…+7,3], notr/v_donusu +6,5 pp;
30 dk penceresinde +1,0 pp (sönüyor). **Ama net farkı sıfır** (−0,00; Welch t −0,04; trend_devam +0,09, notr −0,19): bayraklı
adaylar hedefe daha sık dokunuyor (MFE +2,66 vs +2,10) ve aynı ölçüde daha derin geri çekiliyor (MAE −2,43 vs −2,18) —
oynaklık yüksek, yön kenarı yok. Skor dilimlerinde hit farkı alt ⅓'te +8,3 pp (n 313/1.169; net −0,38 vs **−0,30**, yani
daha kötü), orta +2,5 pp, üst ⅓ +0,3 pp: bonus, skor sıralamasının tepesinde hiçbir şeyi değiştirmez; listeye düşük
skorlu, daha oynak ve net'i daha kötü adayları taşır. ATR ızgarasında M=8 bayraklı alt küme de pozitif hücre vermiyor
(en iyi trailing ATR −0,097, t −1,4). M=12 (ön kayıtlı seçim) ile M=8 arasındaki fark, 8 dk'lık kalıcılığın daha çok
adayı daha erken fazda yakalamasıdır; isabet artışı kâr artışına dönüşmediği için §4'teki karar değişmez.

## Sınırlar

- Tek 20 günlük dönem (BTC EMA200 altı günlerin %57'si); çoklu karşılaştırma (2 bayrak × 6 alt küme × 2 pencere;
  8 alt küme × 24 ızgara hücresi) — tek |t| > 2 yeterli sayılmaz, sıfıra yakın negatif hücreler "pozitif olabilir" diye okunmaz.
- `eval_window` forming barı atlar: tick'ten sonraki ilk 5 dk'daki TP/SL görülmez, 15 dk ufku fiilen 2 bar. Tüm HA ölçümleriyle
  aynı kural; mutlak sayılar iyimser/kötümser olabilir ama bayraklı–bayraksız ve hücreler arası kıyas simetrik.
- Giriş = aday fiyatı (gecikmesiz), komisyon sabit 0,225, kayma yok; 5m mum içi sıra kötümser (SL önce).
- 1m verisi 16 Ekim ~20:00'de bitiyor; persist bayrağı 4.459/4.497 adayda değerlendirilebildi.
- Dedektörler soğumasız koşturuldu (bayrak sorusu için doğru olan); bağımsız-sinyal raporundaki soğumalı sayılarla birebir değil.
- HA kümesi rescan ile yeniden üretilmiş (canlı adayların ~%90'ı), ML hedefi ve spread cezası yok (`docs/RESCAN_HARNESS.md`).
- Canlı kod değiştirilmedi; betik DB'ye yazmaz.
