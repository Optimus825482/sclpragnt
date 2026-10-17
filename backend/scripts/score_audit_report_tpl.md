# Radar bildirim skoru denetimi (2026-10-18)

Çevrimdışı araştırma: canlı kod değişmedi, DB'ye yazılmadı. Tablolar `backend/scripts/score_audit.py` ile yeniden üretilir
(`backend/.venv/Scripts/python.exe backend/scripts/score_audit.py [--refresh]`); aşağıdaki YORUM metinleri 2026-10-18 çalıştırmasının sayılarına dayanır.
Tüm AUC/oranlarda ± = gün-kümeli SE (gün silmeli jackknife; oranlarda küme-dayanıklı SE). n her tabloda verilmiştir.

## 0. Hüküm

**Karar: skor "kalite/isabet" göstergesi değildir; ölçeklenmiş bir OYNAKLIK (ATR) endeksidir. Bildirimde "yüksek skor = iyi fırsat" diye sunulmamalı. Net getiriye göre skorun yerine geçen, dışarıda-örneklemde POZİTİF net veren hiçbir model yok; elde edilebilen tek sağlam kazanç isabet-olasılığı sıralamasında (AUC +0,06…+0,12) ve o da neredeyse tamamen "hedef/ATR geometrisi"nden geliyor.**

1. **Ayrım gücü ≈ yalnız ATR.** Panel skoru → `touched_target` AUC'u: DB canlı 0,47–0,56 (işaret SL rejimine göre değişiyor: SL %1,5'te <0,5, SL %5'te >0,5), replay (SL'siz dokunuş) 0,59–0,60. ATR (hz × ATR beşlisi) kontrol edilince 0,48–0,52 / 0,49–0,52 → şansa yakın. `net>0` AUC 0,47–0,53 (ATR-strata 0,48–0,50). ln(ham skor) varyansının %10–42'si yalnız ln(ATR) ile açıklanıyor; ATR dışındaki kalan çarpım (BB oranı × yapı × hacim × çarpanlar) ATR kontrollü AUC 0,497, lojistik β negatif (replay: −0,06, t=−3,5).
2. **Net ile ters ilişki (yüksek skorda ortalama net daha kötü).** SL %5 bloklarında panel ondalığı ↔ ort. net: ρ=−0,83 / −0,88; panel=100 kovasında ort. net −0,83…−1,32 iken panel<60'ta −0,37. Başabaş isabet (p* = −E[net|ıska]/(E[net|isabet]−E[net|ıska])) SL %5 rejiminde %61–73 iken gözlenen en iyi isabet %60; yüksek skorlu kovalarda başabaş isabet isabetle aynı hızda/daha hızlı yükselir (panel≥85: %69–72; panel=100: %72–73) çünkü kayıplar büyür, kazançlar büyümez → skor eşiğini yükseltmek (≥85/≥95) isabeti SL %5'te +6–7 puan artırır ama neti iyileştirmez (B3 ort. net: tümü −0,55 / ≥85 −0,75 / =100 −1,08; R2b: −0,60 / −0,88 / −1,32).
3. **Hiçbir şey pozitif net üretmiyor.** Tüm katlama × tahmin çiftlerinde en iyi üst-%10 ort. net −0,36 (±0,12); alt %95 sınırı >0 olan çift yok.
4. **Yeniden eşleme (isotonic skor→olasılık) işe yaramıyor:** Brier becerisi DB'de %0,3, replay'de %2,0; taban isabet oranı etiket rejimiyle kayıyor (SL %1,5: %29–36 → SL %5: %46–53) ve skor 85'ten sonra düzleşiyor (SL5: 85–90 → %56,7; 90–95 → %56,4; 95–99,9 → %58,9; =100 → %57,5).
5. **Bimodalite (70→0%, 85→14%, 90→20%, 95→15%, 100→40%) üç şeyin karışımı:** (a) "70" kovası (score=74,0, n=56) gerçek sinyal değil: BTCTRY/ETHTRY, `message='radar'`, aynı dakikada 4'lü yinelenen duman/test satırları; (b) `unified` (füzyon) satırları (n=126, isabet ≈%4, AUC 0,47) 85–99,9 kovalarını aşağı çekiyor; (c) panel=100 = ham skor ≥ 25 000 (kırpma) → tek kovada ham 25 bin…66 milyon; medyan ATR %1,53 (85–99,9'da %0,74) — yani "100" kovasının yüksek isabeti oynaklığın en uç kuyruğu. Saf velocity/trend_devam bildirimleri tek yönlü artıyor: %16,1 → %19,2 → %24,6 → %45,7.

### Özet tablo (otomatik)
{{verdict_tbl}}

Yürüyen-ileri (eğitim: önceki bloklar; test: sonraki blok; üst %10 = tahminin en yüksek %10'u, ort. net %):
{{verdict_wf}}

{{best_net}}

## 1. Kod zinciri (dosya:satır) — ekranda görünen skor nasıl oluşuyor

**A. Ham `velocity_score` (app/routers/velocity.py, `scan_one` içinde, sınırsız çarpım):**
- :722 `prof_atr` (profil bazlı ATR eşiği, vars. 0,25; DB'den kalibre); :779 `bb_ratio = BBgenişlik% / 2,5`; :780 `struct_ratio = max(0, slope/0,20, aroon_up/50)`; :783 `atr_ratio = atr_pct / prof_atr`; :792 `momentum = max(0, ret3, ret5)`; :801–802 `momentum_ratio = min(2,5, momentum / max(prof_atr, 0,4))`; hacim oranı son bar / 20 bar ort. (:796).
- **:803–806** `velocity_score = 100 × atr_ratio × bb_ratio × (0,2 + 0,8·struct_ratio) × (0,5 + 0,5·momentum_ratio) × (0,5 + 0,5·min(1, hacim_oranı/2))` — saturation 2026-09-07'de kaldırıldı, ÜST SINIR YOK.
- Çarpanlar (sırayla): MACD teyidi ×1.15 / ×1.05 / ×0.85 (:807–814); M5 MACD hizası ×1.10 (:877); öncü ATR (`leading_ok`) ×1.15 (:904–905); aşırı alım cezası ×0,85 (:1146–1148, `VELOCITY_EXHAUSTION_MODE=penalty` iken; vars. `block`, config.py:893–894); taker teyidi ≥0,58 ×1,05 / ≤0,45 ×0,95 (:1153–1165, config.py:288–291); choppiness>61,8 ∧ ADX<20 ×0,5 (:1171–1186, config.py:282); geç faz (24s ≥%40) ×0,6 (:1192–1195, config.py:299); spread bilinmiyor ×0,85 (:1199–1201, config.py:304). **ML ayarı yok:** "ML sıralama bonusu KALDIRILDI" (:1134–1138); ML yalnız hedefi etkiler.
- Hedef `dynamic_target_pct` (:2621) — skor bandı (74,0→4,0; 71,5→2,5; 68,2→2,0; config.py:425–426), net-kâr tabanı, **ATR×1,35**, öğrenilmiş/ML harmanı: hedef hem skora hem ATR'ye bağlı → "hit" etiketi hedefin kendisinden de etkilenir (bu denetimde ATR×hedef-strata ile kontrol edildi).
- Kapı (`passes`, :746–754): ATR ≥ eşik (kırılışta gevşer), BB ≥ %2,5, yapı teyidi, aşırı uç yok, üst fitil yok.

**B. Sıralama / aday seçimi:** :1325 `micro_mult` (whale var ×1,05, `no_whale` ×0,9: config.py:441–442; yalnız SIRALAMA, skora girmez); :1329 adaylar `velocity_score × micro_mult` ile sıralanır, `rank` 1…`limit` (≤10, :1275–1331); izleme listesi eşiği `_panel_to_raw_score(0,6)` (:1338–1340, pratikte her elenen aday). `upside_rank_score` (:2453–2481) = (hedef/ufuk) × ham skor × `_quality_multiplier`(sembol dokunuş oranı 0,4…1,3) × `micro_structure_multiplier` — chat/liste sıralaması içindir; bildirim skoru DEĞİL.

**C. 0–100 panel eşlemesi:** app/unified_scan.py:39–60 (kanonik; routers/monitoring.py:220 delege eder; velocity.py:303 `_panel_score` replika): `panel = round(clip(100·ln(1+ham)/ln(1+25000), 0, 100), 1)` (`MONITORING_SCORE_NORM_LOG_REF=25000`, config.py:378; `norm_version=2`, monitoring.py:217, 1587). Her +5 panel puanı ham ×1,65; **panel=100 ⇔ ham ≥ 25 000 (kırpma)**.
{{mapping}}

**D. Bildirimde hangi skor:** routers/monitoring.py `_build_notification` (:1488) → **:1499–1500** `score = unified_score if unified_pass else normalize_score(velocity_score)`; başlık/mesajda `Skor: {score:.1f}` (:1546) ve `+%{target}` / `| ML %{..}` (başlık). Eşik: :1818–1832 (`raw ≥ min_raw` ∧ `panel ≥ eff_min_score`, vars. `MONITORING_MIN_SCORE_DEFAULT=71,5`, config.py:390). Yani radar adayında bildirim skoru = **panel(ham velocity_score)**; çoklu kaynak (jump/early/rising) skoru DEĞİŞTİRMEZ (yalnız `sources` listesini ve politika kapısını etkiler).

**E. Füzyon-tek ("unified") adaylar:** app/unified_signals.py:133–175 `fusion_score` = Σ(w·skor)/Σw (velocity 0,50; jump/early/rising 0,25; config.py:818–821), ≥2 kaynakta **×1,15 sinerji** (:171, config.py:823), tavan 100; 4'lü teyitte `composite_index` büyükse skorun yerine geçer (:323). Bu satırlar `unified_pass=True` ile radar kapısını atlar (monitoring.py:1813–1832). Birleşik liste (`combined_scan_rows`, unified_scan.py:228–): `_combined_quality_score` (:147–173) = 0,6·panel + 8·min(3,kaynak) + 4·min(4,Master Surge katmanı) + aile bonusu (≤+6) (+ jump/velocity bonusu, vars. 0), tavan 99 → `scan_score` (journal `unified_candidate_outcomes.scan_score`); bildirim skoru değildir.

**F. Politika tabanları (app/notification_policy.py, config.py:572–600):** `unified` modu panel ≥ 95 (`RADAR_NOTIFY_UNIFIED_MIN_SCORE`); ≥2 farklı kaynak + `velocity` şartı (`confirm_rule_reason`); **ikinci kademe** tek kaynak Hız için panel ≥ 85 (`single_source_tier_ok`, `RADAR_NOTIFY_SINGLE_SOURCE_MIN_SCORE=85`); 30 dk sessizlik nabzı (`heartbeat_pick`); kapalı modlar notr/v_donusu/llm_ikinci_goz.

**G. Veri kusurları (ölçüm sırasında bulundu):**
- `velocity_candidates.volume_ratio` **tüm satırlarda 0,0**: journal satırı `"volume_ratio": 0.0` sabitiyle yazılıyor (velocity.py:1371). Skorun hacim terimi DB'den doğrudan ölçülemiyor (yalnız 17 Eki sonrası `features` JSON'unda ve replay'de var).
- `outcome_details.features` (mod, taker, defter, rsi…) yalnız 17 Eki'den itibaren (≈1,3 bin ana satır); `mode` eski satırlarda yok; `m1_atr_prev/m3_atr_prev` NULL.
- **Etiket rejimi 3 kez değişti:** 09-17..09-21 eski ölçüm (status_reason yok, net dağılımı tutarsız) → atıldı; 09-22/23..10-06 SL %1,5 + maliyet %0,35; 10-07 geçiş (SL %5'e); 10-08.. SL %5; 10-16'dan itibaren TP maliyeti %0,275. İstenen B1/B2/B3 blokları bu yüzden etiket-karışık (B2: SL1,5→SL5; B3: SL5); karşılaştırma için etiket-homojen **R1a** 09-23..09-29, **R1b** 09-30..10-06 (SL1,5), **R2a** 10-08..10-12, **R2b** 10-13..10-17 (SL5) blokları da raporlandı.

## 2. Veri ve yöntem
- **A) DB canlı (`velocity_candidates`, status=evaluated, passes ∧ rank≤10, status_reason dolu):** n≈110 bin, 26 gün. Etiketler: `touched_target` (TP SL'den önce, 60 dk pencere), `net_pct>0`. **B) Replay 90 g** (`work/indfilter/events_ha.pkl`, rank≤10, aşırı alım yok; tek tip exit_sim: hit=60 dk içinde hedef dokunuşu, SL %3 net): n=20 343, 3×~30 gün; mod/taker/choppiness/rsi vb. burada var. **C) bildirimler** 765 sonuçlu satır (709 gerçek), `unified_candidate_outcomes` 14 004 satır (yalnız 3 gün!).
- **ATR kontrolü:** strata = ufuk × blok-içi ATR beşlisi (ikinci sürüm: × hedef bandı); strata-içi AUC'ler n1·n0 ağırlıklı ortalanır. Lojistik katsayılar: ATR + ufuk + rejim kontrollü, gün-kümeli sandwich SE.
- **Yürüyen-ileri:** DB B1→B2, B1+B2→B3 (istenen) ve etiket-homojen R1a→R1b, R2a→R2b; replay b0→b1, b0+b1→b2. Modeller: lojistik (C=0,5), HistGradientBoosting (150 iter., lr 0,06, 15 yaprak, min yaprak 300; ayar yapılmadı), "NET-E" = p̂·(hedef−c_tp) + (1−p̂)·ê[net|ıska], "NET-REG" = doğrudan net regresyonu. Test bloğunda üst %10 eşiği o bloğun tahmin dağılımından alınır (etiket sızıntısı yok).

## 3. (a) Ayrım gücü
### 3.1 AUC (skor → etiket), blok/ufuk/mod kırılımı
DB canlı:
{{disc_db}}

Replay 90 g (mod kırılımı dahil):
{{disc_rp}}

### 3.2 Ondalık / kova (monotonluk ve kırıldığı yer)
DB canlı — panel ondalık özeti (ρ: ondalık sırası ile ortalama arasındaki Spearman; "düştüğü adımlar" hit'in >0,5 puan geriledığı ondalık geçişleri):
{{dec_db_summ}}

DB sabit kovalar (panel dilimleri):
{{bins_db}}

Replay:
{{dec_rp_summ}}

{{bins_rp}}

Ondalık ayrıntıları — DB:
{{dec_db}}

Ondalık ayrıntıları — Replay:
{{dec_rp}}

**Yorum.** Etiket SL'si geniş (R2, %5) veya SL'siz (replay) iken hit oranı skorla artar (ρ≈+0,8…0,96) ama artış yüzde-puan düzeyinde küçük ve 85'ten sonra düzleşir; SL %1,5'te (R1) ters/negatif: yüksek skor = yüksek ATR → dar stop önce vurulur. Yani skorun "isabet" ilişkisi, stop geometrisine bağlı bir ATR etkisidir. Net ise her iki rejimde de skorla birlikte KÖTÜLEŞİR (R2: ρ=−0,83/−0,88). 90–95 < 85–90 kırılması journal'da sistematik değil (R2a 59,0→59,6); bildirimde görülen 95–99,9 çukuru (aşağıda) karışım/örneklem gürültüsüdür.

### 3.3 Kırpma (panel=100) bilgi kaybı
{{cap}}

AUC(ham)=AUC(panel) (fark ≤0,001): kırpma sıralamayı genel olarak bozmuyor; ama "100" tek kovada ham 25 bin…66 milyonu topluyor ve kova-içi ham skor ATR kontrolüyle AUC 0,51–0,53 → eklenecek bilgi yok. Sorun kırpma değil, ölçeğin bir olasılık/kalite gibi okunması.

## 4. (b) Bileşenler: neyin ayrım gücü var?
ATR payı (skorun ATR ile açıklanan kısmı):
{{atr_share}}

Çarpanların panel ölçeğindeki (sabit) etkisi — log harita: tüm "kalite" çarpanları (MACD, taker, öncü ATR, whale) ≤ ±1,4 puan; yalnız "ceza" çarpanları (geç faz −5,0; choppiness −6,8) büyüktür:
{{mult_effect}}

**DB (R1a/R1b/R2a/R2b; hit etiketi):**
{{dec_comp_db}}

**Replay (b0/b1/b2; hit etiketi; mod, taker, choppiness, rsi, mfi, hacim, 24s değişim dahil):**
{{dec_comp_rp}}

**Okuma.** (i) `log_atr` tek başına replay'de AUC 0,66–0,68 > skorun 0,59–0,60; ATR kontrollü `log_score` β<0. (ii) Skorun ATR-dışı kısmı (`log_rest`, `log_rest2` = BB×yapı×çarpanlar) ATR-strata AUC ≈0,50 ve β<0; `volume_ratio`/hacim terimi (0,5…1,0 çarpan, ≤6,8 panel puanı oynatır) ATR-strata AUC 0,503, `ret3`/momentum terimi 0,500–0,509: ATR dışı hiçbir skor bileşeni ek ayrım getirmiyor. (iii) En güçlü ek bilgi skorun DIŞINDA: 24s değişim (`change_24h`, ATR-strata AUC 0,567, β +0,20, t=+11,5), `m1/m3_atr_prev` (0,54–0,55), CVD (aşağıda), hedef/ATR geometrisi (`log_tgt_atr`, ATR-strata AUC 0,457 = ters yönde güçlü).

### 4.1 Skor çarpanı bayrakları: tasarım yönü vs ölçülen (ATR-strata içi fark)
Replay:
{{flags_rp}}

DB (R1+R2 blokları):
{{flags_db}}

Dikkat çeken: **geç faz cezası (×0,6)** yön olarak YANLIŞ — geç fazda hit +15,5 puan, net ≈0 (n=972); **öncü ATR bonusu (×1,15)** hit'i artırıyor (replay +8,4 puan) ama net'i düşürüyor (−0,22/−0,12); taker bonus/ceza yön olarak doğru ama küçük (+0,7 / −2,4 puan); **CVD işareti** (skora girmiyor; velocity.py:2491 docstring "CVD ayırmıyor" diyor) ATR kontrollü hit +5,8±0,6 puan, net +0,29±0,03, dört blokta aynı işaret (CVD≠0 satırlarda, CVD>0 vs <0). Uyarı: `cvd_try` ölçüm penceresi ve sinyal anı hizası (look-ahead) çıkarım öncesi doğrulanmalı.

### 4.2 Tek gün, zengin özellikler (DB `features`, 17 Eki; keşif — küme SE yok)
{{oneday}}

## 5. (c) Yeniden ağırlıklandırma — yürüyen-ileri
DB (canlı):
{{wf_db}}

Replay 90 g:
{{wf_rp}}

**Okuma.** (1) Mevcut panel skoru hiçbir katlamada en iyi sıralayıcı değil: ML olasılığı (zaten bildirim başlığında "| ML %") DB'de 3/4 katlamada AUC 0,61–0,64 (panel 0,48–0,56) ama olasılık olarak aşırı güvenli (Brier becerisi −%22…−%57). (2) 3 özellikli "LR ATR+hedef geometrisi" AUC 0,55–0,66 ile tam modele (LR 0,55–0,66; HGB 0,54–0,67) neredeyse eşit: tam model ek +0,00…+0,02. Yani kazanç "hedef, ATR'ye göre ne kadar ulaşılabilir" bilgisinden; skorun kendisinden değil. (3) Net: modeller üst-%10 neti panel üst-%10'una göre DB'de genelde iyileştiriyor (≈ −0,03…+0,67; panelin üst %10'u zaten en kötü kesit) ama mutlak değer hep negatif (en iyi −0,36±0,12); replay'de işaret karışık (b0→b1'de LR tam −0,33). NET-REG / NET-E, isabet modelinden net'te daha iyi değil ve katlamalar arası tutarsız. (4) DB etiketi SL rejimine bağlı olduğundan B1→B2 / B1+B2→B3 katlamalarında eğitim–test etiket tanımı farklı (R tabloları bunu ayırır).

## 6. (d) Kalibrasyon / yeniden eşleme
Statik isotonic(skor→hit) (eğitim bloğu → test bloğu):
{{calib_db}}

{{calib_rp}}

Yürüyen isotonic (önceki 7/14 gün) — DB:
{{roll_db}}

Replay:
{{roll_rp}}

Panel diliminin isabet karşılığı (rejime göre; "skor→olasılık" tablosu kullanılacaksa bu kadar rejime bağımlı):
{{remap}}

### 6.1 Önerilen olasılık eşlemesi (skor yerine, hedef/ATR geometrisi)
`p(hit) = σ( b0 + b1·ln(ATR%) + b2·ln(hedef%/ATR%) + b3·[ufuk ≥ 15 dk] )` — katsayılar çıkış rejimine (SL/TP) bağlıdır; HAFTALIK yeniden uydurulmalıdır.

Güncel çıkış rejimi (SL %5; DB R2a+R2b, 10-08..10-17):
{{simple_db2}}

Örnek tablo (ATR% satır, hedef% sütun) — SL %5:
{{simple_db2_grid}}

Önceki rejim (SL %1,5; DB R1):
{{simple_db1}}

SL'siz dokunuş (replay 90 g):
{{simple_rp}}

{{simple_rp_grid}}

### 6.2 Başabaş isabet (çıkış geometrisi)
{{be_db}}

{{be_rp}}

## 7. Bildirimler (monitoring_notifications, sonuçlu 765 satır)
{{note74}}

Sınıfa göre (test satırları ayrı) — hedefe ulaştı = `HEDEFE_ULTI`:
{{notif1}}

Test hariç hepsi birlikte:
{{notif2}}

"100" ne yapıyor? (journal'a eşleşen satırlar):
{{notif3}}

AUC (panel→HEDEFE_ULTI, test hariç): tüm n=709: 0,637; trend_devam n=420: 0,666; notr n=161: 0,555; **unified n=126: 0,474 (şans)**. ATR ile karşılaştırma (journal'a eşleşen velocity-tek/notr, n=486): AUC(panel)=0,633, AUC(ATR)=0,617, ATR-tersil-strata AUC(panel)=0,574 → panelin ek katkısı küçük.

**Bimodalite özeti:** (a) 74,0 kovası test/duman; (b) unified 85–99,9: 117 satır, %0–8; (c) trend_devam/velocity-tek tek yönlü ve dışbükey (16→19→25→46); (d) panel=100 = ham ≥25 000 kırpma kovası, ATR medyanı 2×; (e) Wilson %95 aralıkları 85–99,9 kovalarında örtüşüyor (%14,3 [10–19] / %19,9 [14–27] / %15,0 [10–22]) → 90–95 ile 95–99,9 arasındaki sıra farkı anlamlı değil.

## 8. Birleşik tarama puanı (`unified_candidate_outcomes.scan_score`) — zayıf kanıt
{{uni_txt}} (Yalnız 3 gün, hit = tavana (ceiling) ulaşma, taban %1,6; ikili kaynak satırlarında %0,4 hit — kaynak sayısı bonusunun (+8/kaynak) tersine.)

{{uni_dec}}

{{uni_src}}

## 9. Öneri
**KEEP / RE-MAP / REPLACE:**

1. **Ham `velocity_score` ve panel haritası: KORU (sıralama anahtarı olarak), ama "kalite" diye SUNMA.** Net'e göre onu geçen sağlam bir model yok; AUC'u zaten ATR'den ibaret. Panel=100 kırpmasını açmak (ör. REF↑) AUC'ye bir şey katmaz.
2. **Bildirimde gösterim: "Skor 97" yerine iki ayrı alan.** (i) `Hız/şiddet` = mevcut panel (etiketi "hareket şiddeti"; 85/95 eşikleri "iyi sinyal" anlamı taşımaz), (ii) `Tahmini isabet %` = §6.1 lojistik (ATR, hedef/ATR, ufuk), hafta başı yeniden uydurulmuş, ya da mevcut `ml_hit_probability`'nin yürüyen isotonic/Platt ile kalibre hâli (ham ML olasılığı AUC iyi ama aşırı güvenli). Yanına "başabaş isabet %" (§6.2: SL %5'te ≈%61–73) eklenirse kullanıcı hit%'in neden kâr anlamına gelmediğini görür.
3. **Skor tabanlarını (≥85 tek kaynak, ≥95 unified) kalite filtresi saymayın:** SL %5'te isabeti +6–7 puan artırır, başabaş isabet de +6–8 puan artar; net eşit/kötü (SL %1,5'te isabet bile düşer). `unified` (füzyon) için: sonuçlu 126 satırda %4 isabet, AUC 0,47 → bildirimden tamamen çıkarmak ölçümle desteklenir (≥95 tabanı n=58'de 2 isabet).
4. **Skorun içinde düzeltilecekler (veriyle desteklenen):** geç-faz cezası yön olarak yanlış (hit +15 puan); öncü-ATR bonusu net'i düşürüyor; hacim/momentum terimlerinin ATR-dışı katkısı yok; CVD işareti (+5,8 puan / +0,29 net, 4/4 blok) skor ya da olasılık modeli girdisi adayı — look-ahead kontrolü sonrası.
5. **Veri hijyeni (modeli sınırlayan asıl şey):** `velocity.py:1371` `volume_ratio: 0.0` sabiti; journal'a `mode`, `taker_buy_ratio`, `book_imbalance`, `bb_width_pct`, `volume_ratio`, `m1/m3_atr_prev` yazılmalı (17 Eki'den önce yok); çıkış rejimi (SL/TP maliyeti) her satıra damgalanmalı — rejim değişince etiketler karşılaştırılamıyor.
6. **Yapısal not:** net negatifliğin kaynağı skor değil çıkış geometrisi: SL %5'te başabaş isabet %61–73, gözlenen %46–60; SL %1,5'te %37–46 vs %27–38. Skor sıralaması bunu kapatmıyor.

**Sınırlamalar:** her blokta 5–10 gün (küme sayısı küçük, SE'ler iyimser olabilir); DB etiketi SL rejimine bağlı; replay özellikleri (taker, mod) DB'de eski günler için yok; HGB ayar yapılmadı; bildirimler n=709 ve seçilmiş (eşik üstü) bir örneklem; unified çıktıları 3 gün.
