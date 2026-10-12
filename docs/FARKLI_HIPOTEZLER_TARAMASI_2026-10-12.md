# Farklı Hipotez Taraması + En İyi 2 Adayın Testi — 2026-10-12

**Durum: ARAŞTIRMA — commit/push YOK** (uygulama çalışma düzenine değişiklik yapılmadı).

## Kapsam
Yedi turda denenenlerden (tek-coin momentum, order-flow, lead-lag, ADX rejim, zıt-yön dönüş,
maker maliyet) **bağımsız** yeni hipotezler tarandı; en iyi 2'si derin test edildi.
Veri: `work/market_cache.sqlite` — 71 likit TRY sembolü × 45 gün 5m (mevcut geniş önbellek).
Araçlar: `scripts/screen_hypotheses_fast.py` (tarama), `scripts/verify_top2.py` (derin test).

## Tarama sonucu (net = taker %0.35 düşülmüş, 12-bar ileri)
| Hipotez | Net EV | Kazanma | n |
|---|---|---|---|
| **H5 saat 15:00 (UTC)** | **−0.124%** | 40.5% | 36K |
| H3 aşırı hareket dönüşü (\|z\|≥2) | −0.286% | 38.5% | 57K |
| H1 kesitsel momentum (long) | −0.363% | 32.8% | 170K |
| H2 volatilite sıkışması | −0.362% | 28.5% | 11K |
| H4 hacim-fiyat uyumsuzluğu | −0.400% | 36.8% | 94K |
| (Evren bazı, tüm barlar) | −0.305% | — | 870K |

**Beş hipotezin tamamı net negatif.** En iyi görünen ikisi (H5, H3) derin teste alındı.

## Derin test — ADAY 1: H5 saat sezonluğu
| Saat (UTC) | Net | 3-fold | Gün-gün poz. |
|---|---|---|---|
| 13:00 | −0.351% | −0.07/−0.50/−0.49 | 15/45 |
| 14:00 | −0.475% | −0.44/−0.31/−0.67 | 7/45 |
| **15:00** | **−0.124%** | **−0.29/+0.12/−0.20** | 17/45 |
| 16:00 | −0.308% | −0.22/−0.14/−0.56 | 13/45 |

**Çöktü:** 24 saatin **hiçbiri** pozitif değil; saat 15'in "iyiliği" 3-fold'de kararsız (yalnız
orta fold +), gün-gün 17/45, sembol bazında yalnız 16/71 pozitif. Yüksek t (19.2), evren bazının
o saatte daha kötü olmasından kaynaklanıyor — gerçek edge değil.

## Derin test — ADAY 2: H3 aşırı hareket dönüşü
| Eşik | Net | 3-fold | Gün-gün poz. |
|---|---|---|---|
| \|z\|≥2.0 | −0.286% | −0.26/−0.24/−0.36 | 0/46 |
| \|z\|≥2.5 | −0.267% | −0.24/−0.21/−0.35 | 1/46 |
| \|z\|≥3.0 | −0.259% | −0.22/−0.18/−0.38 | 2/46 |

**Çöktü:** Her eşikte üç fold da negatif, gün-gün 0-2/46. **Tutarlı** negatif = sistematik kayıp
(gürültü değil). Sembol yoğunlaşması düşük (%2-3) yani evrensel.

## KARAR
**Deploy edilebilir aday YOK.** Beş bağımsız yeni hipotezin tamamı, gerçekçi maliyet sonrası
negatif; en iyi ikisi de 3-fold + gün-gün testinde kararlı biçimde negatif. Bu, yedi turun
örüntüsünü bağımsız hipotezlerle de doğruluyor: **mevcut TRY/spot + maliyet yapısında bu sinyal
sınıfı ailesi kârlı değil.**

## Not: uygulama etkilenmedi
Analiz ayrı bir SQLite dosyasında koştu; commit/push yapılmadı. Canlı sistem (PG + API) daha
önce sağlıklı doğrulanmıştı (kilit 0, 200 OK).

## Yeniden üretim
```
python backend/scripts/screen_hypotheses_fast.py --days 45
python backend/scripts/verify_top2.py
```
