# Kesitsel Nötr Sepet (Cross-Sectional) Testi — 15. Tur (2026-10-13)

**ARAŞTIRMA — commit YOK.** Seçenek: beta'yı eleyip saf alfa (göreli güç) var mı?

## Neden bu test
1d momentum tek-bacak testinde "+EV" çıktı ama doğrulama gösterdi: **long +3.12 / short −6.43**
→ kazanç piyasa betasıydı. Kesitsel sepet aynı anda **en güçlü N long + en zayıf N short**
yaparak piyasa yönünü eler; kalan **göreli güç (alfa)** olur.

## Yöntem
`backend/scripts/research_cross_sectional.py` — 80 TRY sembol, 4h ve 1d.
Her 4h/1d noktasında: momentum (12-bar getiri) sırala → en güçlü topN long, en zayıf topN
short → `spread = ort(long fwd) − ort(short fwd)`. hold=6 bar. Maliyet: her bacak round-trip.

## Sonuç — ilk ANLAMLI, beta-elimine sinyal

### 4h, lookback=12, hold=6, topN=2
| Ölçüm | Değer |
|---|---|
| Brüt spread | **+2.52%** |
| Net (2 bacak taker) | **+1.82%** |
| long excess (net) | +0.96% |
| short excess (net) | +0.86% |
| **Rastgele sepet kontrolü (aynı gün)** | −0.01% (brüt) |
| **Fark (gerçek − rastgele)** | **+2.54%, t = 3.23** ✅ ANLAMLI |

**Kritik:** rastgele sepet aynı günde ≈0 üretirken momentum-spread +2.5 → **sıralama bilgi
taşıyor, piyasa betası değil.** Hem long hem short bacak pozitif (alfa iki taraflı).

### Kırılganlık — momentum crash
| Fold | Net spread | Kapsanan dönem |
|---|---|---|
| fold1 | **+4.54%** | 2026-07-14→08-12 |
| **fold2** | **−0.79%** | 2026-08-12→09-10 (momentum ters döndü) |
| fold3 | +1.71% | 2026-09-10→10-09 |

3 dönemin **ortadaki negatif**. Bu klasik **momentum crash** (kesitsel momentumun bilinen
zayıflığı). topN=3'te de aynı örüntü (3.23/−0.91/1.01). Long-only excess: tüm dönem +0.96,
fold1 +3.38 / fold2 −1.05 / fold3 +0.55.

## Değerlendirme
- **Olumlu:** 15 turda **ilk kez** beta-elimine, istatistiksel olarak anlamlı (t=3.23),
  rastgele kontrolden ayrışan bir sinyal. Yön doğru: kesitsel momentum gerçek.
- **Sorun:** 90 günlük veri **tek rejim**; fold2 (momentum crash) sinyalin rejim-bağımlı
  olduğunu gösteriyor. Kararlılık için daha uzun geçmiş şart.
- **Uygulanabilirlik:** TRY **spot long-only** → short bacak doğrudan uygulanamaz. Long-only
  excess +0.96% net (pozitif ama win %40.8 → pozitif çarpıklık; az sayıda büyük kazanan).

## KARAR
**TEŞVİK EDİCİ AMA KARARLI DEĞİL.** İlk gerçek alfa işareti, ama:
1. 3 fold'dan ortadaki negatif (momentum crash) → rejim bağımlı,
2. veri yalnız 90 gün (tek rejim) → kararlılık iddiası KURULAMAZ,
3. spot long-only kısıtı short bacağı eliyor (long-only tek başına zayıf).

**Sonraki adım (önerilen):** Veri penceresi kritik. İki yol:
- **(i)** 600+ gün futures verisiyle (aynı 4h/1d kesitsel momentum) çok-rejimli doğrulama —
  momentum crash'i içerip içermediğini ve long-only excess'in sürdürülebilirliğini ölçer.
  Bu, "kararlı mı" sorusunun NET cevabıdır ve tek eksik parça **daha uzun geçmiş**.
- **(ii)** Long-only sürümü (short yerine "zayıf adaylardan kaçın") + pozisyon boyutlandırma.

Bu, ilk kez "kâra dönük" bir iz; tek gereken **veri derinliği**. Canlıya alınmadı
(90 gün/tek rejim yetersiz). Commit edilmedi (kullanıcı isteği).

## Yeniden üretim
```
python backend/scripts/research_cross_sectional.py --tf 4h --topn 2 --lookback 12 --hold 6
```
