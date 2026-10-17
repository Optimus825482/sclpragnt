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
| nüfus | ölçüt | ham AUC (blok aralığı) | ATR-strata AUC | ATR×hedef-strata AUC |
|---|---|---|---|---|
| DB canlı (R1 SL1,5 / R2 SL5) | AUC(panel→hit) | 0.473–0.560 | 0.478–0.521 | 0.492–0.527 |
| DB canlı (R1 SL1,5 / R2 SL5) | AUC(panel→net>0) | 0.465–0.526 | 0.475–0.505 | 0.487–0.505 |
| Replay 90 g (hit=dokunuş, SL'siz) | AUC(panel→hit) | 0.593–0.599 | 0.487–0.515 | 0.512–0.541 |
| Replay 90 g (hit=dokunuş, SL'siz) | AUC(panel→net>0) | 0.498–0.515 | 0.476–0.500 | 0.488–0.505 |
| DB canlı | ρ(panel ondalığı, ort. net) R1a/R1b/R2a/R2b | -0.37, +0.19, -0.83, -0.88 |  |  |
| Replay | ρ(panel ondalığı, ort. net) b0/b1/b2 | -0.42, +0.19, -0.55 |  |  |

Yürüyen-ileri (eğitim: önceki bloklar; test: sonraki blok; üst %10 = tahminin en yüksek %10'u, ort. net %):
| katlama | AUC panel | AUC ML-olasılığı (mevcut) | AUC LR ATR+hedef | AUC LR tam | AUC HGB tam | üst%10 net panel | üst%10 net LR tam | üst%10 net HGB tam |
|---|---|---|---|---|---|---|---|---|
| DB B1→B2 | 0.522 | 0.635 | 0.642 | 0.643 | 0.633 | -0.65 | -0.45 | -0.45 |
| DB B1+B2→B3 | 0.555 | 0.613 | 0.620 | 0.642 | 0.635 | -1.01 | -0.56 | -0.42 |
| DB R1a→R1b | 0.484 | 0.503 | 0.548 | 0.551 | 0.542 | -0.51 | -0.41 | -0.46 |
| DB R2a→R2b | 0.560 | 0.608 | 0.620 | 0.636 | 0.632 | -1.20 | -0.70 | -0.56 |
| Replay b0→b1 | 0.594 | – | 0.657 | 0.664 | 0.656 | -0.42 | -0.74 | -0.56 |
| Replay b0+b1→b2 | 0.593 | – | 0.657 | 0.663 | 0.665 | -0.78 | -0.80 | -0.67 |

Tüm katlama × tahmin arasında en yüksek üst-%10 ortalama net: -0.358 (±0.116) — wf_db_R1a→R1b: NET-REG: HGB doğrudan net. Alt %95 sınırı > 0 olan hiçbir (katlama, tahmin) çifti YOK.

## 1. Kod zinciri (dosya:satır) — ekranda görünen skor nasıl oluşuyor

**A. Ham `velocity_score` (app/routers/velocity.py, `scan_one` içinde, sınırsız çarpım):**
- :722 `prof_atr` (profil bazlı ATR eşiği, vars. 0,25; DB'den kalibre); :779 `bb_ratio = BBgenişlik% / 2,5`; :780 `struct_ratio = max(0, slope/0,20, aroon_up/50)`; :783 `atr_ratio = atr_pct / prof_atr`; :792 `momentum = max(0, ret3, ret5)`; :801–802 `momentum_ratio = min(2,5, momentum / max(prof_atr, 0,4))`; hacim oranı son bar / 20 bar ort. (:796).
- **:803–806** `velocity_score = 100 × atr_ratio × bb_ratio × (0,2 + 0,8·struct_ratio) × (0,5 + 0,5·momentum_ratio) × (0,5 + 0,5·min(1, hacim_oranı/2))` — saturation 2026-09-07'de kaldırıldı, ÜST SINIR YOK.
- Çarpanlar (sırayla): MACD teyidi ×1.15 / ×1.05 / ×0.85 (:807–814); M5 MACD hizası ×1.10 (:877); öncü ATR (`leading_ok`) ×1.15 (:904–905); aşırı alım cezası ×0,85 (:1146–1148, `VELOCITY_EXHAUSTION_MODE=penalty` iken; vars. `block`, config.py:893–894); taker teyidi ≥0,58 ×1,05 / ≤0,45 ×0,95 (:1153–1165, config.py:288–291); choppiness>61,8 ∧ ADX<20 ×0,5 (:1171–1186, config.py:282); geç faz (24s ≥%40) ×0,6 (:1192–1195, config.py:299); spread bilinmiyor ×0,85 (:1199–1201, config.py:304). **ML ayarı yok:** "ML sıralama bonusu KALDIRILDI" (:1134–1138); ML yalnız hedefi etkiler.
- Hedef `dynamic_target_pct` (:2621) — skor bandı (74,0→4,0; 71,5→2,5; 68,2→2,0; config.py:425–426), net-kâr tabanı, **ATR×1,35**, öğrenilmiş/ML harmanı: hedef hem skora hem ATR'ye bağlı → "hit" etiketi hedefin kendisinden de etkilenir (bu denetimde ATR×hedef-strata ile kontrol edildi).
- Kapı (`passes`, :746–754): ATR ≥ eşik (kırılışta gevşer), BB ≥ %2,5, yapı teyidi, aşırı uç yok, üst fitil yok.

**B. Sıralama / aday seçimi:** :1325 `micro_mult` (whale var ×1,05, `no_whale` ×0,9: config.py:441–442; yalnız SIRALAMA, skora girmez); :1329 adaylar `velocity_score × micro_mult` ile sıralanır, `rank` 1…`limit` (≤10, :1275–1331); izleme listesi eşiği `_panel_to_raw_score(0,6)` (:1338–1340, pratikte her elenen aday). `upside_rank_score` (:2453–2481) = (hedef/ufuk) × ham skor × `_quality_multiplier`(sembol dokunuş oranı 0,4…1,3) × `micro_structure_multiplier` — chat/liste sıralaması içindir; bildirim skoru DEĞİL.

**C. 0–100 panel eşlemesi:** app/unified_scan.py:39–60 (kanonik; routers/monitoring.py:220 delege eder; velocity.py:303 `_panel_score` replika): `panel = round(clip(100·ln(1+ham)/ln(1+25000), 0, 100), 1)` (`MONITORING_SCORE_NORM_LOG_REF=25000`, config.py:378; `norm_version=2`, monitoring.py:217, 1587). Her +5 panel puanı ham ×1,65; **panel=100 ⇔ ham ≥ 25 000 (kırpma)**.
| panel | ham velocity_score eşiği |
|---|---|
| 50 | 157 |
| 60 | 434 |
| 70 | 1,197 |
| 71.5 | 1,394 |
| 74 | 1,796 |
| 80 | 3,298 |
| 85 | 5,472 |
| 90 | 9,081 |
| 95 | 15,067 |
| 99.9 | 24,748 |
| 100 | 25,000 |

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
| blok | alt küme | etiket | skor | n | gün | taban | AUC±SE | ATR-strata AUC±SE | ATR×hedef-strata AUC±SE |
|---|---|---|---|---|---|---|---|---|---|
| B1 | tüm | hit | ham | 35563 | 10 | 35.7% | 0.475±0.007 | 0.482±0.006 | 0.491±0.009 |
| B1 | tüm | hit | panel | 35563 | 10 | 35.7% | 0.475±0.007 | 0.481±0.006 | 0.491±0.009 |
| B1 | tüm | net>0 | ham | 35563 | 10 | 37.1% | 0.468±0.006 | 0.478±0.005 | 0.486±0.008 |
| B1 | tüm | net>0 | panel | 35563 | 10 | 37.1% | 0.468±0.006 | 0.478±0.005 | 0.486±0.008 |
| B1 | 5dk | hit | panel | 17891 | 10 | 36.5% | 0.472±0.006 | 0.479±0.006 | 0.494±0.007 |
| B1 | 5dk | net>0 | panel | 17891 | 10 | 37.7% | 0.467±0.005 | 0.477±0.005 | 0.493±0.008 |
| B1 | 15dk | hit | panel | 17672 | 10 | 34.9% | 0.478±0.008 | 0.484±0.006 | 0.489±0.010 |
| B1 | 15dk | net>0 | panel | 17672 | 10 | 36.5% | 0.469±0.007 | 0.479±0.006 | 0.482±0.009 |
| B2 | tüm | hit | ham | 41363 | 8 | 36.8% | 0.522±0.014 | 0.517±0.009 | 0.541±0.014 |
| B2 | tüm | hit | panel | 41363 | 8 | 36.8% | 0.522±0.014 | 0.516±0.009 | 0.541±0.014 |
| B2 | tüm | net>0 | ham | 41363 | 8 | 40.8% | 0.503±0.013 | 0.498±0.009 | 0.516±0.012 |
| B2 | tüm | net>0 | panel | 41363 | 8 | 40.8% | 0.503±0.013 | 0.498±0.009 | 0.515±0.012 |
| B2 | 5dk | hit | panel | 28184 | 8 | 35.4% | 0.544±0.024 | 0.517±0.009 | 0.545±0.014 |
| B2 | 5dk | net>0 | panel | 28184 | 8 | 40.5% | 0.506±0.023 | 0.500±0.009 | 0.521±0.012 |
| B2 | 15dk | hit | panel | 13179 | 8 | 39.7% | 0.517±0.015 | 0.510±0.010 | 0.525±0.013 |
| B2 | 15dk | net>0 | panel | 13179 | 8 | 41.4% | 0.506±0.015 | 0.503±0.009 | 0.515±0.012 |
| B3 | tüm | hit | ham | 33028 | 8 | 49.7% | 0.555±0.008 | 0.514±0.009 | 0.516±0.006 |
| B3 | tüm | hit | panel | 33028 | 8 | 49.7% | 0.555±0.008 | 0.513±0.009 | 0.515±0.006 |
| B3 | tüm | net>0 | ham | 33028 | 8 | 54.5% | 0.526±0.007 | 0.499±0.008 | 0.500±0.007 |
| B3 | tüm | net>0 | panel | 33028 | 8 | 54.5% | 0.526±0.007 | 0.498±0.008 | 0.500±0.007 |
| B3 | 5dk | hit | panel | 16731 | 8 | 50.4% | 0.580±0.008 | 0.523±0.007 | 0.530±0.008 |
| B3 | 5dk | net>0 | panel | 16731 | 8 | 55.1% | 0.545±0.009 | 0.506±0.008 | 0.509±0.009 |
| B3 | 15dk | hit | panel | 14193 | 8 | 50.7% | 0.531±0.023 | 0.499±0.021 | 0.491±0.015 |
| B3 | 15dk | net>0 | panel | 14193 | 8 | 55.2% | 0.509±0.017 | 0.490±0.018 | 0.487±0.013 |
| R1a | tüm | hit | ham | 25591 | 7 | 35.6% | 0.473±0.010 | 0.479±0.007 | 0.492±0.011 |
| R1a | tüm | hit | panel | 25591 | 7 | 35.6% | 0.473±0.010 | 0.478±0.007 | 0.492±0.011 |
| R1a | tüm | net>0 | ham | 25591 | 7 | 37.2% | 0.465±0.008 | 0.475±0.006 | 0.487±0.009 |
| R1a | tüm | net>0 | panel | 25591 | 7 | 37.2% | 0.465±0.008 | 0.475±0.006 | 0.487±0.009 |
| R1a | 5dk | hit | panel | 12885 | 7 | 36.5% | 0.470±0.008 | 0.476±0.007 | 0.496±0.008 |
| R1a | 5dk | net>0 | panel | 12885 | 7 | 37.9% | 0.464±0.007 | 0.475±0.006 | 0.495±0.008 |
| R1a | 15dk | hit | panel | 12706 | 7 | 34.7% | 0.476±0.011 | 0.481±0.008 | 0.490±0.013 |
| R1a | 15dk | net>0 | panel | 12706 | 7 | 36.5% | 0.465±0.009 | 0.476±0.007 | 0.482±0.010 |
| R1b | tüm | hit | ham | 32588 | 7 | 29.4% | 0.484±0.010 | 0.491±0.012 | 0.505±0.012 |
| R1b | tüm | hit | panel | 32588 | 7 | 29.4% | 0.484±0.010 | 0.491±0.012 | 0.505±0.011 |
| R1b | tüm | net>0 | ham | 32588 | 7 | 32.6% | 0.476±0.008 | 0.480±0.008 | 0.493±0.008 |
| R1b | tüm | net>0 | panel | 32588 | 7 | 32.6% | 0.476±0.008 | 0.480±0.007 | 0.493±0.008 |
| R1b | 5dk | hit | panel | 20822 | 7 | 29.3% | 0.477±0.013 | 0.478±0.016 | 0.497±0.013 |
| R1b | 5dk | net>0 | panel | 20822 | 7 | 33.5% | 0.458±0.010 | 0.471±0.011 | 0.486±0.009 |
| R1b | 15dk | hit | panel | 11766 | 7 | 29.7% | 0.494±0.009 | 0.496±0.009 | 0.500±0.009 |
| R1b | 15dk | net>0 | panel | 11766 | 7 | 31.0% | 0.485±0.008 | 0.493±0.009 | 0.495±0.008 |
| R2a | tüm | hit | ham | 30065 | 5 | 53.1% | 0.551±0.006 | 0.519±0.006 | 0.527±0.005 |
| R2a | tüm | hit | panel | 30065 | 5 | 53.1% | 0.551±0.006 | 0.518±0.006 | 0.527±0.005 |
| R2a | tüm | net>0 | ham | 30065 | 5 | 57.1% | 0.526±0.007 | 0.501±0.007 | 0.506±0.007 |
| R2a | tüm | net>0 | panel | 30065 | 5 | 57.1% | 0.526±0.006 | 0.500±0.007 | 0.505±0.007 |
| R2a | 5dk | hit | panel | 18349 | 5 | 50.9% | 0.599±0.008 | 0.528±0.006 | 0.535±0.006 |
| R2a | 5dk | net>0 | panel | 18349 | 5 | 55.6% | 0.561±0.007 | 0.508±0.007 | 0.511±0.007 |
| R2a | 15dk | hit | panel | 11716 | 5 | 56.6% | 0.500±0.008 | 0.501±0.007 | 0.503±0.005 |
| R2a | 15dk | net>0 | panel | 11716 | 5 | 59.6% | 0.489±0.011 | 0.492±0.010 | 0.496±0.008 |
| R2b | tüm | hit | ham | 14654 | 5 | 45.8% | 0.560±0.009 | 0.521±0.017 | 0.511±0.018 |
| R2b | tüm | hit | panel | 14654 | 5 | 45.8% | 0.560±0.009 | 0.521±0.018 | 0.511±0.018 |
| R2b | tüm | net>0 | ham | 14654 | 5 | 51.5% | 0.526±0.012 | 0.505±0.018 | 0.501±0.019 |
| R2b | tüm | net>0 | panel | 14654 | 5 | 51.5% | 0.526±0.012 | 0.505±0.019 | 0.501±0.020 |
| R2b | 5dk | hit | panel | 6318 | 5 | 47.7% | 0.564±0.013 | 0.517±0.020 | 0.518±0.022 |
| R2b | 5dk | net>0 | panel | 6318 | 5 | 52.9% | 0.529±0.014 | 0.500±0.023 | 0.501±0.026 |
| R2b | 15dk | hit | panel | 6232 | 5 | 46.4% | 0.569±0.013 | 0.527±0.010 | 0.503±0.012 |
| R2b | 15dk | net>0 | panel | 6232 | 5 | 52.0% | 0.534±0.011 | 0.513±0.012 | 0.501±0.013 |

Replay 90 g (mod kırılımı dahil):
| blok | alt küme | etiket | skor | n | gün | taban | AUC±SE | ATR-strata AUC±SE | ATR×hedef-strata AUC±SE |
|---|---|---|---|---|---|---|---|---|---|
| b0 | tüm | hit | ham | 6110 | 30 | 25.2% | 0.599±0.008 | 0.488±0.009 | 0.513±0.008 |
| b0 | tüm | hit | panel | 6110 | 30 | 25.2% | 0.599±0.008 | 0.487±0.009 | 0.512±0.009 |
| b0 | tüm | net>0 | ham | 6110 | 30 | 36.1% | 0.505±0.006 | 0.476±0.007 | 0.492±0.007 |
| b0 | tüm | net>0 | panel | 6110 | 30 | 36.1% | 0.505±0.006 | 0.476±0.007 | 0.493±0.007 |
| b0 | 15dk | hit | panel | 6110 | 30 | 25.2% | 0.599±0.008 | 0.487±0.009 | 0.512±0.009 |
| b0 | 15dk | net>0 | panel | 6110 | 30 | 36.1% | 0.505±0.006 | 0.476±0.007 | 0.493±0.007 |
| b0 | trend_devam | hit | panel | 3326 | 30 | 22.5% | 0.631±0.013 | 0.504±0.013 | 0.521±0.013 |
| b0 | trend_devam | net>0 | panel | 3326 | 30 | 34.5% | 0.518±0.012 | 0.480±0.011 | 0.495±0.010 |
| b0 | notr | hit | panel | 2437 | 30 | 29.4% | 0.602±0.011 | 0.471±0.014 | 0.495±0.014 |
| b0 | notr | net>0 | panel | 2437 | 30 | 38.0% | 0.501±0.009 | 0.472±0.010 | 0.488±0.009 |
| b1 | tüm | hit | ham | 6797 | 30 | 21.3% | 0.594±0.008 | 0.516±0.008 | 0.542±0.009 |
| b1 | tüm | hit | panel | 6797 | 30 | 21.3% | 0.594±0.008 | 0.515±0.008 | 0.541±0.009 |
| b1 | tüm | net>0 | ham | 6797 | 30 | 36.3% | 0.515±0.008 | 0.500±0.008 | 0.506±0.008 |
| b1 | tüm | net>0 | panel | 6797 | 30 | 36.3% | 0.515±0.008 | 0.500±0.008 | 0.505±0.008 |
| b1 | 15dk | hit | panel | 6797 | 30 | 21.3% | 0.594±0.008 | 0.515±0.008 | 0.541±0.009 |
| b1 | 15dk | net>0 | panel | 6797 | 30 | 36.3% | 0.515±0.008 | 0.500±0.008 | 0.505±0.008 |
| b1 | trend_devam | hit | panel | 4117 | 30 | 19.8% | 0.616±0.012 | 0.519±0.011 | 0.539±0.012 |
| b1 | trend_devam | net>0 | panel | 4117 | 30 | 35.4% | 0.533±0.010 | 0.512±0.011 | 0.509±0.011 |
| b1 | notr | hit | panel | 2235 | 30 | 24.6% | 0.607±0.019 | 0.506±0.015 | 0.530±0.017 |
| b1 | notr | net>0 | panel | 2235 | 30 | 37.3% | 0.512±0.016 | 0.499±0.014 | 0.515±0.013 |
| b2 | tüm | hit | ham | 7436 | 29 | 22.5% | 0.594±0.008 | 0.505±0.008 | 0.531±0.009 |
| b2 | tüm | hit | panel | 7436 | 29 | 22.5% | 0.593±0.008 | 0.503±0.008 | 0.528±0.009 |
| b2 | tüm | net>0 | ham | 7436 | 29 | 35.1% | 0.498±0.007 | 0.483±0.008 | 0.488±0.009 |
| b2 | tüm | net>0 | panel | 7436 | 29 | 35.1% | 0.498±0.007 | 0.483±0.008 | 0.488±0.008 |
| b2 | 15dk | hit | panel | 7436 | 29 | 22.5% | 0.593±0.008 | 0.503±0.008 | 0.528±0.009 |
| b2 | 15dk | net>0 | panel | 7436 | 29 | 35.1% | 0.498±0.007 | 0.483±0.008 | 0.488±0.008 |
| b2 | trend_devam | hit | panel | 4529 | 29 | 21.1% | 0.608±0.011 | 0.492±0.012 | 0.521±0.012 |
| b2 | trend_devam | net>0 | panel | 4529 | 29 | 34.6% | 0.505±0.008 | 0.483±0.009 | 0.492±0.010 |
| b2 | notr | hit | panel | 2443 | 29 | 26.2% | 0.605±0.016 | 0.515±0.017 | 0.531±0.016 |
| b2 | notr | net>0 | panel | 2443 | 29 | 35.2% | 0.505±0.012 | 0.487±0.012 | 0.492±0.013 |

### 3.2 Ondalık / kova (monotonluk ve kırıldığı yer)
DB canlı — panel ondalık özeti (ρ: ondalık sırası ile ortalama arasındaki Spearman; "düştüğü adımlar" hit'in >0,5 puan geriledığı ondalık geçişleri):
| blok | ρ(ondalık,hit) | ρ(ondalık,net) | hit'in düştüğü adımlar (k→k+1) | hit ondalıkları |
|---|---|---|---|---|
| B1 | -0.84 | -0.15 | 1→2,2→3,3→4,6→7,8→9 | 39 38 37 35 36 38 35 36 31 33 |
| B2 | 0.92 | -0.53 | 5→6 | 34 35 36 36 37 36 36 38 39 41 |
| B3 | 0.98 | -0.85 | 5→6 | 41 43 46 47 51 50 52 55 56 55 |
| R1a | -0.84 | -0.37 | 2→3,3→4,6→7,7→8,8→9,9→10 | 39 39 35 35 37 38 35 34 33 31 |
| R1b | -0.68 | 0.19 | 1→2,6→7,8→9 | 31 28 32 31 31 31 27 29 27 27 |
| R2a | 0.96 | -0.83 | 1→2 | 49 47 48 51 51 53 55 58 60 60 |
| R2b | 0.82 | -0.88 | 5→6 | 32 40 42 44 52 46 49 49 51 52 |

DB sabit kovalar (panel dilimleri):
| blok | panel dilimi | n | gün | hit±SE | ort. net±SE | ort. ATR% | ort. hedef% |
|---|---|---|---|---|---|---|---|
| B1 | <60 | 18588 | 10 | 37.2%±0.9 | -0.38±0.04 | 0.82 | 2.25 |
| B1 | 60–70 | 7765 | 10 | 36.0%±1.1 | -0.40±0.04 | 0.96 | 2.44 |
| B1 | 70–80 | 4893 | 10 | 32.6%±1.0 | -0.44±0.04 | 1.14 | 2.82 |
| B1 | 80–85 | 1532 | 10 | 29.4%±2.1 | -0.45±0.11 | 1.39 | 3.19 |
| B1 | 85–90 | 986 | 10 | 31.0%±2.0 | -0.41±0.09 | 1.56 | 3.21 |
| B1 | 90–95 | 671 | 10 | 32.5%±3.6 | -0.31±0.17 | 1.72 | 3.31 |
| B1 | 95–99.9 | 495 | 10 | 31.5%±2.8 | -0.30±0.17 | 1.84 | 3.41 |
| B1 | =100 | 633 | 10 | 41.4%±3.8 | 0.26±0.23 | 2.57 | 3.49 |
| B2 | <60 | 9732 | 8 | 34.8%±4.0 | -0.50±0.05 | 0.72 | 2.17 |
| B2 | 60–70 | 9174 | 8 | 36.2%±3.4 | -0.49±0.03 | 0.68 | 2.11 |
| B2 | 70–80 | 9013 | 8 | 36.0%±4.1 | -0.54±0.05 | 0.75 | 2.33 |
| B2 | 80–85 | 3737 | 8 | 37.7%±4.8 | -0.53±0.06 | 0.85 | 2.52 |
| B2 | 85–90 | 2832 | 8 | 38.3%±5.9 | -0.55±0.06 | 0.94 | 2.61 |
| B2 | 90–95 | 2053 | 8 | 38.9%±6.2 | -0.52±0.07 | 1.07 | 2.68 |
| B2 | 95–99.9 | 1521 | 8 | 40.8%±7.4 | -0.59±0.06 | 1.19 | 2.68 |
| B2 | =100 | 3301 | 8 | 40.9%±7.4 | -0.67±0.06 | 1.69 | 2.82 |
| B3 | <60 | 5540 | 8 | 41.9%±4.1 | -0.36±0.04 | 0.51 | 1.82 |
| B3 | 60–70 | 7102 | 8 | 45.8%±2.1 | -0.50±0.05 | 0.57 | 1.73 |
| B3 | 70–80 | 7939 | 8 | 50.9%±1.1 | -0.49±0.03 | 0.66 | 1.80 |
| B3 | 80–85 | 3436 | 8 | 52.5%±2.1 | -0.57±0.10 | 0.77 | 1.83 |
| B3 | 85–90 | 2738 | 8 | 55.8%±1.9 | -0.51±0.12 | 0.83 | 1.86 |
| B3 | 90–95 | 2097 | 8 | 55.0%±3.1 | -0.68±0.17 | 0.98 | 1.93 |
| B3 | 95–99.9 | 1412 | 8 | 57.3%±3.7 | -0.67±0.21 | 1.08 | 2.00 |
| B3 | =100 | 2764 | 8 | 55.1%±2.7 | -1.08±0.18 | 1.77 | 2.10 |
| R2a | <60 | 5840 | 5 | 48.3%±3.3 | -0.37±0.05 | 0.65 | 1.74 |
| R2a | 60–70 | 6167 | 5 | 49.1%±1.5 | -0.51±0.05 | 0.64 | 1.66 |
| R2a | 70–80 | 6770 | 5 | 51.9%±1.0 | -0.53±0.05 | 0.72 | 1.75 |
| R2a | 80–85 | 3090 | 5 | 55.7%±1.0 | -0.55±0.10 | 0.84 | 1.80 |
| R2a | 85–90 | 2305 | 5 | 59.0%±1.9 | -0.48±0.13 | 0.91 | 1.82 |
| R2a | 90–95 | 1766 | 5 | 59.6%±1.8 | -0.54±0.16 | 1.08 | 1.87 |
| R2a | 95–99.9 | 1338 | 5 | 60.2%±4.2 | -0.62±0.23 | 1.19 | 1.94 |
| R2a | =100 | 2789 | 5 | 60.2%±2.6 | -0.83±0.17 | 1.80 | 2.05 |
| R2b | <60 | 2398 | 5 | 35.9%±1.3 | -0.37±0.05 | 0.40 | 1.92 |
| R2b | 60–70 | 3392 | 5 | 42.2%±2.4 | -0.50±0.07 | 0.52 | 1.79 |
| R2b | 70–80 | 3663 | 5 | 48.7%±1.5 | -0.50±0.04 | 0.61 | 1.84 |
| R2b | 80–85 | 1447 | 5 | 47.8%±3.1 | -0.70±0.13 | 0.71 | 1.86 |
| R2b | 85–90 | 1206 | 5 | 52.3%±1.0 | -0.61±0.13 | 0.79 | 1.88 |
| R2b | 90–95 | 870 | 5 | 50.0%±6.3 | -0.86±0.26 | 0.89 | 1.97 |
| R2b | 95–99.9 | 592 | 5 | 55.7%±4.1 | -0.69±0.15 | 0.99 | 2.01 |
| R2b | =100 | 1086 | 5 | 50.6%±3.5 | -1.32±0.19 | 1.68 | 2.14 |

Replay:
| blok | ρ(ondalık,hit) | ρ(ondalık,net) | hit'in düştüğü adımlar | hit ondalıkları |
|---|---|---|---|---|
| b0 | 0.93 | -0.42 | 5→6 | 16 19 18 24 28 21 25 28 33 40 |
| b1 | 0.87 | 0.19 | 5→6,7→8 | 12 17 19 19 21 19 21 20 27 38 |
| b2 | 0.81 | -0.55 | 5→6 | 14 17 21 21 21 18 20 26 28 38 |

| blok | panel dilimi | n | gün | hit±SE | ort. net±SE | ort. ATR% | ort. hedef% |
|---|---|---|---|---|---|---|---|
| b0 | <60 | 950 | 30 | 17.2%±1.3 | -0.43±0.05 | 0.35 | 3.00 |
| b0 | 60–70 | 1492 | 30 | 20.5%±1.0 | -0.54±0.04 | 0.44 | 3.00 |
| b0 | 70–80 | 1562 | 30 | 24.6%±1.0 | -0.42±0.07 | 0.55 | 3.55 |
| b0 | 80–85 | 639 | 30 | 24.4%±1.7 | -0.59±0.10 | 0.68 | 3.91 |
| b0 | 85–90 | 452 | 30 | 33.8%±2.1 | -0.41±0.13 | 0.78 | 3.94 |
| b0 | 90–95 | 305 | 30 | 31.1%±2.9 | -0.74±0.13 | 0.93 | 3.94 |
| b0 | 95–99.9 | 235 | 30 | 36.6%±3.0 | -0.67±0.20 | 1.07 | 3.91 |
| b0 | =100 | 475 | 30 | 41.7%±2.9 | -0.91±0.18 | 1.67 | 3.94 |
| b1 | <60 | 1089 | 30 | 13.6%±0.9 | -0.48±0.07 | 0.34 | 3.00 |
| b1 | 60–70 | 1728 | 30 | 19.3%±1.3 | -0.55±0.06 | 0.40 | 3.01 |
| b1 | 70–80 | 1937 | 30 | 20.1%±1.2 | -0.51±0.07 | 0.48 | 3.56 |
| b1 | 80–85 | 708 | 30 | 20.6%±1.1 | -0.56±0.06 | 0.58 | 3.92 |
| b1 | 85–90 | 454 | 30 | 25.3%±1.9 | -0.44±0.13 | 0.68 | 3.92 |
| b1 | 90–95 | 307 | 30 | 32.6%±3.0 | -0.38±0.16 | 0.82 | 3.93 |
| b1 | 95–99.9 | 187 | 30 | 36.4%±4.2 | -0.38±0.28 | 0.97 | 3.93 |
| b1 | =100 | 387 | 30 | 39.0%±2.2 | -0.51±0.14 | 1.58 | 3.95 |
| b2 | <60 | 1100 | 29 | 14.8%±1.1 | -0.49±0.06 | 0.35 | 3.00 |
| b2 | 60–70 | 1838 | 29 | 20.2%±1.0 | -0.59±0.06 | 0.41 | 3.00 |
| b2 | 70–80 | 2034 | 29 | 19.1%±1.1 | -0.69±0.06 | 0.48 | 3.55 |
| b2 | 80–85 | 798 | 29 | 25.7%±1.9 | -0.43±0.11 | 0.60 | 3.95 |
| b2 | 85–90 | 583 | 29 | 27.1%±1.9 | -0.54±0.11 | 0.67 | 3.94 |
| b2 | 90–95 | 341 | 29 | 30.5%±2.8 | -0.83±0.14 | 0.81 | 3.91 |
| b2 | 95–99.9 | 261 | 29 | 34.5%±3.1 | -0.56±0.19 | 0.93 | 3.95 |
| b2 | =100 | 481 | 29 | 39.9%±2.8 | -0.91±0.13 | 1.65 | 3.96 |

Ondalık ayrıntıları — DB:
| blok | ondalık | n | panel min | panel max | hit±SE | ort. net±SE |
|---|---|---|---|---|---|---|
| B1 | 1 | 3573 | 15.2 | 42.0 | 39.2%±1.6 | -0.28±0.05 |
| B1 | 2 | 3540 | 42.1 | 47.2 | 38.0%±1.6 | -0.37±0.06 |
| B1 | 3 | 3547 | 47.3 | 51.4 | 36.7%±1.6 | -0.41±0.06 |
| B1 | 4 | 3533 | 51.5 | 55.3 | 35.3%±1.7 | -0.44±0.07 |
| B1 | 5 | 3598 | 55.4 | 59.1 | 35.9%±1.7 | -0.42±0.07 |
| B1 | 6 | 3540 | 59.2 | 63.1 | 37.9%±1.6 | -0.34±0.05 |
| B1 | 7 | 3561 | 63.2 | 67.8 | 35.0%±1.6 | -0.44±0.06 |
| B1 | 8 | 3560 | 67.9 | 73.6 | 35.6%±1.2 | -0.41±0.05 |
| B1 | 9 | 3563 | 73.7 | 82.2 | 30.9%±1.1 | -0.42±0.05 |
| B1 | 10 | 3548 | 82.3 | 100.0 | 32.6%±1.8 | -0.28±0.09 |
| B2 | 1 | 4119 | 22.1 | 50.8 | 34.1%±4.5 | -0.54±0.07 |
| B2 | 2 | 4162 | 50.9 | 58.1 | 34.6%±3.8 | -0.50±0.04 |
| B2 | 3 | 4135 | 58.2 | 63.0 | 35.8%±3.2 | -0.46±0.04 |
| B2 | 4 | 4098 | 63.1 | 67.4 | 36.2%±3.4 | -0.51±0.04 |
| B2 | 5 | 4140 | 67.5 | 71.7 | 37.2%±4.2 | -0.50±0.05 |
| B2 | 6 | 4136 | 71.8 | 76.2 | 36.2%±3.7 | -0.53±0.05 |
| B2 | 7 | 4174 | 76.3 | 81.1 | 35.8%±4.6 | -0.57±0.07 |
| B2 | 8 | 4117 | 81.2 | 87.3 | 37.7%±4.9 | -0.54±0.05 |
| B2 | 9 | 4154 | 87.4 | 97.0 | 39.5%±6.6 | -0.52±0.06 |
| B2 | 10 | 4128 | 97.1 | 100.0 | 40.6%±7.4 | -0.66±0.05 |
| B3 | 1 | 3296 | 24.6 | 55.4 | 40.8%±5.4 | -0.33±0.04 |
| B3 | 2 | 3281 | 55.5 | 61.7 | 43.5%±2.3 | -0.42±0.06 |
| B3 | 3 | 3359 | 61.8 | 66.5 | 46.3%±2.3 | -0.48±0.05 |
| B3 | 4 | 3244 | 66.6 | 70.6 | 46.9%±1.7 | -0.53±0.05 |
| B3 | 5 | 3299 | 70.7 | 74.6 | 51.3%±0.9 | -0.47±0.05 |
| B3 | 6 | 3383 | 74.7 | 78.9 | 50.4%±1.5 | -0.52±0.05 |
| B3 | 7 | 3289 | 79.0 | 83.5 | 52.0%±2.2 | -0.57±0.09 |
| B3 | 8 | 3290 | 83.6 | 89.3 | 55.2%±2.1 | -0.52±0.11 |
| B3 | 9 | 3277 | 89.4 | 97.6 | 55.8%±2.7 | -0.66±0.16 |
| B3 | 10 | 3310 | 97.7 | 100.0 | 55.4%±2.6 | -1.01±0.17 |
| R1a | 1 | 2542 | 15.2 | 41.5 | 38.8%±2.0 | -0.29±0.06 |
| R1a | 2 | 2579 | 41.6 | 46.7 | 38.9%±1.7 | -0.33±0.06 |
| R1a | 3 | 2536 | 46.8 | 50.7 | 35.5%±1.5 | -0.45±0.06 |
| R1a | 4 | 2568 | 50.8 | 54.4 | 34.8%±1.9 | -0.47±0.07 |
| R1a | 5 | 2546 | 54.5 | 58.1 | 37.0%±1.9 | -0.38±0.08 |
| R1a | 6 | 2607 | 58.2 | 62.1 | 38.4%±2.1 | -0.33±0.08 |
| R1a | 7 | 2554 | 62.2 | 66.4 | 35.3%±2.6 | -0.44±0.10 |
| R1a | 8 | 2529 | 66.5 | 71.9 | 33.8%±1.8 | -0.47±0.06 |
| R1a | 9 | 2573 | 72.0 | 80.6 | 32.8%±1.7 | -0.39±0.08 |
| R1a | 10 | 2557 | 80.7 | 100.0 | 30.8%±2.4 | -0.40±0.11 |
| R1b | 1 | 3270 | 23.9 | 48.0 | 31.3%±3.4 | -0.53±0.08 |
| R1b | 2 | 3283 | 48.1 | 55.5 | 28.2%±2.2 | -0.58±0.09 |
| R1b | 3 | 3224 | 55.6 | 60.5 | 31.6%±2.0 | -0.42±0.06 |
| R1b | 4 | 3233 | 60.6 | 65.1 | 31.1%±2.1 | -0.45±0.06 |
| R1b | 5 | 3276 | 65.2 | 69.4 | 30.7%±1.5 | -0.51±0.04 |
| R1b | 6 | 3305 | 69.5 | 73.9 | 31.0%±1.5 | -0.52±0.05 |
| R1b | 7 | 3184 | 74.0 | 78.8 | 26.9%±1.8 | -0.49±0.06 |
| R1b | 8 | 3312 | 78.9 | 84.9 | 28.8%±1.9 | -0.44±0.07 |
| R1b | 9 | 3249 | 85.0 | 93.8 | 27.3%±1.6 | -0.52±0.07 |
| R1b | 10 | 3252 | 93.9 | 100.0 | 27.4%±2.4 | -0.51±0.12 |
| R2a | 1 | 3023 | 22.1 | 53.6 | 49.5%±3.3 | -0.34±0.02 |
| R2a | 2 | 2973 | 53.7 | 60.2 | 46.7%±3.4 | -0.41±0.10 |
| R2a | 3 | 3040 | 60.3 | 65.4 | 47.9%±1.3 | -0.55±0.05 |
| R2a | 4 | 2971 | 65.5 | 69.9 | 50.8%±1.7 | -0.47±0.06 |
| R2a | 5 | 3035 | 70.0 | 74.2 | 51.1%±1.5 | -0.55±0.04 |
| R2a | 6 | 2961 | 74.3 | 78.7 | 52.8%±0.9 | -0.49±0.07 |
| R2a | 7 | 3051 | 78.8 | 83.4 | 54.7%±0.9 | -0.56±0.08 |
| R2a | 8 | 2994 | 83.5 | 89.6 | 58.4%±1.7 | -0.49±0.12 |
| R2a | 9 | 3002 | 89.7 | 98.8 | 59.6%±2.6 | -0.58±0.17 |
| R2a | 10 | 3015 | 98.9 | 100.0 | 60.1%±2.6 | -0.82±0.18 |
| R2b | 1 | 1462 | 28.9 | 55.8 | 32.5%±2.1 | -0.36±0.05 |
| R2b | 2 | 1473 | 55.9 | 61.8 | 40.5%±0.9 | -0.38±0.08 |
| R2b | 3 | 1452 | 61.9 | 66.2 | 42.1%±3.3 | -0.48±0.09 |
| R2b | 4 | 1485 | 66.3 | 70.1 | 43.8%±1.4 | -0.54±0.08 |
| R2b | 5 | 1440 | 70.2 | 73.9 | 51.9%±0.8 | -0.32±0.11 |
| R2b | 6 | 1478 | 74.0 | 78.0 | 46.5%±2.8 | -0.62±0.02 |
| R2b | 7 | 1458 | 78.1 | 82.6 | 48.8%±2.5 | -0.63±0.08 |
| R2b | 8 | 1480 | 82.7 | 88.3 | 49.1%±1.6 | -0.66±0.12 |
| R2b | 9 | 1453 | 88.4 | 96.4 | 51.5%±3.5 | -0.77±0.12 |
| R2b | 10 | 1473 | 96.5 | 100.0 | 51.7%±3.9 | -1.20±0.18 |

Ondalık ayrıntıları — Replay:
| blok | ondalık | n | panel min | panel max | hit±SE | ort. net±SE |
|---|---|---|---|---|---|---|
| b0 | 1 | 609 | 27.7 | 56.7 | 15.9%±1.5 | -0.34±0.07 |
| b0 | 2 | 620 | 56.8 | 62.0 | 18.5%±1.9 | -0.58±0.08 |
| b0 | 3 | 597 | 62.1 | 66.1 | 18.1%±1.6 | -0.66±0.10 |
| b0 | 4 | 616 | 66.2 | 69.9 | 24.2%±1.9 | -0.40±0.09 |
| b0 | 5 | 617 | 70.0 | 73.8 | 28.2%±1.9 | -0.26±0.09 |
| b0 | 6 | 603 | 73.9 | 77.6 | 20.6%±1.4 | -0.62±0.09 |
| b0 | 7 | 622 | 77.7 | 81.9 | 25.2%±1.6 | -0.40±0.13 |
| b0 | 8 | 608 | 82.0 | 87.4 | 28.3%±1.7 | -0.57±0.10 |
| b0 | 9 | 605 | 87.5 | 96.5 | 32.7%±2.0 | -0.65±0.10 |
| b0 | 10 | 613 | 96.6 | 100.0 | 40.5%±2.4 | -0.84±0.16 |
| b1 | 1 | 684 | 27.9 | 56.7 | 11.8%±1.3 | -0.47±0.08 |
| b1 | 2 | 668 | 56.8 | 61.7 | 17.4%±1.5 | -0.51±0.08 |
| b1 | 3 | 691 | 61.8 | 65.7 | 19.2%±1.8 | -0.51±0.10 |
| b1 | 4 | 669 | 65.8 | 69.4 | 19.1%±1.7 | -0.56±0.08 |
| b1 | 5 | 695 | 69.5 | 72.9 | 20.7%±2.1 | -0.64±0.10 |
| b1 | 6 | 675 | 73.0 | 76.4 | 18.8%±1.6 | -0.52±0.09 |
| b1 | 7 | 672 | 76.5 | 79.9 | 21.1%±1.9 | -0.41±0.10 |
| b1 | 8 | 680 | 80.0 | 84.6 | 19.9%±1.1 | -0.58±0.06 |
| b1 | 9 | 685 | 84.7 | 92.9 | 27.0%±1.6 | -0.47±0.09 |
| b1 | 10 | 678 | 93.1 | 100.0 | 38.3%±1.7 | -0.39±0.12 |
| b2 | 1 | 750 | 29.8 | 57.2 | 14.0%±1.1 | -0.44±0.07 |
| b2 | 2 | 742 | 57.3 | 62.5 | 17.1%±1.5 | -0.60±0.08 |
| b2 | 3 | 737 | 62.6 | 66.4 | 21.0%±1.8 | -0.60±0.10 |
| b2 | 4 | 742 | 66.5 | 70.1 | 21.0%±1.6 | -0.58±0.10 |
| b2 | 5 | 739 | 70.2 | 73.6 | 21.2%±1.6 | -0.65±0.08 |
| b2 | 6 | 753 | 73.7 | 77.4 | 17.9%±1.3 | -0.75±0.08 |
| b2 | 7 | 739 | 77.5 | 81.2 | 20.2%±1.7 | -0.60±0.10 |
| b2 | 8 | 743 | 81.3 | 86.2 | 26.1%±2.0 | -0.41±0.13 |
| b2 | 9 | 749 | 86.3 | 94.9 | 28.3%±1.9 | -0.72±0.12 |
| b2 | 10 | 742 | 95.0 | 100.0 | 38.0%±2.3 | -0.78±0.11 |

**Yorum.** Etiket SL'si geniş (R2, %5) veya SL'siz (replay) iken hit oranı skorla artar (ρ≈+0,8…0,96) ama artış yüzde-puan düzeyinde küçük ve 85'ten sonra düzleşir; SL %1,5'te (R1) ters/negatif: yüksek skor = yüksek ATR → dar stop önce vurulur. Yani skorun "isabet" ilişkisi, stop geometrisine bağlı bir ATR etkisidir. Net ise her iki rejimde de skorla birlikte KÖTÜLEŞİR (R2: ρ=−0,83/−0,88). 90–95 < 85–90 kırılması journal'da sistematik değil (R2a 59,0→59,6); bildirimde görülen 95–99,9 çukuru (aşağıda) karışım/örneklem gürültüsüdür.

### 3.3 Kırpma (panel=100) bilgi kaybı
| nüfus | panel=100 içinde ham skor dilimi | n | hit±SE | ort. net±SE | ort. ATR% |
|---|---|---|---|---|---|
| DB R1+R2 | ham 24,887–35,595 | 1579 | 45.8%±4.8 | -0.60±0.11 | 1.39 |
| DB R1+R2 | ham 35,595–58,234 | 1579 | 44.2%±4.3 | -0.83±0.13 | 1.56 |
| DB R1+R2 | ham 58,234–130,192 | 1579 | 46.0%±5.1 | -0.79±0.18 | 1.82 |
| DB R1+R2 | ham 130,192–65,806,412 | 1579 | 50.9%±4.1 | -0.77±0.20 | 2.53 |
| DB R1+R2 | panel=100 İÇİNDE ham skor AUC(hit) | 6316 | 0.519±0.011 | ATR-strata 0.530±0.007 |  |
| Replay | ham 24,890–37,757 | 336 | 36.9%±2.8 | -0.70±0.17 | 1.18 |
| Replay | ham 37,757–62,866 | 335 | 35.8%±2.9 | -0.77±0.19 | 1.31 |
| Replay | ham 62,866–134,364 | 336 | 40.5%±2.9 | -0.93±0.18 | 1.55 |
| Replay | ham 134,364–41,458,039 | 336 | 47.9%±2.7 | -0.76±0.20 | 2.51 |
| Replay | panel=100 İÇİNDE ham skor AUC(hit) | 1343 | 0.554±0.014 | ATR-strata 0.510±0.015 |  |

AUC(ham)=AUC(panel) (fark ≤0,001): kırpma sıralamayı genel olarak bozmuyor; ama "100" tek kovada ham 25 bin…66 milyonu topluyor ve kova-içi ham skor ATR kontrolüyle AUC 0,51–0,53 → eklenecek bilgi yok. Sorun kırpma değil, ölçeğin bir olasılık/kalite gibi okunması.

## 4. (b) Bileşenler: neyin ayrım gücü var?
ATR payı (skorun ATR ile açıklanan kısmı):
| blok | n | R²(ln skor ~ ln ATR) | SD(ln ham skor) | SD(ln artık = BB×yapı×hacim×çarpan) |
|---|---|---|---|---|
| B1 | 35563 | 0.341 | 1.61 | 1.32 |
| B2 | 41363 | 0.161 | 1.85 | 1.62 |
| B3 | 33028 | 0.336 | 1.75 | 1.38 |
| R1a | 25591 | 0.333 | 1.59 | 1.30 |
| R1b | 32588 | 0.102 | 1.83 | 1.66 |
| R2a | 30065 | 0.243 | 1.85 | 1.54 |
| R2b | 14654 | 0.423 | 1.68 | 1.25 |

Çarpanların panel ölçeğindeki (sabit) etkisi — log harita: tüm "kalite" çarpanları (MACD, taker, öncü ATR, whale) ≤ ±1,4 puan; yalnız "ceza" çarpanları (geç faz −5,0; choppiness −6,8) büyüktür:
| çarpan | panel puanına etkisi (sabit; log harita) |
|---|---|
| taker güçlü ×1.05 | +0.48 |
| taker zayıf ×0.95 | -0.51 |
| MACD ivmeli ×1.15 | +1.38 |
| MACD pozitif ×1.05 | +0.48 |
| M5+MACD ×1.10 | +0.94 |
| öncü ATR (leading) ×1.15 | +1.38 |
| aşırı alım cezası ×0.85 | -1.60 |
| spread bilinmiyor ×0.85 | -1.60 |
| geç faz ×0.6 | -5.04 |
| choppiness rejimi ×0.5 | -6.84 |
| whale var ×1.05 (yalnız SIRALAMA) | +0.48 |
| no_whale ×0.9 (yalnız SIRALAMA) | -1.04 |

**DB (R1a/R1b/R2a/R2b; hit etiketi):**
| özellik | n | AUC R1a | AUC R1b | AUC R2a | AUC R2b | ATR-strata AUC±SE | lojistik β/SD (ATR+ufuk+rejim kontrollü) |
|---|---|---|---|---|---|---|---|
| log_atr | 102898 | 0.491 | 0.500 | 0.612 | 0.586 | 0.508±0.004 | +0.103 (t=+4.7) |
| log_score | 102898 | 0.473 | 0.484 | 0.551 | 0.560 | 0.500±0.008 | -0.099 (t=-4.8) |
| log_rest | 102898 | 0.472 | 0.478 | 0.507 | 0.528 | 0.494±0.007 | -0.113 (t=-5.9) |
| ret3 | 102898 | 0.488 | 0.507 | 0.515 | 0.502 | 0.507±0.005 | +0.019 (t=+1.4) |
| mom_term | 102898 | 0.492 | 0.510 | 0.526 | 0.514 | 0.509±0.004 | +0.035 (t=+3.1) |
| log_tgt_atr | 102898 | 0.480 | 0.477 | 0.377 | 0.386 | 0.453±0.004 | -0.722 (t=-17.0) |
| target | 102898 | 0.450 | 0.461 | 0.477 | 0.424 | 0.452±0.006 | -0.353 (t=-13.0) |
| leading_ok | 102898 | 0.477 | 0.499 | 0.545 | 0.516 | 0.498±0.002 | -0.161 (t=-6.3) |
| m5_ok | 102863 | 0.486 | 0.493 | 0.546 | 0.529 | 0.504±0.008 | +0.016 (t=+0.8) |
| g0_chg5 | 102863 | 0.493 | 0.488 | 0.508 | 0.500 | 0.497±0.006 | -0.027 (t=-1.5) |
| g0_chg3 | 102863 | 0.491 | 0.496 | 0.504 | 0.495 | 0.502±0.005 | -0.005 (t=-0.3) |
| g0_roc | 102863 | 0.486 | 0.494 | 0.523 | 0.514 | 0.498±0.006 | -0.024 (t=-1.3) |
| g0_atr | 102863 | 0.499 | 0.512 | 0.548 | 0.551 | 0.516±0.005 | +0.190 (t=+8.4) |
| g1_atr | 102863 | 0.499 | 0.513 | 0.551 | 0.549 | 0.517±0.005 | +0.178 (t=+7.6) |
| g2_atr | 102863 | 0.499 | 0.514 | 0.563 | 0.559 | 0.521±0.007 | +0.183 (t=+6.0) |
| no_whale | 75815 | 0.505 | 0.492 | 0.438 | 0.444 | 0.479±0.009 | -0.105 (t=-4.3) |
| whale_cnt | 75815 | 0.491 | 0.514 | 0.572 | 0.565 | 0.526±0.012 | +0.105 (t=+3.4) |
| cvd_sgn | 75815 | 0.528 | 0.555 | 0.528 | 0.534 | 0.532±0.003 | +0.120 (t=+10.3) |
| trade_rate | 75815 | 0.496 | 0.521 | 0.595 | 0.587 | 0.537±0.014 | +0.161 (t=+4.2) |
| ml_prob | 98647 | 0.487 | 0.503 | 0.624 | 0.619 | 0.530±0.012 | +0.309 (t=+2.9) |
| hour_sin | 102898 | 0.517 | 0.519 | 0.517 | 0.488 | 0.518±0.005 | +0.058 (t=+2.6) |
| hour_cos | 102898 | 0.485 | 0.481 | 0.512 | 0.435 | 0.494±0.011 | -0.048 (t=-1.7) |

**Replay (b0/b1/b2; hit etiketi; mod, taker, choppiness, rsi, mfi, hacim, 24s değişim dahil):**
| özellik | n | AUC b0 | AUC b1 | AUC b2 | ATR-strata AUC±SE | lojistik β/SD (ATR+ufuk+rejim kontrollü) |
|---|---|---|---|---|---|---|
| log_atr | 20343 | 0.679 | 0.657 | 0.655 | 0.538±0.005 | +0.291 (t=+31.3) |
| log_score | 20343 | 0.599 | 0.594 | 0.594 | 0.503±0.005 | -0.066 (t=-3.1) |
| log_rest | 20343 | 0.528 | 0.541 | 0.541 | 0.497±0.005 | -0.058 (t=-3.5) |
| log_rest2 | 20343 | 0.526 | 0.538 | 0.539 | 0.498±0.005 | -0.060 (t=-3.7) |
| ret3 | 20343 | 0.505 | 0.499 | 0.497 | 0.500±0.004 | +0.022 (t=+1.3) |
| mom_term | 20343 | 0.524 | 0.512 | 0.514 | 0.502±0.004 | +0.011 (t=+0.7) |
| volume_ratio | 20343 | 0.515 | 0.527 | 0.517 | 0.503±0.005 | -0.008 (t=-0.4) |
| vol_term | 20343 | 0.516 | 0.527 | 0.518 | 0.502±0.005 | -0.004 (t=-0.2) |
| log_tgt_atr | 20343 | 0.320 | 0.344 | 0.344 | 0.457±0.005 | -0.382 (t=-5.3) |
| rank | 20343 | 0.422 | 0.440 | 0.432 | 0.497±0.005 | -0.002 (t=-0.1) |
| mode_trend | 20343 | 0.460 | 0.473 | 0.476 | 0.501±0.004 | -0.005 (t=-0.3) |
| mode_notr | 20343 | 0.544 | 0.532 | 0.535 | 0.505±0.004 | +0.030 (t=+1.7) |
| mode_vdon | 20343 | 0.496 | 0.495 | 0.488 | 0.494±0.002 | -0.054 (t=-2.8) |
| rsi | 20343 | 0.453 | 0.469 | 0.471 | 0.500±0.005 | +0.015 (t=+0.9) |
| mfi | 20343 | 0.459 | 0.484 | 0.491 | 0.502±0.006 | +0.025 (t=+1.4) |
| change_24h | 20336 | 0.648 | 0.615 | 0.611 | 0.567±0.006 | +0.199 (t=+11.5) |
| taker_buy | 20341 | 0.489 | 0.498 | 0.488 | 0.512±0.005 | +0.066 (t=+3.5) |
| chop10 | 20334 | 0.597 | 0.580 | 0.582 | 0.518±0.005 | +0.061 (t=+3.2) |
| range_pos60 | 20343 | 0.453 | 0.465 | 0.478 | 0.507±0.005 | +0.024 (t=+1.3) |
| m1_atr_prev | 20343 | 0.680 | 0.656 | 0.656 | 0.541±0.005 | -0.101 (t=-2.9) |
| m3_atr_prev | 20343 | 0.682 | 0.653 | 0.656 | 0.548±0.005 | -0.003 (t=-0.1) |
| m5_ok | 20343 | 0.527 | 0.529 | 0.534 | 0.509±0.004 | +0.025 (t=+1.4) |
| leading_ok | 20343 | 0.585 | 0.545 | 0.552 | 0.512±0.002 | -0.007 (t=-0.4) |
| late_phase | 20343 | 0.556 | 0.516 | 0.540 | 0.518±0.003 | +0.133 (t=+7.6) |
| hour_sin | 20343 | 0.513 | 0.509 | 0.491 | 0.514±0.006 | +0.056 (t=+3.1) |
| hour_cos | 20343 | 0.468 | 0.469 | 0.499 | 0.484±0.006 | -0.063 (t=-3.6) |

**Okuma.** (i) `log_atr` tek başına replay'de AUC 0,66–0,68 > skorun 0,59–0,60; ATR kontrollü `log_score` β<0. (ii) Skorun ATR-dışı kısmı (`log_rest`, `log_rest2` = BB×yapı×çarpanlar) ATR-strata AUC ≈0,50 ve β<0; `volume_ratio`/hacim terimi (0,5…1,0 çarpan, ≤6,8 panel puanı oynatır) ATR-strata AUC 0,503, `ret3`/momentum terimi 0,500–0,509: ATR dışı hiçbir skor bileşeni ek ayrım getirmiyor. (iii) En güçlü ek bilgi skorun DIŞINDA: 24s değişim (`change_24h`, ATR-strata AUC 0,567, β +0,20, t=+11,5), `m1/m3_atr_prev` (0,54–0,55), CVD (aşağıda), hedef/ATR geometrisi (`log_tgt_atr`, ATR-strata AUC 0,457 = ters yönde güçlü).

### 4.1 Skor çarpanı bayrakları: tasarım yönü vs ölçülen (ATR-strata içi fark)
Replay:
| bayrak | tasarım yönü (skor çarpanı) | n bayraklı | n bayraksız | Δ hit (ATR-strata içi)±SE | Δ net±SE |
|---|---|---|---|---|---|
| geç faz (24s ≥ %40) | ×0,6 (ceza) | 972 | 19371 | +15.5±2.1 puan | +0.034±0.113 |
| taker güçlü (≥0,58) | ×1,05 (bonus) | 8204 | 12139 | +0.7±0.6 puan | +0.067±0.031 |
| taker zayıf (≤0,45) | ×0,95 (ceza) | 5516 | 14827 | -2.4±0.7 puan | -0.082±0.042 |
| choppiness>61,8 (ADX'siz yaklaşık) | ×0,5 (ceza; yalnız ADX<20 iken) | 166 | 20177 | -1.0±3.9 puan | +0.160±0.226 |
| öncü ATR (leading_ok) | ×1,15 (bonus) | 1969 | 18374 | +8.4±1.5 puan | -0.224±0.095 |
| M5 deseni tam (m5_ok) | yalnız etiket/kapı; skora girmez | 5279 | 15064 | +1.5±0.7 puan | -0.058±0.044 |
| hacim oranı ≥ 2 (hacim terimi tavanı) | terim 0,5→1,0 | 4305 | 16038 | -0.7±0.7 puan | +0.016±0.048 |
| mod = trend_devam | — | 11972 | 8371 | +0.1±0.6 puan | -0.028±0.037 |
| mod = notr | — | 7115 | 13228 | +0.8±0.7 puan | -0.001±0.042 |

DB (R1+R2 blokları):
| bayrak | tasarım yönü (skor çarpanı) | n bayraklı | n bayraksız | Δ hit (ATR-strata içi)±SE | Δ net±SE |
|---|---|---|---|---|---|
| öncü ATR (leading_ok) | ×1,15 (bonus) | 26155 | 76743 | -2.5±1.4 puan | -0.124±0.067 |
| no_whale (whale yok) | ×0,9 (yalnız SIRALAMA) | 32000 | 43815 | -4.1±1.2 puan | -0.021±0.058 |
| CVD > 0 (CVD≠0 olanlar arasında; CVD<0'a karşı) | skora girmez (docstring: 'CVD ayırmıyor') | 26361 | 29006 | +5.8±0.6 puan | +0.286±0.032 |
| trade_rate > 0 (mikro-yapı akışı var) | skora girmez | 55377 | 20438 | +6.4±1.5 puan | +0.034±0.086 |
| M5 deseni tam (m5_ok) | yalnız etiket/kapı | 39866 | 63032 | +0.7±1.0 puan | +0.009±0.027 |

Dikkat çeken: **geç faz cezası (×0,6)** yön olarak YANLIŞ — geç fazda hit +15,5 puan, net ≈0 (n=972); **öncü ATR bonusu (×1,15)** hit'i artırıyor (replay +8,4 puan) ama net'i düşürüyor (−0,22/−0,12); taker bonus/ceza yön olarak doğru ama küçük (+0,7 / −2,4 puan); **CVD işareti** (skora girmiyor; velocity.py:2491 docstring "CVD ayırmıyor" diyor) ATR kontrollü hit +5,8±0,6 puan, net +0,29±0,03, dört blokta aynı işaret (CVD≠0 satırlarda, CVD>0 vs <0). Uyarı: `cvd_try` ölçüm penceresi ve sinyal anı hizası (look-ahead) çıkarım öncesi doğrulanmalı.

### 4.2 Tek gün, zengin özellikler (DB `features`, 17 Eki; keşif — küme SE yok)
n=1314, günler=[30] (17 Eki), tek gün → küme SE'si hesaplanamaz; KEŞİF amaçlı.
| özellik | n | AUC(hit) | ATR-strata AUC(hit) | AUC(net>0) |
|---|---|---|---|---|
| taker_buy_ratio | 1314 | 0.502 | 0.500 | 0.502 |
| book_imbalance | 1294 | 0.537 | 0.524 | 0.555 |
| volume_ratio | 1314 | 0.529 | 0.525 | 0.499 |
| bb_width_pct | 1314 | 0.505 | 0.517 | 0.469 |
| rsi | 1314 | 0.507 | 0.502 | 0.490 |
| mfi | 1314 | 0.512 | 0.505 | 0.497 |
| choppiness_10 | 1314 | 0.540 | 0.507 | 0.511 |
| range_pos_60 | 1314 | 0.526 | 0.518 | 0.500 |
| adx_14 | 1314 | 0.544 | 0.530 | 0.503 |
| change_24h | 1314 | 0.592 | 0.559 | 0.552 |
| ret_8h_pct | 1314 | 0.605 | 0.582 | 0.564 |
| slope_15m | 1314 | 0.541 | 0.511 | 0.535 |
| aroon_up | 1314 | 0.457 | 0.463 | 0.445 |
| linreg_slope10_pct | 1314 | 0.495 | 0.496 | 0.479 |
| panel (karşılaştırma) | 1314 | 0.519 | 0.507 | 0.481 |

## 5. (c) Yeniden ağırlıklandırma — yürüyen-ileri
DB (canlı):
**B1→B2** — test n=41363, gün=8, test taban: hit 36.8%, ort. net -0.532±0.029. Üst dilim = tahminin en yüksek %10'u.
| tahmin | AUC hit±SE | AUC net>0±SE | üst %10 n | üst %10 hit | üst %10 ort. net | ρ(tahmin,net) | Brier becerisi (hit; eğitim taban oranına göre) |
|---|---|---|---|---|---|---|---|
| MEVCUT panel | 0.522±0.014 | 0.503±0.013 | 4154 | 40.8%±7.4 | -0.65±0.05 | -0.010 | – |
| MEVCUT ham (kırpmasız) | 0.522±0.014 | 0.503±0.013 | 4137 | 40.6%±7.4 | -0.66±0.05 | -0.010 | – |
| ML olasılığı (mevcut) | 0.635±0.048 | 0.604±0.053 | 4231 | 66.6%±1.2 | -0.46±0.06 | -0.018 | -23.1% |
| LR sade (log_skor+ufuk) →hit | 0.465±0.020 | 0.494±0.019 | 4137 | 30.3%±2.6 | -0.46±0.05 | +0.014 | -0.7% |
| LR ATR+hedef geometrisi →hit | 0.642±0.034 | 0.629±0.030 | 4143 | 61.7%±2.5 | -0.53±0.05 | +0.007 | +4.6% |
| LR tam →hit | 0.643±0.031 | 0.622±0.030 | 4137 | 62.2%±1.6 | -0.45±0.02 | +0.002 | +5.9% |
| LR tam →net>0 | 0.629±0.029 | 0.622±0.025 | 4137 | 57.9%±2.0 | -0.51±0.03 | +0.016 | – |
| HGB tam →hit | 0.633±0.031 | 0.612±0.031 | 4137 | 57.7%±2.5 | -0.45±0.04 | +0.025 | +5.0% |
| HGB tam →net>0 | 0.619±0.028 | 0.609±0.026 | 4139 | 54.8%±3.1 | -0.46±0.02 | +0.027 | – |
| NET-E: HGB p×(hedef−c)+(1−p)×kayıp | 0.547±0.016 | 0.544±0.014 | 4137 | 38.4%±5.9 | -0.45±0.08 | +0.048 | – |
| NET-E: isotonic(skor) p×(hedef−c)+(1−p)×ort.kayıp | 0.398±0.020 | 0.390±0.017 | 4137 | 25.8%±3.0 | -0.59±0.06 | -0.013 | – |
| NET-REG: HGB doğrudan net | 0.564±0.024 | 0.551±0.021 | 4137 | 41.8%±7.4 | -0.45±0.10 | +0.030 | – |
Üst-%10 net farkı (tahmin − MEVCUT panel, gün-jackknife): ML olasılığı (mevcut): +0.195±0.101; LR sade (log_skor+ufuk) →hit: +0.190±0.058; LR ATR+hedef geometrisi →hit: +0.122±0.103; LR tam →hit: +0.206±0.059; LR tam →net>0: +0.138±0.059; HGB tam →hit: +0.205±0.051; HGB tam →net>0: +0.190±0.046; NET-E: +0.198±0.081; NET-E: +0.060±0.063; NET-REG: +0.199±0.092
Mevcut kural kesitleri (aynı test bloğu): 
| kural | n | kapsam | hit | ort. net |
|---|---|---|---|---|
| panel ≥ 70 | 22457 | 54.3% | 37.9%±5.3 | -0.56±0.04 |
| panel ≥ 85 | 9707 | 23.5% | 39.7%±6.7 | -0.59±0.04 |
| panel ≥ 95 | 4822 | 11.7% | 40.9%±7.4 | -0.65±0.05 |
| panel ≥ 100 | 3301 | 8.0% | 40.9%±7.4 | -0.67±0.06 |

**B1+B2→B3** — test n=33028, gün=8, test taban: hit 49.7%, ort. net -0.551±0.068. Üst dilim = tahminin en yüksek %10'u.
| tahmin | AUC hit±SE | AUC net>0±SE | üst %10 n | üst %10 hit | üst %10 ort. net | ρ(tahmin,net) | Brier becerisi (hit; eğitim taban oranına göre) |
|---|---|---|---|---|---|---|---|
| MEVCUT panel | 0.555±0.008 | 0.526±0.007 | 3310 | 55.4%±2.6 | -1.01±0.17 | +0.034 | – |
| MEVCUT ham (kırpmasız) | 0.555±0.008 | 0.526±0.007 | 3303 | 55.3%±2.7 | -1.01±0.17 | +0.034 | – |
| ML olasılığı (mevcut) | 0.613±0.009 | 0.574±0.011 | 3518 | 60.5%±2.9 | -0.81±0.17 | +0.080 | -42.8% |
| LR sade (log_skor+ufuk) →hit | 0.530±0.007 | 0.511±0.008 | 3303 | 52.9%±2.5 | -0.94±0.14 | +0.045 | +0.6% |
| LR ATR+hedef geometrisi →hit | 0.620±0.011 | 0.579±0.008 | 3303 | 63.3%±2.5 | -0.62±0.13 | -0.049 | +9.9% |
| LR tam →hit | 0.642±0.011 | 0.597±0.009 | 3303 | 65.3%±1.8 | -0.56±0.09 | +0.014 | +12.7% |
| LR tam →net>0 | 0.633±0.010 | 0.593±0.009 | 3303 | 64.8%±1.6 | -0.51±0.07 | -0.001 | – |
| HGB tam →hit | 0.635±0.011 | 0.593±0.012 | 3303 | 68.0%±2.1 | -0.42±0.11 | +0.048 | +11.7% |
| HGB tam →net>0 | 0.620±0.013 | 0.585±0.014 | 3303 | 68.0%±2.1 | -0.40±0.10 | +0.047 | – |
| NET-E: HGB p×(hedef−c)+(1−p)×kayıp | 0.496±0.009 | 0.507±0.009 | 3303 | 54.5%±4.1 | -0.37±0.17 | +0.044 | – |
| NET-E: isotonic(skor) p×(hedef−c)+(1−p)×ort.kayıp | 0.451±0.014 | 0.465±0.012 | 3304 | 47.5%±3.5 | -0.68±0.20 | +0.130 | – |
| NET-REG: HGB doğrudan net | 0.514±0.006 | 0.520±0.008 | 3303 | 61.3%±1.8 | -0.43±0.04 | +0.038 | – |
Üst-%10 net farkı (tahmin − MEVCUT panel, gün-jackknife): ML olasılığı (mevcut): +0.195±0.092; LR sade (log_skor+ufuk) →hit: +0.070±0.071; LR ATR+hedef geometrisi →hit: +0.388±0.175; LR tam →hit: +0.446±0.165; LR tam →net>0: +0.497±0.164; HGB tam →hit: +0.587±0.098; HGB tam →net>0: +0.608±0.122; NET-E: +0.640±0.171; NET-E: +0.328±0.095; NET-REG: +0.578±0.158
Mevcut kural kesitleri (aynı test bloğu): 
| kural | n | kapsam | hit | ort. net |
|---|---|---|---|---|
| panel ≥ 70 | 20386 | 61.7% | 53.3%±1.7 | -0.62±0.09 |
| panel ≥ 85 | 9011 | 27.3% | 55.6%±2.4 | -0.75±0.14 |
| panel ≥ 95 | 4176 | 12.6% | 55.8%±2.8 | -0.94±0.18 |
| panel ≥ 100 | 2764 | 8.4% | 55.1%±2.7 | -1.08±0.18 |

**R1a→R1b** — test n=32588, gün=7, test taban: hit 29.4%, ort. net -0.498±0.044. Üst dilim = tahminin en yüksek %10'u.
| tahmin | AUC hit±SE | AUC net>0±SE | üst %10 n | üst %10 hit | üst %10 ort. net | ρ(tahmin,net) | Brier becerisi (hit; eğitim taban oranına göre) |
|---|---|---|---|---|---|---|---|
| MEVCUT panel | 0.484±0.010 | 0.476±0.008 | 3288 | 27.4%±2.3 | -0.51±0.11 | -0.012 | – |
| MEVCUT ham (kırpmasız) | 0.484±0.010 | 0.476±0.008 | 3259 | 27.5%±2.4 | -0.51±0.12 | -0.011 | – |
| ML olasılığı (mevcut) | 0.503±0.012 | 0.469±0.015 | 3260 | 29.5%±2.9 | -0.49±0.12 | -0.081 | -21.6% |
| LR sade (log_skor+ufuk) →hit | 0.517±0.010 | 0.533±0.009 | 3259 | 30.5%±3.0 | -0.47±0.06 | +0.032 | +0.6% |
| LR ATR+hedef geometrisi →hit | 0.548±0.006 | 0.548±0.002 | 3259 | 35.3%±2.4 | -0.53±0.08 | +0.006 | +1.6% |
| LR tam →hit | 0.551±0.005 | 0.540±0.007 | 3259 | 37.5%±2.0 | -0.41±0.06 | +0.004 | +1.9% |
| LR tam →net>0 | 0.538±0.004 | 0.544±0.004 | 3259 | 33.3%±2.1 | -0.43±0.04 | +0.034 | – |
| HGB tam →hit | 0.542±0.008 | 0.531±0.008 | 3259 | 33.3%±3.2 | -0.46±0.11 | +0.013 | -0.3% |
| HGB tam →net>0 | 0.528±0.010 | 0.533±0.009 | 3259 | 33.0%±3.3 | -0.40±0.11 | +0.039 | – |
| NET-E: HGB p×(hedef−c)+(1−p)×kayıp | 0.518±0.012 | 0.521±0.010 | 3259 | 31.7%±3.3 | -0.37±0.13 | +0.043 | – |
| NET-E: isotonic(skor) p×(hedef−c)+(1−p)×ort.kayıp | 0.462±0.006 | 0.444±0.005 | 3262 | 23.4%±2.4 | -0.52±0.13 | -0.043 | – |
| NET-REG: HGB doğrudan net | 0.513±0.009 | 0.519±0.008 | 3259 | 31.8%±3.1 | -0.36±0.12 | +0.044 | – |
Üst-%10 net farkı (tahmin − MEVCUT panel, gün-jackknife): ML olasılığı (mevcut): +0.020±0.061; LR sade (log_skor+ufuk) →hit: +0.036±0.107; LR ATR+hedef geometrisi →hit: -0.025±0.104; LR tam →hit: +0.097±0.092; LR tam →net>0: +0.078±0.100; HGB tam →hit: +0.044±0.093; HGB tam →net>0: +0.113±0.114; NET-E: +0.137±0.114; NET-E: -0.016±0.086; NET-REG: +0.150±0.096
Mevcut kural kesitleri (aynı test bloğu): 
| kural | n | kapsam | hit | ort. net |
|---|---|---|---|---|
| panel ≥ 70 | 15935 | 48.9% | 28.2%±1.4 | -0.50±0.06 |
| panel ≥ 85 | 6501 | 19.9% | 27.3%±1.9 | -0.52±0.09 |
| panel ≥ 95 | 2978 | 9.1% | 27.5%±2.6 | -0.50±0.13 |
| panel ≥ 100 | 1994 | 6.1% | 27.7%±2.9 | -0.50±0.14 |

**R2a→R2b** — test n=14654, gün=5, test taban: hit 45.8%, ort. net -0.596±0.040. Üst dilim = tahminin en yüksek %10'u.
| tahmin | AUC hit±SE | AUC net>0±SE | üst %10 n | üst %10 hit | üst %10 ort. net | ρ(tahmin,net) | Brier becerisi (hit; eğitim taban oranına göre) |
|---|---|---|---|---|---|---|---|
| MEVCUT panel | 0.560±0.009 | 0.526±0.012 | 1473 | 51.7%±3.9 | -1.20±0.18 | -0.005 | – |
| MEVCUT ham (kırpmasız) | 0.560±0.009 | 0.526±0.012 | 1467 | 51.7%±3.9 | -1.20±0.18 | -0.005 | – |
| ML olasılığı (mevcut) | 0.608±0.012 | 0.563±0.010 | 1532 | 53.3%±2.2 | -1.14±0.11 | +0.025 | -57.1% |
| LR sade (log_skor+ufuk) →hit | 0.530±0.006 | 0.509±0.009 | 1466 | 50.1%±4.1 | -1.08±0.14 | +0.016 | -1.0% |
| LR ATR+hedef geometrisi →hit | 0.620±0.028 | 0.570±0.020 | 1466 | 55.3%±3.2 | -1.00±0.16 | -0.012 | +6.3% |
| LR tam →hit | 0.636±0.025 | 0.585±0.024 | 1466 | 61.4%±2.5 | -0.70±0.17 | +0.023 | +7.5% |
| LR tam →net>0 | 0.620±0.025 | 0.576±0.029 | 1466 | 59.8%±1.0 | -0.64±0.13 | +0.031 | – |
| HGB tam →hit | 0.632±0.016 | 0.583±0.014 | 1466 | 63.4%±0.8 | -0.56±0.14 | +0.030 | +6.4% |
| HGB tam →net>0 | 0.605±0.016 | 0.570±0.018 | 1466 | 63.2%±0.5 | -0.57±0.06 | +0.031 | – |
| NET-E: HGB p×(hedef−c)+(1−p)×kayıp | 0.478±0.012 | 0.492±0.017 | 1466 | 46.7%±5.3 | -0.61±0.06 | +0.035 | – |
| NET-E: isotonic(skor) p×(hedef−c)+(1−p)×ort.kayıp | 0.483±0.009 | 0.480±0.012 | 1469 | 44.6%±3.5 | -0.88±0.15 | +0.046 | – |
| NET-REG: HGB doğrudan net | 0.477±0.018 | 0.491±0.020 | 1466 | 50.3%±5.3 | -0.53±0.08 | +0.029 | – |
Üst-%10 net farkı (tahmin − MEVCUT panel, gün-jackknife): ML olasılığı (mevcut): +0.054±0.327; LR sade (log_skor+ufuk) →hit: +0.115±0.113; LR ATR+hedef geometrisi →hit: +0.193±0.396; LR tam →hit: +0.500±0.470; LR tam →net>0: +0.559±0.411; HGB tam →hit: +0.633±0.413; HGB tam →net>0: +0.629±0.294; NET-E: +0.591±0.212; NET-E: +0.316±0.254; NET-REG: +0.666±0.148
Mevcut kural kesitleri (aynı test bloğu): 
| kural | n | kapsam | hit | ort. net |
|---|---|---|---|---|
| panel ≥ 70 | 8864 | 60.5% | 49.9%±2.3 | -0.70±0.06 |
| panel ≥ 85 | 3754 | 25.6% | 51.8%±2.9 | -0.88±0.10 |
| panel ≥ 95 | 1678 | 11.5% | 52.4%±3.4 | -1.10±0.15 |
| panel ≥ 100 | 1086 | 7.4% | 50.6%±3.5 | -1.32±0.19 |


Replay 90 g:
**b0→b1** — test n=6797, gün=30, test taban: hit 21.3%, ort. net -0.506±0.036. Üst dilim = tahminin en yüksek %10'u.
| tahmin | AUC hit±SE | AUC net>0±SE | üst %10 n | üst %10 hit | üst %10 ort. net | ρ(tahmin,net) | Brier becerisi (hit; eğitim taban oranına göre) |
|---|---|---|---|---|---|---|---|
| MEVCUT panel | 0.594±0.008 | 0.515±0.008 | 685 | 38.1%±1.7 | -0.42±0.12 | -0.040 | – |
| MEVCUT ham (kırpmasız) | 0.594±0.008 | 0.515±0.008 | 680 | 38.4%±1.7 | -0.39±0.12 | -0.040 | – |
| LR sade (log_skor+ufuk) →hit | 0.594±0.008 | 0.515±0.008 | 680 | 38.4%±1.7 | -0.39±0.12 | -0.040 | +2.6% |
| LR ATR+hedef geometrisi →hit | 0.657±0.008 | 0.534±0.009 | 681 | 41.1%±2.1 | -0.60±0.12 | -0.062 | +6.0% |
| LR tam →hit | 0.664±0.007 | 0.535±0.008 | 680 | 42.1%±1.9 | -0.74±0.12 | -0.063 | +6.8% |
| LR tam →net>0 | 0.609±0.008 | 0.528±0.008 | 680 | 35.7%±1.8 | -0.46±0.07 | -0.035 | – |
| HGB tam →hit | 0.656±0.007 | 0.536±0.008 | 680 | 42.8%±1.9 | -0.56±0.09 | -0.057 | +5.4% |
| HGB tam →net>0 | 0.569±0.007 | 0.514±0.007 | 680 | 29.7%±1.6 | -0.54±0.08 | -0.031 | – |
| NET-E: HGB p×(hedef−c)+(1−p)×kayıp | 0.549±0.009 | 0.497±0.007 | 680 | 38.5%±2.2 | -0.46±0.11 | -0.036 | – |
| NET-E: isotonic(skor) p×(hedef−c)+(1−p)×ort.kayıp | 0.586±0.008 | 0.513±0.009 | 1108 | 33.5%±1.5 | -0.39±0.08 | -0.039 | – |
| NET-REG: HGB doğrudan net | 0.495±0.006 | 0.487±0.006 | 680 | 25.9%±1.3 | -0.56±0.09 | -0.020 | – |
Üst-%10 net farkı (tahmin − MEVCUT panel, gün-jackknife): LR sade (log_skor+ufuk) →hit: +0.022±0.009; LR ATR+hedef geometrisi →hit: -0.189±0.115; LR tam →hit: -0.327±0.098; LR tam →net>0: -0.049±0.119; HGB tam →hit: -0.142±0.108; HGB tam →net>0: -0.123±0.130; NET-E: -0.040±0.135; NET-E: +0.024±0.065; NET-REG: -0.147±0.119
Mevcut kural kesitleri (aynı test bloğu): 
| kural | n | kapsam | hit | ort. net |
|---|---|---|---|---|
| panel ≥ 70 | 3980 | 58.6% | 24.4%±0.9 | -0.50±0.05 |
| panel ≥ 85 | 1335 | 19.6% | 32.5%±1.3 | -0.44±0.08 |
| panel ≥ 95 | 574 | 8.4% | 38.2%±1.9 | -0.47±0.14 |
| panel ≥ 100 | 387 | 5.7% | 39.0%±2.2 | -0.51±0.14 |

**b0+b1→b2** — test n=7436, gün=29, test taban: hit 22.5%, ort. net -0.613±0.036. Üst dilim = tahminin en yüksek %10'u.
| tahmin | AUC hit±SE | AUC net>0±SE | üst %10 n | üst %10 hit | üst %10 ort. net | ρ(tahmin,net) | Brier becerisi (hit; eğitim taban oranına göre) |
|---|---|---|---|---|---|---|---|
| MEVCUT panel | 0.593±0.008 | 0.498±0.007 | 748 | 38.1%±2.3 | -0.78±0.11 | -0.076 | – |
| MEVCUT ham (kırpmasız) | 0.594±0.008 | 0.498±0.007 | 744 | 38.0%±2.3 | -0.78±0.11 | -0.076 | – |
| LR sade (log_skor+ufuk) →hit | 0.594±0.008 | 0.498±0.007 | 744 | 38.0%±2.3 | -0.78±0.11 | -0.076 | +2.4% |
| LR ATR+hedef geometrisi →hit | 0.657±0.007 | 0.518±0.008 | 744 | 43.7%±2.3 | -0.86±0.09 | -0.089 | +5.5% |
| LR tam →hit | 0.663±0.008 | 0.520±0.008 | 744 | 44.8%±2.2 | -0.80±0.10 | -0.091 | +6.3% |
| LR tam →net>0 | 0.604±0.008 | 0.523±0.006 | 744 | 36.2%±2.0 | -0.66±0.09 | -0.049 | – |
| HGB tam →hit | 0.665±0.008 | 0.526±0.007 | 744 | 45.0%±2.3 | -0.67±0.09 | -0.081 | +6.0% |
| HGB tam →net>0 | 0.561±0.007 | 0.528±0.007 | 744 | 29.6%±2.2 | -0.52±0.10 | -0.022 | – |
| NET-E: HGB p×(hedef−c)+(1−p)×kayıp | 0.565±0.008 | 0.516±0.004 | 744 | 40.7%±2.6 | -0.56±0.09 | -0.015 | – |
| NET-E: isotonic(skor) p×(hedef−c)+(1−p)×ort.kayıp | 0.590±0.008 | 0.499±0.007 | 783 | 37.5%±2.3 | -0.75±0.11 | -0.073 | – |
| NET-REG: HGB doğrudan net | 0.481±0.008 | 0.511±0.006 | 744 | 29.2%±1.9 | -0.37±0.09 | +0.031 | – |
Üst-%10 net farkı (tahmin − MEVCUT panel, gün-jackknife): LR sade (log_skor+ufuk) →hit: -0.005±0.010; LR ATR+hedef geometrisi →hit: -0.085±0.115; LR tam →hit: -0.021±0.118; LR tam →net>0: +0.121±0.119; HGB tam →hit: +0.103±0.107; HGB tam →net>0: +0.259±0.141; NET-E: +0.219±0.106; NET-E: +0.026±0.037; NET-REG: +0.401±0.122
Mevcut kural kesitleri (aynı test bloğu): 
| kural | n | kapsam | hit | ort. net |
|---|---|---|---|---|
| panel ≥ 70 | 4498 | 60.5% | 25.3%±1.0 | -0.65±0.04 |
| panel ≥ 85 | 1666 | 22.4% | 32.7%±1.6 | -0.71±0.07 |
| panel ≥ 95 | 742 | 10.0% | 38.0%±2.3 | -0.78±0.11 |
| panel ≥ 100 | 481 | 6.5% | 39.9%±2.8 | -0.91±0.13 |


**Okuma.** (1) Mevcut panel skoru hiçbir katlamada en iyi sıralayıcı değil: ML olasılığı (zaten bildirim başlığında "| ML %") DB'de 3/4 katlamada AUC 0,61–0,64 (panel 0,48–0,56) ama olasılık olarak aşırı güvenli (Brier becerisi −%22…−%57). (2) 3 özellikli "LR ATR+hedef geometrisi" AUC 0,55–0,66 ile tam modele (LR 0,55–0,66; HGB 0,54–0,67) neredeyse eşit: tam model ek +0,00…+0,02. Yani kazanç "hedef, ATR'ye göre ne kadar ulaşılabilir" bilgisinden; skorun kendisinden değil. (3) Net: modeller üst-%10 neti panel üst-%10'una göre DB'de genelde iyileştiriyor (≈ −0,03…+0,67; panelin üst %10'u zaten en kötü kesit) ama mutlak değer hep negatif (en iyi −0,36±0,12); replay'de işaret karışık (b0→b1'de LR tam −0,33). NET-REG / NET-E, isabet modelinden net'te daha iyi değil ve katlamalar arası tutarsız. (4) DB etiketi SL rejimine bağlı olduğundan B1→B2 / B1+B2→B3 katlamalarında eğitim–test etiket tanımı farklı (R tabloları bunu ayırır).

## 6. (d) Kalibrasyon / yeniden eşleme
Statik isotonic(skor→hit) (eğitim bloğu → test bloğu):
| katlama | eğitim hit | test hit | Brier sabit | Brier isotonic(skor) | Brier test-sabiti (kayma tanısı) | LogLoss sabit | LogLoss isotonic |
|---|---|---|---|---|---|---|---|
| B1→B2 | 35.7% | 36.8% | 0.2326 | 0.2324 | 0.2325 | 0.6580 | 0.6575 |
| B1+B2→B3 | 36.3% | 49.7% | 0.2682 | 0.2668 | 0.2500 | 0.7309 | 0.7281 |
| R1a→R1b | 35.6% | 29.4% | 0.2116 | 0.2118 | 0.2077 | 0.6146 | 0.6152 |
| R2a→R2b | 53.1% | 45.8% | 0.2536 | 0.2512 | 0.2482 | 0.7004 | 0.6957 |

| katlama | eğitim hit | test hit | Brier sabit | Brier isotonic(skor) | Brier test-sabiti (kayma tanısı) | LogLoss sabit | LogLoss isotonic |
|---|---|---|---|---|---|---|---|
| b0→b1 | 25.2% | 21.3% | 0.1694 | 0.1649 | 0.1679 | 0.5227 | 0.5099 |
| b0+b1→b2 | 23.2% | 22.5% | 0.1743 | 0.1701 | 0.1743 | 0.5331 | 0.5214 |

Yürüyen isotonic (önceki 7/14 gün) — DB:
Yürüyen 7 günlük isotonic(panel→hit) vs aynı pencerenin sabit taban oranı: n=103627, Brier 0.2398 vs 0.2404 (beceri 0.3%, kazanç 0.0006±0.0003).

| tahmin ondalığı | n | ort. tahmin | gerçekleşen hit |
|---|---|---|---|
| 1 | 12078 | 29.8% | 36.7% |
| 2 | 10254 | 31.0% | 41.6% |
| 3 | 8751 | 32.9% | 27.2% |
| 4 | 9969 | 34.5% | 39.4% |
| 5 | 11382 | 35.6% | 36.9% |
| 6 | 9838 | 37.1% | 39.0% |
| 7 | 9180 | 38.3% | 38.2% |
| 8 | 11535 | 41.0% | 44.5% |
| 9 | 10259 | 45.7% | 48.7% |
| 10 | 10381 | 52.9% | 50.4% |

Replay:
Yürüyen 14 günlük isotonic(panel→hit) vs aynı pencerenin sabit taban oranı: n=12390, Brier 0.1656 vs 0.1690 (beceri 2.0%, kazanç 0.0034±0.0006).

| tahmin ondalığı | n | ort. tahmin | gerçekleşen hit |
|---|---|---|---|
| 1 | 1251 | 12.1% | 15.0% |
| 2 | 1203 | 16.6% | 16.8% |
| 3 | 1263 | 18.5% | 18.1% |
| 4 | 1243 | 19.6% | 20.1% |
| 5 | 1242 | 20.5% | 19.5% |
| 6 | 1256 | 21.6% | 19.3% |
| 7 | 1182 | 23.4% | 19.4% |
| 8 | 1268 | 25.3% | 22.9% |
| 9 | 1242 | 30.1% | 27.0% |
| 10 | 1240 | 40.6% | 36.3% |

Panel diliminin isabet karşılığı (rejime göre; "skor→olasılık" tablosu kullanılacaksa bu kadar rejime bağımlı):
| panel dilimi | R1 (SL1,5) hit | n | R2 (SL5) hit | n | Replay (touch) hit | n |
|---|---|---|---|---|---|---|
| <60 | 34.5%±1.3 | 23366 | 44.7%±3.1 | 8238 | 15.1%±0.6 | 3139 |
| 60–70 | 33.0%±1.2 | 12938 | 46.6%±1.7 | 9559 | 20.0%±0.6 | 5058 |
| 70–80 | 30.0%±1.2 | 10005 | 50.8%±0.9 | 10433 | 21.0%±0.7 | 5533 |
| 80–85 | 28.7%±1.5 | 3628 | 53.1%±1.6 | 4537 | 23.6%±1.0 | 2145 |
| 85–90 | 28.0%±1.4 | 2629 | 56.7%±1.6 | 3511 | 28.6%±1.2 | 1489 |
| 90–95 | 28.0%±1.9 | 1886 | 56.4%±2.6 | 2636 | 31.4%±1.6 | 953 |
| 95–99.9 | 27.1%±1.8 | 1286 | 58.9%±3.1 | 1930 | 35.7%±1.9 | 683 |
| =100 | 29.7%±2.8 | 2441 | 57.5%±2.3 | 3875 | 40.3%±1.5 | 1343 |

### 6.1 Önerilen olasılık eşlemesi (skor yerine, hedef/ATR geometrisi)
`p(hit) = σ( b0 + b1·ln(ATR%) + b2·ln(hedef%/ATR%) + b3·[ufuk ≥ 15 dk] )` — katsayılar çıkış rejimine (SL/TP) bağlıdır; HAFTALIK yeniden uydurulmalıdır.

Güncel çıkış rejimi (SL %5; DB R2a+R2b, 10-08..10-17):
| terim | katsayı (doğal birim) | SE (gün-küme) |
|---|---|---|
| sabit | +1.106 |  |
| ln(ATR%) | -0.675 | ±0.165 |
| ln(hedef%/ATR%) | -1.402 | ±0.126 |
| ufuk≥15dk | +0.059 | ±0.024 |

Örnek tablo (ATR% satır, hedef% sütun) — SL %5:
| ATR% / hedef% | 1,5 | 2 | 3 | 4 |
|---|---|---|---|---|
| 0.3 | 43% | 34% | 22% | 16% |
| 0.5 | 52% | 42% | 29% | 22% |
| 0.8 | 61% | 51% | 37% | 28% |
| 1.2 | 67% | 58% | 44% | 34% |
| 2 | 75% | 67% | 53% | 43% |
| 3 | 80% | 73% | 60% | 50% |

Önceki rejim (SL %1,5; DB R1):
| terim | katsayı (doğal birim) | SE (gün-küme) |
|---|---|---|
| sabit | +0.359 |  |
| ln(ATR%) | -0.906 | ±0.103 |
| ln(hedef%/ATR%) | -1.172 | ±0.124 |
| ufuk≥15dk | +0.027 | ±0.021 |

SL'siz dokunuş (replay 90 g):
| terim | katsayı (doğal birim) | SE (gün-küme) |
|---|---|---|
| sabit | +0.290 |  |
| ln(ATR%) | +0.343 | ±0.117 |
| ln(hedef%/ATR%) | -0.682 | ±0.130 |

| ATR% / hedef% | 1,5 | 2 | 3 | 4 |
|---|---|---|---|---|
| 0.3 | 23% | 20% | 16% | 13% |
| 0.5 | 33% | 29% | 24% | 20% |
| 0.8 | 45% | 40% | 33% | 29% |
| 1.2 | 55% | 50% | 43% | 38% |
| 2 | 67% | 63% | 56% | 51% |
| 3 | 76% | 72% | 66% | 62% |

### 6.2 Başabaş isabet (çıkış geometrisi)
| blok | alt küme | n | E[net|isabet] | E[net|ıska] | başabaş isabet | gözlenen isabet | fark |
|---|---|---|---|---|---|---|---|
| R1a | tümü | 25591 | +2.04 | -1.74 | 46.0% | 35.6% | -10.4 puan |
| R1a | panel ≥ 85 | 1741 | +2.86 | -1.84 | 39.1% | 32.2% | -6.9 puan |
| R1a | panel = 100 | 447 | +3.10 | -1.85 | 37.3% | 38.3% | +0.9 puan |
| R1b | tümü | 32588 | +2.23 | -1.64 | 42.3% | 29.4% | -12.9 puan |
| R1b | panel ≥ 85 | 6501 | +2.79 | -1.76 | 38.7% | 27.3% | -11.4 puan |
| R1b | panel = 100 | 1994 | +2.94 | -1.82 | 38.2% | 27.7% | -10.5 puan |
| R2a | tümü | 30065 | +1.41 | -2.73 | 65.9% | 53.1% | -12.7 puan |
| R2a | panel ≥ 85 | 8198 | +1.55 | -3.88 | 71.5% | 59.7% | -11.7 puan |
| R2a | panel = 100 | 2789 | +1.67 | -4.61 | 73.4% | 60.2% | -13.3 puan |
| R2b | tümü | 14654 | +1.48 | -2.35 | 61.4% | 45.8% | -15.6 puan |
| R2b | panel ≥ 85 | 3754 | +1.59 | -3.55 | 69.0% | 51.8% | -17.2 puan |
| R2b | panel = 100 | 1086 | +1.73 | -4.43 | 71.9% | 50.6% | -21.4 puan |

| blok | alt küme | n | E[net|isabet] | E[net|ıska] | başabaş isabet | gözlenen isabet | fark |
|---|---|---|---|---|---|---|---|
| b0 | tümü | 6110 | +2.54 | -1.57 | 38.2% | 25.2% | -12.9 puan |
| b0 | panel ≥ 85 | 1467 | +2.31 | -2.38 | 50.8% | 36.3% | -14.5 puan |
| b0 | panel = 100 | 475 | +1.89 | -2.90 | 60.6% | 41.7% | -18.9 puan |
| b1 | tümü | 6797 | +2.80 | -1.40 | 33.4% | 21.3% | -12.0 puan |
| b1 | panel ≥ 85 | 1335 | +2.87 | -2.03 | 41.4% | 32.5% | -8.9 puan |
| b1 | panel = 100 | 387 | +2.60 | -2.50 | 49.0% | 39.0% | -10.0 puan |
| b2 | tümü | 7436 | +2.62 | -1.55 | 37.2% | 22.5% | -14.7 puan |
| b2 | panel ≥ 85 | 1666 | +2.46 | -2.24 | 47.7% | 32.7% | -15.1 puan |
| b2 | panel = 100 | 481 | +1.82 | -2.72 | 59.9% | 39.9% | -20.0 puan |

## 7. Bildirimler (monitoring_notifications, sonuçlu 765 satır)
score=74.0 ∧ message='radar' ∧ mod boş satır sayısı: 56 (sembol: BTCTRY, ETHTRY; aynı dakikada 4'lü yinelenen satırlar) — gerçek sinyal DEĞİL, '70 kovası %0' bulgusunun kaynağı bu duman/test satırlarıdır.

Sınıfa göre (test satırları ayrı) — hedefe ulaştı = `HEDEFE_ULTI`:
| sınıf | panel dilimi | n | hedefe ulaştı | hit | Wilson %95 | ort. MFE% | ort. hedef% |
|---|---|---|---|---|---|---|---|
| velocity-tek (trend_devam) | 85–90 | 137 | 22 | 16.1% | 11–23% | 1.18 | 3.01 |
| velocity-tek (trend_devam) | 90–95 | 78 | 15 | 19.2% | 12–29% | 1.54 | 3.01 |
| velocity-tek (trend_devam) | 95–99.9 | 65 | 16 | 24.6% | 16–36% | 1.45 | 2.97 |
| velocity-tek (trend_devam) | =100 | 140 | 64 | 45.7% | 38–54% | 2.06 | 2.80 |
| notr | 85–90 | 55 | 9 | 16.4% | 9–28% | 1.21 | 2.92 |
| notr | 90–95 | 25 | 10 | 40.0% | 23–59% | 1.70 | 2.68 |
| notr | 95–99.9 | 33 | 4 | 12.1% | 5–27% | 1.12 | 2.69 |
| notr | =100 | 48 | 14 | 29.2% | 18–43% | 1.40 | 2.60 |
| unified (füzyon) | 85–90 | 30 | 0 | 0.0% | -0–11% | 0.73 | 4.00 |
| unified (füzyon) | 90–95 | 38 | 3 | 7.9% | 3–21% | 0.90 | 4.00 |
| unified (füzyon) | 95–99.9 | 49 | 2 | 4.1% | 1–14% | 0.93 | 4.00 |
| unified (füzyon) | =100 | 9 | 0 | 0.0% | 0–30% | 0.70 | 4.00 |
| TEST/duman satırı (message='radar') | <80 | 56 | 0 | 0.0% | 0–6% | 0.02 | 2.00 |

Test hariç hepsi birlikte:
| panel dilimi | n | hit | Wilson %95 |
|---|---|---|---|
| 85–90 | 224 | 14.3% | 10–19% |
| 90–95 | 141 | 19.9% | 14–27% |
| 95–99.9 | 147 | 15.0% | 10–22% |
| =100 | 197 | 39.6% | 33–47% |

"100" ne yapıyor? (journal'a eşleşen satırlar):
| grup | n | medyan ham skor | medyan ATR% | medyan ret3% | medyan hedef% | journal hit (TP-önce-SL) |
|---|---|---|---|---|---|---|
| =100 (ham ≥ 25000) | 180 | 57707 | 1.53 | 0.43 | 2.46 | 53.9% |
| 85–99.9 | 434 | 7649 | 0.74 | 0.36 | 2.97 | 25.9% |

AUC (panel→HEDEFE_ULTI, test hariç): tüm n=709: 0,637; trend_devam n=420: 0,666; notr n=161: 0,555; **unified n=126: 0,474 (şans)**. ATR ile karşılaştırma (journal'a eşleşen velocity-tek/notr, n=486): AUC(panel)=0,633, AUC(ATR)=0,617, ATR-tersil-strata AUC(panel)=0,574 → panelin ek katkısı küçük.

**Bimodalite özeti:** (a) 74,0 kovası test/duman; (b) unified 85–99,9: 117 satır, %0–8; (c) trend_devam/velocity-tek tek yönlü ve dışbükey (16→19→25→46); (d) panel=100 = ham ≥25 000 kırpma kovası, ATR medyanı 2×; (e) Wilson %95 aralıkları 85–99,9 kovalarında örtüşüyor (%14,3 [10–19] / %19,9 [14–27] / %15,0 [10–22]) → 90–95 ile 95–99,9 arasındaki sıra farkı anlamlı değil.

## 8. Birleşik tarama puanı (`unified_candidate_outcomes.scan_score`) — zayıf kanıt
n=14004, gün=3, taban hit=1.6%, AUC(scan_score→hit)=0.785±0.068 (kaynak-sayısı-strata AUC 0.781±0.088). (Yalnız 3 gün, hit = tavana (ceiling) ulaşma, taban %1,6; ikili kaynak satırlarında %0,4 hit — kaynak sayısı bonusunun (+8/kaynak) tersine.)

| ondalık | n | min | max | hit±SE |
|---|---|---|---|---|
| 1 | 985 | 29.8 | 42.2 | 0.3%±0.2 |
| 2 | 2536 | 42.3 | 42.4 | 0.0%±0.0 |
| 3 | 514 | 42.5 | 42.5 | 0.0%±0.0 |
| 4 | 1567 | 42.6 | 45.7 | 0.4%±0.3 |
| 5 | 1468 | 45.8 | 46.4 | 0.4%±0.3 |
| 6 | 1437 | 46.5 | 49.7 | 0.8%±0.0 |
| 7 | 1258 | 49.8 | 57.6 | 3.0%±1.1 |
| 8 | 1411 | 57.7 | 63.3 | 2.3%±0.6 |
| 9 | 1427 | 63.4 | 71.1 | 3.0%±0.7 |
| 10 | 1401 | 71.2 | 99.0 | 5.9%±0.4 |

| kaynak sayısı | n | hit±SE | ort. scan_score |
|---|---|---|---|
| 1 | 1726 | 5.4%±0.4 | 55.4 |
| 2 | 9274 | 0.4%±0.4 | 46.8 |
| 3 | 1241 | 3.7%±0.5 | 70.9 |
| 4 | 1519 | 2.6%±0.5 | 65.4 |
| 5 | 228 | 1.8%±0.1 | 70.6 |

## 9. Öneri
**KEEP / RE-MAP / REPLACE:**

1. **Ham `velocity_score` ve panel haritası: KORU (sıralama anahtarı olarak), ama "kalite" diye SUNMA.** Net'e göre onu geçen sağlam bir model yok; AUC'u zaten ATR'den ibaret. Panel=100 kırpmasını açmak (ör. REF↑) AUC'ye bir şey katmaz.
2. **Bildirimde gösterim: "Skor 97" yerine iki ayrı alan.** (i) `Hız/şiddet` = mevcut panel (etiketi "hareket şiddeti"; 85/95 eşikleri "iyi sinyal" anlamı taşımaz), (ii) `Tahmini isabet %` = §6.1 lojistik (ATR, hedef/ATR, ufuk), hafta başı yeniden uydurulmuş, ya da mevcut `ml_hit_probability`'nin yürüyen isotonic/Platt ile kalibre hâli (ham ML olasılığı AUC iyi ama aşırı güvenli). Yanına "başabaş isabet %" (§6.2: SL %5'te ≈%61–73) eklenirse kullanıcı hit%'in neden kâr anlamına gelmediğini görür.
3. **Skor tabanlarını (≥85 tek kaynak, ≥95 unified) kalite filtresi saymayın:** SL %5'te isabeti +6–7 puan artırır, başabaş isabet de +6–8 puan artar; net eşit/kötü (SL %1,5'te isabet bile düşer). `unified` (füzyon) için: sonuçlu 126 satırda %4 isabet, AUC 0,47 → bildirimden tamamen çıkarmak ölçümle desteklenir (≥95 tabanı n=58'de 2 isabet).
4. **Skorun içinde düzeltilecekler (veriyle desteklenen):** geç-faz cezası yön olarak yanlış (hit +15 puan); öncü-ATR bonusu net'i düşürüyor; hacim/momentum terimlerinin ATR-dışı katkısı yok; CVD işareti (+5,8 puan / +0,29 net, 4/4 blok) skor ya da olasılık modeli girdisi adayı — look-ahead kontrolü sonrası.
5. **Veri hijyeni (modeli sınırlayan asıl şey):** `velocity.py:1371` `volume_ratio: 0.0` sabiti; journal'a `mode`, `taker_buy_ratio`, `book_imbalance`, `bb_width_pct`, `volume_ratio`, `m1/m3_atr_prev` yazılmalı (17 Eki'den önce yok); çıkış rejimi (SL/TP maliyeti) her satıra damgalanmalı — rejim değişince etiketler karşılaştırılamıyor.
6. **Yapısal not:** net negatifliğin kaynağı skor değil çıkış geometrisi: SL %5'te başabaş isabet %61–73, gözlenen %46–60; SL %1,5'te %37–46 vs %27–38. Skor sıralaması bunu kapatmıyor.

**Sınırlamalar:** her blokta 5–10 gün (küme sayısı küçük, SE'ler iyimser olabilir); DB etiketi SL rejimine bağlı; replay özellikleri (taker, mod) DB'de eski günler için yok; HGB ayar yapılmadı; bildirimler n=709 ve seçilmiş (eşik üstü) bir örneklem; unified çıktıları 3 gün.
