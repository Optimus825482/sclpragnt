# Bildirimdeki hedef, birleşik skor ve olasılık — üç denetimin ortak özeti (2026-10-18)

Soru: Bildirimde gösterilen üç sayı (hedef %, birleşik skor, isabet olasılığı) nasıl üretiliyor, ne kadar doğru, nasıl geliştirilir?
Veri: 729 bin Hız Avcısı adayı (17 Eyl–17 Eki), 709 sonuçlanmış bildirim, 14 bin birleşik aday; yürüyen-ileri bloklar; gerçekçi dolum (taker giriş, maker kâr al).
Raporlar: `HEDEF_DENETIMI_2026-10-18.md`, `SKOR_DENETIMI_2026-10-18.md`, `OLASILIK_DENETIMI_2026-10-18.md`.

## Tek cümlelik hüküm

Üç sayı da kullanıcıya olduğundan iyi bir resim çiziyor: hedef ulaşılabilirlik olarak şişkin, skor isabeti değil oynaklığı ölçüyor, olasılık kalibre değil ve üstüne hedefi sessizce düşürüyor. Hiçbir yeniden hesaplama net kârı pozitife çevirmiyor; ama sayıları dürüstleştirmek ve iki yapısal kusuru kaldırmak mümkün.

| sayı | nasıl üretiliyor | ölçülen gerçek | ana kusur |
|---|---|---|---|
| **Hedef %** | profil tabanı → skor kademesi → net-kâr tabanı → ATR → öğrenilmiş sembol hedefi (0,6 ağırlık) → ML karışımı (p ≥ 0,65). Birleşik yol: sabit 4,0 ya da 1,5 | Medyan MFE %0,58 iken medyan hedef %2,06; P(MFE ≥ hedef) %14,7 (5 dk %7,8, 15 dk %23,8). Sabit 4,0 hedef %4,6 tutuyor (n=195) | Oynaklığa ve ufka kör; öğrenilmiş hedef %89 sembolde tabana yapışık; birleşik yolda sabit 4,0 |
| **Birleşik skor** | ham = 100·ATR oranı·BB·yapı·momentum·hacim × çarpanlar; panel = 100·ln(1+ham)/ln(25001), 100'de kırpılır | ATR kontrol edilince AUC 0,48–0,52 (şans). Yüksek skorda net DAHA KÖTÜ (ρ −0,83…−0,88). "100" kovası ham 25 bin…66 milyonu topluyor | Kalite değil hareket şiddeti; skor eşiği neti düzeltmiyor |
| **Olasılık** | HGB (ml_forecast), etiket "5/15 dk MFE ≥ %2/%3", `class_weight=balanced`, ham predict_proba | ECE 0,22–0,37; 10-08 sonrası ort. p 0,95 iken gerçek %46. AUC 0,56–0,67 | Kalibre değil; p ≥ 0,65 hedefi ~3,3'ten ~1,7'ye düşürüyor (frontend notu yanlış) |

## Ölçülmüş, uygulanabilir değişiklikler (önerilen sıra)

1. **Ham "ML %" ibaresini push başlığından ve kartlardan kaldır.** Yerine, isteniyorsa, Platt ile kalibre olasılık aralığı ("%40–50"); 4–7 günlük pencere, günlük yeniden fit, sapma büyürse gizle. Beklenen ECE 0,03–0,05.
2. **ML hedef karışımını kapat** (p ≥ 0,65 kuralı). Hedefi düşürerek isabeti %12 → %23'e çıkarıyor ama net farkı sıfıra yakın; kullanıcıya "olasılık hedefi etkilemez" denmesine rağmen etkiliyor.
3. **Birleşik (füzyon) yoldaki sabit 4,0 hedefi kaldır**, aynı dinamik hedef zincirine bağla. %4,6 isabetli hedef gösterilmesin.
4. **Hedefi "ölçülmüş ulaşılabilirlik" olarak kur:** `T = clamp(exp(a)·ATR%^b·(ufuk/5)^d·exp(c·(skor−70)/10), 0,5, 6,0)`; nominal %30 isabete göre katsayılar raporda. B3'te her ATR/ufuk/skor diliminde %23–26 isabet (mevcut %5–32); net aynı (−0,54). Yanında "net hedef = brüt − 0,33" ve hücrenin geçmiş isabeti.
5. **Skoru "hareket şiddeti" diye etiketle**, kalite diye sunma; yeni alan: "tahmini isabet %" = σ(1,106 − 0,675·ln ATR − 1,402·ln(hedef/ATR) + 0,059·[ufuk≥15]) (SL %5 rejimi; haftalık yeniden uydurma) ve yanında başabaş isabet (%61–73).
6. **Skor içi düzeltmeler (veriyle destekli):** geç faz cezası (×0,6) yön olarak yanlış (+15 puan isabet); öncü ATR bonusu (×1,15) neti düşürüyor; CVD işareti skora girmiyor ama +5,8 puan isabet / +0,29 net (look-ahead doğrulanmalı).
7. **Veri kusurları:** `velocity.py:1371` volume_ratio sabit 0,0 yazıyor; `hit_calibration.py` hiç bağlı değil; yerel DB'deki pytest kirliliği (BTCTRY/ETHTRY, 60 satır) temizlendi.

## Neyi değiştirmiyor
Net beklenen değer her kuralda −0,5…−0,6 bandında. Sebep sinyalin yönsüzlüğü ve çıkış geometrisi (başabaş isabet %61–73, gerçekleşen ≤ %60). Bu denetim sayıları dürüst yapar, kârlı yapmaz.
