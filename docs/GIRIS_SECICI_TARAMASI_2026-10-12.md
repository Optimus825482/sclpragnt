# Giriş Seçici Taraması — 2026-10-12

Devam: [KALIBRASYON_combined_paper_2026-10-12.md](KALIBRASYON_combined_paper_2026-10-12.md)

## Soru
Çıkış geometrisi kalibre edildi (SL 3.0→1.0) ama portföy hâlâ negatif. Kalan kaldıraç
**hangi sinyalleri işleme alacağımız** (giriş seçicisi). Pozitife dönen bir filtre var mı?

## Yöntem
Aynı harness (`scripts/calibrate_combined_paper.py --entry-scan`): 5.909 gerçek velocity
adayı + gerçek mumlar, kronolojik %60 eğitim / %40 sınav walk-forward, SL=1.0 sabit.
Sınav kümesinde (n=2338) ölçülen filtreler: skor / rank / ATR / gerçek-liste taklidi (30 dk
top-N) + eşleştirilmiş (seçilen vs seçilmeyen) t-testi.

## Bulgular
| Filtre (5m SINAV EV) | EV/işlem | n | Payoff |
|---|---|---|---|
| Baz (filtresiz) | **-0.360%** | 2338 | 1.15 |
| score ≥ p85 | -0.344% | 253 | 1.51 |
| atr ≥ p70 | -0.209% | 452 | 1.33 |
| rank == 1 | -0.252% | 1137 | 1.25 |
| **gerçek liste taklidi top-1** | **-0.918%** | 28 | 3.26 |
| top-3 | -0.626% | 85 | 2.42 |

Eşleştirilmiş testler (seçilen vs seçilmeyen):
- `rank==1`: fark **+0.32 puan, t=3.2** (ANLAMLI, ama hâlâ negatif).
- `score≥p85`: fark +0.41 puan, t=2.48 — küçük örneklemde (n=83) kaybolan, tam örneklemde
  baza yakınsayan zayıf sinyal.
- `atr≥p70`: fark **-0.39 puan, t=-3.1** — yüksek ATR **kötü** (beklenen).
- **top-1 seçim (en yüksek skor): -1.03% vs tümü -0.55%** → en yüksek skorlu seçim
  tüm adaylardan **DAHA KÖTÜ**.

## Karar
**KARAR: NO_ENTRY_EDGE** — hiçbir tek-değişkenli filtre sınav kümesinde pozitif EV
üretmiyor. Yani edge **giriş sinyalinin kendisinde yok**; mevcut `velocity_score`
sıralaması bilgilendirici değil (hatta tersine). Uygulanacak bir parametre yok —
körlemesine filtre sıkılaştırmak örneklemi küçültür, EV'yi düzeltmez.

## Neden önemli
Bu, "ayar yap, düzel" döngüsünün sınırını gösterir: tükenme noktası **çıkış değil,
GİRİŞ sinyalinin kendisidir**. Pozitife dönüş için gereken, yeni/bağımsız bir öngörücü
(skorun yerine geçecek kanıt) — ayrı bir araştırma işi.

## Yeniden üretim
```
python backend/scripts/calibrate_combined_paper.py --hours 3600 --fetch --entry-scan
```
Rapor: `work/cp_entry_scan_full.json` (gitignore'da; ham veri).
