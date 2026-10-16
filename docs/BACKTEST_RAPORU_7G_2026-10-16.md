# 7 Günlük Backtest ve Replay Raporu — 2026-10-16

**Soru:** Güncel kod (main @ db0edc60 + bugünkü harness onarımları) ile son 7 günde (9–16 Ekim 2026) sistem para kazanıyor mu?
**Kısa cevap:** Hayır. Beş bağımsız ölçümün beşinde de ortalama net getiri negatif; zararın büyüklüğü işlem başına gidiş-dönüş maliyetine (%0.30–0.35) eşit. Brüt kenar sıfır civarında. Bugün eklenen zaman-stop varyantları bunu değiştirmiyor. Tek pozitif alt küme, radar replay'inde `jump+velocity` çakışmaları (+0.13 %/sinyal, n≈190), hipotez düzeyinde.

**Yöntem:** Yerel PostgreSQL 17'de `scalper_prod_copy` (549 MB üretim kopyası) dump/restore ile `scalper` olarak klonlandı, 17 migration uygulandı. Beş Sonnet ajanı paralel koştu; her biri tek harness'ı 7 gün için çalıştırıp metrikleri raporladı. Ham çıktılar scratchpad `backtest/` altında.

---

## 1. Ortam ve Veri

| Öğe | Durum |
|-----|-------|
| PostgreSQL | 17 (Windows servisi), pgvector kurulu |
| Veritabanı | `scalper` ← `scalper_prod_copy` (dump/restore; kopya başka oturum tarafından açık olduğundan TEMPLATE kullanılamadı) |
| Migration | 001–017 `schema_migrations` ile uygulandı (017 bu kurulumda yeni) |
| velocity_candidates | 2026-09-16 .. 10-16, 492k satır |
| auto_paper_trades | 2026-09-05 .. 10-16, 1752 satır (son 7 gün: 145 kapalı) |
| combined_paper_trades | 2026-10-11 .. 10-15, 219 satır |
| unified_candidate_outcomes | 2026-10-14 .. 10-16, 14k satır (journal yalnız 2 gün) |
| historical_candles | 5m, 98 sembol, 2026-10-09 .. 10-16 |
| monitoring_notifications | 2026-09-16 .. 10-16 (son 7 gün: 586) |
| Binance public REST | erişilebilir (eksik mumlar çekildi) |

**Test paketi (DB ile):** 2449 geçti, 16 başarısız. Önceden DB yokluğundan kırmızı olan 26 testin 10'u geçti. Kalan 16: Binance TR adaptörünün bugünden önce de kayık `clientOrderId` sözleşme testleri (4) ve üretim kopyasındaki canlı duruma bağlı testler (2 açık otonom pozisyon, 1 pozisyon, üretim ayarları → `score_below_min`, "mock called 0 times"; 12). Bugünkü değişikliklerden kaynaklanan regresyon yok.

---

## 2. Harness Sonuçları

### 2.1 Birleşik havuz replay'i (`unified_pool_replay.py --days 7`)
`passes=true` velocity adayları (37.525), TP/SL %3/ufuk sonu, taker %0.35; ilk %60 eğitim, son %40 sınav (~2.8 gün, n=6539).

| | baseline | time_stop 15 dk / 0.3 % | time_stop 20 dk / 0.5 % |
|---|---|---|---|
| TP oranı | %27.7 | %26.6 | %27.1 |
| Ort. net %/işlem | −0.420 | −0.415 | −0.419 |
| Medyan net % | −0.35 | −0.35 | −0.35 |
| Çıkış TP/SL/ufuk/time-stop | 1809/804/3926/0 | 1742/633/2279/1885 | 1772/712/2304/1752 |
| Maker maliyetiyle | −0.17 | −0.165 | −0.169 |

Tüm günler negatif (0/5), 3-fold hepsi negatif, karar GEÇMEDİ. Birleşik (confluence) kapı 6539 işlemden yalnız 66'sını eliyor; "skortop" (üst %50 skor) daha kötü (−0.457). İşlemlerin %91'i 13 ve 15 Ekim'de yığılmış, bağımsız değil.
**Harness kusuru:** script `work/market_cache.sqlite` istiyor (yok); ajan `_load_prices`'ı Postgres `historical_candles` okuyan sarmalayıcıyla çalıştırdı. Kalıcı düzeltme gerekli.

### 2.2 Kombine paper kalibrasyonu (`calibrate_combined_paper.py --hours 168 --fetch`)
51 çıkış konfigürasyonu, walk-forward (eğitim 22.515 / sınav 15.010), komisyon %0.15 + slippage %0.025.

| Konfig (sınav) | Kazanma % | Ort. net %/işlem | t |
|---|---|---|---|
| Baseline (SL 1.0 / trig 2.0 / gap 1.0) | 33.9 | −0.277 | −19.9 |
| En iyi: SL 0.8 / trig 1.0 / gap 0.8 | 42.7 | −0.183 | −15.4 |
| time_stop_15 | 26.7 | −0.266 | −20.3 |
| time_stop_20 | 30.7 | −0.264 | −20.0 |

Karar `KEEP_DEFAULT_NO_EDGE`. Giriş taraması (`--entry-scan`): hiçbir filtre pozitif değil; skor ≥p85 −0.180, ATR ≥p70 −0.176, 30 dk kovada top-1 **−0.862** (top-N seçimi bazdan kötü) → `NO_ENTRY_EDGE`. 12 Ekim raporuyla aynı yön; baseline zararı −0.42'den −0.277'ye küçülmüş (SL 1.0 artık canlı).

### 2.3 Birleşik radar replay'i (`combined_radar_replay_24h.py`, 7 × 24 saat)
Journal'daki velocity/rising/MACD kayıtları, 1m REST mumları, auto_paper B1–B4 çıkış merdiveni, maliyet %0.35.

| Gün | combined n | TP % | Kazanma % | Ort. net % | Velocity-only ort. net (n) |
|---|---|---|---|---|---|
| 09.10 | 212 | 9.0 | 30.2 | −0.505 | −0.506 (2611) |
| 10.10 | 189 | 9.0 | 32.3 | −0.475 | −0.427 (2794) |
| 11.10 | 214 | 10.3 | 43.5 | −0.268 | −0.393 (3698) |
| 12.10 | 216 | 12.0 | 35.6 | −0.452 | −0.514 (4000, sınır) |
| 13.10 | 211 | 8.1 | 30.3 | −0.478 | −0.654 (2833) |
| 14.10 | 64 | 9.4 | 37.5 | −0.462 | −0.476 (1007) |
| 15.10 | 249 | 7.2 | 34.1 | −0.439 | −0.430 (3182) |
| **Toplam** | **1355** | **9.2** | **34.5** | **−0.437** | **−0.483 (20125)** |

Unified akış −0.444 (n=2042). Combined velocity'yi 5/7 gün geçiyor ama fark ~0.05 puan. `rising_only` her gün 0 sinyal (filtreler hepsini eliyor). **Tek pozitif alt küme:** `jump+velocity` ve `jump+rising+velocity` çakışmaları: n≈95'er, kazanma %64–66, ort. net +0.13, medyan +0.21/+0.33. Hedef/MFE oranı 1.4–1.8× (TP çoğu zaman ulaşılamaz).
**Harness kusuru (düzeltildi):** `--help` argparse'ı çökertiyordu (`%` → `%%`, satır 1405/1407/1409).

### 2.4 Portföy backtest'i (`run_portfolio_backtest.py`, 98 sembol, 5m, 10.000 TL)
**Uyarı:** Bu script 4 Eylül'de kaldırılan **BB-MFI mean-reversion** stratejisini (Pine v3) oynatıyor; canlı velocity/LLM hattını ölçmüyor. Sonuç yalnız referans.

| Metrik | Spread %0.1 | Spread %0.2 |
|---|---|---|
| İşlem | 109 | 109 |
| Kazanma | %65.1 | %60.6 |
| Net | −762 TL (−%7.62) | −910 TL (−%9.10) |
| Profit factor | 0.72 | 0.67 |
| Maks. düşüş | %13.5 | %13.9 |
| Çıkışlar (TL) | 36 TP +1127 / 8 stop −1468 / 65 sinyal −303 | 35 TP +1053 / 8 stop −1462 / 66 sinyal −375 |

8 stop (−1468 TL), 36 TP'nin toplamından (+1127) fazla. Kayıp BLUR/0G/SENT'te yoğun.
**Harness kusuru (düzeltildi):** `config.BACKTEST_ASSUMED_SPREAD_PCT` yoktu (config.py'ye eklendi, varsayılan 0.001); kaldırılmış `ACTIVE_STRATEGY`/`BB_MFI_*` değerleri script içinde `setattr` ile tamamlandı; `analyzer.calculate_bollinger_bands` → `technical_analysis._bollinger`.

### 2.5 Gerçekleşen sonuçlar ve journal (SQL + yeni analiz araçları)
**auto_paper_trades (kapalı), İstanbul saati:**

| | n | Kazanma % | Ort. pnl % | Medyan | Toplam TRY | Payoff | Başabaş için gereken kazanma % | Medyan tutma |
|---|---|---|---|---|---|---|---|---|
| 09–15 Ekim | 145 | 52.4 | −0.326 | +0.188 | −1933 | 0.665 | 60.1 | 20.4 dk |
| 02–08 Ekim | 293 | 53.4 | −0.428 | +0.497 | −2443 | 0.564 | 64.0 | 17.8 dk |

Çıkış nedenleri (bu hafta): trailing_stop n53 +1.46, take_profit n17 +2.91, stop_loss n23 **−4.32** (her seferinde tam), max_duration n25 −1.51, symbol_deactivated n27 −1.37 (kazanma %3.7). Skor 95+ kovası (n77, −0.12) 85–95'ten (n68, −0.56) iyi. İşlem başı komisyon 10.34 TL (~0.30 puan); brüt ortalama ≈ −0.03 % → **zararın neredeyse tamamı komisyon**. İşlem başı notional 1994 → 3449 TL büyümüş, TRY zararı işlem başına −8.3 → −13.3.
**combined_paper_trades:** n219, kazanma %36.1, ort. −0.314, payoff 1.27 (stop_loss n131 −1.77, trailing n80 +2.08).
**Bildirimler (7 gün):** 586 bildirim, 116 sembol; ilk 10 sembol %40; aynı sembol 60 dk içinde tekrar **%45**; 28 satırda skor >100 (eski ham ölçek artığı).
**Journal (`radar_lift_analysis --days 7`, n=14.004, yalnız 2 gün):** hit %1.6; precision@5 = 0.00, @10 = 0.10; Spearman(skor, MFE) 0.373 genel ama ufka ayrılınca 0.17–0.21 (60 dk: −0.065). Lift: macd_mtf 5.14, skor 85–95 4.35, 95–100 3.55, skor <70 **0.21**; `short_squeeze` 0.01 (n9166), `snapback` 0.00, `fusion` 0.00 → KARAR: lift<1 aileler `['short_squeeze','fusion','snapback']`. Ufuk 0 satırlar (9166, short_squeeze) hit %0.1.

---

## 3. Kesişen Sonuçlar

1. **Maliyet duvarı doğrulandı.** Beş ölçümde ortalama net −0.28 … −0.48 %/işlem; gerçekleşen brüt ≈ 0, komisyon ≈ 0.30. 15 Ekim raporunun "yapısal sınır" tespiti 7 günlük veriyle tekrarlandı.
2. **Skor sıralaması seçici değil, ama eşik olarak işe yarıyor.** Skor <70 lift 0.21, 85+ lift 3.5–4.4; gerçekleşen 95+ kovası 85–95'ten iyi. Buna karşın top-N seçimi bazdan **kötü** (−0.86) ve precision@5 sıfır. Yani "en iyi 3'ü al" stratejisi zarar büyütüyor; "70 altını at" filtresi doğru.
3. **Zaman-stop yararsız.** Üç harness'ta da fark ±0.005 puan; kazancı SL'den time-stop'a kaydırıyor, EV değişmiyor. Flag kapalı kalmalı.
4. **Çıkış asimetrisi aynı:** stop −4.32 sabit ve tam; kazançlar +1.5/+2.9. Payoff 0.67 ile %60 kazanma gerekir, gerçekleşen %52. Kalibrasyonda dar stop (0.8) + erken trailing kaybı en çok azaltıyor (−0.277 → −0.183) ama 12 Ekim'de "riskli" bulunmuştu; canlıda sıkı SL 7× kötüleşmişti. Bu çelişki aynı harness'ta kapanmadan SL değiştirilmemeli.
5. **Kesilebilir aileler:** `short_squeeze` (9166 satır, hit %0.1), `snapback`, `fusion`. `rising_only` zaten sıfır sinyal üretiyor. `jump+velocity` çakışması tek umut vaat eden sinyal (n küçük).
6. **Sinyal bağımsızlığı zayıf:** %45 tekrar, ilk 10 sembol %40, replay işlemlerinin %91'i iki günde. İstatistikler iyimser.
7. **Ölçüm altyapısı eksikleri:** journal 2 günlük; `unified_pool_replay` sqlite'a bağımlı; `run_portfolio_backtest` eski stratejiyi oynatıyor; velocity journal günde 20k satır sınırına takılıyor (09/12/13 Ekim `truncated`); 28 bildirimde ham skor sızıntısı.

---

## 4. Önerilen Aksiyonlar (kanıt sırasıyla)

1. **Hemen:** `short_squeeze`, `snapback`, `fusion` ailelerini bildirim/otonom akışından çıkar (lift<1, n büyük). Skor <70 adayları listeye alma. Bunlar DENEY_KAYDI'na satır olarak girsin.
2. **Hemen:** zaman-stop flag'i kapalı kalsın; DENEY_KAYDI'na "yararsız, 3 harness" sonucu işlensin.
3. **Harness onarımı:** `unified_pool_replay._load_prices` Postgres `historical_candles` okusun; `run_portfolio_backtest` için canlı velocity hattını oynatan bir mod ya da "BB-MFI referans" etiketi; velocity journal satır sınırını kaldır/kademeli oku; bildirim kaydında ham skor normalizasyonu.
4. **Ölçüm:** journal 14 güne ulaşınca `radar_lift_analysis` ve `radar_bucket_analysis` tekrar; `jump+velocity` çakışması için ayrı sayaç; sembol bazlı dedup flag'ini (`RADAR_NOTIFY_SYMBOL_COOLDOWN_MIN=60`) 1 hafta A/B.
5. **Ürün kararı:** brüt kenar ≈ 0 iken komisyon 0.30 → komisyon indirimi (BNB/VIP), daha uzun ufuk ya da yalnız `trend_devam` + `jump+velocity` ile seyrek sinyal. Sinyal ayarıyla pozitife geçiş yolu bu 7 günde de görünmüyor.

---

## 5. Sınırlar
- 7 gün tek rejim; ardışık sinyaller korele; t değerleri iyimser.
- Replay'ler mid-price/1m-5m mum tabanlı; gerçek spread ve derinlik yok.
- `unified_pool_replay` ajan sarmalayıcısıyla koştu (repoda düzeltme yok); `run_portfolio_backtest` canlı stratejiyi ölçmüyor.
- Journal yalnız 14–16 Ekim; kova analizi için özellik CSV'si yok.
- Ham çıktılar scratchpad'de (`backtest/{unified_pool,calibrate,portfolio,radar_replay,realized}/`), repoya alınmadı.

---

## 6. Tarama Algoritması Başarı Ölçümü ve Güncellemeler (aynı gün, öğleden sonra)

### 6.1 Onarılmış harness ile yeniden koşum
Harness onarımından sonra (`--price-source auto`: postgres 82 + REST 157 = 239/239 sembol; `--max-journal-rows 0`) sonuçlar yön değiştirmedi:

| | Dün | Bugün |
|---|---|---|
| Birleşik havuz: n / ort. net | 6539 / −0.420 | 14660 / −0.473 |
| Birleşik havuz: TP % | 27.7 | 27.5 |
| Radar replay combined: n / ort. net | 1355 / −0.437 | 1375 / −0.431 |
| Velocity-only: n / ort. net | 20125 / −0.483 | 20383 / −0.480 |
| `jump+velocity` çakışması: n / kazanma / ort. net | 95 / %66.3 / +0.129 | 97 / %66.0 / +0.153 |

Dünkü 83 sembollük örnek hafif iyimserdi; kapsam tamamlanınca EV biraz kötüleşti. Journal kesilmesi 3 günde yalnız %4–5 veri kaybettiriyormuş.

### 6.2 Aile başarısı, 7 gün (bildirimler, 5m mumla yeniden ölçüm)
586 bildirimden 279'u ölçülebildi (66 sembolün mumu yok: AMP, LUMIA, SKL, OGN, WAL, ERA gibi en çok bildirim üretenler dahil → seçilim yanlılığı). 60 dk ufuk, net proxy = TP/SL −3 %/ufuk sonu − %0.35.

| Aile | n | hit60 % [CI95] | Ort. MFE60 | Net proxy |
|---|---|---|---|---|
| velocity (tek başına) | 146 | 42.5 [35–51] | 4.60 | **−0.15** |
| velocity (tüm) | 207 | 45.4 [39–52] | 4.57 | −0.32 |
| rising | 38 | 36.8 [23–53] | 2.86 | −0.29 |
| jump | 98 | 37.8 [29–48] | 3.40 | −0.74 |
| early | 97 | 37.1 [28–47] | 3.38 | −0.77 |

| Mode | n | hit60 % | Net proxy |
|---|---|---|---|
| trend_devam | 150 | 52.7 | 0.00 |
| trend_devam + skor ≥95 | 80 | 61 [50–71] | **+0.13** |
| unified | 41 | 19.5 | — (kayıtlı hedef isabeti %3.7) |
| notr | — | — | −1.09 (stop %18) |
| v_donusu | 10 | 0 | — |

Skor kovası: 85–95 hit %35.2 (n128), 95+ %48.9 (n131); <70 %30 (n20). precision@5 = 0.47, @10 = 0.50 (taban %41; günler arası 0–1). Spearman(skor, MFE60) 0.12; Spearman(skor, net60) 0.01. Velocity adayları (16.330, kendi ufku/hedefi): 5 dk hit %17 net −0.38; 15 dk %33 / −0.36; 60 dk %42 / −0.64; skor arttıkça hit artıyor ama net kötüleşiyor (SL'ye takılma artıyor). Journal çapraz kontrolü aynı kaba sırayı veriyor (jump ≈ velocity ≈ early > rising; macd_mtf journal'da en iyi ama bildirimde ölçülemedi).

**Yorum:** velocity ve özellikle `trend_devam` tutulacak; `unified`, `notr`, `v_donusu` modları ve `short_squeeze`/`snapback`/`fusion` aileleri kesilecek; skor **taban** olarak işe yarıyor (85–95 → 95+ geçişinde hit 35 → 49), **sıralayıcı** olarak değil (P@k tabana yakın, net ile ilişki yok, 95+ kovasının çoğu tam 100). En umut veren küme `trend_devam + skor ≥95` ve replay'deki `jump+velocity` çakışması; ikisi de n<100, iki güne ve MAGIC gibi az sembole yaslanıyor.

### 6.3 Yapılan algoritma güncellemeleri (commit edildi)
| Değişiklik | Yer | Varsayılan | Kanıt |
|---|---|---|---|
| Aile kara listesi `RADAR_DISABLED_SOURCE_FAMILIES` — tüm etiketleri listedeyse `gate_candidate` bloklar, satır `blocked_by` ile kalır | monitoring.py `_family_block_reason`, unified_scan.py kombine yol | `short_squeeze,snapback` (**açık**) | short_squeeze n9166 hit %0.1 lift 0.01; snapback lift 0.00 |
| Otonom paper mod listesi `AUTO_PAPER_ALLOWED_MODES` (env) | config.py, auto_paper.py `_allowed_modes_from_config` | `trend_devam` (**açık**; eski `trend_devam,unified`) | unified hit60 %19.5 vs trend_devam %52.7 |
| Liste skor tabanı `RADAR_LIST_MIN_SCAN_SCORE` (journal `scan_score` = kalite 0-99 alanında; etkin taban max(env, kullanıcı `min_score`)) | config.py, monitoring.py `_score_floor_block_reason`, `_send_combined_list` | 0 (**kapalı**) | "<70 lift 0.21" short_squeeze ile karışık; tek kaynaklı velocity (kalite ≤66) en iyi aile → 70 tabanı onu keserdi |
| `jump+velocity` uyum bonusu `RADAR_JUMP_VELOCITY_BONUS` (kalite puanına ekleme, tavan 99) | config.py, unified_scan.py `_jump_velocity_bonus` | 0.0 (**kapalı**) | n≈97, kazanma %66, +0.15; hipotez düzeyi |

Dikkat: DB'de kayıtlı `auto_paper_settings.allowed_modes` varsa yeni varsayılanı **ezer**; canlıda tek seferlik ayar düzeltmesi gerekir. Tüm satırlar `docs/DENEY_KAYDI.md`'de; 14 gün sonra `radar_lift_analysis --days 14` ile (short_squeeze hariç) yeniden ölçüm.

### 6.4 Sonraki ölçüm adımları
1. Kara liste + mod kısıtı sonrası 14 günlük journal ile aile lift'lerini yeniden hesapla; `<70` kovası short_squeeze'siz de lift<1 ise tabanı 70 ile aç.
2. `trend_devam + skor ≥95` ve `jump+velocity` için ayrı sayaçlar; n≥300 olmadan bonus/öncelik açma.
3. Mumu olmayan 66 sembol için `historical_candles` doldurma (REST backfill) — bildirim ölçümünün yarısı bu yüzden eksik.
4. Velocity adaylarının kayıtlı `touched_target` (%50) ile mum yeniden ölçümü (%17–33) arasındaki fark araştırılmalı (pencere tanımı).

---

## 7. 30 Günlük Ölçüm (16 Eylül – 16 Ekim 2026)

**Ölçülen şey:** yükselme potansiyeli olan sembolü tespit edip bildirim gönderen sistemin isabeti (otonom işlem kârı değil). Önce 5 dakikalık mumlar 303 sembol için 30 gün geriye dolduruldu (`scripts/backfill_historical_candles.py`, 2.49 M satır, %100 kapsama, 16.5 dk). Bildirim ölçümü mum kapsamı **tam** (3597/3597).

### 7.1 Bildirim tespit sistemi: şansa karşı
"Şans" = aynı sembolde, aynı hedefle, bildirim anındaki 30 dk volatilite ve getirisi benzer rastgele anlar. hit = ufukta MFE ≥ bildirilen hedef.

| Grup | n | hit30 | hit60 [CI95] | hit120 | Med. MFE/MAE60 | Net60 proxy | Şans hit60 |
|---|---|---|---|---|---|---|---|
| Tümü | 3597 | 33.1 | **39.9** [38–42] | 47.2 | 1.99 / −2.66 | −0.57 | 28.8 |
| Tekrarsız (sembol/60 dk) | 1869 | 31.0 | 38.8 | 45.7 | 1.82 / −2.23 | −0.48 | 27.0 |
| H38 (kısmi) | 575 | 49.6 | 57.2 | 63.1 | | −0.38 | 39.2 |
| H39 | 636 | 26.3 | 33.3 | 40.6 | | −0.56 | 21.9 |
| H40 | 946 | 28.2 | 35.6 | 43.9 | | −0.69 | 25.7 |
| H41 | 1087 | 33.3 | 39.3 | 46.3 | | −0.55 | 29.8 |
| H42 (kısmi) | 353 | 30.9 | 36.8 | 45.0 | | −0.65 | 29.3 |

- Dedektör **şanstan iyi**: 60 dk isabet 11 puan üstte ve 5 haftanın 5'inde pozitif (7–18 puan). Rejim etkisi büyük (H38 %57, H39 %33).
- **Net kazanç yok:** net60 −0.57, şans tabanı −0.49. Bildirimler yükselişi haber veriyor ama −%3 stop + %0.35 maliyetle kâra çevrilemiyor.
- Gün-içi precision@5 = 0.60, @10 = 0.58 (gün tabanı %39) — 7 güne göre daha iyi; Spearman(skor, MFE60) 0.19.

### 7.2 Aile, mod, skor (hit60; şans = eşleşmiş)

| Grup | n | hit60 | Şans | Net60 |
|---|---|---|---|---|
| velocity | 1087 | **48.6** | 41.1 | −0.67 |
| global | 907 | 40.5 | 30.8 | −0.58 |
| rising | 1153 | 41.2 | 26.4 | −0.47 |
| jump / early | ~1600 | 39.4 / 39.3 | 26.8 | −0.56 |
| jump+early+rising+velocity | 227 | **59.9** | 52.8 | −0.68 |
| jump+early (yalnız) | 169 | 18.9 | 8.6 | −0.51 |
| **trend_devam** | 1021 | **53.6** | 39.4 | **−0.34** |
| global_lead_lag | 717 | 38.5 | 30.6 | −0.64 |
| unified | 1170 | 32.8 | 19.1 | −0.39 |
| notr | 406 | 41.1 | **45.9** (şansın altı) | −1.25 |
| llm_ikinci_goz | 258 | 22.1 | 19.5 | −1.00 |
| Skor <70 / 70–85 / 85–95 / 95–99.9 / 100+ | 344 / 327 / 1772 / 523 / 631 | 29.1 / 41.6 / 36.7 / 39.4 / **54.4** | 21.9 / 28.5 / 26.5 / 29.9 / 42.6 | −0.78 / −0.39 / −0.61 / −0.61 / −0.41 |

`llm_verdict` (FAKE %41 vs DEVAM %30) ve `macd_mtf` (GÜÇLÜ %37 vs etiketsiz %41) doğrulamaları isabeti **yükseltmiyor**. Saat 21–23 bandı en zayıf (%31). Skor taban olarak yalnız `trend_devam` içinde çalışıyor (95+ %62.3 vs altı %44.1, ρ 0.24); `unified`/`notr`/`llm_ikinci_goz`'da skor–MFE ilişkisi yok (unified'da 85–95, 70–85'ten kötü: %25 vs %48).

### 7.3 Güncellenmiş kapıların 30 güne geriye dönük etkisi

| Senaryo | n (pay) | hit60 | Şans | Net60 | Haftalık hit60 (H38–H42) |
|---|---|---|---|---|---|
| Orijinal | 3597 | 39.9 | 28.8 | −0.57 | 57 / 33 / 36 / 39 / 37 |
| a) short_squeeze/snapback kara listesi | 3597 (%100) | 39.9 | 28.8 | −0.57 | aynı (bu aileler bildirim üretmemiş) |
| b) mod kısıtı (unified, notr, v_donusu dışarı) | 1996 (%55) | 44.1 | 33.1 | −0.53 | 71 / 52 / 39 / 43 / 45 |
| d) b + skor ≥95 | 747 (%21) | **55.3** | 42.1 | **−0.32** | 72 / 73 / 45 / 57 / 50 |
| e) b + yalnız trend_devam | 1021 (%28) | 53.6 | 39.4 | −0.34 | 71 / 58 / 40 / 57 / 45 |

Kapılar 5 haftanın 5'inde isabeti yükseltiyor; şansa göre fark b'de değişmiyor (+8), d/e'de +11'e çıkıyor ve net60 şans tabanını (−0.64) geçiyor. Bedeli hacim: günde 116 bildirimden 24–33'e.
**Çapraz kontrol:** uygulamanın kendi etiketiyle (n=706) uyum hit60'ta %84; `HEDEFE_ULTI` etiketlilerin %99'u mumda da hit; mumda hit olanların yalnız %59'u uygulamada etiketli (uygulama kaçırıyor; `global_lead_lag` ve `llm_ikinci_goz` hiç etiketlenmiyor).

### 7.4 Replay ve kalibrasyon, 30 gün (120.876 aday, 295/295 sembol Postgres'ten)

| Ölçüm | n (sınav) | TP/Kazanma % | Ort. net %/işlem | Not |
|---|---|---|---|---|
| Birleşik havuz replay (mevcut) | 48.351 | TP 30.3 | −0.48 (medyan −0.35) | 10/10 gün, 2/2 hafta negatif; birleşik = mevcut; skortop −0.53 |
| Kalibrasyon baseline (SL 1.0/trig 2.0/gap 1.0) | 48.351 | kazanma 33.4 | −0.25 | KEEP_DEFAULT_NO_EDGE |
| En iyi: SL 0.8/trig 1.0/gap 0.8 | 48.344 | 41.4 | −0.158 | 51 konfigürasyonun hiçbiri pozitif değil |
| time_stop_15 / 20 (eğitim) | 72.525 | 28.7 / 30.8 | −0.246 / −0.245 | baseline eğitim −0.257; etkisiz |
| Giriş taraması: skor ≥p85 / ATR ≥p70 / top-1 | 11.920 / 8.859 / 378 | — | −0.138 / **−0.019** / −0.606 | NO_ENTRY_EDGE; top-N en kötü |

7 güne göre: aynı yön, daha büyük örneklemle daha kesin (t ≈ −62). ATR ≥p70 filtresi başabaşa en yakın (−0.02), tek dikkat çeken giriş özelliği.

### 7.5 30 günün özeti
1. Tespit sistemi **gerçek bir sinyal** taşıyor (şans +11 puan, her hafta), ama **kârlı değil**: brüt kenar komisyon ve −%3 stop asimetrisinin altında kalıyor.
2. Sinyali taşıyanlar `trend_devam` modu, velocity ailesi ve dört-kaynaklı çakışma; `notr` şansın altında, `unified` ve `llm_ikinci_goz` zayıf, LLM/MACD doğrulamaları katkısız.
3. Bugünkü mod kısıtı doğru yönde (5/5 hafta); `trend_devam + skor ≥95` en güçlü aday (n=747, isabet %55, net −0.32).
4. Çıkış geometrisi değişikliği ve zaman-stop 30 günde de edge üretmiyor; giriş seçicide yalnız ATR ≥p70 başabaşa yakın.
5. Ölçüm altyapısı artık 30 gün ve tam kapsama ile saniyeler içinde koşuyor (`--price-source`, Postgres mum okuması); darboğaz REST çekimiydi, paralellik değil.

**Sonraki adım önerileri:** (i) `RADAR_LIST_MIN_SCAN_SCORE`'u yalnız `trend_devam` için 95'e bağlayan mod-bazlı taban; (ii) `notr` ve `llm_ikinci_goz` modlarını bildirimden çıkar (`notr` şansın altı); (iii) giriş filtresi olarak ATR ≥p70'i replay'de A/B; (iv) uygulamanın outcome etiketlemesini `global_lead_lag` ve `llm_ikinci_goz` için de aç; (v) net kârlılık için ürün kararı (komisyon/ufuk) değişmedi.
