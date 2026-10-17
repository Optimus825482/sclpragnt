# Limit giriş + StochRSI ön sinyali — çekirdek dönüşünü önceden görür mü, kârlı giriş verir mi? (2026-10-17)

Bu rapor `backend/scripts/limitstoch_report.py` tarafından üretilmiştir (2026-10-17 14:36). Çalışma çevrimdışıdır; canlı koda bağlanmaz.

## 0. Özet ve kararlar

**(1) StochRSI ön sinyali çekirdeğin AL dönüşünü güvenilir biçimde önceden haber veriyor mu? — HAYIR (zayıf, işe yaramaz).**
- 5m (birincil, seviye 20, W30, ön sinyal 2242/gün, tüm likit semboller, tekilleştirmeden önce): çekirdek 1 bar (5 dk) içinde dönme olasılığı 13.4% (kırmızı bar tabanı 16.0% → **daha düşük**), 3 bar içinde 35.5% (taban 38.1%), 6 bar (30 dk) içinde 68.4% (taban 61.3%, **+7.1 pp, 1,12×**), 12 bar (60 dk) içinde 88.4% (taban 86.5%, 1,02×). Yani kısa ufukta (1–3 bar) tabanın ALTINDA; 30 dk'da küçük bir üstünlük; 60 dk'da fark yok. Öncülük (12 bar içinde dönenlerde) medyan 4 bar = 20 dk, ama dönüşün kendisi zaten çok sık (tabanın 86.5%'i 60 dk'da döner). Dönüşlerin 53.5%'inden önce ön sinyal var, rastgele bir kırmızı barın önünde 50.2% (1,06×).
- 1m: 3 bar içinde 34.9% (taban 29.7%, 1,18×), 6 bar içinde 65.4% (taban 50.6%, 1,29×); lift daha büyük ama 1 dk çekirdek her ~8 dk'da döndüğü ve 1m ön sinyal günde ≈ 8171 kez çaldığı için pratik değeri yok; öncülük medyan 4 dk.
- LUNA tipi olaylar (4 552 olay, t0'dan önceki 30 dk, nedensel): 5m ön sinyal olaylarda 26.3%, rastgele anlarda 32.2% (**0.81× — daha az**); 1m: 82.0% vs 76.1% (1,08×, ama her ~dakika çalıyor). Çekirdek AL dönüşü de aynı (5m 0,86×). LUNATRY 17 Ekim: 5m ön sinyal ilk kez 02:30'da (t0 + 90 dk, fiyat P0'ın +%4,3 üstünde); 1m'de 00:58'de (t0 − 2 dk, fiyat P0 civarında) çaldı ve çekirdek 01:02'de döndü — ama 1m 00:44'te de çalmıştı (−16 dk, yanlış) ve gün boyu gürültü üretiyor.

**(2) Ön sinyal örneklem dışında KÂRLI bir giriş mi? — HAYIR.**
- 12 sinyal kümesi (5m/1m/15m × seviye 20/30 × ön sinyal/onaylı) × 24 çıkış = 288 hücre: W30'da net > 0 olan hücre sayısı **0** (birincil 60 sn/%0,15), iyimser senaryoda (0 sn/%0,05) **0**; en iyi hücre neti -0.48 (birincil, 1m|20|pre) ve -0.28 (iyimser, 15m|30|conf). Yürüyen-ileri (bloğta seç → diğer iki blokta ölç): 0/72 satırda OOS net > 0, alt sınır > 0 olan 0. Sinyal oynaklık-eşleşmeli koşulsuz rastgeleden (taban 4) ayırt edilemiyor: sinyal−taban farkı 72 satırın hiçbirinde anlamlı pozitif değil (0); hit60@1,5 şans yükselişi 5m ön sinyalde 0,88×, onaylıda 1,02×, 1m'de 1,02–1,03×, 15m'de 0,97–1,01×.
- Not: istenen rastgele taban (aynı sembol/saat, herhangi bir sinyalden ≥ 2 sa uzak) 5m ön sinyalde POZİTİF çıkıyor (≈ +0,1 net): bu, 'ileride 2 saat ön sinyal olmaması' koşulunun geleceğe bakması yüzünden bir seçim yanlılığıdır (sinyalsiz saatler = yükseliş trendi). Dışlamasız tabanlar (3/4) ≈ −0,49 (maliyet tabanı) ve sinyal onlardan farksız.

**(3) Limit / StochRSI girişi örneklem dışında net-pozitif VE rastgeleden iyi mi? — HAYIR (net-pozitif hiçbiri yok; küçük 'rastgeleden az kötü' farkları var).**
- **Net-pozitif:** HA W30'da 73 giriş hücresi × 24 çıkış (işlem ≥ 100 olan 1752 bileşim) içinde net/sinyal > 0 olan **0**, net/işlem > 0 olan **0**; en iyi net/işlem -0.33 (LK d1 V60 / fixed TP1 SL3 T120). HA B1, B2, B3, 90 gün, canlı bildirimler (hepsi / trend_devam) ve canlı journal adayları (ileri) için de pozitif bileşim sayısı sıfır (bölüm 5.4). 'En iyi' net/sinyal bileşimleri (≈ −0,05) zaten yalnızca %10 dolan, neredeyse hiç işlem yapmayan hücrelerdir; işlem başına net hep −0,4…−0,5.
- **Dolum ve seçim yanlılığı:** HA W30'da düz limit dolum oranı d = %0,3 için %77–89, d = %0,6 için %63–82, d = %1,0 için %45–71, d = %1,5 için %29–57 (V = 15…60 dk); oynaklık eşleşmeli rastgele giriş de benzer oranda doluyor (limit oynak anda zaten dolar). Dolan sinyallerden sonra P0'a göre 60 dk getirisi -1.87…-0.61%, DOLMAYANLARDAN sonra +0.50…+3.26% (limit en iyi koşuları kaçırıyor: dolmayanlar sonra ortalama yükseliyor); rastgele-4'te aynı ayrım daha küçük (dolan -1.59…-0.46%, dolmayan +0.39…+2.08%), yani bu ayrımın bir kısmı mekanik, ama sinyallerde daha belirgin. Limit fiyatından 60 dk sonraki getiri hep negatif (−0,17…−0,37%): dipten alım ortalamada geri toparlama vermiyor.
- **StochRSI desteği:** (a) K5 < 50 kapısı dolumu yaklaşık üçte bire indirir (ör. d = %0,3, V = 60: %28 vs %89) ve net/işlemi düzeltmez (−0,4…−0,5); (b) dip + ön sinyal teyidi ve (c) dolum + 5 dk içinde ön sinyal, düz limitten ve piyasa girişinden daha iyi değil — rastgele-4'e göre en iyi farklar −0,04…+0,02 (anlamlı pozitif yok), net hep < 0. 'Rastgeleden az kötü' sonuçlar çıkıyor (ör. LK d0,3 V60: HA B3'te net/sinyal −0,15 vs rastgele-4 −0,20, fark +0,05 [+0,03; +0,08]; trend_devam bildirimlerinde +0,16), ama (i) net hâlâ −0,15, (ii) canlı journal ileri çizgisinde fark +0,01 [−0,02; +0,04] (anlamsız), (iii) 1 752 bileşim içinde seçilmiş. Piyasa girişi (referans M) trend_devam bildirimlerinde -0.27 [-0.41; -0.13] net/sinyal (rastgele-4 -0.54; fark +0.27 [+0.11; +0.43]) — önceki çalışmadaki 'trend_devam rastgeleyi +0,2…0,3 geçer ama net −0,3' bulgusuyla tutarlı.
- **Yürüyen-ileri (HA blokları):** 14 satırdan OOS net/sinyal > 0 olan 0, %95 alt sınırı > 0 olan 0. Ölçüt B (rastgele-4'e göre en iyi) satırlarında sinyal−rastgele-4 alt sınırı > 0: 6/7 (hepsi LK d0,3 V60 türü) ama net negatif. **Önerilen limit/StochRSI parametresi yok.**
- **LUNATRY 17 Ekim:** ilk HA adayı (01:15:30, P0'ın +%1,7 üstü) için yalnız d = %0,3 limit doldu (1 dk içinde; net +0,77…+6,02), d ≥ %0,6 limitler HİÇ dolmadı ve +%8'lik koşuyu kaçırdı; tek bildirim (02:03:29, P0'ın +%6,2 üstü) için limitler doldu ama fiyat sonra düştü (net −1,87…+0,14). Yani limit, kazanan koşuyu kaçırıp kaybedeni dolduruyor.

## 1. Yöntem

- **Veri:** `historical_candles` 1m/5m/15m, 19 Tem → 17 Eki 2026 06:00 (306 sembol; taker sütunları kullanılmadı). Zaman dilimi İstanbul (UTC+3). Pencereler (İstanbul günü): **W30** = 17 Eyl–16 Eki (birincil), **B1** 20 Tem–18 Ağu, **B2** 19 Ağu–17 Eyl, **B3** 18 Eyl–16 Eki (önceki çalışmalarla aynı 30 günlük bloklar).
- **StochRSI** (`app/rescan/stochrsi.py`, testli: `tests/test_stochrsi.py`): Wilder RSI(14) (ilk 14 değişimin ortalaması tohum, RMA); stoch = 100·(RSI − min14)/(max14 − min14), aralık 0 → 0; K = SMA3(stoch); D = SMA3(K). Grafik tarafında (frontend `IndicatorPicker.tsx`) StochRSI parametreleri (14/14/3/3, seviye 20) tanımlanmış, hesap kodu bu çalışmanın başlangıcında depoda henüz yoktu — tanım isteğe göre yazıldı; aralık 0 durumunda `technical_analysis._stoch_rsi` 50 döndürür, burada 0 (istenen tanım). **Ön sinyal** bar i'nin kapanışında: K[i−1] ≤ D[i−1], K[i] > D[i], K[i−1] < seviye (20 | 30) ve çekirdek i'de kırmızı (bearish & valid).
- **Çekirdek (RQK):** `app/rescan/rqk.py` varyant A (uygulama birebir; h = 8, r = 2, smoothColors = false, uygulama renk kuralı); ham mumlar (boşluk doldurulmadı). Bar i kapanışında renk bilinir; 'AL dönüşü' = kırmızı → yeşil.
- **Likit sembol filtresi (Çalışma A):** son kapanmış 5 dk barına göre 24 sa quote hacmi ≥ 5M TRY (olay tanımıyla aynı). Not: TRY değer kaybı yüzünden likit sembol sayısı zamanla artıyor (sinyal/gün B1 534 → B3 1 565 gibi artışlar kısmen bundandır). Çalışma B'de filtre yok (HA havuzu kendi seçimi).
- **Simülatör:** `app/rescan/exit_sim.py` (gerçekçi doluş; bu çalışmada geriye uyumlu `entry_slip_pct` eklendi, `tests/test_exit_sim.py`'de test). Giriş = sinyal + 60 sn sonraki ilk 1 dk açılışı × (1 + %0,15) (birincil) veya 0 sn / %0,05 (iyimser); stop: min(stop, bar açılışı) × (1 − kayma); TP tam seviye; aynı barda stop + TP → stop; zaman stopu kapanış × (1 − kayma); bacak başına %0,1125. Pencere 120 dk 1 dk barı.
- **İstatistik:** gün-kümeli standart hata; farkların SE'si bağımsız kabulle karekök toplamı (muhafazakâr). Walk-forward: seçim bloğunda, ölçüm diğer bloklarda.
- **Tekrarlanabilirlik:** `scripts/limitstoch_*.py` (ind → a1 → a3 → b rows/sim → report); `python scripts/limitstoch_report.py`. Çıktı: `work/limitstoch/report.md`.

## 2. Çalışma A-1 — Ön sinyal çekirdek AL dönüşünü önceden haber veriyor mu?

Tanım: ön sinyal bar i'nin kapanışında verilir (çekirdek i'de KIRMIZI). 'N bar içinde dönüş' = i+1 … i+N barlarından birinde çekirdek yeşil. Taban 1 (**kırmızı**) = çekirdeğin kırmızı olduğu TÜM barlar; taban 2 (**kırmızı+dip**) = kırmızı ve K[i-1] < seviye ama kesişim şartı YOK (kesişimin kendisinin katkısını ayırır). Likit sembol (24 sa ≥ 5M TRY). Aralıklar gün-bootstrap %95 (aynı gündeki barlar ilişkili). Fark = ön sinyal − taban (yüzde puan).

### 5m çekirdek / StochRSI K seviye 20 — W30 (17 Eyl–16 Eki)  (BİRİNCİL)

Ön sinyal sayısı: **67266** (2242/gün); kırmızı bar tabanı: 795192 bar; kırmızı+dip tabanı: 357902 bar.

| N bar (≈ dk) | P(dönüş \| ön sinyal) | taban 1 kırmızı | fark [%95] | oran | taban 2 kırmızı+dip | fark [%95] | oran |
|---|---|---|---|---|---|---|---|
| 1 (5 dk) | 13.4% [13.1; 13.6] | 16.0% | -2.6 [-3.2; -2.1] | 0.84× | 10.5% | +2.9 [+2.6; +3.2] | 1.27× |
| 3 (15 dk) | 35.5% [35.2; 35.9] | 38.1% | -2.6 [-3.5; -1.7] | 0.93× | 31.1% | +4.5 [+4.0; +5.0] | 1.14× |
| 6 (30 dk) | 68.4% [68.1; 68.8] | 61.3% | +7.1 [+6.4; +8.0] | 1.12× | 59.8% | +8.7 [+8.2; +9.2] | 1.15× |
| 12 (60 dk) | 88.4% [88.1; 88.6] | 86.5% | +1.8 [+1.3; +2.3] | 1.02× | 85.8% | +2.5 [+2.0; +2.9] | 1.03× |

12 bar içinde dönüş olan ön sinyallerde **medyan öncülük: 4 bar = 20 dk**; dağılım (bar 1…12, % toplamın): 15 13 12 14 13 10 7 3 4 4 3 2.
Tersi: kırmızı→yeşil dönüş barlarının **53.5%'inden önceki 12 barda ön sinyal var** (n=127228); dönüşe uygun HERHANGİ bir kırmızı barın önceki 12 barında ön sinyal olma oranı (taban) 50.2% → oran 1.06×. Dönüşten önceki son ön sinyal medyan 5 bar = 25 dk önce.

### 5m çekirdek / StochRSI K seviye 30 — W30 (17 Eyl–16 Eki)

Ön sinyal sayısı: **74564** (2485/gün); kırmızı bar tabanı: 795192 bar; kırmızı+dip tabanı: 450902 bar.

| N bar (≈ dk) | P(dönüş \| ön sinyal) | taban 1 kırmızı | fark [%95] | oran | taban 2 kırmızı+dip | fark [%95] | oran |
|---|---|---|---|---|---|---|---|
| 1 (5 dk) | 14.4% [14.2; 14.7] | 16.0% | -1.6 [-2.1; -1.1] | 0.90× | 11.8% | +2.6 [+2.3; +2.9] | 1.22× |
| 3 (15 dk) | 36.9% [36.5; 37.2] | 38.1% | -1.2 [-2.0; -0.4] | 0.97× | 33.2% | +3.7 [+3.2; +4.1] | 1.11× |
| 6 (30 dk) | 69.2% [68.9; 69.5] | 61.3% | +7.9 [+7.0; +8.7] | 1.13× | 60.7% | +8.5 [+7.9; +9.0] | 1.14× |
| 12 (60 dk) | 88.6% [88.3; 88.8] | 86.5% | +2.0 [+1.5; +2.5] | 1.02× | 86.2% | +2.4 [+2.0; +2.8] | 1.03× |

12 bar içinde dönüş olan ön sinyallerde **medyan öncülük: 4 bar = 20 dk**; dağılım (bar 1…12, % toplamın): 16 14 12 14 13 9 7 3 4 3 3 2.
Tersi: kırmızı→yeşil dönüş barlarının **58.3%'inden önceki 12 barda ön sinyal var** (n=127228); dönüşe uygun HERHANGİ bir kırmızı barın önceki 12 barında ön sinyal olma oranı (taban) 54.2% → oran 1.08×. Dönüşten önceki son ön sinyal medyan 4 bar = 20 dk önce.

### 1m çekirdek / StochRSI K seviye 20 — W30 (17 Eyl–16 Eki)

Ön sinyal sayısı: **245129** (8171/gün); kırmızı bar tabanı: 4541076 bar; kırmızı+dip tabanı: 2482479 bar.

| N bar (≈ dk) | P(dönüş \| ön sinyal) | taban 1 kırmızı | fark [%95] | oran | taban 2 kırmızı+dip | fark [%95] | oran |
|---|---|---|---|---|---|---|---|
| 1 (1 dk) | 13.0% [12.9; 13.1] | 11.6% | +1.4 [+1.2; +1.7] | 1.12× | 9.4% | +3.6 [+3.5; +3.8] | 1.39× |
| 3 (3 dk) | 34.9% [34.7; 35.1] | 29.7% | +5.2 [+4.7; +5.6] | 1.18× | 27.2% | +7.7 [+7.3; +8.0] | 1.28× |
| 6 (6 dk) | 65.4% [65.2; 65.6] | 50.6% | +14.8 [+14.3; +15.2] | 1.29× | 50.7% | +14.7 [+14.2; +15.2] | 1.29× |
| 12 (12 dk) | 84.9% [84.8; 85.1] | 76.1% | +8.8 [+8.3; +9.4] | 1.12× | 75.0% | +10.0 [+9.3; +10.6] | 1.13× |

12 bar içinde dönüş olan ön sinyallerde **medyan öncülük: 4 bar = 4 dk**; dağılım (bar 1…12, % toplamın): 15 14 12 16 12 9 7 2 4 4 3 3.
Tersi: kırmızı→yeşil dönüş barlarının **43.7%'inden önceki 12 barda ön sinyal var** (n=525338); dönüşe uygun HERHANGİ bir kırmızı barın önceki 12 barında ön sinyal olma oranı (taban) 35.0% → oran 1.25×. Dönüşten önceki son ön sinyal medyan 4 bar = 4 dk önce.

### 1m çekirdek / StochRSI K seviye 30 — W30 (17 Eyl–16 Eki)

Ön sinyal sayısı: **265789** (8860/gün); kırmızı bar tabanı: 4541076 bar; kırmızı+dip tabanı: 2765371 bar.

| N bar (≈ dk) | P(dönüş \| ön sinyal) | taban 1 kırmızı | fark [%95] | oran | taban 2 kırmızı+dip | fark [%95] | oran |
|---|---|---|---|---|---|---|---|
| 1 (1 dk) | 13.6% [13.5; 13.8] | 11.6% | +2.1 [+1.8; +2.3] | 1.18× | 10.0% | +3.6 [+3.4; +3.8] | 1.36× |
| 3 (3 dk) | 35.6% [35.5; 35.8] | 29.7% | +6.0 [+5.5; +6.4] | 1.20× | 28.5% | +7.1 [+6.8; +7.5] | 1.25× |
| 6 (6 dk) | 66.1% [65.9; 66.3] | 50.6% | +15.5 [+15.0; +15.9] | 1.31× | 52.0% | +14.1 [+13.6; +14.6] | 1.27× |
| 12 (12 dk) | 85.3% [85.2; 85.5] | 76.1% | +9.2 [+8.7; +9.8] | 1.12× | 76.2% | +9.1 [+8.5; +9.7] | 1.12× |

12 bar içinde dönüş olan ön sinyallerde **medyan öncülük: 4 bar = 4 dk**; dağılım (bar 1…12, % toplamın): 16 14 12 15 12 8 6 2 4 4 3 3.
Tersi: kırmızı→yeşil dönüş barlarının **46.9%'inden önceki 12 barda ön sinyal var** (n=525338); dönüşe uygun HERHANGİ bir kırmızı barın önceki 12 barında ön sinyal olma oranı (taban) 37.2% → oran 1.26×. Dönüşten önceki son ön sinyal medyan 4 bar = 4 dk önce.

### 15m çekirdek / StochRSI K seviye 20 — W30 (17 Eyl–16 Eki)

Ön sinyal sayısı: **25267** (842/gün); kırmızı bar tabanı: 261845 bar; kırmızı+dip tabanı: 117908 bar.

| N bar (≈ dk) | P(dönüş \| ön sinyal) | taban 1 kırmızı | fark [%95] | oran | taban 2 kırmızı+dip | fark [%95] | oran |
|---|---|---|---|---|---|---|---|
| 1 (15 dk) | 12.8% [12.4; 13.2] | 16.9% | -4.1 [-4.9; -3.3] | 0.76× | 10.0% | +2.8 [+2.2; +3.4] | 1.28× |
| 3 (45 dk) | 34.4% [33.8; 34.9] | 39.0% | -4.7 [-6.0; -3.2] | 0.88× | 30.1% | +4.3 [+3.2; +5.4] | 1.14× |
| 6 (90 dk) | 66.5% [65.9; 67.1] | 61.8% | +4.7 [+3.2; +6.3] | 1.08× | 58.6% | +7.9 [+7.0; +8.9] | 1.14× |
| 12 (180 dk) | 87.8% [87.4; 88.2] | 86.4% | +1.3 [+0.3; +2.1] | 1.02× | 85.2% | +2.5 [+2.0; +3.0] | 1.03× |

12 bar içinde dönüş olan ön sinyallerde **medyan öncülük: 4 bar = 60 dk**; dağılım (bar 1…12, % toplamın): 15 13 11 14 13 10 8 2 4 4 3 3.
Tersi: kırmızı→yeşil dönüş barlarının **56.0%'inden önceki 12 barda ön sinyal var** (n=44189); dönüşe uygun HERHANGİ bir kırmızı barın önceki 12 barında ön sinyal olma oranı (taban) 55.5% → oran 1.01×. Dönüşten önceki son ön sinyal medyan 5 bar = 75 dk önce.

### 15m çekirdek / StochRSI K seviye 30 — W30 (17 Eyl–16 Eki)

Ön sinyal sayısı: **27955** (932/gün); kırmızı bar tabanı: 261845 bar; kırmızı+dip tabanı: 151854 bar.

| N bar (≈ dk) | P(dönüş \| ön sinyal) | taban 1 kırmızı | fark [%95] | oran | taban 2 kırmızı+dip | fark [%95] | oran |
|---|---|---|---|---|---|---|---|
| 1 (15 dk) | 13.9% [13.5; 14.3] | 16.9% | -2.9 [-3.7; -2.2] | 0.83× | 11.7% | +2.2 [+1.6; +2.8] | 1.19× |
| 3 (45 dk) | 35.9% [35.4; 36.5] | 39.0% | -3.1 [-4.3; -1.7] | 0.92× | 32.7% | +3.2 [+2.1; +4.2] | 1.10× |
| 6 (90 dk) | 67.6% [67.1; 68.2] | 61.8% | +5.8 [+4.4; +7.2] | 1.09× | 59.8% | +7.8 [+6.9; +8.6] | 1.13× |
| 12 (180 dk) | 88.1% [87.7; 88.5] | 86.4% | +1.6 [+0.9; +2.5] | 1.02× | 85.7% | +2.4 [+1.9; +2.9] | 1.03× |

12 bar içinde dönüş olan ön sinyallerde **medyan öncülük: 4 bar = 60 dk**; dağılım (bar 1…12, % toplamın): 16 14 11 14 13 9 7 2 4 4 3 3.
Tersi: kırmızı→yeşil dönüş barlarının **61.3%'inden önceki 12 barda ön sinyal var** (n=44189); dönüşe uygun HERHANGİ bir kırmızı barın önceki 12 barında ön sinyal olma oranı (taban) 59.8% → oran 1.02×. Dönüşten önceki son ön sinyal medyan 4 bar = 60 dk önce.

### Bloklara göre sağlamlık (fark = P(N bar içinde dönüş | ön sinyal) − kırmızı bar tabanı, yüzde puan [%95])

| çekirdek | seviye | N | B1 | B2 | B3 | W30 |
|---|---|---|---|---|---|---|
| 5m | 20 | 3 | -2.2 [-2.8; -1.4] | -2.2 [-3.0; -1.3] | -2.6 [-3.6; -1.8] | -2.6 [-3.5; -1.6] |
| 5m | 20 | 6 | +7.4 [+6.7; +8.1] | +8.5 [+7.7; +9.2] | +7.1 [+6.3; +8.0] | +7.1 [+6.3; +8.0] |
| 5m | 20 | 12 | +1.7 [+1.3; +2.2] | +2.2 [+1.9; +2.6] | +1.8 [+1.3; +2.3] | +1.8 [+1.3; +2.3] |
| 5m | 30 | 3 | -0.8 [-1.5; -0.1] | -0.8 [-1.6; -0.0] | -1.3 [-2.1; -0.4] | -1.2 [-2.1; -0.4] |
| 5m | 30 | 6 | +8.2 [+7.6; +8.9] | +9.3 [+8.6; +10.0] | +7.9 [+7.0; +8.7] | +7.9 [+7.1; +8.7] |
| 5m | 30 | 12 | +2.0 [+1.7; +2.4] | +2.5 [+2.1; +2.8] | +2.0 [+1.6; +2.5] | +2.0 [+1.5; +2.5] |
| 1m | 20 | 3 | +6.0 [+5.5; +6.4] | +5.4 [+4.8; +6.0] | +5.2 [+4.7; +5.6] | +5.2 [+4.8; +5.6] |
| 1m | 20 | 6 | +16.0 [+15.5; +16.5] | +15.2 [+14.6; +15.7] | +14.8 [+14.3; +15.2] | +14.8 [+14.3; +15.2] |
| 1m | 20 | 12 | +10.3 [+9.8; +11.0] | +9.3 [+8.8; +9.8] | +8.9 [+8.3; +9.4] | +8.8 [+8.3; +9.3] |
| 1m | 30 | 3 | +6.8 [+6.3; +7.2] | +6.1 [+5.6; +6.7] | +6.0 [+5.5; +6.4] | +6.0 [+5.5; +6.4] |
| 1m | 30 | 6 | +16.9 [+16.4; +17.4] | +15.9 [+15.4; +16.4] | +15.5 [+15.1; +15.9] | +15.5 [+15.0; +15.9] |
| 1m | 30 | 12 | +10.9 [+10.3; +11.5] | +9.7 [+9.2; +10.2] | +9.2 [+8.7; +9.8] | +9.2 [+8.7; +9.7] |
| 15m | 20 | 3 | -5.3 [-6.3; -4.3] | -5.7 [-7.0; -4.2] | -4.6 [-6.1; -3.2] | -4.7 [-6.2; -3.3] |
| 15m | 20 | 6 | +5.4 [+4.4; +6.4] | +6.1 [+4.8; +7.4] | +4.7 [+3.1; +6.5] | +4.7 [+2.9; +6.5] |
| 15m | 20 | 12 | +0.6 [+0.0; +1.1] | +0.6 [-0.1; +1.2] | +1.4 [+0.4; +2.2] | +1.3 [+0.5; +2.1] |
| 15m | 30 | 3 | -3.6 [-4.6; -2.7] | -3.9 [-5.1; -2.7] | -3.1 [-4.4; -1.6] | -3.1 [-4.3; -1.8] |
| 15m | 30 | 6 | +6.4 [+5.4; +7.4] | +7.1 [+5.9; +8.3] | +5.8 [+4.4; +7.3] | +5.8 [+4.4; +7.2] |
| 15m | 30 | 12 | +1.1 [+0.6; +1.5] | +1.0 [+0.4; +1.5] | +1.7 [+0.8; +2.5] | +1.6 [+0.8; +2.5] |

## 3. Çalışma A-2 — LUNA tipi erken yükselişler: ön sinyal [t0 − 30 dk, t0 + 5 dk] içinde çalıyor mu?

Olaylar: `work/pattern90/events.csv` (60 dk içinde ≥ +%4, ≥ %70 yeşil mum, geri çekilme ≤ %1,5; kümesiz birincil **4552** olay; t0 = koşunun ilk mumu). Rastgele: aynı sembol + aynı İstanbul günü, olay koşularından ±60 dk uzak, olay başına ≤ 40 beş-dakikalık an (olay başına ortalama alınır). Hit = pencerede en az bir sinyal. **Dikkat:** olay tanımı geleceğe bakar (t0 → +%4 yükseliş), olaylar küçük bir düşüşün diplerinden başlar; bu yüzden 'dip bölgesinde kesişim' olaylarda doğal olarak sık görünür — asıl sınav rastgele andan ayrışma + t0'dan ÖNCE (nedensel) pencere.

### 90 gün (07-20 → 10-16)

| çekirdek | sinyal | pencere | olay hit % | rastgele hit % | fark [%95] | oran [%95] | n olay |
|---|---|---|---|---|---|---|---|
| 5m | ön sinyal 20 | t0−30…+5 | 35.8 | 35.8 | -0.0 [-1.5; +1.4] | 1.00× [0.96; 1.04] | 4552 |
| 5m | ön sinyal 20 | t0−30…t0 (nedensel) | 26.3 | 32.2 | -6.0 [-7.3; -4.6] | 0.81× [0.77; 0.86] | 4552 |
| 5m | onaylı (≤6 bar) 20 | t0−30…+5 | 22.3 | 24.6 | -2.3 [-3.7; -1.1] | 0.91× [0.85; 0.95] | 4552 |
| 5m | onaylı (≤6 bar) 20 | t0−30…t0 (nedensel) | 17.0 | 21.6 | -4.6 [-5.8; -3.3] | 0.79× [0.73; 0.85] | 4552 |
| 5m | ön sinyal 30 | t0−30…+5 | 38.8 | 39.0 | -0.2 [-1.7; +1.3] | 0.99× [0.96; 1.03] | 4552 |
| 5m | ön sinyal 30 | t0−30…t0 (nedensel) | 29.2 | 35.1 | -5.9 [-7.2; -4.6] | 0.83× [0.80; 0.87] | 4552 |
| 5m | onaylı (≤6 bar) 30 | t0−30…+5 | 25.0 | 27.0 | -2.0 [-3.4; -0.6] | 0.93× [0.87; 0.98] | 4552 |
| 5m | onaylı (≤6 bar) 30 | t0−30…t0 (nedensel) | 19.0 | 23.7 | -4.6 [-6.0; -3.2] | 0.81× [0.75; 0.86] | 4552 |
| 1m | ön sinyal 20 | t0−30…+5 | 87.3 | 81.0 | +6.3 [+5.3; +7.4] | 1.08× [1.07; 1.09] | 4552 |
| 1m | ön sinyal 20 | t0−30…t0 (nedensel) | 82.0 | 76.1 | +5.9 [+4.8; +7.2] | 1.08× [1.06; 1.10] | 4552 |
| 1m | onaylı (≤6 bar) 20 | t0−30…+5 | 78.3 | 69.2 | +9.0 [+7.8; +10.4] | 1.13× [1.11; 1.15] | 4552 |
| 1m | onaylı (≤6 bar) 20 | t0−30…t0 (nedensel) | 63.9 | 63.8 | +0.2 [-1.2; +1.5] | 1.00× [0.98; 1.02] | 4552 |
| 1m | ön sinyal 30 | t0−30…+5 | 89.3 | 83.6 | +5.6 [+4.8; +6.5] | 1.07× [1.06; 1.08] | 4552 |
| 1m | ön sinyal 30 | t0−30…t0 (nedensel) | 84.6 | 79.2 | +5.5 [+4.4; +6.5] | 1.07× [1.06; 1.08] | 4552 |
| 1m | onaylı (≤6 bar) 30 | t0−30…+5 | 81.9 | 73.1 | +8.7 [+7.6; +9.9] | 1.12× [1.10; 1.14] | 4552 |
| 1m | onaylı (≤6 bar) 30 | t0−30…t0 (nedensel) | 68.4 | 67.9 | +0.5 [-1.1; +2.0] | 1.01× [0.98; 1.03] | 4552 |
| 15m | ön sinyal 20 | t0−30…+5 | 11.6 | 13.8 | -2.2 [-3.2; -1.2] | 0.84× [0.77; 0.91] | 4552 |
| 15m | ön sinyal 20 | t0−30…t0 (nedensel) | 9.9 | 12.1 | -2.2 [-3.2; -1.4] | 0.82× [0.74; 0.89] | 4552 |
| 15m | onaylı (≤6 bar) 20 | t0−30…+5 | 6.9 | 7.6 | -0.8 [-1.6; +0.1] | 0.90× [0.80; 1.01] | 4552 |
| 15m | onaylı (≤6 bar) 20 | t0−30…t0 (nedensel) | 5.8 | 6.7 | -0.9 [-1.6; -0.2] | 0.87× [0.76; 0.97] | 4552 |
| 15m | ön sinyal 30 | t0−30…+5 | 12.3 | 15.0 | -2.7 [-3.7; -1.8] | 0.82× [0.76; 0.88] | 4552 |
| 15m | ön sinyal 30 | t0−30…t0 (nedensel) | 10.5 | 13.2 | -2.6 [-3.5; -1.7] | 0.80× [0.73; 0.87] | 4552 |
| 15m | onaylı (≤6 bar) 30 | t0−30…+5 | 7.4 | 8.3 | -0.9 [-1.7; -0.2] | 0.89× [0.79; 0.98] | 4552 |
| 15m | onaylı (≤6 bar) 30 | t0−30…t0 (nedensel) | 6.3 | 7.2 | -1.0 [-1.7; -0.3] | 0.87× [0.77; 0.96] | 4552 |
| 5m | çekirdek AL dönüşü (referans) | t0−30…+5 | 56.2 | 55.0 | +1.3 [-0.2; +2.9] | 1.02× [1.00; 1.05] | 4552 |
| 5m | çekirdek AL dönüşü (referans) | t0−30…t0 (nedensel) | 42.9 | 49.9 | -7.0 [-8.5; -5.4] | 0.86× [0.83; 0.89] | 4552 |
| 1m | çekirdek AL dönüşü (referans) | t0−30…+5 | 99.5 | 98.2 | +1.3 [+1.0; +1.5] | 1.01× [1.01; 1.02] | 4552 |
| 1m | çekirdek AL dönüşü (referans) | t0−30…t0 (nedensel) | 96.5 | 96.9 | -0.4 [-1.0; +0.1] | 1.00× [0.99; 1.00] | 4552 |
| 15m | çekirdek AL dönüşü (referans) | t0−30…+5 | 19.5 | 21.0 | -1.5 [-2.7; -0.2] | 0.93× [0.87; 0.99] | 4552 |
| 15m | çekirdek AL dönüşü (referans) | t0−30…t0 (nedensel) | 16.9 | 18.6 | -1.6 [-2.7; -0.3] | 0.91× [0.85; 0.98] | 4552 |

### W30 (t0 17 Eyl–16 Eki)

| çekirdek | sinyal | pencere | olay hit % | rastgele hit % | fark [%95] | oran [%95] | n olay |
|---|---|---|---|---|---|---|---|
| 5m | ön sinyal 20 | t0−30…+5 | 36.8 | 36.4 | +0.3 [-1.5; +2.0] | 1.01× [0.96; 1.05] | 1869 |
| 5m | ön sinyal 20 | t0−30…t0 (nedensel) | 28.2 | 32.8 | -4.6 [-6.3; -2.9] | 0.86× [0.81; 0.91] | 1869 |
| 5m | onaylı (≤6 bar) 20 | t0−30…+5 | 24.0 | 25.2 | -1.2 [-3.2; +0.7] | 0.95× [0.87; 1.03] | 1869 |
| 5m | onaylı (≤6 bar) 20 | t0−30…t0 (nedensel) | 18.6 | 22.1 | -3.5 [-5.5; -1.5] | 0.84× [0.75; 0.93] | 1869 |
| 5m | ön sinyal 30 | t0−30…+5 | 39.3 | 39.6 | -0.3 [-2.6; +1.6] | 0.99× [0.93; 1.04] | 1869 |
| 5m | ön sinyal 30 | t0−30…t0 (nedensel) | 30.7 | 35.6 | -4.9 [-6.8; -3.2] | 0.86× [0.81; 0.91] | 1869 |
| 5m | onaylı (≤6 bar) 30 | t0−30…+5 | 26.1 | 27.5 | -1.4 [-3.4; +0.7] | 0.95× [0.88; 1.02] | 1869 |
| 5m | onaylı (≤6 bar) 30 | t0−30…t0 (nedensel) | 20.1 | 24.2 | -4.1 [-6.2; -1.9] | 0.83× [0.75; 0.92] | 1869 |
| 1m | ön sinyal 20 | t0−30…+5 | 86.4 | 80.3 | +6.0 [+4.4; +7.8] | 1.08× [1.06; 1.10] | 1869 |
| 1m | ön sinyal 20 | t0−30…t0 (nedensel) | 81.6 | 75.3 | +6.3 [+4.5; +8.3] | 1.08× [1.06; 1.11] | 1869 |
| 1m | onaylı (≤6 bar) 20 | t0−30…+5 | 77.6 | 68.2 | +9.4 [+7.8; +11.4] | 1.14× [1.11; 1.17] | 1869 |
| 1m | onaylı (≤6 bar) 20 | t0−30…t0 (nedensel) | 63.5 | 62.7 | +0.8 [-1.2; +2.8] | 1.01× [0.98; 1.04] | 1869 |
| 1m | ön sinyal 30 | t0−30…+5 | 88.0 | 82.8 | +5.2 [+3.8; +6.9] | 1.06× [1.05; 1.08] | 1869 |
| 1m | ön sinyal 30 | t0−30…t0 (nedensel) | 84.1 | 78.2 | +5.8 [+4.2; +7.7] | 1.07× [1.05; 1.10] | 1869 |
| 1m | onaylı (≤6 bar) 30 | t0−30…+5 | 80.7 | 72.0 | +8.8 [+7.3; +10.7] | 1.12× [1.10; 1.15] | 1869 |
| 1m | onaylı (≤6 bar) 30 | t0−30…t0 (nedensel) | 67.5 | 66.7 | +0.8 [-1.1; +2.8] | 1.01× [0.98; 1.04] | 1869 |
| 15m | ön sinyal 20 | t0−30…+5 | 11.7 | 13.9 | -2.2 [-3.6; -0.9] | 0.84× [0.74; 0.94] | 1869 |
| 15m | ön sinyal 20 | t0−30…t0 (nedensel) | 10.1 | 12.1 | -2.0 [-3.3; -0.7] | 0.83× [0.73; 0.94] | 1869 |
| 15m | onaylı (≤6 bar) 20 | t0−30…+5 | 6.5 | 7.8 | -1.3 [-2.7; +0.0] | 0.83× [0.66; 1.00] | 1869 |
| 15m | onaylı (≤6 bar) 20 | t0−30…t0 (nedensel) | 5.1 | 6.8 | -1.7 [-2.8; -0.6] | 0.75× [0.59; 0.91] | 1869 |
| 15m | ön sinyal 30 | t0−30…+5 | 12.5 | 15.1 | -2.6 [-4.0; -0.9] | 0.83× [0.74; 0.94] | 1869 |
| 15m | ön sinyal 30 | t0−30…t0 (nedensel) | 10.9 | 13.2 | -2.3 [-3.7; -1.0] | 0.82× [0.72; 0.92] | 1869 |
| 15m | onaylı (≤6 bar) 30 | t0−30…+5 | 7.0 | 8.5 | -1.5 [-2.8; +0.0] | 0.82× [0.67; 1.00] | 1869 |
| 15m | onaylı (≤6 bar) 30 | t0−30…t0 (nedensel) | 5.5 | 7.3 | -1.8 [-2.8; -0.7] | 0.75× [0.62; 0.90] | 1869 |
| 5m | çekirdek AL dönüşü (referans) | t0−30…+5 | 56.1 | 54.7 | +1.5 [-0.6; +3.5] | 1.03× [0.99; 1.06] | 1869 |
| 5m | çekirdek AL dönüşü (referans) | t0−30…t0 (nedensel) | 43.1 | 49.6 | -6.5 [-8.9; -4.0] | 0.87× [0.82; 0.92] | 1869 |
| 1m | çekirdek AL dönüşü (referans) | t0−30…+5 | 99.4 | 98.2 | +1.2 [+0.9; +1.6] | 1.01× [1.01; 1.02] | 1869 |
| 1m | çekirdek AL dönüşü (referans) | t0−30…t0 (nedensel) | 96.5 | 96.9 | -0.4 [-1.4; +0.5] | 1.00× [0.99; 1.01] | 1869 |
| 15m | çekirdek AL dönüşü (referans) | t0−30…+5 | 19.5 | 21.4 | -1.9 [-3.8; -0.1] | 0.91× [0.83; 1.00] | 1869 |
| 15m | çekirdek AL dönüşü (referans) | t0−30…t0 (nedensel) | 16.5 | 18.8 | -2.3 [-4.2; -0.7] | 0.88× [0.78; 0.96] | 1869 |

### Öncülük süresi (dk) — 90 gün; yalnız pencerede sinyali olan olaylar

| çekirdek | sinyal | hit olay | t0'a göre İLK sinyal (dk önce) medyan [Q1–Q3] | t0'dan önceki SON sinyal (dk önce) medyan | t0 sonrası ilk çekirdek AL dönüşü (dk sonra) medyan |
|---|---|---|---|---|---|
| 5m | ön sinyal 20 | 1630 | 15 [-5–25] | 15 | 10 |
| 5m | ön sinyal 30 | 1765 | 15 [0–25] | 15 | 10 |
| 1m | ön sinyal 20 | 3976 | 18 [9–25] | 8 | 2 |
| 1m | ön sinyal 30 | 4063 | 19 [10–25] | 7 | 2 |
| 15m | ön sinyal 20 | 530 | 15 [5–25] | 15 | 25 |
| 15m | ön sinyal 30 | 562 | 15 [5–25] | 15 | 25 |

Okuma: ilk sinyal dk önce > 0 → t0'dan ÖNCE (öncü); negatif → yükseliş başladıktan sonra. Çekirdek AL dönüşü sütunu ölçülen gecikmedir (RQK analizi: yükselişten sonra döner).

### LUNATRY 17 Ekim 01:00 (t0; +%8 / 60 dk) sağlama

t0 = 01:00; P0 (t0 öncesi son 1 dk kapanışı) = 2.176; yükseliş: 60 dk sonra 2.35 (+8.00%).

| çekirdek | sinyal | zaman (İstanbul) | t0'a göre (dk) | kapanış fiyatı / P0 |
|---|---|---|---|---|
| 5m | ön sinyal (K<20) | 02:30 | +90 | 1.0432 |
| 5m | ön sinyal (K<30) | 02:30 | +90 | 1.0432 |
| 5m | ön sinyal (K<20) | 02:45 | +105 | 1.0377 |
| 5m | ön sinyal (K<30) | 02:45 | +105 | 1.0377 |
| 5m | çekirdek AL dönüşü | 02:50 | +110 | 1.0460 |
| 5m | çekirdek AL dönüşü | 03:00 | +120 | 1.0496 |
| 1m | çekirdek AL dönüşü | 00:22 | -38 | 0.9986 |
| 1m | çekirdek AL dönüşü | 00:35 | -25 | 1.0028 |
| 1m | ön sinyal (K<20) | 00:44 | -16 | 1.0014 |
| 1m | ön sinyal (K<30) | 00:44 | -16 | 1.0014 |
| 1m | çekirdek AL dönüşü | 00:48 | -12 | 1.0009 |
| 1m | ön sinyal (K<20) | 00:58 | -2 | 0.9995 |
| 1m | ön sinyal (K<30) | 00:58 | -2 | 0.9995 |
| 1m | çekirdek AL dönüşü | 01:02 | +2 | 1.0005 |
| 1m | çekirdek AL dönüşü | 01:20 | +20 | 1.0207 |
| 15m | (pencerede yok) | | | |


## 4. Çalışma A-3 — Ön sinyal / onaylı sinyal GİRİŞ sinyali olarak (gerçekçi doluş)

Sinyal: ön sinyal = bar kapanışında (çekirdek kırmızı + K/D yukarı kesişimi, K[i-1] < seviye). **Onaylı** = ön sinyalden sonraki 6 bar içinde çekirdek AL dönüşü; sinyal DÖNÜŞ barının kapanışında. Aynı sembolde 60 dk tekilleştirme; likit sembol (24 sa ≥ 5M TRY). Giriş: sinyal + 60 sn sonraki ilk 1 dk açılışı × (1 + %0,15) (birincil); bacak başına %0,1125 ücret (maker = taker, bkz. Yöntem). Çıkış kümesi 24 hücre: sabit TP {1,0; 1,5} × SL {1,5; 3} × zaman {60; 120}; izleyen tetik {0,5; 1,0} × iz {0,4; 0,8} × SL {1,5; 3} × zaman {60; 120}. Rastgele tabanlar: (1) istenen: aynı sembol + saat dilimi + blok, herhangi bir HAM sinyalden ≥ 2 sa uzak; (2) oynaklık eşleşmeli (son 30 dk aralığı ±%25), ≥ 2 sa; (3) aynı sembol/saat, **dışlamasız**; (4) oynaklık eşleşmeli + dışlamasız. Tüm net değerler %/işlem (ücret + kayma dâhil); [aralık] = gün-kümeli %95.

**Taban notu:** (1) ve (2)'nin 'herhangi bir sinyalden ≥ 2 sa uzak' koşulu tabanı yukarı yanlılaştırabilir — ön sinyaller düşüşlerin sonunda çaldığı için sinyalsiz saatler çoğunlukla sakin yükseliş / pompa dönemleridir, bu yüzden rastgele (1) bazı kümelerde sinyalden DAHA iyi çıkar. Adil kıyas için dışlamasız (3)/(4) de verilir; karar her ikisine göre okunmalı.

### 4.1 Sinyal sıklığı ve hit60@1,5 (60 dk içinde en yüksek ≥ giriş açılışı +%1,5) — W30

| küme | sinyal (n) | /gün | hit60@1,5 sinyal | taban 1 | taban 2 | taban 3 | taban 4 | şans yükselişi (sinyal/taban 4) | pp farkı (sinyal−taban 4) | brüt 60 dk getiri: sinyal / taban 4 |
|---|---|---|---|---|---|---|---|---|---|---|
| 5m|20|pre | 47575 | 1586 | 13.8% | 22.4% | 24.8% | 14.2% | 15.6% | 0.88× | -1.8 | +0.004% / -0.003% |
| 5m|20|conf | 39672 | 1322 | 13.8% | 16.9% | 16.7% | 14.3% | 13.6% | 1.02× | +0.2 | -0.025% / +0.015% |
| 5m|30|pre | 51139 | 1705 | 13.7% | 23.0% | 25.4% | 14.6% | 15.5% | 0.89× | -1.8 | +0.004% / -0.002% |
| 5m|30|conf | 43278 | 1443 | 13.8% | 17.2% | 16.5% | 14.5% | 13.5% | 1.02× | +0.3 | -0.023% / +0.020% |
| 1m|20|pre | 85092 | 2836 | 15.2% | 16.1% | 17.1% | 14.3% | 14.8% | 1.03× | +0.4 | +0.007% / +0.003% |
| 1m|20|conf | 72331 | 2411 | 15.4% | 11.5% | 11.9% | 14.6% | 15.1% | 1.02× | +0.3 | -0.009% / +0.004% |
| 1m|30|pre | 86902 | 2897 | 15.1% | 15.9% | 17.0% | 14.5% | 14.8% | 1.02× | +0.3 | +0.006% / +0.001% |
| 1m|30|conf | 74644 | 2488 | 15.4% | 11.7% | 11.7% | 14.6% | 15.1% | 1.02× | +0.3 | -0.010% / -0.004% |
| 15m|20|pre | 23943 | 798 | 13.7% | 18.4% | 17.7% | 14.9% | 13.7% | 1.00× | -0.0 | -0.012% / +0.003% |
| 15m|20|conf | 15242 | 508 | 14.3% | 13.6% | 12.9% | 14.7% | 14.6% | 0.98× | -0.3 | -0.020% / +0.005% |
| 15m|30|pre | 26447 | 882 | 13.6% | 19.2% | 18.3% | 14.9% | 13.4% | 1.01× | +0.2 | -0.009% / -0.000% |
| 15m|30|conf | 16999 | 567 | 14.1% | 13.1% | 13.0% | 14.1% | 14.5% | 0.97× | -0.5 | -0.023% / +0.002% |

### 4.2a Net sonuç — W30, senaryo 60 sn gecikme / %0,15 kayma (BİRİNCİL)

Çıkış hücresi, sinyal kümesinin W30 ortalama neti en yüksek olandır (**iç-örneklem, iyimser**); yanında aynı hücrenin tabanlardaki neti ve fark.

| küme | 24 çıkışın ort. neti | net>0 çıkış sayısı | en iyi çıkış (iç-örneklem) | net sinyal [%95] | kazanma % | taban 1 (aynı çıkış) | taban 4 (aynı çıkış) | fark vs taban 1 | fark vs taban 4 |
|---|---|---|---|---|---|---|---|---|---|
| 5m|20|pre | -0.51 | 0/24 | fixed TP1 SL3 T120 | -0.49 [-0.58; -0.41] | 39.7 | +0.11 | -0.49 | -0.61 [-0.71; -0.50] | -0.00 [-0.10; +0.10] |
| 5m|20|conf | -0.54 | 0/24 | fixed TP1.5 SL3 T120 | -0.52 [-0.61; -0.44] | 33.7 | -0.40 | -0.48 | -0.13 [-0.26; -0.00] | -0.05 [-0.15; +0.06] |
| 5m|30|pre | -0.51 | 0/24 | fixed TP1 SL3 T120 | -0.50 [-0.58; -0.42] | 39.7 | +0.09 | -0.49 | -0.59 [-0.69; -0.49] | -0.00 [-0.10; +0.10] |
| 5m|30|conf | -0.53 | 0/24 | fixed TP1.5 SL3 T120 | -0.52 [-0.60; -0.44] | 33.9 | -0.42 | -0.48 | -0.10 [-0.23; +0.03] | -0.04 [-0.15; +0.07] |
| 1m|20|pre | -0.50 | 0/24 | fixed TP1 SL3 T120 | -0.48 [-0.54; -0.42] | 41.1 | -0.25 | -0.49 | -0.23 [-0.31; -0.15] | +0.01 [-0.07; +0.10] |
| 1m|20|conf | -0.51 | 0/24 | fixed TP1 SL3 T120 | -0.50 [-0.56; -0.44] | 40.8 | -0.44 | -0.49 | -0.06 [-0.15; +0.03] | -0.01 [-0.09; +0.08] |
| 1m|30|pre | -0.50 | 0/24 | fixed TP1 SL3 T120 | -0.48 [-0.54; -0.42] | 41.0 | -0.25 | -0.49 | -0.23 [-0.31; -0.15] | +0.01 [-0.07; +0.09] |
| 1m|30|conf | -0.51 | 0/24 | fixed TP1 SL3 T120 | -0.50 [-0.56; -0.44] | 40.8 | -0.43 | -0.49 | -0.07 [-0.16; +0.02] | -0.01 [-0.09; +0.08] |
| 15m|20|pre | -0.52 | 0/24 | fixed TP1.5 SL1.5 T120 | -0.52 [-0.59; -0.44] | 32.5 | -0.27 | -0.48 | -0.24 [-0.33; -0.16] | -0.03 [-0.13; +0.06] |
| 15m|20|conf | -0.52 | 0/24 | trail act0.5 gap0.8 SL3 T120 | -0.48 [-0.56; -0.41] | 27.9 | -0.65 | -0.50 | +0.16 [+0.05; +0.27] | +0.01 [-0.08; +0.11] |
| 15m|30|pre | -0.52 | 0/24 | fixed TP1.5 SL1.5 T120 | -0.51 [-0.59; -0.44] | 32.5 | -0.26 | -0.49 | -0.25 [-0.34; -0.16] | -0.02 [-0.11; +0.07] |
| 15m|30|conf | -0.52 | 0/24 | trail act0.5 gap0.8 SL3 T120 | -0.48 [-0.55; -0.41] | 28.0 | -0.68 | -0.50 | +0.20 [+0.09; +0.31] | +0.02 [-0.07; +0.10] |

### 4.2b Net sonuç — W30, senaryo 0 sn / %0,05 kayma (iyimser)

Çıkış hücresi, sinyal kümesinin W30 ortalama neti en yüksek olandır (**iç-örneklem, iyimser**); yanında aynı hücrenin tabanlardaki neti ve fark.

| küme | 24 çıkışın ort. neti | net>0 çıkış sayısı | en iyi çıkış (iç-örneklem) | net sinyal [%95] | kazanma % | taban 1 (aynı çıkış) | taban 4 (aynı çıkış) | fark vs taban 1 | fark vs taban 4 |
|---|---|---|---|---|---|---|---|---|---|
| 5m|20|pre | -0.32 | 0/24 | trail act1 gap0.8 SL3 T120 | -0.30 [-0.39; -0.22] | 41.4 | +0.41 | -0.30 | -0.71 [-0.83; -0.59] | -0.00 [-0.11; +0.11] |
| 5m|20|conf | -0.35 | 0/24 | trail act1 gap0.8 SL1.5 T120 | -0.33 [-0.40; -0.27] | 38.2 | -0.14 | -0.29 | -0.20 [-0.31; -0.08] | -0.04 [-0.13; +0.05] |
| 5m|30|pre | -0.32 | 0/24 | trail act1 gap0.8 SL3 T120 | -0.30 [-0.39; -0.22] | 41.3 | +0.37 | -0.30 | -0.68 [-0.79; -0.56] | -0.01 [-0.11; +0.10] |
| 5m|30|conf | -0.34 | 0/24 | trail act1 gap0.8 SL1.5 T120 | -0.33 [-0.39; -0.26] | 38.4 | -0.15 | -0.29 | -0.17 [-0.28; -0.06] | -0.04 [-0.13; +0.05] |
| 1m|20|pre | -0.31 | 0/24 | trail act1 gap0.8 SL3 T120 | -0.29 [-0.36; -0.23] | 42.3 | -0.01 | -0.30 | -0.29 [-0.38; -0.19] | +0.00 [-0.09; +0.10] |
| 1m|20|conf | -0.32 | 0/24 | trail act0.5 gap0.8 SL1.5 T120 | -0.31 [-0.35; -0.26] | 33.8 | -0.21 | -0.30 | -0.09 [-0.16; -0.02] | -0.01 [-0.07; +0.06] |
| 1m|30|pre | -0.31 | 0/24 | trail act1 gap0.8 SL3 T120 | -0.30 [-0.36; -0.23] | 42.2 | -0.01 | -0.30 | -0.29 [-0.38; -0.20] | +0.00 [-0.09; +0.09] |
| 1m|30|conf | -0.32 | 0/24 | trail act0.5 gap0.8 SL1.5 T120 | -0.31 [-0.35; -0.26] | 33.8 | -0.20 | -0.30 | -0.10 [-0.18; -0.03] | -0.01 [-0.07; +0.06] |
| 15m|20|pre | -0.33 | 0/24 | trail act0.5 gap0.8 SL1.5 T60 | -0.32 [-0.38; -0.26] | 31.4 | -0.11 | -0.31 | -0.20 [-0.27; -0.14] | -0.01 [-0.08; +0.06] |
| 15m|20|conf | -0.32 | 0/24 | trail act0.5 gap0.8 SL3 T120 | -0.28 [-0.35; -0.21] | 34.5 | -0.44 | -0.30 | +0.16 [+0.05; +0.27] | +0.02 [-0.08; +0.11] |
| 15m|30|pre | -0.33 | 0/24 | trail act0.5 gap0.8 SL1.5 T120 | -0.32 [-0.39; -0.25] | 33.6 | -0.08 | -0.30 | -0.24 [-0.32; -0.15] | -0.01 [-0.10; +0.07] |
| 15m|30|conf | -0.32 | 0/24 | trail act0.5 gap0.8 SL3 T120 | -0.28 [-0.35; -0.21] | 34.6 | -0.48 | -0.30 | +0.20 [+0.09; +0.31] | +0.02 [-0.07; +0.11] |

### 4.3 Üç 30 günlük blok (sağlamlık) — senaryo P; her blokta kümenin EN İYİ çıkışı (iç-blok, iyimser)

| küme | B1 (20 Tem–18 Ağu) | B2 (19 Ağu–17 Eyl) | B3 (18 Eyl–16 Eki) | sinyal/gün B1 / B2 / B3 |
|---|---|---|---|---|
| 5m|20|pre | -0.47 (fixed TP1 SL3 T120; taban 4 -0.50; >0: 0/24) | -0.41 (fixed TP1.5 SL3 T120; taban 4 -0.46; >0: 0/24) | -0.50 (fixed TP1 SL3 T120; taban 4 -0.50; >0: 0/24) | 534 / 689 / 1565 |
| 5m|20|conf | -0.51 (trail act0.5 gap0.4 SL3 T120; taban 4 -0.49; >0: 0/24) | -0.48 (fixed TP1 SL3 T120; taban 4 -0.45; >0: 0/24) | -0.53 (fixed TP1.5 SL3 T120; taban 4 -0.48; >0: 0/24) | 447 / 591 / 1304 |
| 5m|30|pre | -0.47 (fixed TP1 SL3 T120; taban 4 -0.48; >0: 0/24) | -0.42 (fixed TP1.5 SL3 T120; taban 4 -0.45; >0: 0/24) | -0.50 (fixed TP1 SL3 T120; taban 4 -0.50; >0: 0/24) | 578 / 741 / 1682 |
| 5m|30|conf | -0.51 (fixed TP1 SL3 T120; taban 4 -0.50; >0: 0/24) | -0.48 (fixed TP1 SL3 T120; taban 4 -0.44; >0: 0/24) | -0.52 (fixed TP1.5 SL3 T120; taban 4 -0.48; >0: 0/24) | 489 / 643 / 1423 |
| 1m|20|pre | -0.49 (fixed TP1 SL3 T120; taban 4 -0.49; >0: 0/24) | -0.45 (fixed TP1 SL3 T120; taban 4 -0.46; >0: 0/24) | -0.48 (fixed TP1 SL3 T120; taban 4 -0.49; >0: 0/24) | 954 / 1237 / 2799 |
| 1m|20|conf | -0.50 (fixed TP1 SL3 T120; taban 4 -0.50; >0: 0/24) | -0.46 (fixed TP1 SL3 T120; taban 4 -0.46; >0: 0/24) | -0.50 (fixed TP1 SL3 T120; taban 4 -0.49; >0: 0/24) | 785 / 1040 / 2380 |
| 1m|30|pre | -0.49 (fixed TP1.5 SL3 T120; taban 4 -0.49; >0: 0/24) | -0.45 (fixed TP1.5 SL3 T120; taban 4 -0.44; >0: 0/24) | -0.48 (fixed TP1 SL3 T120; taban 4 -0.50; >0: 0/24) | 977 / 1265 / 2859 |
| 1m|30|conf | -0.50 (fixed TP1 SL3 T120; taban 4 -0.49; >0: 0/24) | -0.45 (fixed TP1 SL3 T120; taban 4 -0.45; >0: 0/24) | -0.50 (fixed TP1 SL3 T120; taban 4 -0.50; >0: 0/24) | 814 / 1076 / 2456 |
| 15m|20|pre | -0.49 (fixed TP1.5 SL3 T120; taban 4 -0.52; >0: 0/24) | -0.45 (fixed TP1 SL3 T120; taban 4 -0.46; >0: 0/24) | -0.52 (trail act0.5 gap0.8 SL1.5 T60; taban 4 -0.51; >0: 0/24) | 269 / 337 / 790 |
| 15m|20|conf | -0.55 (trail act0.5 gap0.4 SL3 T60; taban 4 -0.51; >0: 0/24) | -0.47 (fixed TP1.5 SL3 T120; taban 4 -0.45; >0: 0/24) | -0.49 (trail act0.5 gap0.8 SL3 T120; taban 4 -0.50; >0: 0/24) | 176 / 228 / 502 |
| 15m|30|pre | -0.49 (fixed TP1.5 SL3 T120; taban 4 -0.48; >0: 0/24) | -0.45 (fixed TP1 SL3 T120; taban 4 -0.45; >0: 0/24) | -0.52 (trail act0.5 gap0.8 SL1.5 T120; taban 4 -0.50; >0: 0/24) | 300 / 374 / 873 |
| 15m|30|conf | -0.55 (fixed TP1.5 SL3 T60; taban 4 -0.52; >0: 0/24) | -0.48 (fixed TP1.5 SL3 T120; taban 4 -0.47; >0: 0/24) | -0.48 (trail act0.5 gap0.8 SL3 T120; taban 4 -0.50; >0: 0/24) | 197 / 253 / 560 |

### 4.4 Yürüyen-ileri (bir blokta çıkış seç → diğer bloklarda DOKUNMADAN ölç), senaryo P

Seçim: eğitim bloğunda sinyal ortalama neti en yüksek çıkış (n ≥ 100). Sütunlar: OOS net sinyal [%95]; taban 1 / taban 4 aynı çıkış; fark (sinyal − taban 4) [%95].

| küme | eğitim → test | seçilen çıkış | OOS net sinyal [%95] | taban 1 | taban 4 | sinyal−taban 4 [%95] |
|---|---|---|---|---|---|---|
| 5m|20|pre | B1 → B2 | fixed TP1 SL3 T120 | -0.41 [-0.47; -0.36] | +0.11 | -0.46 | +0.05 [-0.04; +0.14] |
| 5m|20|pre | B1 → B3 | fixed TP1 SL3 T120 | -0.50 [-0.58; -0.42] | +0.11 | -0.50 | -0.00 [-0.11; +0.10] |
| 5m|20|pre | B2 → B1 | fixed TP1.5 SL3 T120 | -0.47 [-0.51; -0.44] | -0.04 | -0.50 | +0.03 [-0.03; +0.08] |
| 5m|20|pre | B2 → B3 | fixed TP1.5 SL3 T120 | -0.50 [-0.59; -0.41] | +0.20 | -0.50 | -0.00 [-0.11; +0.11] |
| 5m|20|pre | B3 → B1 | fixed TP1 SL3 T120 | -0.47 [-0.50; -0.43] | -0.08 | -0.50 | +0.03 [-0.02; +0.08] |
| 5m|20|pre | B3 → B2 | fixed TP1 SL3 T120 | -0.41 [-0.47; -0.36] | +0.11 | -0.46 | +0.05 [-0.04; +0.14] |
| 5m|20|conf | B1 → B2 | trail act0.5 gap0.4 SL3 T120 | -0.50 [-0.55; -0.44] | -0.38 | -0.46 | -0.04 [-0.12; +0.04] |
| 5m|20|conf | B1 → B3 | trail act0.5 gap0.4 SL3 T120 | -0.54 [-0.61; -0.47] | -0.43 | -0.49 | -0.05 [-0.14; +0.04] |
| 5m|20|conf | B2 → B1 | fixed TP1 SL3 T120 | -0.51 [-0.54; -0.48] | -0.42 | -0.49 | -0.03 [-0.07; +0.02] |
| 5m|20|conf | B2 → B3 | fixed TP1 SL3 T120 | -0.53 [-0.61; -0.45] | -0.42 | -0.48 | -0.05 [-0.15; +0.05] |
| 5m|20|conf | B3 → B1 | fixed TP1.5 SL3 T120 | -0.53 [-0.56; -0.49] | -0.42 | -0.48 | -0.04 [-0.09; +0.01] |
| 5m|20|conf | B3 → B2 | fixed TP1.5 SL3 T120 | -0.48 [-0.56; -0.41] | -0.30 | -0.44 | -0.05 [-0.15; +0.06] |
| 5m|30|pre | B1 → B2 | fixed TP1 SL3 T120 | -0.42 [-0.48; -0.36] | +0.10 | -0.45 | +0.03 [-0.06; +0.12] |
| 5m|30|pre | B1 → B3 | fixed TP1 SL3 T120 | -0.50 [-0.58; -0.42] | +0.09 | -0.50 | -0.00 [-0.10; +0.10] |
| 5m|30|pre | B2 → B1 | fixed TP1.5 SL3 T120 | -0.47 [-0.51; -0.44] | -0.03 | -0.49 | +0.01 [-0.04; +0.07] |
| 5m|30|pre | B2 → B3 | fixed TP1.5 SL3 T120 | -0.50 [-0.59; -0.42] | +0.18 | -0.50 | -0.00 [-0.11; +0.10] |
| 5m|30|pre | B3 → B1 | fixed TP1 SL3 T120 | -0.47 [-0.50; -0.43] | -0.07 | -0.48 | +0.01 [-0.04; +0.07] |
| 5m|30|pre | B3 → B2 | fixed TP1 SL3 T120 | -0.42 [-0.48; -0.36] | +0.10 | -0.45 | +0.03 [-0.06; +0.12] |
| 5m|30|conf | B1 → B2 | fixed TP1 SL3 T120 | -0.48 [-0.55; -0.42] | -0.35 | -0.44 | -0.04 [-0.13; +0.05] |
| 5m|30|conf | B1 → B3 | fixed TP1 SL3 T120 | -0.53 [-0.60; -0.45] | -0.44 | -0.48 | -0.04 [-0.14; +0.06] |
| 5m|30|conf | B2 → B1 | fixed TP1 SL3 T120 | -0.51 [-0.54; -0.48] | -0.42 | -0.50 | -0.01 [-0.06; +0.03] |
| 5m|30|conf | B2 → B3 | fixed TP1 SL3 T120 | -0.53 [-0.60; -0.45] | -0.44 | -0.48 | -0.04 [-0.14; +0.06] |
| 5m|30|conf | B3 → B1 | fixed TP1.5 SL3 T120 | -0.52 [-0.55; -0.48] | -0.41 | -0.50 | -0.02 [-0.07; +0.03] |
| 5m|30|conf | B3 → B2 | fixed TP1.5 SL3 T120 | -0.49 [-0.56; -0.42] | -0.33 | -0.44 | -0.05 [-0.15; +0.06] |

**Yürüyen-ileri özeti (12 küme × 6 eğitim→test çifti):**

| küme | OOS net>0 satır | OOS net %95 alt sınırı >0 | OOS ort. net | sinyal−taban 4 alt sınırı >0 | sinyal−taban 4 ort. |
|---|---|---|---|---|---|
| 5m|20|pre | 0/6 | 0 | -0.46 | 0 | +0.02 |
| 5m|20|conf | 0/6 | 0 | -0.52 | 0 | -0.04 |
| 5m|30|pre | 0/6 | 0 | -0.46 | 0 | +0.01 |
| 5m|30|conf | 0/6 | 0 | -0.51 | 0 | -0.04 |
| 1m|20|pre | 0/6 | 0 | -0.47 | 0 | +0.01 |
| 1m|20|conf | 0/6 | 0 | -0.49 | 0 | -0.00 |
| 1m|30|pre | 0/6 | 0 | -0.47 | 0 | +0.00 |
| 1m|30|conf | 0/6 | 0 | -0.49 | 0 | -0.01 |
| 15m|20|pre | 0/6 | 0 | -0.50 | 0 | -0.00 |
| 15m|20|conf | 0/6 | 0 | -0.53 | 0 | -0.04 |
| 15m|30|pre | 0/6 | 0 | -0.50 | 0 | -0.01 |
| 15m|30|conf | 0/6 | 0 | -0.53 | 0 | -0.02 |
| **toplam** | 0/72 | 0 | | 0 | |

## 5. Çalışma B — Bildirim fiyatının ALTINDA limit giriş (+ StochRSI desteği), 30 günlük geriye dönük test

### 5.0 Kurulum

- **Kaynaklar:** (1) **HA** = Hız Avcısı canlı-benzeri adaylar (rescan, rank ≤ 10, aşırı alımda değil, 60 dk bölümler; `work/rescan_90g_nogate.jsonl`) — 30 günlük birincil pencere W30 (17 Eyl–16 Eki) + 90 günlük bloklar B1/B2/B3; (2) **canlı bildirimler** (`monitoring_notifications`, W30; hepsi ve yalnız `trend_devam`; aynı sembolde 60 dk tekilleştirme); (3) **canlı journal adayları** (`velocity_candidates`, non-rescan, passes, rank ≤ 10, 60 dk bölüm; 18 Eyl–16 Eki) = ileri çizgi. Sinyal fiyatı P0 = kaynağın fiyatı (yoksa son kapanmış 1 dk kapanışı).
- **Limit emri:** sinyal + 60 sn sonra yerleşir (gecikme); geçerlilik V ∈ {15, 30, 60} dk; limit = P0 × (1 − d%), d ∈ {0,3; 0,6; 1,0; 1,5}; ilk 1 dk barının DÜŞÜĞÜ limitin KESİNLİKLE altına inerse dolar; dolum fiyatı = limit (açılış daha düşük olsa bile; kötümser). Dolum barında yalnız düşük kullanılır (yüksek = limit; TP/iz o barda tetiklenmez; stop kontrolü düşükle yapılır) → kötümser. Giriş kayması 0 (maker), çıkışlarda stop/zaman kayması %0,15. Dolmayan = işlem yok, net/sinyal'e 0 girer.
- **Ücret:** `config.py` COMMISSION_PCT = 0,0015 (Binance TR maker = taker = %0,15/bacak, satır 584 yorumu), COMMISSION_BNB_MODE varsayılan açık, indirim %25 → **%0,1125/bacak** (`paper_ledger.commission_pct()`); maker için ayrı (daha düşük) bir oran YOK, bu yüzden limit girişin tek maliyet avantajı kaymanın olmamasıdır.
- **StochRSI destekli varyantlar:** (LK) limit yalnız sinyal anında son kapanmış 5 dk StochRSI K < 50 ise yerleşir; (C) geçerlilik penceresi içinde 1 dk ya da 5 dk **ön sinyal** (seviye 20 / 30; çekirdek kırmızı şartı dâhil) gelirse o barın kapanışından +60 sn sonraki ilk 1 dk açılışında PİYASA girişi (%0,15 kayma), isteğe bağlı fiyat kapısı: giriş açılışı ≤ P0 × (1 − d%) (d = 0 → kapı yok); (LC) limit dolar ve dolum barının kapanışından sonraki 5 dk içinde ön sinyal gelirse giriş dolumda değil ön sinyalde (piyasa). (M) referans: sinyal + 60 sn piyasa girişi.
- **Çıkışlar:** 24 hücre (Çalışma A ile aynı). **Rastgele taban:** AYNI giriş kuralı rastgele anlarda: (1) istenen — aynı sembol + saat dilimi + çerçeve, kaynağın HİÇBİR tick'inden ≥ 2 sa uzak; (2) oynaklık eşleşmeli ≥ 2 sa; (3) saat dilimi eşleşmeli, dışlamasız; (4) oynaklık (son 30 dk aralığı ±%25) eşleşmeli, dışlamasız. Her sinyal için 2'şer rastgele an. Tabanlarda likit-sembol filtresi YOK (aynı sembol eşleşmesi likiditeyi taşır; HA havuzu 5M TRY altını da içeriyor).
- **Not (limit + oynaklık karıştırıcısı):** sinyaller yüksek oynaklık anlarında gelir; oynak anlarda limit daha sık dolar (aşağıda sinyal dolum % ≫ rastgele-1 dolum %). Bu yüzden 'sinyal − rastgele-1' fark tablosu oynaklık etkisini de taşır; oynaklık eşleşmeli rastgele-4 asıl kıyastır. Ayrıca rastgele-1/-2'nin 'sinyalden ≥ 2 sa uzak' koşulu GELECEĞE de bakar (ileride sinyal olmayan anlar) — bu yanlılık A bölümünde ölçüldü.

### 5.1 Düz limit

**HA (rescan) — W30** — sinyal n = 7643 (rastgele-4: 15220)

#### HA (rescan) — W30: düz limit tablosu (net/sinyal: dolmayan = 0)

| d % | geçerli (dk) | dolum % sinyal | dolum % rastgele-1 / -4 | en iyi çıkış (iç-örneklem) | net/işlem % | net/sinyal % [%95] | rastgele-1 net/sinyal | rastgele-4 net/sinyal | sinyal−rastgele-1 [%95] | sinyal−rastgele-4 [%95] | net/sinyal>0 çıkış | medyan çıkış net/sinyal |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.3 | 15 | 77.1 | 41.5 / 67.6 | trail act0.5 gap0.4 SL1.5 T120 | -0.53 | -0.41 [-0.43; -0.38] | -0.20 | -0.34 | -0.21 [-0.25; -0.17] | -0.07 [-0.11; -0.04] | 0/24 | -0.43 |
| 0.3 | 30 | 84.8 | 54.6 / 76.1 | trail act0.5 gap0.4 SL1.5 T60 | -0.53 | -0.45 [-0.48; -0.43] | -0.27 | -0.37 | -0.19 [-0.22; -0.15] | -0.08 [-0.11; -0.05] | 0/24 | -0.48 |
| 0.3 | 60 | 89.4 | 66.4 / 83.4 | trail act0.5 gap0.4 SL1.5 T60 | -0.53 | -0.47 [-0.50; -0.45] | -0.32 | -0.40 | -0.15 [-0.19; -0.11] | -0.07 [-0.11; -0.04] | 0/24 | -0.50 |
| 0.6 | 15 | 62.6 | 21.2 / 51.3 | trail act0.5 gap0.8 SL1.5 T120 | -0.50 | -0.31 [-0.34; -0.28] | -0.10 | -0.23 | -0.21 [-0.24; -0.18] | -0.08 [-0.11; -0.04] | 0/24 | -0.33 |
| 0.6 | 30 | 73.6 | 34.0 / 62.7 | trail act0.5 gap0.8 SL1.5 T120 | -0.51 | -0.37 [-0.40; -0.34] | -0.16 | -0.28 | -0.22 [-0.26; -0.18] | -0.09 [-0.13; -0.05] | 0/24 | -0.39 |
| 0.6 | 60 | 81.7 | 47.7 / 73.0 | trail act0.5 gap0.8 SL1.5 T120 | -0.50 | -0.41 [-0.44; -0.38] | -0.21 | -0.33 | -0.20 [-0.24; -0.15] | -0.07 [-0.12; -0.03] | 0/24 | -0.42 |
| 1 | 15 | 44.6 | 8.9 / 34.5 | fixed TP1 SL3 T120 | -0.46 | -0.20 [-0.24; -0.17] | -0.02 | -0.14 | -0.18 [-0.22; -0.14] | -0.07 [-0.11; -0.02] | 0/24 | -0.22 |
| 1 | 30 | 59.0 | 17.5 / 47.1 | fixed TP1 SL3 T120 | -0.43 | -0.26 [-0.30; -0.22] | -0.06 | -0.17 | -0.20 [-0.24; -0.15] | -0.09 [-0.13; -0.04] | 0/24 | -0.29 |
| 1 | 60 | 70.6 | 28.9 / 60.0 | fixed TP1 SL3 T120 | -0.41 | -0.29 [-0.34; -0.25] | -0.10 | -0.21 | -0.19 [-0.25; -0.13] | -0.08 [-0.14; -0.03] | 0/24 | -0.32 |
| 1.5 | 15 | 29.4 | 3.0 / 21.4 | trail act0.5 gap0.4 SL3 T120 | -0.44 | -0.13 [-0.15; -0.11] | -0.02 | -0.09 | -0.12 [-0.14; -0.09] | -0.04 [-0.07; -0.01] | 0/24 | -0.14 |
| 1.5 | 30 | 43.0 | 7.7 / 32.5 | trail act0.5 gap0.4 SL3 T120 | -0.40 | -0.17 [-0.20; -0.15] | -0.04 | -0.12 | -0.13 [-0.17; -0.10] | -0.05 [-0.09; -0.02] | 0/24 | -0.18 |
| 1.5 | 60 | 56.9 | 15.5 / 45.5 | fixed TP1.5 SL3 T120 | -0.38 | -0.22 [-0.27; -0.17] | -0.06 | -0.14 | -0.16 [-0.22; -0.10] | -0.07 [-0.13; -0.01] | 0/24 | -0.24 |

**Canlı bildirimler (hepsi) — W30** — sinyal n = 1834 (rastgele-4: 3604)

#### Canlı bildirimler (hepsi) — W30: düz limit tablosu (net/sinyal: dolmayan = 0)

| d % | geçerli (dk) | dolum % sinyal | dolum % rastgele-1 / -4 | en iyi çıkış (iç-örneklem) | net/işlem % | net/sinyal % [%95] | rastgele-1 net/sinyal | rastgele-4 net/sinyal | sinyal−rastgele-1 [%95] | sinyal−rastgele-4 [%95] | net/sinyal>0 çıkış | medyan çıkış net/sinyal |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.3 | 15 | 76.8 | 43.2 / 68.8 | trail act1 gap0.4 SL1.5 T60 | -0.63 | -0.48 [-0.54; -0.42] | -0.20 | -0.35 | -0.28 [-0.35; -0.21] | -0.13 [-0.20; -0.05] | 0/24 | -0.51 |
| 0.3 | 30 | 83.4 | 56.0 / 76.9 | trail act1 gap0.4 SL1.5 T60 | -0.61 | -0.51 [-0.57; -0.45] | -0.27 | -0.40 | -0.24 [-0.32; -0.17] | -0.12 [-0.20; -0.04] | 0/24 | -0.55 |
| 0.3 | 60 | 88.8 | 67.3 / 82.6 | trail act1 gap0.4 SL1.5 T60 | -0.59 | -0.53 [-0.59; -0.46] | -0.32 | -0.43 | -0.21 [-0.29; -0.13] | -0.10 [-0.18; -0.02] | 0/24 | -0.56 |
| 0.6 | 15 | 65.8 | 23.9 / 54.2 | fixed TP1 SL1.5 T120 | -0.59 | -0.39 [-0.44; -0.34] | -0.09 | -0.27 | -0.30 [-0.36; -0.25] | -0.12 [-0.18; -0.05] | 0/24 | -0.42 |
| 0.6 | 30 | 75.4 | 36.7 / 65.1 | fixed TP1 SL1.5 T120 | -0.58 | -0.43 [-0.49; -0.38] | -0.15 | -0.33 | -0.29 [-0.35; -0.22] | -0.10 [-0.17; -0.03] | 0/24 | -0.47 |
| 0.6 | 60 | 83.0 | 49.2 / 73.3 | fixed TP1 SL1.5 T120 | -0.56 | -0.47 [-0.53; -0.41] | -0.19 | -0.37 | -0.27 [-0.35; -0.20] | -0.10 [-0.17; -0.02] | 0/24 | -0.50 |
| 1 | 15 | 52.6 | 10.7 / 38.7 | fixed TP1 SL1.5 T60 | -0.51 | -0.27 [-0.31; -0.22] | -0.03 | -0.18 | -0.24 [-0.29; -0.19] | -0.09 [-0.15; -0.03] | 0/24 | -0.29 |
| 1 | 30 | 63.8 | 20.0 / 50.8 | fixed TP1 SL1.5 T120 | -0.51 | -0.33 [-0.38; -0.27] | -0.06 | -0.24 | -0.26 [-0.32; -0.20] | -0.08 [-0.15; -0.02] | 0/24 | -0.35 |
| 1 | 60 | 73.7 | 31.4 / 61.8 | fixed TP1 SL1.5 T60 | -0.51 | -0.37 [-0.43; -0.32] | -0.11 | -0.28 | -0.27 [-0.33; -0.20] | -0.10 [-0.17; -0.02] | 0/24 | -0.40 |
| 1.5 | 15 | 39.5 | 4.8 / 27.4 | fixed TP1.5 SL1.5 T120 | -0.45 | -0.18 [-0.22; -0.13] | -0.02 | -0.13 | -0.16 [-0.21; -0.11] | -0.05 [-0.10; +0.01] | 0/24 | -0.19 |
| 1.5 | 30 | 51.5 | 9.5 / 38.7 | fixed TP1.5 SL1.5 T120 | -0.47 | -0.24 [-0.29; -0.19] | -0.04 | -0.19 | -0.20 [-0.25; -0.14] | -0.05 [-0.12; +0.01] | 0/24 | -0.26 |
| 1.5 | 60 | 63.7 | 16.9 / 49.1 | fixed TP1.5 SL1.5 T120 | -0.46 | -0.29 [-0.35; -0.24] | -0.07 | -0.21 | -0.22 [-0.28; -0.16] | -0.08 [-0.15; -0.01] | 0/24 | -0.31 |

**Canlı bildirimler (trend_devam) — W30** — sinyal n = 624 (rastgele-4: 1204)

#### Canlı bildirimler (trend_devam) — W30: düz limit tablosu (net/sinyal: dolmayan = 0)

| d % | geçerli (dk) | dolum % sinyal | dolum % rastgele-1 / -4 | en iyi çıkış (iç-örneklem) | net/işlem % | net/sinyal % [%95] | rastgele-1 net/sinyal | rastgele-4 net/sinyal | sinyal−rastgele-1 [%95] | sinyal−rastgele-4 [%95] | net/sinyal>0 çıkış | medyan çıkış net/sinyal |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.3 | 15 | 81.1 | 47.0 / 78.7 | trail act1 gap0.8 SL1.5 T60 | -0.54 | -0.44 [-0.56; -0.32] | -0.24 | -0.44 | -0.20 [-0.33; -0.07] | -0.00 [-0.14; +0.14] | 0/24 | -0.49 |
| 0.3 | 30 | 86.7 | 58.8 / 84.9 | trail act1 gap0.4 SL1.5 T60 | -0.55 | -0.47 [-0.60; -0.35] | -0.29 | -0.48 | -0.19 [-0.32; -0.05] | +0.00 [-0.14; +0.15] | 0/24 | -0.51 |
| 0.3 | 60 | 90.2 | 69.5 / 89.0 | trail act0.5 gap0.8 SL3 T120 | -0.52 | -0.46 [-0.64; -0.29] | -0.30 | -0.52 | -0.17 [-0.36; +0.02] | +0.05 [-0.15; +0.26] | 0/24 | -0.49 |
| 0.6 | 15 | 74.0 | 26.4 / 67.9 | trail act1 gap0.4 SL1.5 T120 | -0.55 | -0.41 [-0.50; -0.32] | -0.10 | -0.35 | -0.30 [-0.40; -0.21] | -0.06 [-0.17; +0.05] | 0/24 | -0.45 |
| 0.6 | 30 | 81.2 | 38.1 / 76.8 | trail act1 gap0.4 SL1.5 T120 | -0.54 | -0.44 [-0.54; -0.34] | -0.16 | -0.40 | -0.28 [-0.39; -0.17] | -0.04 [-0.17; +0.08] | 0/24 | -0.49 |
| 0.6 | 60 | 86.5 | 50.5 / 82.9 | trail act0.5 gap0.8 SL1.5 T120 | -0.54 | -0.47 [-0.56; -0.38] | -0.23 | -0.43 | -0.24 [-0.35; -0.13] | -0.04 [-0.16; +0.08] | 0/24 | -0.49 |
| 1 | 15 | 64.1 | 12.7 / 53.6 | trail act0.5 gap0.8 SL1.5 T60 | -0.40 | -0.26 [-0.35; -0.17] | -0.06 | -0.26 | -0.20 [-0.29; -0.11] | -0.00 [-0.10; +0.10] | 0/24 | -0.32 |
| 1 | 30 | 74.7 | 22.7 / 63.1 | trail act0.5 gap0.8 SL1.5 T120 | -0.43 | -0.32 [-0.42; -0.22] | -0.08 | -0.29 | -0.24 [-0.34; -0.13] | -0.03 [-0.14; +0.09] | 0/24 | -0.39 |
| 1 | 60 | 82.1 | 32.9 / 72.4 | trail act0.5 gap0.8 SL1.5 T120 | -0.42 | -0.35 [-0.45; -0.24] | -0.13 | -0.34 | -0.22 [-0.33; -0.11] | -0.01 [-0.13; +0.11] | 0/24 | -0.41 |
| 1.5 | 15 | 52.9 | 5.4 / 39.5 | trail act0.5 gap0.8 SL1.5 T120 | -0.39 | -0.21 [-0.28; -0.13] | -0.02 | -0.18 | -0.18 [-0.26; -0.11] | -0.02 [-0.12; +0.07] | 0/24 | -0.25 |
| 1.5 | 30 | 63.9 | 10.4 / 51.1 | trail act0.5 gap0.8 SL1.5 T60 | -0.40 | -0.26 [-0.33; -0.18] | -0.04 | -0.20 | -0.21 [-0.29; -0.14] | -0.05 [-0.15; +0.04] | 0/24 | -0.31 |
| 1.5 | 60 | 76.0 | 18.8 / 63.1 | trail act0.5 gap0.8 SL3 T60 | -0.37 | -0.28 [-0.41; -0.15] | -0.07 | -0.23 | -0.21 [-0.34; -0.08] | -0.05 [-0.19; +0.10] | 0/24 | -0.35 |

**Dayanıklılık — HA 90 gün (07-20 → 10-16) ve canlı journal adayları (ileri, 18 Eyl–16 Eki):**

#### HA (rescan) — 90 gün

| d % | geçerli (dk) | dolum % sinyal | dolum % rastgele-1 / -4 | en iyi çıkış (iç-örneklem) | net/işlem % | net/sinyal % [%95] | rastgele-1 net/sinyal | rastgele-4 net/sinyal | sinyal−rastgele-1 [%95] | sinyal−rastgele-4 [%95] | net/sinyal>0 çıkış | medyan çıkış net/sinyal |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.3 | 15 | 76.8 | 40.1 / 67.9 | trail act0.5 gap0.4 SL1.5 T60 | -0.55 | -0.42 [-0.44; -0.41] | -0.20 | -0.35 | -0.22 [-0.24; -0.20] | -0.08 [-0.10; -0.05] | 0/24 | -0.44 |
| 0.3 | 30 | 84.0 | 52.7 / 76.2 | trail act0.5 gap0.4 SL1.5 T60 | -0.55 | -0.46 [-0.48; -0.44] | -0.26 | -0.39 | -0.20 [-0.22; -0.17] | -0.07 [-0.10; -0.05] | 0/24 | -0.47 |
| 0.3 | 60 | 88.8 | 64.8 / 82.8 | trail act0.5 gap0.4 SL1.5 T60 | -0.54 | -0.48 [-0.50; -0.46] | -0.32 | -0.42 | -0.16 [-0.19; -0.14] | -0.07 [-0.09; -0.04] | 0/24 | -0.49 |
| 0.6 | 15 | 63.3 | 20.7 / 52.5 | trail act0.5 gap0.4 SL1.5 T120 | -0.50 | -0.32 [-0.33; -0.30] | -0.10 | -0.24 | -0.22 [-0.24; -0.20] | -0.08 [-0.09; -0.06] | 0/24 | -0.33 |
| 0.6 | 30 | 73.6 | 32.8 / 63.4 | trail act0.5 gap0.4 SL1.5 T60 | -0.50 | -0.37 [-0.38; -0.35] | -0.15 | -0.29 | -0.21 [-0.23; -0.19] | -0.08 [-0.10; -0.06] | 0/24 | -0.38 |
| 0.6 | 60 | 81.3 | 46.2 / 72.8 | trail act0.5 gap0.4 SL1.5 T60 | -0.49 | -0.40 [-0.42; -0.38] | -0.21 | -0.33 | -0.19 [-0.21; -0.17] | -0.07 [-0.09; -0.05] | 0/24 | -0.41 |
| 1 | 15 | 45.7 | 8.9 / 35.9 | fixed TP1 SL1.5 T120 | -0.40 | -0.19 [-0.20; -0.17] | -0.02 | -0.14 | -0.16 [-0.18; -0.15] | -0.05 [-0.06; -0.03] | 0/24 | -0.21 |
| 1 | 30 | 58.9 | 16.9 / 47.9 | fixed TP1 SL1.5 T120 | -0.40 | -0.23 [-0.25; -0.22] | -0.05 | -0.18 | -0.19 [-0.20; -0.17] | -0.06 [-0.08; -0.04] | 0/24 | -0.27 |
| 1 | 60 | 70.1 | 28.0 / 59.7 | fixed TP1 SL1.5 T120 | -0.38 | -0.27 [-0.29; -0.25] | -0.08 | -0.22 | -0.19 [-0.21; -0.16] | -0.05 [-0.07; -0.03] | 0/24 | -0.31 |
| 1.5 | 15 | 29.8 | 3.3 / 22.3 | fixed TP1.5 SL3 T120 | -0.40 | -0.12 [-0.14; -0.10] | -0.01 | -0.09 | -0.11 [-0.13; -0.09] | -0.03 [-0.05; -0.01] | 0/24 | -0.13 |
| 1.5 | 30 | 42.7 | 7.5 / 33.1 | fixed TP1.5 SL1.5 T120 | -0.39 | -0.17 [-0.18; -0.15] | -0.02 | -0.12 | -0.15 [-0.16; -0.13] | -0.05 [-0.07; -0.03] | 0/24 | -0.17 |
| 1.5 | 60 | 55.8 | 14.9 / 45.1 | fixed TP1.5 SL3 T120 | -0.38 | -0.21 [-0.24; -0.19] | -0.04 | -0.16 | -0.17 [-0.20; -0.14] | -0.06 [-0.09; -0.02] | 0/24 | -0.23 |

#### Canlı journal adayları — 18 Eyl–16 Eki

| d % | geçerli (dk) | dolum % sinyal | dolum % rastgele-1 / -4 | en iyi çıkış (iç-örneklem) | net/işlem % | net/sinyal % [%95] | rastgele-1 net/sinyal | rastgele-4 net/sinyal | sinyal−rastgele-1 [%95] | sinyal−rastgele-4 [%95] | net/sinyal>0 çıkış | medyan çıkış net/sinyal |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.3 | 15 | 74.4 | 41.4 / 67.7 | trail act0.5 gap0.8 SL1.5 T120 | -0.55 | -0.41 [-0.44; -0.37] | -0.20 | -0.33 | -0.21 [-0.25; -0.16] | -0.08 [-0.13; -0.03] | 0/24 | -0.45 |
| 0.3 | 30 | 81.5 | 53.6 / 76.2 | trail act0.5 gap0.8 SL1.5 T120 | -0.55 | -0.45 [-0.48; -0.41] | -0.26 | -0.36 | -0.18 [-0.24; -0.13] | -0.08 [-0.13; -0.03] | 0/24 | -0.48 |
| 0.3 | 60 | 86.8 | 65.1 / 82.9 | trail act0.5 gap0.8 SL1.5 T120 | -0.54 | -0.47 [-0.50; -0.44] | -0.31 | -0.39 | -0.16 [-0.21; -0.10] | -0.07 [-0.12; -0.03] | 0/24 | -0.51 |
| 0.6 | 15 | 61.2 | 21.8 / 51.6 | trail act0.5 gap0.8 SL1.5 T120 | -0.51 | -0.31 [-0.34; -0.28] | -0.10 | -0.24 | -0.21 [-0.25; -0.17] | -0.07 [-0.11; -0.03] | 0/24 | -0.34 |
| 0.6 | 30 | 70.8 | 33.7 / 63.0 | trail act0.5 gap0.8 SL1.5 T120 | -0.51 | -0.36 [-0.39; -0.33] | -0.16 | -0.28 | -0.20 [-0.25; -0.16] | -0.08 [-0.12; -0.04] | 0/24 | -0.39 |
| 0.6 | 60 | 79.4 | 46.9 / 72.6 | trail act0.5 gap0.8 SL1.5 T120 | -0.50 | -0.40 [-0.42; -0.37] | -0.21 | -0.32 | -0.18 [-0.23; -0.14] | -0.07 [-0.11; -0.03] | 0/24 | -0.43 |
| 1 | 15 | 43.9 | 9.4 / 35.2 | trail act0.5 gap0.8 SL1.5 T120 | -0.48 | -0.21 [-0.24; -0.19] | -0.04 | -0.15 | -0.17 [-0.20; -0.14] | -0.06 [-0.09; -0.03] | 0/24 | -0.23 |
| 1 | 30 | 56.8 | 17.5 / 47.6 | trail act0.5 gap0.4 SL1.5 T120 | -0.47 | -0.27 [-0.28; -0.25] | -0.08 | -0.20 | -0.19 [-0.21; -0.16] | -0.07 [-0.09; -0.04] | 0/24 | -0.28 |
| 1 | 60 | 68.0 | 28.9 / 59.5 | trail act0.5 gap0.8 SL1.5 T120 | -0.46 | -0.31 [-0.33; -0.29] | -0.13 | -0.24 | -0.18 [-0.22; -0.15] | -0.07 [-0.10; -0.04] | 0/24 | -0.33 |
| 1.5 | 15 | 29.0 | 3.6 / 22.1 | trail act0.5 gap0.4 SL3 T60 | -0.52 | -0.15 [-0.18; -0.12] | -0.01 | -0.09 | -0.14 [-0.17; -0.11] | -0.06 [-0.09; -0.02] | 0/24 | -0.16 |
| 1.5 | 30 | 41.6 | 7.8 / 33.2 | trail act0.5 gap0.4 SL3 T60 | -0.47 | -0.20 [-0.23; -0.17] | -0.03 | -0.13 | -0.16 [-0.20; -0.13] | -0.07 [-0.10; -0.03] | 0/24 | -0.21 |
| 1.5 | 60 | 54.7 | 15.8 / 45.5 | trail act0.5 gap0.4 SL3 T60 | -0.44 | -0.24 [-0.28; -0.20] | -0.06 | -0.17 | -0.18 [-0.22; -0.14] | -0.07 [-0.12; -0.02] | 0/24 | -0.25 |

### 5.2 Seçim yanlılığı: dolan ve dolmayan sinyallerden sonra fiyat

#### HA — W30

Getiri = sinyal fiyatından (P0) sinyal + 60 sn + 59 dk sonraki 1 dk kapanışına brüt % (ücretsiz); 'dolumdan' = limit fiyatından aynı kapanışa. Ortalama [gün-kümeli %95]. Seçim yanlılığı: dolan sinyallerde fiyat sonra daha mı kötü gidiyor?

| d % | geçerli (dk) | n dolan / dolmayan | P0'dan 60 dk: DOLAN | P0'dan 60 dk: DOLMAYAN | fark (dolan−dolmayan) | rastgele-4 dolan / dolmayan | dolan sinyaller: limit fiyatından 60 dk |
|---|---|---|---|---|---|---|---|
| 0.3 | 15 | 5891 / 1752 | -0.643 [-0.738; -0.548] | +1.313 [+1.096; +1.529] | -1.956 [-2.192; -1.719] | -0.475 / +0.875 | -0.344 [-0.439; -0.249] |
| 0.3 | 30 | 6481 / 1162 | -0.616 [-0.706; -0.526] | +2.157 [+1.911; +2.403] | -2.773 [-3.035; -2.511] | -0.465 / +1.320 | -0.317 [-0.408; -0.227] |
| 0.3 | 60 | 6830 / 813 | -0.606 [-0.693; -0.518] | +3.260 [+2.964; +3.555] | -3.865 [-4.174; -3.557] | -0.459 / +2.078 | -0.307 [-0.394; -0.219] |
| 0.6 | 15 | 4781 / 2862 | -0.933 [-1.040; -0.826] | +1.039 [+0.882; +1.196] | -1.972 [-2.162; -1.782] | -0.752 / +0.714 | -0.335 [-0.443; -0.227] |
| 0.6 | 30 | 5624 / 2019 | -0.890 [-0.992; -0.789] | +1.743 [+1.566; +1.920] | -2.633 [-2.837; -2.429] | -0.725 / +1.117 | -0.292 [-0.394; -0.190] |
| 0.6 | 60 | 6242 / 1401 | -0.864 [-0.956; -0.772] | +2.787 [+2.581; +2.992] | -3.650 [-3.876; -3.425] | -0.720 / +1.811 | -0.265 [-0.358; -0.173] |
| 1 | 15 | 3412 / 4231 | -1.335 [-1.465; -1.204] | +0.725 [+0.607; +0.842] | -2.059 [-2.235; -1.884] | -1.097 / +0.522 | -0.338 [-0.470; -0.206] |
| 1 | 30 | 4510 / 3133 | -1.258 [-1.372; -1.143] | +1.335 [+1.187; +1.483] | -2.593 [-2.780; -2.406] | -1.072 / +0.884 | -0.260 [-0.376; -0.145] |
| 1 | 60 | 5396 / 2247 | -1.214 [-1.316; -1.112] | +2.253 [+2.095; +2.411] | -3.467 [-3.655; -3.278] | -1.065 / +1.503 | -0.216 [-0.319; -0.113] |
| 1.5 | 15 | 2247 / 5396 | -1.868 [-2.022; -1.713] | +0.502 [+0.391; +0.613] | -2.370 [-2.560; -2.179] | -1.592 / +0.385 | -0.373 [-0.530; -0.217] |
| 1.5 | 30 | 3283 / 4360 | -1.731 [-1.856; -1.605] | +0.962 [+0.845; +1.079] | -2.693 [-2.864; -2.521] | -1.556 / +0.694 | -0.234 [-0.362; -0.107] |
| 1.5 | 60 | 4346 / 3297 | -1.670 [-1.772; -1.567] | +1.749 [+1.610; +1.889] | -3.419 [-3.592; -3.246] | -1.536 / +1.214 | -0.172 [-0.276; -0.069] |

#### Canlı bildirimler (hepsi) — W30

Getiri = sinyal fiyatından (P0) sinyal + 60 sn + 59 dk sonraki 1 dk kapanışına brüt % (ücretsiz); 'dolumdan' = limit fiyatından aynı kapanışa. Ortalama [gün-kümeli %95]. Seçim yanlılığı: dolan sinyallerde fiyat sonra daha mı kötü gidiyor?

| d % | geçerli (dk) | n dolan / dolmayan | P0'dan 60 dk: DOLAN | P0'dan 60 dk: DOLMAYAN | fark (dolan−dolmayan) | rastgele-4 dolan / dolmayan | dolan sinyaller: limit fiyatından 60 dk |
|---|---|---|---|---|---|---|---|
| 0.3 | 15 | 1409 / 425 | -0.968 [-1.160; -0.776] | +2.084 [+1.504; +2.665] | -3.052 [-3.664; -2.441] | -0.576 / +1.158 | -0.670 [-0.862; -0.478] |
| 0.3 | 30 | 1530 / 304 | -0.958 [-1.154; -0.762] | +3.250 [+2.460; +4.041] | -4.209 [-5.023; -3.394] | -0.572 / +1.751 | -0.660 [-0.856; -0.464] |
| 0.3 | 60 | 1628 / 206 | -0.918 [-1.101; -0.735] | +4.935 [+3.959; +5.911] | -5.853 [-6.846; -4.860] | -0.563 / +2.469 | -0.620 [-0.804; -0.436] |
| 0.6 | 15 | 1207 / 627 | -1.251 [-1.444; -1.059] | +1.647 [+1.241; +2.052] | -2.898 [-3.347; -2.449] | -0.836 / +0.911 | -0.655 [-0.849; -0.462] |
| 0.6 | 30 | 1383 / 451 | -1.196 [-1.395; -0.997] | +2.608 [+2.021; +3.195] | -3.804 [-4.424; -3.184] | -0.820 / +1.432 | -0.600 [-0.800; -0.399] |
| 0.6 | 60 | 1523 / 311 | -1.148 [-1.339; -0.958] | +4.088 [+3.330; +4.845] | -5.236 [-6.017; -4.455] | -0.805 / +2.078 | -0.552 [-0.743; -0.361] |
| 1 | 15 | 965 / 869 | -1.658 [-1.916; -1.400] | +1.291 [+0.997; +1.586] | -2.949 [-3.341; -2.558] | -1.260 / +0.739 | -0.665 [-0.925; -0.404] |
| 1 | 30 | 1171 / 663 | -1.590 [-1.847; -1.334] | +2.088 [+1.680; +2.497] | -3.679 [-4.161; -3.196] | -1.231 / +1.202 | -0.596 [-0.856; -0.337] |
| 1 | 60 | 1352 / 482 | -1.509 [-1.745; -1.274] | +3.242 [+2.748; +3.736] | -4.751 [-5.298; -4.204] | -1.188 / +1.832 | -0.514 [-0.752; -0.276] |
| 1.5 | 15 | 724 / 1110 | -2.092 [-2.443; -1.741] | +0.934 [+0.697; +1.171] | -3.026 [-3.450; -2.602] | -1.728 / +0.604 | -0.601 [-0.958; -0.244] |
| 1.5 | 30 | 945 / 889 | -2.055 [-2.349; -1.762] | +1.647 [+1.345; +1.949] | -3.702 [-4.124; -3.281] | -1.691 / +1.012 | -0.564 [-0.861; -0.266] |
| 1.5 | 60 | 1169 / 665 | -1.943 [-2.197; -1.690] | +2.697 [+2.300; +3.094] | -4.640 [-5.112; -4.169] | -1.640 / +1.515 | -0.450 [-0.707; -0.192] |

#### Canlı bildirimler (trend_devam) — W30

Getiri = sinyal fiyatından (P0) sinyal + 60 sn + 59 dk sonraki 1 dk kapanışına brüt % (ücretsiz); 'dolumdan' = limit fiyatından aynı kapanışa. Ortalama [gün-kümeli %95]. Seçim yanlılığı: dolan sinyallerde fiyat sonra daha mı kötü gidiyor?

| d % | geçerli (dk) | n dolan / dolmayan | P0'dan 60 dk: DOLAN | P0'dan 60 dk: DOLMAYAN | fark (dolan−dolmayan) | rastgele-4 dolan / dolmayan | dolan sinyaller: limit fiyatından 60 dk |
|---|---|---|---|---|---|---|---|
| 0.3 | 15 | 506 / 118 | -0.987 [-1.474; -0.499] | +3.975 [+2.492; +5.459] | -4.962 [-6.523; -3.401] | -0.784 / +1.063 | -0.689 [-1.177; -0.200] |
| 0.3 | 30 | 541 / 83 | -1.002 [-1.500; -0.504] | +6.170 [+4.503; +7.838] | -7.173 [-8.913; -5.432] | -0.807 / +1.953 | -0.704 [-1.204; -0.205] |
| 0.3 | 60 | 563 / 61 | -0.921 [-1.428; -0.414] | +8.008 [+5.883; +10.134] | -8.929 [-11.115; -6.744] | -0.798 / +2.898 | -0.623 [-1.132; -0.114] |
| 0.6 | 15 | 462 / 162 | -1.247 [-1.754; -0.741] | +3.371 [+2.127; +4.615] | -4.618 [-5.961; -3.275] | -1.061 / +1.026 | -0.651 [-1.161; -0.142] |
| 0.6 | 30 | 507 / 117 | -1.263 [-1.781; -0.745] | +5.215 [+3.846; +6.583] | -6.478 [-7.941; -5.014] | -1.073 / +1.874 | -0.667 [-1.188; -0.145] |
| 0.6 | 60 | 540 / 84 | -1.186 [-1.705; -0.667] | +7.266 [+5.646; +8.886] | -8.452 [-10.153; -6.751] | -1.042 / +2.771 | -0.590 [-1.112; -0.068] |
| 1 | 15 | 400 / 224 | -1.586 [-2.122; -1.050] | +2.698 [+1.760; +3.637] | -4.285 [-5.365; -3.204] | -1.636 / +1.048 | -0.592 [-1.134; -0.051] |
| 1 | 30 | 466 / 158 | -1.601 [-2.122; -1.079] | +4.530 [+3.484; +5.576] | -6.130 [-7.299; -4.962] | -1.632 / +1.737 | -0.607 [-1.133; -0.080] |
| 1 | 60 | 512 / 112 | -1.511 [-2.023; -0.999] | +6.638 [+5.344; +7.931] | -8.149 [-9.540; -6.758] | -1.543 / +2.639 | -0.516 [-1.033; +0.001] |
| 1.5 | 15 | 330 / 294 | -2.039 [-2.711; -1.367] | +2.186 [+1.425; +2.948] | -4.225 [-5.241; -3.209] | -2.223 / +0.805 | -0.547 [-1.230; +0.135] |
| 1.5 | 30 | 399 / 225 | -2.047 [-2.619; -1.476] | +3.497 [+2.675; +4.318] | -5.544 [-6.545; -4.543] | -2.115 / +1.411 | -0.556 [-1.136; +0.025] |
| 1.5 | 60 | 474 / 150 | -1.887 [-2.421; -1.353] | +5.762 [+4.815; +6.710] | -7.650 [-8.737; -6.562] | -1.957 / +2.293 | -0.393 [-0.935; +0.149] |

### 5.3 StochRSI destekli varyantlar (aile başına en iyi bileşim)

#### HA — W30

Her giriş ailesinin W30 net/sinyal'e göre EN İYİ (hücre, çıkış) bileşimi (**iç-örneklem, iyimser**; işlem ≥ 30). Net/sinyal: dolmayan = 0.

| aile | hücre | çıkış | dolum % (sinyal / rastgele-1 / rastgele-4) | işlem n | net/işlem | net/sinyal [%95] | rastgele-1 | rastgele-4 | sinyal−rastgele-4 [%95] | net/sinyal>0 bileşim (hücre×çıkış) |
|---|---|---|---|---|---|---|---|---|---|---|
| piyasa girişi (sinyal + 60 sn; referans) | M | trail act0.5 gap0.8 SL1.5 T60 | 100.0 / 100.0 / 100.0 | 7643 | -0.50 | -0.50 [-0.53; -0.47] | -0.55 | -0.50 | +0.00 [-0.05; +0.05] | 0/24 |
| düz limit | L d1.5 V15 | trail act0.5 gap0.4 SL3 T120 | 29.4 / 3.0 / 21.4 | 2247 | -0.44 | -0.13 [-0.15; -0.11] | -0.02 | -0.09 | -0.04 [-0.07; -0.01] | 0/288 |
| limit + 5 dk StochRSI K<50 | LK d1.5 V15 | trail act0.5 gap0.4 SL1.5 T120 | 10.2 / 1.7 / 11.0 | 777 | -0.46 | -0.05 [-0.06; -0.04] | -0.01 | -0.05 | -0.00 [-0.02; +0.01] | 0/288 |
| (b) dip + ön sinyal teyidi, seviye 20 | C lv20 d1 V15 | trail act0.5 gap0.4 SL1.5 T120 | 16.4 / 1.8 / 10.8 | 1254 | -0.51 | -0.08 [-0.10; -0.07] | -0.01 | -0.05 | -0.04 [-0.05; -0.02] | 0/288 |
| (b) dip + ön sinyal teyidi, seviye 30 | C lv30 d1 V15 | trail act0.5 gap0.4 SL1.5 T120 | 16.5 / 1.8 / 10.7 | 1260 | -0.51 | -0.08 [-0.10; -0.07] | -0.01 | -0.05 | -0.04 [-0.05; -0.02] | 0/288 |
| (c) limit dolumu + 5 dk içinde ön sinyal, seviye 20 | LC lv20 d1.5 V15 | fixed TP1.5 SL3 T120 | 21.4 / 2.1 / 15.6 | 1637 | -0.44 | -0.09 [-0.11; -0.07] | -0.01 | -0.07 | -0.02 [-0.05; +0.01] | 0/288 |
| (c) limit dolumu + 5 dk içinde ön sinyal, seviye 30 | LC lv30 d1.5 V15 | fixed TP1.5 SL3 T120 | 22.0 / 2.2 / 16.4 | 1683 | -0.44 | -0.10 [-0.12; -0.07] | -0.01 | -0.08 | -0.02 [-0.05; +0.01] | 0/288 |

#### Canlı bildirimler (hepsi) — W30

Her giriş ailesinin W30 net/sinyal'e göre EN İYİ (hücre, çıkış) bileşimi (**iç-örneklem, iyimser**; işlem ≥ 30). Net/sinyal: dolmayan = 0.

| aile | hücre | çıkış | dolum % (sinyal / rastgele-1 / rastgele-4) | işlem n | net/işlem | net/sinyal [%95] | rastgele-1 | rastgele-4 | sinyal−rastgele-4 [%95] | net/sinyal>0 bileşim (hücre×çıkış) |
|---|---|---|---|---|---|---|---|---|---|---|
| piyasa girişi (sinyal + 60 sn; referans) | M | trail act0.5 gap0.8 SL1.5 T120 | 100.0 / 100.0 / 100.0 | 1834 | -0.46 | -0.46 [-0.54; -0.38] | -0.50 | -0.50 | +0.03 [-0.07; +0.14] | 0/24 |
| düz limit | L d1.5 V15 | fixed TP1.5 SL1.5 T120 | 39.5 / 4.8 / 27.4 | 724 | -0.45 | -0.18 [-0.22; -0.13] | -0.02 | -0.13 | -0.05 [-0.10; +0.01] | 0/288 |
| limit + 5 dk StochRSI K<50 | LK d1.5 V15 | fixed TP1.5 SL1.5 T120 | 9.9 / 2.7 / 13.2 | 181 | -0.43 | -0.04 [-0.06; -0.02] | -0.01 | -0.07 | +0.02 [-0.00; +0.05] | 0/288 |
| (b) dip + ön sinyal teyidi, seviye 20 | C lv20 d1 V15 | trail act0.5 gap0.4 SL3 T120 | 22.6 / 2.7 / 13.0 | 415 | -0.51 | -0.11 [-0.16; -0.07] | -0.01 | -0.08 | -0.04 [-0.08; +0.01] | 0/288 |
| (b) dip + ön sinyal teyidi, seviye 30 | C lv30 d1 V15 | trail act0.5 gap0.4 SL3 T120 | 22.7 / 2.7 / 12.7 | 416 | -0.51 | -0.12 [-0.16; -0.08] | -0.01 | -0.07 | -0.04 [-0.09; +0.00] | 0/288 |
| (c) limit dolumu + 5 dk içinde ön sinyal, seviye 20 | LC lv20 d0.3 V15 | trail act0.5 gap0.4 SL3 T120 | 31.1 / 20.6 / 32.7 | 571 | -0.48 | -0.15 [-0.19; -0.11] | -0.10 | -0.17 | +0.02 [-0.03; +0.07] | 0/288 |
| (c) limit dolumu + 5 dk içinde ön sinyal, seviye 30 | LC lv30 d0.3 V15 | fixed TP1 SL3 T120 | 31.7 / 21.8 / 34.7 | 582 | -0.47 | -0.15 [-0.19; -0.11] | -0.10 | -0.17 | +0.02 [-0.03; +0.08] | 0/288 |

#### Canlı bildirimler (trend_devam) — W30

Her giriş ailesinin W30 net/sinyal'e göre EN İYİ (hücre, çıkış) bileşimi (**iç-örneklem, iyimser**; işlem ≥ 30). Net/sinyal: dolmayan = 0.

| aile | hücre | çıkış | dolum % (sinyal / rastgele-1 / rastgele-4) | işlem n | net/işlem | net/sinyal [%95] | rastgele-1 | rastgele-4 | sinyal−rastgele-4 [%95] | net/sinyal>0 bileşim (hücre×çıkış) |
|---|---|---|---|---|---|---|---|---|---|---|
| piyasa girişi (sinyal + 60 sn; referans) | M | trail act1 gap0.8 SL1.5 T120 | 100.0 / 100.0 / 100.0 | 624 | -0.27 | -0.27 [-0.41; -0.13] | -0.53 | -0.54 | +0.27 [+0.11; +0.43] | 0/24 |
| düz limit | L d1.5 V15 | trail act0.5 gap0.8 SL1.5 T120 | 52.9 / 5.4 / 39.5 | 330 | -0.39 | -0.21 [-0.28; -0.13] | -0.02 | -0.18 | -0.02 [-0.12; +0.07] | 0/288 |
| limit + 5 dk StochRSI K<50 | LK d1.5 V15 | fixed TP1.5 SL1.5 T120 | 11.2 / 2.6 / 19.2 | 70 | -0.21 | -0.02 [-0.06; +0.01] | -0.02 | -0.08 | +0.06 [+0.01; +0.11] | 0/288 |
| (b) dip + ön sinyal teyidi, seviye 20 | C lv20 d1 V15 | trail act0.5 gap0.4 SL3 T120 | 28.0 / 2.9 / 20.5 | 175 | -0.72 | -0.20 [-0.28; -0.13] | -0.01 | -0.10 | -0.10 [-0.19; -0.01] | 0/288 |
| (b) dip + ön sinyal teyidi, seviye 30 | C lv30 d1 V15 | trail act0.5 gap0.4 SL3 T120 | 27.9 / 2.9 / 20.8 | 174 | -0.73 | -0.20 [-0.28; -0.13] | -0.01 | -0.10 | -0.10 [-0.19; -0.02] | 0/288 |
| (c) limit dolumu + 5 dk içinde ön sinyal, seviye 20 | LC lv20 d0.3 V30 | trail act1 gap0.4 SL3 T120 | 37.7 / 25.3 / 41.7 | 235 | -0.42 | -0.16 [-0.26; -0.06] | -0.09 | -0.14 | -0.01 [-0.14; +0.11] | 0/288 |
| (c) limit dolumu + 5 dk içinde ön sinyal, seviye 30 | LC lv30 d0.3 V30 | trail act1 gap0.4 SL3 T120 | 38.3 / 27.0 / 44.3 | 239 | -0.39 | -0.15 [-0.25; -0.05] | -0.09 | -0.15 | +0.00 [-0.13; +0.13] | 0/288 |

#### HA — 90 gün

Her giriş ailesinin W30 net/sinyal'e göre EN İYİ (hücre, çıkış) bileşimi (**iç-örneklem, iyimser**; işlem ≥ 30). Net/sinyal: dolmayan = 0.

| aile | hücre | çıkış | dolum % (sinyal / rastgele-1 / rastgele-4) | işlem n | net/işlem | net/sinyal [%95] | rastgele-1 | rastgele-4 | sinyal−rastgele-4 [%95] | net/sinyal>0 bileşim (hücre×çıkış) |
|---|---|---|---|---|---|---|---|---|---|---|
| piyasa girişi (sinyal + 60 sn; referans) | M | fixed TP1 SL1.5 T60 | 100.0 / 100.0 / 100.0 | 20343 | -0.52 | -0.52 [-0.54; -0.50] | -0.54 | -0.51 | -0.01 [-0.04; +0.01] | 0/24 |
| düz limit | L d1.5 V15 | fixed TP1.5 SL3 T120 | 29.8 / 3.3 / 22.3 | 6056 | -0.40 | -0.12 [-0.14; -0.10] | -0.01 | -0.09 | -0.03 [-0.05; -0.01] | 0/288 |
| limit + 5 dk StochRSI K<50 | LK d1.5 V15 | fixed TP1.5 SL1.5 T120 | 10.4 / 1.7 / 11.3 | 2108 | -0.40 | -0.04 [-0.05; -0.04] | -0.00 | -0.04 | +0.00 [-0.01; +0.01] | 0/288 |
| (b) dip + ön sinyal teyidi, seviye 20 | C lv20 d1 V15 | fixed TP1 SL3 T120 | 16.4 / 1.7 / 11.2 | 3332 | -0.47 | -0.08 [-0.09; -0.07] | -0.01 | -0.05 | -0.03 [-0.04; -0.02] | 0/288 |
| (b) dip + ön sinyal teyidi, seviye 30 | C lv30 d1 V15 | fixed TP1 SL3 T120 | 16.5 / 1.7 / 11.2 | 3350 | -0.47 | -0.08 [-0.09; -0.07] | -0.01 | -0.05 | -0.03 [-0.04; -0.02] | 0/288 |
| (c) limit dolumu + 5 dk içinde ön sinyal, seviye 20 | LC lv20 d1.5 V15 | fixed TP1 SL3 T120 | 21.0 / 2.1 / 16.1 | 4271 | -0.47 | -0.10 [-0.11; -0.09] | -0.01 | -0.08 | -0.02 [-0.04; -0.01] | 0/288 |
| (c) limit dolumu + 5 dk içinde ön sinyal, seviye 30 | LC lv30 d1.5 V15 | fixed TP1 SL3 T120 | 21.6 / 2.3 / 16.9 | 4387 | -0.47 | -0.10 [-0.11; -0.09] | -0.01 | -0.08 | -0.02 [-0.04; -0.01] | 0/288 |

#### Canlı journal adayları — 18 Eyl–16 Eki

Her giriş ailesinin W30 net/sinyal'e göre EN İYİ (hücre, çıkış) bileşimi (**iç-örneklem, iyimser**; işlem ≥ 30). Net/sinyal: dolmayan = 0.

| aile | hücre | çıkış | dolum % (sinyal / rastgele-1 / rastgele-4) | işlem n | net/işlem | net/sinyal [%95] | rastgele-1 | rastgele-4 | sinyal−rastgele-4 [%95] | net/sinyal>0 bileşim (hücre×çıkış) |
|---|---|---|---|---|---|---|---|---|---|---|
| piyasa girişi (sinyal + 60 sn; referans) | M | trail act0.5 gap0.8 SL1.5 T60 | 100.0 / 100.0 / 100.0 | 6283 | -0.49 | -0.49 [-0.53; -0.45] | -0.53 | -0.50 | +0.01 [-0.05; +0.07] | 0/24 |
| düz limit | L d1.5 V15 | trail act0.5 gap0.4 SL3 T60 | 29.0 / 3.6 / 22.1 | 1825 | -0.52 | -0.15 [-0.18; -0.12] | -0.01 | -0.09 | -0.06 [-0.09; -0.02] | 0/288 |
| limit + 5 dk StochRSI K<50 | LK d1.5 V15 | trail act1 gap0.4 SL3 T60 | 12.6 / 1.8 / 11.5 | 794 | -0.41 | -0.05 [-0.07; -0.04] | -0.00 | -0.03 | -0.02 [-0.04; -0.00] | 0/288 |
| (b) dip + ön sinyal teyidi, seviye 20 | C lv20 d1 V15 | trail act0.5 gap0.4 SL3 T120 | 16.3 / 2.3 / 11.1 | 1027 | -0.53 | -0.09 [-0.11; -0.07] | -0.01 | -0.05 | -0.04 [-0.06; -0.02] | 0/288 |
| (b) dip + ön sinyal teyidi, seviye 30 | C lv30 d1 V15 | trail act0.5 gap0.4 SL3 T120 | 16.6 / 2.2 / 11.0 | 1042 | -0.54 | -0.09 [-0.11; -0.07] | -0.01 | -0.05 | -0.04 [-0.06; -0.02] | 0/288 |
| (c) limit dolumu + 5 dk içinde ön sinyal, seviye 20 | LC lv20 d1.5 V15 | trail act0.5 gap0.4 SL3 T60 | 20.2 / 2.7 / 16.2 | 1272 | -0.50 | -0.10 [-0.12; -0.08] | -0.01 | -0.07 | -0.03 [-0.05; -0.01] | 0/288 |
| (c) limit dolumu + 5 dk içinde ön sinyal, seviye 30 | LC lv30 d1.5 V15 | trail act0.5 gap0.4 SL3 T60 | 21.0 / 2.8 / 17.0 | 1317 | -0.49 | -0.10 [-0.12; -0.08] | -0.01 | -0.07 | -0.03 [-0.06; -0.01] | 0/288 |

### 5.4 Tüm bileşimlerin taraması (73 giriş × 24 çıkış = 1 752; işlem ≥ 100 olanlar)

| kaynak / pencere | bileşim sayısı | net/sinyal > 0 | net/işlem > 0 | sinyal−rastgele-4 alt sınırı > 0 |
|---|---|---|---|---|
| HA W30 | 1752 | 0 | 0 | 82 |
| HA B1 | 1752 | 0 | 0 | 183 |
| HA B2 | 1752 | 0 | 0 | 57 |
| HA B3 | 1752 | 0 | 0 | 95 |
| HA ALL | 1752 | 0 | 0 | 163 |
| NOTIF_all W30 | 1752 | 0 | 0 | 100 |
| NOTIF_trend W30 | 1608 | 0 | 0 | 126 |
| LIVE B3 | 1752 | 0 | 0 | 0 |

**HA W30 — net/sinyal'e göre ilk 10 bileşim (iç-örneklem; tümü ≤ 0 ise 'en az kötü'):**

| sıra | hücre | çıkış | dolum % | işlem n | net/işlem | net/sinyal [%95] | rastgele-4 net/sinyal | sinyal−rastgele-4 [%95] |
|---|---|---|---|---|---|---|---|---|
| 1 | LK d1.5 V15 | trail act0.5 gap0.4 SL1.5 T120 | 10.2 | 777 | -0.46 | -0.05 [-0.06; -0.04] | -0.05 | -0.00 [-0.02; +0.01] |
| 2 | LK d1.5 V15 | trail act0.5 gap0.4 SL1.5 T60 | 10.2 | 777 | -0.46 | -0.05 [-0.06; -0.04] | -0.05 | -0.00 [-0.02; +0.01] |
| 3 | LK d1.5 V15 | trail act0.5 gap0.8 SL1.5 T60 | 10.2 | 777 | -0.47 | -0.05 [-0.06; -0.04] | -0.05 | -0.00 [-0.02; +0.01] |
| 4 | LK d1.5 V15 | trail act0.5 gap0.8 SL1.5 T120 | 10.2 | 777 | -0.47 | -0.05 [-0.06; -0.04] | -0.05 | -0.00 [-0.02; +0.01] |
| 5 | LK d1.5 V15 | trail act1 gap0.4 SL1.5 T120 | 10.2 | 777 | -0.47 | -0.05 [-0.06; -0.04] | -0.05 | -0.00 [-0.02; +0.01] |
| 6 | LK d1.5 V15 | fixed TP1.5 SL1.5 T120 | 10.2 | 777 | -0.47 | -0.05 [-0.06; -0.04] | -0.04 | -0.00 [-0.02; +0.01] |
| 7 | LK d1.5 V15 | trail act1 gap0.4 SL1.5 T60 | 10.2 | 777 | -0.48 | -0.05 [-0.06; -0.04] | -0.05 | -0.00 [-0.02; +0.01] |
| 8 | LK d1.5 V15 | trail act0.5 gap0.4 SL3 T120 | 10.2 | 777 | -0.48 | -0.05 [-0.06; -0.03] | -0.04 | -0.01 [-0.03; +0.01] |
| 9 | LK d1.5 V15 | trail act1 gap0.8 SL1.5 T60 | 10.2 | 777 | -0.48 | -0.05 [-0.06; -0.04] | -0.05 | -0.00 [-0.02; +0.01] |
| 10 | LK d1.5 V15 | fixed TP1.5 SL1.5 T60 | 10.2 | 777 | -0.48 | -0.05 [-0.06; -0.04] | -0.04 | -0.00 [-0.02; +0.01] |

### 5.5 Yürüyen-ileri ve ileri çizgi

#### HA 90 gün: yürüyen-ileri (eğitim penceresinde bileşim seç → diğer pencerede DOKUNMADAN ölç), senaryo P

Evren: 73 giriş hücresi × 24 çıkış = 1 752 bileşim (işlem ≥ 100). Ölçüt A = eğitim net/sinyal; ölçüt B = eğitim (net/sinyal − rastgele-4 net/sinyal).

| ölçüt | eğitim → test | seçilen bileşim | eğitim net/sinyal | OOS dolum % | OOS işlem n | OOS net/işlem | OOS net/sinyal [%95] | rastgele-1 | rastgele-4 | sinyal−rastgele-4 [%95] | OOS iyimser (0 sn/%0,05) net/sinyal |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A | B1 → B2 | LK d1.5 V15 / fixed TP1.5 SL3 T120 | -0.04 | 9.3 | 635 | -0.41 | -0.04 [-0.06; -0.02] | -0.00 | -0.04 | +0.00 [-0.02; +0.02] | -0.03 |
| A | B1 → B3 | LK d1.5 V15 / fixed TP1.5 SL3 T120 | -0.04 | 10.1 | 753 | -0.51 | -0.05 [-0.07; -0.03] | -0.01 | -0.04 | -0.01 [-0.04; +0.02] | -0.04 |
| A | B2 → B1 | LK d1.5 V15 / fixed TP1.5 SL1.5 T120 | -0.03 | 11.8 | 720 | -0.36 | -0.04 [-0.06; -0.03] | +0.00 | -0.05 | +0.00 [-0.01; +0.02] | -0.03 |
| A | B2 → B3 | LK d1.5 V15 / fixed TP1.5 SL1.5 T120 | -0.03 | 10.1 | 753 | -0.48 | -0.05 [-0.06; -0.04] | -0.01 | -0.04 | -0.00 [-0.02; +0.01] | -0.04 |
| A | B3 → B1 | LK d1.5 V15 / trail act0.5 gap0.4 SL1.5 T120 | -0.05 | 11.8 | 720 | -0.46 | -0.05 [-0.06; -0.04] | -0.01 | -0.05 | -0.00 [-0.02; +0.01] | -0.04 |
| A | B3 → B2 | LK d1.5 V15 / trail act0.5 gap0.4 SL1.5 T120 | -0.05 | 9.3 | 635 | -0.41 | -0.04 [-0.05; -0.03] | -0.01 | -0.04 | +0.01 [-0.01; +0.02] | -0.03 |
| A | B12 → B3 | LK d1.5 V15 / fixed TP1.5 SL3 T120 | -0.04 | 10.1 | 753 | -0.51 | -0.05 [-0.07; -0.03] | -0.01 | -0.04 | -0.01 [-0.04; +0.02] | -0.04 |
| B | B1 → B2 | LK d0.3 V60 / fixed TP1.5 SL3 T60 | -0.16 | 26.5 | 1799 | -0.56 | -0.15 [-0.18; -0.12] | -0.13 | -0.18 | +0.03 [-0.01; +0.07] | -0.11 |
| B | B1 → B3 | LK d0.3 V60 / fixed TP1.5 SL3 T60 | -0.16 | 28.1 | 2092 | -0.58 | -0.16 [-0.18; -0.14] | -0.14 | -0.21 | +0.05 [+0.01; +0.09] | -0.13 |
| B | B2 → B1 | LK d0.3 V60 / trail act0.5 gap0.4 SL1.5 T60 | -0.13 | 28.5 | 1740 | -0.56 | -0.16 [-0.18; -0.14] | -0.15 | -0.22 | +0.06 [+0.04; +0.09] | -0.11 |
| B | B2 → B3 | LK d0.3 V60 / trail act0.5 gap0.4 SL1.5 T60 | -0.13 | 28.1 | 2092 | -0.52 | -0.15 [-0.16; -0.13] | -0.14 | -0.20 | +0.05 [+0.03; +0.08] | -0.10 |
| B | B3 → B1 | LK d0.3 V60 / fixed TP1.5 SL1.5 T60 | -0.15 | 28.5 | 1740 | -0.57 | -0.16 [-0.18; -0.14] | -0.15 | -0.23 | +0.07 [+0.04; +0.10] | -0.12 |
| B | B3 → B2 | LK d0.3 V60 / fixed TP1.5 SL1.5 T60 | -0.15 | 26.5 | 1799 | -0.52 | -0.14 [-0.16; -0.12] | -0.13 | -0.18 | +0.04 [+0.01; +0.07] | -0.11 |
| B | B12 → B3 | LK d0.3 V60 / trail act0.5 gap0.4 SL1.5 T60 | -0.15 | 28.1 | 2092 | -0.52 | -0.15 [-0.16; -0.13] | -0.14 | -0.20 | +0.05 [+0.03; +0.08] | -0.10 |

Yürüyen-ileri özeti: 14 satır; OOS net/sinyal > 0: 0; %95 alt sınırı > 0: 0; sinyal−rastgele-4 alt sınırı > 0: 6.

#### Donmuş seçim (HA B1+B2'de seçildi) → HA B3, canlı journal adayları (ileri, 18 Eyl–16 Eki), canlı bildirimler

| ölçüt | seçilen bileşim | kaynak / pencere | dolum % | işlem n | net/işlem | net/sinyal [%95] | rastgele-1 | rastgele-4 | sinyal−rastgele-4 [%95] | iyimser (0 sn/%0,05) net/sinyal |
|---|---|---|---|---|---|---|---|---|---|---|
| A | LK d1.5 V15 / fixed TP1.5 SL3 T120 | HA B3 | 10.1 | 753 | -0.51 | -0.05 [-0.07; -0.03] | -0.01 | -0.04 | -0.01 [-0.04; +0.02] | -0.04 |
| A | LK d1.5 V15 / fixed TP1.5 SL3 T120 | LIVE B3 | 12.6 | 794 | -0.43 | -0.05 [-0.07; -0.04] | -0.00 | -0.03 | -0.03 [-0.05; -0.01] | -0.04 |
| A | LK d1.5 V15 / fixed TP1.5 SL3 T120 | NOTIF_all W30 | 9.9 | 181 | -0.56 | -0.06 [-0.08; -0.03] | -0.00 | -0.06 | +0.01 [-0.03; +0.04] | -0.05 |
| A | LK d1.5 V15 / fixed TP1.5 SL3 T120 | NOTIF_trend W30 | 11.2 | 70 | -0.29 | -0.03 [-0.08; +0.02] | -0.01 | -0.08 | +0.04 [-0.03; +0.12] | -0.03 |
| B | LK d0.3 V60 / trail act0.5 gap0.4 SL1.5 T60 | HA B3 | 28.1 | 2092 | -0.52 | -0.15 [-0.16; -0.13] | -0.14 | -0.20 | +0.05 [+0.03; +0.08] | -0.10 |
| B | LK d0.3 V60 / trail act0.5 gap0.4 SL1.5 T60 | LIVE B3 | 33.5 | 2102 | -0.54 | -0.18 [-0.20; -0.16] | -0.15 | -0.19 | +0.01 [-0.02; +0.04] | -0.13 |
| B | LK d0.3 V60 / trail act0.5 gap0.4 SL1.5 T60 | NOTIF_all W30 | 21.8 | 399 | -0.65 | -0.14 [-0.18; -0.11] | -0.16 | -0.21 | +0.07 [+0.02; +0.11] | -0.10 |
| B | LK d0.3 V60 / trail act0.5 gap0.4 SL1.5 T60 | NOTIF_trend W30 | 18.3 | 114 | -0.53 | -0.10 [-0.15; -0.04] | -0.16 | -0.26 | +0.16 [+0.10; +0.23] | -0.06 |

### 5.6 LUNATRY 17 Ekim sağlaması (B)

LUNATRY için kayıtlı ilk HA adayı 01:15:30'da (fiyat 2,212; t0 01:00'daki P0 = 2,176 → yükselişin %1,7'si geçmişti) ve tek canlı bildirim 02:03:29'da (fiyat 2,31, trend_devam) idi. Aşağıda bu iki sinyal için limit girişler (doğrudan 1 dk yolundan; net % 60 sn gecikme / %0,15 çıkış kayması / %0,1125 ücret):

| sinyal | giriş | doldu mu (dk sonra) | fiyat 60 dk sonra / giriş | net % (fixed TP1.5 SL3 T120) | net % (trail act0.5 gap0.8 SL3 T120) | net % (fixed TP1 SL1.5 T60) |
|---|---|---|---|---|---|---|
| HA adayı 01:15:30 (fiyat 2,212; P0'ın +%1,7 üstü) | piyasa (60 sn + %0,15 kayma) | giriş | +3.17% | +1.27 | +5.69 | +0.77 |
| | limit d0.3% V15 | 1 dk | +3.34% | +1.27 | +6.02 | +0.77 |
| | limit d0.3% V60 | 1 dk | +3.34% | +1.27 | +6.02 | +0.77 |
| | limit d0.6% V15 | dolmadı | | 0 (işlem yok) | 0 (işlem yok) | 0 (işlem yok) |
| | limit d0.6% V60 | dolmadı | | 0 (işlem yok) | 0 (işlem yok) | 0 (işlem yok) |
| | limit d1% V15 | dolmadı | | 0 (işlem yok) | 0 (işlem yok) | 0 (işlem yok) |
| | limit d1% V60 | dolmadı | | 0 (işlem yok) | 0 (işlem yok) | 0 (işlem yok) |
| | limit d1.5% V15 | dolmadı | | 0 (işlem yok) | 0 (işlem yok) | 0 (işlem yok) |
| | limit d1.5% V60 | dolmadı | | 0 (işlem yok) | 0 (işlem yok) | 0 (işlem yok) |
| bildirim trend_devam 02:03:29 (fiyat 2,31; P0'ın +%6,2 üstü) | piyasa (60 sn + %0,15 kayma) | giriş | -0.44% | -0.91 | -0.91 | -1.87 |
| | limit d0.3% V15 | 1 dk | -0.87% | -1.20 | -1.20 | -1.87 |
| | limit d0.3% V60 | 1 dk | -0.87% | -1.20 | -1.20 | -1.87 |
| | limit d0.6% V15 | 1 dk | -0.57% | -0.90 | -0.90 | -1.87 |
| | limit d0.6% V60 | 1 dk | -0.57% | -0.90 | -0.90 | -1.87 |
| | limit d1% V15 | 1 dk | -0.17% | -0.50 | -0.67 | -0.54 |
| | limit d1% V60 | 1 dk | -0.17% | -0.50 | -0.67 | -0.54 |
| | limit d1.5% V15 | 2 dk | +0.51% | +0.00 | -0.67 | +0.14 |
| | limit d1.5% V60 | 2 dk | +0.51% | +0.00 | -0.67 | +0.14 |

## 6. Sınırlar

- **Veri:** 90 gün, tek piyasa rejimi (TRY pariteleri, Temmuz–Ekim 2026); W30 yalnız bir ay. Notification kaynakları küçük (W30'da hepsi 1834, trend_devam 624 bölüm) → güç düşük; kararlar HA (≈ 20 bin bölüm) ve Çalışma A (yüz binlerce sinyal) üzerinde ağırlıklı.
- **Limit dolumu varsayımı:** düşük limitin KESİNLİKLE altına inince dolar ve dolum fiyatı limit; kuyruk önceliği, kısmi dolum, defter derinliği ve emrin gerçekte bar içi önce/sonra sırası modellenmedi. Dolum barında yükselişler yok sayıldı (kötümser). Gerçekte dolum oranı bu sayıdan düşük olabilir (fiyat limite değer ama emir sıranın arkasında kalır) — bu yalnız sonuçları KÖTÜLEŞTİRİR; yani 'hayır' kararını güçlendirir.
- **Rastgele taban yanlılıkları:** (1) ve (2) 'herhangi bir sinyalden ≥ 2 sa uzak' koşulu geleceğe bakar: ön sinyal (düşüş dibi) olmayan anlar yükselişte olur → taban yukarı yanlı (5m ön sinyalde taban ≈ +0,1 net). (3)/(4) dışlamasızdır ama sinyallerin kendisini az miktarda içerir (sinyal oranı ≈ %2–4); (4) oynaklık eşleşmesi son 30 dk aralığıyla yaklaşıktır, yönü/momentumu eşleştirmez. Sinyal − taban farkları bu yüzden taban türüne duyarlıdır; ana kararlar mutlak net'e (< 0) dayanır, tabana bağlı değil.
- **Çoklu karşılaştırma:** 12 küme × 24 çıkış; 73 giriş × 24 çıkış; 'en iyi hücre' tabloları iç-örneklem ve iyimser. Pozitif bir hücre olsaydı bile walk-forward gerekirdi; hiç pozitif yok.
- **Kayma/gecikme:** sabit %0,15 ve 60 sn; düşük likit sembollerde gerçek kayma daha büyük olabilir (özellikle 1m ön sinyaller), yüksek likitlerde daha düşük. İyimser (0 sn/%0,05) senaryo da raporlandı: sonuç aynı.
- **Çekirdek tanımı:** uygulamadaki kesik pencereli (son 8 bar) RQK; kanonik 25 bar pencere değil. 1m çekirdekte düz (hacimsiz) mumlar çekirdeği 'kırmızı' tutuyor (1m yeşil oranı %35). Frontend StochRSI kodu henüz yoktu → grafikteki ile BİREBİR eşleşme doğrulanamadı (yalnız isteğe göre tanım ve birim testleri).
- **Hacim/uç durumlar:** 1 dk çıkış yolunda bar-içi sıra kötümser (stop önce). Sinyal sonrası 120 dk veri gerektiği için veri sonuna yakın sinyaller atıldı (yanlılık yaratmaz, sayıyı azaltır).
- **Canlı koda dokunulmadı:** yalnız `app/rescan/stochrsi.py` (yeni), `app/rescan/exit_sim.py` (geriye uyumlu `entry_slip_pct`), testler ve `scripts/limitstoch_*.py` eklendi.
