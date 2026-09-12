# Scalper Agent V4 — Kalıcı Proje Notları

Kalıcı (oturumlar arası) proje kuralları ve mimari kararlar. Günlük iş kaydı için
`YYYY-MM-DD.md` dosyalarına bakın.

## Değişmez kurallar / sözleşmeler

- **Paper-only.** Tüm çalışma sanal cüzdanladır; gerçek emir yolu yoktur. Strateji
  değişiklikleri OOS kanıtı olmadan aktive edilmez.
- **Renk anlamı:** YEŞİL = kâr, KIRMIZI = zarar. `null`/`NaN` **nötr**
  (`text-bunker-muted`) — asla yeşile/kırmızıya boyanmaz.
- **Gösterge tanımları tek kanonik kaynak:** `app/technical_analysis.py`
  (`_rsi` = Wilder, `_aroon` = high/low + `period+1` pencere + **son-tekrar
  tie-break**, `_linreg_slope_pct` = 10-bar yüzde). `ml_forecast.py` ve
  `routers/velocity.py` bunları import etmeli; kendi kopyalarını üretmemeli.
- **Özellik sürümleme:** gösterge tanımı/özellik şekli değişirse
  `ml_forecast.FEATURE_VERSION` artırılır (bayat artifact'lar geçersiz olsun).
- **Geç bağlama:** router→main fonksiyon bağlama **yalnızca**
  `app/runtime_deps.py` üzerinden (`pending_dep` + `bind`). `startup_services()`
  ilk satırı `runtime_deps.assert_ready()`. Router global'leri monkeypatch
  EDİLMEZ.
- **Okuma yolu saftır:** `database.load_*` / `get_*` DB'ye yazmaz. Tek seferlik
  backfill işleri ayrı fonksiyon + `init_db()` çağrısı (ör.
  `backfill_position_trade_ids`).
- **Birim sözleşmesi:** dışa açılan `*_pct` alanları **yüzde**, iç hesap **kesir**
  (`_ratio_from_pct`).
- **Düzenleme kuralı (ZORUNLU):** aynı dosyaya **paralel** birden çok düzenleme
  GÖNDERME. Edit read-modify-write yapar → son yazan öncekini ezer ve düzenlemeler
  **sessizce kaybolur** (belirti: `grep` eski metni göstermeye devam eder). Bir dosyada
  birden çok değişiklik gerekiyorsa **tek atomik script** kullan: her `(old,new)` için
  dosyada tam **1 eşleşme** zorunlu, hepsi doğrulanmadan **hiçbir dosya yazılmaz**.
  Örnek: `outputs/denetim_2026-09-12/scratch/apply_w5_residual.py`. Düzenleme sonrası
  her değişikliği `grep -c` ile **doğrula**.
- **`next build` doğrulaması:** sandbox'ın node shim'i Next.js'in `.next` ara dosyalarını
  silmesini engeller (`SAFE_DELETE_BULK_CONFIRM_REQUIRED`) — bu **kod hatası DEĞİLDİR**.
  Önce `.next`'i sil (gitignore'lu, yeniden üretilebilir), sonra derle. `tsc --noEmit`
  tek başına yetmez (server/client sınırı hatalarını yakalamaz).

## Aktif otonom döngüler

- `routers/velocity.py::autonomous_velocity_loop` — **AKTİF** (2026-09-10,
  kullanıcı kararı). `main.py::startup_services()` içinde
  `_start_background(autonomous_velocity_loop, "velocity-autonomous")`.
  Çift kilit: `VELOCITY_AUTO_ENABLED` (env=.env'de true) **ve**
  `llm_paper_trade_enabled` (DB=1) — ikisi de açık olmalı. Kapı her turda
  yeniden okunur → ayar değişimi restart gerektirmez. Paper-only.
  Kapatma: env'i false yap **veya** DB ayarını 0 yap.
  `/api/velocity/status` → `auto_enabled` (ayar) ve `loop_running` (fiilen
  başlatıldı mı) ayrı raporlanır.
- Kablolama koruması: `tests/test_loop_wiring.py` (W6'da YENİDEN YAZILDI) — `app/`
  altındaki her `*_loop` tanımı ya `_start_background(<ad>…)` ile **gerçekten**
  başlatılmalı ya da modülünde `create_task(<ad>(…))` olmalı. **Import/isim geçişi
  SAYILMAZ** (eski sürüm `re.search(name, main_src)` ile import bloğuna takılıyordu →
  kapsam 1/29, boşa çalışıyordu). Yeni denetim `_START_BG_RE` / `_CREATE_TASK_RE`
  kullanır ve girintili tanımları da görür. Mutasyonla doğrulandı: bir
  `_start_background(...)` satırı silinince test KIRILIR. Yeni döngü eklerken bu test
  kırılırsa wiring unutulmuş demektir.

## Bilinçli olarak bağlanmamış kancalar (çağıranı yok, silinmedi)

- `routers/runtime.py::invalidate_wallet_caches` (TTL=3sn olduğu için bayatlık
  sınırlı), `_ma_cascade_observation_context`,
  `routers/maintenance.py::_persist_replay_parity_observation` — işaretlendi.

## 2026-09-12 kapsamlı denetim (W1–W8 TAMAMLANDI — 10/10 KRİTİK kapandı)

Çıktılar: `outputs/denetim_2026-09-12/` — `ANA_RAPOR.md` + `A…J_*.md` + `FIX_W1…W8_*.md`.
**195 bulgu** (10 KRİTİK / 44 YÜKSEK / 75 ORTA / 66 DÜŞÜK). Red-team: 10 doğrulandı, 2 kısmen, 0 reddedildi.
Test sayısı: 381 → 416 → 442 → 465 → 475 → **493/493 yeşil** (ölçüldü).

**10 KRİTİK bulgu ve kapanış yeri:**
`ML-01` (W3) · `D-01` (W2) · `F-02` (W4) · `G-01` (Parti 1) · `C-01`/`C-02` (W1) ·
`H-01`/`H-02` (W5) · **`V-01` (W7)** · **`B-01`/`B-02` (W8)**.

> **Ders (kalıcı):** W1–W6 bittiğinde "hepsi kapandı" varsayıldı ama `V-01` ve `B-01`/`B-02`
> **hiçbir partiye atanmamıştı**; `B_*` alt sisteminin tamamı (20 bulgu) hiçbir rapora girmemişti.
> **Düzeltme planına değil, BULGU LİSTESİNE güven** — parti sonunda ID bazında "kalan var mı?" tara.

**Uygulanan partiler:**
- **W1/W2** — göstergeler + işlem/risk (`FIX_W1_gostergeler.md`, `FIX_W2_islem_risk.md`).
- **W3** — ML/velocity eğitim-çıkarım uyumu (ML-01, ML-02, ML-09, I-05, I-01, I-02, D-04).
  Ayrıca **üretim regresyonu**: I-05 katı doğrulaması `training_bar_minutes` alanı olmayan
  mevcut artifact'ı reddetti → 503. Düzeltme: alan **varsa** doğrulanır, yoksa legacy kabul.
- **W4** — gözlem/kanıt bütünlüğü (F-02, F-01, TAH-02) → aşağıya bkz.
- **W5** — frontend net esas + `null` renk sözleşmesi (H-01/H-02/H-03) → aşağıya bkz.
- **W6** — kablolama koruması + para matematiği testleri (G-02, I-08) → aşağıya bkz.
- **Parti 1:** G-01, G-06, G-08, G-07, G-03/04.

- **Ölü araştırma düğmesi YOK:** 3 "ölü" düğme `backend\work\` betikleri tarafından okunuyor → CANLI.
  Gerçekten ölü sembol sayısı: **0** (204 aday tarandı).
- Operasyonel: `pytest` özet satırı yazdırmıyor, çıkışta `couldn't stop thread 'pool-1-worker-N'`
  → zararsız psycopg havuzu teardown gürültüsü (kapatılmayan `ThreadPoolExecutor`).

## Para matematiği & ölçüm katmanı — kilitli sözleşmeler

- **Açık pozisyon net K/Z TEK KAYNAK:** `frontend/app/lib/pnl.ts`. Kanonik kural backend
  `config.min_net_exit_pct` ile aynı: `net = brüt − commission_pct × q × (giriş + çıkış)`
  (**iki bacak**; yalnız giriş bacağı D-01'in kök hatasıydı). Girdi eksikse **`null`** (0 DEĞİL).
  Tüketiciler: `portfolio`, `page`, `charts`. Komisyon oranı WS `portfolio.commission_pct`
  + `GET /api/config` ile yayınlanır → `applyCommissionPct` (geçersiz değeri yok sayar).
- **Backend `pnl_try` bilinçli olarak YALNIZ giriş bacağını düşer** (`main.py:1677-1680`,
  `runtime.py:152-155`) — muhasebe/`reconciliation`/`unrealized_pnl` doğru kalsın diye.
  Görüntü tek esasa çekildi; **muhasebe tarafı DEĞİŞTİRİLMEDİ.** İkisini eşitlemek
  `min_net_exit_pct`'i yayınlamayı + reconciliation'ı yeniden doğrulamayı gerektirir → açık iş.
- **MACD kanıt ileri getirisi (F-02):** `database.py::_macd_forward_outcomes(rows, base, t0_ms, now_ms)`
  saf fonksiyon. Bir ufuk ancak hedefi **kapsayan KAPANMIŞ** 5m bar varsa mühürlenir
  (`stamp + _MACD_BAR_MS >= target` **ve** `<= now_ms`); yoksa `NULL` kalır, sonraki turda dolar.
  `_MACD_BAR_MS = 5*60_000`.
- **MACD hayalet alarm kapısı (F-01):** trend gücü evren-içi min-max ile normalize edilir →
  tek sembol evrenden çıkınca diğerleri zıplar. Alarm artık `_stable_range` (p5–p95,
  `_STABLE_RANGE_PCTL=5.0`; `n<20` → min/max) **ve** `_own_activity_changed` kapısından geçer.
  Ekrandaki `strength` evren min-max **kaldı** (gösterge tanımı değişmedi).
- **Tahmin isabet penceresi (TAH-02):** tek kaynak `forecast_learning.py` —
  `effective_hit_grace_minutes = min(grace, horizon)`, `outcome_window_seconds = (h + grace)*60`.
  Tolerans ufku AŞAMAZ (5m tahmin 19. dk'da "isabet" sayılamaz). Belirlenimci; tarama
  gecikmesinden bağımsız. Tüketiciler: `database.py:2106/2349`, `llm_chat.py:362`.
- **`min_net_exit_pct` `0` davranışı:** `float(order_value or DEFAULT_ORDER_TRY)` → `0` değeri
  varsayılan emir proxy'sini devreye sokar. **Risk kapısı; sessizce değiştirme** — davranış
  kilitli (`test_w6_money_math.py`).
- **Cüzdan mutabakatı TEK KAYNAK (V-01):** `database._portfolio_reconcile_figures(conn, cutoff)`
  → `(realized_pnl, main_open_cost, auto_open_cost)`. `virtual_wallet` TRY satırı **iki defter
  tarafından paylaşılır**: ana (`trades`/`positions`) + otonom (`auto_paper_trades`).
  `reconcile_portfolio` (apply) **ve** `preview_portfolio_reconcile` **ve** `init_db` açılış
  mutabakatı bu yardımcıyı/aynı formülü kullanmak ZORUNDA. Preview'in kendi SQL'ini kurması
  V-01'in kök hatasıydı (iki adımlı onayda admin yanlış bakiyeyi onaylıyordu).
  Yeni bir bacak eklersen **üçünü birlikte** güncelle.

## Piyasa verisi & WebSocket — kilitli sözleşmeler (W8)

- **REST klines'ın SON satırı AÇIK mumdur.** Önbelleğe yazmadan önce **her zaman**
  `market._closed_history(rows, tf, now_ms)` kullan — açık barı atar ve `timestamps` /
  `last_closed_at_ms` alanlarını yazar. Elle `{"opens":…,"closes":…}` kurmak yasak:
  `last_closed_at_ms` yazılmazsa `kline_freshness` `age=inf` → sembol **kalıcı fail-closed**
  (B-02). Kanonik örnek: `routers/runtime.py:920`.
- **WS nesil döngüsü (B-01):** 24s ömür dalında `ws_connected_at` **sıfırlanmadan**
  `reconnect_requested` set edilirse her nesil yeniden tetiklenir → saniyede binlerce yarım
  bağlantı (ölçüldü ~11.900/sn). Watcher'da bayrak **sleep'ten SONRA** kontrol edilir
  (min-dwell) ve nesiller arası `WS_GENERATION_MIN_INTERVAL_SEC` beklenir.
- **WS URL her denemede yeniden kurulur (B-03):** `_ws_url_for(base, symbols, timeframes)`;
  donmuş `plan["url"]` kullanmak yedek host'a geçişi fiilen öldürür. Backoff:
  `_ws_backoff_sec(attempt)` (üstel + jitter, 30 sn tavan) — sabit `sleep(2)` yasak.
- **Çerçeve başına koruma (B-05):** WS mesajları `_handle_ws_frame()` üzerinden işlenir;
  tek bozuk çerçeve dıştaki `except`'e sızıp **tüm grup soketini** düşürmemeli.
- **Arka plan görevleri güçlü referansla tutulur (B-06):** `_schedule_repair()` →
  `self._bg_tasks` + `add_done_callback`. Çıplak `create_task(...)` GC'ye kurban gidebilir
  ve istisnası görünmez.
- **Ticker istekleri dilimlenir (B-04):** `_ticker_paged()` 50'lik partilerle çeker ve
  **birleştirir**; `_ticker_params` **dilimlemez**. `ticker_24h` **merge** edilir
  (`.update`), **replace** edilmez — aksi halde bu turda dönmeyen sembol hacmini kaybedip
  likidite kapısında **sessizce** kilitlenir.

## ARAÇ KURALI — Git Bash ters bölü bozar

`python - <<'EOF'` veya `python -c "..."` ile **satır içi** betik verirken Git Bash ters
bölüleri bozar (`\n` → `/n`) ve `str.count()` sessizce **0** döndürür → betik hiçbir şey
yapmaz, testler "yeşil" görünür (yanlış güven). **Ters bölü/newline içeren betikleri Write
aracıyla dosyaya yaz, sonra çalıştır.**

## Komutlar

- Backend test: `backend/venv/Scripts/python.exe -m pytest tests/ -q`
- Tip denetimi: `frontend` içinde `npx tsc --noEmit`
- Derleme kontrolü: `python -m py_compile <dosyalar>`

## MACD MONITOR — bilinen tasarım özellikleri / açık kararlar

Denetim raporu: `outputs/macd_monitor_denetim_raporu.md` (2026-09-10). Modül:
`routers/macd_monitor.py` (döngü + `GET /api/macd-monitor` + ayar ucu), beslediği paneller:
`/macd-monitor` ve `/monitoring` (YÜKSELİŞ EĞİLİMİ ADAYLARI, SIRÇRAMA ADAYLARI).

- **Trend gücü göreceli ve yönsüzdür ve bu KANITLA DOĞRUDUR.** `strength` 0-10, evren-içi min-max ile
  normalize edilir (`_strength_meta`) ve hız `abs(slope)/bar_aralığı` olduğundan **yön içermez**.
  OOS/replay (312 sembol · 571.980 gözlem) yönlü formülün bu evrende **contrarian** olduğunu gösterdi
  (IC −0.049, t −23.8 @30m) → yön skora EKLENMEZ. `dir` alanı yalnızca tanımlayıcıdır, skora girmez.
  `monitoring/page.tsx` `RISING_MIN_STRENGTH=9.8` "evren maksimumu"nu seçer; bu davranış korundu.
- **Tazelik (C1 ile düzeltildi):** M3/M30 serileri WS aboneliğinde değildir, `market.refresh_series()`
  ile REST'ten tazelenir (3m≈75sn, 30m≈1860sn). Artık tazelenen `(sym,tf)` hücreleri fiyat değişmese
  de yeniden hesaplanır (`refreshed` kümesi + `_bar_marker` yeni-bar kapısı).
- **Alarm cooldown'ları ayrıdır:** jump (`_jump_alerted_at`) ve erken (`_early_alerted_at`),
  ikisi de 30 dk sabitini kullanır ama birbirini bloke etmez.
- **Kanıt katmanı VAR (C3):** `macd_monitor_alerts` tablosu; her alarm sinyal imzası + fiyatla kaydedilir,
  5m/15m/30m ileri getirisi doldurulur (`macd_evidence_loop`, ~2 dk). `GET /api/macd-monitor/alerts`.
  UI: MACD MONITOR sayfasında "ALARM GEÇMİŞİ & İSABET" paneli. **Eşik/ağırlık ayarı yalnızca bu
  kanıtla yapılır** — sezgiyle veya kısmi modellerle DEĞİL.
- **Performans:** `_trend_cache` (B8) değişmeyen sembolde trend/sinyal hesabını atlar;
  `macd_monitor_delta` WS mesajı (B9) yalnız değişen sembolleri yayınlar, her 5. pass'ta tam yayın.
- **MACD snapshot'ın İKİ tüketicisi vardır:** `/macd-monitor` ve `/monitoring` (YÜKSELİŞ/SIRÇAAMA panelleri).
  Yeni bir WS mesaj tipi eklerken **ikisini de** güncelle — B9'da yalnız biri güncellendiği için
  `/monitoring` sessizce ~1 sn → ~5 sn'ye yavaşladı. Birleştirme tek kaynaktan:
  `frontend/app/lib/macdSnapshot.ts` → `mergeMacdDelta`.
- **Kararlar (2026-09-10, kullanıcı onayı):** C1/C3 uygulandı; C2 kanıt sonrası → yön eklenmedi,
  eşik/ağırlık DEĞİŞMEDİ; B6 histerezis + B8/B9 uygulandı. Kanıt: `outputs/macd_monitor_replay_kanit.md`.

## Dikkat

- Araştırma betikleri (`backend/scripts`, `backend/work`) **silinmez** — kullanıcının
  kanıta dayalı araştırma araçlarıdır ve korunur.

- **ML eğitim/çıkarım bar dayanağı (W3):** `ml_forecast.TRAINING_BAR_MINUTES=5`;
  çıkarım (`velocity`, `chart_forecast`) 5m KAPANIŞ barlardan özellik üretmeli
  (`inference_bar_minutes`), warmup yoksa ML tahminini atla (1m tahmin YASAK).
  `prepare_journal_samples` 6'lı dönüş (son: karar zaman damgası ms); `train()`
  kronolojik holdout (journal_ts <= times[split-1]).

## Piyasa verisi & adaptörler — kilitli sözleşmeler (W8/W9/W10)

- **`_interval_ms` KATIDIR** (`market_data`): `re.fullmatch(r"(\d+)([smhdwM])")`,
  bilinmeyen aralıkta `ValueError`. `M` = 1 ay (2.592.000.000 ms), `m` = 1 dk —
  büyük/küçük harf AYIRT EDİCİ. Sessiz 60 sn varsayılanı YASAK.
- **`kline_freshness` toleransı = bar aralığı + pay**, serinin `source`'una göre:
  WS ile beslenen → 15 sn; REST ile tazelenen (3m/30m) → 120 sn. `interval*2+30` YASAK.
- **`market_data.trade_flow` KAYAN penceredir** (1 sn'lik kovalar). Düz sayaçlar
  (`buy_qty`…`whale_sells`) korunur çünkü `macd_monitor._symbol_cvd` onları DOĞRUDAN okur.
  `window_start` = en eski tutulan kovanın saniyesi. Tumbling reset YASAK.
  Yanıt ufuk etiketleri: `window_elapsed_sec`, `tape_trades`, `tape_horizon`.
- **`microflow._aggregate_5s` kovayı `opened_at_ms // 5000 * 5000` ile hizalar**;
  eksik 1s bar içeren kova ATILIR (uydurma bar üretilmez).
- **`MicroFlow.start()` sembol değişiminde tahliye eder** (`_evict`): `bars`,
  `trade_flow`, `depth`+`depth_updated_at`. Aynı sembolün yeniden başlatılması sıcak durumu korur.
- **Public REST: tek paylaşılan semafor** (`REST_MAX_CONCURRENCY=8`, `threading.Semaphore`)
  + sunucu metriğine dayalı gaz kelebeği (`REST_WEIGHT_SOFT_LIMIT=4500`, doğrulanmadı).
  Çağrı noktaları KENDİ semaforunu kurmamalı.
- **Yeniden deneme politikası (public+private):** geçici = 429/5xx/418 + bozuk gövde;
  418 uzun geri çekilme (30→120 sn). **`code != 0` iş hatası DENENMEZ.**
- **Private: `timestamp` sunucu saati ofsetiyle** düzeltilir (`/open/v1/time`, 300 sn TTL).
  `_fmt_quantity(q, step_size)` lot adımına AŞAĞI yuvarlar; `place_market_sell` adımı
  yalnız YÜKLÜ filtre önbelleğinden okur (satış yoluna yeni ağ bağımlılığı eklenmez).
  `_load_symbol_list` tek uçuştur (`_symbols_load_lock`).
- **B-17 (bilinçli):** MicroFlow kendi `aggTrade` soketini açar; `MarketData` ile
  birleştirilMEZ (velocity havuzu ana evrenin üst kümesidir, `kline_1s` MarketData'da yok,
  grup soketi düşerse körlük riski). İki besleme BAĞIMSIZ; `agg_feed` alanı kimliği bildirir.
- **`universe_at()` tüketilir:** `GET /api/research/universe-at?ts=` (salt okunur).
  En büyük `ts <= hedef` kaydını seçer. `_MAX_ENTRIES=2000` saat ≈ **83 gün**.
