# Maliyet-Duyarlılık Analizi — 2026-10-12

Devam: [REJIM_GUDUMLU_SINYAL_ARASTIRMASI_2026-10-12.md](REJIM_GUDUMLU_SINYAL_ARASTIRMASI_2026-10-12.md)

## Soru
Beş turun ortak teşhisi: motor sinyalleri hep hafif negatif EV verdi; en iyi hücreler 0'a
yakın ama pozitif değil. **Hipotez: sinyaller komisyon eşiğinin altında.** Tüm simülasyonlar
~%0.15/bacak TAKER komisyonu varsaydı (round-trip ~%0.30). Peki komisyon düşerse (maker)
sinyaller kâra döner mi?

## Yöntem
`scripts/research_cost_sensitivity.py` — her güçlü sinyal için **BRÜT** getiri serisi
(komisyonsuz) hesaplanır, sonra komisyon 0 → %0.15 süpürülerek:
1. **Başabaş komisyon** (EV=0 yapan per-leg oran) bulunur,
2. Taker (%0.15), maker-benzeri (%0.02) ve sıfır senaryolarında net EV verilir,
3. **Adverse-selection testi:** gerçek limit giriş simülasyonu (limit dolmazsa işlem yok).

## Bulgular 1 — Evet, sinyaller komisyon eşiğinin altında
| Sinyal | n | Brüt EV | Başabaş comm | Taker %0.15 | Maker %0.02 | Sıfır |
|---|---|---|---|---|---|---|
| 5m:vol_r_high (hacim patlaması) | 559 | **+0.341%** | **%0.170** | +0.04 | **+0.30** | +0.34 |
| 5m:r1_high (öncü momentum) | 641 | +0.168% | %0.084 | −0.13 | **+0.13** | +0.17 |
| 5m:tbr_low (order-flow) | 549 | +0.153% | %0.076 | −0.15 | **+0.11** | +0.15 |
| 5m:g_ret1_high (Global lead-lag) | 661 | +0.145% | %0.072 | −0.16 | **+0.11** | +0.15 |
| 1h:aralik_dip (rejim) | 25978 | +0.058% | %0.029 | −0.24 | +0.02 | +0.06 |

**Teşhis doğrulandı:** bu sinyallerin BRÜT beklentisi pozitif, ama taker komisyonu (%0.30
round-trip) hepsini negatife sokuyor. Maker komisyonuyla (%0.02) **5/8 sinyal pozitif** oluyor —
özellikle `vol_r_high` (hacim patlaması) maker'da **+0.30%**.

## Bulgular 2 — AMA maker edge'i adverse-selection ile ÇÖKÜYOR
Naif maker hesabı, sinyalin %100'ünün limit emirle dolduğunu varsayar. Gerçekte limit emir
yalnız fiyat o seviyeye **geldiğinde** dolar — ki bu genellikle fiyatın **düştüğü** (olumsuz)
durumdur. Gerçek limit-dolgu simülasyonu:

| Giriş tipi | Komisyon | EV/işlem |
|---|---|---|
| Taker giriş (referans) | maker %0.02 | **+0.278%** |
| **Gerçek limit giriş (dolmazsa işlem yok)** | maker %0.02 | **−0.279%** |
| Limit, %0.3 aşağıda bekleyerek | maker %0.02 | −0.279% |
| Limit, %1.0 aşağıda bekleyerek | maker %0.02 | −0.292% |

**"Maker edge"i tamamen ters seçimdir.** Naif hesapta +0.28% olan sinyal, gerçek limit
dolgusunda −0.28%'a düşer: limitin dolduğu işlemler fiyatın düştüğü işlemlerdir; dolmayan
iyi işlemler kaçar. 559 seçili sinyalin yalnız 391'i dolar (168'i kaçar) ve dolanlar kötüdür.

## KARAR
**Maker hipotezi ÇÜRÜDÜ.** Maker komisyonu "bedava" değil — bedelini **adverse selection**
olarak ödüyor. Görünüşteki pozitif maker EV'si bir ölçüm yanılgısıydı (dolgu varsayımı).
Uygulanacak maker mimarisi yok.

## Altı turun kesin sonucu
| # | Katman | Ufuk | Sonuç |
|---|---|---|---|
| 1 | Çıkış geometrisi (SL 3.0→1.0) | 5 dk | Kaybı ~%50 azalttı ✅ UYGULANDI |
| 2 | Giriş seçici (skor/rank/ATR/ML) | 5 dk | `NO_ENTRY_EDGE` |
| 3 | Fiyat-mum feature'ları | 5 dk | `NO_FEATURE_EDGE` |
| 4 | Order-flow / lead-lag kanalları | 5 dk | `NO_CHANNEL_EDGE` |
| 5 | Rejim-güdümlü sinyal | 1 saat | `NO_REGIME_EDGE` (hipotez yönü doğru) |
| 6 | **Maker/maliyet mimarisi** | — | **`NO_MAKER_EDGE`** (adverse selection) |

**Net sonuç:** Ölçülebilir hipotez uzayının tamamı — sinyal, ufuk, rejim, veri kanalı ve
maliyet yapısı — tükendi. Motorun ürettiği sinyaller brüt olarak hafif pozitif olabilse de
(`vol_r_high` +0.34%), gerçekçi yürütme maliyeti (taker VEYA maker+adverse-selection) bunu
her durumda siler. Bu bir parametre/sinyal sorunu değil: **sinyalin ham bilgi içeriği
(~+0.1–0.3% brüt), yürütme maliyet tabanının (~%0.3 taker, maker'da dolgu riski) altında.**

**Öneri artık net:** Bu sinyal ailesiyle kârlı otonom işlem, mevcut veri ve maliyet
yapısında mümkün görünmüyor. Anlamlı bir sonraki adım, mikro-yapıda ölçülebilir bir avantaj
gerektirir (ör. gerçek order-book derinliğinden türetilen, likit seviyelerde dolan limit
stratejisi) veya tamamen farklı bir varlık/venue — bu, ayrı ve daha büyük bir ürün yatırımı.

## Yeniden üretim
```
python backend/scripts/research_cost_sensitivity.py
```
Rapor: `work/cost_sensitivity.json` (gitignore).
Kilitler: `tests/test_research_cost_sensitivity.py` (komisyon düşümü + başabaş + adverse-selection).
