# Kesitsel Momentum — Çok-Rejimli Doğrulama (16. Tur) (2026-10-13)

**ARAŞTIRMA — commit YOK (kullanıcı isteği, 15. tur ile aynı).** Soru: 15. turda 90 günde
bulunan beta-elimine kesitsel momentum sinyali 600+ günde KARARLI mı?

## Yöntem
`backend/scripts/research_cs_multi_regime.py` — Binance futures (um) monthly klines arşivi
(`data.binance.vision`), top-60 likit USDT perpetual, 1d, 20 ay (~561 kesitsel nokta).
Aynı ölçüm: momentum (12-bar getiri) sırala → en güçlü topN long / en zayıf topN short →
`spread = ort(long fwd) − ort(short fwd)`, hold=6 bar, maliyet 2×taker.
Yerel önbellek: `work/cs_fut_cache/` (indirme bir kez, tekrar kullanılır).

## Ham sonuç — görünürde KARARLI
| Ölçüm | Değer |
|---|---|
| Net spread (2 bacak) | **+2.044%** |
| long-only excess (net) | **+1.736%** |
| 4-fold spread | 1.03 / 3.06 / 0.56 / 3.51 → **pozitif 4/4** |
| Verdict (script) | **KARARLI** |

Bu, 15. turun "kararlı değil" sonucunun tersi görünüyordu. **Ama üç kontrol testi bunu çürüttü.**

## Doğrulama — sinyal artefakt
`research_cs_verify.py` + `research_cs_robust.py` + `research_cs_listing.py`.

### (1) Rastgele sepet kontrolü — GEÇTİ
| | Net EV |
|---|---|
| Gerçek sepet | +2.02 |
| Rastgele sepet (aynı gün) | −0.38 |
| **Fark** | **+2.41, t = 4.18** |

Sinyal rastgeleden ayrışıyor — ama bu, TAM evren/örtüşen ölçümde. Asıl sorun örtüşme.

### (2) Örtüşen pencere şişmesi — KALDI
`hold=6` iken her bar ilerliyoruz → ileri getiriler 5/6 örtüşür → 561 nokta **bağımsız değil**.
| Ölçüm | n | EV | t (düz) | t (blok-boot) |
|---|---|---|---|---|
| Örtüşen (script1) | 561 | +2.02 | 4.21 | **2.44** |
| **Bağımsız (adım=hold)** | **94** | **+0.95** | **0.85** | **0.91** |

Bağımsız pencerelerde EV +2.04 → **+0.95**, t **anlamsız** (0.85). Bağımsız 4-fold:
[−0.26, 2.89, 1.12, 0.01] → 3/4. **script1'in "+2.04, 4/4" rakamı örtüşmenin ürünü.**

### (3) Sabit evren (survivorship) — KALDI
Evren sabit değil: 59 sembolden **yalnız 32'si 2025-03'ten beri var**; gerisi 2025-12…2026-08'de
listelendi (bugünün top-60 listesi). Yani sonraki foldlara "yeni listelenip bugün hâlâ top-60'ta
kalan kazananlar" giriyor → yapay yanlılık.

**Sabit evren (32 sembol, baştan beri var):**
| Ölçüm | EV | t (blok) | foldlar |
|---|---|---|---|
| Örtüşen spread | +0.696 | 1.00 | 2/4 |
| **Bağımsız spread** | **+0.295** | **0.31** | **1/4** |
| Bağımsız long_exc | +0.78 | — | [−0.18, 3.74, −0.02, −2.40] |
| Bağımsız rastgele kontrol | +0.295 vs −1.53 | fark t=1.93 (n94) | — |

Sabit evrende **edge kayboldu** (EV +0.29, t 0.29–0.31, bağımsız fold 1/4, son fold −2.40).

### (4) Listing-yaşı testi — son kalan iz de taze-listing
Her sembolün ilk N gününü hariç tutarak:
| min_hist | Bağımsız EV | t | win |
|---|---|---|---|
| 0 | +0.95 | 0.91 | 54.3 |
| 30 | +0.96 | 1.03 | 53.8 |
| 60 | +0.89 | 0.86 | 53.5 |
| **90** | **+0.39** | **0.33** | **49.4** |

90 günlük geçmiş şartı koyunca edge **+0.39, win %49** (yazı-tura) → kalan izin kaynağı
**taze listelenmiş coin'lerin momentum pump'ı**, sürdürülebilir alfa değil.

## Değerlendirme
- **15. turun "ilk anlamlı alfa" işareti 600 günde ÇÜRÜDÜ.** t=3.23/4.18 rakamları örtüşen
  pencerelerden geliyordu; blok-bootstrap ile t≈2.4, bağımsız pencerede t≈0.85.
- **Sinyalin görünen gücü iki artefakttan:** (i) örtüşme → şişik n/t; (ii) büyüyen
  survivorship evreni + taze-listing pump'ı. İkisi de kesilince edge ≈ 0.
- **Sabit evren** (baştan beri var olan 32 sembol) en dürüst koşu: EV +0.29, t 0.31, fold 1/4.
- Win oranı maliyet sonrası ~%50–54 → **net alfa yok.**

## KARAR
**KESİTSEL MOMENTUM KARARLI DEĞİL — artefakt.** 15. turdaki olumlu okuma, kısa veri +
örtüşme + survivorship'ten kaynaklanan yanılsamaydı. Canlıya **alınmaz**; metodolojik
ders: **kesitsel testlerde adım=hold (örtüşmesiz) + sabit evren ZORUNLU.**

Bu, "16. tur" olarak önceki 15 turun kapanışını netleştirir: bilinen adayların (lead-lag
hariç) hiçbiri üretim edge'i taşımıyor; **USD residual lead-lag** (üretimde) tek istisna
kalmaya devam ediyor.

## Yeniden üretim
```
# indirme + ana koşu (önbellek work/cs_fut_cache/)
python backend/scripts/research_cs_multi_regime.py --tf 1d --months 20 --top-syms 60
# kontroller
python backend/scripts/research_cs_verify.py  --tf 1d --top-syms 60
python backend/scripts/research_cs_robust.py  --tf 1d --top-syms 60
python backend/scripts/research_cs_listing.py --tf 1d --top-syms 60
```
