# Radar / Tarama Algoritmaları — Backtest & Replay Analizi

**Tarih:** 2026-11-10
**Veri:** Yerel Postgres `scalper` — 57.5M mum (1m/5m/15m/3m/1h/4h/1d),
331 sembol, 2026-06-27 → 2026-10-27
**Ölçüm tabanı:** `velocity_candidates` — 411.375 gerçekleşmiş, MFE/hedef/net
etiketi dolu aday
**Yöntem:** SQL ölçümü + gerçek 1m mumlarla dürüst replay (mum KAPANIŞINDAN
trailing/stop; mum-içi sıralama bilinmediği için muhafazakâr)
**Maliyet varsayımı:** %0,30 round-trip (BNB indirimli, 2×%0,15)

---

## 1. Mevcut durum: sistem yapısal olarak zarar ediyor

Mevcut çıkış modeliyle (sabit TP = bildirim hedefi, SL = %2):

| Metrik | Değer |
|---|---|
| Ölçülen aday | 411.375 |
| Hedefe değen | 148.733 (**%36,2**) |
| **Ortalama net** | **−0,465%** |
| **Medyan net** | **−0,700%** |

### Çıkış dağılımı

| Çıkış | n | % | ort net |
|---|---|---|---|
| TARGET_HIT | 148.729 | %36,2 | **+1,61%** |
| MAX_HORIZON_EXPIRE | 132.228 | %32,1 | **−1,04%** |
| STOPPED_OUT | 130.376 | %31,7 | **−2,25%** |

Beklenen değer: `0,362×1,61 + 0,321×(−1,04) + 0,317×(−2,25) = −0,46%`.
Tablo kendi içinde tutarlı — hesap hatası yok, sistem gerçekten kaybediyor.

### Hiçbir TP/SL kombinasyonu kurtarmıyor

Sabit TP + sabit SL taraması (411k aday, fee %0,30):

| TP | SL | isabet | beklenen net |
|---|---|---|---|
| 0,5% | 1,0% | 71,7% | −0,225% |
| 0,8% | 1,0% | 62,0% | −0,184% ← **en iyi** |
| 0,8% | 2,0% | 62,0% | −0,564% |
| 1,0% | 3,0% | 56,6% | −1,035% |
| 2,0% | 3,0% | 34,6% | −1,569% |

**Sebep — asimetri ters:** MFE dağılımı `+0,5%: %71,7 / +1%: %56,6 /
+2%: %34,6 / +3%: %17,7`. Kazanç küçük (0,5−0,30 = 0,20) ama kayıp büyük
(1,0+0,30 = 1,30). Bu yapıda hedefi büyütmek de küçültmek de kurtarmıyor.

---

## 2. Trailing denemesi — iyimser MFE tahmini YANILTICI

MFE tabanlı ilk simülasyon trailing'i çok parlak gösterdi (gap %0,3 → **+1,14%**).
Gerçek 1m mumlarla replay bunu **çürüttü**:

| Yöntem | Sonuç |
|---|---|
| MFE proxy (iyimser) | +1,14% |
| **Gerçek 1m mum replay** | **+0,007%** |

**Neden fark:** MFE "ulaşılan zirve"dir, "gerçekleşebilir kâr" değil. Mum içinde
tepe hızla oluşup aynı mumda geri geliyor; trailing devreye girdiğinde fiyat çoktan
düşmüş oluyor. `mum-içi sıralama` bilinmediği için sadece kapanışa bakan
muhafazakâr model, iyimser varsayımdan **1,1 puan** daha düşük çıktı.

Trailing parametre taraması (gerçek replay, 900 aday/varyant):

| gap | SL | ort net |
|---|---|---|
| 0,15% | 1,5% | +0,029% |
| 0,30% | 1,5% | +0,007% |
| 0,50% | 1,5% | +0,010% |
| 1,00% | 2,0% | −0,063% |
| 0,30% | 0,75% | +0,013% |

Hepsi sıfır civarı. **Trailing tek başına kenar üretmiyor.**

---

## 3. Gerçek kenar: volatilite filtresi (`atr_pct`)

Giriş kalitesi ayrıştırmasında tek güçlü ve monoton sinyal volatilite:

| atr_pct | n | ort MFE | MFE≥0,8% |
|---|---|---|---|
| 0–0,5 | 227.263 | 1,39 | %56,3 |
| 0,5–1 | 130.179 | 2,13 | %67,5 |
| 1–2 | 46.676 | 2,84 | %72,8 |
| 2–5 | 7.058 | 3,58 | %73,0 |
| ≥5 | 199 | 5,68 | %75,9 |

Gerçek replay ile doğrulama (gap %0,3, SL %1,5, fee %0,30):

| atr filtresi | n | ort net | medyan | kazanan |
|---|---|---|---|---|
| yok | 2.494 | +0,005% | −0,263% | %34,6 |
| ≥0,5 | 2.496 | +0,114% | −0,170% | %39,3 |
| **≥1,0** | 2.498 | **+0,344%** | −0,004% | **%49,7** |
| **≥1,5** | 2.495 | **+0,549%** | **+0,059%** | **%53,0** |

**Kritik nokta:** `atr≥1,5` ile medyan da pozitife geçiyor (+0,059%). Bu,
ortalamanın birkaç şanslı işlemden gelmediği anlamına gelir — dağılımın tamamı
kayıyor.

### Sağlamlık kontrolleri

**Parametre dayanıklılığı** (atr≥1,5):

| gap | SL | ort net | kazanan |
|---|---|---|---|
| 0,2% | 1,0% | +0,564% | %58,1 |
| 0,2% | 2,0% | **+0,643%** | %57,7 |
| 0,5% | 1,0% | +0,591% | %51,7 |
| 0,5% | 2,0% | +0,534% | %50,4 |

Tek bir şanslı ayar değil — tüm varyantlar +0,53…+0,64%.

**Maliyet duyarlılığı** (atr≥1,5, gap %0,3, SL %2):

| fee | ort net | medyan | kazanan |
|---|---|---|---|
| %0,30 | +0,524% | +0,165% | %57,1 |
| %0,45 | +0,371% | −0,029% | %48,7 |
| %0,60 | +0,208% | −0,224% | %39,4 |

**Maliyete çok duyarlı.** BNB indirimi / komisyon oranı bu strateji için
belirleyici — %0,60'ta kenar neredeyse yok oluyor.

**Zaman istikrarı** (haftalık, atr≥1,5):

| hafta | n | ort MFE | MFE≥0,8% |
|---|---|---|---|
| 2026-39 | 2.185 | 2,57 | %68,3 |
| 2026-40 | 5.903 | 3,12 | %73,3 |
| 2026-41 | 7.789 | 3,71 | %76,1 |
| 2026-42 | 2.330 | 3,46 | %74,3 |

Her hafta %68–76 bandında — **rejim bağımlı değil**, kenar tutarlı.

**Evren maliyeti:** `atr≥1,5` evrenin **%4,4'ü** (18.235 / 411.375). Yani
sinyalleri %95,6 oranında azaltıyor ama kalanlar kazandırıyor.

---

## 4. İkincil bulgu: `ret3_pct` U-şekilli

| ret3 (3 bar getiri) | n | ort MFE | MFE≥0,8% |
|---|---|---|---|
| < −2% | 8.361 | 2,75 | %74,3 |
| −2…−1% | 23.385 | 2,20 | %69,5 |
| **−1…0%** | 112.836 | 1,76 | %62,8 |
| **0…1%** | **207.101** | **1,65** | **%59,6** ← en kötü |
| 1…2% | 45.357 | 2,07 | %63,0 |
| > 2% | 14.335 | 3,11 | %68,6 |

**U-şekli:** hem dip alımı (< −2%) hem momentum (> +2%) iyi; **`0…1%` ölü bölge**
(en kalabalık grup, 207k aday) en kötü. Bu, "hafif yükselmiş ama henüz
ivmelenmemiş" adayların ayıklanması gerektiğini gösteriyor. Henüz replay ile
doğrulanmadı.

### Zayıf sinyal notu: `volume_ratio`

Volume ratio arttıkça MFE **düşüyor** (vr<0,5 → 1,84; vr≥5 → 1,07). Bu ters
görünüyor ama büyük olasılıkla tanım gereği: yüksek `volume_ratio` zaten
patlamış (geç kalınmış) adayları işaret ediyor. `velocity_score` ile birlikte
yeniden ele alınmalı — tek başına filtre olarak kullanılmamalı.

---

## 4b. Üretim kapısı üzerinden doğrulama (asıl kanıt)

`scripts/filt_replay.py` filtreyi SQL'de (`atr_pct >= X`) yeniden yazar — yani
kapının **kopyasını** test eder. Gerçek kanıt için `scripts/gate_replay.py`
adayı doğrudan üretim kapısından (`auto_paper._entry_context`) geçirir; sıralama,
fail-open ve kural muafiyeti dahil.

### Kapı gerçekten çalışıyor

`min_atr_pct=1.0` ile 400 adayın kapı denetimi:

```
kabul=55  engel=345   (%13,8 geçti)
  atr_below_min: 345
```

Engel nedeninin **tamamı** `atr_below_min` — başka bir kapı sızıntısı yok.

### 5 bağımsız seed toplamı (her biri 3.000 aday, gerçek 1m mum replay)

| min_atr | geçen (ort) | ort net | sd | medyan | kazanan |
|---|---|---|---|---|---|
| **0,0 (kapalı)** | 3.000 | +0,013% | 0,014 | −0,261% | %34,3 |
| 0,5 | 1.380 | +0,127% | 0,025 | −0,180% | %39,8 |
| **1,0** | 410 | **+0,346%** | **0,065** | −0,028% | %48,7 |
| **1,5** | 156 | **+0,580%** | 0,148 | **+0,078%** | **%53,0** |

Monoton artış, seed'den bağımsız (5 ayrı örneklem aynı yönü veriyor).

**Karar notu — 1,0 mı 1,5 mi?** Ortalama 1,5'te daha yüksek (+0,580 vs
+0,346) ve medyan orada pozitif. AMA standart sapma 1,5'te 2,3 kat büyük
(0,148 vs 0,065) çünkü örneklem 156'ya düşüyor. Yani 1,5'in üstünlüğü
**daha az güvenilir**. Başlangıç için **1,0** önerilir; 1,5 için en az
300–400 işlem birikmesini beklemek gerekir.

## 4c. `ret3_pct` ölü bölgesi — gerçek replay ile doğrulandı, FİLTRE EKLENMEDİ

Proxy MFE analizi (bölüm 4) U-şekli gösteriyordu. Yanıltıcı olabileceği için
gerçek 1m mum replay ile ölçüldü — **4 seed × 2.000 = 8.000 aday**:

| bölge | n | ort net | sd | medyan | kazanan |
|---|---|---|---|---|---|
| **< −2%** (dip) | 168 | **+0,550%** | 0,216 | **+0,220%** | **%59,9** |
| −2…−1% | 459 | +0,099% | 0,060 | −0,104% | %42,9 |
| −1…0% | 2.196 | −0,036% | 0,028 | −0,240% | %33,2 |
| **0…1% (ölü)** | **3.975** | **−0,064%** | 0,017 | −0,312% | **%29,7** |
| 1…2% | 882 | +0,058% | 0,041 | −0,301% | %34,3 |
| **> +2%** (momentum) | 296 | **+0,662%** | 0,104 | **+0,069%** | **%52,2** |

U-şekli **gerçek** — hem dip hem momentum iyi, `0…1%` en kalabalık (%50)
ve en kötü (%29,7 kazanan).

### Ama filtre olarak eklemeye değmez

| varyant | geçen | ort net | sd | kazanan |
|---|---|---|---|---|
| ATR≥1,0 | 261 | +0,247% | **0,056** | %47,5 |
| ATR≥1,0 + ret3 dışla (0…1) | 191 | +0,290% | **0,101** | %49,1 |
| ATR≥1,0 + sadece momentum (>2) | **32** | +0,622% | **0,317** | %51,3 |
| ATR≥1,0 + uçlar (dip veya momentum) | **59** | +0,596% | 0,239 | %55,7 |

**+0,043 puanlık kazanç, standart sapmanın 2 kat artmasıyla geliyor**
(0,056 → 0,101) ve örneklem 261 → 191'e düşüyor. Uç filtrelerin görünen
üstünlüğü (+0,35 puan) yalnız 32–59 işleme dayanıyor — sd 0,317 ile
istatistiksel olarak anlamsız.

**Karar: `ret3` kapısı EKLENMEDİ.** ATR filtresi tek başına daha güvenilir.
Bu karar `tests/test_ret3_finding.py` ile kilitlendi.

## 5. Öneri (öncelik sırası)

1. **`atr_pct ≥ 1,0` (muhafazakâr) / `≥ 1,5` (agresif) giriş filtresi ekle.**
   En yüksek etkili, en iyi doğrulanmış tek değişiklik. Ölçülen etki:
   −0,46% → **+0,34…+0,55%** ort net, kazanan oranı %34 → **%50–53**.
   Sinyal hacmi %95 azalır — bu bir özellik, hata değil.

2. **Trailing'i tek başına "çözüm" sayma.** Gerçek replay kenar üretmedi
   (+0,007%). Mevcut sabit TP modeli de zarar ediyor; ikisi de ancak
   volatilite filtresiyle birlikte anlamlı.

3. **Komisyon oranını sabitle ve izle.** Kenar %0,30 fee'ye bağlı.
   %0,60'a çıkarsa strateji durdurulmalı (eşik: ort net < +0,1%).

4. **`ret3_pct` ölü bölgesini (0…1%) araştır.** En kalabalık ve en kötü grup.
   Filtre veya ayrı davranış gerekebilir.

5. **Canlı doğrulama:** filtreyi paper modda A/B olarak çalıştır, en az 200
   işlem biriktir, sonra `velocity_candidates.net_pct` ile karşılaştır.

---

## 6. Araçlar

| Betik | Ne yapar |
|---|---|
| `scripts/radar_14d_eval.py` | 8 radar ailesini 14 günlük 1m mumla karşılaştırır |
| `scripts/rsi_filter_search.py` | RSI filtre parametre araması |
| `scripts/rsi_tf_geometry.py` | RSI zaman dilimi geometrisi |
| `scripts/trail_replay.py` | Gerçek 1m mumla trailing/SL dürüst replay |
| `scripts/filt_replay.py` | `atr_pct` filtresi ile replay (filtrenin SQL kopyası) |
| `scripts/gate_replay.py` | **Asıl kanıt:** adayı ÜRETİM kapısından geçirip replay eder |
| `scripts/ret3_replay.py` | `ret3_pct` bölge analizi (gerçek 1m mum) |

Çalıştırma:
```bash
cd backend
./.venv/Scripts/python.exe scripts/gate_replay.py --limit 3000 --gap 0.3 --sl 2.0
```

---

## 7. Sınırlar (dürüstlük notu)

- **Mum-içi sıralama bilinmiyor.** 1m mumun high/low sırası bilinmediği için
  hem TP hem SL aynı mumda tetiklenebiliyorsa **SL önce** varsayıldı
  (muhafazakâr). Gerçek sonuç biraz daha iyi olabilir, daha kötü olamaz.
- **Slippage modeli yok.** Replay sadece komisyon içeriyor. Gerçek dolumda
  ek kayma olur — kenar bir miktar erir.
- **`atr_pct` replay'de sızıntı riski.** Filtre giriş ANINDAKİ `atr_pct`
  değerini kullanıyor (geleceğe bakmıyor), ama bu değerin canlıda ölçüldüğü
  an ile replay'deki an birebir aynı olmayabilir. Canlı A/B ile doğrulanmalı.
- **Tek borsa, tek dönem.** 4 ay, Binance TR. Farklı rejimde (ayı piyasası)
  test edilmedi.
- **Örneklem:** replay 900–2.500 işlem bandında. Daha büyük örneklem daha
  kesin olurdu ama sonuçlar örneklem büyüdükçe **kararlı** kaldı.
