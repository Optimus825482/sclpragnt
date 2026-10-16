# 60 Günlük Backtest — Veritabanı Verisi ve Yeniden Tarama (2026-10-16)

**Fark:** Önceki 60 günlük rapor (`BACKTEST_60G_2026-10-16.md`) canlı journal'a bağımlıydı (31 gün). Bu raporda Binance TR'den 60 günlük 1 dk / 5 dk / 15 dk mumlar veritabanına çekildi ve **mevcut Hız Avcısı dedektörü bu mumlar üzerinde yeniden koşturuldu** (`scripts/rescan_velocity_history.py`). Böylece algoritmanın 17 Ağustos–16 Ekim arası 60 günlük davranışı, canlı journal'dan bağımsız ölçüldü.

## 1. Veri ve yöntem
| Öğe | Değer |
|---|---|
| Mum verisi (DB `historical_candles`) | 1 dk 26.6 M satır (305 sembol), 5 dk 5.3 M, 15 dk 1.8 M; 17 Ağu–16 Eki |
| Çekim | `backfill_historical_candles.py`, üç paralel süreç (concurrency 6), ~55 dk; birkaç 429 → otomatik soğuma, veri kaybı yok |
| Yeniden tarama | 1 dk adım, havuz = günlük en çok yükselen 30 + aktif 15 + keşif 8 + SYMBOLS; dört paralel 15 günlük pencere, toplam ~6 dk |
| Üretilen aday | 465.248 (`candidate_id` `rescan:…`, `status='rescan'`, DB + JSONL) |
| Sadakat (canlı journal ile örtüşen pencere) | 16–30 Eyl: canlı adayların **%97.8**'i yeniden üretildi, skor korelasyonu 0.93; 1–16 Eki: **%94.7**, 0.89. Kesinlik %23–50 (rescan spread/ML kapısı olmadan ~1.5–3× fazla aday üretir) |
| Sapmalar | spread/taker/emir defteri/ML/öğrenilmiş hedef yok (nötr), `created_at` 1 bar kayma; bkz. `docs/RESCAN_HARNESS.md` |

## 2. Tespit başarısı: 60 gün, şansa karşı (olay bazında)
Olay = aynı sembolde ≥60 dk boşluktan sonraki ilk aday (465 k satır → 13.636 olay). Şans = aynı sembol, 30 dk volatilite/getiri eşleşmiş rastgele anlar.

| | n | Hedefe ulaşma (kendi ufku) | Şans | Fark | Net60 | Net − şans |
|---|---|---|---|---|---|---|
| 60 gün | 13.636 | **%14.8** | %11.5 | **+3.2 ± 0.6 pp** | −0.41 ± 0.03 | −0.03 ± 0.03 |
| İlk 30 gün (17 Ağu–15 Eyl) | 6.542 | | | +2.4 ± 0.9 | | −0.04 |
| Son 30 gün (16 Eyl–16 Eki) | 7.094 | | | +4.0 ± 0.8 | | −0.02 |

- **9 haftanın 9'unda** fark pozitif (8'inde güven aralığı sıfırın üstünde, +1.5 … +4.6 pp).
- Avantaj rejimle azalmıyor; son 30 günde biraz artıyor.
- Ama **net getiri şansla aynı** (−0.41 vs −0.38): dedektör yükselişi yakalıyor, ters hareket (MAE −1.31) ve maliyet kazancı siliyor.

**Ayıran özellikler (fark, pp, düşük uç → yüksek uç):** ATR tertili +1.0 → +5.4 (isabet %10 → %21), panel skoru quintili +0.6 → +5.4, ret3 çeyreği +2.2 → +5.9, hacim oranı +1.5 → +5.5, satır hedefi %3 → %4: +1.8 → +5.2, rank 1 vs 4–10: %18.7 vs %12.3. Saat ayırmıyor; sembol yoğunlaşması yok (ilk 10 payı %12). Kısa ufuk şansa göre daha güçlü: 5 dk 1.70×, 15 dk 1.42×, 60 dk 1.29×.

**Net-pozitif alt küme araması:** 248 hücre (n ≥ 300, her yarıda n ≥ 100) içinde TP = hedef/1.5/2/3 çıkışlarıyla ortalaması sıfırın üstünde olan **yok**; ilk yarıda pozitif 2 hücre ikinci yarıda −0.31. "Net − şans" ölçütünde iki yarıda da pozitif 31 hücre var ama saf gürültüde ~62 beklenir; yalnız 2'sinin alt CI'sı sıfırın üstünde.

## 3. Canlı ile rescan aynı popülasyon mu? (16 Eyl–16 Eki, olaylar)
| Küme | n | hit60 (T = %2) | Net60 |
|---|---|---|---|
| Canlı journal | 4.355 | %34.7 | −0.44 ± 0.06 |
| Rescan | 7.098 | %30.4 | −0.43 ± 0.04 |

Replay düzeyinde de aynı: birleşik havuz replay'i 30 gün canlı adaylarla EV −0.480 (n 48.225), rescan adaylarla EV −0.476 (n 101.078); rescan'de kazanma oranı düşük (%34.7 vs %42.4) ama payoff yüksek (1.01 vs 0.69), net eşit.

Net birebir aynı (z = 0.13); isabette rescan biraz muhafazakâr (z = −4.7; eşleşen alt kümede %34.8 vs %37.7). Canlı adayların %94'ü rescan'de var; rescan'de olup canlıda olmayanların isabeti daha düşük (%27.8). Yani 60 günlük rescan rakamları canlıya göre **hafif kötümser** ama yön ve büyüklük güvenilir.

## 4. Replay ve kalibrasyon, 60 gün (rescan adayları, DB mumları)
| Ölçüm | n (sınav) | TP/Kazanma | Ort. net %/işlem | Not |
|---|---|---|---|---|
| Birleşik havuz replay'i (`--candidates-source rescan --days 60`) | 185.553 | kazanma %35.4, payoff 0.99 | **−0.459** (medyan −0.55) | 3-fold −0.46/−0.47/−0.45; **0/24 gün** pozitif; maker maliyetiyle −0.21, 1/24 gün |
| Skor-top (üst %50) | 96.122 | %34.9 | −0.48 | skor seçici değil (30 ve 7 günle aynı) |
| Kombine kalibrasyon (`--hours 1440 --candidates-source rescan`) | _(bölüm 4.1)_ | | | |

### 4.1 Kalibrasyon sonucu
_(koşu tamamlanınca dolduruldu, aşağıya bakın)_

## 5. Değerlendirme
1. **60 günlük veriyle de aynı sonuç, daha kesin:** tarama algoritması yükselme potansiyelini şanstan iyi yakalıyor (9/9 hafta, iki rejimde), fakat bu isabet maliyet sonrası net getiriye **dönüşmüyor** (0/24 gün pozitif, 185 k işlem).
2. **Canlı journal'ın 31 günlük sonuçları 60 güne genelleniyor:** rescan ile canlı aynı net getiriyi veriyor; dolayısıyla "kısa pencere şansı" açıklaması dışlanmış oldu.
3. **Neyin işe yaradığı netleşti:** ATR, skor, hacim oranı ve kısa vadeli momentum isabeti ayırıyor; kısa ufuk (5 dk) şansa göre en güçlü. Bunlar taban/filtre olarak kullanılmalı, sıralayıcı olarak değil (skor-top yine kötü).
4. **Kârlılık için sinyal tarafında yapılacak iş bitti:** 248 alt küme × 4 çıkış taraması net pozitif tutarlı hiçbir hücre bulmadı. Kalan kaldıraçlar maliyet (BNB), giriş gecikmesi ve çıkış/boyutlama; bunlar bu haftaki değişikliklerle canlıda ölçülecek.
5. **Altyapı:** 60 günlük (ya da daha uzun) ölçüm artık dakikalar içinde tekrarlanabilir: backfill → rescan (4 paralel pencere, ~6 dk) → replay/kalibrasyon/olay analizi.

**Sınırlar:** rescan'de spread/taker/ML kapıları yok (aday sayısı canlının 1.5–3×'i, isabet hafif düşük); olaylar piyasa genelinde bağımlı (CI'lar iyimser); giriş = satır fiyatı; aynı mumda SL önce; 5 dk mum granülaritesi.
Ham çıktılar: scratchpad `backtest/rescan60/` (JSONL, doğrulama JSON'ları, `eval/eval_rescan_60d.md`, replay/kalibrasyon çıktıları).
