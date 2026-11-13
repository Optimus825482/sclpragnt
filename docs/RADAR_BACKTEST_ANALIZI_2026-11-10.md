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
| `work/trail_replay.py` | **Yeni:** gerçek 1m mumla trailing/SL dürüst replay |
| `work/filt_replay.py` | **Yeni:** `atr_pct` filtresi ile filtreli replay |

Çalıştırma: `cd backend && ./.venv/Scripts/python.exe work/trail_replay.py --limit 2000 --gap 0.3 --sl 1.5`

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
