# Yeni Bilgi Sınıfı Ön Testi — İlk 3 Aday (2026-10-13)

**ÖN TEST — kısa vadeli; kapsamlı walk-forward/replay GECE (off-peak) koşusuna bırakıldı.**

## Erişilebilirlik + tarihsellik taraması (doğrulandı)
| Kanal | Erişim | Tarihsel derinlik | Test edilebilir? |
|---|---|---|---|
| **funding rate** (fapi) | ✅ 200 | **120+ gün** | ✅ |
| **fear&greed** (alternative.me) | ✅ 200 | 90 gün günlük | ✅ (makro) |
| **OKX/Coinbase klines** | ✅ 200 | canlı (pencere sınırlı) | ✅ |
| OI / long-short (futures/data) | ❌ HTTPError | kısa pencere | ❌ |
| CryptoPanic haber | ❌ 403 (token) | — | ❌ |

## İlk 3 aday (erişilebilir + geriye dönük test edilebilir)
- **A1 FUNDING TAŞIMA**: aşırı pozitif funding (kalabalık long) → ters dönüş hipotezi.
- **A2 MAKRO DUYGU**: Fear&Greed uçları → risk iştahı yönü.
- **A3 CROSS-VENUE**: BTC OKX (USDT) → BTC TRY öncülük (lead-lag).

## Ön test sonuçları (`research_new_channels_precheck.py --days 60`)
| Aday | Bulgu | Ön karar |
|---|---|---|
| **A1 funding** | corr **+0.14**; aşırı-poz funding → sonraki 1s getirisi **+0.134%** vs aşırı-neg **−0.018%** | **DEVAM** |
| **A2 fear&greed** | 1d BTC verisi eksik → ölçülemedi (n=0) | veri bekliyor |
| **A3 cross-venue** | corr_okx_fwd **+0.066**, eşzamanlı −0.017 (fwd>same → öncülük işareti) | **DEVAM** |

## Yorum (dürüst)
- **A1** ilginç: yüksek funding → sonraki getiri POZİTİF. Yani "kalabalık long → ters dönüş"
  hipotezinin AKSİ (momentum). Küçük ama ölçülebilir ilişki; kapsamlı test gerek.
- **A3** zayıf ama yön doğru: OKX getirisi TRY'nin sonraki barıyla pozitif, eşzamanlıdan
  büyük → hafif öncülük (daha önce USD→TRY residual +0.14 bulmuştuk; OKX benzer).
- **UYGULANABİLİRLİK UYARISI:** funding ve OKX/Coinbase majör çiftlerde (BTC) var; işlem
  yaptığımız TRY alt-coinlerin çoğunda futures karşılığı yok. Sinyalin **BTC'den TRY
  alt-coin evrenine taşınabilirliği** gece görevinin ana sorusu.
- **A2** veri eksikliğinden atlanmadı, ertelendi (1d BTC serisi tam çekilince test edilir).

## Sonraki adım: gecelik kapsamlı backtest/replay (off-peak)
3 adayın tamamı, 60 günlük veri + walk-forward + maliyet (taker/maker) + sembol
yoğunlaşması + 3-fold ile ölçülecek. Eşik: net EV>0 & 3-fold kararlı. Geçmezse
canlıya alınmaz. Off-peak görev olarak kuyruğa alındı.

## Yeniden üretim
```
python backend/scripts/research_new_channels_precheck.py --days 60
```
Rapor: `work/new_channels_precheck.json`.
