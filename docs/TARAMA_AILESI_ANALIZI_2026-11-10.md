# Tarama Aileleri Karşılaştırması — rising / momentum / pulse / notifications

**Tarih:** 2026-11-10
**Önceki rapor:** `docs/RADAR_BACKTEST_ANALIZI_2026-11-10.md` (velocity ailesi)
**Yöntem:** Gerçek 1m mum replay + gerçekleşmiş işlem defteri teşhisi

---

## 1. Aile karşılaştırması (aynı çıkış modeli: gap %0,3, SL %2, fee %0,30)

| Aile | Ham kayıt | Replay edilen | Ort net | Medyan | Kazanan |
|---|---|---|---|---|---|
| velocity | 900 | 896 | +0,027% | −0,239% | %34,6 |
| rising | 900 | **0** | — | — | — |
| notifications | 709 | 709 | **+0,258%** | −0,072% | %44,9 |
| **trades** (gerçekleşmiş) | 900 | 900 | **+0,414%** | **+0,008%** | **%50,3** |

**Aynı çıkış modeliyle bile** kalite sıralaması net:
`trades > notifications > velocity`.

Yani kendi ölçümünün doğruladığı şey: **gerçekten işlem açmaya değer sinyaller
açtığın sinyallerden daha iyi değil** — bu iyi haber. Kötü haber: hepsi
filtresiz ~0 civarında.

---

## 2. `rising` ailesi — **ölçülemedi**, ama ölçülebilir kısmı zayıf

### Kritik veri boşluğu (düzeltilmeli)

`rising_alerts` tablosunda **hem `price` hem `expected_price` kolonu TAMAMEN
BOŞ** (4.279 kayıt, 0 dolu). Fiyat `signals` jsonb'inde de yok.

Sonuç: `rising` ailesi için gerçek mum replay'i **imkânsız**. Bu, monitoring
bildirimlerinde ve velocity'de olan `price` alanının rising'de yazılmadığı
anlamına gelir — ileride not: **rising sinyalleri fiyatsız kaydediliyor.**

### MFE/MAE ile kısmi ölçüm (3.231 kayıt)

| kind | n | ort MFE | ort MAE | MFE≥0,5 | MFE≥1 | MFE≥2 |
|---|---|---|---|---|---|---|
| yükseliş | 1.002 | 1,665 | −1,729 | %62,4 | %45,2 | %25,9 |
| erken | 2.229 | 1,198 | −1,196 | %60,6 | %40,6 | %18,2 |

`yükseliş` tipi `erken`'e göre **belirgin şekilde daha iyi** (MFE 1,665 vs 1,198;
MFE≥2 oranı %25,9 vs %18,2).

Sabit TP/SL simülasyonu (muhafazakâr: TP ve SL ikisi de değdiyse SL önce):

| kind | TP | SL | beklenen net |
|---|---|---|---|
| erken | 1,0 | 1,0 | −0,719% |
| yükseliş | 1,0 | 1,0 | −0,755% |
| erken | 1,0 | 1,5 | −0,962% |
| yükseliş | 1,5 | 1,5 | −1,046% |

Hiçbir kombinasyon pozitif değil. Ort MAE ≈ ort MFE olduğu için asimetri
yok — **rising ailesi de yapısal olarak sıfır/negatif.**

---

## 3. Mod bazlı kalite (monitoring_notifications, MFE/MAE ile)

| mode | n | ort MFE | ort MAE | MFE≥1 |
|---|---|---|---|---|
| **trend_devam** | 420 | 1,584 | −1,490 | **%48,1** |
| nötr | 161 | 1,324 | **−2,185** | %42,9 |
| **unified** | 126 | **0,858** | −1,036 | **%31,7** |

**`trend_devam` en iyi, `unified` en kötü** (MFE≥1 oranı neredeyse yarı yarıya:
%48,1 vs %31,7). Bu, önceki ölçümde `allowed_modes = ["trend_devam"]`
varsayılanının doğru olduğunu **bağımsız olarak** doğruluyor.

`nötr` modu en kötü MAE'ye sahip (−2,185) — yani en çok ters gidiyor. Mevcut
varsayılanda zaten dışlanmış, doğru karar.

---

## 4. ⚠ ASIL BULGU: gerçekleşmiş işlemlerde asimetri ters

1.757 kapalı işlem:

| Metrik | Değer |
|---|---|
| Ortalama kazanç | **+1,595%** |
| Ortalama kayıp | **−2,915%** |
| Kazanan oranı | %56,7 |
| **Kazanç/kayıp oranı** | **0,547** |
| **Kazanmak için gereken oran** | **0,764** |
| **AÇIK** | **−0,217 puan** |

Kazanan oranı %56,7 olmasına rağmen zarar ediliyor çünkü **kayıplar
kazançların 1,83 katı**. Matematiksel olarak kapanmayan bir açık.

### Kök neden: SL, TP'den geniş

| | Değer |
|---|---|
| Ortalama SL mesafesi | **3,88%** |
| Ortalama TP mesafesi | **3,75%** |
| SL/TP oranı | **1,03** |

Stop, hedeften **daha uzak**. Bu tek başına kayıp garantisidir: aynı
mesafede iki eşik varsa ve kazanma oranı %56,7 ise yine de kaybedilir,
çünkü kayıp büyüklüğü kazançtan fazladır.

### Çıkış nedeni dağılımı

| exit_reason | n | ort pnl |
|---|---|---|
| breakeven_stop | 457 | +1,419% |
| **stop_loss** | **391** | **−4,276%** |
| trailing_stop | 368 | +1,500% |
| symbol_deactivated | 239 | −1,029% |
| max_duration | 149 | −1,229% |
| take_profit | 125 | +2,771% |

`stop_loss` ortalaması **−4,28%** — diğer tüm kayıp nedenlerinin 3-4 katı.
391 işlem tüm zararın ana kaynağı.

**Not:** `breakeven_stop` (457) ve `trailing_stop` (368) aslında **kârlı**
çıkışlar (+1,42 / +1,50) — isimleri yanıltıcı, kâr koruma mekanizması
çalışıyor. `symbol_deactivated` (239, −1,03%) ise ölçülebilir bir sızıntı.

---

## 5. Öneri (öncelik sırası)

1. **SL/TP oranını düzelt: SL en fazla TP'nin %70'i olsun.**
   Mevcut oran 1,03 → hedef ≤ 0,70. Bu tek değişiklik, kazanma oranını
   %56,7'de tutarken sistemi başabaşın üstüne taşır (gereken oran 0,764
   olduğu için %70 yeterli değil; **≤0,64** güvenli marj bırakır).

2. **`stop_loss` çıkışını ayrıca incele** — 391 işlem, −4,28% ortalama.
   Stop genişliği 3,88% iken gerçekleşen kaybın 4,28% olması, slippage veya
   stop'un geç tetiklenmesine işaret ediyor (ek %0,4 kayıp beklenmedik).

3. **`symbol_deactivated` çıkışını gözden geçir** — 239 işlem, −1,03%.
   Pasifleştirme kapanışı, pozisyonu zorla zararına kapatıyor olabilir.

4. **`rising_alerts.price` yazımını düzelt.** Bu aile şu an ölçülemiyor;
   fiyat kaydedilirse gerçek replay yapılabilir hale gelir.

5. **Mod dağılımını koru:** `trend_devam` birincil, `unified` zayıf
   (bağımsız doğrulandı), `nötr` en yüksek ters hareket.

---

## 6. Araçlar

| Betik | Ne yapar |
|---|---|
| `scripts/family_replay.py` | Aile karşılaştırması + asimetri teşhisi + çıkış duyarlılığı |
| `scripts/gate_replay.py` | Üretim kapısından geçirip replay (velocity) |
| `scripts/ret3_replay.py` | `ret3_pct` bölge analizi |
| `scripts/trail_replay.py` | Trailing/SL dürüst replay |
| `scripts/filt_replay.py` | `atr_pct` filtreli replay |

```bash
cd backend
./.venv/Scripts/python.exe scripts/family_replay.py --limit 1500
```

---

## 7. Sınırlar

- **`rising` replay edilemedi** (fiyat kolonu boş). Yalnız MFE/MAE ile
  kısmi ölçüm; mum-içi sıralama bilinmediği için muhafazakâr varsayım
  (TP ve SL ikisi de değdiyse SL önce).
- **Aile örneklemleri farklı büyüklükte** ve farklı zaman aralıklarını
  kapsıyor (velocity 4 ay, notifications/rising ~1 ay). Doğrudan
  karşılaştırma piyasa rejimi farkı içerebilir.
- **`trades` ailesi seçim yanlılığı taşır**: bunlar zaten filtreden geçmiş,
  gerçekten açılmış işlemler. Ham sinyal evrenini temsil etmez.
- Slippage modeli yok; gerçek dolumda kayıplar daha büyük olur.
- Tek borsa, tek dönem.
