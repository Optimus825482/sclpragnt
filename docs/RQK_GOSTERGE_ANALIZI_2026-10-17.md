# Rational Quadratic Kernel (RQK) göstergesi — LUNA tipi erken yükselişler için destek verir mi? (2026-10-17)

**Soru:** Grafiğin "Rational Quadratic Kernel" göstergesi (yükselirken yeşil, düşerken kırmızı; renk değişimi = al/sat) LUNATRY 17 Ekim 01:00 (+%8 / 60 dk) gibi erken yükselişleri
**mevcut sistemden (Hız Avcısı, HA) daha erken ya da daha iyi** yakalamaya yardım eder mi?

## 1. Sonuç

**Erken tespit — hayır.** Çekirdek yükselişten ÖNCE yeşile dönmüyor: t0'da yeşil olma oranı olayda 1m/5m/15m için %22/%37/%54 (rastgele anda %46/%49/%52); t0'dan önceki 15 dk'da AL dönüşü olay tarafında rastgele andan DAHA AZ (5m: %17 vs %24; AUC 0,47) — olaylar küçük bir düşüşün dibinden başlıyor ve çekirdek o sırada kırmızı. Dönüş yükseliş başladıktan SONRA geliyor: 5m dönüşü t0'dan medyan 20 dk sonra, fiyat P0'ın +1,84% üstündeyken (HA'nın ilk adayı: medyan 15 dk, +2,48%); 15m dönüşü +2,90% ile çok geç. 1m çekirdek t0'dan medyan 4 dk sonra dönüyor ama 1m çekirdek rastgele anlarda da her ~8 dk'da dönüyor (t0…t0+15 AUC'si 0,55). (t0'dan SONRAKİ pencerelerdeki yüksek oranlar kısmen tanım gereği: olayın ilk 5m mumu yeşil ve P0'ın üstünde olmak zorunda.)

Sinyal penceresi karşılaştırması (olay ↔ rastgele an): 5m çekirdek AL dönüşü t0…t0+15 dk %49 ↔ %24 (2,0×), t0…t0+30 dk %64 ↔ %45 (1,4×); HA adayı için %29 ↔ %13 (2,3×) ve %50 ↔ %19 (2,6×). İkisi de 30 dk içinde sinyal veren 1.441 olayda 5m dönüşü HA'dan %62 oranında önce (%21 aynı 5 dk), medyan 5 dk önce — küçük bir zaman avantajı var; ama dönüş rastgele anların da %45'inde görüldüğü için ayırt edicilik HA'dan düşük ve çekirdek bağımsız bir 'erken uyarı' vermiyor. LUNATRY'de 5m çekirdek zaten t0'dan önce yeşildi (son AL dönüşü 160 dk önce; yükseliş boyunca hiç dönüş yok), 1m çekirdek 01:02'de P0 seviyesinde döndü (ama 00:00–01:02 arasında 1m çekirdek altı kez AL döndü; tek başına gürültü).

**Giriş sinyali olarak — HA'nın gerisinde; B1'de rastgeleden ayrışmıyor, B2/B3'te küçük ama pozitif.** 8 yapılandırma (5m/1m × {yalnız likidite, +EMA99, +15m yeşil, +ikisi}) için şans farkı: B1: 2/8 hücrede aralık > 0, en yüksek +1,7 pp (HA +3,5 pp); B2: 7/8 hücrede aralık > 0, en yüksek +3,5 pp (HA +4,6 pp); B3: 8/8 hücrede aralık > 0, en yüksek +2,8 pp (HA +5,4 pp). HA'yı geçen hücre sayısı **0/24**. Soğuma sonrası bile günde ≈ 866–4.660 sinyal (HA ≈ 200–250). net60 hiçbir hücrede pozitif değil (en iyi -0,213 %/işlem; HA −0,36…−0,43 — fakat HA daha oynak sembol-günlerde olduğundan net60 doğrudan kıyaslanmaz, şans farkı kıyaslanır); trailing net en iyi -0,175 (HA ≈ 0,00 … −0,06). 'Olay içi' kat ≈ 1–1,5× (HA ≈ 13–14×): dönüş sinyali olay pencerelerini rastgele ana göre pek zenginleştirmiyor. B2/B3'teki küçük pozitif fark, B1'de olmayışı ve HA'nın yarısı kadar büyüklüğü nedeniyle büyük olasılıkla genel yükseliş-momentumuyla ilgili (nedensellik bu veriyle ayrıştırılamaz).

**HA filtresi olarak — ölçülebilir ek değer yok.** 15 durum grubundan (varsayılan A/h8/r2, 5m ve 15m) üç blokta birden (Δ isabet %95 aralığı > 0 ve şans farkı HA'nın üstünde) HA'yı iyileştiren: **yok**. Üç bloktan ikisinde tutan (post-hoc): 5m kırmızı; 15m yeşil, olgun (>3 bar); 5m kırmızı + 15m yeşil. Üç blokta da HA'yı kötüleştiren: 15m yeşil, yeni (≤3 bar). 5m çekirdek aday anında KIRMIZI iken HA daha iyi (beklenen 'yeşil teyit eder'in tersi): Δ isabet (kırmızı − yeşil) B1 +5,9 pp [+2,1; +9,5], B2 +4,3 pp [+0,7; +7,6], B3 +1,0 pp [-2,0; +4,5] — etki B3'te kayboluyor.

Kontrol (aynı sembol-gün rastgele anlar): 15m_A_h25_r2 yeşilken rastgele anlarda hit60@1,5 +10,8 pp/+11,0 pp/+9,1 pp yüksek (B1/B2/B3) — genel momentum etkisi; HA içinde ise yalnız +1,6 pp/+4,8 pp/+4,6 pp. Fark-farkı -9,3 pp/-6,2 pp/-4,5 pp (her blokta aralık < 0): çekirdek rengi HA'nın seçtiği adayların üstüne ek bilgi taşımıyor — HA bu bilgiyi zaten içeriyor.

**Parametreler (yürüyen-ileri, B1'de seçip B2/B3'te test):** (E) AL dönüşü sinyali için B1'in en iyisi 5m_A_h8_r8: şans farkı B1 +0,7 pp → B2 +2,2 pp, B3 +2,0 pp; HA +3,5 pp/+4,6 pp/+5,4 pp. Tüm 24 kombinasyonda blok başına en yüksek şans farkı +0,7 pp/+2,2 pp/+2,3 pp — HA'nın altında; varyant B, h=16/25, r=1/8 ve 1m/15m seçenekleri varsayılandan anlamlı biçimde iyi değil.

(F) HA filtresi olarak B1'de seçilen **15m_A_h25_r2** (HA adayı anında 15m çekirdek h=25 yeşil ise tut): skor (yeşil−kırmızı şans farkı) B1 +3,0 pp (içi), B2 +4,1 pp, B3 +4,0 pp (dışı) — işaret üç blokta tutarlı, ama korunan kümenin isabeti HA tümünün yalnız +0,3 pp/+1,0 pp/+1,0 pp üstünde, net60 hâlâ negatif ve kontrol testinde HA'ya özgü katkı yok. Bu, tek bir filtre varyantının seçim-dışı bloklarda küçük ve pratik değeri olmayan bir işaret tutarlılığıdır.

**Genel hüküm:** RQK çekirdeği (uygulamadaki ya da kanonik ayarlarla) LUNA tipi erken yükselişlerde (a) yükselişten önce değil sonra döndüğü (HA ile ortak olaylarda birkaç dk önce olabilir ama rastgele anlarda da sık döndüğü için ayırt edici değil), (b) giriş sinyali olarak HA'nın gerisinde kalan, B1'de sıfır, B2/B3'te küçük bir şans farkı ürettiği, (c) HA adaylarına filtre olarak örneklem dışında HA'nın zaten seçtiği momentumun ötesinde bilgi eklemediği (kontrol testinde fark-farkı her blokta negatif) için **HA'ya anlamlı bir destek sağlamıyor; daha erken değil, daha iyi de değil**. Canlıya alma önerisi yok. Tek tutarlı örüntü: 15m çekirdek az önce (≤ 3 bar) yeşile döndüyse HA adayı daha kötü (Δ isabet B1 -3,4, B2 -5,1, B3 -4,2 pp; üç blokta aralık < 0), 5m çekirdek kırmızıysa (geri çekilme) biraz daha iyi (B3'te kayboluyor). Bu 'yeni dönüşü kovalama / geri çekilmeyi bekle' hipotezi olarak ileri (kâğıt-defter) testle sınanabilir; 15 grup × 3 blok çoklu karşılaştırması içinde kanıtlanmış sayılmaz.

> Bu rapor `scripts/rqk_study.py` (+ `rqk_analysis.py`, `rqk_report.py`) tarafından üretildi; gösterge `app/rescan/rqk.py`. Canlı koda dokunulmadı.


## 2. Gösterge ve yöntem

**Gösterge (grafik hesabı, `frontend/app/charts/IndicatorPicker.tsx` → `SLING_SHOT_ENTRY`).** Varsayılan h=8, r=2, smoothColors=false. yhat(i) = Σ_{k<min(h,i+1)} close[i−k]·w(k) / Σ w(k), w(k) = (1 + k²/(h²·2r))^(−r); toplam yalnız SON h muma uzanır
(özgün jdehorty betiği ~25+ bar toplar; uygulama kesiyor). Renk: yeşil ⇔ yhat(i−1) < yhat(i) veya (yhat(i−2) > yhat(i−1) ve yhat(i−1) > yhat(i) DEĞİL). AL = kırmızı→yeşil renk değişimi.
Port: `app/rescan/rqk.py` (vektörel numpy; toplama sırası uygulamayla aynı olduğundan bit-düzeyinde aynı — düz serilerdeki eşitlik dalları dâhil). Parite testi: `tests/test_rqk.py` (TS mantığının birebir JS kopyası
`work/rqk/rqk_calc.js` Node ile çalıştırıldı → `tests/fixtures/rqk_parity.json`; 5 seri × 7 parametre kümesi, > 1000 yhat/renk karşılaştırması; Node varsa test yeniden çalıştırır). Varyant B = kanonik: pencere 25 bar, bant genişliği h, renk yhat(i−1) < yhat(i).

> **Önemli not (kullanıcı varsayımı):** Grafikte bu göstergenin B/S okları renk değişiminden ÇIKMIYOR. `page.tsx` `registryId === "sling_shot"` için `signals.ts → slingShotSignals`'ı çağırıyor; bu fonksiyon çekirdekle ilgisiz bir
> **EMA50/EMA11 SlingShot** mantığı (EMA11 > EMA50 iken önceki kapanış ≤ EMA11 ve yeni kapanış > EMA11 ⇒ AL; alternasyonlu). Aşağıdaki analizler çekirdeğin RENK DEĞİŞİMİNİ ölçüyor (soruda istenen); grafikteki oklar ayrı bir mantık.

**Veri.** `historical_candles` 1m/5m/15m, 19 Tem → 17 Eki 2026 (306 sembol; 1m yalnız 304 likit sembol). Çekirdek HAM mumlar üzerinde (uygulamanın gördüğü sıra; boşluk doldurulmadı — DB 0 hacimli düz mumları da tutuyor, eksik satır çok az).
Olaylar: `work/pattern90/events.csv` (tanım docs/CIKIS_DESEN_ANALIZI_90G_2026-10-17.md: 60 dk içinde ≥ +%4, ≥ %70 yeşil mum, geri çekilme ≤ %1,5, tek mum ≤ %2,5, 24 sa quote ≥ 5M TRY; t0 = koşunun ilk mumu).
HA: `work/rescan_90g_nogate.jsonl` canlı-benzeri alt küme (rank ≤ 10, aşırı alımda değil; 20 343 bölüm, ≈ 226/gün). Sonuç araçları: `pattern_study.forward_outcomes` (5m ızgara; 1m sinyaller için aynı kurallar 1 dk ızgarada:
karardan 5. dk … 60. dk, ≥ 45/55 gerçek mum) ve 90 günlük çalışmanın `NullEngine` (null3) şans tabanı. Bloklar (yürüyen-ileri): **B1** 20 Tem–18 Ağu, **B2** 19 Ağu–17 Eyl, **B3** 18 Eyl–16 Eki.


## 3. Analiz 1 — Olay zamanlaması: çekirdek YÜKSELİŞTEN ÖNCE mi, SONRA mı yeşile dönüyor?

Olay = 90 günlük çalışmadaki kümesiz birincil olay (**4.552**; t0 = koşunun ilk mumunun açılışı = bir önceki 5m mumun kapanışı). Taban = aynı sembol + aynı gün, olay başına rastgele ≤ 40 geçerli an (**182.003** an; olay koşusu dışında). Durum = t anında KAPANMIŞ son çekirdek barının rengi (yeşil=boğa). Uygulama varsayılanları: varyant A, h=8, r=2. 'AL dönüşü' = kırmızı→yeşil renk değişimi, dönüş zamanı = o barın kapanışı. P0 = t0'daki fiyat (olayda koşudan önceki kapanış). **Dikkat:** olay tanımı geleceğe bakar (ilk 5m mum yeşil ve P0'ın üstünde, koşu P0'ın altına inmez, 60 dk'da ≥ %4), bu yüzden t0'dan SONRAKİ pencerelerdeki (t0+5 …) oranlar kısmen tanım gereğidir; t0 ve ÖNCESİ (t0−15 … t0) ölçümleri nedensel ve 'önceden işaret veriyor mu?' sorusunun asıl cevabıdır. HA ile karşılaştırma aynı pencerede yapıldığından adildir.

### 1m çekirdek (A, h=8, r=2)

| ölçü | olay | taban (eşleşmiş rastgele an) |
|---|---|---|
| yeşil — t0−15 dk | %48,3 | %47,0 |
| yeşil — t0−10 dk | %45,3 | %46,3 |
| yeşil — t0−5 dk | %37,7 | %45,9 |
| **yeşil — t0** | %22,5 | %45,6 |
| yeşil — t0+5 dk (yükseliş başladı) | %84,2 | %45,3 |
| yeşil — t0+10 dk | %89,7 | %45,8 |
| yeşil — t0+15 dk | %80,8 | %46,0 |
| yeşil — t0+30 dk | %74,6 | %47,2 |
| t0'dan ÖNCEKİ 15 dk içinde AL dönüşü var | %72,1 | %78,4 |
| t0'dan SONRAKİ 15 dk içinde AL dönüşü | %88,8 | %79,1 |
| t0'dan sonraki 30 dk içinde AL dönüşü | %96,7 | %97,1 |
| medyan: son AL dönüşü kaç dk ÖNCE (t0'a göre) | 9 | 7 |
| medyan: sonraki AL dönüşü kaç dk SONRA | 4 | 8 |
| medyan: sonraki AL dönüşünde fiyat (P0'a göre %) | +0,59 | +0,04 |

AUC (olay ↔ taban; 0,5 = ayırt etmez; < 0,5 olay daha az / > 0,5 olay daha çok):

| özellik | tümü | B1 | B2 | B3 |
|---|---|---|---|---|
| t0'da yeşil (ikili) | 0,384 | 0,385 | 0,375 | 0,392 |
| işaretli durum yaşı (yeşil +, kırmızı −) | 0,367 | 0,367 | 0,356 | 0,377 |
| t0'da yeni yeşil (≤ 3 bar) | 0,463 | 0,461 | 0,462 | 0,467 |
| t0−15…t0 arası AL dönüşü | 0,468 | 0,472 | 0,465 | 0,469 |
| t0+15'te yeşil (yükseliş içinde) | 0,674 | 0,689 | 0,666 | 0,672 |
| t0…t0+15 arası AL dönüşü | 0,548 | 0,543 | 0,551 | 0,549 |
| t0…t0+30 arası AL dönüşü | 0,498 | 0,496 | 0,501 | 0,496 |

Gecikme histogramı — SON AL dönüşü t0'dan kaç dk önce (sol) ve SONRAKİ AL dönüşü t0'dan kaç dk sonra (sağ):

| dk önce | olay | taban |
|---|---|---|
| 0–5 | %27,3 | %35,8 |
| 5–10 | %25,7 | %25,7 |
| 10–15 | %19,1 | %17,0 |
| 15–30 | %23,9 | %18,3 |
| 30–60 | %3,9 | %3,1 |
| >60 | %0,1 | %0,2 |
| hiç yok | %0,0 | %0,0 |

| dk sonra | olay | taban |
|---|---|---|
| 0–5 | %72,5 | %35,7 |
| 5–10 | %12,8 | %26,0 |
| 10–15 | %3,5 | %17,4 |
| 15–30 | %7,8 | %18,0 |
| 30–60 | %3,1 | %2,7 |
| >60 | %0,3 | %0,2 |
| hiç yok | %0,0 | %0,0 |

### 5m çekirdek (A, h=8, r=2)

| ölçü | olay | taban (eşleşmiş rastgele an) |
|---|---|---|
| yeşil — t0−15 dk | %53,5 | %50,4 |
| yeşil — t0−10 dk | %52,0 | %49,8 |
| yeşil — t0−5 dk | %47,2 | %49,4 |
| **yeşil — t0** | %37,4 | %49,0 |
| yeşil — t0+5 dk (yükseliş başladı) | %59,0 | %48,3 |
| yeşil — t0+10 dk | %70,9 | %47,8 |
| yeşil — t0+15 dk | %80,3 | %47,5 |
| yeşil — t0+30 dk | %95,0 | %48,2 |
| t0'dan ÖNCEKİ 15 dk içinde AL dönüşü var | %17,0 | %23,9 |
| t0'dan SONRAKİ 15 dk içinde AL dönüşü | %48,8 | %24,3 |
| t0'dan sonraki 30 dk içinde AL dönüşü | %64,4 | %44,5 |
| medyan: son AL dönüşü kaç dk ÖNCE (t0'a göre) | 40 | 35 |
| medyan: sonraki AL dönüşü kaç dk SONRA | 20 | 35 |
| medyan: sonraki AL dönüşünde fiyat (P0'a göre %) | +1,84 | +0,17 |

AUC (olay ↔ taban; 0,5 = ayırt etmez; < 0,5 olay daha az / > 0,5 olay daha çok):

| özellik | tümü | B1 | B2 | B3 |
|---|---|---|---|---|
| t0'da yeşil (ikili) | 0,442 | 0,445 | 0,431 | 0,451 |
| işaretli durum yaşı (yeşil +, kırmızı −) | 0,468 | 0,466 | 0,466 | 0,470 |
| t0'da yeni yeşil (≤ 3 bar) | 0,458 | 0,459 | 0,450 | 0,464 |
| t0−15…t0 arası AL dönüşü | 0,465 | 0,461 | 0,464 | 0,469 |
| t0+15'te yeşil (yükseliş içinde) | 0,664 | 0,672 | 0,656 | 0,665 |
| t0…t0+15 arası AL dönüşü | 0,622 | 0,623 | 0,628 | 0,617 |
| t0…t0+30 arası AL dönüşü | 0,599 | 0,600 | 0,606 | 0,594 |

Gecikme histogramı — SON AL dönüşü t0'dan kaç dk önce (sol) ve SONRAKİ AL dönüşü t0'dan kaç dk sonra (sağ):

| dk önce | olay | taban |
|---|---|---|
| 0–5 | %3,9 | %8,3 |
| 5–10 | %5,8 | %8,2 |
| 10–15 | %7,3 | %7,5 |
| 15–30 | %19,9 | %18,8 |
| 30–60 | %30,1 | %26,9 |
| >60 | %33,1 | %30,3 |
| hiç yok | %0,0 | %0,0 |

| dk sonra | olay | taban |
|---|---|---|
| 0–5 | %23,0 | %8,2 |
| 5–10 | %15,2 | %8,4 |
| 10–15 | %10,6 | %7,7 |
| 15–30 | %15,6 | %20,2 |
| 30–60 | %4,0 | %28,3 |
| >60 | %31,6 | %27,2 |
| hiç yok | %0,0 | %0,0 |

### 15m çekirdek (A, h=8, r=2)

| ölçü | olay | taban (eşleşmiş rastgele an) |
|---|---|---|
| yeşil — t0−15 dk | %57,3 | %53,0 |
| yeşil — t0−10 dk | %57,4 | %52,8 |
| yeşil — t0−5 dk | %56,4 | %52,6 |
| **yeşil — t0** | %54,1 | %52,2 |
| yeşil — t0+5 dk (yükseliş başladı) | %54,8 | %51,8 |
| yeşil — t0+10 dk | %58,7 | %51,5 |
| yeşil — t0+15 dk | %66,5 | %51,1 |
| yeşil — t0+30 dk | %81,1 | %50,5 |
| t0'dan ÖNCEKİ 15 dk içinde AL dönüşü var | %6,1 | %7,8 |
| t0'dan SONRAKİ 15 dk içinde AL dönüşü | %16,0 | %7,8 |
| t0'dan sonraki 30 dk içinde AL dönüşü | %31,8 | %16,0 |
| medyan: son AL dönüşü kaç dk ÖNCE (t0'a göre) | 115 | 110 |
| medyan: sonraki AL dönüşü kaç dk SONRA | 110 | 110 |
| medyan: sonraki AL dönüşünde fiyat (P0'a göre %) | +2,90 | +0,34 |

AUC (olay ↔ taban; 0,5 = ayırt etmez; < 0,5 olay daha az / > 0,5 olay daha çok):

| özellik | tümü | B1 | B2 | B3 |
|---|---|---|---|---|
| t0'da yeşil (ikili) | 0,510 | 0,502 | 0,517 | 0,508 |
| işaretli durum yaşı (yeşil +, kırmızı −) | 0,524 | 0,514 | 0,533 | 0,523 |
| t0'da yeni yeşil (≤ 3 bar) | 0,492 | 0,495 | 0,490 | 0,492 |
| t0−15…t0 arası AL dönüşü | 0,492 | 0,492 | 0,491 | 0,492 |
| t0+15'te yeşil (yükseliş içinde) | 0,577 | 0,576 | 0,584 | 0,571 |
| t0…t0+15 arası AL dönüşü | 0,541 | 0,550 | 0,539 | 0,537 |
| t0…t0+30 arası AL dönüşü | 0,579 | 0,589 | 0,572 | 0,579 |

Gecikme histogramı — SON AL dönüşü t0'dan kaç dk önce (sol) ve SONRAKİ AL dönüşü t0'dan kaç dk sonra (sağ):

| dk önce | olay | taban |
|---|---|---|
| 0–5 | %1,4 | %2,6 |
| 5–10 | %1,9 | %2,6 |
| 10–15 | %2,8 | %2,6 |
| 15–30 | %8,3 | %8,0 |
| 30–60 | %14,5 | %14,1 |
| >60 | %71,1 | %70,1 |
| hiç yok | %0,0 | %0,0 |

| dk sonra | olay | taban |
|---|---|---|
| 0–5 | %2,8 | %2,6 |
| 5–10 | %5,0 | %2,6 |
| 10–15 | %8,2 | %2,6 |
| 15–30 | %15,9 | %8,2 |
| 30–60 | %13,0 | %14,8 |
| >60 | %55,1 | %69,1 |
| hiç yok | %0,1 | %0,1 |

### Hız Avcısı (HA) ile aynı ölçüt

| sinyal penceresi | olay | taban | olay/taban |
|---|---|---|---|
| HA adayı t0…t0+15 dk içinde | %28,8 | %12,7 | 2,3× |
| HA adayı t0…t0+30 dk içinde | %49,8 | %19,0 | 2,6× |
| 1m çekirdek AL dönüşü t0…t0+15 dk | %88,8 | %79,1 | 1,1× |
| 1m çekirdek AL dönüşü t0…t0+30 dk | %96,7 | %97,1 | 1,0× |
| 5m çekirdek AL dönüşü t0…t0+15 dk | %48,8 | %24,3 | 2,0× |
| 5m çekirdek AL dönüşü t0…t0+30 dk | %64,4 | %44,5 | 1,4× |
| 15m çekirdek AL dönüşü t0…t0+15 dk | %16,0 | %7,8 | 2,0× |
| 15m çekirdek AL dönüşü t0…t0+30 dk | %31,8 | %16,0 | 2,0× |

HA'nın ilk adayı (30 dk içinde olanlarda) medyan **15 dk** sonra, o andaki fiyat P0'ın medyan **+2,48%** üstünde (tabanda +0,81%). 5m çekirdek AL dönüşü için aynı sayı: medyan 20 dk, +1,84%.

Aynı olayda 30 dk içinde HA adayı VE çekirdek AL dönüşü varsa kim önce (HA−RQK > 0 ⇒ RQK önce); birleşim yakalama oranı:

| tf | ikisi de olan olay | RQK önce | aynı 5 dk | medyan HA−RQK (dk) | olayda RQK ≤30 dk | olayda RQK∪HA ≤30 dk | tabanda RQK∪HA ≤30 dk |
|---|---|---|---|---|---|---|---|
| 1m | 2.193 | %86,9 | %2,1 | 12 | %96,7 | %98,3 | %97,6 |
| 5m | 1.441 | %62,5 | %20,5 | 5 | %64,4 | %82,6 | %54,7 |
| 15m | 679 | %38,1 | %19,3 | 0 | %31,8 | %66,7 | %31,8 |

Not: 1m çekirdek her ~5 dk'da bir döndüğü için 'AL dönüşü ≤ 30 dk' neredeyse her an doğru (taban %97); 1m için bu tablo bilgi taşımıyor.

Ek — 24 kombinasyonun zamanlama özeti (AUC'ler tüm olaylarda):

| kombinasyon | yeşil t0 (olay) | yeşil t0 (taban) | AUC yeşil t0 | AUC dönüş t0−15…t0 | AUC dönüş t0…t0+15 | dönüş ≤15 dk sonra (olay) | (taban) |
|---|---|---|---|---|---|---|---|
| 1m_A_h8_r2 | %22,5 | %45,6 | 0,384 | 0,468 | 0,548 | %88,8 | %79,1 |
| 1m_A_h16_r2 | %25,1 | %47,1 | 0,390 | 0,464 | 0,619 | %81,9 | %58,1 |
| 1m_A_h25_r2 | %29,9 | %47,8 | 0,410 | 0,473 | 0,613 | %69,6 | %46,9 |
| 5m_A_h8_r1 | %37,6 | %49,0 | 0,443 | 0,465 | 0,621 | %48,6 | %24,5 |
| 5m_A_h8_r2 | %37,4 | %49,0 | 0,442 | 0,465 | 0,622 | %48,8 | %24,3 |
| 5m_A_h8_r8 | %37,2 | %49,0 | 0,441 | 0,464 | 0,623 | %48,9 | %24,2 |
| 5m_A_h16_r1 | %44,4 | %50,6 | 0,469 | 0,479 | 0,587 | %34,3 | %17,0 |
| 5m_A_h16_r2 | %44,4 | %50,6 | 0,469 | 0,479 | 0,588 | %34,4 | %16,9 |
| 5m_A_h16_r8 | %44,4 | %50,6 | 0,469 | 0,479 | 0,588 | %34,4 | %16,7 |
| 5m_A_h25_r1 | %49,2 | %52,0 | 0,486 | 0,481 | 0,569 | %27,2 | %13,3 |
| 5m_A_h25_r2 | %49,1 | %52,0 | 0,485 | 0,482 | 0,571 | %27,4 | %13,3 |
| 5m_A_h25_r8 | %49,0 | %51,9 | 0,485 | 0,481 | 0,571 | %27,4 | %13,2 |
| 5m_B_h8_r1 | %42,9 | %50,1 | 0,464 | 0,476 | 0,604 | %36,8 | %16,1 |
| 5m_B_h8_r2 | %41,5 | %49,8 | 0,459 | 0,473 | 0,612 | %38,9 | %16,5 |
| 5m_B_h8_r8 | %40,7 | %49,6 | 0,455 | 0,470 | 0,616 | %40,3 | %17,1 |
| 5m_B_h16_r1 | %47,2 | %51,4 | 0,479 | 0,479 | 0,582 | %29,8 | %13,5 |
| 5m_B_h16_r2 | %47,1 | %51,3 | 0,479 | 0,479 | 0,582 | %29,8 | %13,3 |
| 5m_B_h16_r8 | %46,8 | %51,2 | 0,478 | 0,478 | 0,584 | %30,0 | %13,2 |
| 5m_B_h25_r1 | %49,2 | %52,0 | 0,486 | 0,482 | 0,569 | %27,2 | %13,3 |
| 5m_B_h25_r2 | %49,1 | %52,0 | 0,485 | 0,482 | 0,571 | %27,4 | %13,2 |
| 5m_B_h25_r8 | %49,0 | %51,9 | 0,485 | 0,481 | 0,571 | %27,4 | %13,2 |
| 15m_A_h8_r2 | %54,1 | %52,2 | 0,510 | 0,492 | 0,541 | %16,0 | %7,8 |
| 15m_A_h16_r2 | %58,3 | %55,4 | 0,515 | 0,494 | 0,533 | %11,8 | %5,2 |
| 15m_A_h25_r2 | %61,9 | %58,1 | 0,519 | 0,495 | 0,528 | %9,7 | %4,1 |


## 4. Analiz 2 — RQK dönüşü giriş sinyali olarak

Sinyal = çekirdeğin **kırmızı→yeşil** dönüşü (bar kapanışında), 24 sa quote ≥ 5M TRY. Sonuç ölçüsü 90 günlük çalışmadakiyle aynı: TP 1,5 / SL −3 / maliyet 0,225 / 60 dk (pencere karardan 5 dk sonra başlar); trailing = tetik %1,0 / iz %0,8. Şans farkı = isabet − null3 (aynı sembol, ±1 sa dilimi, benzer 30 dk aralık ve getiri; 3 tohum × 3000 sinyal örneği; ± = gün-kümeli %95). Her sembolde 60 dk soğuma (filtreden SONRA). 'olay içi' = sinyal anı bir olayın [t0−10 dk, bitiş] penceresinde; 'kat' = bunun rastgele geçerli ana oranı (HA ≈ 13–14×).

Rastgele geçerli anın olay penceresinde olma olasılığı (taban): B1 %0,85; B2 %1,10; B3 %1,20.

### 5m dönüşleri (A, h=8, r=2)

| yapılandırma | blok | ham sinyal/gün | soğumalı/gün | hit60@1,5 | hit60@2,0 | net60 | trailing net | şans farkı (pp) | net şans farkı | olay içi/öncesi pay | olay içi kat |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 5m · yalnız likidite | B1 | 4224 | 2449 | %10,8 | %6,8 | -0,267 | -0,222 | +0,6 ± 1,0 | -0,007 | %0,85 | 1,0× |
| 5m · yalnız likidite | B2 | 4939 | 2927 | %13,4 | %7,9 | -0,245 | -0,200 | +1,7 ± 1,6 | -0,001 | %1,02 | 0,9× |
| 5m · yalnız likidite | B3 | 5417 | 3177 | %13,7 | %8,3 | -0,261 | -0,206 | +2,3 ± 1,3 | -0,012 | %1,13 | 0,9× |
| 5m · + fiyat > EMA99 (5m) | B1 | 2105 | 1289 | %12,5 | %8,3 | -0,307 | -0,253 | +1,0 ± 1,1 | -0,057 | %1,08 | 1,3× |
| 5m · + fiyat > EMA99 (5m) | B2 | 2637 | 1629 | %15,2 | %9,5 | -0,269 | -0,214 | +3,2 ± 1,8 | -0,046 | %1,38 | 1,3× |
| 5m · + fiyat > EMA99 (5m) | B3 | 2924 | 1799 | %14,9 | %9,4 | -0,283 | -0,219 | +2,4 ± 1,3 | -0,049 | %1,45 | 1,2× |
| 5m · + 15m çekirdek yeşil | B1 | 1747 | 1140 | %12,3 | %8,0 | -0,293 | -0,239 | +1,1 ± 1,0 | -0,062 | %0,91 | 1,1× |
| 5m · + 15m çekirdek yeşil | B2 | 2148 | 1415 | %14,8 | %9,1 | -0,261 | -0,208 | +3,5 ± 2,0 | -0,014 | %1,21 | 1,1× |
| 5m · + 15m çekirdek yeşil | B3 | 2274 | 1505 | %14,8 | %9,2 | -0,269 | -0,212 | +2,7 ± 1,3 | -0,033 | %1,24 | 1,0× |
| 5m · + ikisi | B1 | 1325 | 866 | %13,4 | %8,8 | -0,305 | -0,249 | +1,7 ± 1,2 | -0,065 | %1,03 | 1,2× |
| 5m · + ikisi | B2 | 1668 | 1103 | %16,1 | %10,1 | -0,271 | -0,211 | +3,4 ± 2,1 | -0,040 | %1,36 | 1,2× |
| 5m · + ikisi | B3 | 1803 | 1198 | %15,4 | %9,8 | -0,294 | -0,230 | +2,5 ± 1,5 | -0,053 | %1,40 | 1,2× |
| **HA referansı** | B1 | — | 204 | %48,5 | %40,8 | -0,428 | +0,028 | +3,5 ± 1,7 | -0,108 | %12,14 | 14,3× |
| **HA referansı** | B2 | — | 227 | %47,0 | %38,1 | -0,357 | -0,047 | +4,6 ± 2,5 | -0,055 | %15,37 | 14,0× |
| **HA referansı** | B3 | — | 256 | %47,8 | %38,8 | -0,410 | -0,056 | +5,4 ± 1,9 | -0,098 | %15,30 | 12,7× |

### 1m dönüşleri (A, h=8, r=2)

| yapılandırma | blok | ham sinyal/gün | soğumalı/gün | hit60@1,5 | hit60@2,0 | net60 | trailing net | şans farkı (pp) | net şans farkı | olay içi/öncesi pay | olay içi kat |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1m · yalnız likidite | B1 | 16836 | 3517 | %11,5 | %7,3 | -0,241 | -0,207 | -0,5 ± 1,1 | -0,045 | %0,76 | 0,9× |
| 1m · yalnız likidite | B2 | 20443 | 4243 | %14,4 | %8,6 | -0,213 | -0,175 | +1,8 ± 1,6 | -0,001 | %0,94 | 0,9× |
| 1m · yalnız likidite | B3 | 22324 | 4660 | %14,7 | %8,8 | -0,225 | -0,181 | +1,7 ± 1,4 | -0,027 | %1,02 | 0,9× |
| 1m · + fiyat > EMA99 (5m) | B1 | 8026 | 1970 | %13,1 | %8,7 | -0,290 | -0,250 | +0,2 ± 1,2 | -0,078 | %1,12 | 1,3× |
| 1m · + fiyat > EMA99 (5m) | B2 | 10573 | 2528 | %15,7 | %9,8 | -0,257 | -0,211 | +2,2 ± 1,9 | -0,017 | %1,42 | 1,3× |
| 1m · + fiyat > EMA99 (5m) | B3 | 11648 | 2800 | %15,8 | %10,0 | -0,251 | -0,197 | +2,3 ± 1,5 | -0,021 | %1,55 | 1,3× |
| 1m · + 15m çekirdek yeşil | B1 | 7683 | 2044 | %12,7 | %8,4 | -0,266 | -0,225 | -0,3 ± 1,1 | -0,038 | %1,05 | 1,2× |
| 1m · + 15m çekirdek yeşil | B2 | 9890 | 2564 | %15,3 | %9,5 | -0,243 | -0,201 | +1,7 ± 1,9 | -0,033 | %1,39 | 1,3× |
| 1m · + 15m çekirdek yeşil | B3 | 10670 | 2802 | %15,6 | %9,8 | -0,241 | -0,190 | +2,0 ± 1,5 | -0,002 | %1,52 | 1,3× |
| 1m · + ikisi | B1 | 5824 | 1551 | %13,9 | %9,3 | -0,288 | -0,243 | -0,2 ± 1,2 | -0,058 | %1,28 | 1,5× |
| 1m · + ikisi | B2 | 7779 | 2026 | %16,4 | %10,4 | -0,259 | -0,211 | +2,5 ± 1,7 | -0,020 | %1,67 | 1,5× |
| 1m · + ikisi | B3 | 8446 | 2230 | %16,5 | %10,6 | -0,257 | -0,200 | +2,8 ± 1,5 | -0,008 | %1,82 | 1,5× |


## 5. Analiz 3 — RQK, Hız Avcısı adayları üzerinde filtre olarak

Hız Avcısı (HA) adayı = `rescan_90g_nogate` rank ≤ 10, aşırı alımda değil, 60 dk bölümlenmiş (**20.343** bölüm; bölüm başına ilk aday). Aday anında KAPANMIŞ son 5m ve 15m çekirdek barının durumu (A, h=8, r=2): yeşil/kırmızı; 'yeni' = renk en çok 3 bar önce değişti, 'olgun' = daha eski. Metrikler HA'nın kendi bloklarıyla aynı: hit60@1,5, net60 (TP 1,5/SL −3/maliyet 0,225), trailing, şans farkı (null3; 3 tohum × 3000). **Δ isabet** = grup − tümleyeni (gün-kümeli bootstrap %95 aralık); aralık 0'ı içermiyorsa ayırt edici.

| grup (aday anında çekirdek durumu) | blok | n | pay | hit60@1,5 | net60 | trailing net | şans farkı (pp) | Δ isabet vs tümleyen (pp) [%95] |
|---|---|---|---|---|---|---|---|---|
| **TÜM (HA)** | B1 | 6.110 | %100 | %48,5 | -0,428 | +0,028 | +3,5 ± 1,7 | — |
| **TÜM (HA)** | B2 | 6.797 | %100 | %47,0 | -0,357 | -0,047 | +4,6 ± 2,5 | — |
| **TÜM (HA)** | B3 | 7.436 | %100 | %47,8 | -0,410 | -0,056 | +5,4 ± 1,9 | — |
| 5m yeşil | B1 | 4.774 | %78 | %47,2 | -0,468 | -0,010 | +3,4 ± 1,8 | -5,9 [-9,5; -2,1] |
| 5m yeşil | B2 | 5.388 | %79 | %46,1 | -0,382 | -0,063 | +4,8 ± 2,2 | -4,3 [-7,6; -0,7] |
| 5m yeşil | B3 | 5.872 | %79 | %47,6 | -0,428 | -0,058 | +5,7 ± 1,5 | -1,0 [-4,5; +2,0] |
| 5m kırmızı | B1 | 1.336 | %22 | %53,1 | -0,286 | +0,162 | +5,9 ± 2,9 | +5,9 [+2,1; +9,5] |
| 5m kırmızı | B2 | 1.409 | %21 | %50,4 | -0,258 | +0,015 | +7,1 ± 3,5 | +4,3 [+0,7; +7,6] |
| 5m kırmızı | B3 | 1.564 | %21 | %48,6 | -0,340 | -0,047 | +5,8 ± 3,3 | +1,0 [-2,0; +4,5] |
| 5m yeşil, yeni (≤3 bar) | B1 | 2.561 | %42 | %46,3 | -0,458 | -0,022 | +4,0 ± 2,0 | -3,9 [-6,8; -0,9] |
| 5m yeşil, yeni (≤3 bar) | B2 | 2.824 | %42 | %45,3 | -0,331 | -0,020 | +4,4 ± 1,9 | -3,0 [-5,8; -0,3] |
| 5m yeşil, yeni (≤3 bar) | B3 | 3.145 | %42 | %46,5 | -0,407 | -0,038 | +5,7 ± 2,0 | -2,2 [-5,1; +0,6] |
| 5m yeşil, olgun (>3 bar) | B1 | 2.213 | %36 | %48,4 | -0,479 | +0,004 | +2,7 ± 1,9 | -0,3 [-2,6; +1,8] |
| 5m yeşil, olgun (>3 bar) | B2 | 2.564 | %38 | %47,1 | -0,439 | -0,112 | +4,2 ± 2,9 | +0,1 [-2,7; +2,6] |
| 5m yeşil, olgun (>3 bar) | B3 | 2.727 | %37 | %48,8 | -0,452 | -0,081 | +5,6 ± 2,1 | +1,6 [-0,9; +4,5] |
| 5m kırmızı, yeni (≤3 bar) | B1 | 684 | %11 | %50,0 | -0,191 | +0,222 | +6,9 ± 3,6 | +1,7 [-2,3; +5,7] |
| 5m kırmızı, yeni (≤3 bar) | B2 | 674 | %10 | %50,6 | -0,207 | +0,050 | +9,9 ± 4,5 | +4,0 [-0,9; +8,5] |
| 5m kırmızı, yeni (≤3 bar) | B3 | 707 | %10 | %46,3 | -0,367 | -0,042 | +6,3 ± 4,3 | -1,7 [-5,9; +2,5] |
| 5m kırmızı, olgun (>3 bar) | B1 | 652 | %11 | %56,4 | -0,386 | +0,100 | +4,8 ± 4,0 | +8,9 [+4,4; +13,1] |
| 5m kırmızı, olgun (>3 bar) | B2 | 735 | %11 | %50,2 | -0,306 | -0,017 | +4,1 ± 4,0 | +3,6 [+0,5; +6,6] |
| 5m kırmızı, olgun (>3 bar) | B3 | 857 | %12 | %50,5 | -0,318 | -0,051 | +5,4 ± 3,9 | +3,1 [-0,4; +6,7] |
| 15m yeşil | B1 | 4.427 | %72 | %48,0 | -0,434 | +0,010 | +3,4 ± 1,8 | -1,8 [-4,6; +1,2] |
| 15m yeşil | B2 | 4.954 | %73 | %47,8 | -0,364 | -0,026 | +5,3 ± 2,3 | +2,8 [-0,4; +6,2] |
| 15m yeşil | B3 | 5.363 | %72 | %48,2 | -0,420 | -0,034 | +6,2 ± 1,8 | +1,6 [-0,9; +4,0] |
| 15m kırmızı | B1 | 1.683 | %28 | %49,9 | -0,411 | +0,074 | +4,3 ± 2,3 | +1,8 [-1,2; +4,6] |
| 15m kırmızı | B2 | 1.843 | %27 | %45,0 | -0,338 | -0,105 | +2,9 ± 2,9 | -2,8 [-6,2; +0,4] |
| 15m kırmızı | B3 | 2.073 | %28 | %46,6 | -0,383 | -0,112 | +5,0 ± 2,2 | -1,6 [-4,0; +0,9] |
| 15m yeşil, yeni (≤3 bar) | B1 | 1.886 | %31 | %46,2 | -0,403 | -0,021 | +2,8 ± 1,8 | -3,4 [-5,8; -1,1] |
| 15m yeşil, yeni (≤3 bar) | B2 | 2.015 | %30 | %43,4 | -0,406 | -0,075 | +2,0 ± 2,3 | -5,1 [-8,1; -2,5] |
| 15m yeşil, yeni (≤3 bar) | B3 | 2.332 | %31 | %44,9 | -0,428 | -0,016 | +3,2 ± 2,0 | -4,2 [-6,5; -1,8] |
| 15m yeşil, olgun (>3 bar) | B1 | 2.541 | %42 | %49,4 | -0,458 | +0,034 | +4,4 ± 1,7 | +1,5 [-0,5; +3,4] |
| 15m yeşil, olgun (>3 bar) | B2 | 2.939 | %43 | %50,8 | -0,335 | +0,008 | +8,2 ± 2,6 | +6,6 [+3,4; +9,8] |
| 15m yeşil, olgun (>3 bar) | B3 | 3.031 | %41 | %50,8 | -0,414 | -0,047 | +7,8 ± 1,7 | +5,0 [+3,0; +7,0] |
| 5m yeşil + 15m yeşil | B1 | 3.861 | %63 | %47,1 | -0,460 | -0,023 | +2,8 ± 1,7 | -3,8 [-6,7; -0,6] |
| 5m yeşil + 15m yeşil | B2 | 4.354 | %64 | %46,9 | -0,378 | -0,039 | +4,7 ± 2,1 | -0,4 [-3,0; +2,3] |
| 5m yeşil + 15m yeşil | B3 | 4.701 | %63 | %48,0 | -0,421 | -0,044 | +6,0 ± 1,8 | +0,5 [-2,1; +3,0] |
| 5m yeşil + 15m kırmızı | B1 | 913 | %15 | %47,6 | -0,498 | +0,045 | +4,3 ± 3,5 | -1,0 [-4,6; +2,7] |
| 5m yeşil + 15m kırmızı | B2 | 1.034 | %15 | %43,0 | -0,400 | -0,168 | +1,7 ± 2,9 | -4,7 [-8,2; -1,5] |
| 5m yeşil + 15m kırmızı | B3 | 1.171 | %16 | %46,0 | -0,457 | -0,112 | +4,9 ± 2,7 | -2,1 [-4,6; +0,4] |
| 5m kırmızı + 15m yeşil | B1 | 566 | %9 | %54,1 | -0,254 | +0,235 | +7,7 ± 4,2 | +6,1 [+1,5; +10,5] |
| 5m kırmızı + 15m yeşil | B2 | 600 | %9 | %54,3 | -0,259 | +0,069 | +10,3 ± 4,5 | +8,0 [+3,2; +12,8] |
| 5m kırmızı + 15m yeşil | B3 | 662 | %9 | %50,2 | -0,413 | +0,041 | +6,9 ± 4,0 | +2,6 [-1,2; +6,8] |
| 5m kırmızı + 15m kırmızı | B1 | 770 | %13 | %52,5 | -0,309 | +0,109 | +4,5 ± 3,4 | +4,5 [+0,5; +8,4] |
| 5m kırmızı + 15m kırmızı | B2 | 809 | %12 | %47,5 | -0,258 | -0,026 | +4,7 ± 5,2 | +0,5 [-4,5; +5,4] |
| 5m kırmızı + 15m kırmızı | B3 | 902 | %12 | %47,5 | -0,287 | -0,112 | +5,1 ± 3,7 | -0,4 [-3,8; +3,2] |


### Kontrol — çekirdek durumu HA'ya ÖZGÜ bilgi mi, yoksa genel bir taban etkisi mi?

Çekirdek rengi her rastgele anda da kısa vadeli momentumu yansıtır; HA zaten momentum seçtiği için etkinin HA içinde azalması beklenir. Kontrol: her HA bölümü için AYNI sembol + AYNI günden ≤ 20 rastgele likit an (toplam 404.647) alındı; 'yeşil − tümleyeni' hit60@1,5 farkı bu anlarda ve HA'da ölçüldü. **Fark-farkı** = HA farkı − rastgele an farkı (gün-kümeli bootstrap %95): < 0 ise çekirdek rengi HA'nın üstüne bilgi eklemiyor (HA zaten içeriyor), > 0 ise HA'ya özgü katkı var. Not: rastgele anların kendi isabeti HA'ya yakın (≈ %40) çünkü HA'nın seçtiği sembol-günler zaten 'sıcak'.

| çekirdek | blok | yeşil payı HA | yeşil payı rastgele | HA hit yeşil | HA hit diğer | HA farkı | rastgele hit yeşil | rastgele hit diğer | rastgele fark | fark-farkı (pp) [%95] |
|---|---|---|---|---|---|---|---|---|---|---|
| 5m_A_h8_r2 | B1 | %78 | %50 | %47,2 | %53,1 | -5,9 pp | %43,3 | %40,0 | +3,4 pp | -9,3 [-12,8; -5,4] |
| 5m_A_h8_r2 | B2 | %79 | %52 | %46,1 | %50,4 | -4,3 pp | %41,1 | %38,2 | +2,9 pp | -7,1 [-10,9; -3,6] |
| 5m_A_h8_r2 | B3 | %79 | %52 | %47,6 | %48,6 | -1,0 pp | %42,1 | %39,8 | +2,3 pp | -3,3 [-6,4; -0,2] |
| 15m_A_h8_r2 | B1 | %72 | %52 | %48,0 | %49,9 | -1,8 pp | %45,3 | %37,5 | +7,8 pp | -9,6 [-12,0; -7,3] |
| 15m_A_h8_r2 | B2 | %73 | %55 | %47,8 | %45,0 | +2,8 pp | %42,6 | %36,1 | +6,5 pp | -3,7 [-6,6; -0,4] |
| 15m_A_h8_r2 | B3 | %72 | %54 | %48,2 | %46,6 | +1,6 pp | %43,5 | %38,0 | +5,6 pp | -4,0 [-6,6; -1,5] |
| 15m_A_h25_r2 | B1 | %78 | %57 | %48,9 | %47,3 | +1,6 pp | %46,2 | %35,4 | +10,8 pp | -9,3 [-11,8; -6,7] |
| 15m_A_h25_r2 | B2 | %80 | %60 | %48,0 | %43,2 | +4,8 pp | %44,0 | %33,0 | +11,0 pp | -6,2 [-9,2; -3,0] |
| 15m_A_h25_r2 | B3 | %78 | %61 | %48,8 | %44,2 | +4,6 pp | %44,6 | %35,4 | +9,1 pp | -4,5 [-6,9; -1,9] |
| 5m_A_h25_r2 | B1 | %76 | %52 | %47,9 | %50,4 | -2,5 pp | %45,3 | %37,6 | +7,7 pp | -10,1 [-13,1; -6,8] |
| 5m_A_h25_r2 | B2 | %77 | %55 | %47,6 | %45,1 | +2,4 pp | %42,5 | %36,3 | +6,2 pp | -3,7 [-6,8; -0,6] |
| 5m_A_h25_r2 | B3 | %77 | %54 | %48,1 | %46,9 | +1,2 pp | %43,4 | %38,2 | +5,2 pp | -4,0 [-6,5; -1,7] |


## 6. Analiz 4 — Parametreler ve yürüyen-ileri doğrulama

24 kombinasyon: 5m için varyant A ve B × h ∈ {8,16,25} × r ∈ {1,2,8} (18); 1m ve 15m için yalnız varyant A, r=2, h ∈ {8,16,25} (6). Tam ızgara (54) çalıştırılmadı (çoklu karşılaştırmayı sınırlamak için). **Seçim yalnız B1'de**, B2 ve B3 dokunulmadan test edildi. İki rol: (E) sade AL dönüşü sinyali (likidite + 60 dk soğuma; seçim ölçütü B1 şans farkı, sinyal/gün ≥ 20); (F) HA filtresi (5m/15m kombinasyonlar; ölçüt B1'de skor = şans farkı(yeşil) − şans farkı(kırmızı), her iki grupta n ≥ 300).

### (E) Sade AL dönüşü sinyali — 24 kombinasyon

| kombinasyon | sinyal/gün B1 | B2 | B3 | şans farkı B1 | B2 | B3 | net60 B1 | B2 | B3 |
|---|---|---|---|---|---|---|---|---|---|
| 1m_A_h8_r2 | 3517 | 4243 | 4660 | -0,5 pp | +1,8 pp | +1,7 pp | -0,241 | -0,213 | -0,225 |
| 1m_A_h16_r2 | 3228 | 3873 | 4245 | -0,8 pp | +1,4 pp | +1,3 pp | -0,250 | -0,219 | -0,237 |
| 1m_A_h25_r2 | 2973 | 3555 | 3896 | +0,6 pp | +2,1 pp | +1,5 pp | -0,257 | -0,223 | -0,254 |
| 5m_A_h8_r1 | 2452 | 2931 | 3179 | +0,4 pp | +1,8 pp | +1,9 pp | -0,267 | -0,245 | -0,261 |
| 5m_A_h8_r2 | 2449 | 2927 | 3177 | +0,6 pp | +1,7 pp | +2,3 pp | -0,267 | -0,245 | -0,261 |
| 5m_A_h8_r8 | 2447 | 2925 | 3175 | +0,7 pp | +2,2 pp | +2,0 pp | -0,267 | -0,246 | -0,261 |
| 5m_A_h16_r1 | 1835 | 2182 | 2353 | -0,4 pp | +0,8 pp | +1,6 pp | -0,282 | -0,262 | -0,256 |
| 5m_A_h16_r2 | 1830 | 2177 | 2346 | -0,7 pp | +1,0 pp | +1,7 pp | -0,282 | -0,262 | -0,256 |
| 5m_A_h16_r8 | 1825 | 2173 | 2341 | -0,7 pp | +0,9 pp | +1,8 pp | -0,282 | -0,263 | -0,257 |
| 5m_A_h25_r1 | 1521 | 1795 | 1930 | -0,8 pp | +0,2 pp | +0,3 pp | -0,282 | -0,253 | -0,255 |
| 5m_A_h25_r2 | 1516 | 1786 | 1923 | -0,7 pp | -0,1 pp | +0,6 pp | -0,283 | -0,254 | -0,256 |
| 5m_A_h25_r8 | 1511 | 1780 | 1917 | -0,5 pp | +0,4 pp | +1,7 pp | -0,283 | -0,255 | -0,257 |
| 5m_B_h8_r1 | 1756 | 2103 | 2270 | -0,6 pp | +0,3 pp | +0,4 pp | -0,287 | -0,268 | -0,276 |
| 5m_B_h8_r2 | 1807 | 2171 | 2341 | -0,4 pp | +0,9 pp | +1,6 pp | -0,285 | -0,270 | -0,278 |
| 5m_B_h8_r8 | 1869 | 2247 | 2421 | -0,7 pp | +0,6 pp | +0,6 pp | -0,289 | -0,268 | -0,277 |
| 5m_B_h16_r1 | 1541 | 1821 | 1958 | -0,4 pp | +0,2 pp | +1,1 pp | -0,289 | -0,256 | -0,260 |
| 5m_B_h16_r2 | 1534 | 1816 | 1955 | -1,1 pp | +0,7 pp | +0,7 pp | -0,289 | -0,256 | -0,261 |
| 5m_B_h16_r8 | 1528 | 1810 | 1949 | -1,2 pp | +0,3 pp | +0,7 pp | -0,290 | -0,259 | -0,262 |
| 5m_B_h25_r1 | 1517 | 1793 | 1928 | -0,6 pp | +0,8 pp | +0,6 pp | -0,283 | -0,253 | -0,255 |
| 5m_B_h25_r2 | 1512 | 1784 | 1921 | -0,8 pp | +0,3 pp | +0,7 pp | -0,283 | -0,254 | -0,257 |
| 5m_B_h25_r8 | 1507 | 1778 | 1916 | -0,6 pp | +0,0 pp | +0,8 pp | -0,284 | -0,255 | -0,258 |
| 15m_A_h8_r2 | 1278 | 1504 | 1621 | -0,9 pp | +0,0 pp | +0,2 pp | -0,297 | -0,260 | -0,261 |
| 15m_A_h16_r2 | 911 | 1092 | 1168 | -1,8 pp | -0,3 pp | +0,9 pp | -0,299 | -0,287 | -0,255 |
| 15m_A_h25_r2 | 744 | 882 | 939 | -2,2 pp | -1,1 pp | +0,6 pp | -0,309 | -0,274 | -0,261 |

Seçim sonucu — örneklem-içi (B1) ve örneklem-dışı (B2, B3):

|  | kombinasyon | şans farkı B1 (içi) | B2 (dışı) | B3 (dışı) | net60 B1 | B2 | B3 |
|---|---|---|---|---|---|---|---|
| B1'de seçilen (en yüksek şans farkı) | 5m_A_h8_r8 | +0,7 ± 1,1 | +2,2 ± 1,5 | +2,0 ± 1,6 | -0,267 | -0,246 | -0,261 |
| uygulama varsayılanı 5m A h8 r2 | 5m_A_h8_r2 | +0,6 ± 1,0 | +1,7 ± 1,6 | +2,3 ± 1,3 | -0,267 | -0,245 | -0,261 |
| uygulama varsayılanı 1m A h8 r2 | 1m_A_h8_r2 | -0,5 ± 1,1 | +1,8 ± 1,6 | +1,7 ± 1,4 | -0,241 | -0,213 | -0,225 |
| HA (aynı ölçü) | — | +3,5 ± 1,7 | +4,6 ± 2,5 | +5,4 ± 1,9 | -0,428 | -0,357 | -0,410 |

24 kombinasyonun B1 şans farkı sırası ile B2/B3 sırası arasında Spearman ρ: B2 için **0,67**, B3 için **0,62** (kombinasyonlar birbirine çok benzediği — r değişimi neredeyse etkisiz — için 24 gözlem bağımsız değil; ρ'nun bir kısmı ortak 'piyasa dönemi' etkisidir). Hiçbir kombinasyonun şans farkı B1'de +0,7 pp'i, B2'de +2,2 pp'yi, B3'te +2,3 pp'ü geçmiyor; HA ise +3,5 pp / +4,6 pp / +5,4 pp.

### (F) HA filtresi — 5m ve 15m kombinasyonlar

Skor = şans farkı(yeşil grup) − şans farkı(kırmızı grup) (pp; > 0 ⇒ 'yeşil' HA adayı daha iyi). Δ isabet = yeşil grup − tümleyeni (kırmızı + bilinmeyen) [%95].

| kombinasyon | skor B1 | B2 | B3 | Δ isabet B1 (pp) | Δ isabet B2 | Δ isabet B3 | n yeşil/kırmızı (B1) |
|---|---|---|---|---|---|---|---|
| 5m_A_h8_r1 | -2,2 pp | -2,0 pp | -0,8 pp | -6,0 [-9,6; -2,2] | -4,0 [-7,3; -0,5] | -1,0 [-4,4; +2,0] | 4.768/1.342 |
| 5m_A_h8_r2 | -2,5 pp | -2,2 pp | -0,1 pp | -5,9 [-9,5; -2,1] | -4,3 [-7,6; -0,7] | -1,0 [-4,5; +2,0] | 4.774/1.336 |
| 5m_A_h8_r8 | -2,2 pp | -2,6 pp | -1,5 pp | -5,8 [-9,4; -2,1] | -4,2 [-7,5; -0,8] | -1,0 [-4,5; +2,1] | 4.774/1.336 |
| 5m_A_h16_r1 | -1,0 pp | -0,3 pp | +0,0 pp | -2,7 [-6,4; +1,1] | -0,4 [-3,7; +3,4] | +1,1 [-2,2; +4,2] | 4.692/1.418 |
| 5m_A_h16_r2 | -0,6 pp | -1,0 pp | +0,6 pp | -2,6 [-6,1; +1,1] | -0,3 [-3,7; +3,5] | +1,1 [-2,2; +4,1] | 4.696/1.414 |
| 5m_A_h16_r8 | -1,1 pp | -0,4 pp | -0,3 pp | -2,7 [-6,3; +1,0] | -0,5 [-3,9; +3,2] | +1,0 [-2,2; +3,9] | 4.694/1.416 |
| 5m_A_h25_r1 | -0,8 pp | +2,2 pp | +1,2 pp | -2,5 [-5,9; +1,0] | +2,3 [-0,8; +5,9] | +1,3 [-1,5; +4,2] | 4.652/1.458 |
| 5m_A_h25_r2 | +0,2 pp | +2,3 pp | +0,0 pp | -2,5 [-5,8; +1,0] | +2,4 [-0,5; +6,0] | +1,2 [-1,7; +4,2] | 4.658/1.452 |
| 5m_A_h25_r8 | -0,4 pp | +1,7 pp | +0,3 pp | -2,4 [-5,8; +1,1] | +2,4 [-0,6; +6,0] | +1,3 [-1,6; +4,3] | 4.660/1.450 |
| 5m_B_h8_r1 | -1,3 pp | -0,5 pp | -0,2 pp | -3,3 [-7,0; +0,4] | -1,1 [-4,2; +2,2] | -0,6 [-3,7; +2,7] | 4.765/1.345 |
| 5m_B_h8_r2 | -1,3 pp | -0,8 pp | -1,6 pp | -3,6 [-7,2; -0,0] | -0,7 [-3,7; +2,6] | -0,7 [-4,0; +2,5] | 4.778/1.332 |
| 5m_B_h8_r8 | -1,8 pp | -0,9 pp | -1,9 pp | -4,1 [-7,6; -0,4] | -1,4 [-4,5; +1,9] | -1,3 [-4,5; +1,7] | 4.783/1.327 |
| 5m_B_h16_r1 | -0,5 pp | +1,7 pp | +0,1 pp | -2,1 [-5,7; +1,6] | +2,1 [-0,8; +5,4] | +0,7 [-2,2; +3,5] | 4.689/1.421 |
| 5m_B_h16_r2 | -1,0 pp | +2,3 pp | +0,5 pp | -2,3 [-6,1; +1,5] | +2,4 [-0,5; +5,8] | +0,8 [-2,1; +3,8] | 4.689/1.421 |
| 5m_B_h16_r8 | -0,7 pp | +2,4 pp | -0,2 pp | -2,7 [-6,6; +1,2] | +2,4 [-0,5; +5,7] | +0,7 [-2,4; +3,9] | 4.696/1.414 |
| 5m_B_h25_r1 | -0,8 pp | +2,2 pp | +1,2 pp | -2,5 [-5,9; +1,0] | +2,3 [-0,8; +5,9] | +1,3 [-1,5; +4,2] | 4.652/1.458 |
| 5m_B_h25_r2 | +0,2 pp | +2,3 pp | +0,0 pp | -2,5 [-5,8; +1,0] | +2,4 [-0,5; +6,0] | +1,2 [-1,7; +4,2] | 4.658/1.452 |
| 5m_B_h25_r8 | -0,4 pp | +1,7 pp | +0,3 pp | -2,4 [-5,8; +1,1] | +2,4 [-0,6; +6,0] | +1,3 [-1,6; +4,3] | 4.660/1.450 |
| 15m_A_h8_r2 | -0,9 pp | +2,4 pp | +1,2 pp | -1,8 [-4,6; +1,2] | +2,8 [-0,4; +6,2] | +1,6 [-0,9; +4,0] | 4.427/1.683 |
| 15m_A_h16_r2 | -0,4 pp | +4,4 pp | +0,9 pp | -1,5 [-3,9; +1,0] | +4,6 [+1,4; +8,4] | +2,3 [-0,4; +4,9] | 4.586/1.524 |
| 15m_A_h25_r2 | +3,0 pp | +4,1 pp | +4,0 pp | +1,6 [-1,6; +4,3] | +4,8 [+1,8; +8,1] | +4,6 [+1,9; +7,2] | 4.749/1.361 |

Seçim sonucu — şans farkı (yeşil grup / kırmızı grup), pp ± %95:

|  | kombinasyon | B1 (içi) | B2 (dışı) | B3 (dışı) |
|---|---|---|---|---|
| B1'de en yüksek skor ('yeşil daha iyi') | 15m_A_h25_r2 | +4,9 ± 1,7 / +1,9 ± 2,3 | +5,8 ± 2,4 / +1,7 ± 3,0 | +7,2 ± 1,5 / +3,1 ± 2,5 |
| B1'de en düşük skor ('kırmızı daha iyi') | 5m_A_h8_r2 | +3,4 ± 1,8 / +5,9 ± 2,9 | +4,8 ± 2,2 / +7,1 ± 3,5 | +5,7 ± 1,5 / +5,8 ± 3,3 |
| varsayılan 5m A h8 r2 | 5m_A_h8_r2 | +3,4 ± 1,8 / +5,9 ± 2,9 | +4,8 ± 2,2 / +7,1 ± 3,5 | +5,7 ± 1,5 / +5,8 ± 3,3 |
| varsayılan 15m A h8 r2 | 15m_A_h8_r2 | +3,4 ± 1,8 / +4,3 ± 2,3 | +5,3 ± 2,3 / +2,9 ± 2,9 | +6,2 ± 1,8 / +5,0 ± 2,2 |
| HA tümü | — | +3,5 ± 1,7 | +4,6 ± 2,5 | +5,4 ± 1,9 |

Skorun B1→B2 sıra korelasyonu ρ = **0,74**, B1→B3 ρ = **0,61**.

B1'de seçilen filtre **15m_A_h25_r2** ayrıntısı (HA adayı anında bu çekirdek yeşil ise tut):

| blok | grup | n | hit60@1,5 | hit60@2,0 | net60 | trailing net | şans farkı (pp) |
|---|---|---|---|---|---|---|---|
| B1 | yeşil (korunan) | 4.749 | %48,9 | %41,3 | -0,432 | +0,003 | +4,9 ± 1,7 |
| B1 | kırmızı (elenen) | 1.361 | %47,3 | %39,0 | -0,413 | +0,113 | +1,9 ± 2,3 |
| B1 | HA tümü | 6.110 | %48,5 | %40,8 | -0,428 | +0,028 | +3,5 ± 1,7 |
| B2 | yeşil (korunan) | 5.427 | %48,0 | %39,3 | -0,365 | -0,047 | +5,8 ± 2,4 |
| B2 | kırmızı (elenen) | 1.370 | %43,2 | %33,1 | -0,322 | -0,048 | +1,7 ± 3,0 |
| B2 | HA tümü | 6.797 | %47,0 | %38,1 | -0,357 | -0,047 | +4,6 ± 2,5 |
| B3 | yeşil (korunan) | 5.812 | %48,8 | %40,0 | -0,411 | -0,035 | +7,2 ± 1,5 |
| B3 | kırmızı (elenen) | 1.624 | %44,2 | %34,5 | -0,404 | -0,129 | +3,1 ± 2,5 |
| B3 | HA tümü | 7.436 | %47,8 | %38,8 | -0,410 | -0,056 | +5,4 ± 1,9 |


## 7. Analiz 5 — LUNATRY 17 Ekim 01:00

t0 = 2026-10-17 01:00 (5m ızgara; P0 = 00:55 mumunun kapanışı = **2,176**). Sonraki 60 dk'da en yüksek 5m kapanış 2,350 (**+8,00%**), en yüksek fiyat 2,350. Çekirdekler HAM mumlar üzerinde (uygulamanın gördüğü sıra); zaman = bar KAPANIŞ zamanı.

| çekirdek | t0'da renk | t0 öncesi son AL dönüşü (tüm geçmiş; gün saat, fiyat) | t0 SONRASI ilk AL dönüşü (zaman, fiyat, P0'a göre, t0'dan dk) |
|---|---|---|---|
| 1m_A_h8_r2 | kırmızı | 17 00:48 (2,178; 12 dk önce) | 01:02 (2,177; +0,05%; 2 dk) |
| 5m_A_h8_r2 | yeşil | 16 22:20 (2,153; 160 dk önce) | 02:50 (2,276; +4,60%; 110 dk) |
| 15m_A_h8_r2 | yeşil | 16 23:00 (2,162; 120 dk önce) | — |
| 5m_B_h8_r2 | yeşil | 16 22:20 (2,153; 160 dk önce) | — |
| 5m_A_h16_r2 | yeşil | 16 22:55 (2,156; 125 dk önce) | 03:25 (2,292; +5,33%; 145 dk) |

**1m_A_h8_r2** — 00:00–04:00 arası tüm renk değişimleri:

| bar kapanışı | yön | kapanış | P0'a göre | t0'a göre dk |
|---|---|---|---|---|
| 00:02 | SAT(kırmızı) | 2,165 | -0,51% | -58 |
| 00:06 | AL(yeşil) | 2,168 | -0,37% | -54 |
| 00:07 | SAT(kırmızı) | 2,168 | -0,37% | -53 |
| 00:10 | AL(yeşil) | 2,168 | -0,37% | -50 |
| 00:19 | SAT(kırmızı) | 2,170 | -0,28% | -41 |
| 00:22 | AL(yeşil) | 2,173 | -0,14% | -38 |
| 00:34 | SAT(kırmızı) | 2,175 | -0,05% | -26 |
| 00:35 | AL(yeşil) | 2,182 | +0,28% | -25 |
| 00:43 | SAT(kırmızı) | 2,177 | +0,05% | -17 |
| 00:48 | AL(yeşil) | 2,178 | +0,09% | -12 |
| 00:52 | SAT(kırmızı) | 2,178 | +0,09% | -8 |
| 01:02 | AL(yeşil) | 2,177 | +0,05% | 2 |
| 01:18 | SAT(kırmızı) | 2,205 | +1,33% | 18 |
| 01:20 | AL(yeşil) | 2,221 | +2,07% | 20 |
| 01:30 | SAT(kırmızı) | 2,225 | +2,25% | 30 |
| 01:31 | AL(yeşil) | 2,223 | +2,16% | 31 |
| 02:05 | SAT(kırmızı) | 2,295 | +5,47% | 65 |
| 02:15 | AL(yeşil) | 2,276 | +4,60% | 75 |
| 02:16 | SAT(kırmızı) | 2,281 | +4,83% | 76 |
| 02:17 | AL(yeşil) | 2,279 | +4,73% | 77 |
| 02:18 | SAT(kırmızı) | 2,261 | +3,91% | 78 |
| 02:19 | AL(yeşil) | 2,282 | +4,87% | 79 |
| 02:27 | SAT(kırmızı) | 2,276 | +4,60% | 87 |
| 02:36 | AL(yeşil) | 2,281 | +4,83% | 96 |
| 02:40 | SAT(kırmızı) | 2,254 | +3,58% | 100 |
| 02:42 | AL(yeşil) | 2,269 | +4,27% | 102 |
| 02:43 | SAT(kırmızı) | 2,260 | +3,86% | 103 |
| 02:47 | AL(yeşil) | 2,272 | +4,41% | 107 |
| 02:55 | SAT(kırmızı) | 2,268 | +4,23% | 115 |
| 02:56 | AL(yeşil) | 2,277 | +4,64% | 116 |
| 03:05 | SAT(kırmızı) | 2,283 | +4,92% | 125 |
| 03:06 | AL(yeşil) | 2,287 | +5,10% | 126 |
| 03:16 | SAT(kırmızı) | 2,288 | +5,15% | 136 |
| 03:17 | AL(yeşil) | 2,290 | +5,24% | 137 |
| 03:18 | SAT(kırmızı) | 2,288 | +5,15% | 138 |
| 03:20 | AL(yeşil) | 2,297 | +5,56% | 140 |
| 03:26 | SAT(kırmızı) | 2,283 | +4,92% | 146 |
| 03:34 | AL(yeşil) | 2,290 | +5,24% | 154 |
| 03:43 | SAT(kırmızı) | 2,289 | +5,19% | 163 |
| 03:49 | AL(yeşil) | 2,298 | +5,61% | 169 |
| 03:55 | SAT(kırmızı) | 2,278 | +4,69% | 175 |

**5m_A_h8_r2** — 00:00–04:00 arası tüm renk değişimleri:

| bar kapanışı | yön | kapanış | P0'a göre | t0'a göre dk |
|---|---|---|---|---|
| 02:30 | SAT(kırmızı) | 2,270 | +4,32% | 90 |
| 02:50 | AL(yeşil) | 2,276 | +4,60% | 110 |
| 02:55 | SAT(kırmızı) | 2,268 | +4,23% | 115 |
| 03:00 | AL(yeşil) | 2,284 | +4,96% | 120 |
| 03:45 | SAT(kırmızı) | 2,282 | +4,87% | 165 |
| 03:50 | AL(yeşil) | 2,295 | +5,47% | 170 |
| 03:55 | SAT(kırmızı) | 2,278 | +4,69% | 175 |

**15m_A_h8_r2** — 00:00–04:00 arası tüm renk değişimleri:

| bar kapanışı | yön | kapanış | P0'a göre | t0'a göre dk |
|---|---|---|---|---|
| 04:00 | SAT(kırmızı) | 2,285 | +5,01% | 180 |

**5m_B_h8_r2** — 00:00–04:00 arası tüm renk değişimleri:

| bar kapanışı | yön | kapanış | P0'a göre | t0'a göre dk |
|---|---|---|---|---|
| 03:55 | SAT(kırmızı) | 2,278 | +4,69% | 175 |

**5m_A_h16_r2** — 00:00–04:00 arası tüm renk değişimleri:

| bar kapanışı | yön | kapanış | P0'a göre | t0'a göre dk |
|---|---|---|---|---|
| 03:15 | SAT(kırmızı) | 2,293 | +5,38% | 135 |
| 03:25 | AL(yeşil) | 2,292 | +5,33% | 145 |

1m çekirdek (A, h=8, r=2) — 00:50…01:30 bar kapanışları:

| kapanış | close | yhat | renk |
|---|---|---|---|
| 00:50 | 2,178 | 2,1779 | yeşil |
| 00:51 | 2,180 | 2,1782 | yeşil |
| 00:52 | 2,178 | 2,1782 | kırmızı |
| 00:53 | 2,178 | 2,1781 | kırmızı |
| 00:54 | 2,177 | 2,1780 | kırmızı |
| 00:55 | 2,177 | 2,1780 | kırmızı |
| 00:56 | 2,177 | 2,1778 | kırmızı |
| 00:57 | 2,177 | 2,1777 | kırmızı |
| 00:58 | 2,175 | 2,1772 | kırmızı |
| 00:59 | 2,176 | 2,1768 | kırmızı |
| 01:00 | 2,176 | 2,1765 | kırmızı |
| 01:01 | 2,176 | 2,1763 | kırmızı |
| 01:02 | 2,177 | 2,1763 | yeşil |
| 01:03 | 2,179 | 2,1767 | yeşil |
| 01:04 | 2,183 | 2,1775 | yeşil |
| 01:05 | 2,184 | 2,1786 | yeşil |
| 01:06 | 2,184 | 2,1797 | yeşil |
| 01:07 | 2,206 | 2,1839 | yeşil |
| 01:08 | 2,204 | 2,1876 | yeşil |
| 01:09 | 2,206 | 2,1916 | yeşil |
| 01:10 | 2,205 | 2,1951 | yeşil |
| 01:11 | 2,205 | 2,1982 | yeşil |
| 01:12 | 2,210 | 2,2015 | yeşil |
| 01:13 | 2,207 | 2,2040 | yeşil |
| 01:14 | 2,198 | 2,2051 | yeşil |
| 01:15 | 2,212 | 2,2059 | yeşil |
| 01:16 | 2,208 | 2,2064 | yeşil |
| 01:17 | 2,209 | 2,2069 | yeşil |
| 01:18 | 2,205 | 2,2068 | kırmızı |
| 01:19 | 2,205 | 2,2067 | kırmızı |
| 01:20 | 2,221 | 2,2084 | yeşil |
| 01:21 | 2,221 | 2,2104 | yeşil |
| 01:22 | 2,228 | 2,2142 | yeşil |
| 01:23 | 2,220 | 2,2154 | yeşil |
| 01:24 | 2,225 | 2,2176 | yeşil |
| 01:25 | 2,224 | 2,2194 | yeşil |
| 01:26 | 2,225 | 2,2217 | yeşil |
| 01:27 | 2,230 | 2,2245 | yeşil |
| 01:28 | 2,225 | 2,2249 | yeşil |
| 01:29 | 2,229 | 2,2259 | yeşil |
| 01:30 | 2,225 | 2,2256 | kırmızı |

HA adayı satırı yok: `work/rescan_90g_nogate.jsonl` 16 Ekim 23:55'te bitiyor. Canlıda LUNATRY radarın izleme listesinin tepesindeydi ama bildirim `BTC_BEAR_REGIME_SHIELD` + `mfi_asiri_alim:96` kapılarına takıldı (docs/REJIM_KALKANI_ANALIZI_2026-10-17.md).


## 8. Sınırlar

- **Çoklu karşılaştırma.** 24 kombinasyon × 3 blok × (E ve F rolleri) + 15 durum grubu × 3 blok + 8 giriş yapılandırması × 3 blok: yüzün üstünde hücre. %95 aralıkları çoklu karşılaştırma için düzeltilmedi; "post-hoc" etiketli bulgular
  (ör. 15m olgun yeşil) seçim dışı gözlemdir ve ileri bir testten geçmeden kanıt sayılmamalı. Parametre seçimi tek bloğa (B1, ≈ 30 gün) dayanıyor.
- **Tek piyasa dönemi.** 90 günün tamamı tek rejim kümesi: BTC EMA200 altı günler çoğunlukta, 22 Ağu/21 Ağu/15 Eki/21 Eyl gibi birkaç geniş yükseliş günü olayların ≈ %16'sını veriyor. Bloklar bağımsız piyasalar değil, ardışık parçalar.
- **t0 ileriye bakışı.** Olay tanımı geleceğe bakıyor (60 dk içinde ≥ %4, ≥ %70 yeşil mum, koşu boyunca kapanış ≥ P0, ilk mum yeşil): olay anı hep küçük bir düşüşün/duraklamanın ardından seçiliyor, bu yüzden t0'da 'kırmızı' çekirdek ve 'düşüş sonrası' özelliklerin
  görünümü kısmen tanım artefaktı; çekirdeğin 'öncü' olmadığı sonucu bu seçimden etkilenir (t0'ın biraz öncesi/sonrası değişse AUC'ler kayar). Sinyal tarafındaki ölçümler (giriş, filtre) ileriye bakmaz; yalnız sonucun ölçülebilirlik koşulu (60 dk'lık pencerede gerçek mum) gelecekten gelir (tüm çalışmalarda aynı).
- **Pencere/çözünürlük.** 5m sinyal sonuçları 5m mum içi sırayı kötümser (SL önce) ele alır; 1m sinyallerde 1 dk yolu kullanıldığı için net60/trailing biraz farklı çözünürlükte ölçülüyor, şans tabanı ise 5m ızgara üzerinde (karar pencereleri 5 dk kayık: sinyal 5. dk'da, taban 0. dk'da başlıyor — taban lehine, yani kazançlar muhafazakâr).
- **HA satırları bağımsız değil** (aynı sembolde art arda bölümler, gün kümeli bootstrap kullanıldı ama sembol kümeli değil). NullEngine örneklemli (3 tohum × 3000; ± gün-kümeli).
- **Kontrol testi (fark-farkı)** HA'nın seçtiği kümede aralık kısıtlıdır (tavan/seçilim etkisi): HA içinde etkinin küçülmesi 'HA zaten içeriyor' ile 'HA'nın dar aralığı' ayrımını tam yapmaz; rastgele anlar da aynı sembol-günden (HA satırı başına ≤ 20) örneklendi, 5m ızgara hit60@1,5 ölçüsüyle.
- **Önbellek/yeniden üretim.** Analizler 90 günlük çalışmanın önbelleğini (`pattern90_study.py --cache-dir`: d1/d5/grid/snap/events) ve `work/pattern90/ha.npz` dosyasını kullanır; sıra: `rqk_study.py --p90-cache <dizin> --stages fetch15,sym,agg,analyze,report`.
- **Aday dosyası** 16 Ekim 23:55'te bitiyor; 17 Ekim (LUNATRY) için HA satırı yok. LUNATRY tek örnek ve analiz öncesi görülmüş.
- **Çekirdek kısaltması.** Uygulama toplamı son h muma kesiyor (h=8 → 8 bar): gösterge fiyata çok yakın, hızlı bir yumuşatma; kanonik (25 bar pencere) ile karşılaştırma 5m'de yapıldı (varyant B); h=25'te iki varyant aynı pencereyi kullanır, yalnız renk kuralı farklıdır.

