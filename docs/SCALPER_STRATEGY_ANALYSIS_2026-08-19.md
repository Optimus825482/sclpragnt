# BB_MFI_MEAN_REVERSION Strateji Analizi

**Tarih:** 2026-08-19  
**Kapsam:** Kod inceleme + Replay test hata analizi + 72 saat backtest karşılaştırması  
**Sonuç:** Paper-trading only, yatırım tavsiyesi değildir

---

## 1. Yönetici Özeti

Aktif strateji **BB_MFI_MEAN_REVERSION v3 ("Flawless Victory")** 18 Binance TR spot sembolünde, ~3.1 günlük 5 dakikalık mum verisi üzerinde test edildi. **Üç senaryoda da toplam PnL negatif** — strateji mevcut haliyle kârlı değil. En büyük sorun: %8.88 stop-loss / %2.32 take-profit asimetrisi (3.83:1 aleyhte risk-ödül).

| Senaryo | Stop | TP | İşlem | Kazanç | Net PnL (TRY) | WR |
|---|---|---|---|---|---|---|
| **A_LIVE** (mevcut) | %8.88 | %2.32 | 114 | 53 | **-395.80** | %46.5 |
| B_BALANCED | %3.50 | %3.50 | 121 | 56 | -478.71 | %46.3 |
| C_TIGHT | %2.50 | %2.50 | 125 | 58 | -448.83 | %46.4 |

---

## 2. Backtest: Sembol Bazında Detay (Senaryo A_LIVE)

| Sembol | İşlem | Kazanç | PnL (TRY) | WR | PF | Ana Kapanış Nedeni |
|---|---|---|---|---|---|---|
| SOLTRY | 5 | 4 | **+9.15** | %80 | 5.29 | bb_mfi_sell |
| LINKTRY | 7 | 5 | **+8.38** | %71.4 | 1.93 | bb_mfi_sell, take_profit |
| ARBTRY | 6 | 3 | **+6.80** | %50 | 3.54 | bb_mfi_sell |
| BTCTRY | 9 | 4 | -4.81 | %44.4 | 1.77 | bb_mfi_sell |
| XRPTRY | 4 | 2 | -7.32 | %50 | 0.86 | bb_mfi_sell |
| DOGETRY | 6 | 3 | -7.91 | %50 | 1.40 | bb_mfi_sell |
| ETHTRY | 7 | 4 | -10.28 | %57.1 | 1.04 | bb_mfi_sell |
| INJTRY | 4 | 3 | -10.68 | %75 | 0.78 | bb_mfi_sell |
| BNBTRY | 4 | 0 | -22.18 | %0 | — | bb_mfi_sell |
| OPTRY | 9 | 5 | -20.31 | %55.6 | 0.77 | bb_mfi_sell |
| APTTRY | 6 | 3 | -23.18 | %50 | 0.70 | bb_mfi_sell |
| LTCTRY | 9 | 2 | -27.73 | %22.2 | 0.19 | bb_mfi_sell |
| AVAXTRY | 5 | 2 | -31.28 | %40 | 0.39 | bb_mfi_sell |
| DOTTRY | 7 | 2 | -33.64 | %28.6 | 0.45 | bb_mfi_sell |
| ADATRY | 6 | 2 | -35.18 | %33.3 | 0.35 | bb_mfi_sell |
| NEARTRY | 8 | 4 | -39.78 | %50 | 0.47 | bb_mfi_sell |
| SUITRY | 5 | 2 | -47.13 | %40 | 0.18 | bb_mfi_sell |
| **WLDTRY** | 7 | 3 | **-98.73** | %42.9 | 0.20 | bb_mfi_sell, stop_loss |

**Sadece 3/18 sembol pozitif PnL üretti.** WLDTRY tek başına tüm sistemin zararının %25'ini oluşturuyor.

---

## 3. Replay / Backtest Kod İncelemesi — Bulunan Hatalar

### 3.1 `_strategy_tf` mapping'de eksik stratejiler (DÜŞÜK ETKİ)
**Dosya:** `backend/app/analyzer.py:468-483`

`MOMENTUM_COST_AWARE` ve `MOMENTUM_SCORED` stratejileri `_strategy_tf` mapping'inde yok. Şu anda devre dışı oldukları için canlıyı etkilemiyor, ama `_strategy_tf` mapping'i kullanan diğer kod yolları (pozisyon kapanış cooldown, vs.) için ileride sorun çıkarabilir.

### 3.2 BB-MFI pozisyonları ATR trailing stop'u hiç kullanmıyor (ORTA ETKİ)
**Dosya:** `backend/app/analyzer.py:524`, `analyzer.py:555`

```python
# Satır 524: BB-MFI için erken return
if pos.get("strategy") == "BB_MFI_MEAN_REVERSION":
    # ... Pine sell sinyali kontrolü ...
    return None  # ← Buradan dönüyor, 555. satırdaki ATR trailing'e ulaşılamıyor
```

BB-MFI pozisyonları sadece Pine sell sinyali veya sabit stop/TP ile kapanıyor. Trend devam ederken sinyal üretmeyen durumlarda pozisyon açık kalıyor ve BB üst bandına değmeden geri dönebiliyor.

### 3.3 Entry Volume Ratio filtresi kapalı (YÜKSEK ETKİ)
**Dosya:** `backend/app/config.py:67`

```python
BB_MFI_ENTRY_VOLUME_RATIO_MIN = 0.0  # ← Her hacim kabul ediliyor
```

Bu filtre "ölü kedi sıçraması" (dead cat bounce) riskini azaltmak için tasarlanmıştı. Kapalı olması, düşük hacimli fake dip'lerde de giriş yapılmasına neden oluyor.

### 3.4 Dip Confirmation ve MFI Reversal filtreleri kapalı (YÜKSEK ETKİ)
**Dosya:** `backend/app/config.py:68-71`

```python
BB_MFI_DIP_CONFIRMATION_ENABLED = False         # Kapalı
BB_MFI_ENTRY_MFI_REVERSAL_ENABLED = False       # Kapalı
```

Bu iki filtre, mean-reversion stratejisinin "bıçak düşerken yakalama" riskini azaltır. İkisi de devre dışı.

---

## 4. Senaryo Karşılaştırması Analizi

### Stop-loss azaldıkça ne oluyor?

| Senaryo | Stop | TP | İşlem | Kapanış Dağılımı |
|---|---|---|---|---|
| A_LIVE %8.88 | 114 | Sadece WLDTRY'de 1 stop_loss |
| B_BALANCED %3.50 | 121 | 7 stop_loss tetiklenmesi |
| C_TIGHT %2.50 | 125 | 13 stop_loss tetiklenmesi |

Stop daraldıkça daha fazla stop-loss kapanışı oluyor, ama işlem sayısı da artıyor. **Hiçbir senaryo kârlı değil.** Temel sorun stop/TP parametresinden çok **giriş sinyalinin kalitesinde**.

---

## 5. Önerilen Aksiyonlar

### Öncelik 1 — Hemen Yapılmalı (düşük risk, yüksek etki)
1. **Volume Ratio filtresini aktif et:** `BB_MFI_ENTRY_VOLUME_RATIO_MIN = 0.8`
2. **Dip Confirmation'ı aktif et:** `BB_MFI_DIP_CONFIRMATION_ENABLED = true`
3. **MFI Reversal'ı aktif et:** `BB_MFI_ENTRY_MFI_REVERSAL_ENABLED = true`, `delta = 0.5`

### Öncelik 2 — Parametre Optimizasyonu
4. **Stop-loss'u %4 civarına çek, TP'yi %3 civarına:** Mevcut %8.88 stop, %2.32 TP ile matematiksel olarak kârlı olmak için %79+ win rate gerekir — mean-reversion'da bu imkansıza yakın.
5. **ADX bear pressure eşiklerini düşür:** `BB_MFI_BEAR_PRESSURE_MIN_ADX = 35` (50'den), böylece daha fazla düşüş trendi filtrelenir.

### Öncelik 3 — Yapısal İyileştirmeler
6. **BB-MFI'ye ATR trailing stop desteği ekle:** `_manage_open_position` içinde BB-MFI erken return kaldırılıp ATR trailing stop çalıştırılmalı.
7. **Spread filtresi ekle:** BB-MFI girişinde `spread_pct < 0.15` kontrolü yok — likidite filtresinden bağımsız olarak bu strateji seviyesinde de kontrol edilmeli.
8. **WLDTRY'yi sembol listesinden çıkar:** Tek başına 3 işlemde -98 TRY zarar — orantısız risk.
9. **Per-symbol lot sizing:** Volatiliteye göre pozisyon büyüklüğü ayarlanmalı.

### Öncelik 4 — Backtest İyileştirmesi
10. **Backtest spread varsayımını %0.2 yap:** `BACKTEST_ASSUMED_SPREAD_PCT = 0.002` — şu an %0.1, canlıda %0.3'e kadar kabul ediliyor. Backtest sonuçları gerçekte olduğundan iyi görünüyor.

---

## 6. Sonuç

BB_MFI_MEAN_REVERSION v3 algoritmasının **mimarisi sağlam** — çok katmanlı koruma, bear pressure filtresi, piramitleme mantığı iyi düşünülmüş. Ancak:

1. **Parametreler optimize edilmemiş** — 3 temel güvenlik filtresi (volume, dip, MFI reversal) devre dışı.
2. **Stop/TP asimetrisi sürdürülemez** — %8.88 stop / %2.32 TP ile hiçbir mean-reversion stratejisi uzun vadede kârlı olamaz.
3. **72 saatlik backtestte -395 TRY net zarar** — 18 sembol, 114 işlem, %46.5 win rate.

Önerilen filtreler aktif edilip stop/TP yeniden dengelendikten sonra sistemin tekrar backtest edilmesi gerekir. Bu haliyle **canlı paper-trading'de kullanılması önerilmez** — önce filtreler eklenmeli ve en az 14 günlük out-of-sample walk-forward testinden geçmelidir.

---

*Analiz tarihi: 2026-08-19 | Backtest penceresi: ~3.1 gün (900 mum × 5dk) | 18 Binance TR spot sembolü*
