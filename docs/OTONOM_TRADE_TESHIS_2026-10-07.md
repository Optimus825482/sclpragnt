# Otonom Paper Trade Teşhisi ve Düzeltmesi — 2026-10-07

Bu belge, "uygulama sinyal başarısı iyi ama otonom işlemler hep zarar ediyor"
şikâyeti üzerine yapılan incelemenin kanıtlarını, düzeltmelerini ve
önerilen konfigürasyonu kaydeder.

**Yöntem:** canlı DB (1538 kapanan işlem, 3223 bildirim) + **gerçek Binance TR
5 dakikalık mumları** (256 sembol × 9000 mum, 2026-09-06 → 2026-10-07) üzerinden
mum-içi replay. Tüm rakamlar tur başı **%0,325 maliyet** (2×%0,15 komisyon +
2×%0,025 slipaj) düşülmüş **net** değerlerdir. Scriptler: `work/*.py`,
veri: `work/analiz_2026-10-07/`.

---

## ÖZET (kısa)

1. Otonom katman **-10.621 TRY**. İşlem başına **-%0,312**.
2. Sebep giriş kalitesi değil, **karışık sinyal havuzu + maliyet**. Sinyal brüt
   olarak yazı-turaya yakın.
3. Ancak **tek bir sinyal modu gerçek ve kalıcı bir edge taşıyor: `trend_devam`.**
4. `trend_devam` + bildirim dedup + dar trailing ile: **+0,375 — +0,470%/işlem**,
   5/5 hafta pozitif, train/test ikisinde pozitif, null testi **p≈0,000**.

---

## 1. Mevcut durum: neden zarar ediyor

| Çıkış nedeni | n | ort PnL% | toplam TL |
| --- | --- | --- | --- |
| breakeven_stop | 457 | +1.419 | +16.688 |
| trailing_stop | 296 | +1.507 | +7.566 |
| take_profit | 101 | +2.745 | +5.615 |
| **stop_loss** | **353** | **-4.271** | **-34.815** |
| symbol_deactivated | 201 | -0.929 | -2.992 |
| max_duration | 122 | -1.181 | -2.448 |
| manual_close | 8 | -1.660 | -235 |

Kazanan ort +%1,58 / kaybeden ort -%2,93 → **R:R 1:1,85 terste**. İsabet %62;
başabaş için %65 gerekiyor. Gerçekleşen -%0,312 **komisyon düşülmüş** hâlidir;
maliyet %0,325 → **brüt beklenti ≈ +%0,01**, yani sinyal başabaş.

Bunu doğrulayan bağımsız ölçüm — aynı pencerede gerçek ileri fiyatlarla
(743 bildirim, 15 dk): **MFE +%1,60 / MAE -%1,68**. MFE ≈ MAE olması, sinyalin
yön değil **volatilite** seçtiğinin imzasıdır.

## 2. Ayarların gerçek durumu (canlı)

| | Ayar | Gerçekleşen |
| --- | --- | --- |
| TP hedefi | bildirimden +%4,30 | tepe medyan **+%1,62** |
| Stop | -%4,00 (1276 işlemde sabit) | ort. kayıp -%2,93 |
| Ufuk | sinyal **5 dk** | pozisyon **60 dk** |

`default_target_pct` **fiilen etkisiz**: TP bildirimin kendi `target_pct`'inden
gelir; varsayılan yalnızca bildirimde hedef yoksa kullanılır. İşlemlerin
**%87'si** hedefe değmiyor (hedef = ulaşılabilir tepenin 2,7 katı).

Tutma süresi × sonuç — ilk 5 dakikadan sonrası zarar:

| Tutma | n | ort PnL% |
| --- | --- | --- |
| 0-5 dk | 490 | **+0,452** |
| 5-15 dk | 359 | -0,425 |
| 15-30 dk | 219 | -0,320 |
| 30-60 dk | 234 | -1,079 |
| 60-120 dk | 160 | -1,208 |

## 3. ASIL BULGU: mod ayrımı

3214 bildirim, 30 gün, gerçek mum verisi, 5 dk sabit çıkış:

| Mod | n | net% | isabet | train / test |
| --- | --- | --- | --- | --- |
| **trend_devam** | 853 | **+0.269** | **45%** | +0.412 / -0.066 |
| unified | 1066 | -0.258 | 35% | -0.309 / -0.139 |
| notr | 418 | -1.226 | 30% | -1.424 / -0.767 |
| llm_ikinci_goz | 186 | -0.670 | 25% | -0.570 / -0.901 |
| global_lead_lag | 684 | -0.455 | 33% | -0.457 / -0.452 |

`trend_devam` diğerlerinden **istatistiksel olarak farklı** ve tek pozitif mod.

### 3.1 Nihai strateji (mod filtresi + dedup + trailing)

| Konfigürasyon | n | net% | train / test |
| --- | --- | --- | --- |
| trend_devam + 60dk dedup + TP+1.5/tr0.4 | 541 | +0.110 | +0.123 / +0.080 |
| **trend_devam + 60dk dedup + TP+2.5/tr0.3 (+SL-5, 120dk)** | **541** | **+0.375** | +0.424 / +0.263 |
| trend_devam + 60dk dedup + TP+4.0/tr0.3 (+SL-5) | 541 | +0.701 | +0.787 / +0.501 |

Aynı strateji diğer modlara uygulanınca **negatif** (unified +0.02,
global_lead_lag -0.13, notr -0.70) → edge modun kendisinde, çıkış kuralında değil.

### 3.2 Sağlamlık kanıtları

- **Hafta bazında 5/5 pozitif**: +0.047 / +1.213 / +0.602 / +0.158 / +0.626
- **Train/test**: %70/%30 ayrımında **ikisi de pozitif** (+0.424 / +0.263)
- **Null testi**: mod etiketi karıştırıldığında 400 rastgele örneklemin
  **0'ı** bu sonuca ulaştı → **p ≈ 0.000**
- **Parametre yüzeyi monoton**: TP 1.5→2.5→4.0 ve trail 0.3→0.8 boyunca düzgün
  artış/azalış; tesadüfi gürültüde bu olmaz
- **Dedup penceresi geniş toleranslı**: 0/30/60/120/240 dk hepsi pozitif

### 3.3 Risk ölçüsü (dürüst taraf)

- Stop **olmadığında** en kötü işlem **-%28,5** (120 dk pencerede tek yönlü
  hareket). **SL-5.0 bunu -%5,3'e indirip getirinin %80'ini koruyor.**
- Std 2,35; medyan +0,88. Getiri pozitif eğimli ama tek işlemlerde ±%20 oynar.
- Kazananların kuyruğu kalın: en iyi %5 işlem toplam getirinin ~%23'ü.
- 17 işlem/gün (541 işlem / 30,1 gün).

## 4. ÇÜRÜTÜLEN hipotezler (kayda geçiyor)

| Hipotez | Sonuç | Kanıt |
| --- | --- | --- |
| Giriş kovalama (tepeden alım) | **YANLIŞ** | ≥%3 uzamış 333 işlem -%0,31 vs <%1 uzamış 757 işlem -%0,30 — fark yok; tepe ≥%2 oranı da aynı (%31,4 vs %33,6) |
| Hedef tavanı kâr getirir | **YANLIŞ** | iyimser varsayımla bile TP+1,5 -%0,485, mevcut -%0,312 |
| Sıkı stop zararı keser | **YANLIŞ (canlıda denendi)** | SL 4→1,5: -%0,121 → -%0,853, **7 kat kötü**; geri alındı |
| Breakeven tavanı | **GERÇEKLEŞEMEZ** | iyimser sınırda yalnızca %0,5 eşiğinde pozitif |
| Ölü işlemler girişte elenir | **AYRIŞTIRICI YOK** | skor/ml/MACD/saat/gecikme farkları ~0 |
| velocity_score yüksek = iyi | **TERS** | ≥1000: -%0,59 vs 100-300: -%0,36 |
| ML olasılığı yüksek = iyi | **TERS** | ≥0,5: -%1,04, en kötü bant |
| Onay sayısı (teyit) | **AYRIŞTIRMIYOR** | teyit=1: -%0,397, teyit=3: -%0,294 |

## 5. Bu çalışmada düzeltilen hatalar

1. **TP2 sıralama hatası** (`auto_paper.py`): Master Surge TP2 hedefi, TP fiyatı
   hesaplandıktan SONRA yükseltiliyordu → DB'ye ulaşılamayacak hedef yazılıyor,
   `take_profit` eski düşük değerde kalıyordu. Artık TP2 TP'den önce uygulanıyor.
2. **Hedef tavanı mekanizması** (`AUTO_PAPER_MAX_TARGET_PCT`, varsayılan
   **0 = kapalı**): opsiyonel üst sınır. Geriye dönük uyumlu. *(§4 gereği
   bugün açık önerilmiyor.)*
3. **ATR stop koruması ölü koddu**: `max(sl_pct, min(TABAN, 1.2*atr))`, canlıda
   `sl_pct(%4) > TABAN(%2,8)` olduğu için her zaman `sl_pct` döndürüyordu →
   koruma sessizce tamamen devre dışıydı.
4. **Rapor etiketleri yanıltıcıydı** (`reports/page.tsx`): "TP1 KİLİTLENDİ" /
   "TP2 KOŞUSU" yalnızca **tepe noktasına** bakıyordu ve `KISMİ` kontrolünden
   önce geldiği için hedefe hiç dokunmamış satırlara da yazıyordu. Kanıt:
   07:41 NMRTRY "TP1 KİLİTLENDİ" derken otonom PnL **-%4,32**.
   Etiketler "TEPE ≥%1,2 (hedefe değmedi)" oldu; "ZAMAN AŞIMI" →
   "ÖLÇÜLEMEDİ (1m mum yok)".
5. **YENİ — mod filtresi kapısı** (`allowed_modes`, varsayılan boş = kapalı).
6. **YENİ — bildirim dedup kapısı** (`dedup_cooldown_minutes`, varsayılan 0 =
   kapalı). Aynı sembolde kısa süre önce giriş varsa tekrar açmaz.
   `database.get_last_auto_paper_entry_time` eklendi.

## 6. UYGULAMA NOTU (önemli)

Yukarıdaki kapıların ikisi de **varsayılan olarak kapalı**. Kod değişikliğini
canlıya almak hiçbir davranışı değiştirmez; etki **ayarlar** üzerinden açılır:

| Ayar | Önerilen | Etki |
| --- | --- | --- |
| `allowed_modes` | `["trend_devam"]` | yalnızca edge taşıyan modu işle |
| `dedup_cooldown_minutes` | `60` | aynı sembole saatte en fazla bir giriş |
| `trailing_trigger_pct` | `1.0` | kârı erken kilitle |
| `trailing_gap_pct` | `0.3` | dar geri çekilme |
| `max_hold_minutes` | `120` | 5 dk'lık sinyale uygun tavan |
| `stop_loss_pct` | `5.0` | **felaket stopu** (kuyruğu -%28,5 → -%5,3) |

**Dikkat:** canlıdaki `stop_loss_pct` şu an **4,0**. Backtest'te 5,0 daha iyi
(+0,375 vs +0,332) ama fark küçük; 4,0'ı bırakmak da savunulabilir.

**Backtest iddiası (aynı 30 gün, aynı maliyet):**
- Mevcut kurgu (tüm sinyaller): **-0,143%/işlem** ≈ -22.168 TRY
- Önerilen kurgu: **+0,375%/işlem** ≈ +9.782 TRY
- İşlem hacmi 107/gün → 17/gün

Bu bir **backtest**tir, garanti değildir. Devreye alındıktan sonra ilk 1-2 hafta
gerçekleşen sonuç bu aralıkta mı diye izlenmelidir; ayrışırsa `allowed_modes`
boşaltılarak eski davranışa dönülür.

## 7. Açık kalan işler

- `llm_verdict` 1234/1254 işlemde `None` → **LLM kapısı fiilen hiç çalışmamış**.
  Çalışsa da §4'te ayırt edici sinyal bulunamadı; ama kapının neden hiç
  dolmadığı ayrıca incelenmeli.
- **Komisyon doğrulaması**: tüm hesap %0,325'e duyarlı. Gerçek komisyon maker
  (%0,075-0,1) ise tur maliyeti %0,2'ye iner ve sonuçlar iyileşir. Tek başına
  sistemi etkileyen en büyük dış değişken. `SCALPER_COMMISSION_PCT` /
  `COMMISSION_PCT` ortam değişkeni.
- `trend_devam` modunun **neden** edge taşıdığı incelenmeli (sinyal üretimi
  tarafı) — bu, edge'i güçlendirmenin ya da çoğaltmanın yolu.
