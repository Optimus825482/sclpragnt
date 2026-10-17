# BTC Rejim Kalkanı, Aşırı Alım Kapısı ve Merdiven Yükseliş — Geriye Dönük Ölçüm (2026-10-17)

**Tetikleyici:** LUNATRY 17 Ekim 01:05–01:53 arasında +%5,5 "merdiven" yükseliş yaptı; radar onu izleme listesinin
tepesine aldı (birleşik skor 92,7, trend_devam, 4 kaynak, ML olasılık 0,94) ama bildirim gitmedi:
`BTC_BEAR_REGIME_SHIELD` (BTC 1H EMA200'ün %0,76 altı) ve `mfi_asiri_alim:96` kapıları. Soru: bu iki kapı
geçmişte gerçekten kayıp mı önledi, yoksa fırsat mı kaçırdı? Ve sıçramasız yükselişler daha erken yakalanabilir mi?

**Veri ve yöntem**
- Pencere **2026-09-26 .. 10-16 (21 gün)**: `historical_candles` 5m bu tarihte başlıyor (60 günlük mum yok; rescan
  journal'ı 30 gün ama mumsuz ölçüm yapılamaz).
- Adaylar: `scripts/rescan_velocity_history.py --no-exhaustion-gate --journal-cap 0 --step-min 5` (yeni bayrak;
  MFI/RSI üst kapısı kapalı, satırda `rsi`/`mfi` alanı) → 35.802 satır, (sembol,tick) tekilleştirilmiş 17.901,
  **birincil küme tick başına rank ≤ 10 (canlı bildirim havuzuna en yakın) 17.446 satır / 5.344 bağımsız bölüm** (aynı
  sembolde 60 dk içindeki tekrarlar tek bölüm).
- Kalkan etiketi: BTCTRY 1h kapanışları (public kline, 1000 bar) üzerinde canlı `macro_sentiment_service` ile aynı
  `_ema(closes[-210:], 200)`; forming barın kapanışı = tick anındaki son 5m BTC kapanışı. **Kalkan açık ⇔ fiyat < EMA200.**
- Aşırı alım etiketi: satırın MFI14(1m) ≥ 90 ya da RSI14(1m) ≥ 80 (canlı `VELOCITY_MFI_UPPER` / `VELOCITY_RSI_UPPER`).
- Sonuç: hedef = adayın kendi `target_pct`'si, SL −3, maliyet −0,225 (BNB taker ×2), 15 ve 60 dk ufuk; giriş = aday
  fiyatı. Şans tabanı: `notification_outcomes_report.compute_chance` null3 (aynı sembol, saat dilimi, 30 dk aralık ve
  getiri eşleşmiş rastgele anlar), 3.000 bölüm örnekleminde. Betik: `backend/scripts/radar_shield_rescan_analysis.py`;
  ham çıktı `backend/work/shield_rescan.md`.
- Ön kayıtlı karar kuralı (`scripts/radar_shield_analysis.py` ile aynı, veri görülmeden): hit60(kalkan) ≥ hit60(geçen) − 5
  puan → **KALKAN_FAZLA_SIKI**; < −10 puan → KALKAN_ISE_YARIYOR.

## 1. Kalkan ne sıklıkla açıktı?

Pencerede 5 dk tick'lerin **%57**'sinde kalkan açıktı. Gün payları: 09-28..10-01 %63–85, 10-02..10-06 %0, 10-07..10-16
%55–100 (10-08..10-11 ve 10-15 **%100**). Yani son 10 günün çoğunda sistem hiç bildirim üretmedi.

## 2. Kalkanın engellediği adaylar daha mı kötüydü? Hayır.

Bağımsız bölümler, aşırı alım kapısı canlıdaki gibi açık (yalnız kapıyı geçenler):

| küme | n | hit15 | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | hit60 − şans (null3) |
|---|---|---|---|---|---|---|---|
| Kalkan KAPALI — bildirim gitti | 1431 | %6,1 | %19,8 [18–22] | +2,11 | −2,34 | −0,57 (t −9,2) | +3,8 pp (n=799) |
| Kalkan AÇIK — bildirim KESİLDİ | 2261 | %6,9 | **%21,6** [20–23] | +2,40 | −2,29 | **−0,38** (t −7,5) | +4,4 pp (n=1282) |

Fark hit60 **+1,9 puan** kesilenler lehine; net60 farkı Welch **t +2,33**. Ön kayıtlı kural: **KALKAN_FAZLA_SIKI**.
trend_devam alt kümesinde aynı yön (kalkan açık %19,4 / −0,45 vs kapalı %18,4 / −0,55). Rank sınırı olmadan tüm geçen
adaylarda da aynı (kesilen %27,9 / −0,42 vs giden %26,1 / −0,54).

**Yumuşatma bölgesi:** kalkan açıkken "sert" bölge (EMA'nın ≥%1 altı VE BTC 4 saatlik getiri < 0, n=762) hit60 %23,4,
şansa göre +5,9 pp; "yumuşak" bölge (n=1499) %20,7, +3,7 pp. Yani BTC'nin EMA'nın daha da altında ve düşerken olduğu
anlar bile altcoin adaylarını kötüleştirmiyor; **kalkanı "biraz altındayken serbest bırak" diye yumuşatmanın da
kanıtı yok, kalkanın kendisinin kanıtı da yok.**

## 3. Aşırı alım kapısı (MFI ≥ 90 / RSI ≥ 80) — kalkan kapalı bölümlerde

| küme | n | hit60 [Wilson95] | MFE60 | MAE60 | net60 % (t) | hit60 − şans |
|---|---|---|---|---|---|---|
| Kapı geçti (bildirim gitti) | 1431 | %19,8 [18–22] | +2,11 | −2,34 | −0,57 (t −9,2) | +3,8 pp |
| Kapı eledi (aşırı alım) | 690 | %19,0 [16–22] | +2,00 | −2,04 | −0,39 (t −4,4) | **+10,5 pp** (n=396) |
| trend_devam · geçti | 879 | %18,4 | +2,16 | −2,26 | −0,55 | +4,3 pp |
| trend_devam · aşırı alım elendi | 677 | %19,1 | +1,99 | −2,06 | −0,39 | +10,2 pp |

Elenenlerin isabeti geçenlerle aynı, MAE daha küçük, net daha az kötü; şansa göre farkları (eşleşen rastgele anların
isabeti düşük olduğu için) belirgin daha yüksek. **Kapı, kalkan kapalıyken ayırt edici değil.** Kalkan açıkken aşırı
alım kümesi daha zayıf (%16,6, +3,3 pp) — iki kapının kesişimi tek anlamlı "kötü" hücre, o da zaten kesiliyor.

## 4. Merdiven yükseliş dedektörü (prototip) — erken yakalıyor mu, değer katıyor mu?

`app/rescan/ladder.py` + `scripts/ladder_rescan.py`: 5m barda N ardışık (yüksek kapanış ∧ dip ≥ önceki dip), N barlık
kazanç [gain_min, 4], hacim ≥ vol_min × önceki 20 bar, RSI14(5m) ≤ rsi_max, 24s quote ≥ 5M TRY, 60 dk soğuma. 16 hücre,
TP 1,5 / 2,0, SL −3, maliyet −0,225, 60 dk. Ham çıktı `backend/work/ladder_rescan.md`.

| hücre (N, gain_min, vol_min, rsi_max) | sinyal/gün | hit60@1,5 | net60@1,5 | hit60@2,0 | net60@2,0 | HA adayı 90 dk içinde geldi | öncülük medyan | HA bölüm kapsama |
|---|---|---|---|---|---|---|---|---|
| 3, 0,8, 1,0, 70 (net en iyi) | 214 | %27,1 | −0,29 | %18,7 | −0,29 | %20,8 | 10 dk | %18,3 |
| 3, 1,5, 1,0, 70 (hit en iyi) | 77 | **%39,5** | −0,32 | %29,4 | −0,31 | %42,7 | 5 dk | %12,8 |
| 4, 1,5, 1,0, 70 | 42 | %37,2 | −0,30 | %27,9 | −0,27 | %36,7 | 10 dk | %5,9 |
| (16 hücrenin tamamı) | 31–300 | %25–40 | **−0,29 … −0,39** | %18–29 | −0,27 … −0,38 | %20–46 | 5–15 dk | %4–28 |

- Şansa göre: hit en iyi hücre %39,5 vs eşleşmiş şans %35,4 → **+4,1 pp**; net en iyi hücre +2,4 pp. Hız Avcısı'nın
  aynı pencerede şansa göre farkı +3,8/+4,4 pp. **Merdiven dedektörü Hız Avcısı'ndan daha iyi değil.**
- Erkenlik: yakaladığı hareketlerde Hız Avcısı adayı medyan **5–10 dk sonra** zaten geliyor; Hız Avcısı bölümlerinin
  en çok %28'inden önce sinyal veriyor (o alt kümede medyan 35–40 dk erken). Yani "20–25 dk gecikme" iddiasının
  çoğu pencerede doğrulanmıyor; erkenlik kazancı dar bir alt kümede.
- "Yeni yakalama" (±90 dk'da Hız Avcısı adayı yok) kümeleri daha zayıf: hit60 %17–28, net −0,37 … −0,41.
- Her hücre net negatif (t −5 … −19): sabit TP/SL ile kârlı bir erken-giriş kuralı bulunamadı. LUNATRY tipi tek
  örnekler var, ama kural olarak genelleşmiyor.

## 5. Sonuç ve öneri

1. **Rejim kalkanı kanıtsız bir duvar.** 21 günün %57'sinde tüm altcoin bildirimlerini kesti; kestikleri adaylar
   gidenlerden daha kötü değil, hatta biraz daha iyi (hit +1,9 puan, net t +2,3). Ön kayıtlı kurala göre
   KALKAN_FAZLA_SIKI. Öneri: **kalkanı bildirimde rozete çevir** (bildirim "⚠ BTC rejim" etiketiyle gider), kalkan
   yalnız otonom paper girişi için kalsın; bu da ayrıca ölçülsün (auto_paper mod bazlı outcome). Bayrak önerisi:
   `RADAR_SHIELD_MODE=badge|block` (varsayılan geçişte `badge`), `BTC_REGIME_SHIELD_ENABLED` dokunulmaz.
2. **Aşırı alım kapısı kalkan kapalıyken değer katmıyor.** Elenen adaylar geçenlerle aynı isabette, daha az MAE.
   Öneri: trend_devam modunda kapıyı **skor cezasına** çevir (eleme yerine `velocity_score × 0,85`, bayrak
   `VELOCITY_EXHAUSTION_MODE=penalty|block`), kalkan açıkken (kesişim hücresi) eleme kalsın; 14 gün sonra
   `notification_outcomes_report.py` ile isabet/hacim kontrolü.
3. **Merdiven dedektörünü canlıya alma.** Erkenlik kazancı dar, şansa göre üstünlüğü Hız Avcısı'ndan düşük, her hücre
   net negatif. Prototip ve ölçüm betiği repoda kalır; 1m mum ve adaya özel hedefle tekrar denenebilir.
4. Daha genel bulgu değişmedi: bu pencerede tüm kümeler net negatif (−0,3 … −0,6 %/işlem); kapıları açmak kârlılık
   getirmez, yalnız **kaybı artırmadan sinyal akışını geri getirir** (kullanıcı kararı: görünürlük vs. sessizlik).

**Sınırlar:** 21 gün tek dönem; kalkan günleri kümelenmiş (rejim-dönem karışıklığı olası); rescan sapmaları
(spread/taker/ML hedef, kadans 5 dk) `docs/RESCAN_HARNESS.md`; giriş gecikmesiz; 16 hücrelik ızgarada en iyi hücre
iyimser; şans tabanı örneklemde. Canlı kod değiştirilmedi; `--no-exhaustion-gate` yalnız analiz bayrağıdır.

## 6. Uygulama (2026-10-17, aynı gün)

- `RADAR_SHIELD_MODE=badge` (varsayılan): Master Surge ve yükseliş yolunda kalkan artık `passes=False` üretmez;
  aday `regime_badge="BTC_BEAR_REGIME_SHIELD"` taşır, bildirim başlığı/mesajı "⚠ BTC REJİM · " ile başlar,
  `monitoring_notifications` zarfına ve `unified_candidate_outcomes.regime_badge` (migration 019) kolonuna yazılır.
  `auto_paper.try_open_from_notification` rozeti ya da anlık kalkanı görünce otonom girişi yine engeller
  (`risk_blocked:BTC_BEAR_REGIME_SHIELD`). `block` eski davranışı geri getirir.
- `VELOCITY_EXHAUSTION_MODE=penalty` (varsayılan) + `VELOCITY_EXHAUSTION_PENALTY_MULT=0.85`: trend_devam modunda
  `mfi/rsi_asiri_alim` eleme değil skor cezası; yalnız kalkan kapalıyken (kalkan açıkken eleme sürer). Canlı dedektör
  ve rescan çekirdeği `velocity.exhaustion_decision` ile aynı kararı verir; `radar.exhaustion_penalty` bayrağı.
- Ölçüm: `scripts/radar_shield_analysis.py` artık `shield_badge` (rozetle giden) grubunu ayrı raporlar; 14 gün sonra
  `passed` ile kıyaslanmalı. Merdiven dedektörü canlıya alınmadı.

> **Güncelleme (aynı gün):** 90 günlük doğrulama (docs/DOGRULAMA_90G_2026-10-17.md) kalkan bulgusunu teyit etti (FAZLA_SIKI, rozet korundu) ama aşırı alım bulgusunu ÇÜRÜTTÜ: kalkan kapalıyken elenenler 90 günde belirgin kötü (−8,0 pp). `VELOCITY_EXHAUSTION_MODE` varsayılanı `block`'a geri alındı. Bu rapordaki §3 sonucu yalnız son ~3 haftaya özgüdür.
