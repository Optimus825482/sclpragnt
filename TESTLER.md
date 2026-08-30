# PUMP ARAŞTIRMASI — TEST RAPORU (TESTLER.md)

**Tarih:** 30–31 Ağustos 2026 · **Kapsam:** ≥%2 M5 pump desenleri, gösterge snapshot analizi, OOS doğrulama, maliyet simülasyonu, v2 aday filtresi
**Veri:** Binance TR public API · 50 likit TRY sembolü · 7 gün M5 (2.017 mum/sembol) + M1 (10.081 mum/sembol) · PostgreSQL `historical_candles`
**Kod:** `backend/scripts/pump24/` · **Rapor JSON'ları:** kök dizinde `pump24_*.json` · **DB:** `research_runs` id=6,8,9,10,11 + `research_patterns` 3 kayıt

---

## 1. Araştırma Soruları

1. ≥%2 M5 pump'larından **önceki** 10 M1 mum ve 3 M5 mumdaki gösterge snapshot'larında, pump'ı **önceden** haber veren ortak desen var mı? (kullanıcının "%70'inde RSI<40" tarzı madencilik isteği)
2. Bulunan desenler **out-of-sample** (OOS) stabil mi?
3. **Komisyon sonrası** pozitif beklenen değer (EV) üreten hedef/stop kombinasyonu var mı?
4. Canlıdaki **v2 aday filtresi** gerçekten seçim yapıyor mu?

---

## 2. ⚠️ KRİTİK BULGU: Veri Ayrıştırma Bugı (önce tüm sonuçları geçersiz kıldı)

İlk `normalize_binance` fonksiyonu Binance kline sütunlarını **bir kaydırarak** okuyordu (`row[0]`=timestamp → `open` alanına yazılıyordu). Sonuç: 213.574 bozuk mum (`high < low`).

- **Teşhis:** frame değerlerinde `open=1788065400000.0` ve `high<low` tutarsızlığı.
- **Aksiyon:** bozuk satırlar silindi, 7 günlük veri yeniden çekildi, **tüm testler temiz veriyle baştan koşuldu**.
- **Ders:** yeni veri parsellerinde OHLC tutarlılık kontrolü (`low ≤ min(open,close) ≤ max(open,close) ≤ high`) zorunlu; eski `pump24_volatility_confluence` candidate kaydı DB'de `invalid_data` yapıldı.

Aşağıdaki tüm bulgular **temiz veri** iledir.

---

## 3. Test Özeti (chronological)

| # | Test | Script | Soru | Sonuç |
|---|------|--------|------|-------|
| 1 | Veri hattı + smoke | `run.py smoke` | Göstergeler app ile aynı mı? | ✅ RSI/ATR/ADX 1e-6 eşleşme, 79 öznitelik |
| 2 | Pump tespiti + snapshot | `run.py events` | ≥%2 olaylar ve 13 grup snapshot | ✅ 24h: 54 olay · 6d train: 185 olay |
| 3 | Desen madenciliği | `run.py patterns` | Pump öncesi ortak göstergeler | ⚠️ Desenler pump **sırasında** beliriyor, öncesinde değil |
| 4 | 24h backtest | `run.py backtest` | Kurallar tabanı yener mi? | ✅ Evet (baz %12,7 → kurallar %50–70) |
| 5 | OOS doğrulama | `oos.py oos` | Train→test stabil mi? | ✅ Stabil (~1 puan düşüş) |
| 6 | Erken giriş | `early.py` | Pump'tan 5 dk önce sinyal var mı? | ❌ **Yok** (EV lift +0,01–0,02 pt) |
| 7 | MFE dağılımı | `oos.py` devamı | Gerçek potansiyel ne? | ✅ ema_gap>2: medyan MFE +1,96% |
| 8 | Hedef/stop izgarası | `grid.py` | Pozitif EV hücresi var mı? | ❌ **Hiç yok** (240 hücre/kural) |
| 9 | v2 filtre testi | `filter_v2_test.py` | UI filtresi seçim yapıyor mu? | ✅ **Güçlü** (+26pp dokunuş lifti) |
| 10 | Kesişim v2×pump | `intersection.py` | En iyi izleme seti hangisi? | ✅ İzleme: evet · ❌ Otonom giriş: hayır |

---

## 4. Detaylı Bulgular

### 4.1 Tanımlar
- **Pump:** `M5 kapanış(i) / kapanış(i−1) − 1 ≥ %2` — `m5_g0` = yükselişin başladığı mum, `m5_g1/g2` = önceki M5'ler; `m1_g0..g9` = yükselişten önceki son 10 M1 mumu (g0 en yakın).
- **Dokunuş (MFE):** sinyal mumu kapanışından sonra N M5 bar içinde `high ≥ hedef`.
- **Maliyet:** taker gidiş-dönüş %0,35 (komisyon 0,15×2 + kayma 0,025×2 — `app/config.py`); maker %0,15.
- **EV:** düz N-bar tutma getirisi − maliyet; **yarış EV:** hedefe/stop'a hangisi önce vurulur.

### 4.2 Sinyal gerçek ve OOS stabil (Bulgu 1)
En iyi kurallar 6 gün train'de madencilendi, 7. gün (temiz, hiç görülmemiş) testte:

| Kural (sinyal mumu kapanışında) | Test n | Komisyon-hedef vurma | Taban | Net EV |
|---|---|---|---|---|
| `m5g0_atr_pct > 1,5` | 662 | **%70,8** | %13,65 | ~0 (taker, dar hedef) |
| `m5g0_ema_gap_pct > 1` | 529 | %63,3 | %13,65 | −0,11% |
| `m5g0_bb_width > %6` | 855 | %60,1 | %13,65 | −0,14% |

Train→test güç düşüşü ~1 puan → **overfit yok**. Sinyal "sonraki 15 dk'da +1%'e dokunma" olasılığını 5× artırıyor.

### 4.3 Erken giriş yolu kapalı (Bulgu 2) — kullanıcının hipotezi test edildi
M1 göstergeleri (m1_g0..g9) ve önceki M5 göstergeleri karar mumunun **açılışından** (pump'tan ~5 dk önce) değerlendirildi (`early.py`, 202 kural, 79.968 train + 10.656 test bar):

- En iyi erken kuralların EV avantajı **+0,01–0,02 puan** (istatistiksel gürültü).
- **Sonuç:** pump'tan önce (10 dk içinde) gösterge deseni yok; sinyal ancak pump'ın ilk M5 mumu **içinde** kendini gösteriyor. Pump öncesi M1 snapshot'ları ARŞİV değeri var ama ÖNGÖRÜ değeri yok.

### 4.4 Izgara taraması: pozitif EV yok (Bulgu 3)
`grid.py` — 8 kural × **240 hücre** (6 hedef %0,6–3 × 5 stop %0,5–2 × 2 ufuk 15/30dk × 2 giriş modu × 2 maliyet):

- **Train penceresinde hiçbir hücre pozitif EV üretmedi** (en iyi −0,086%).
- Dar stop (%0,5): %82–85 stop oranı — pump barları 1%+ ATR ile oynadığı için mikro stop her seferinde vuruluyor.
- Geniş stop + taker: hedef/stop asimetrisi maliyeti yiyor.
- Testte pozitife geçen 2 hücre train'de **negatifti** → seçim gürültüsü, aday değil.
- **DB:** `pump24_no_positive_ev_close_entry` (status=`rejected_for_trading`, güven 0,75).

### 4.5 v2 aday filtresi doğrulandı (Bulgu 4)
UI'daki filtre birebir test edildi: `ATR%≥0,3 · BB genişlik≥2,5% · RSI≥60 (trend) veya ≤35 (V-dönüş) · MFI 10–90 · LinReg eğim≥%0,2/bar VEYA Aroon≥50`

| Pencere | Geçen bar | +0,95 dokunuş | Taban | Lift | avg MFE3 |
|---|---|---|---|---|---|
| Train (6g) | 6.848 (%8,3) | %30,2 | %11,8 | +18,4pp | %0,92 (taban %0,41) |
| **Test (24h OOS)** | 976 (%9,9) | **%40,4** | %14,4 | **+26,0pp** | **%1,42 (taban %0,53, 2,7×)** |

- Güç train→test **arttı** → filtre bozulmuyor, volatil rejimde daha isabetli.
- **RSI kolları asimetrik:** trend kolu (≥60) değeri taşır (test %41,0, n=936); V-dönüş kolu (≤35) zayıf ve örneklem küçük (n=40, %25,0) — ayrı kalibrasyon gerekir.
- **UI kalibrasyon notu:** UI hedefi %19 / ölçülen %17,5 — muhtemelen farklı isabet tanımı. MFE-tanımıyla hizalama yapılmadan ATR kaydırma döngüsü yanlış yöne kalibre edebilir.
- **DB:** `pump24_filter_v2_watchlist` (status=`validated_as_filter`, güven 0,7).

### 4.6 Kesişim: v2 × pump sinyalleri (Bulgu 5)
`intersection.py` + **gün-bazlı** analiz (7 günün her biri ayrı):

**Test günü (trend günü) parlak görünmüştü:**

| Set | n | +0,95 dokunuş | Medyan MFE | EV (maker, stopsuz) |
|---|---|---|---|---|
| v2 ∧ ema_gap>2 | 131 | %69,5 | %2,25 | +0,60% |
| v2 ∧ ATR≥1,5 | 225 | %67,6 | %1,85 | +0,39% |

**Ama haftalık gerçektir (gün-bazlı ağırlıklı):**

| Set | n | avg ret3 | EV maker | Pozitif gün | Ort. dokunuş %55–70 |
|---|---|---|---|---|---|
| v2 ∧ ema_gap>2 | 607 | +0,184% | **+0,034% (≈0)** | 3/7 | %64,1 |
| v2 ∧ ATR≥1,5 | 1.153 | +0,006% | −0,144% | 2/7 | %63,0 |
| Sadece v2 | 7.850 | +0,014% | −0,136% | 1/7 | %31,1 |

- **Dokunuş oranı gün-bazlı STABİL** (%55–70; taban %12–25) → seçim gücü rejimden bağımsız.
- **Getiri rejim bağımlı:** sıkışma (chop) günlerinde pump sonrası getiri −0,5..−0,9%; trend günlerinde +0,5..+0,8%.
- **DB:** `pump24_v2_x_pump_watchlist` (status=`validated_as_filter`, güven 0,7).

---

## 5. Kararlar ve Canlı Kullanım Önerisi

| Kullanım | Karar |
|---|---|
| **Aday/izleme tarama filtresi** | ✅ **KULLAN:** `v2 VE (ema_gap>2 veya ATR≥1,5)` → günlük ~85–165 sinyal barı; %55–70'i 15 dk'da +0,95'e dokunur (3–4× sıkılaştırma) |
| **Otonom giriş sinyali** | ❌ **KULLANMA:** stoplu yarışta hiçbir hücre pozitif değil; stopsuz tutma EV'si rejime bağlı (haftalık ≈0) |
| **Pump öncesi M1 tahmini** | ❌ Yol kapalı — önceden öngörü yok; sinyal ilk pump mumu içinde |
| **Giriş kararı** | Ayrı katmana bırakılmalı (ScalpAnalyzer / LLM konfluans) |

## 6. Açık Kalan Adımlar

1. **Rejim filtresi:** chop_index/ADX ile 4 negatif günü ayıklayıp EV'yi pozitife taşıma denemesi (dokunuş zaten stabil — tek eksik gün tipi ayrımı).
2. **Maker-fill modeli:** 30+ gün veriyle maker giriş (limits emir) ters-seçim riskinin ölçülmesi — tek teorik pozitif pencere burası.
3. **UI kalibrasyon hizalaması:** kalibrasyon döngüsünün isabet tanımı ile MFE-tanımının eşitlenmesi.
4. V-dönüş (RSI≤35) kolunun ayrı kalibrasyonu / eşiğin %30'a çekilmesi.

## 7. Rapor Dosyaları (repo kökü)

| Dosya | İçerik |
|---|---|
| `pump24_desen_raporu.json` | İlk desen madenciliği + grup istatistikleri (temiz veri öncesi mimari referans) |
| `pump24_oos_raporu.json` | 6g train / 1g test OOS + fee simülasyonu |
| `pump24_oos_sim_raporu.json` | OOS + yarış EV + MFE dağılımı konsolide rapor |
| `pump24_grid_raporu.json` / `pump24_grid_sonuc_raporu.json` | 240 hücrelik izgara detayı + karar |
| `pump24_filtro_v2_test.json` / `pump24_filtro_v2_sonuc.json` | v2 filtre detay istatistik + karar |
| `pump24_kesisim_test.json` / `pump24_kesisim_sonuc_raporu.json` | Kesişim setleri + gün-bazlı EV |
| `pump24_early_raporu.json` | Erken giriş (pump öncesi) testi |

**DB izleri:** `research_runs` (id 6, 8, 9, 10, 11) · `research_patterns`: `pump24_volatility_confluence` (invalid_data) · `pump24_no_positive_ev_close_entry` (rejected_for_trading) · `pump24_filter_v2_watchlist` + `pump24_v2_x_pump_watchlist` (validated_as_filter).

## 8. Teknik Notlar / Tuzaklar

- **Binance TR M1'de işlem olmayan dakikalarda mum üretilmez** → frame builder boş dakikaları flat doldurur (`smc.fill_m1_gaps`).
- Binance TR kline API ~8 gün 1m geçmiş tutar; daha gerisi OKX public API'den onarılabilir (`data.fetch_okx_klines`).
- psycopg3'te `mogrify` yok → `executemany` kullan.
- Fiyat-ölçekli göstergeler (MACD, Awesome, OBV) semboller arası eşikte anlamsızdır → yüzde-normalize sürümler (`macd_hist_pct`, `awesome_pct`, `obv_slope_norm`).
- Eşikler alan ölçeğine göre `patterns.FIELD_THRESHOLDS`'ta tanımlı; her alana aynı ızgarayı vurmak sahte %100 kurallar üretir.
- Pipeline komutları (`backend/scripts` cwd): `venv/Scripts/python.exe -m pump24.run fetch|events|patterns|backtest|smoke 24` · `-m pump24.oos fetch7d|oos` · `-m pump24.grid grid` · `-m pump24.intersection` · `-m pump24.filter_v2_test`
