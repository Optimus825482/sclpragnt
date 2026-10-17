# Bildirim hedefi (target_pct) denetimi: üretim zinciri, kalibrasyon, net ve öneri

Üretim: `backend/scripts/target_audit.py` (çevrimdışı, DB'ye yazmaz, canlı koda bağlanmaz). Son 1 dk mum: 17.10.2026 20:19 (TRT); olay kesiti: 17.10.2026 19:09. Veri: 11054 Hız Avcısı adayı (passes, rank≤10, (sembol,ufuk) başına 60 dk soğuma), 3483 bildirim satırı (mode dolu; sonucu ölçülmüş: 709), 14004 birleşik journal satırı. Bloklar: B1 09-17..10-01 | B2 10-02..10-09 | B3 10-10..10-17 (TRT). Önceki çalışmalar: docs/BILDIRIM_POLITIKASI_7G_2026-10-17.md, app/rescan/dyn_target.py, exit_sim.py.

## 0. Karar

**Kısa cevap.** Gösterilen hedef, *ulaşılabilirlik beyanı* olarak sistematik şişkindir ve oynaklığa/ufka kördür; ama hedefi değiştirmek bildirimleri **kârlı yapmaz** — hiçbir kural test
bloğunda net pozitif değil; en iyi kural bile mevcuttan en fazla +0.02 … +0.07 puan farklı ve bu fark çoğunlukla sıfırdan ayırt edilemiyor.

* **(a) Kalibrasyon.** Hız Avcısı adaylarında (n=11054, canlıya benzer) medyan MFE(ufuk) 0.58 % iken medyan hedef 2.06 % (hedef ≈ 3.5 x medyan MFE;
  p75 MFE 1.35 % bile hedefin altında). P(MFE ≥ hedef) = %14.7 (5 dk %7.8, 15 dk %23.8; 60 dk içinde %41.6). Hedef ufka (medyan 5 dk 1.93 / 15 dk 2.10 / 60 dk 2.11)
  ve oynaklığa kördür: ATR üçlülerinde isabet %5 → %26; gösterilen hedefin MFE ile Spearman ρ'su +0.15 (B3'te +0.03), ATR·√(ufuk/5)'in +0.44.
  Gönderilen bildirimlerde (uygulamanın kendi sonucu): sabit 4,0 hedefi %4.6 (n=195), 2,5 hedefi %16.4 (n=73); %46 görünen 2,1-2,4 grubu (n=153) 'iyi kalibrasyon' değil,
  tamamı ML-karışımlı (prob>=0,65) ve yüksek skorlu (ort. 96) satırlardır: düşük hedef + yüksek skor etkisi (c6). Yapı: 5. adım öğrenilmiş sembol hedefi sembollerin %89'unda 1,5'a yapışık ve ağırlık 0,6 ⇒ gösterilen ≈ 0,4·X + 0,9
  (X = kademe/taban); 'net %2 güvencesi' (net-kâr tabanı) tutmuyor (V hedeflerinin %74'i en düşük taban olan 2,275'in altında).
* **(b) Net.** Gerçekçi dolumla (giriş taker+kayma, TP maker, SL %3) bütün hücreler −0,50…−0,63: mevcut k=1 → -0.54 ±0.04 (zaman=ufuk), -0.56 ±0.07 (zaman=60 dk). k=0,4…1,5, sabit %0,75…3, ATR-k,
  MFE yüzdeliği, havuz-MFE hepsi aynı bantta. Önceki blokta seçilen en iyi kural sonraki blokta mevcuttan yalnız +0.02 … +0.07 farklı (eşleştirilmiş; 6 protokolün 1'sında %95 aralığı sıfırı dışlıyor). Neden: giriş sinyalinin
  yönsüz olması (serbest ufuk sürüklenmesi -0.05 ±0.05) ve maliyet; TP-dışı çıkışlar ort. −1.98, başabaş TP isabeti %54 iken gerçekleşen %39. Küçük hedef yalnız isabeti şişirir
  (k=0,4 → zaman=60'ta %65 TP isabeti), neti değiştirmez.
* **(c) ML ve kalibrasyon.** ML karışımı hedefi ort. 2.28 → 1.64 çeker ve isabeti %12 → %23 yapar; net farkı küçük (+0.03 ±0.03 ufuk / +0.13 ±0.07 60 dk; 60 dk sınırda anlamlı ve ML bilgisinden değil hedefin düşmesinden: TP=ml_target ile net de −0,45).
  ml_target_pct MFE ile ρ=+0.27 (ATR ρ=+0.43); ml_hit_probability AUC=0.64. `target_calibration` açılsa bile emülasyon p50 değerlerinin %99'i net-kâr tabanının altında
  ⇒ 3. adım hedefi tabana geri alır (bayrak fiilen yalnız kademe uçlarını siler); birleşik (fusion) yol ufuk geçmediği için hiç etkilenmez. Kalibre p50'nin TP olarak neti mevcuttan +0,03…+0,05 daha iyi, aralıklar sıfırı kapsıyor (c4).
* **(d) Öneri.** Hedefi kâr vaadi olarak değil, **ölçülmüş ulaşılabilirlik** olarak tanımla: aşağıdaki nicel-regresyon formülü (yalnız sinyal anı bilgisi: üretimdeki `atr_pct` = M1 ATR14 %, ufuk, panel skor) OOS'ta isabeti
  oynaklık/ufuk/skor dilimlerinde tekdüze yapar (B3 ATR üçlülerinde nominal %50 formülü %33–%45, mevcut hedef %5–%31); net mevcutla aynı (fark ≈ 0). Bildirimde **net hedef = brüt −
  0,33** (maker TP) ve hücrenin geçmiş isabeti gösterilsin; net pozitiflik iddia edilmesin. Birleşik yoldaki sabit 4,0 (%4 isabet) ve `ceiling_pct` (%0,1) bu formülle değiştirilmeye en çok değer olan iki yerdir.


**Özet tablo** (B3 = 10-10..10-17, test bloğu; ± %95 gün-kümeli; net = işlem başına yüzde puan; maliyet: TP %0,33, SL/zaman %0,525; SL %3; hedef kuralları önceki bloklardan türetilmiş):

| hedef kuralı (B3, test bloğu) | n | ort. hedef | MFE>=hedef (ufuk) | TP isabeti (zaman=ufuk) | net (zaman=ufuk) | TP isabeti (zaman=60) | net (zaman=60) |
|---|---|---|---|---|---|---|---|
| **mevcut hedef (k=1)** | 4034 | 1.85 | 16.2% ±1.8 | 15.6% ±1.7 | -0.52 ±0.10 | 39.4% ±5.5 | -0.53 ±0.14 |
| k=0,5 x hedef | 4034 | 0.93 | 35.0% ±1.5 | 33.6% ±1.2 | -0.51 ±0.06 | 59.4% ±4.6 | -0.51 ±0.10 |
| sabit %0,75 | 4034 | 0.75 | 40.1% ±2.6 | 38.9% ±2.2 | -0.51 ±0.04 | 64.3% ±2.9 | -0.51 ±0.07 |
| sabit %1,5 | 4034 | 1.50 | 20.6% ±3.3 | 19.7% ±2.6 | -0.52 ±0.07 | 46.0% ±4.3 | -0.52 ±0.12 |
| sabit %2,0 | 4034 | 2.00 | 14.2% ±2.3 | 13.5% ±2.2 | -0.52 ±0.08 | 36.5% ±3.9 | -0.53 ±0.13 |
| ATR k=0,75 | 4034 | 1.24 | 32.3% ±2.2 | 31.7% ±2.0 | -0.52 ±0.07 | 59.1% ±6.2 | -0.50 ±0.09 |
| ATR k=1,5 | 4034 | 2.48 | 13.0% ±2.4 | 12.8% ±2.8 | -0.54 ±0.09 | 38.9% ±7.5 | -0.55 ±0.11 |
| sembol 60 dk MFE q50 (dyn_target c) | 3971 | 0.57 | 49.4% ±2.0 | 46.7% ±1.9 | -0.50 ±0.05 | 70.9% ±3.0 | -0.50 ±0.08 |
| havuz MFE p50 (target_calibration emülasyonu) | 4034 | 0.84 | 37.9% ±1.6 | 37.2% ±2.0 | -0.51 ±0.06 | 62.9% ±5.7 | -0.50 ±0.09 |
| formül (ATR·ufuk·skor, nominal %50; B1+B2'de kurulu) | 4034 | 0.90 | 39.4% ±2.4 | 39.5% ±2.4 | -0.51 ±0.08 | 64.8% ±6.5 | -0.50 ±0.10 |
| formül (ATR·ufuk·skor, nominal %30; B1+B2'de kurulu) | 4034 | 1.45 | 24.4% ±2.4 | 24.1% ±2.7 | -0.54 ±0.09 | 52.6% ±8.0 | -0.54 ±0.13 |

**Veri uyarısı (ön ölçümle fark):** `monitoring_notifications`'ta 10-17 15:38'den itibaren `mode` NULL, `horizon_minutes` NULL, sembolü BTCTRY/ETHTRY, hedefi 2,0, MFE'si ≈ 0,02 olan test kirliliği satırları var (56 satırın sonucu 'doldu'). 'Hedef 2,0 → %17 (n=88)' ön ölçümü bu satırlar yüzünden aşağı çekilmiş; burada `mode IS NOT NULL` süzülür (hedef 2,0 → n=5, uygulama isabeti ≈ %40). Aynı tarihte `velocity_candidates`'ta da hedefi 1,5-2,3 olan 60 dk adayları artıyor (10-17 14:00 sonrası).

## 1. Kod zinciri

Bildirimde görünen `target_pct` = `velocity.dynamic_target_pct(...)` çıktısıdır (velocity.py:2621-2688); bildirim `expected_price = fiyat x (1 + hedef/100)`
(monitoring.py:1521) ve mesajda `Potansiyel: +%{hedef}` (monitoring.py:1546) olarak gösterir. Zincir (sıra önemlidir; her adım bir öncekinin ÇIKTISINA uygulanır):

| # | adım | formül / bayrak | yer |
|---|---|---|---|
| 0 | profil tabanı | 5 dk 2,0; 15 dk 3,0; 30 dk 1,0; 60 dk 1,5 (`VELOCITY_PROFILES`) | velocity.py:276-287, kullanım :502-503 |
| 1 | skor kademesi | panel skor = 100·ln(1+ham)/ln(25001); `MONITORING_TARGET_SCORE_TIERS` = 74,0→4,0 ; 71,5→2,5 ; 68,2→2,0; `hedef = max(taban, en yüksek geçilen kademe)` | velocity.py:303-330, 2504-2530, 2641-2649; config.py:425-426 |
| 2 | ölçülmüş MFE kalibrasyonu (BAYRAKLI, varsayılan KAPALI) | `RADAR_TARGET_CALIBRATION_ENABLED=0`; açıksa `hedef = klamp(p50 MFE(ufuk), 0,6…4,5)` (son 14 gün, `unified_candidate_outcomes`, TTL 600 sn); kapalı/boş/ufuk=0 → değişmez | target_calibration.py:24-27, 54-83; velocity.py:2654; database.py:8333; main.py:1273,1316 |
| 3 | net-kâr tabanı | `taban = SCALPING_NET_TARGET_PCT (2,0) + gidiş-dönüş maliyet (0,275) + spread (bilinmiyorsa DEFAULT_ESTIMATED_SPREAD_PCT 0,65)` ≈ 2,3…2,9; `hedef = max(hedef, taban)` | velocity.py:2657-2661; config.py:859-860 |
| 4 | ATR potansiyeli | `hedef = max(hedef, 1,35·ATR%)` | velocity.py:2664-2666 |
| 5 | öğrenilmiş sembol hedefi | `w = min(0,6; sayı/20)`; `hedef = hedef·(1−w) + öğrenilmiş·w` (sayı ≥ 3). Öğrenilmiş = `symbol_target_state.target_pct`, 0,8·MFE EMA'sı, [1,5; 6,0] kelepçeli | velocity.py:2669-2672; database.py:6858-6883, 6886-6935 |
| 6 | ML karışımı | `ml_prob ≥ 0,65` ise `w = 0,25` (`≥ 0,80` ise 0,5); `hedef = hedef·(1−w) + ml_target_pct·w`. `ml_target_pct` = regresör çıktısı: ufuk sonu kapanışından çıkışın `ML_TARGET_QUANTILE`=0,65 yüzdeliği (MFE DEĞİL) | velocity.py:2675-2678, 987-1008; ml_forecast.py:698-760; config.py:216-220 |
| 7 | zayıf skor kelepçesi | `min(hedef, max(0,3·skor, 0,75·taban))` (panel skorlarda fiilen etkisiz); `panel_score=False` (rising) dalında `max(hedef, taban)` | velocity.py:2681-2684 |
| 8 | sınır | `[MONITORING_TARGET_PCT_MIN=1,5 ; MAX=6,0]`, 3 ondalık | velocity.py:2686-2688; config.py:434-435 |
| 9 | gerçekçilik sınırı | MACD güçlü değil ve `ml_prob < 0,5` ise `min(hedef, 3,0)` (`VELOCITY_TARGET_REALISM_*`, açık) | velocity.py:1129-1133; config.py:668-670 |
| 10 | aday/bildirim | `effective_target` → adayın `target_pct`'i (:1232) ve `ml_target_pct`'i (:1233); spread kapısı `spread > 0,35·hedef` ise aday elenir; bildirim zarfı `target_pct`, `expected_price`, `ml_target_pct`, `rr` | velocity.py:1047-1056, 1078, 1232-1233; monitoring.py:1488-1585, 1820-1887 |

Diğer yollar:

* **Yükseliş (rising) sinyali**: `dynamic_target_pct(skor, RISING_TARGET_PCT=2,2, learned, panel_score=False)`; ATR/ML/ufuk geçmez (monitoring.py:3058-3080; config.py:771).
* **Birleşik (fusion) yol**: `unified_signals.py:361-367, 464-470` `dynamic_target_pct(skor=füzyon skoru, taban=2,2, panel_score=True)` çağırır; öğrenilmiş/ML/ATR/ufuk
  GEÇMEZ → skor ≥ 74 ise kademe (**4,0**), değilse taban (~2,9). Hız adayıyla eşleşirse adayın hedefi aynen devralınır (unified_signals.py:461-462). Bu yüzden
  `unified` modunda hedef 4,0 (n=651/1111) ya da 1,5 (hız adayından, ML-kelepçeli; n=371).
* **Birleşik tarama `ceiling_pct`** (liste/rapor 'tavan', bildirim hedefi DEĞİL): `max(calculate_adaptive_targets(70, ATR, 3,0).tp2_runner, 3·ATR)`; skor sabiti 70
  olduğundan pratikte 3,0 ya da 4,4 sabitidir (unified_scan.py:462-470, 525; master_surge.py:383-436). Ölçüm: P(MFE ≥ tavan) ≈ %0,1 (tablo a7).
* **Kapalı modlar**: `notr`, `v_donusu`, `llm_ikinci_goz` varsayılan olarak bildirilmez (`RADAR_NOTIFY_DISABLED_MODES`, config.py:574); canlı modlar `trend_devam` ve `unified`.

**Zincirin davranışsal sonucu (ölçümle bağlı):** 5. adımdaki öğrenilmiş sembol hedefi, sembollerin %89'unda tabana (1,5) yapışıktır ve %97'sinde ağırlık tavanındadır (0,6). Sonuç
`gösterilen ≈ 0,4·X + 0,9` (X = 0-4. adımların çıktısı): tavan kademesi X=4,0 → **2,5**; net-kâr tabanı X≈2,9–3,0 → **~2,1**; kademe 2,5 → **~1,9**; ML karışımı → **1,5-2,3**. Yani (i) 4. ve
3. adımlar ve olası kalibrasyon, 5. adımda ×0,4'e sıkıştırılır; (ii) 'net %2 + maliyet' güvencesi (3. adım) pratikte tutmaz — V satırlarının medyan hedefi 2,06 < taban (~2,3–2,9);
(iii) hedef ufka kördür (medyan 5 dk 1,93 / 15 dk 2,10 / 60 dk 2,11) ve ATR'ye zayıf bağlıdır; (iv) sabit 4,0 yalnızca öğrenme/ML karışımı uygulanmayan fusion yolundan çıkar.


## 2. Yöntem

* **Olay kümesi V**: `velocity_candidates` (candidate_id `vel-*`; rescan/uni/backfill dışarıda), `passes AND rank<=10`, 17.09 → kesit; aynı (sembol, ufuk) için 60 dk soğuma. Bildirim kapısının (skor eşiği, kaynak teyidi, mod süzgeci) tamamı değil, 'canlıya benzer' bir üst kümedir; bildirimlerle ayrıca karşılaştırılır (a6, a10).
* **MFE** (yeniden hesaplandı; DB `mfe_pct` TP/SL anında kesildiği için kullanılmadı): ilk tam 1 dk bar sinyalden sonra açılır, referans = o barın açılışı; MFE(ufuk) = ufuk dakikası içinde en yüksek high; MFE60 = 60 dk içinde.
* **Net simülasyonu** (`app/rescan/exit_sim.py`): giriş = sinyal + 60 sn sonraki ilk 1 dk barın açılışı x 1,0015; TP = bildirimdeki fiyat (sinyale göre), dolan girişe göre (1+T)/1,0015−1; bekleyen LIMIT maker %0,0675, kaymasız ⇒ TP çıkışında toplam maliyet %0,33; SL %3 ve zaman çıkışı taker %0,1125 + %0,15 kayma ⇒ %0,525; aynı barda SL+TP ⇒ SL. Zaman stopu iki seçenek: ufuk ve 60 dk.
* **İstatistik**: ± yarı genişlik = 1,96 x gün-kümeli SE (`exit_sim.cluster_se`); eşleştirilmiş farklar aynı satırlarda. Seçim yalnız önceki bloklarda yapıldı, sonraki blokta ölçüldü (B1→B2, B1→B3, B1+B2→B3). 62 strateji hücresi (2 zaman stopu dâhil) denendi: en iyi hücrelerin 'kazanan laneti' riski vardır; fark sütunları bunu zaten sıfıra yakın gösterir.
* **Sınırlar**: birleşik journal ve 30/60 dk ufuk yalnız son dönemde var (30/60 dk n=302/184, hepsi B3'te); hedef kovası tabloları 5/15 dk için güvenilir. Uygulamanın kendi 'Hedefe ulaştı' etiketi benim ölçümümden gevşektir (ör. trend_devam 2,0-2,4: uygulama %54 vs yeniden %41). Net ≠ kasa getirisi: işlem başına yüzde puan.

## 3. (a) Mevcut hedefin kalibrasyonu

### a1. Hız Avcısı adayları (passes, rank≤10, (sembol,ufuk) başına 60 dk soğuma): genel kalibrasyon

isabet(ufuk) = ufuk içinde en yüksek >= gösterilen hedef (referans: sinyal sonrası ilk tam 1 dk barın açılışı); isabet(60) = 60 dk içinde. ± = %95 (gün-kümeli SE). MFE yüzdelikleri ufuk içindir.

| küme | n | ort. hedef | medyan hedef | isabet(ufuk) | isabet(60 dk) | MFE(ufuk) p25/p50/p75 | medyan MFE / medyan hedef |
|---|---|---|---|---|---|---|---|
| tümü | 11054 | 2.08 | 2.06 | 14.7% ±1.5 | 41.6% ±2.8 | 0.18 / 0.58 / 1.35 | 0.28 |
| B1 09-17..10-01 | 3530 | 2.28 | 2.10 | 15.9% ±3.0 | 46.1% ±2.9 | 0.28 / 0.75 / 1.69 | 0.36 |
| B2 10-02..10-09 | 3490 | 2.14 | 2.08 | 11.9% ±2.3 | 37.5% ±4.1 | 0.12 / 0.48 / 1.14 | 0.23 |
| B3 10-10..10-17 | 4034 | 1.85 | 1.71 | 16.2% ±1.8 | 41.2% ±5.6 | 0.14 / 0.55 / 1.28 | 0.32 |

### a2. Ufuk bazında

| ufuk dk | n | medyan hedef | isabet(ufuk) | isabet B1 / B2 / B3 | MFE p25/p50/p75 | medyan MFE / medyan hedef |
|---|---|---|---|---|---|---|
| 5 | 6188 | 1.93 | 7.8% ±1.2 | 9.9% ±2.8 / 5.8% ±1.3 / 8.6% ±1.6 | 0.08 / 0.41 / 0.91 | 0.22 |
| 15 | 4380 | 2.10 | 23.8% ±2.9 | 21.9% ±3.6 / 28.0% ±6.2 / 23.3% ±4.6 | 0.33 / 0.91 / 2.00 | 0.43 |
| 30 | 302 | 2.10 | 14.9% ±1.0 | – / – / 14.9% ±1.0 | 0.30 / 0.84 / 1.71 | 0.40 |
| 60 | 184 | 2.11 | 32.1% ±0.3 | – / – / 32.1% ±0.3 | 0.63 / 1.50 / 3.10 | 0.71 |

### a3. Hedef kovası x ufuk (n≥20)

| hedef kovası | ufuk | n | ort. hedef | isabet(ufuk) | isabet B1 / B2 / B3 | MFE p25/p50/p75 |
|---|---|---|---|---|---|---|
| <2,0 | 5 | 3748 | 1.73 | 8.0% ±1.3 | 9% (n=835) / 6% (n=1388) / 9% (n=1525) | 0.07 / 0.37 / 0.81 |
| <2,0 | 15 | 1356 | 1.58 | 30.9% ±5.8 | 39% (n=18) / 44% (n=240) / 28% (n=1098) | 0.32 / 0.84 / 1.91 |
| 2,0–2,4 | 5 | 1094 | 2.14 | 6.4% ±1.7 | 8% (n=558) / 4% (n=324) / 7% (n=212) | 0.03 / 0.40 / 0.92 |
| 2,0–2,4 | 15 | 2154 | 2.16 | 18.5% ±2.5 | 19% (n=1268) / 23% (n=441) / 13% (n=445) | 0.29 / 0.83 / 1.74 |
| 2,5–2,9 | 5 | 1080 | 2.57 | 7.6% ±1.9 | 15% (n=239) / 6% (n=696) / 5% (n=145) | 0.14 / 0.53 / 1.13 |
| 2,5–2,9 | 15 | 585 | 2.61 | 23.2% ±4.2 | 27% (n=313) / 21% (n=175) / 18% (n=97) | 0.41 / 1.19 / 2.53 |
| 3,0–3,9 | 5 | 227 | 3.26 | 13.2% ±5.2 | 18% (n=112) / 10% (n=105) / 0% (n=10) | 0.35 / 0.92 / 2.12 |
| 3,0–3,9 | 15 | 244 | 3.29 | 31.6% ±6.4 | 36% (n=146) / 25% (n=91) / 29% (n=7) | 0.71 / 1.90 / 3.71 |
| ≥4,0 | 5 | 39 | 4.29 | 10.3% ±11.7 | 10% (n=20) / 13% (n=15) / 0% (n=4) | 0.59 / 1.31 / 2.62 |
| ≥4,0 | 15 | 41 | 4.23 | 24.4% ±10.8 | 29% (n=21) / 27% (n=15) / 0% (n=5) | 0.72 / 2.00 / 4.33 |

### a4. Panel skoru kovası (tüm ufuklar)

| skor (panel) | n | ort. hedef | isabet(ufuk) | MFE p25/p50/p75 | medyan MFE / medyan hedef |
|---|---|---|---|---|---|
| <68,2 | 6129 | 2.01 | 12.3% ±1.5 | 0.15 / 0.54 / 1.20 | 0.26 |
| 68,2–74 | 1457 | 1.94 | 13.8% ±3.1 | 0.14 / 0.49 / 1.19 | 0.26 |
| 74–80 | 1342 | 2.22 | 13.9% ±2.8 | 0.18 / 0.57 / 1.30 | 0.23 |
| 80–90 | 1252 | 2.21 | 19.3% ±3.4 | 0.28 / 0.75 / 1.71 | 0.30 |
| ≥90 | 874 | 2.37 | 28.1% ±4.4 | 0.42 / 1.15 / 2.57 | 0.50 |

### a5. Karşılaştırma: yeniden hesap vs DB `touched_target` (60 dk pencere, SL %5, belirsiz bar = stop)

| ölçüt | n | oran / değer |
|---|---|---|
| DB touched_target (60 dk) | 11052 | 36.9% ±2.7 |
| yeniden hesap isabet(60 dk) | 11052 | 41.6% ±2.8 |
| yeniden hesap isabet(ufuk) | 11052 | 14.7% ±1.5 |
| DB net_pct ortalaması (%) | 11052 | -0.43 ±0.06 |

### a6. Gönderilen bildirimler (monitoring_notifications, sonucu ölçülmüş; legacy global_lead_lag hariç)

uygulama isabeti = outcome_status=HEDEFE_ULTI; 'yeniden isabet' = 1 dk mumlardan ufuk içi MFE >= hedef. Toplam sonucu ölçülmüş: 709.

| mod | hedef kovası | n | ort. hedef | uygulama isabeti | yeniden isabet(ufuk) | uygulama MFE p25/p50/p75 |
|---|---|---|---|---|---|---|
| notr | 2,0–2,4 | 68 | 2.19 | 33.8% ±8.8 | 20.6% ±5.9 | 0.48 / 1.17 / 2.79 |
| notr | 2,5–2,9 | 38 | 2.60 | 21.1% ±15.6 | 15.8% ±10.8 | 0.00 / 0.55 / 1.96 |
| notr | 3,0–3,9 | 37 | 3.24 | 13.5% ±7.8 | 13.5% ±12.4 | 0.00 / 0.15 / 1.19 |
| notr | ≥4,0 | 18 | 4.10 | 5.6% ±5.9 | 0.0% ±0.0 | 0.00 / 0.41 / 0.97 |
| trend_devam | 2,0–2,4 | 117 | 2.17 | 53.8% ±7.1 | 41.0% ±6.5 | 0.26 / 2.26 / 2.82 |
| trend_devam | 2,5–2,9 | 136 | 2.64 | 23.5% ±6.9 | 16.2% ±6.3 | 0.00 / 0.77 / 2.23 |
| trend_devam | 3,0–3,9 | 81 | 3.29 | 17.3% ±9.6 | 13.6% ±6.4 | 0.00 / 0.51 / 2.39 |
| trend_devam | ≥4,0 | 86 | 4.10 | 9.3% ±8.0 | 4.7% ±4.7 | 0.06 / 0.69 / 1.58 |
| unified | ≥4,0 | 126 | 4.00 | 4.0% ±2.9 | 3.2% ±3.5 | 0.02 / 0.37 / 1.25 |

Sabit hedef değerleri (tüm modlar, sonucu olan bildirimler):

| hedef | n | uygulama isabeti | medyan MFE (uygulama) |
|---|---|---|---|
| 2.0 | 5 | 40.0% ±48.3 | 0.00 |
| 2.5 | 73 | 16.4% ±8.5 | 0.62 |
| 3.0 | 22 | 9.1% ±7.7 | 0.12 |
| 4.0 | 195 | 4.6% ±2.0 | 0.55 |
| 2,1–2,4 | 153 | 46.4% ±7.5 | 1.70 |

Not: 2,1–2,4 grubu 10-08..10-15 arasında yoğunlaşır (n=153, 10-08'de 34); hedef arttıkça isabetin tek yönlü düşmesi kısmen dönem ve skor karışımıdır (bkz. c6).

### a7. Birleşik tarama journal'ı (unified_candidate_outcomes, 10-14 sonrası; yalnız B3 ile örtüşür)

| target_pct kovası | n | ort. hedef | P(MFE>=target) | P(MFE>=tavan) | MFE p25/p50/p75 |
|---|---|---|---|---|---|
| <2,0 | 2798 | 1.61 | 24.3% | 5.6% | 0.18 / 0.66 / 1.55 |
| 2,0–2,4 | 1045 | 2.15 | 13.2% | 4.3% | 0.02 / 0.44 / 1.16 |
| 2,5–2,9 | 91 | 2.57 | 17.6% | 8.8% | 0.00 / 0.48 / 1.85 |
| 3,0–3,9 | 3249 | 3.24 | 0.2% | 0.1% | 0.00 / 0.00 / 0.13 |
| ≥4,0 | 5969 | 5.72 | 0.1% | 0.1% | 0.00 / 0.19 / 0.55 |

### a8. Gösterilen hedef değerlerinin yapısı

Hız Avcısı adayları (V): hedef değeri -> pay; ML karışımı (ml_prob>=0,65) payı; ort. skor; 'öğrenilmiş=1,5 / ağırlık 0,6' varsayımıyla ima edilen karışım-öncesi hedef X=(t-0,9)/0,4.

| gösterilen hedef | n | pay | ML karışımı payı | ort. panel skor | ima edilen X |
|---|---|---|---|---|---|
| 1.5 | 2377 | 21.5% | 100% | 72.3 | 1.50 |
| 1.9 | 1758 | 15.9% | 14% | 58.5 | 2.50 |
| 2.0 | 717 | 6.5% | 11% | 59.7 | 2.75 |
| 2.1 | 2107 | 19.1% | 3% | 55.0 | 3.00 |
| 2.2 | 468 | 4.2% | 11% | 59.6 | 3.25 |
| 2.5 | 1100 | 10.0% | 2% | 78.8 | 4.00 |
| 3.0 | 168 | 1.5% | 2% | 74.0 | 5.25 |
| 4.0 | 19 | 0.2% | 5% | 85.5 | 7.75 |

`symbol_target_state` (öğrenilmiş sembol hedefi): 310 sembol; hedefi tabana (%1,5) yapışık olan %89; toplam_sayı>=12 (ağırlık 0,6 tavanı) olan %97; medyan öğrenilmiş hedef 1.50.

Bildirim tablosunda mod başına en sık hedef değerleri (n):

| mod | n | en sık hedefler | medyan |
|---|---|---|---|
| llm_ikinci_goz | 258 | 4.0(124), 3.0(23), 2.5(22), 2.9(13), 2.2(9) | 3.91 |
| notr | 386 | 3.0(65), 2.5(48), 2.3(36), 2.2(34), 2.1(22) | 2.80 |
| trend_devam | 990 | 2.5(145), 4.0(117), 2.3(66), 3.0(61), 2.2(60) | 2.88 |
| unified | 1111 | 4.0(651), 1.5(371), 3.0(69), 2.0(17), 2.3(1) | 4.00 |
| v_donusu | 21 | 3.0(9), 2.1(3), 2.5(3), 2.4(3), 2.6(2) | 2.58 |

### a10. Moda göre net (bildirim tablosu satırları; legacy global_lead_lag hariç)

| mod | n | medyan hedef | isabet(ufuk) | MFE(ufuk) p25/p50/p75 | net k=0,5 (60) | net k=0,7 (60) | net k=1 (60) | net k=1 (ufuk) |
|---|---|---|---|---|---|---|---|---|
| llm_ikinci_goz | 258 | 3.91 | 4.3% ±2.9 | 0.10 / 0.39 / 0.93 | -0.76 ±0.19 | -0.78 ±0.25 | -0.84 ±0.25 | -0.62 ±0.09 |
| notr | 386 | 2.80 | 16.1% ±5.8 | 0.35 / 0.91 / 2.02 | -0.84 ±0.28 | -0.89 ±0.33 | -1.07 ±0.33 | -0.85 ±0.24 |
| trend_devam | 990 | 2.88 | 21.5% ±4.8 | 0.41 / 1.08 / 2.54 | -0.47 ±0.15 | -0.47 ±0.20 | -0.46 ±0.23 | -0.37 ±0.12 |
| unified | 1111 | 4.00 | 7.1% ±3.4 | 0.14 / 0.43 / 1.00 | -0.55 ±0.14 | -0.55 ±0.18 | -0.51 ±0.17 | -0.42 ±0.05 |


### a9. Hangi hedef bilgisi gerçekleşen MFE'yi sıralıyor? (V; Spearman ρ, tüm satırlar | blok başına)

| bilgi | ρ(tümü) | ρ B1 | ρ B2 | ρ B3 |
|---|---|---|---|---|
| gösterilen hedef (target_pct) | +0.151 | +0.262 | +0.124 | +0.025 |
| panel skoru | +0.110 | +0.229 | +0.091 | +0.179 |
| ATR14(5m) x sqrt(ufuk/5) | +0.391 | +0.318 | +0.389 | +0.402 |
| üretim atr_pct (M1 ATR14) x sqrt(ufuk/5) | +0.436 | +0.396 | +0.433 | +0.430 |
| sembol 60 dk MFE q50 (önceki 14 g) | +0.017 | -0.050 | -0.008 | +0.076 |
| sembol ufuk-MFE q60 (önceki 14 g) | +0.176 | +0.070 | +0.165 | +0.244 |
| ml_target_pct | +0.274 | +0.364 | +0.263 | +0.225 |
| ufuk (dk) | +0.291 | +0.228 | +0.347 | +0.298 |


### e3. Kalibrasyonun tekdüzeliği: ATR14(5m)·sqrt(ufuk/5) üçlüleri başına gerçekleşen isabet(ufuk)

İyi kalibre bir hedef, oynaklık ne olursa olsun benzer isabet vermeli. Üçlü eşikleri V satırlarının ATR·sqrt(h/5) dağılımından. Hücre: tümü / yalnız B3.

| hedef kuralı | düşük oynaklık (ATR üçlü 1) | orta | yüksek |
|---|---|---|---|
| gösterilen hedef | 5.1% / 5.4% (ort. hedef 1.98) | 13.1% / 14.3% (ort. hedef 2.03) | 26.0% / 31.2% (ort. hedef 2.23) |
| ATR·sqrt(h/5) x 0,75 | 39.8% / 39.2% (ort. hedef 0.45) | 33.4% / 32.5% (ort. hedef 0.98) | 23.6% / 23.8% (ort. hedef 2.49) |
| ATR·sqrt(h/5) x 1,5 | 20.1% / 18.8% (ort. hedef 0.89) | 13.8% / 11.9% (ort. hedef 1.96) | 7.3% / 7.2% (ort. hedef 4.98) |
| sembol ufuk-MFE q60 | 77.9% / 76.8% (ort. hedef 0.11) | 77.4% / 75.4% (ort. hedef 0.22) | 82.3% / 80.3% (ort. hedef 0.31) |
| havuz-MFE p50 (emülasyon) | 27.9% / 25.4% (ort. hedef 0.67) | 40.7% / 38.1% (ort. hedef 0.83) | 53.5% / 54.3% (ort. hedef 1.02) |



## 4. (b) Hedef çarpanı ve alternatiflerde gerçekçi net

Maliyet: giriş taker %0,1125 + %0,15 kayma; TP çıkışı maker %0,0675 (toplam %0,33); SL/zaman çıkışı taker + %0,15 kayma (toplam %0,525). SL %3. Net = işlem başına yüzde puan (kasa değil). n = 11054 (V, canlıya benzer).

### b1-H. Hedef çarpanı k x mevcut hedef (zaman stopu = ufuk)

| k | ort. TP% | TP isabeti | net (tümü) | net B1 | net B2 | net B3 | çıkış: TP / SL / zaman |
|---|---|---|---|---|---|---|---|
| 0.4 | 0.83 | 38.4% | -0.52 ±0.02 | -0.52 ±0.03 | -0.53 ±0.03 | -0.51 ±0.05 | 38% / 6% / 56% |
| 0.5 | 1.04 | 32.1% | -0.52 ±0.03 | -0.52 ±0.04 | -0.52 ±0.03 | -0.51 ±0.06 | 32% / 6% / 62% |
| 0.6 | 1.25 | 26.7% | -0.53 ±0.03 | -0.54 ±0.04 | -0.53 ±0.04 | -0.51 ±0.06 | 27% / 7% / 67% |
| 0.7 | 1.45 | 22.4% | -0.53 ±0.03 | -0.54 ±0.04 | -0.54 ±0.04 | -0.51 ±0.08 | 22% / 7% / 71% |
| 0.8 | 1.66 | 19.3% | -0.54 ±0.04 | -0.54 ±0.04 | -0.54 ±0.04 | -0.52 ±0.09 | 19% / 7% / 74% |
| 0.9 | 1.87 | 16.6% | -0.54 ±0.04 | -0.55 ±0.04 | -0.54 ±0.04 | -0.53 ±0.10 | 17% / 7% / 76% |
| 1 | 2.08 | 14.0% | -0.54 ±0.04 | -0.57 ±0.04 | -0.54 ±0.05 | -0.52 ±0.10 | 14% / 7% / 79% |
| 1.1 | 2.28 | 12.1% | -0.55 ±0.04 | -0.58 ±0.04 | -0.55 ±0.05 | -0.52 ±0.10 | 12% / 8% / 80% |
| 1.25 | 2.60 | 9.8% | -0.55 ±0.04 | -0.59 ±0.04 | -0.54 ±0.05 | -0.52 ±0.09 | 10% / 8% / 83% |
| 1.5 | 3.11 | 7.3% | -0.56 ±0.04 | -0.59 ±0.05 | -0.53 ±0.05 | -0.55 ±0.10 | 7% / 8% / 85% |

### b2-H. Alternatif hedef kuralları (zaman stopu = ufuk)

| kural | n | TP isabeti | net (tümü) | net B1 | net B2 | net B3 |
|---|---|---|---|---|---|---|
| sabit %0.75 (zaman=ufuk) | 11054 | 40.6% | -0.51 ±0.02 | -0.51 ±0.03 | -0.52 ±0.02 | -0.51 ±0.04 |
| sabit %1.5 (zaman=ufuk) | 11054 | 21.5% | -0.53 ±0.03 | -0.54 ±0.04 | -0.54 ±0.03 | -0.52 ±0.07 |
| sabit %1 (zaman=ufuk) | 11054 | 32.2% | -0.52 ±0.03 | -0.52 ±0.03 | -0.53 ±0.03 | -0.51 ±0.06 |
| sabit %2.5 (zaman=ufuk) | 11054 | 10.6% | -0.54 ±0.04 | -0.57 ±0.05 | -0.53 ±0.04 | -0.53 ±0.09 |
| sabit %2 (zaman=ufuk) | 11054 | 14.7% | -0.54 ±0.04 | -0.56 ±0.05 | -0.54 ±0.04 | -0.52 ±0.08 |
| sabit %3 (zaman=ufuk) | 11054 | 7.8% | -0.55 ±0.04 | -0.58 ±0.04 | -0.54 ±0.05 | -0.54 ±0.09 |
| ATR k=0.75 (zaman=ufuk) | 11054 | 31.1% | -0.53 ±0.03 | -0.56 ±0.04 | -0.52 ±0.04 | -0.52 ±0.07 |
| ATR k=1.5 (zaman=ufuk) | 11054 | 13.2% | -0.56 ±0.04 | -0.59 ±0.05 | -0.54 ±0.03 | -0.54 ±0.09 |
| ATR k=1 (zaman=ufuk) | 11054 | 22.7% | -0.55 ±0.03 | -0.58 ±0.05 | -0.53 ±0.04 | -0.53 ±0.08 |
| ATR k=2 (zaman=ufuk) | 11054 | 7.9% | -0.56 ±0.04 | -0.60 ±0.05 | -0.54 ±0.04 | -0.55 ±0.10 |
| ATR k=3 (zaman=ufuk) | 11054 | 3.6% | -0.57 ±0.04 | -0.60 ±0.05 | -0.56 ±0.04 | -0.56 ±0.11 |
| sembol 60dk-MFE q50 (zaman=ufuk) | 10897 | 46.4% | -0.50 ±0.02 | -0.49 ±0.04 | -0.51 ±0.03 | -0.50 ±0.05 |
| sembol 60dk-MFE q60 (zaman=ufuk) | 11012 | 38.6% | -0.52 ±0.02 | -0.52 ±0.04 | -0.52 ±0.03 | -0.51 ±0.04 |
| sembol 60dk-MFE q70 (zaman=ufuk) | 11045 | 30.8% | -0.52 ±0.03 | -0.52 ±0.05 | -0.53 ±0.03 | -0.51 ±0.06 |
| sembol ufuk-MFE q50 (zaman=ufuk) | 5964 | 47.5% | -0.52 ±0.04 | -0.53 ±0.05 | -0.51 ±0.04 | -0.53 ±0.08 |
| sembol ufuk-MFE q60 (zaman=ufuk) | 7725 | 49.7% | -0.51 ±0.03 | -0.52 ±0.05 | -0.50 ±0.04 | -0.50 ±0.07 |
| sembol ufuk-MFE q70 (zaman=ufuk) | 9265 | 52.9% | -0.51 ±0.03 | -0.52 ±0.05 | -0.49 ±0.02 | -0.51 ±0.06 |
| havuz-MFE p30 (zaman=ufuk) | 11054 | 46.1% | -0.51 ±0.02 | -0.51 ±0.03 | -0.50 ±0.02 | -0.51 ±0.04 |
| havuz-MFE p50 (zaman=ufuk) | 11054 | 39.0% | -0.52 ±0.03 | -0.52 ±0.02 | -0.52 ±0.03 | -0.51 ±0.06 |
| havuz-MFE p70 (zaman=ufuk) | 11054 | 24.5% | -0.53 ±0.03 | -0.54 ±0.03 | -0.53 ±0.03 | -0.52 ±0.08 |

### b1-60. Hedef çarpanı k x mevcut hedef (zaman stopu = 60 dk)

| k | ort. TP% | TP isabeti | net (tümü) | net B1 | net B2 | net B3 | çıkış: TP / SL / zaman |
|---|---|---|---|---|---|---|---|
| 0.4 | 0.83 | 65.3% | -0.51 ±0.04 | -0.48 ±0.06 | -0.56 ±0.05 | -0.50 ±0.08 | 65% / 17% / 18% |
| 0.5 | 1.04 | 59.8% | -0.51 ±0.05 | -0.48 ±0.07 | -0.55 ±0.06 | -0.51 ±0.10 | 60% / 18% / 22% |
| 0.6 | 1.25 | 54.6% | -0.53 ±0.05 | -0.51 ±0.08 | -0.58 ±0.07 | -0.51 ±0.11 | 55% / 20% / 25% |
| 0.7 | 1.45 | 50.1% | -0.54 ±0.06 | -0.50 ±0.06 | -0.61 ±0.07 | -0.51 ±0.12 | 50% / 22% / 28% |
| 0.8 | 1.66 | 46.2% | -0.54 ±0.06 | -0.49 ±0.07 | -0.60 ±0.08 | -0.52 ±0.14 | 46% / 23% / 31% |
| 0.9 | 1.87 | 42.4% | -0.54 ±0.06 | -0.50 ±0.07 | -0.60 ±0.08 | -0.52 ±0.14 | 42% / 24% / 34% |
| 1 | 2.08 | 38.8% | -0.56 ±0.07 | -0.54 ±0.07 | -0.61 ±0.10 | -0.53 ±0.14 | 39% / 25% / 36% |
| 1.1 | 2.28 | 36.0% | -0.57 ±0.07 | -0.57 ±0.07 | -0.63 ±0.10 | -0.52 ±0.14 | 36% / 26% / 38% |
| 1.25 | 2.60 | 32.0% | -0.58 ±0.06 | -0.59 ±0.07 | -0.63 ±0.11 | -0.53 ±0.13 | 32% / 27% / 41% |
| 1.5 | 3.11 | 26.4% | -0.59 ±0.06 | -0.60 ±0.08 | -0.60 ±0.11 | -0.58 ±0.13 | 26% / 28% / 46% |

### b2-60. Alternatif hedef kuralları (zaman stopu = 60 dk)

| kural | n | TP isabeti | net (tümü) | net B1 | net B2 | net B3 |
|---|---|---|---|---|---|---|
| sabit %0.75 (zaman=60 dk) | 11054 | 66.6% | -0.51 ±0.04 | -0.48 ±0.05 | -0.55 ±0.06 | -0.51 ±0.07 |
| sabit %1.5 (zaman=60 dk) | 11054 | 48.4% | -0.53 ±0.06 | -0.49 ±0.06 | -0.60 ±0.07 | -0.52 ±0.12 |
| sabit %1 (zaman=60 dk) | 11054 | 59.7% | -0.52 ±0.05 | -0.49 ±0.05 | -0.56 ±0.07 | -0.52 ±0.10 |
| sabit %2.5 (zaman=60 dk) | 11054 | 31.9% | -0.57 ±0.06 | -0.54 ±0.06 | -0.63 ±0.09 | -0.56 ±0.12 |
| sabit %2 (zaman=60 dk) | 11054 | 39.3% | -0.55 ±0.06 | -0.50 ±0.08 | -0.61 ±0.10 | -0.53 ±0.13 |
| sabit %3 (zaman=60 dk) | 11054 | 26.5% | -0.59 ±0.06 | -0.58 ±0.06 | -0.62 ±0.09 | -0.56 ±0.14 |
| ATR k=0.75 (zaman=60 dk) | 11054 | 59.8% | -0.53 ±0.04 | -0.53 ±0.05 | -0.56 ±0.07 | -0.50 ±0.09 |
| ATR k=1.5 (zaman=60 dk) | 11054 | 40.4% | -0.59 ±0.05 | -0.60 ±0.09 | -0.62 ±0.07 | -0.55 ±0.11 |
| ATR k=1 (zaman=60 dk) | 11054 | 52.2% | -0.56 ±0.05 | -0.56 ±0.07 | -0.59 ±0.07 | -0.53 ±0.09 |
| ATR k=2 (zaman=60 dk) | 11054 | 31.7% | -0.61 ±0.06 | -0.63 ±0.10 | -0.63 ±0.08 | -0.57 ±0.12 |
| ATR k=3 (zaman=60 dk) | 11054 | 20.5% | -0.63 ±0.07 | -0.65 ±0.11 | -0.69 ±0.07 | -0.57 ±0.14 |
| sembol 60dk-MFE q50 (zaman=60 dk) | 10897 | 70.8% | -0.51 ±0.04 | -0.50 ±0.07 | -0.53 ±0.05 | -0.50 ±0.08 |
| sembol 60dk-MFE q60 (zaman=60 dk) | 11012 | 65.2% | -0.52 ±0.04 | -0.50 ±0.06 | -0.54 ±0.05 | -0.51 ±0.07 |
| sembol 60dk-MFE q70 (zaman=60 dk) | 11045 | 57.7% | -0.53 ±0.05 | -0.50 ±0.07 | -0.57 ±0.06 | -0.53 ±0.09 |
| sembol ufuk-MFE q50 (zaman=60 dk) | 5964 | 55.2% | -0.56 ±0.06 | -0.56 ±0.07 | -0.65 ±0.11 | -0.50 ±0.10 |
| sembol ufuk-MFE q60 (zaman=60 dk) | 7725 | 60.4% | -0.53 ±0.05 | -0.49 ±0.07 | -0.60 ±0.09 | -0.52 ±0.07 |
| sembol ufuk-MFE q70 (zaman=60 dk) | 9265 | 68.8% | -0.51 ±0.04 | -0.51 ±0.07 | -0.52 ±0.05 | -0.51 ±0.07 |
| havuz-MFE p30 (zaman=60 dk) | 11054 | 70.9% | -0.50 ±0.03 | -0.49 ±0.05 | -0.52 ±0.05 | -0.50 ±0.07 |
| havuz-MFE p50 (zaman=60 dk) | 11054 | 65.4% | -0.51 ±0.04 | -0.49 ±0.04 | -0.54 ±0.06 | -0.50 ±0.09 |
| havuz-MFE p70 (zaman=60 dk) | 11054 | 53.4% | -0.52 ±0.05 | -0.50 ±0.05 | -0.56 ±0.07 | -0.51 ±0.12 |

### b3. İleriye dönük (walk-forward) seçim: eğitim bloğunda en iyi kural -> sonraki blokta değerlendirme

Havuz: o zaman stopundaki TÜM kurallar (k x hedef, sabit, ATR, MFE yüzdeliği, havuz-MFE). Karşılaştırma: aynı satırlarda k=1 (mevcut hedef). 'fark' = seçilen − mevcut (eşleştirilmiş, gün-kümeli).

| zaman | protokol | seçilen kural | eğitim neti | test neti | test neti: mevcut (k=1) | fark [seçilen−mevcut] | TP isabeti sec. vs mevcut |
|---|---|---|---|---|---|---|---|
| H | B1→B2 | sembol 60dk-MFE q50 (zaman=ufuk) | -0.49 | -0.51 ±0.03 | -0.54 ±0.04 | +0.03 ±0.05 | 40.3% vs 11.4% |
| H | B1→B3 | sembol 60dk-MFE q50 (zaman=ufuk) | -0.49 | -0.50 ±0.05 | -0.52 ±0.10 | +0.02 ±0.05 | 46.7% vs 15.6% |
| H | B1+B2→B3 | sembol 60dk-MFE q50 (zaman=ufuk) | -0.50 | -0.50 ±0.05 | -0.52 ±0.10 | +0.02 ±0.05 | 46.7% vs 15.6% |
| 60 | B1→B2 | sabit %0.75 (zaman=60 dk) | -0.48 | -0.55 ±0.06 | -0.61 ±0.10 | +0.07 ±0.06 | 64.0% vs 34.3% |
| 60 | B1→B3 | sabit %0.75 (zaman=60 dk) | -0.48 | -0.51 ±0.07 | -0.53 ±0.14 | +0.02 ±0.09 | 64.3% vs 39.4% |
| 60 | B1+B2→B3 | havuz-MFE p30 (zaman=60 dk) | -0.50 | -0.50 ±0.07 | -0.53 ±0.14 | +0.03 ±0.10 | 69.2% vs 39.4% |

### b4. Aile içi en iyi kural (B1+B2'de seçilir, B3'te değerlendirilir; zaman stopu iki seçenek de)

| zaman | aile | seçilen | eğitim neti (B1+B2) | test neti (B3) | fark vs mevcut k=1 | TP isabeti (B3) |
|---|---|---|---|---|---|---|
| H | mevcut hedef x k | k=0.5 x hedef (zaman=ufuk) | -0.52 | -0.51 ±0.06 | +0.01 ±0.04 | 33.6% |
| H | sabit | sabit %0.75 (zaman=ufuk) | -0.51 | -0.51 ±0.04 | +0.01 ±0.06 | 38.9% |
| H | ATR-k | ATR k=0.75 (zaman=ufuk) | -0.54 | -0.52 ±0.07 | +0.01 ±0.03 | 31.7% |
| H | sembol 60 dk MFE yüzdeliği | sembol 60dk-MFE q50 (zaman=ufuk) | -0.50 | -0.50 ±0.05 | +0.02 ±0.05 | 46.7% |
| H | sembol ufuk-MFE yüzdeliği | sembol ufuk-MFE q70 (zaman=ufuk) | -0.51 | -0.51 ±0.06 | +0.02 ±0.06 | 53.0% |
| H | havuz MFE yüzdeliği (target_calibration) | havuz-MFE p30 (zaman=ufuk) | -0.50 | -0.51 ±0.04 | +0.01 ±0.06 | 44.2% |
| 60 | mevcut hedef x k | k=0.5 x hedef (zaman=60 dk) | -0.51 | -0.51 ±0.10 | +0.01 ±0.06 | 59.4% |
| 60 | sabit | sabit %0.75 (zaman=60 dk) | -0.51 | -0.51 ±0.07 | +0.02 ±0.09 | 64.3% |
| 60 | ATR-k | ATR k=0.75 (zaman=60 dk) | -0.54 | -0.50 ±0.09 | +0.02 ±0.07 | 59.1% |
| 60 | sembol 60 dk MFE yüzdeliği | sembol 60dk-MFE q50 (zaman=60 dk) | -0.51 | -0.50 ±0.08 | +0.03 ±0.09 | 70.9% |
| 60 | sembol ufuk-MFE yüzdeliği | sembol ufuk-MFE q70 (zaman=60 dk) | -0.51 | -0.51 ±0.07 | -0.01 ±0.11 | 69.0% |
| 60 | havuz MFE yüzdeliği (target_calibration) | havuz-MFE p30 (zaman=60 dk) | -0.50 | -0.50 ±0.07 | +0.03 ±0.10 | 69.2% |

### b5. Ufuk bazında k eğrisi (tüm bloklar; zaman stopu = ufuk | 60 dk)

| ufuk | k | ort. TP% | net (ufuk) | TP isabeti | net (60 dk) | TP isabeti |
|---|---|---|---|---|---|---|
| 5 | 0.4 | 0.81 | -0.51 ±0.02 | 28.5% | -0.50 ±0.03 | 64.9% |
| 5 | 0.6 | 1.21 | -0.52 ±0.02 | 17.2% | -0.51 ±0.05 | 53.8% |
| 5 | 0.8 | 1.62 | -0.53 ±0.02 | 11.2% | -0.53 ±0.05 | 45.0% |
| 5 | 1 | 2.02 | -0.53 ±0.02 | 7.4% | -0.55 ±0.06 | 37.7% |
| 5 | 1.25 | 2.53 | -0.53 ±0.02 | 4.7% | -0.56 ±0.06 | 31.1% |
| 5 | 1.5 | 3.03 | -0.53 ±0.03 | 3.4% | -0.57 ±0.06 | 25.8% |
| 15 | 0.4 | 0.85 | -0.51 ±0.03 | 51.1% | -0.51 ±0.05 | 67.0% |
| 15 | 0.6 | 1.27 | -0.52 ±0.05 | 38.9% | -0.54 ±0.06 | 56.7% |
| 15 | 0.8 | 1.70 | -0.52 ±0.05 | 29.6% | -0.51 ±0.07 | 49.2% |
| 15 | 1 | 2.12 | -0.53 ±0.06 | 22.5% | -0.54 ±0.08 | 41.6% |
| 15 | 1.25 | 2.65 | -0.55 ±0.06 | 16.2% | -0.58 ±0.08 | 34.3% |
| 15 | 1.5 | 3.18 | -0.56 ±0.06 | 12.3% | -0.59 ±0.07 | 28.3% |

### b6. Referans: stop/zaman çıkışlarının maliyet tabanı

k=1, zaman=60 dk: TP olmayan çıkışlarda ortalama net -1.98 ±0.10 (n=6768) ve TP çıkışlarında +1.69 ±0.12 (n=4286). Yani tüm farkı TP isabeti ile TP büyüklüğü arasındaki takas belirler; sinyal sonrası serbest 60 dk sürüklenme ortalaması -0.05 ±0.05.


### e2. TP çıkışı için başabaş isabet (SL %3, k=1 mevcut hedef; ortalama kayıp, TP-dışı çıkışların ortalama netidir)

| zaman stopu | n | TP çıkışı ort. net | TP-dışı çıkış ort. net (mutlak) | başabaş isabet | gerçekleşen TP isabeti |
|---|---|---|---|---|---|
| H | 11054 | 1.74 | 0.91 | 34.5% | 14.0% |
| 60 | 11054 | 1.69 | 1.98 | 54.0% | 38.8% |

## 5. (c) ML hedefi ve target_calibration

### c1. ML hedefi/olasılığı ne öngörüyor? (V, ml alanları dolu satırlar: n=10023)

Spearman(ml_target_pct, MFE) ; AUC(ml_hit_probability -> MFE(ufuk) >= gösterilen hedef) ; AUC(prob -> MFE60 >= %1) ; karşılaştırma için Spearman(atr_pct·sqrt(ufuk/5), MFE(ufuk)).

| küme | n | medyan ml_target | ρ(ml_tgt, MFE ufuk) | ρ(ml_tgt, MFE60) | AUC prob→isabet | AUC prob→MFE60≥1 | ρ(atr_pct·√(h/5), MFE ufuk) |
|---|---|---|---|---|---|---|---|
| tümü | 10023 | 0.42 | +0.274 | +0.174 | 0.643 | 0.530 | +0.427 |
| B1 09-17..10-01 | 3523 | 0.96 | +0.364 | +0.187 | 0.663 | 0.582 | +0.396 |
| B2 10-02..10-09 | 3373 | 0.38 | +0.263 | +0.140 | 0.697 | 0.568 | +0.424 |
| B3 10-10..10-17 | 3127 | 0.12 | +0.225 | +0.092 | 0.723 | 0.612 | +0.402 |

### c2. ML karışımı etkisi: gösterilen hedef vs karışım-öncesi hedef (aynı satırlar)

Karışım: hedef = X(1-w) + ml_target x w ; w=0,5 (prob>=0,8), 0,25 (prob>=0,65). Karışım-öncesi X geri kurulur: X=(hedef−w·ml)/(1−w); yalnız kelepçeye (1,5/6,0) değmeyen satırlar (n=1180 / ML karışımı alan 3459). ML hedefi çoğunlukla düşük (medyan 0.42), bu yüzden karışım hedefi AŞAĞI çeker.
| zaman | küme | n | ort. gösterilen | ort. karışım-öncesi | isabet(gösterilen) | isabet(öncesi) | net(gösterilen) | net(öncesi) | fark [gösterilen−öncesi] | net(TP=ml_target) |
|---|---|---|---|---|---|---|---|---|---|---|
| H | tümü | 1180 | 1.88 | 2.89 | 23.0% ±4.4 | 12.3% ±3.8 | -0.47 ±0.10 | -0.51 ±0.12 | +0.03 ±0.03 | -0.46 ±0.07 |
| H | w=0,5 | 564 | 1.88 | 3.45 | 35.1% ±6.8 | 17.6% ±6.4 | -0.38 ±0.22 | -0.45 ±0.24 | +0.07 ±0.07 | -0.45 ±0.14 |
| H | w=0,25 | 616 | 1.88 | 2.38 | 11.9% ±3.9 | 7.5% ±3.1 | -0.56 ±0.08 | -0.56 ±0.08 | +0.00 ±0.02 | -0.46 ±0.08 |
| H | B1 09-17..10-01 | 95 | 2.56 | 3.00 | 34.7% ±13.6 | 31.6% ±12.2 | -0.36 ±0.42 | -0.29 ±0.47 | -0.07 ±0.15 | -0.25 ±0.41 |
| H | B2 10-02..10-09 | 236 | 1.92 | 3.09 | 23.7% ±3.5 | 13.6% ±5.8 | -0.64 ±0.24 | -0.70 ±0.20 | +0.06 ±0.10 | -0.50 ±0.11 |
| H | B3 10-10..10-17 | 849 | 1.79 | 2.83 | 21.4% ±5.6 | 9.8% ±4.0 | -0.44 ±0.10 | -0.48 ±0.12 | +0.04 ±0.03 | -0.47 ±0.07 |
| 60 | tümü | 1180 | 1.88 | 2.89 | 23.0% ±4.4 | 12.3% ±3.8 | -0.46 ±0.15 | -0.59 ±0.17 | +0.13 ±0.07 | -0.45 ±0.08 |
| 60 | w=0,5 | 564 | 1.88 | 3.45 | 35.1% ±6.8 | 17.6% ±6.4 | -0.32 ±0.23 | -0.52 ±0.26 | +0.20 ±0.13 | -0.43 ±0.17 |
| 60 | w=0,25 | 616 | 1.88 | 2.38 | 11.9% ±3.9 | 7.5% ±3.1 | -0.59 ±0.14 | -0.65 ±0.16 | +0.06 ±0.05 | -0.47 ±0.09 |
| 60 | B1 09-17..10-01 | 95 | 2.56 | 3.00 | 34.7% ±13.6 | 31.6% ±12.2 | -0.35 ±0.62 | -0.52 ±0.62 | +0.17 ±0.29 | -0.24 ±0.48 |
| 60 | B2 10-02..10-09 | 236 | 1.92 | 3.09 | 23.7% ±3.5 | 13.6% ±5.8 | -0.62 ±0.38 | -0.80 ±0.35 | +0.18 ±0.13 | -0.45 ±0.12 |
| 60 | B3 10-10..10-17 | 849 | 1.79 | 2.83 | 21.4% ±5.6 | 9.8% ±4.0 | -0.43 ±0.16 | -0.54 ±0.20 | +0.11 ±0.08 | -0.47 ±0.09 |

### c3. ML-karışımlı vs karışımsız satırlar: hedef ve isabet

| küme | n | ort. hedef | isabet(ufuk) | medyan MFE | net (zaman=ufuk) | net (zaman=60) |
|---|---|---|---|---|---|---|
| ML karışımı yok (prob<0,65 / ML yok) | 7595 | 2.28 | 12.0% ±1.7 | 0.58 | -0.56 ±0.05 | -0.58 ±0.08 |
| ML karışımı var (prob>=0,65) | 3459 | 1.63 | 20.8% ±2.5 | 0.60 | -0.50 ±0.05 | -0.51 ±0.10 |

### c6. Bildirimlerde 'kalibre' görünen 2,1–2,4 hedef grubu nedir?

| grup | n | ML karışımı (prob>=0,65) payı | ort. ml_prob | ort. skor | ort. hedef | uygulama isabeti | yeniden isabet(ufuk) |
|---|---|---|---|---|---|---|---|
| hedef 2,05–2,45 | 153 | 100% | 0.96 | 96.2 | 2.21 | 46.4% ±7.5 | 34.0% ±5.5 |
| diğer hedefler | 556 | 11% | 0.31 | 93.3 | 3.32 | 16.0% ±3.7 | 11.3% ±2.5 |
| diğer hedefler, skor>=90 | 358 | 13% | 0.35 | 96.6 | 3.36 | 18.2% ±4.8 | 14.8% ±4.2 |

Aynı eksenin V karşılığı (ML karışımından bağımsız, skora göre):

| küme | n | ort. hedef | isabet(ufuk) | medyan MFE |
|---|---|---|---|---|
| V, skor>=90, ufuk 5 | 559 | 2.30 | 20.6% ±4.5 | 0.89 |
| V, skor<90, ufuk 5 | 5629 | 2.00 | 6.6% ±1.1 | 0.38 |
| V, skor>=90, ufuk 15 | 276 | 2.39 | 43.8% ±5.7 | 1.98 |
| V, skor<90, ufuk 15 | 4104 | 2.10 | 22.4% ±2.9 | 0.87 |

Okuma: 2,1–2,4 grubunun tamamı ML-karışımlı ve yüksek skorludur; V'de yüksek skor zaten 15 dk'da ~%44 isabet veriyor. ML olasılığı yüksek kovada medyan MFE düşük kovadan yalnız %12-17 yüksek (tablo c5: 5 dk 0,49 vs 0,42; 15 dk 1,05 vs 0,94); isabet farkının büyük kısmı hedefin ML ile aşağı çekilmesinden ve yüksek skordan gelir (ML seçimi ile hedef düşüşü bu veriyle tam ayrıştırılamaz); yani bu grup 'iyi kalibrasyon' kanıtı değil, 'daha düşük hedef + yüksek skor' kanıtıdır.

### c4. `target_calibration` (RADAR_TARGET_CALIBRATION_ENABLED): ölçülmüş MFE yüzdeliği hedef olsaydı

Emülasyon: ufuk başına önceki 14 günün V-olaylarının MFE(ufuk) yüzdeliği (>=30 örnek), [0,6; 4,5] kelepçe, 1 ondalık; yeterli örnek yoksa mevcut hedefe düşer. (Üretimde veri kaynağı unified_candidate_outcomes'tır; aşağıdaki tablo aynı hesabın V karşılığı.)

| ufuk | n (son 14 gün) | p30 | p50 (varsayılan) | p70 | mevcut medyan hedef |
|---|---|---|---|---|---|
| 5 | 3860 | 0.6 | 0.6 | 0.7 | 1.89 |
| 15 | 2396 | 0.6 | 0.8 | 1.5 | 1.76 |
| 30 | 302 | 0.6 | 0.8 | 1.6 | 2.10 |
| 60 | 184 | 0.7 | 1.5 | 2.7 | 2.11 |

Kalibre hedef TP olarak (yalnız emülasyon verisi olan satırlar):

| zaman | yüzdelik | n | ort. kalibre hedef | ort. mevcut hedef | TP isabeti kalibre vs mevcut | net kalibre | net mevcut | fark |
|---|---|---|---|---|---|---|---|---|
| H | p30 | 10921 | 0.62 | 2.07 | 46.3% vs 13.8% | -0.51 ±0.02 | -0.54 ±0.04 | +0.04 ±0.03 |
| H | p50 | 10921 | 0.83 | 2.07 | 39.1% vs 13.8% | -0.52 ±0.02 | -0.54 ±0.04 | +0.03 ±0.02 |
| H | p70 | 10921 | 1.38 | 2.07 | 24.4% vs 13.8% | -0.53 ±0.03 | -0.54 ±0.04 | +0.01 ±0.01 |
| 60 | p30 | 10921 | 0.62 | 2.07 | 71.2% vs 38.7% | -0.50 ±0.03 | -0.56 ±0.06 | +0.06 ±0.05 |
| 60 | p50 | 10921 | 0.83 | 2.07 | 65.7% vs 38.7% | -0.51 ±0.04 | -0.56 ±0.06 | +0.05 ±0.04 |
| 60 | p70 | 10921 | 1.38 | 2.07 | 53.5% vs 38.7% | -0.52 ±0.05 | -0.56 ±0.06 | +0.04 ±0.03 |

Kod notu: `dynamic_target_pct` kalibre hedefi hesapladıktan SONRA `max(hedef, net_profit_floor)` uygular (floor = 2,0 + gidiş-dönüş maliyet %0,275 + spread; spread bilinmiyorsa 0,65 → ~%2,9). Emülasyondaki p50 değerlerinin %99'i 2.27'nin altındadır → bayrak açılsa bile hedef çoğunlukla net-kâr tabanına (floor) geri döner; kalibrasyon yalnız skor kademesinin yukarı itişini (4,0) siler. Birleşik (fusion) yolu `horizon_minutes` geçmediği için kalibrasyondan hiç etkilenmez.


### c5. ML isabet olasılığı güvenilirliği (V)

ML sınıflandırıcısı ufuk 5 için %2, ufuk 15 için %3 hedefe dokunma olasılığını tahmin eder (config.ML_HIT_TARGET_PCT). Tabloda tahmin kovası başına gerçekleşen P(MFE(ufuk) >= o ufkun ML hedefi) ve P(MFE >= gösterilen hedef).

| ufuk | ml_hit_probability | n | ort. tahmin | gerçekleşen P(MFE>=ML hedefi %2/%3) | gerçekleşen P(MFE>=gösterilen hedef) | medyan MFE |
|---|---|---|---|---|---|---|
| 5 | 0.00–0.30 | 3323 | 0.06 | 7.5% ±1.4 | 6.0% ±1.3 | 0.42 |
| 5 | 0.30–0.50 | 306 | 0.39 | 9.8% ±5.2 | 6.2% ±4.0 | 0.32 |
| 5 | 0.50–0.65 | 313 | 0.58 | 6.4% ±4.0 | 5.1% ±3.4 | 0.27 |
| 5 | 0.65–0.80 | 514 | 0.74 | 5.6% ±3.0 | 5.8% ±2.6 | 0.31 |
| 5 | 0.80–1.01 | 1529 | 0.90 | 9.5% ±1.9 | 13.9% ±2.4 | 0.49 |
| 15 | 0.00–0.30 | 2221 | 0.10 | 13.0% ±2.1 | 19.5% ±2.4 | 0.94 |
| 15 | 0.30–0.50 | 289 | 0.39 | 22.1% ±8.4 | 24.2% ±9.0 | 1.04 |
| 15 | 0.50–0.65 | 223 | 0.58 | 11.7% ±7.8 | 15.2% ±8.1 | 0.63 |
| 15 | 0.65–0.80 | 338 | 0.74 | 7.7% ±5.3 | 13.9% ±4.8 | 0.63 |
| 15 | 0.80–1.01 | 1156 | 0.91 | 16.7% ±4.3 | 37.5% ±5.3 | 1.05 |



## 6. (d) Öneri: formül, tablo, net hedef

### Öneri özeti (d)

1. **Bu çalışmanın ana bulgusu hedefin DEĞİL giriş sinyalinin net getirisi olmadığıdır**: hedef kuralı ne olursa olsun B3 neti −0,50…−0,55 bandında (mevcut −0,52/−0,53). Hedef formülü
   değiştirmek 'bildirim kârlı olur' iddiasını DESTEKLEMEZ; yalnız **gösterilen sayının doğruluğunu** (ulaşılabilirlik) ve tekdüzeliğini iyileştirir.
2. **Önerilen formül** (yalnız sinyal anı bilgisi; panel skor 30-100 aralığına kısılır, atr_pct yüzde olarak [0,05; 5]):
   `T = clamp( exp(a) · atr_pct^b · (ufuk/5)^d · exp(c·(skor−70)/10) , 0,5 ; 6,0 )`.
   * Nominal %50 isabet: a=-0.31, b=0.72, d=0.52, c=0.05 (tüm veriyle); B1+B2'de kurulup B3'te sınanan sürüm: gerçekleşen isabet ≈ %39 (ATR/ufuk/skor dilimlerinde %33–45), ort. hedef 0,90,
     net −0,51 (zaman=ufuk) / −0,50 (zaman=60).
   * Nominal %30 isabet: a=0.27, b=0.71, d=0.51, c=0.06; B3 gerçekleşen isabet ≈ %24 (dilimler %23–26; mevcut hedefte %5–32), ort. hedef 1,45, net −0,54 / −0,54.
   * Gerçekleşen isabetin nominalden düşük olması iki kaynaktan gelir: [0,5] alt kelepçesi (maliyet tabanı) hedefi yüzdeliğin üstüne iter; B3 MFE'si B1'den düşüktür (gözlenen dönem kayması).
   * Alternatif (formülsüz, tablo): 'e1' tablosu — ufuk x skor hücresinden eğitim bloklarının MFE yüzdeliği; 5 dk için nominal %30'da hedef ≈ 0,70 (skor<74) / 1,00 (74–90) / 1,70 (≥90) ve 15 dk için
     1,70 / 3,10 / 4,75; B3 gerçekleşen isabet nominalin altında (dönem kayması). 15 dk skor>=90'da MEVCUT hedef (≈1,8) B3'te %42 tutuyor; tablo yöntemi (nominal %50) orada hedefi 2,9'a çıkarıp isabeti %22'ye düşürüyor — tabloyu
     canlıya almadan önce rolling pencereyle (14 gün) yeniden kurmak gerekir.
3. **Net hedef gösterimi**: evet, ama bilgi olarak: `net hedef = brüt − 0,33` (giriş kayması %0,15 + taker %0,1125 + maker TP %0,0675; stop/zaman çıkışında 0,525). Yanında hücrenin geçmiş isabeti
   (örn. 'son 14 gün bu ufuk/skor/oynaklıkta isabet %X') ve başabaş isabet gösterilmeli: k=1, zaman=60 dk için başabaş isabet %54, gerçekleşen %39 (tablo e2); 'Beklenen fiyat' bu yüzden kâr vaadi gibi okunmamalı.
4. **Kod düzeltmeleri (öncelik sırası, canlı koda bu çalışmada dokunulmadı)**:
   * (i) `unified_signals.py:361-367, 464-470` fusion yolu: sabit 4,0 (n=126 sonuçta %4 isabet) yerine ufuk/ATR'li formül; ufuk=5 sabit yazılı.
   * (ii) `velocity.py:2669-2672` öğrenilmiş hedef: EMA 0,8·MFE ile beslendiği için sembollerin %89'unda tabana (1,5) yapışık ve ağırlık 0,6 ⇒ kademe/taban/kalibrasyon ×0,4'e sıkışıyor. Ya EMA'yı
     anlamlı bir yüzdelikle besleyin ya da bu adımı hedeften çıkarın; şimdiki hali sabit bir doğrusal dönüşümdür.
   * (iii) `RADAR_TARGET_CALIBRATION_ENABLED` bayrağını açmak fayda sağlamaz: ölçülmüş p50 (0,6–0,8; 60 dk 1,5) net-kâr tabanının (2,3–2,9) altında kaldığı için `max(hedef, taban)` hedefi geri alır
     (emülasyonda %99) ve fusion yolu ufuk geçmediği için hiç kalibre olmaz. Kalibrasyon ancak taban kaldırılırsa/ayrı 'net hedef' olarak ele alınırsa etkili olur.
   * (iv) Net-kâr tabanı 'net %2 güvencesi' vaat ediyor ama 5. ve 6. adımlarda (öğrenilmiş + ML karışımı) çiğneniyor (V hedeflerinin %74'i 2,275'in altında). Ya vaat kaldırılmalı ya adım sırası düzeltilmeli.
   * (v) Test kirliliği: `monitoring_notifications`'ta mode NULL / BTCTRY-ETHTRY / hedef 2,0 satırları (56+) raporları bozuyor; testlerin üretim DB'sine yazması engellenmeli ve satırlar silinmeli (bu çalışmada silinmedi).
5. **Yapılmaması gerekenler**: hedefi 'daha gerçekçi' diye düşürüp isabet artışını başarı olarak sunmak (k=0,4 → zaman=60'ta %65 TP isabeti ama net −0,51); ML karışımını 'ML iyileştirdi' diye yorumlamak (etki hedefi düşürmekten ibaret).

Model: T = exp(a) · atr_pct^b · (ufuk/5)^d · exp(c·(skor−70)/10), [0,5; 6,0] kelepçe; katsayılar MFE(ufuk)'in (1−nominal isabet) yüzdeliği için pinball kaybını küçültür. Eğitim: B1+B2 (ve ayrıca B1→B2 sınaması); test: B3 / B2. Girdi yalnız sinyal anında bilinenler.

| nominal isabet | protokol | katsayılar | n (test) | ort. hedef | gerçekleşen isabet | net (zaman=ufuk) | net (zaman=60) | fark vs mevcut (ufuk) | fark vs mevcut (60) |
|---|---|---|---|---|---|---|---|---|---|
| 50% | B1→B2 | a=-0.23 b=0.61 d=0.57 c=0.11 | 3490 | 0.79 | 38.9% ±1.9 | -0.52 ±0.03 | -0.55 ±0.07 | +0.02 ±0.03 | +0.07 ±0.04 |
| 50% | B1+B2→B3 | a=-0.34 b=0.64 d=0.65 c=0.09 | 4034 | 0.90 | 39.4% ±2.4 | -0.51 ±0.08 | -0.50 ±0.10 | +0.02 ±0.02 | +0.03 ±0.05 |
| 30% | B1→B2 | a=0.32 b=0.58 d=0.56 c=0.12 | 3490 | 1.28 | 24.2% ±1.8 | -0.53 ±0.05 | -0.60 ±0.08 | +0.01 ±0.02 | +0.02 ±0.05 |
| 30% | B1+B2→B3 | a=0.22 b=0.63 d=0.63 c=0.10 | 4034 | 1.45 | 24.4% ±2.4 | -0.54 ±0.09 | -0.54 ±0.13 | -0.01 ±0.01 | -0.02 ±0.05 |

B1+B2 → B3: formül hedefinin gerçekleşen isabeti, dilim başına (mevcut gösterilen hedef karşılaştırması ile):

| nominal | dilim | n | formül: ort. hedef | formül: isabet | mevcut: ort. hedef | mevcut: isabet |
|---|---|---|---|---|---|---|
| 50% | tümü | 4034 | 0.90 | 39.4% ±2.4 | 1.85 | 16.2% ±1.8 |
| 50% | ufuk 5 | 1896 | 0.59 | 36.6% ±2.7 | 1.77 | 8.6% ±1.6 |
| 50% | ufuk 15 | 1652 | 0.98 | 44.4% ±1.8 | 1.80 | 23.3% ±4.6 |
| 50% | ATR düşük | 1475 | 0.56 | 32.9% ±1.5 | 1.84 | 5.4% ±1.4 |
| 50% | ATR orta | 1343 | 0.77 | 41.4% ±5.1 | 1.76 | 14.3% ±3.8 |
| 50% | ATR yüksek | 1216 | 1.44 | 45.1% ±4.3 | 1.97 | 31.2% ±3.1 |
| 50% | skor<74 | 2412 | 0.76 | 37.7% ±1.4 | 1.81 | 13.0% ±2.9 |
| 50% | skor 74–90 | 1209 | 0.92 | 42.1% ±4.5 | 1.90 | 17.2% ±2.3 |
| 50% | skor>=90 | 413 | 1.59 | 41.6% ±7.4 | 1.95 | 31.7% ±5.9 |
| 30% | tümü | 4034 | 1.45 | 24.4% ±2.4 | 1.85 | 16.2% ±1.8 |
| 30% | ufuk 5 | 1896 | 0.86 | 25.2% ±1.3 | 1.77 | 8.6% ±1.6 |
| 30% | ufuk 15 | 1652 | 1.68 | 25.4% ±2.9 | 1.80 | 23.3% ±4.6 |
| 30% | ATR düşük | 1475 | 0.79 | 23.3% ±1.7 | 1.84 | 5.4% ±1.4 |
| 30% | ATR orta | 1343 | 1.30 | 24.8% ±3.9 | 1.76 | 14.3% ±3.8 |
| 30% | ATR yüksek | 1216 | 2.41 | 25.3% ±4.4 | 1.97 | 31.2% ±3.1 |
| 30% | skor<74 | 2412 | 1.19 | 24.8% ±2.5 | 1.81 | 13.0% ±2.9 |
| 30% | skor 74–90 | 1209 | 1.55 | 24.1% ±3.3 | 1.90 | 17.2% ±2.3 |
| 30% | skor>=90 | 413 | 2.66 | 23.0% ±6.9 | 1.95 | 31.7% ±5.9 |

Tüm veriyle (B1+B2+B3) uyarlanmış katsayılar (uygulama önerisi için): nominal 50%: a=-0.31 b=0.72 d=0.52 c=0.05; nominal 30%: a=0.27 b=0.71 d=0.51 c=0.06


### e1. Öneri adayı: ufuk x skor tablosundan 'ölçülmüş yüzdelik' hedef — B1+B2'de kurulur, B3'te sınanır

Hedef = ilgili hücrede eğitim bloklarının MFE(ufuk) dağılımının (1 − nominal isabet) yüzdeliği (0,05'e yuvarlı). Gerçekleşen isabet, net (zaman=ufuk | zaman=60) yalnız B3 satırlarında ölçülür. 'mevcut' = aynı B3 satırlarında gösterilen hedef.

| ufuk | skor | nominal isabet | hedef % | n (B3) | gerçekleşen isabet (B3) | net B3 (zaman=ufuk) | net B3 (zaman=60) | mevcut: ort. hedef / isabet |
|---|---|---|---|---|---|---|---|---|
| 5 | <74 | 50% | 0.40 | 1046 | 38.0% ±2.8 | -0.49 ±0.03 | -0.44 ±0.04 | 1.74 / 3.8% |
| 5 | <74 | 30% | 0.70 | 1046 | 21.0% ±2.0 | -0.49 ±0.03 | -0.47 ±0.04 | 1.74 / 3.8% |
| 5 | <74 | 20% | 0.95 | 1046 | 12.4% ±2.0 | -0.49 ±0.03 | -0.47 ±0.07 | 1.74 / 3.8% |
| 5 | 74–90 | 50% | 0.55 | 633 | 44.2% ±5.3 | -0.48 ±0.04 | -0.50 ±0.08 | 1.80 / 10.7% |
| 5 | 74–90 | 30% | 1.00 | 633 | 23.5% ±4.8 | -0.51 ±0.06 | -0.58 ±0.13 | 1.80 / 10.7% |
| 5 | 74–90 | 20% | 1.45 | 633 | 12.8% ±3.2 | -0.51 ±0.05 | -0.55 ±0.17 | 1.80 / 10.7% |
| 5 | >=90 | 50% | 0.95 | 217 | 45.6% ±6.1 | -0.45 ±0.13 | -0.38 ±0.20 | 1.81 / 25.3% |
| 5 | >=90 | 30% | 1.70 | 217 | 24.4% ±7.5 | -0.40 ±0.20 | -0.24 ±0.35 | 1.81 / 25.3% |
| 5 | >=90 | 20% | 2.30 | 217 | 17.5% ±6.5 | -0.35 ±0.25 | -0.26 ±0.35 | 1.81 / 25.3% |
| 15 | <74 | 50% | 0.95 | 1034 | 36.4% ±5.4 | -0.46 ±0.05 | -0.47 ±0.08 | 1.80 / 19.1% |
| 15 | <74 | 30% | 1.70 | 1034 | 19.0% ±7.0 | -0.48 ±0.07 | -0.46 ±0.11 | 1.80 / 19.1% |
| 15 | <74 | 20% | 2.30 | 1034 | 11.7% ±5.0 | -0.49 ±0.07 | -0.51 ±0.09 | 1.80 / 19.1% |
| 15 | 74–90 | 50% | 1.80 | 461 | 26.5% ±3.4 | -0.44 ±0.15 | -0.39 ±0.21 | 1.80 / 26.5% |
| 15 | 74–90 | 30% | 3.10 | 461 | 10.2% ±1.5 | -0.53 ±0.14 | -0.53 ±0.28 | 1.80 / 26.5% |
| 15 | 74–90 | 20% | 4.05 | 461 | 5.6% ±1.8 | -0.55 ±0.15 | -0.55 ±0.29 | 1.80 / 26.5% |
| 15 | >=90 | 50% | 2.90 | 157 | 21.7% ±6.1 | -0.61 ±0.21 | -0.78 ±0.30 | 1.84 / 42.0% |
| 15 | >=90 | 30% | 4.75 | 157 | 13.4% ±6.2 | -0.58 ±0.30 | -0.77 ±0.44 | 1.84 / 42.0% |
| 15 | >=90 | 20% | 5.75 | 157 | 9.6% ±5.6 | -0.68 ±0.24 | -0.98 ±0.48 | 1.84 / 42.0% |

