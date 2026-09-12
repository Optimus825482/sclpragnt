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

## 2026-09-12 kapsamlı denetim (W1–W6 TAMAMLANDI)

Çıktılar: `outputs/denetim_2026-09-12/` — `ANA_RAPOR.md` + `A…J_*.md` + `FIX_W1…W6_*.md`.
**195 bulgu** (10 KRİTİK / 44 YÜKSEK / 75 ORTA / 66 DÜŞÜK). Red-team: 10 doğrulandı, 2 kısmen, 0 reddedildi.
Test sayısı: 381 → **469/469 yeşil**.

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
