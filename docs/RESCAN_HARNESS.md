# Hız Avcısı Çevrimdışı Yeniden Tarama Harness'ı (`rescan_velocity_history.py`)

**Tarih:** 2026-10-16 · **Dal:** `feat/60g-rescan-harness`
**Kod:** `backend/app/rescan/` (saf çekirdek), `backend/scripts/rescan_velocity_history.py` (CLI),
`backend/tests/test_rescan_velocity_history.py` (15 test, parite dâhil).

## Amaç

Canlı Hız Avcısı journal'ı (`velocity_candidates`) 2026-09-16'da başlar ve `RETENTION_DAYS=30`
ile budanır. Mevcut replay'ler (`unified_pool_replay.py`, `calibrate_combined_paper.py`,
`notification_outcomes_report.py`) bu yüzden ≤30 günlük pencere ölçebiliyor. Bu harness,
**bugünkü** dedektör mantığını `historical_candles` (1m/5m/15m) üzerinde geriye dönük
çalıştırır ve 60 günlük (2026-08-17..10-16) aday satırları üretir — ağa çıkmaz, canlı
modülleri DEĞİŞTİRMEZ, yalnız saf fonksiyonlarını içe aktarır.

## Sadık olan (canlı `scan_one` ile BİREBİR)

Canlı kodun aynısı `app.rescan.scan.scan_symbol_at_tick` içinde, aynı sırayla:

| Canlı girdi | Rescan kaynağı |
|---|---|
| 1m kapanmış bar ×59 (REST limit 60, forming düşer) | `historical_candles` 1m, tick öncesi son 59 kapanmış bar |
| ATR14, ATR3, BB20 (ddof=0), RSI14 (Wilder), MFI14, LinReg20 yapısal eğim, Aroon25, MACD(12,26,9) + önceki bar MACD, ret3/ret5, hacim oranı (son/ort20), üst fitil z-skoru, M1/M3 öncü ATR | `app.technical_analysis` + `app.routers.velocity._velocity_*` fonksiyonları doğrudan içe aktarılır |
| 5m desen ×39 (G0/G1/G2 chg5/chg3/roc/ATR eşikleri), M5 MACD | `historical_candles` 5m, tick öncesi son 39 kapanmış bar, `config.VELOCITY_PATTERN_*` |
| 15m ×129: ret_8h, ADX14/+DI, ATR15m, slope15m (yalnız `adx_14` rejim kapısına girer) | `historical_candles` 15m (varsa; yoksa canlıdaki "15m çekilemedi" yolu: adx None → chop cezası ADX'e bakmadan uygulanır) |
| Kapılar: ATR profili/breakout tabanı, BB ≥ 2.5, RSI/MFI uçları, fitil tuzağı, yapısal teyit, 24s quote hacmi ≥ 1M | aynı sabitler (`VELOCITY_*`), 24s hacim 5m mumlardan |
| `velocity_score` formülü + MACD ×1.15/1.05/0.85, M5-MACD ×1.10, öncü ATR ×1.15, chop10 > 61.8 ×0.5, geç faz (24s ≥ %40) ×0.6 | aynı |
| `dynamic_target_pct(_panel_score(score), ...)` + hedef gerçekçiliği | aynı fonksiyonlar (ML/öğrenilmiş hedef hariç, aşağıda) |
| Sıralama: skor azalan, ilk 10 rank; journal tick+ufuk başına ilk 20 geçen | `rank_tick(rank_limit=10, journal_cap=20)` |
| Profil ATR eşiği (`llm_settings.velocity_min_atr_pct_5m/15m`, max_atr kelepçesi) | `--prof-atr db` (varsayılan; bugün 5m=0.10, 15m=0.10) |

**Parite kanıtı:** `tests/test_rescan_velocity_history.py::ParityTests` aynı sentetik serilerle
canlı `detect_velocity_candidates`'ı (REST/WS/DB/ML yamalı) ve rescan çekirdeğini çalıştırır;
skor, kapı, hedef, ATR/RSI/MFI/BB, desen, öncü ATR, radar bayrakları alan alan eşit olmalıdır.

## Sapmalar (yeniden üretilemeyen / nötr sayılan girdiler)

| Canlı girdi | Rescan işlemi | Etki |
|---|---|---|
| **Spread** (`market.orderflow[sym].spread_pct`, WS) | `--spread-mode known` (varsayılan): ceza yok, spread kapısı yok, hedefte `DEFAULT_ESTIMATED_SPREAD_PCT`. Ölçüm: 62 canlı adayda rescan/canlı skor oranı medyanı **tam 0.85** → canlıda anlık görüntü var, ceza uygulanmıyor. `unknown` → ×0.85 | `asiri_spread` elemesi yeniden üretilemez (rescan biraz FAZLA aday verir) |
| **Taker alış oranı** (kline 10. sütun) | `historical_candles`'ta sütun yok → canlının 9-sütun yolu gibi teyit atlanır (`radar.taker_unavailable`) | canlıda ±%5 çarpan; rescan'de yok |
| **Emir defteri dengesizliği** (bid/ask qty) | yazılmaz (0/yok) | yalnız birleşik tarama tie-break'i |
| **Mikro-yapı çarpanı** (`microflow` whale/CVD) | 1.0 | sıralama (rank) değişebilir |
| **ML tahmini** (`ml_forecast.predict_target`) | yok (`ml_pct=None`) — model bugünkü veriyle eğitildi, geçmişe sızardı | `target_pct` ML harmanı yok; `ml_dusuk_olasilik` kapısı zaten 0 eşikli |
| **Öğrenilmiş sembol hedefi** (`symbol_target_state`) | varsayılan kapalı (`--learned-target db` bugünkü anlık görüntüyü uygular) | `target_pct` harmanı |
| **24s ticker** (`priceChangePercent`, `quoteVolume`, high/low, count) | 5m mumlardan: close(j)/close(j−288)−1, 288-bar toplam/uç değerler | Binance "24s önceki ilk işlem" ile küçük fark |
| **Havuz**: `top_gainers`(30, qv ≥ 5M) + `active_movers_pool`(15, qv ≥ 2.5M, range_pos/activity) + `early_discovery`(8, WS saniyelik) + `SYMBOLS`(18) + izleme listesi `extra_symbols`(≤10) | gainer/mover/SYMBOLS aynı formüllerle 5m'den; discovery 1m bar yaklaşımı (`ret_1m ≥ 0.4`, hacim patlaması ≥ 2.0); **izleme listesi yok**; `trading_symbols` kesişimi yerine "mumu olan sembol" | ölçüldü: canlı adayların **%95.7**'si rescan havuzundaydı |
| **Tarama kadansı** (~30-60 sn, tur süresi değişken; `created_at` tur başı, veri tur içinde daha taze olabilir) | sabit ızgara `--step-min` (1 veya 5) | 5 dk: canlı adayların %89.6'sı; 1 dk: %97.0'si yeniden üretildi (aşağıda) |
| **Profil ATR eşiğinin tarihçesi** (`velocity_learning_loop` zamanla kaydırır) | bugünkü DB değeri tüm pencereye uygulanır | eşik geçmişte farklıysa aday sayısı sapar |
| Journal `volume_ratio` | canlı journal SABİT 0.0 yazar; rescan gerçek oranı yazar | bilgi kazancı |
| Geçmeyen adaylar (watchlist/warm) | yazılmaz (replay'ler `passes=true` okur) | — |
| Ek ufuklar 30m/60m | `VELOCITY_EXTRA_HORIZONS_ENABLED=false` → yalnız 5m/15m | — |

## Nasıl çalışır (performans)

1. **Faz 1 (havuz):** her sembolün 5m serisinden tick-hizalı 24s ticker aynası (numpy, kayan
   pencere), 1m'den discovery istatistiği; S×T havuz matrisi (`build_pool_matrix`).
2. **Faz 2 (tarama):** sembol başına 1m/5m/15m bir kez yüklenir; `bar_features` ile ATR14/BB20/MFI14
   vektörel hesaplanır ve `prefilter_mask` **gerekli koşul** olarak (`passes` ⊂ ön-filtre; test
   `PrefilterTests` bunu kilitler) tam taramayı yalnız aday tick'lerde çalıştırır.
3. **Sıralama/journal kuralı**, JSONL ve/veya DB yazımı, `--validate` tablosu.

Ölçüm (5 sembol, 7 gün): 1 dk adımda 9.636 tam değerlendirme 12 sn (~1,25 ms/değerlendirme).
60 gün × 303 sembol tahmini: 5 dk adım ≈ 8-10 dk; 1 dk adım ≈ 30-40 dk (havuz-tick sayısına bağlı).

## Çalıştırma

```bash
cd backend
# 60 gün, 1 dk adım (en sadık), JSONL + doğrulama
SCALPER_ADMIN_PASSWORD=x PYTHONIOENCODING=utf-8 DATABASE_URL=postgresql://... \
  ./.venv/Scripts/python.exe scripts/rescan_velocity_history.py \
  --start 2026-08-17 --end 2026-10-16 --step-min 1 --universe top-gainers-daily \
  --write none --out work/rescan_60g.jsonl --validate --validate-json work/rescan_60g_val.json

# duman testi
... --symbols PYTHTRY,RSRTRY --start 2026-10-09 --end 2026-10-16 --validate
... --max-symbols 5 ...

# DB'ye yaz (velocity_candidates, candidate_id 'rescan:%', status='rescan')
... --write db --replace
```

Bayraklar: `--universe {all,top-gainers-daily}`, `--no-discovery`, `--prof-atr {db,default,5m=0.1,15m=0.1}`,
`--spread-mode {known,unknown}`, `--learned-target {off,db}`, `--rank-limit 10`, `--journal-cap 20` (0=hepsi),
`--tol-min 5` (doğrulama eşleşme toleransı). **Analiz bayrağı** `--no-exhaustion-gate` (2026-10-17): MFI/RSI üst kapısı kapalı koşar; satırlara `exhausted`/`rsi`/`mfi` eklenir (`scripts/radar_shield_rescan_analysis.py` kullanır); canlı eşikler değişmez. 1m verisi olmayan semboller atlanır (başlıkta sayılır).

## Çıktı şekli

`velocity_candidates` ile aynı kolonlar: `candidate_id` = `rescan:{SYMBOL}:{tick_ms}:{horizon}`,
`created_at` = tick (epoch sn), `symbol, price` (tick öncesi son 1m kapanış), `target_pct, atr_pct,
volume_ratio, ret3_pct, velocity_score, passes, rank`. Ek alanlar (JSONL'de düz, DB'de
`outcome_details` JSON'unda): `horizon_minutes, mode, pool_source, change_24h, m5_pattern(_ok),
leading_ok, m1/m3_atr_prev, radar`.

DB yazımında `status='rescan'`: canlı öğrenme döngüsü yalnız `status='pending'` okur ve kalibrasyon
istatistiği `status='evaluated'` sayar → canlı kalibrasyon KİRLENMEZ. **Dikkat:** retention
(`RETENTION_DAYS=30`) `created_at < cutoff` satırları siler — 30 günden eski rescan satırları bir
sonraki budamada gider; bu yüzden JSONL ana çıktıdır, DB'ye yazıp replay'i hemen koşun.

## Replay'lere besleme

Replay'lerde `--candidates-source rescan` YOKTUR. İki yol:

1. **DB yolu:** `--write db` sonrası replay'ler `velocity_candidates WHERE passes=true` okuduğu için
   rescan satırlarını da görür; canlı satırlardan ayırmak için replay SQL'ine
   `AND candidate_id LIKE 'rescan:%'` (yalnız rescan) ya da `NOT LIKE 'rescan:%'` (yalnız canlı)
   eklemek gerekir. `unified_pool_replay.py` ufku `_velocity_horizon_from_candidate_id` ile
   `vel-5dk/15dk` önekinden okur; `rescan:` öneki için 5 döner → 15m ufku için `candidate_id`
   sonekine (`:15`) bakılmalı. `calibrate_combined_paper.py` rank/score/atr kolonlarını
   doğrudan okur (uyumlu). `notification_outcomes_report.py` `monitoring_notifications`/`signals`
   okur; velocity journal'ı doğrudan tüketmez — rescan satırları ancak sentetik bildirim
   olarak eşlenirse kullanılabilir.
2. **JSONL yolu:** `--out` dosyası satır başına aynı kolonları taşır; replay'e küçük bir
   `--candidates-jsonl` yükleyicisi eklenerek (ayrı iş) DB'ye dokunmadan beslenebilir.

## Doğrulama (2026-10-09..16, 1m verisi olan semboller)

`--validate` tablosu: gün başına canlı/rescan aday sayısı, sembol Jaccard'ı, **havuzda** (canlı adayın
sembolü o tick'te rescan havuzunda mıydı), **yeniden** (canlı adayın ±5 dk içinde aynı sembol+ufukta
rescan karşılığı), **kesinlik** (rescan adayının canlıda karşılığı), eşleşen çiftlerde skor Pearson/Spearman.

5 en aktif sembol (PYTHTRY, RSRTRY, ANIMETRY, AMPTRY, FOGOTRY), 3.094 canlı aday:

| adım | rescan aday | havuzda | yeniden | kesinlik | pearson | spearman |
|---|---|---|---|---|---|---|
| 5 dk | 996 | %95,7 | **%89,6** | %79,1 | 0,82 | 0,83 |
| 1 dk | 5.000 | %95,6 | **%97,0** | %46,3 | 0,94 | 0,89 |

Tam `created_at` anında yeniden tarama (62 rastgele canlı 5dk adayı): 56/62 (%90) `passes=True`;
kalan 6'sı fitil tuzağı/MFI ucu/yapısal teyit — canlı turun verisi `created_at`'ten 60-113 sn daha
taze olduğu için (REST tur içinde çekilir) 1 bar kayması. Skor oranı medyanı 0,85 (= spread cezası).

**Geniş küme — 1m verisi olan 129 sembol, 7 gün, 1 dk adım** (14.448 canlı aday, 108 sembol; çalışma 64 sn):

| gün | canlı | rescan | jaccard | havuzda | yeniden | kesinlik | pearson | spearman |
|---|---|---|---|---|---|---|---|---|
| 10-09 | 2809 | 3960 | 0,69 | %96,0 | %96,9 | %54,2 | 0,73 | 0,71 |
| 10-10 | 1550 | 2582 | 0,74 | %91,2 | %93,4 | %45,0 | 0,56 | 0,75 |
| 10-11 | 2372 | 3174 | 0,72 | %93,4 | %96,0 | %55,5 | 0,80 | 0,87 |
| 10-12 | 3133 | 3386 | 0,83 | %91,5 | %93,3 | %64,4 | 0,94 | 0,95 |
| 10-13 | 2085 | 3412 | 0,69 | %85,2 | %88,8 | %43,3 | 0,89 | 0,96 |
| 10-14 | 514 | 1756 | 0,56 | %88,9 | %92,0 | %21,0 | 0,84 | 0,95 |
| 10-15 | 1848 | 2682 | 0,50 | %82,4 | %87,7 | %46,5 | 0,98 | 0,95 |
| 10-16 | 137 | 1434 | 0,23 | %95,6 | %95,6 | %8,2 | 0,88 | 0,96 |
| **TOPLAM** | **14448** | **22386** | 0,83 | **%90,5** | **%93,1** | %46,7 | **0,93** | 0,85 |

Okuma: canlı adayların %93'ü rescan'de (±5 dk) karşılık buluyor; kaçanların ana nedeni havuz
(%9,5 havuz dışı: izleme listesi `extra_symbols` ve WS discovery) ve canlı turun 1 bar daha taze
verisi. "Kesinlik" %47: rescan her dakika ve spread/ML kapısız taradığı için canlıdan ~1,5× fazla
aday üretir (canlı tur ~30-60 sn ama tur süresi değişken; 10-14/10-16 günlerinde canlı kısmen
kapalıydı). Skor korelasyonu 0,93 — sıralama replay'leri için yeterli.

Çalışma süresi ölçümü: 129 sembol × 7 gün × 1 dk = 40.674 tam değerlendirme, 52 sn (faz 2) + 12 sn (faz 1).
60 gün × 303 sembol tahmini: **1 dk adım ≈ 25-35 dk**, 5 dk adım ≈ 8-10 dk (1m yükleme 2×~5 dk dâhil).

## Açık sorular

* Canlı `created_at` = tur başlangıcı; REST verisi tur içinde (≤ ~50 sn) daha taze. Rescan tick'i
  "veri anı" olarak alır; eşleşme toleransı ±5 dk bunu örter ama skor birebir eşitliği engeller.
* Profil ATR eşiği tarihçesi `llm_settings`'te tutulmuyor; 60 günlük pencere için tek değer varsayımı.
* Discovery havuzu WS saniyelik akışın 1m bar yaklaşımı; canlıdaki "pump'ın ilk saniyeleri"
  yakalaması rescan'de 1 dk gecikir.
* `--universe all` ile canlı havuz dışındaki sembollerde de aday üretilebilir (karşı-olgusal evren);
  canlıyla karşılaştırmada "kesinlik" düşer, ölçüm için ayrı etiketlenmelidir.
