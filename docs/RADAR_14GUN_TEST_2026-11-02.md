# Sclpragnt Radar Stratejileri — 14 / 50 Günlük Test

**Tarih:** 2026-11-02
**Veri:** `scalper` DB, 1m mumlar, 100 kripto sembolü (TRY)
**Kapsam:** 14 gün (442.800 bar) ve 50 gün (21.868.444 bar — MEVCUT TÜM VERİ)
**Maliyet:** %0.15 round-trip (BNB indirimli)

> **Not:** 60 gün istendi; DB'de kripto 1m verisi **50 gün** (2026-09-03 → 2026-10-22).
> Eksik 10 gün ayrıca çekilmedi.

---

## KRİTİK: 14 günde kazanan 50 günde çöktü

| strateji | 14 GÜN (takipçi) | 50 GÜN (takipçi) | değişim |
|:---------|----------------:|----------------:|--------:|
| `rsi_oversold` | PF **1.21**, +0.076% | PF **1.00**, +0.000% | **-0.076** |
| `rising_kdj_dip` | PF **1.04**, +0.018% | PF 0.90, -0.050% | **-0.068** |
| *rastgele* | PF 0.95, -0.022% | PF 0.86, -0.067% | -0.045 |

**14 günde "kârlı" görünen iki strateji, 50 günde kâra geçemedi.**

`rsi_oversold` tam olarak sıfıra oturdu (PF 1.00, +0.000%). `rising_kdj_dip`
kayıp bölgesine döndü (PF 0.90).

---

## 50 gün tam tablo (takipçi çıkış)

| strateji | n | WR | PF | ort% | t-stat | pozCoin |
|:---------|--:|---:|---:|-----:|-------:|--------:|
| `rsi_oversold_trail` | 51.963 | 45.4% | **1.00** | +0.000 | +0.02 | 51/100 |
| `rising_kdj_dip_trail` | 200.211 | 43.2% | 0.90 | -0.050 | -19.59 | 28/100 |
| *rastgele* | 151.500 | 41.8% | 0.86 | -0.067 | -22.91 | 14/100 |
| `momentum_24h_trail` | 734.276 | 39.8% | 0.78 | -0.121 | -86.22 | 11/100 |
| `rising_supertrend_trail` | 156.708 | 39.1% | 0.77 | -0.141 | -44.03 | 8/100 |
| `velocity_5m_trail` | 33.570 | 35.9% | 0.70 | -0.191 | -27.40 | 5/100 |
| `velocity_15m_trail` | 60.126 | 42.0% | 0.69 | -0.238 | -39.00 | 6/100 |
| `pulse_trail` | 14.759 | 33.2% | 0.62 | -0.249 | -24.04 | 6/100 |

Yalnızca `rsi_oversold` sıfırda; diğer yedisi negatif. Hiçbiri anlamlı pozitif değil.

---

## Bulgular

### 1. 14 gün güvenilmez — 50 gün çürüttü
14 günde `rsi_oversold` PF 1.21 ve 59/100 coin pozitifti. 50 günde PF 1.00,
51/100. **Kazanç dönem-spesifikti.**

Bu, globall'da yaşananın aynısı: `squeeze_breakout` kısa pencerede PF 1.82
görünüp 60 günde PF 0.70'e düşmüştü.

### 2. Takipçi çıkış hâlâ değerli — ama tek başına yetmiyor
50 günde de takipçi her stratejide sabit TP/SL'den iyi:
`rsi_oversold` -0.077 → +0.000 (+0.077), `rising_kdj_dip` -0.112 → -0.050 (+0.062).
Ama bu iyileşme maliyeti karşılamaya yetmiyor — sadece sıfıra yaklaştırıyor.

### 3. Pozitif coin sayısı da çöktü
`rsi_oversold`: 59/100 → 51/100. `rising_kdj_dip`: 55/100 → **28/100**.
İkincisindeki düşüş, 14 günlük sonucun ne kadar kırılgan olduğunu gösteriyor.

### 4. velocity_5m ve pulse iki dönemde de en kötü
PF 0.70 ve 0.62. "En hızlı sıçrayanı al" mantığı iki dönemde de çalışmıyor.

---

## Sonuç

**Radar stratejileri 50 günde kârlı değil.** En iyisi tam sıfırda (PF 1.00).
14 günlük parlak sonuç tek dönemin tesadüfüydü.

Takipçi çıkış gerçek bir iyileşme (+0.06–0.08 puan) ama bu, stratejilerin
negatif edge'ini **sıfıra** taşıyor, pozitife değil.

---

## Sınırlar

- **50 gün, tek dönem.** Farklı rejimde farklı sonuç verebilir
- Takipçi parametreleri globall'dan alındı, bu veri için optimize edilmedi
- Vekil kurallar gerçek radarın basitleştirilmiş hali (Bollinger/ATR/MFI/RSI
  filtreleri yok)
- Gap modeli yok

---

## Öneri

1. **14 günlük sonuçlara göre karar vermeyin.** `rsi_oversold` PF 1.21
   görünüyordu; 50 günde 1.00. Kısa pencere yanıltıcı.
2. **Takipçi çıkışı yine de bağlayın.** İki dönemde de iyileştiriyor
   (+0.05–0.12), hiçbir stratejiye zarar vermiyor. Ama bunu "kâr" diye
   sunmayın — kaybı azaltıyor, kâra çevirmiyor.
3. **Radar giriş sinyalleri 1 dakikalıkta maliyeti karşılamıyor.** Globall'da
   aynı sonuca 4 kez varıldı (8 strateji, 60 gün, vectorbt). Kâr için farklı
   zaman dilimi (günlük TSMOM Sharpe 1.01) veya farklı edge kaynağı gerekiyor.

---

## EK (2026-11-10): betiklerin akıbeti ve bugünkü doğrulama

### Betik temizliği

| Betik | Durum | Neden |
|---|---|---|
| `radar_14d_eval.py` | **TUTULDU** → `backend/scripts/radar_family_eval.py` | Çalışıyor, `--days`/`--symbols` parametreli, 16 strateji × TRAIN/TEST |
| `rsi_filter_search.py` | **SİLİNDİ** | Çöküyor: `days=14` sabit kodlu, `----` veri 17 gün geride → `sembol: 0`, `TypeError` |
| `rsi_tf_geometry.py` | **SİLİNDİ** | Çökmüyor ama TÜM hücreler boş → "HİÇBİR KOMBİNASYON GEÇMEDİ" **sahte sonuç**. Yanlış negatif üretmek, hiç ölçmemekten kötü |

**Kök neden:** her ikisi de `days = 14` sabit kodluyor ve "bugün"e göre geriye
bakıyor. DB'deki 1m veri **2026-10-27**'de bitiyor; 2026-11-14'te çalıştırıldığında
14 günlük pencere tamamen boş kalıyor. `radar_14d_eval.py` bu tuzağa düşmüyor
çünkü `--days` parametresi var; 40 gün verildiğinde çalışıyor.

### Bugünkü bağımsız ölçüm (`backend/scripts/radar_family_eval.py`, 40 gün/40 sembol)

| strateji | n | WR | PF | ort% | t-stat |
|---|---:|---:|---:|---:|---:|
| rising_kdj_dip_trail | 33.237 | 41,6% | 0,85 | −0,073 | −11,53 |
| rsi_oversold_trail | 9.270 | 41,7% | 0,83 | −0,077 | −6,52 |
| **rastgele (trail)** | 26.160 | 40,4% | 0,83 | −0,082 | −11,62 |
| velocity_5m | 5.270 | 19,1% | **0,28** | −0,240 | −31,94 |
| pulse | 2.712 | 14,3% | **0,19** | −0,267 | −28,97 |

**Bu dokümanın 2026-11-02 bulguları bağımsız olarak DOĞRULANDI:**
- `velocity_5m`/`pulse` hâlâ en kötü (PF 0,28 / 0,19 — bu doküman 0,70/0,62 demişti, bugün daha da kötü).
- Hiçbir strateji PF > 1,0 değil; en iyisi 0,85 (rastgele 0,83). **Rastgelelikten ayırt edilemiyor.**
- Tüm t-stat'lar anlamlı negatif.

### Bunun bugünkü ayar karalarına etkisi

`min_atr_pct`/`max_sl_tp_ratio`/`max_target_pct` ölçümlerinde **filtresiz evren
~0** çıkıyordu; bu doküman ise **PF 0,83** (yani −0,082%) diyor. Fark, farklı
çıkış modellerinden (burada sabit TP/SL + trailing; bizde gap=0,3% trailing).
İkisi de aynı sonuca çıkıyor: **filtresiz sistem kaybeder.** ATR filtresi bunu
+0,32'ye taşıyor — ama bu dokümanın uyarısı geçerli: 14 günlük pencereler
yanıltıcı, ve benim ölçümüm de 2 seed ile sınırlı. Canlı doğrulama şart.
