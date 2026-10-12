# Fizibilite Planı — Order-Book / Mikro-Yapı Limit Stratejisi (2026-10-12)

## Kapsam
Öneri: **gerçek order-book derinliğinden türetilen, likit seviyelerde dolan bir limit (maker)
stratejisi.** Bu belge, bunun teknik olarak yapılabilir olup olmadığını ölçülmüş kanıtlarla
değerlendirir. Kaynak dokümanlar: `developers.binance.com` (Spot REST + WS), `binance-public-data`,
canlı API sorguları, mevcut kod tabanı ve 6 turluk araştırma serisi.

---

## 1) Belirleyici kısıt: SPOT'ta tarihsel order-book YOK

Fizibilite için her şeyden önce şu soruyu yanıtladım: *"L2 derinliğini geriye dönük çekip
test edebilir miyim?"* Cevap **hayır**. Üç bağımsız kanıt:

| Kaynak | Bulgu |
|---|---|
| Resmi Spot REST dokümanı (`/api/v3/depth`) | **Data Source: Memory** → yalnız anlık görüntü, tarih parametresi YOK |
| `data.binance.vision` SPOT arşivi (canlı test) | `aggTrades` ✅, `trades` ✅, `klines` ✅ — **`depth` ✗, `bookTicker` ✗, `bookDepth` ✗** (HTTPError) |
| Binance TR | Public data arşivi **hiç yok** (`data.binance.tr` DNS'te yok). TR L2 yalnız canlı WS'te var |

**Sonuç:** Önerilen "order-book derinliği tabanlı limit stratejisi" mevcut veriyle **backtest
EDİLEMEZ** — ne SPOT'ta ne TR'de geçmiş L2 var. Bu, projenin kuralını ihlal eder: doğrulanmamış
sinyali canlıya alma (6 turun tamamı bu kural sayesinde negatif kanıt üretti).

> **Tek istisna:** Binance **USDⓈ-M Futures** arşivinde `bookTicker` ve `bookDepth` (günlük)
> dump'ları VAR (binance-public-data doğruladı). Ama terminalimiz SPOT TRY'dır; futures L2
> ile TRY spot paper arasında venue/maliyet farkı yüksek.

---

## 2) Geriye-dönük test EDİLEBİLİR tek mikro-yapı sinyali ölçüldü — yetersiz

Spot'ta ölçülebilir tek mikro-yapı kanalı **trade tape (aggTrades) order-flow**'dur; 730 güne
kadar çekilebilir. Ölçtüm (BTCUSDT, 5 dk, son 500 bar):

| Metrik | Değer |
|---|---|
| korelasyon(5dk taker imbalance → sonraki 5dk getiri) | **+0.03** |
| imb ≥ +1σ sinyal, ortalama ileri getiri | **+0.005%** / işlem |
| 5dk getiri standart sapması (gürültü) | 0.074% |
| **Round-trip MALİYET (taker)** | **~0.41%** (komisyon %0.30 + spread/2) |

**Sinyalin brüt edge'i (+0.005%), maliyetin (0.41%) ~1/80'i.** Tape imbalance, tek başına
ölçülebilir bir avantaj değil. (Not: 5dk turunun `tbr` sonucuyla tutarlı — order-flow kanalı
`NO_CHANNEL_EDGE`.)

---

## 3) Maliyet tabanı — gerçek ölçüm (önerinin neden zor olduğu)

Canlı bookTicker + kayıtlı WS örneklerinden **gerçek spread** (top-20 likit TRY):

| Segment | Median spread |
|---|---|
| BTCTRY / PEPETRY (en likit) | ~0.00–0.01% |
| Top-20 likit TRY ortalaması | **0.13%** |
| Orta likidite (MAGIC/CYBER/RSR) | 0.17–0.52% |

Ücret yapısı (resmi): Binance Global SPOT VIP0 **maker = taker = %0.10** (BNB ile %0.075);
maker indirimi VIP1+ başlar. Binance TR: **%0.15/bacak** (yapılandırılmış `COMMISSION_PCT`).

| Yol | Round-trip maliyet (top-20 likit) |
|---|---|
| Taker (TR %0.15×2 + spread) | ~0.41% |
| Maker (Global %0.10×2 − spread kazancı) | ~0.07% brüt tasarruf — **AMA** |
| Maker **gerçek dolgu** (5. turda kanıtlandı) | **adverse selection** ile edge YOK olur (limit dolan işlemler kötü işlemlerdir) |

**Kritik:** Maker komisyonu "bedava" değil. 5. turda `vol_r_high` sinyali taker-girişte
maker-maliyetle +0.28% görünürken **gerçek limit dolguda −0.28%** çıktı. Aynı tuzak burada da
geçerli: gerçek L2 olsa bile, likit seviyeye konan limitin doldUğu an olumsuz seçimdir.

---

## 4) Sermaye / büyüklük fizibilitesi

Mevcut paper bakiye 5.000 TL, pozisyon = serbest bakiyenin %10'u (~500 TL). Bu ölçekte:
- Likit TRY tahtasında 500 TL'lik limit emir spread'i etkilemez (depth med. ~1.9M TRY). **İyi.**
- Ama maliyet tabanı bakiyeden bağımsız: %0.1–0.4 round-trip. Küçük bakiyede oransal maliyet
  aynı; avantaj yalnız sinyal edge'i maliyeti aşarsa doğar — burada aşmıyor.

---

## 5) İki gerçekçi yol ve gereken yatırım

### Yol A — İleriye dönük L2 toplama (kendi verimiz) · ÖNERİLEN
Spot tarihsel L2 olmadığı için, kendi verimizi **bugünden** toplayıp N hafta sonra test etmek:
- **Ne gerekir:** aktif aday semboller için `@depth20@100ms` WS aboneliği + snapshot+diff
  book reconstruction (doküman: `binance-spot-api-docs/web-socket-streams.md`, kanıtlanmış
  prosedür) → kendi DB'mize yaz. Ölçek: sembol başına ~10–40 MB/gün.
- **Maliyet:** mevcut `microflow.py` altyapısı **zaten** tek-sembol depth snapshot alıyor;
  genişletmek orta iş (~1–2 hafta geliştirme), ek ücret yok (public WS).
- **Süre:** anlamlı backtest için **en az 4–8 hafta** veri birikmeli. Hiçbir sonuç bugün alınamaz.
- **Risk:** 4–8 hafta sonunda sinyal yine maliyetin altında çıkabilir (6 turun örüntüsü bunu
  işaret ediyor).

### Yol B — Futures L2 üzerinde araştırma (hazır arşiv) · HIZLI KANIT
- Futures arşivinde `bookTicker` + `bookDepth` **hazır** → derhal test edilebilir.
- **AMA:** venue USDⓈ-M, terminalimiz SPOT TRY. Futures order-flow'un TRY spot'a taşınabilirliği
  belirsiz; futures kaldıraç/funding ekstra risk. Yalnız **araştırma/kanıt** için uygun, üretim
  için değil.
- **Maliyet:** ~1–2 gün veri indirme + analiz. Düşük.

---

## 6) Karar ve öneri

| Soru | Cevap |
|---|---|
| Önerilen strateji bugün yapılabilir mi? | **HAYIR** — spot/TR'de tarihsel L2 yok, backtest edilemez |
| Tek ölçülebilir mikro-yapı sinyali (tape flow) yeterli mi? | **HAYIR** — edge maliyetin ~1/80'i |
| Maker maliyeti avantaj sağlar mı? | **HAYIR** — adverse selection edge'i siliyor (5. turda kanıtlı) |
| Yatırım yapmaya değer bir yol var mı? | **Şartlı evet:** Yol A (ileriye dönük L2 toplama) |

**Önerim (sıralı):**
1. **Şimdi (düşük maliyet, hızlı kanıt):** Yol B — Futures `bookTicker/bookDepth` arşivinden
   tek bir sembolde (BTCUSDT) L2-imbalance → fiyat edge'ini ölç. Eğer orada bile edge ≈ 0 ise,
   Yol A'nın 4–8 haftalık yatırımı **rantable değildir**; proje kapanır.
2. **Şartlı:** Yol B pozitif VE taşınabilir çıkarsa → Yol A (TR L2 toplama) başlat, 4–8 hafta
   veri biriktir, sonra walk-forward testi.
3. Her iki durumda da canlıya alma kapısı: **net EV > 0, t > 1.65, 3-fold kararlı, sembol
   yoğunlaşması < %10** (mevcut araştırma standartları).

**Beklenti (dürüst):** 6 turun tümünde ham bilgi içeriği ~%0.1–0.3 brüt çıktı, maliyet tabanı
~%0.3–0.4. L2 derinliğinin bu tabloyu kökten değiştirmesi için, order-book'un tape'te
görünmeyen **bir bilgi taşıması** gerekir (ör. gizli/iceberg duvarları, kısa ömürlü likidite
boşlukları). Bu mümkün ama **varsayılamaz** — ölçülmeli. Bu yüzden sıralama "önce ucuz
kanıt (Yol B), sonra pahalı yatırım (Yol A)" şeklindedir.

---

## 7) Yapılmış testlerin özeti (bu belge için)
- `/api/v3/depth` veri kaynağı: resmi dokümandan teyit (Memory).
- `data.binance.vision` SPOT günlük dump: depth/bookTicker/bookDepth **yok** (HTTPError);
  aggTrades/trades/klines **var** (200 OK).
- Futures arşivi: bookTicker/bookDepth **var** (binance-public-data).
- Tape imbalance öngörü: korelasyon +0.03, edge +0.005%/işlem (BTCUSDT 5dk).
- Gerçek spread: top-20 likit TRY median %0.13 (canlı bookTicker).
- Ücret: Global SPOT VIP0 maker=taker %0.10; TR %0.15/bacak.
- Maker adverse-selection: 5. tur commit `f414581` (`docs/MALIYET_DUYARLILIK_2026-10-12.md`).

## Sonraki adım (onay gerekir)
Yol B'yi (Futures L2 hızlı kanıt) uygulayayım mı? Tahmini 1–2 gün, sıfır ücret, üretime
dokunmaz. Sonucu bu plana ekleyip Yol A'nın yatırıma değer olup olmadığını veriyle karara bağlarız.

---

## 8) YOL B UYGULANDI — beklenmedik örneklem tuzağı yakalandı

Planın "önce ucuz kanıt" önerisini fiilen koştum (Futures `bookDepth` arşivi, BTCUSDT).

**Yöntem:** `bookDepth` (yüzde bantlı bid/ask derinliği, ~1 dk örneklem) → L2 imbalance
`(bid_depth(-1%) − ask_depth(+1%)) / toplam` → sonraki 15 dk getiri ile korelasyon.

**Sonuçlar (gün gün):**
| Gün | n | korelasyon(imbalance → fwd 15dk) |
|---|---|---|
| 2026-10-07 | 339 | **−0.433** |
| 2026-10-09 | 2359 | +0.032 |
| 2026-10-06 | 2850 | +0.137 |
| 2026-10-05 | 2850 | +0.204 |
| 2026-10-04 | 2850 | +0.120 |
| 2026-10-03 | 2850 | +0.091 |
| 2026-10-02 | 2850 | −0.183 |
| **TOPLAM** | **16948** | **−0.033** |

**Kritik ders:** Tek başına ilk baktığım gün (10-07, n=339) **−0.43** korelasyon gösterdi ve
neredeyse "güçlü L2 edge bulundu" diye raporlanıyordu. 7 güne çıkınca işaret **gün gün
değişiyor** ve toplam korelasyon **−0.03**'e (gürültü seviyesi) çöküyor. En yüksek/düşük
imbalance kovalarının farkı yalnız **0.017%** — futures taker maliyetinin (~0.05% round-trip)
**altında**.

**Sonuç:** L2 imbalance, tek günlük örneklemde "muhteşem" görünüp haftalık ölçekte yok olan
klasik bir istatistiksel yanılsama. **Futures L2'de de gerçek bir edge bulunamadı** (en azından
bu basit imbalance formunda, BTCUSDT'de). Bu, Yol A'nın (4–8 hafta TR L2 toplama) yatırıma
değer olma olasılığını **belirgin biçimde düşürür** — çünkü aynı bilgi sınıfı (L2 derinlik
asimetrisi), hazır ve bol veriyle bile sinyal üretmedi.

> Not: Bu yalnız BTCUSDT + tek imbalance formülü + 7 gündür. Nihai karar için daha fazla
> gün/sembol/formül gerekir; ancak "ucuz kanıt" aşamasının amacı buydu ve sonuç **negatif**.

## GÜNCEL KARAR (Yol B sonrası)
| Soru | Cevap |
|---|---|
| L2 derinliği (hazır veri, futures) edge üretiyor mu? | **HAYIR** — 7 günde korelasyon −0.03, gün gün kararsız |
| Yol A (4–8 hafta TR L2 toplama) yatırıma değer mi? | **Öncelik DÜŞTÜ** — aynı bilgi sınıfı bol veriyle sinyal vermedi |
| Önerilen sonraki hamle | **Bu sinyal ailesini kapatmak.** Farklı varlık/venue veya farklı bilgi sınıfı (haber/duygu, cross-venue lead-lag) araştırılmalı — spekülatif, ayrı karar |

**Nihai önerim:** Order-book/mikro-yapı yolu, mevcut kanıtlarla **kârlı edge üretmiyor**.
Projeyi bu eksende kapatmayı ve kaynakları (varsa) farklı bir hipotez sınıfına yöneltmeyi öneririm.
Karar senin; istersen Yol A'yı yine de başlatabiliriz ama beklenti artık düşük ve gerekçesi zayıf.

