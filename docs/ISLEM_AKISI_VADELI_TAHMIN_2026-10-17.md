# İşlem akışı + vadeli (OI / L-S / fonlama / defter) verisi — LUNA tipi yükseliş ve Hız Avcısı için çevrimdışı ölçüm (2026-10-17)

**Hüküm: HAYIR — maliyet sonrası net-pozitif, kullanılabilir bir kenar YOK; ana tahmin motorunu besleyecek ölçüde bilgi de yok.** Veri gerçek ve kısmen anlamlı bilgi taşıyor (olay öncesi işlem sayısı/büyük işlem patlaması ve vadeli primi), ama (i) olay öngörüsünde mevcut 154 özelliğe eklenen bilgi gün-kümeli %95 aralığın sıfırı içinde ya da en çok AUC +0,004 (t0'da +fu) mertebesinde, (ii) HA süzgeci olarak hiçbir kural örneklem dışı üç blokta birden net-pozitif olmadı, (iii) önceden belirlenmiş 13 sinyalin hiçbiri üç blokta net-pozitif olmadı. Tek tutarlı yapı **vadeli primi (perp − TRY spot/USDTTRY)**: bu, daha önce ölçülen USD→TRY lead-lag'in aynısı; brüt kenar 60 dakikada ≈ +%0,2 (uç %5 ≈ +%0,3-0,4), maliyet duvarı ≈ %0,525. Gerçekçi doluşla en iyi uç %5 net -0,29…-0,32 (rastgele giriş -0,49…-0,51): rastgeleden her blokta ≈ +0,2 puan iyi ama hâlâ NEGATİF. Vadeli veri 5 dk geç bilinirse brüt avantaj `basis_z`'de yaklaşık yarıya, `basis_d15`'te dörtte bire iner; ts_ms yanlış (bar kapanışı) okunursa yapay şişer (bölüm 5).

| soru | sonuç (örneklem dışı: B1, B2, B3; seçim hiçbir zaman değerlendirilen blokta yapılmadı) |
|---|---|
| (a) Olay öngörüsü, tek tek özellik (t0−10) | 94 özellikten BH q<0,05: ham 33, dip+oynaklık kontrollü artık 27 (tf 14 / fu 10 FWER-artık); en güçlü artık AUC 0,563 (`tf.ntr_z_15`), 3 blokta aynı işaret. En güçlüler **etkinlik/işlem-sayısı patlaması** (z-skorlu işlem sayısı, büyük işlem sayısı: 0,55-0,56); ardından OI z/büyüklüğü, top-trader L/S düzeyi, fonlama (0,52-0,54). Yönlü bir alım-akışı öncüsü yok: 15 dk alıcı payı artığı 0,465 (olay öncesi alıcı payı DAHA DÜŞÜK = satış baskısı/dip). |
| (a) Blok-dışı seçilmiş en iyi 10 özelliğin ortalama AUC'si (t0−10) | tf 0,541 / 0,544 / 0,540, fu 0,521 / 0,525 / 0,526 (B1/B2/B3; ½ = bilgi yok) |
| (a) Çok değişkenli HGB (t0−10, aynı alt küme), grup-içi AUC farkı vs mevcut 154 | +tf +0,0009 [-0,0054; +0,0074] · +fu +0,0029 [-0,0037; +0,0097] · +ikisi +0,0023 [-0,0051; +0,0106] (blok-dışı, havuz, gün-kümeli %95 aralık). t0'da: +tf -0,0016 [-0,0041; +0,0010] · +fu +0,0038 [+0,0009; +0,0068] · +ikisi +0,0033 [-0,0002; +0,0071]. Mevcut 154: t0−10 0,616/0,637/0,621, t0 0,770/0,777/0,761. |
| (b) HA süzgeci | ATR-kontrollü kısmi Spearman (net−taban): 41/94 özellik BH q<0,05; en güçlü `fu.basis_z` r=0,046 (t=6,7), 3/3 blok aynı işaret. Blok-dışı seçilen en iyi 10 özelliğin favori tersilinde HA neti her blokta NEGATİF (en iyi tek blok-hücre -0,36); kural rotasyonunda iki OOS blokta birden net>0 olan kural: 0 / 36; 548 aday içinde 3 blokta net>0: 0. |
| (c) 13 önceden belirlenmiş sinyal | Günde 48-1800 tetik (çoğu doygun); 3 blokta da net>0 olan: **yok**. En az negatif (en kötü blok): `basis_lead` (-0,32 / -0,32 / -0,31). Koşulsuz rastgele giriş -0,51 / -0,48 / -0,49. 'Kanıtlı erken uyarı' ölçütünü geçen tek sinyal `big_oi` (günde 400-625 tetik, kesinlik %1,6-2,1, net -0,52…-0,48 / rastgele -0,56…-0,53): zayıf istatistiksel eğilim, kullanılamaz (bölüm 4). |
| (d) Karar | Ana tahmin motoruna ve canlı günlüğe EKLEMEYİN (kenar yok). Vadeli primi (basis) zaten canlıdaki GLOBAL_LEAD_LAG ile aynı mekanizma; yeni bilgi sayılmaz. Detay bölüm 6. |

## 1. Nedensellik (ileriye bakış denetimi) ve veri

Vadeli satırlarından türetilen fiyat (OI notional/OI; defter notional/derinlik) ile TRY spot/USDTTRY getirilerinin korelasyonu, satırın `ts_ms` değerine göre dakika gecikmesinde (`stage_timing`, ham tablo `timing.json`):

| sembol / tablo | en iyi gecikme (dk) | r (en iyi) | r (gecikme 0) | r (gecikme +5) |
|---|---|---|---|---|
| BNBTRY / bookdepth | 0 | 0,824 | 0,824 | 0,084 |
| BNBTRY / metrics | 5 | 0,871 | -0,005 | 0,871 |
| BTCTRY / bookdepth | 0 | 0,864 | 0,864 | 0,002 |
| BTCTRY / metrics | 5 | 0,941 | -0,013 | 0,941 |
| ETHTRY / bookdepth | 0 | 0,875 | 0,875 | 0,000 |
| ETHTRY / metrics | 5 | 0,902 | -0,001 | 0,902 |
| SOLTRY / bookdepth | 0 | 0,894 | 0,894 | -0,010 |
| SOLTRY / metrics | 5 | 0,941 | -0,021 | 0,941 |

- **`hist_futures_metrics.ts_ms` dilimin BAŞLANGICIDIR; değer dilim SONUNDA (ts+5 dk) ölçülür** (4/4 sembolde en iyi gecikme +5 dk, r≈0,87-0,94; gecikme 0'da r≈0). Yani ts=T satırı T+5 dk'dan önce bilinmez: karar anı t_dec = mum kapanışı olduğundan mum i'ye T = açılış zamanı olan satır bağlandı (t_dec'te bilinen en yeni satır), `--extra-lag` ile 1 bar daha gecikmeli sürüm ayrıca ölçüldü (bölüm 6). Naif bağlama (ts'yi bar kapanışı sanmak) 5 dk ileriye bakış olurdu ve bazis/OI özelliklerini yapay güçlendirirdi.
- `hist_futures_bookdepth.ts_ms` anlık görüntünün GERÇEK zamanıdır (en iyi gecikme 0 dk) -> ts ∈ [ot, ot+5dk) satırı mum i'ye bağlandı.
- Fonlama: yalnız `funding_time_ms <= t_dec` olan son yerleşmiş oran; z-skoru önceki 21 yerleşimden.
- İşlem akışı: dakika açılışı ot[i] ≤ dakika < ot[i]+5dk, t_dec'te tamam. `sum_open_interest>0` süzgeci uygulandı (15 Eki ~13:40 UTC toplu sıfırlar); en çok 3 bar ileri taşıma, taze olmayan satırda baz (basis) hesaplanmaz.
- Kesme testi: `tests/test_flow_futures.py` her özellik için girdileri t anında kesip yeniden hesaplar, satır aynıdır; hizalama fonksiyonları gelecekteki satırlar değiştirilince geçmiş barları etkilemez.
- Perp = Binance USDⓈ-M küresel kontrat; Binance TR TRY defteri DEĞİL (defter özellikleri küresel derinliktir). Baz = (OI notional/OI / çarpan) / (TRY spot/USDTTRY).

**Özellikler:** 46 işlem akışı (`tf.`: alıcı payı, büyük/balina net akış ve sayı, z-skorlu işlem sayısı/ortalama/azami büyüklük, vwap uzaklığı, ivme, emilim, CVD eğimi; pencere 5/15/60 dk) + 48 vadeli (`fu.`: OI değişim 5/15/60, OI z, dört kadran, top-trader ve hesap L/S, taker L/S, fonlama düzey/z/değişim, baz bps/z/değişim, defter dengesizliği ±1/2/5 %, derinlik z). Kapsam: olayların 100,0%'sinde işlem akışı, 95,8%'sinde vadeli (perp'i olmayan 16 taban + eksik satırlar); eşleşmiş taban olayla AYNI sembolden olduğundan kapsam grup içinde aynıdır. Her karşılaştırma kapsamı olan alt kümede yapıldı (olay sayısı: 4360/4552).

## 2. (a) Olay öngörüsü — LUNA tipi 90 günlük yükseliş olayları (n=4552), eşleşmiş taban (olay başına ≤20)

### t0-10: en güçlü 14 özellik (|artık AUC−½|)

| özellik | aile | ham AUC | artık AUC | q (artık) | B1/B2/B3 artık AUC | işaret tutarlılığı |
|---|---|---|---|---|---|---|
| `tf.ntr_z_15` | tf_size | 0,570 | 0,563 | 0,004 | 0,561 / 0,570 / 0,559 | 3 |
| `tf.ntr_z_60` | tf_size | 0,565 | 0,562 | 0,004 | 0,566 / 0,564 / 0,558 | 3 |
| `tf.bigcnt_z_60` | tf_big | 0,559 | 0,556 | 0,004 | 0,559 / 0,558 / 0,552 | 3 |
| `tf.bigcnt_z_15` | tf_big | 0,564 | 0,555 | 0,004 | 0,550 / 0,563 / 0,552 | 3 |
| `tf.ntr_z_5` | tf_size | 0,563 | 0,553 | 0,004 | 0,549 / 0,555 / 0,553 | 3 |
| `fu.tt_ls` | fu_ls | 0,531 | 0,538 | 0,004 | 0,539 / 0,539 / 0,537 | 3 |
| `tf.bigcnt_z_5` | tf_big | 0,555 | 0,537 | 0,004 | 0,532 / 0,539 / 0,538 | 3 |
| `tf.buy_share_15` | tf_dir | 0,498 | 0,465 | 0,004 | 0,467 / 0,460 / 0,467 | 3 |
| `fu.oi_val_log10` | fu_oi | 0,482 | 0,465 | 0,004 | 0,473 / 0,475 / 0,452 | 3 |
| `fu.oi_z` | fu_oi | 0,533 | 0,532 | 0,004 | 0,537 / 0,542 / 0,519 | 3 |
| `fu.fund_bps` | fu_fund | 0,501 | 0,529 | 0,004 | 0,530 / 0,537 / 0,520 | 3 |
| `tf.maxsz_z_15` | tf_size | 0,548 | 0,526 | 0,004 | 0,528 / 0,529 / 0,522 | 3 |
| `fu.fund_chg` | fu_fund | 0,494 | 0,526 | 0,004 | 0,511 / 0,531 / 0,532 | 3 |
| `fu.fund_age_h` | fu_fund | 0,523 | 0,524 | 0,004 | 0,503 / 0,521 / 0,540 | 3 |

| aile | özellik | q<0,05 (artık) | en büyük |AUC−½| |
|---|---|---|---|
| fu_basis | 4 | 1 | 0,011 |
| fu_book | 11 | 1 | 0,018 |
| fu_fund | 4 | 3 | 0,029 |
| fu_ls | 12 | 1 | 0,038 |
| fu_oi | 6 | 3 | 0,035 |
| fu_quad | 6 | 2 | 0,019 |
| fu_taker | 5 | 0 | 0,009 |
| tf_absorb | 4 | 1 | 0,015 |
| tf_big | 15 | 5 | 0,056 |
| tf_dir | 9 | 1 | 0,035 |
| tf_size | 9 | 6 | 0,063 |
| tf_vwap | 3 | 0 | 0,004 |
| tf_whale | 6 | 3 | 0,019 |

Blok-dışı seçim (her blokta, diğer iki bloktaki artık-AUC sapması en büyük 10 özellik; işaret oradan; değerlendirme kalan blokta):

| aile | blok | olay | ort. AUC [gün-kümeli %95] | >½ | en iyi tek | seçilen (ilk 3) |
|---|---|---|---|---|---|---|
| tf. | B1 | 1133 | 0,541 [0,529; 0,553] | 10/10 | 0,566 | `tf.ntr_z_15`, `tf.ntr_z_60`, `tf.bigcnt_z_15` |
| tf. | B2 | 1591 | 0,544 [0,536; 0,553] | 10/10 | 0,570 | `tf.ntr_z_60`, `tf.ntr_z_15`, `tf.bigcnt_z_60` |
| tf. | B3 | 1823 | 0,540 [0,531; 0,550] | 10/10 | 0,559 | `tf.ntr_z_15`, `tf.ntr_z_60`, `tf.bigcnt_z_60` |
| fu. | B1 | 1088 | 0,521 [0,514; 0,527] | 10/10 | 0,539 | `fu.tt_ls`, `fu.oi_val_log10`, `fu.fund_chg` |
| fu. | B2 | 1534 | 0,525 [0,518; 0,532] | 10/10 | 0,542 | `fu.oi_val_log10`, `fu.tt_ls`, `fu.bd_depth2_log` |
| fu. | B3 | 1738 | 0,526 [0,519; 0,533] | 10/10 | 0,548 | `fu.oi_z`, `fu.tt_ls`, `fu.fund_bps` |

### t0: en güçlü 14 özellik (|artık AUC−½|)

| özellik | aile | ham AUC | artık AUC | q (artık) | B1/B2/B3 artık AUC | işaret tutarlılığı |
|---|---|---|---|---|---|---|
| `fu.quad_shortcover_15` | fu_quad | 0,476 | 0,583 | 0,002 | 0,575 / 0,591 / 0,581 | 3 |
| `tf.ntr_z_15` | tf_size | 0,584 | 0,573 | 0,002 | 0,570 / 0,578 / 0,571 | 3 |
| `tf.ntr_z_5` | tf_size | 0,579 | 0,571 | 0,002 | 0,577 / 0,575 / 0,564 | 3 |
| `tf.ntr_z_60` | tf_size | 0,577 | 0,568 | 0,002 | 0,572 / 0,569 / 0,564 | 3 |
| `fu.oi_val_log10` | fu_oi | 0,454 | 0,433 | 0,002 | 0,440 / 0,433 / 0,430 | 3 |
| `tf.bigcnt_z_15` | tf_big | 0,578 | 0,565 | 0,002 | 0,562 / 0,570 / 0,563 | 3 |
| `fu.quad_newshort_15` | fu_quad | 0,535 | 0,436 | 0,002 | 0,447 / 0,423 / 0,440 | 3 |
| `tf.bigcnt_z_60` | tf_big | 0,572 | 0,561 | 0,002 | 0,562 / 0,565 / 0,556 | 3 |
| `tf.bigcnt_z_5` | tf_big | 0,576 | 0,559 | 0,002 | 0,571 / 0,566 / 0,546 | 3 |
| `fu.basis_z` | fu_basis | 0,583 | 0,558 | 0,002 | 0,567 / 0,541 / 0,567 | 3 |
| `fu.basis_bps` | fu_basis | 0,583 | 0,554 | 0,002 | 0,564 / 0,539 / 0,562 | 3 |
| `fu.tt_ls` | fu_ls | 0,530 | 0,553 | 0,002 | 0,554 / 0,556 / 0,548 | 3 |
| `fu.quad_newlong_15` | fu_quad | 0,471 | 0,552 | 0,002 | 0,550 / 0,555 / 0,552 | 3 |
| `tf.absorb_buy_15` | tf_absorb | 0,598 | 0,550 | 0,002 | 0,560 / 0,551 / 0,544 | 3 |

| aile | özellik | q<0,05 (artık) | en büyük |AUC−½| |
|---|---|---|---|
| fu_basis | 4 | 4 | 0,058 |
| fu_book | 11 | 2 | 0,031 |
| fu_fund | 4 | 4 | 0,046 |
| fu_ls | 12 | 9 | 0,053 |
| fu_oi | 6 | 6 | 0,067 |
| fu_quad | 6 | 6 | 0,083 |
| fu_taker | 5 | 5 | 0,025 |
| tf_absorb | 4 | 4 | 0,050 |
| tf_big | 15 | 14 | 0,065 |
| tf_dir | 9 | 7 | 0,046 |
| tf_size | 9 | 6 | 0,073 |
| tf_vwap | 3 | 3 | 0,046 |
| tf_whale | 6 | 2 | 0,028 |

Not: `fu.quad_*` bayrakları fiyat hareketinin işaretinden türetilir; dip kontrolü yalnız doğrusal olduğundan t0'daki yüksek artık AUC'ler (0,58 / 0,44) büyük ölçüde dipin kendisinin doğrusal olmayan kalıntısıdır; öncü bilgi sayılmamalı.

Blok-dışı seçim (her blokta, diğer iki bloktaki artık-AUC sapması en büyük 10 özellik; işaret oradan; değerlendirme kalan blokta):

| aile | blok | olay | ort. AUC [gün-kümeli %95] | >½ | en iyi tek | seçilen (ilk 3) |
|---|---|---|---|---|---|---|
| tf. | B1 | 1133 | 0,558 [0,550; 0,567] | 10/10 | 0,577 | `tf.ntr_z_15`, `tf.ntr_z_5`, `tf.bigcnt_z_15` |
| tf. | B2 | 1591 | 0,563 [0,553; 0,573] | 10/10 | 0,578 | `tf.ntr_z_15`, `tf.ntr_z_5`, `tf.ntr_z_60` |
| tf. | B3 | 1823 | 0,553 [0,547; 0,561] | 10/10 | 0,571 | `tf.ntr_z_5`, `tf.ntr_z_15`, `tf.ntr_z_60` |
| fu. | B1 | 1088 | 0,552 [0,545; 0,559] | 10/10 | 0,575 | `fu.quad_shortcover_15`, `fu.oi_val_log10`, `fu.quad_newshort_15` |
| fu. | B2 | 1534 | 0,554 [0,548; 0,562] | 10/10 | 0,591 | `fu.quad_shortcover_15`, `fu.basis_z`, `fu.oi_val_log10` |
| fu. | B3 | 1737 | 0,556 [0,548; 0,563] | 10/10 | 0,581 | `fu.quad_shortcover_15`, `fu.quad_newshort_15`, `fu.oi_val_log10` |

### Çok değişkenli (HistGradientBoosting, olay başına 12 taban; grup-içi AUC, her olay aynı olay grubunun tabanlarına karşı)

**t0-10 — aynı alt küme (tf+fu var)** (olay 4360, satır 56712)

| değişken | blok-dışı B1/B2/B3 | ileri-yürüyen B2/B3 | Δ vs 154 (blok-dışı) [%95] | Δ vs 154 (ileri) [%95] |
|---|---|---|---|---|
| mevcut 154 | 0,616 / 0,637 / 0,621 | 0,606 / 0,621 | - | - |
| + tf | 0,622 / 0,639 / 0,618 | 0,601 / 0,618 | +0,0009 [-0,0054; +0,0074] | -0,0039 [-0,0112; +0,0028] |
| + fu | 0,629 / 0,640 / 0,618 | 0,603 / 0,618 | +0,0029 [-0,0037; +0,0097] | -0,0028 [-0,0121; +0,0068] |
| + tf + fu | 0,624 / 0,644 / 0,615 | 0,592 / 0,615 | +0,0023 [-0,0051; +0,0106] | -0,0094 [-0,0184; -0,0002] |
| yalnız tf+fu | 0,571 / 0,576 / 0,580 | 0,559 / 0,580 | -0,0491 [-0,0598; -0,0377] | -0,0438 [-0,0577; -0,0282] |

**t0-10 — tüm (tf var)** (olay 4547, satır 59109)

| değişken | blok-dışı B1/B2/B3 | ileri-yürüyen B2/B3 | Δ vs 154 (blok-dışı) [%95] | Δ vs 154 (ileri) [%95] |
|---|---|---|---|---|
| mevcut 154 | 0,623 / 0,639 / 0,622 | 0,604 / 0,622 | - | - |
| + tf | 0,622 / 0,634 / 0,632 | 0,602 / 0,632 | +0,0016 [-0,0035; +0,0064] | +0,0037 [-0,0042; +0,0116] |

**t0 — aynı alt küme (tf+fu var)** (olay 4359, satır 56706)

| değişken | blok-dışı B1/B2/B3 | ileri-yürüyen B2/B3 | Δ vs 154 (blok-dışı) [%95] | Δ vs 154 (ileri) [%95] |
|---|---|---|---|---|
| mevcut 154 | 0,770 / 0,777 / 0,761 | 0,754 / 0,761 | - | - |
| + tf | 0,770 / 0,772 / 0,761 | 0,754 / 0,761 | -0,0016 [-0,0041; +0,0010] | +0,0002 [-0,0041; +0,0044] |
| + fu | 0,778 / 0,779 / 0,763 | 0,760 / 0,763 | +0,0038 [+0,0009; +0,0068] | +0,0043 [+0,0002; +0,0084] |
| + tf + fu | 0,778 / 0,778 / 0,762 | 0,759 / 0,762 | +0,0033 [-0,0002; +0,0071] | +0,0034 [-0,0008; +0,0080] |
| yalnız tf+fu | 0,719 / 0,721 / 0,711 | 0,705 / 0,711 | -0,0521 [-0,0586; -0,0452] | -0,0495 [-0,0579; -0,0407] |

**t0 — tüm (tf var)** (olay 4547, satır 59109)

| değişken | blok-dışı B1/B2/B3 | ileri-yürüyen B2/B3 | Δ vs 154 (blok-dışı) [%95] | Δ vs 154 (ileri) [%95] |
|---|---|---|---|---|
| mevcut 154 | 0,775 / 0,774 / 0,761 | 0,761 / 0,761 | - | - |
| + tf | 0,773 / 0,775 / 0,759 | 0,759 / 0,759 | -0,0013 [-0,0038; +0,0013] | -0,0019 [-0,0050; +0,0013] |

## 3. (b) Hız Avcısı (HA) süzgeci — 20343 olay (geçerli 20343), 3 blok

HA nüfusu (TP = HA'nın kendi hedefi, SL %3, T60, exit_sim gerçekçi doluş): B1 n=6110 net -0,54±0,03, net−taban +0,33; B2 n=6797 net -0,51±0,04, net−taban +0,10; B3 n=7436 net -0,62±0,03, net−taban +0,17. Özellik kapsamı: tf 100,0%, fu 94,5%, defter 92,5%.

### Kısmi Spearman (ATR + hedef/ATR kontrollü) — net−taban ile, |t| sırasıyla ilk 16

| özellik | aile | r | t (gün-kümeli) | q | B1/B2/B3 r | uyum | kapsam |
|---|---|---|---|---|---|---|---|
| `fu.basis_z` | fu_basis | +0,046 | 6,7 | 0,000 | +0,061 / +0,049 / +0,029 | 3 | 94% |
| `fu.basis_d60` | fu_basis | +0,036 | 4,8 | 0,000 | +0,052 / +0,024 / +0,036 | 3 | 94% |
| `fu.basis_bps` | fu_basis | +0,038 | 4,7 | 0,000 | +0,080 / +0,049 / +0,005 | 3 | 94% |
| `fu.tt_cnt_ls_d12` | fu_ls | +0,035 | 4,7 | 0,000 | +0,033 / +0,036 / +0,036 | 3 | 94% |
| `fu.oi_val_log10` | fu_oi | +0,038 | 4,5 | 0,000 | +0,031 / +0,068 / +0,028 | 3 | 95% |
| `tf.absorb_buy_60` | tf_absorb | +0,030 | 4,4 | 0,000 | +0,026 / +0,038 / +0,030 | 3 | 100% |
| `tf.ntr_z_5` | tf_size | -0,032 | -4,2 | 0,001 | -0,020 / -0,030 / -0,041 | 3 | 100% |
| `tf.bigcnt_z_5` | tf_big | -0,031 | -4,1 | 0,001 | -0,021 / -0,026 / -0,042 | 3 | 100% |
| `fu.tt_cnt_ls_z` | fu_ls | +0,030 | 3,8 | 0,002 | +0,019 / +0,034 / +0,034 | 3 | 94% |
| `fu.fund_z` | fu_fund | +0,031 | 3,7 | 0,003 | +0,021 / +0,051 / +0,026 | 3 | 73% |
| `fu.tt_cnt_ls` | fu_ls | -0,026 | -3,7 | 0,003 | -0,018 / -0,022 / -0,030 | 3 | 95% |
| `fu.acc_ls` | fu_ls | -0,026 | -3,6 | 0,005 | -0,021 / -0,025 / -0,028 | 3 | 95% |
| `tf.bigcnt_5` | tf_big | -0,025 | -3,5 | 0,006 | -0,033 / -0,013 / -0,029 | 3 | 100% |
| `tf.whale_net_rel_60` | tf_whale | -0,025 | -3,5 | 0,006 | -0,021 / -0,022 / -0,029 | 3 | 100% |
| `fu.quad_60` | fu_quad | +0,023 | 3,4 | 0,006 | +0,027 / +0,010 / +0,036 | 3 | 94% |
| `fu.quad_longliq_15` | fu_quad | +0,026 | 3,4 | 0,007 | +0,018 / +0,027 / +0,034 | 3 | 94% |

| aile | özellik | q<0,05 (net−taban) | en büyük |r| |
|---|---|---|---|
| fu_basis | 4 | 4 | 0,046 |
| fu_book | 11 | 0 | 0,016 |
| fu_fund | 4 | 1 | 0,031 |
| fu_ls | 12 | 7 | 0,035 |
| fu_oi | 6 | 5 | 0,038 |
| fu_quad | 6 | 2 | 0,026 |
| fu_taker | 5 | 0 | 0,014 |
| tf_absorb | 4 | 3 | 0,030 |
| tf_big | 15 | 7 | 0,031 |
| tf_dir | 9 | 0 | 0,011 |
| tf_size | 9 | 7 | 0,032 |
| tf_vwap | 3 | 1 | 0,023 |
| tf_whale | 6 | 4 | 0,025 |

### HA neti, blok-dışı seçilmiş en iyi 10 özelliğin favori tersilinde (yön ve tersil kenarları YALNIZ diğer iki bloktan)

**Değerlendirme bloğu B1**

| özellik (seçim) | seçim r | n (favori) | net favori | net−taban favori | net sakıncalı tersil | net tüm HA |
|---|---|---|---|---|---|---|
| `fu.oi_val_log10` | +0,050 | 961 | -0,38 | +0,57 | -0,56 | -0,54 |
| `fu.basis_z` | +0,039 | 1956 | -0,47 | +0,43 | -0,68 | -0,54 |
| `fu.tt_cnt_ls` | -0,028 | 2650 | -0,52 | +0,43 | -0,55 | -0,54 |
| `tf.absorb_buy_60` | +0,034 | 1676 | -0,50 | +0,47 | - | -0,54 |
| `fu.acc_ls` | -0,027 | 2491 | -0,48 | +0,42 | -0,54 | -0,54 |
| `tf.ntr_z_5` | -0,037 | 2163 | -0,54 | +0,38 | -0,51 | -0,54 |
| `fu.tt_cnt_ls_d12` | +0,035 | 1902 | -0,44 | +0,49 | -0,63 | -0,54 |
| `fu.bd_depth2_log` | +0,032 | 542 | -0,44 | +0,39 | -0,48 | -0,54 |
| `fu.tt_cnt_ls_z` | +0,035 | 1797 | -0,57 | +0,36 | -0,49 | -0,54 |
| `tf.bigcnt_z_5` | -0,035 | 2161 | -0,54 | +0,38 | -0,52 | -0,54 |

**Değerlendirme bloğu B2**

| özellik (seçim) | seçim r | n (favori) | net favori | net−taban favori | net sakıncalı tersil | net tüm HA |
|---|---|---|---|---|---|---|
| `fu.basis_z` | +0,043 | 2229 | -0,50 | +0,14 | -0,64 | -0,51 |
| `fu.basis_d60` | +0,042 | 2134 | -0,51 | +0,09 | -0,59 | -0,51 |
| `fu.tt_cnt_ls_d12` | +0,035 | 2178 | -0,49 | +0,18 | -0,58 | -0,51 |
| `tf.bigcnt_5` | -0,033 | 2626 | -0,49 | +0,09 | -0,57 | -0,51 |
| `fu.quad_60` | +0,031 | 2231 | -0,54 | +0,11 | -0,49 | -0,51 |
| `tf.absorb_buy_60` | +0,028 | 1783 | -0,47 | +0,18 | - | -0,51 |
| `tf.bigcnt_z_5` | -0,032 | 2178 | -0,53 | +0,17 | -0,44 | -0,51 |
| `tf.big_net_60` | -0,025 | 2179 | -0,55 | +0,05 | -0,47 | -0,51 |
| `fu.basis_bps` | +0,034 | 2628 | -0,42 | +0,21 | -0,63 | -0,51 |
| `tf.ntr_z_5` | -0,031 | 2210 | -0,47 | +0,22 | -0,46 | -0,51 |

**Değerlendirme bloğu B3**

| özellik (seçim) | seçim r | n (favori) | net favori | net−taban favori | net sakıncalı tersil | net tüm HA |
|---|---|---|---|---|---|---|
| `fu.basis_z` | +0,055 | 2216 | -0,58 | +0,24 | -0,68 | -0,62 |
| `fu.basis_bps` | +0,057 | 2621 | -0,59 | +0,13 | -0,72 | -0,62 |
| `fu.oi_val_log10` | +0,046 | 3407 | -0,57 | +0,26 | -0,68 | -0,62 |
| `fu.basis_d15` | +0,036 | 2329 | -0,60 | +0,19 | -0,67 | -0,62 |
| `fu.basis_d60` | +0,037 | 2263 | -0,52 | +0,30 | -0,74 | -0,62 |
| `fu.tt_cnt_ls_d12` | +0,035 | 2328 | -0,58 | +0,24 | -0,75 | -0,62 |
| `tf.absorb_buy_60` | +0,030 | 2002 | -0,54 | +0,30 | - | -0,62 |
| `fu.acc_ls_d12` | +0,033 | 2388 | -0,57 | +0,23 | -0,67 | -0,62 |
| `fu.fund_z` | +0,034 | 1462 | -0,56 | +0,26 | -0,57 | -0,62 |
| `fu.taker_ls_m60` | -0,024 | 2499 | -0,63 | +0,13 | -0,61 | -0,62 |

Tüm özellikler için (blok-dışı yön/kenar): favori tersilde HA neti **3 blokta birden pozitif olan özellik sayısı: 0**. En az kötü 6 (en kötü blok neti): `fu.quad_longliq_15` -0,46; `fu.basis_d60` -0,53; `tf.absorb_buy_60` -0,54; `tf.bigcnt_z_5` -0,54; `fu.quad_60` -0,54; `fu.tt_ls_z` -0,54.

### Kural arama rotasyonu (seçim bloğunda seç, diğer iki blokta dokunmadan değerlendir; her seçim bloğu için net ve net−taban hedefli 6'şar kural)

| seçim | hedef | kural | OOS blokları |
|---|---|---|---|
| B3 | net | `fu.tt_cnt_ls_d12 > -0.02309` | B1: n4163 net -0,49 (+0,40) / B2: n4535 net -0,48 (+0,16) |
| B3 | ex | `fu.basis_d60 > 5.575` | B1: n2000 net -0,53 (+0,39) / B2: n2173 net -0,52 (+0,09) |
| B3 | ex | `fu.tt_cnt_ls <= 0.3728` | B1: n2971 net -0,51 (+0,42) / B2: n2935 net -0,54 (+0,17) |
| B3 | net | `tf.bigcnt_z_5 <= 0.8169` | B1: n2156 net -0,54 (+0,38) / B2: n2254 net -0,53 (+0,16) |
| B3 | net | `fu.quad_60 > 1` | B1: n2019 net -0,51 (+0,44) / B2: n2231 net -0,54 (+0,11) |
| B3 | ex | `fu.quad_60 > 1` | B1: n2019 net -0,51 (+0,44) / B2: n2231 net -0,54 (+0,11) |
| B2 | ex | `tf.ntr_z_5 <= 0.8553` | B1: n2163 net -0,54 (+0,38) / B3: n2477 net -0,55 (+0,28) |
| B2 | ex | `fu.fund_z > 0.486` | B1: n1360 net -0,56 (+0,39) / B3: n1309 net -0,56 (+0,26) |
| B3 | net | `tf.bigbuy_share_60 <= 0.4703` | B1: n2035 net -0,53 (+0,39) / B2: n2169 net -0,56 (+0,05) |
| B3 | net | `fu.oi_chg_5 <= -0.04942` | B1: n1999 net -0,57 (+0,36) / B2: n2204 net -0,56 (+0,09) |
| B3 | ex | `fu.oi_chg_5 <= -0.04942` | B1: n1999 net -0,57 (+0,36) / B2: n2204 net -0,56 (+0,09) |
| B3 | net | `tf.bigcnt_z_15 <= 0.7962` | B1: n2176 net -0,57 (+0,34) / B2: n2174 net -0,52 (+0,19) |
| B1 | ex | `fu.acc_ls_d12 > 0.007491` | B2: n2282 net -0,51 (+0,17) / B3: n2436 net -0,57 (+0,23) |
| B2 | net | `tf.net_acc > 0.1591` | B1: n1835 net -0,52 (+0,30) / B3: n2457 net -0,57 (+0,15) |

(36 kuralın OOS'ta en iyi 14'ü; iki OOS blokta birden net>0: **0**. 548 aday kuralın seçim-sonrası ilk 300'ünde 3 blokta net>0: **0**.)

## 4. (c) Önceden belirlenmiş sinyaller (5 dk süpürme, 60 dk cooldown, TP1,5/SL3/T60 ve iz 1,0/0,8; gerçekçi doluş)

Eşikler SABİT (veriden ayarlanmadı); NaN = tetiklemez. Tanımlar:

- `whale_flat_abs`: balina alım patlaması: 5 dk net balina alımı >= 100 bin TRY ve fiyat yatay (|getiri5| <= %0,3) (cooldown öncesi ham tetik 141.802)
- `whale_flat_rel`: balina alım patlaması (göreli): 5 dk net balina alımı >= sembolün tipik 5 dk hacmi ve fiyat yatay (cooldown öncesi ham tetik 86.532)
- `whale_15`: 15 dk net balina alımı >= 200 bin TRY ve fiyat henüz <= %0,4 yükselmiş (cooldown öncesi ham tetik 174.962)
- `bigbuy_dom`: büyük işlem alım baskınlığı: 15 dk büyük-alım payı >= %80, >= 3 büyük işlem, alıcı payı >= %60 (cooldown öncesi ham tetik 398.728)
- `absorb_buy`: emilim: 15 dk büyük-alım payı >= %70, >= 2 büyük işlem, fiyat düşmüyor/yatay (getiri15 <= 0) (cooldown öncesi ham tetik 323.423)
- `flow_surge`: akış ivmesi: alıcı payı15 >= %65, ivme >= 0,10 ve işlem sayısı z15 >= 1,5 (cooldown öncesi ham tetik 46.549)
- `oi_px_up`: fiyat↑ + OI↑ (15 dk: getiri >= %0,5, OI >= +%0,5) ve fonlama aşırı değil (z <= 1,5, <= 5 bps) (cooldown öncesi ham tetik 70.098)
- `short_cover`: short kapatma sıkışması: getiri15 >= %0,5, OI15 <= -%0,3, taker L/S ivmesi > 0 (cooldown öncesi ham tetik 47.463)
- `bid_imb`: defter alış dengesizliği ±%2 >= 0,3 ve yükseliyor (3 bar) (cooldown öncesi ham tetik 311.682)
- `crowded_short`: kalabalık short: fonlama <= -2 bps ve OI60 >= +%1 (cooldown öncesi ham tetik 38.294)
- `basis_lead`: perp primi TRY spotun önünde: baz değişimi15 >= +15 bps ve baz z >= 1,5 (cooldown öncesi ham tetik 211.589)
- `taker_surge`: vadeli taker L/S z >= 2 (cooldown öncesi ham tetik 128.429)
- `big_oi`: büyük-alım payı15 >= %70 ve OI15 >= +%0,3 (cooldown öncesi ham tetik 96.277)

Sütunlar: tetik/gün (60 dk cooldown sonrası); kesinlik60 = tetikten sonraki 60 dk içinde olay (t0) başlama oranı (rastgele giriş / koşulsuz); hit60@1,5 şans farkı (pp, oynaklık-eşleşmiş null); net = exit_sim ortalaması (sinyal / sayı-eşleşmiş rastgele giriş); izleyen = trailing 1,0/0,8. t0'dan ÖNCE yakalama = olayların t0−60..t0 arasında sinyal alan payı (sayı-eşleşmiş sıfır); HA'dan önce = ortak yakalanan olaylarda sinyalin HA'dan önce gelme payı.

| sinyal | blok | tetik/gün | kesinlik60 (rastg. / koşulsuz) | hit şans farkı pp | net TP1,5 (sinyal / rastgele) | net izleyen (sinyal / rastgele) | t0 öncesi yakalama (sıfır) | HA'dan önce | medyan öncelik dk |
|---|---|---|---|---|---|---|---|---|---|
| `whale_flat_abs` | B1 | 700 | 1,5% (0,7% / 0,9%) | +0,4 | -0,52 / -0,53 | -0,53 / -0,54 | 27,0% (16,2%) | 39% | 30 |
|  | B2 | 859 | 2,0% (0,5% / 1,1%) | +3,4 | -0,49 / -0,51 | -0,51 / -0,52 | 29,1% (16,0%) | 40% | 30 |
|  | B3 | 1035 | 2,0% (0,6% / 1,3%) | +2,4 | -0,51 / -0,53 | -0,51 / -0,53 | 29,5% (15,5%) | 43% | 35 |
| `whale_flat_rel` | B1 | 666 | 0,5% (0,9% / 0,9%) | -1,7 | -0,54 / -0,54 | -0,55 / -0,55 | 8,7% (9,9%) | 41% | 35 |
|  | B2 | 699 | 1,0% (0,9% / 1,1%) | +0,7 | -0,50 / -0,52 | -0,51 / -0,53 | 12,1% (10,2%) | 43% | 35 |
|  | B3 | 770 | 1,1% (1,1% / 1,3%) | +0,8 | -0,51 / -0,53 | -0,52 / -0,54 | 11,8% (11,5%) | 44% | 35 |
| `whale_15` | B1 | 527 | 2,5% (0,5% / 0,9%) | +1,1 | -0,52 / -0,53 | -0,52 / -0,55 | 32,0% (14,4%) | 34% | 35 |
|  | B2 | 678 | 2,7% (0,6% / 1,1%) | +3,0 | -0,48 / -0,51 | -0,49 / -0,52 | 29,7% (15,5%) | 35% | 30 |
|  | B3 | 840 | 2,6% (0,6% / 1,3%) | +1,8 | -0,52 / -0,52 | -0,52 / -0,53 | 31,8% (12,9%) | 36% | 30 |
| `bigbuy_dom` | B1 | 1317 | 0,7% (1,5% / 0,9%) | -1,0 | -0,53 / -0,55 | -0,55 / -0,55 | 23,5% (28,2%) | 74% | 35 |
|  | B2 | 1652 | 1,0% (1,6% / 1,1%) | +1,1 | -0,50 / -0,54 | -0,52 / -0,55 | 27,7% (27,2%) | 77% | 35 |
|  | B3 | 1809 | 1,0% (2,0% / 1,3%) | +1,1 | -0,50 / -0,56 | -0,51 / -0,55 | 27,3% (26,2%) | 76% | 30 |
| `absorb_buy` | B1 | 1314 | 0,7% (1,9% / 0,9%) | -0,3 | -0,50 / -0,47 | -0,52 / -0,47 | 21,7% (24,2%) | 69% | 30 |
|  | B2 | 1605 | 1,0% (2,1% / 1,1%) | +1,6 | -0,47 / -0,46 | -0,48 / -0,46 | 26,9% (26,3%) | 69% | 30 |
|  | B3 | 1724 | 1,0% (2,3% / 1,3%) | +2,5 | -0,48 / -0,45 | -0,49 / -0,45 | 24,4% (25,4%) | 67% | 30 |
| `flow_surge` | B1 | 233 | 1,1% (0,9% / 0,9%) | -0,8 | -0,49 / -0,52 | -0,52 / -0,53 | 6,4% (5,1%) | 43% | 25 |
|  | B2 | 276 | 1,7% (0,7% / 1,1%) | +2,4 | -0,45 / -0,51 | -0,46 / -0,52 | 7,6% (4,7%) | 47% | 30 |
|  | B3 | 293 | 1,8% (0,9% / 1,3%) | +1,6 | -0,50 / -0,51 | -0,50 / -0,52 | 7,5% (4,9%) | 47% | 35 |
| `oi_px_up` | B1 | 246 | 4,0% (0,4% / 0,9%) | +3,6 | -0,55 / -0,55 | -0,56 / -0,56 | 25,4% (7,8%) | 42% | 30 |
|  | B2 | 310 | 4,1% (0,6% / 1,1%) | +4,9 | -0,49 / -0,55 | -0,52 / -0,56 | 23,0% (6,4%) | 53% | 35 |
|  | B3 | 347 | 4,1% (0,6% / 1,3%) | +7,0 | -0,52 / -0,56 | -0,50 / -0,57 | 21,0% (7,1%) | 51% | 30 |
| `short_cover` | B1 | 225 | 3,1% (0,5% / 0,9%) | +0,3 | -0,56 / -0,54 | -0,56 / -0,56 | 17,9% (8,8%) | 42% | 35 |
|  | B2 | 338 | 2,6% (0,9% / 1,1%) | +2,2 | -0,51 / -0,51 | -0,53 / -0,52 | 16,3% (6,7%) | 46% | 35 |
|  | B3 | 377 | 3,0% (1,0% / 1,3%) | -0,7 | -0,57 / -0,51 | -0,58 / -0,53 | 16,7% (8,4%) | 42% | 30 |
| `bid_imb` | B1 | 728 | 1,5% (1,2% / 0,9%) | +0,9 | -0,49 / -0,50 | -0,51 / -0,52 | 26,5% (21,6%) | 50% | 30 |
|  | B2 | 1019 | 1,4% (1,3% / 1,1%) | +2,2 | -0,51 / -0,48 | -0,52 / -0,49 | 24,8% (18,7%) | 60% | 30 |
|  | B3 | 801 | 1,8% (1,3% / 1,3%) | +3,6 | -0,48 / -0,49 | -0,49 / -0,50 | 20,3% (19,6%) | 56% | 30 |
| `crowded_short` | B1 | 78 | 6,1% (1,6% / 0,9%) | +6,0 | -0,52 / -0,53 | -0,47 / -0,54 | 11,5% (2,6%) | 34% | 35 |
|  | B2 | 48 | 5,3% (1,1% / 1,1%) | +8,7 | -0,56 / -0,47 | -0,56 / -0,48 | 4,4% (2,1%) | 27% | 30 |
|  | B3 | 49 | 7,7% (1,3% / 1,3%) | +10,6 | -0,58 / -0,47 | -0,52 / -0,47 | 5,7% (1,8%) | 25% | 30 |
| `basis_lead` | B1 | 1117 | 1,1% (1,3% / 0,9%) | +5,9 | -0,32 / -0,54 | -0,34 / -0,55 | 28,3% (24,6%) | 51% | 30 |
|  | B2 | 1444 | 1,3% (1,4% / 1,1%) | +10,1 | -0,32 / -0,52 | -0,33 / -0,53 | 30,5% (26,3%) | 56% | 25 |
|  | B3 | 1544 | 1,4% (1,6% / 1,3%) | +10,0 | -0,31 / -0,50 | -0,32 / -0,51 | 28,5% (25,3%) | 58% | 30 |
| `taker_surge` | B1 | 641 | 0,7% (1,1% / 0,9%) | -0,0 | -0,48 / -0,53 | -0,49 / -0,55 | 10,8% (13,5%) | 68% | 35 |
|  | B2 | 776 | 0,8% (1,4% / 1,1%) | +1,3 | -0,47 / -0,52 | -0,49 / -0,53 | 11,1% (14,0%) | 68% | 35 |
|  | B3 | 824 | 1,0% (1,6% / 1,3%) | +2,1 | -0,44 / -0,54 | -0,44 / -0,54 | 12,0% (13,4%) | 68% | 35 |
| `big_oi` | B1 | 403 | 1,6% (0,5% / 0,9%) | +1,5 | -0,52 / -0,56 | -0,54 / -0,56 | 16,0% (9,8%) | 56% | 35 |
|  | B2 | 563 | 2,0% (0,6% / 1,1%) | +3,8 | -0,48 / -0,53 | -0,50 / -0,54 | 18,9% (9,8%) | 60% | 30 |
|  | B3 | 625 | 2,1% (0,9% / 1,3%) | +3,4 | -0,52 / -0,55 | -0,51 / -0,56 | 18,8% (10,7%) | 59% | 30 |
| `HA (canlı-benzeri)` | B1 | 204 | 6,6% (0,3% / 0,9%) | +3,5 | -0,54 / -0,57 | -0,54 / -0,59 | 32,3% (7,1%) | - | 30 |
|  | B2 | 227 | 6,7% (0,5% / 1,1%) | +4,6 | -0,50 / -0,52 | -0,54 / -0,54 | 26,4% (6,0%) | - | 35 |
|  | B3 | 256 | 6,7% (0,6% / 1,3%) | +5,4 | -0,56 / -0,55 | -0,54 / -0,56 | 25,7% (6,8%) | - | 30 |

Koşulsuz rastgele giriş (TP1,5): -0,51 / -0,48 / -0,49 (B1/B2/B3). Net-pozitif sinyal sayısı (3 blokta): **0**.

Okuma: 60 dk önden kesinliği 3 blokta da rastgele girişin >= 2 katı olanlar: `whale_flat_abs` (x2,4/3,6/3,3), `whale_15` (x4,8/4,6/4,3), `oi_px_up` (x10,1/6,7/6,4), `short_cover` (x6,2/3,1/3,0), `crowded_short` (x3,8/5,1/6,1), `big_oi` (x3,2/3,3/2,3). HA ise kesinlik 6,6%/6,7%/6,7%. 'Kanıtlı erken uyarı' ölçütü (t0 öncesi yakalama > sayı-eşleşmiş sıfır x1,5 VE ortak olayların >%50'sinde HA'dan önce, her blokta): **big_oi**. Doygun sinyallerde (`bigbuy_dom`, `absorb_buy`, `taker_surge`) 'HA'dan önce' %67-77 görünür ama t0 öncesi yakalama sıfırla aynı: sinyal her yerde tetiklendiği için bilgi taşımaz.

## 5. Koşulsuz zamanlama — özellik uçları ve sonraki 60 dk (tüm geçerli anlar, 15 dk'da bir örnek, n=1.733.226)

Brüt kapanıştan-kapanışa 60 dk getiri (%) — uç beşte-birlik (üst/alt %20 ve %5) eksi blok ortalaması; blok ortalaması -0,004 / +0,025 / +0,022 (B1/B2/B3). Maliyet duvarı ≈ %0,525 (2×ücret %0,1125 + 2×kayma %0,15). Yön önceden seçilmedi: iki uç da gösterilir (yalnız long yapılabilir).

| özellik | üst %5 | üst %20 | alt %20 | alt %5 |
|---|---|---|---|---|
| `fu.basis_z` | +0,34 / +0,36 / +0,40 | +0,22 / +0,21 / +0,23 | -0,22 / -0,22 / -0,24 | -0,38 / -0,37 / -0,41 |
| `fu.basis_d15` | +0,27 / +0,30 / +0,31 | +0,16 / +0,16 / +0,17 | -0,17 / -0,17 / -0,17 | -0,36 / -0,31 / -0,29 |
| `fu.basis_d60` | +0,30 / +0,29 / +0,35 | +0,17 / +0,16 / +0,18 | -0,19 / -0,17 / -0,18 | -0,41 / -0,32 / -0,31 |
| `fu.oi_chg_15` | -0,07 / -0,01 / -0,08 | -0,01 / +0,00 / -0,03 | -0,01 / +0,02 / -0,00 | -0,04 / +0,04 / +0,04 |
| `fu.oi_chg_60` | -0,07 / -0,03 / -0,08 | -0,01 / +0,00 / -0,03 | +0,00 / +0,01 / +0,00 | -0,03 / +0,05 / +0,01 |
| `fu.taker_ls_z` | +0,04 / +0,02 / +0,07 | +0,03 / +0,01 / +0,04 | -0,02 / -0,01 / -0,02 | -0,03 / -0,03 / -0,01 |
| `fu.tt_ls_d12` | -0,10 / -0,01 / -0,01 | -0,03 / -0,00 / -0,00 | +0,02 / +0,02 / -0,02 | -0,03 / +0,02 / -0,06 |
| `fu.fund_bps` | +0,00 / +0,03 / -0,01 | +0,01 / +0,01 / -0,00 | -0,02 / -0,03 / +0,00 | -0,06 / -0,06 / -0,04 |
| `fu.bd_imb2` | +0,02 / -0,04 / +0,00 | +0,02 / -0,01 / +0,00 | -0,02 / -0,00 / -0,01 | -0,05 / -0,03 / -0,03 |
| `fu.bd_imb2_d3` | -0,03 / -0,02 / -0,01 | -0,00 / -0,00 / +0,00 | -0,01 / -0,00 / +0,00 | -0,03 / -0,02 / -0,00 |
| `tf.ntr_z_15` | -0,10 / +0,01 / -0,10 | -0,03 / +0,01 / -0,03 | -0,00 / +0,01 / +0,02 | -0,01 / +0,01 / +0,02 |
| `tf.bigcnt_z_15` | -0,07 / +0,00 / -0,11 | -0,02 / -0,00 / -0,02 | +0,00 / +0,00 / +0,00 | -0,03 / +0,01 / -0,00 |
| `tf.whale_net_rel_5` | -0,06 / -0,07 / -0,08 | +0,00 / -0,00 / -0,00 | +0,01 / +0,01 / +0,01 | +0,02 / +0,05 / +0,04 |
| `tf.whale_net_rel_60` | -0,06 / -0,04 / -0,11 | -0,03 / -0,02 / -0,04 | +0,01 / +0,03 / +0,02 | +0,01 / +0,06 / +0,01 |
| `tf.buy_share_15` | -0,06 / -0,06 / -0,05 | -0,03 / -0,03 / -0,02 | +0,05 / +0,04 / +0,03 | +0,09 / +0,07 / +0,06 |
| `tf.bigbuy_share_15` | -0,02 / -0,02 / -0,01 | -0,02 / -0,02 / -0,01 | +0,04 / +0,03 / +0,03 | +0,04 / +0,03 / +0,02 |
| `tf.absorb_buy_15` | +0,01 / -0,00 / +0,01 | +0,03 / +0,02 / +0,01 | -0,01 / -0,02 / -0,02 | -0,01 / -0,02 / -0,02 |
| `tf.net_acc` | -0,02 / -0,02 / -0,01 | -0,01 / -0,01 / +0,00 | +0,02 / +0,02 / +0,01 | +0,03 / +0,02 / +0,01 |
| `tf.cvd_slope_60` | -0,03 / -0,02 / -0,02 | -0,01 / -0,02 / -0,01 | +0,03 / +0,03 / +0,02 | +0,05 / +0,04 / +0,03 |

**Baz (perp primi) uçlarında gerçekçi doluşlu net** (60 sn gecikme, %0,15 kayma, ücret; her hücre B1 / B2 / B3):

| küme | TP1.5 SL3 T60 | TP2.0 SL3 T60 | iz act1.0 gap0.8 SL3 T60 | 60 dk tut SL3 |
|---|---|---|---|---|
| `rastgele` | -0,51 / -0,49 / -0,50 | -0,51 / -0,49 / -0,50 | -0,52 / -0,50 / -0,50 | -0,52 / -0,51 / -0,52 |
| `fu.basis_z top5` | -0,32 / -0,30 / -0,29 | -0,32 / -0,30 / -0,29 | -0,34 / -0,31 / -0,29 | -0,34 / -0,31 / -0,29 |
| `fu.basis_z top20` | -0,38 / -0,37 / -0,36 | -0,38 / -0,37 / -0,37 | -0,40 / -0,38 / -0,37 | -0,39 / -0,38 / -0,37 |
| `fu.basis_z bot20` | -0,64 / -0,60 / -0,63 | -0,64 / -0,60 / -0,63 | -0,65 / -0,61 / -0,63 | -0,67 / -0,62 / -0,65 |
| `fu.basis_d15 top5` | -0,31 / -0,31 / -0,33 | -0,31 / -0,31 / -0,33 | -0,36 / -0,35 / -0,34 | -0,37 / -0,35 / -0,34 |
| `fu.basis_d60 top5` | -0,30 / -0,31 / -0,28 | -0,30 / -0,31 / -0,29 | -0,35 / -0,33 / -0,29 | -0,34 / -0,33 / -0,30 |
| `fu.taker_ls_z top5` | -0,49 / -0,48 / -0,43 | -0,49 / -0,48 / -0,44 | -0,50 / -0,49 / -0,44 | -0,50 / -0,50 / -0,45 |
| `tf.ntr_z_15 top5` | -0,51 / -0,42 / -0,52 | -0,52 / -0,42 / -0,53 | -0,53 / -0,44 / -0,54 | -0,58 / -0,48 / -0,60 |
| `tf.buy_share_15 top5` | -0,56 / -0,53 / -0,54 | -0,56 / -0,53 / -0,54 | -0,58 / -0,54 / -0,54 | -0,57 / -0,54 / -0,54 |
| `tf.buy_share_15 bot5` | -0,45 / -0,43 / -0,45 | -0,45 / -0,43 / -0,45 | -0,46 / -0,45 / -0,46 | -0,45 / -0,44 / -0,46 |

Gün-kümeli SE (TP1,5, `fu.basis_z top5`): B1 ±0,014 (n=22801, kazanç 30,6%), B2 ±0,026 (n=25000, kazanç 35,8%), B3 ±0,025 (n=25000, kazanç 37,1%).

**Yayın gecikmesi duyarlılığı** (tüm vadeli özellikler +1 bar = 5 dk geç bilinirse), baz uçları, TP1,5 neti B1 / B2 / B3: `fu.basis_z top5`: -0,32 / -0,30 / -0,29 → gecikmeli -0,40 / -0,33 / -0,36; `fu.basis_d15 top5`: -0,31 / -0,31 / -0,33 → gecikmeli -0,42 / -0,40 / -0,46. Brüt üst-%5 farkı (lead): `fu.basis_z` +0,14 / +0,23 / +0,20; `fu.basis_d15` +0,06 / +0,08 / +0,05.

**Yanlış hizalama kontrolü** (ts_ms'i bar KAPANIŞI sanıp satırı 1 bar erken bağlamak = 5 dk ileriye bakış): brüt uç-%5 farkı `fu.basis_z` doğru +0,34 / +0,36 / +0,40 → yanlış +0,77 / +0,83 / +0,81; `fu.basis_d15` doğru +0,27 / +0,30 / +0,31 → yanlış +0,69 / +0,67 / +0,64; `fu.oi_chg_15` doğru -0,07 / -0,01 / -0,08 → yanlış +0,05 / +0,10 / +0,06; `fu.taker_ls_z` doğru +0,04 / +0,02 / +0,07 → yanlış +0,17 / +0,17 / +0,21. Yani doğru hizalama zorunlu; naif bağlama baz/OI/taker özelliklerini yapay biçimde şişirirdi.

## 6. Karar, anlam ve öneri

1. **Net-pozitif kenar yok.** Brüt kenarın en iyisi (vadeli primi, uç %5) 60 dakikada ≈ +%0,2…0,4; maliyet ≈ %0,525. En iyi uçta bile TP1,5 neti -0,32…-0,29; rastgele -0,51…-0,49. Bu, `USD_LEADLAG_ARASTIRMASI` ve `GENIS_PENCERE` bulgularıyla aynı: gerçek mekanizma, maliyete mahkûm.

2. **Ana tahmin motoruna beslemeye değer mi?** Hayır. Olay öngörüsünde mevcut 154 özelliğe eklenen bilgi t0−10'da +tf +0,0009 [-0,0054; +0,0074], +fu +0,0029 [-0,0037; +0,0097] (aynı alt küme, havuz, %95 aralık sıfırı içerir ya da ihmal edilebilir); t0'da yalnız +fu küçük pozitif (+0,0038 [+0,0009; +0,0068]). Tek başına tf+fu özellikleri 154'ten ≈0,05 AUC düşük. Tek tek özelliklerde görünen en güçlü yapı (işlem-sayısı z-skoru) zaten mevcut oynaklık/hacim özelliklerinin başka bir ölçüsü.

3. **HA'yı güçlendirir mi?** Kısmen *sıralar* (baz/perp primi yüksekse HA'nın taban üstü kazancı büyük: kısmi r≈+0,05, 3/3 blok), ama mutlak net değişmez (en iyi favori tersil bile her blokta negatif). Aşırı-uyum tanısı için: 548 aday kuralda 3 blokta net>0 sayısı 0.

4. **Canlı günlüğe (journal) yazmak** ancak gelecekteki bir doğrulama için bilgi birikimi amacıyla anlamlı olur ve yalnız ucuz/hazır alanlar için: `fu.basis_*` (tek özellik, GLOBAL_LEAD_LAG zaten aynı bilgiyi taşır), `fonlama` ve `OI` (tek satır sorgusu, 5 dk) — ölçülen etkileri ihmal edilebilir olduğundan öncelik düşük. Defter/işlem-akışı özellikleri için canlı toplama maliyeti (REST ağırlığı, depolama) kazanımla orantısız. Önerilmez.

### Kısıtlar ve uyarılar

- Perp küresel USDⓈ-M; TRY defteri/gerçek TRY derinliği değil. Gerçek TRY defter geçmişi yalnız ücretli sağlayıcılardan (bkz. VADELI_GECMIS_VERI).
- 90 gün, 3 blok; olay sayısı 4552 (taban ≤20/olay). Blok-dışı HGB gelecekten de eğitim görür (ileri-yürüyen sürüm ayrıca verildi; sonuç aynı yönde).
- 'Aynı alt küme' = işlem akışı ve vadeli verisi olan olaylar (95,8%); perp'i olmayan tabanlar ayrı raporlandı (tam küme).
- Sinyal eşikleri bilinçli SABİT ve gevşek tutuldu; bu yüzden günde yüzlerce tetik (306 sembol × 60 dk cooldown) üretiyor. Daha sıkı eşikler tetik sayısını düşürür ama 3 blokta net-pozitif sinyal çıkması için gerekli brüt kenar (≥ +%0,53) hiçbir ucun brüt farkına (≤ +%0,4) yaklaşmıyor.
- BH düzeltmesi tf+fu ortak (94 özellik) / HA için 94; permütasyon p tabanı 1/1001 olduğundan q=0,004 tabanı 'çok anlamlı' demektir, etki büyüklüğü AUC sapması ile okunmalıdır.

Kaynaklar: `backend/app/rescan/flow_futures.py` (kurucular), `backend/tests/test_flow_futures.py`, `backend/scripts/flowfut_study.py`, ham çıktılar `backend/work/flowfut/*.pkl`.
