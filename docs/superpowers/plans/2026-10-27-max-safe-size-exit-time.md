# Maksimum Güvenli Tutar + Tahmini Süre / Çıkış Zamanı — Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Her yükseliş bildirimine (radar, yükseliş, MA BUY) donmuş bir "işlem planı" (maks. güvenli tutar, net %3 brüt hedef, stop, tahmini süre, çıkış saati) eklemek; push, uygulama içi bildirim, alım diyaloğu ve otonom paper'ın hepsi bu planı kullanır; gerçek pozisyonlara çıkış zamanında yalnız push gönderilir.

**Architecture:** Saf hesap modülleri (`trade_size.py` defter→tutar, `signal_eta.py` geçmiş→süre istatistiği) + tek bir plan kurucu (`notification_plan.py`) bildirim anında planı hesaplar, `notification_trade_plans` tablosunda `notification_key` ile dondurur ve zarfa `trade_plan` olarak ekler. Üç bildirim kurucusu, auto_paper, gerçek alım (`open_position`) ve frontend planı bu tek kaynaktan okur. Süre istatistikleri arka plan döngüsüyle (günde bir) 1m mumlardan hesaplanır.

**Tech Stack:** Python 3 / FastAPI / PostgreSQL (psycopg, SQL migration'lar), pytest; Next.js + TypeScript, vitest.

**Spec:** `docs/superpowers/specs/2026-10-27-max-safe-size-exit-time-design.md`

## Global Constraints

- Net hedef sabiti: `PLAN_NET_TARGET_PCT = 3.0`.
- Maks. tutar = min(giriş: ask süpürmesinde ortalama kayma ≤ **%0,2**; çıkış: best bid'den −**%1** içindeki bid toplamı × **0,4**; hacim: 24s TRY hacminin **%2**'si). Gösterimde 1.000 TL'ye aşağı yuvarlanır.
- Brüt hedef % = 3,0 + giriş kayması % + çıkış kayması % + 2 × `config.effective_commission_pct()` × 100. Sinyalin kendi hedefi daha büyükse sinyalinki.
- Brüt hedef > **%8** veya tutar < `config.MIN_PARTIAL_ORDER_TRY` → `warnings` içine `"hedef_gercekci_degil"`.
- ETA eşikleri (brüt %): `(3.6, 5.0, 8.0, 10.0)`; plan, brüt hedefe eşit/büyük en küçük eşiği kullanır (10'u aşarsa 10).
- Tahmini süre = P50, çıkış zamanı = başlangıç + P75 dk, ek süre = bir P75 daha.
- Stop % = kazananların hedef-öncesi MAE P80'i, `[2.0, 10.0]` aralığına kırpılır.
- Kova < **30** örnek → `eta_minutes`, `exit_at`, `stop_pct` = `None`, `warnings` içine `"veri_yetersiz"`.
- Geçmiş: son **60 gün**, yalnız push'u gitmiş sinyaller; replay penceresi **24 saat**, 1m mum.
- Plan hesaplaması bildirim yolunda **2 sn** zaman aşımlı; aşılır/hata olursa bildirim plansız (`trade_plan=None`) gider.
- Kovalar: radar → `"radar"`; yükseliş → `f"rising:{kind}"`; MA BUY → `f"ma_buy:{timeframe}"`.
- Profil kuralı (kullanıcı kararı): sinyal hedefi brüt hedeften büyükse sinyal hedefi + profilin stop/trailing/tutma süresi kalır (`plan["profile_exit"] = True`).
- Gerçek hesapta hiçbir yeni kod emir GÖNDERMEZ (yalnız push).
- **Commit yok:** kullanıcı commit/deploy'u kendisi yapar; her görev değişiklikleri commit'lemeden bırakır.
- Testler: `cd backend && python -m pytest <dosya> -v` (yalnız `-q` özet satırını gizliyor); frontend `cd frontend && npx vitest run <dosya>`.

## Review Focus

1. Boş/tek taraflı emir defteri (asks veya bids boş, 24s hacim 0) → tutar 0 ve `"hedef_gercekci_degil"`, istisna yok. → Task 1 testi.
2. Binance TR REST depth zaman aşımı/429 → bildirim yine gider, `trade_plan` None. → Task 4 testi.
3. Aynı `notification_key` iki kez (yeniden başlatma/çift tur) → ilk dondurulan plan korunur, üzerine yazılmaz. → Task 4 testi.
4. Kullanıcı gerçek pozisyonu elle sattı (coin bakiyesi < alınan miktarın %50'si) → çıkış push'u gitmez. → Task 7 testi.
5. Push URL'sinde `key` var ama plan bulunamadı (eski bildirim) → diyalog bugünkü davranışla (bakiye %25, boş SL/TP) açılır. → Task 8 testi.

---

### Task 1: Defterden maksimum güvenli tutar (saf)

**Files:**
- Create: `backend/app/trade_size.py`
- Test: `backend/tests/test_trade_size.py`

**Interfaces:**
- Produces:
  - `sweep(asks: list[tuple[float, float]], amount_try: float) -> dict` → `{"filled_try", "qty", "avg_price", "avg_slip_pct", "last_price"}` (avg_slip_pct = (avg/best−1)×100).
  - `max_safe_amount(asks, bids, quote_volume_try: float, *, max_avg_slip_pct=0.2, bid_band_pct=1.0, bid_haircut=0.4, volume_share=0.02) -> dict` → `{"amount_try", "limits": {"entry", "exit", "volume"}, "binding": str, "entry_slip_pct", "exit_slip_pct"}`; `exit_slip_pct` = aynı tutarın bids üzerinde satışla süpürülmesindeki ortalama kayma (pozitif sayı).
  - `gross_target_pct(net_pct: float, entry_slip_pct: float, exit_slip_pct: float, fee_frac: float) -> float`.
  - Fiyat/miktar girişleri Binance depth string çiftleri olabilir; `parse_levels(raw: list) -> list[tuple[float,float]]`.

- [ ] **Step 1: Failing testler**

```python
ASKS = [(6.000, 342.8), (6.001, 1175.7), (6.004, 3211.5), (6.005, 4488.0)]
BIDS = [(5.992, 3696.8), (5.991, 500.0), (5.989, 2521.1)]

def test_sweep_avg_slip():
    r = trade_size.sweep(ASKS, 10_000)
    assert r["last_price"] == 6.004
    assert 0 < r["avg_slip_pct"] < 0.07

def test_volume_limit_binds():
    r = trade_size.max_safe_amount(ASKS, BIDS, quote_volume_try=500_000)
    assert r["binding"] == "volume" and r["amount_try"] == pytest.approx(10_000)

def test_exit_limit_uses_haircut():
    bids_try = sum(p * q for p, q in BIDS)
    r = trade_size.max_safe_amount(ASKS, BIDS, quote_volume_try=1e12)
    assert r["limits"]["exit"] == pytest.approx(bids_try * 0.4)

def test_empty_book_is_zero():
    r = trade_size.max_safe_amount([], [], quote_volume_try=0)
    assert r["amount_try"] == 0

def test_gross_target():
    assert trade_size.gross_target_pct(3.0, 0.1, 0.2, 0.001125) == pytest.approx(3.525)

def test_parse_levels_strings():
    assert trade_size.parse_levels([["6.0", "1.5"]]) == [(6.0, 1.5)]
```

- [ ] **Step 2:** `python -m pytest tests/test_trade_size.py -v` → FAIL (modül yok).
- [ ] **Step 3:** `trade_size.py`'yi yaz. Giriş limiti: ask kümülatif TRY üzerinde, ortalama kaymanın ≤ eşik kaldığı en büyük tutar (kademe içinde doğrusal arama yeterli; kademe sınırında eşik aşılıyorsa o kademede kısmi tutar). Kitap bitmişse ve eşik aşılmadıysa giriş limiti = kitabın tamamı.
- [ ] **Step 4:** Aynı komut → PASS.

---

### Task 2: Geçmiş sinyallerden süre/stop istatistiği

**Files:**
- Create: `backend/migrations/030_signal_eta.sql`
- Create: `backend/app/signal_eta.py`
- Modify: `backend/app/database.py` (yeni sorgu yardımcıları), `backend/app/main.py` (döngü başlatma, mevcut `notification_outcome_loop` başlatıldığı yerin yanına)
- Test: `backend/tests/test_signal_eta.py`

**Interfaces:**
- Migration 030 (yalnız ekleme, idempotent, 029'un başlık yorumu stilinde):
  - `signal_eta_samples(source_kind TEXT, ref_id BIGINT, bucket TEXT, symbol TEXT, signal_ts DOUBLE PRECISION, entry_price DOUBLE PRECISION, hits JSONB, mae_before JSONB, measured_at DOUBLE PRECISION, PRIMARY KEY(source_kind, ref_id))` — `hits` = `{"3.6": dakika|null, ...}`, `mae_before` = `{"3.6": negatif % | null, ...}` (hedefe kadar en kötü düşüş).
  - `signal_eta_stats(bucket TEXT, threshold DOUBLE PRECISION, n INT, hit_rate DOUBLE PRECISION, p50_min DOUBLE PRECISION, p75_min DOUBLE PRECISION, mae_p80_pct DOUBLE PRECISION, updated_at DOUBLE PRECISION, PRIMARY KEY(bucket, threshold))`.
  - `notification_trade_plans(notification_key TEXT PRIMARY KEY, symbol TEXT NOT NULL, bucket TEXT, plan JSONB NOT NULL, created_at DOUBLE PRECISION NOT NULL)` (Task 4 kullanır; şema tek migration'da).
- Produces (`signal_eta.py`):
  - `THRESHOLDS = (3.6, 5.0, 8.0, 10.0)`, `MIN_SAMPLES = 30`, `LOOKBACK_DAYS = 60`, `WINDOW_MIN = 1440`.
  - `first_hits(candles: list, entry: float, thresholds=THRESHOLDS) -> tuple[dict, dict]` → (hits, mae_before); mumlar Binance kline listesi `[open_ms, o, h, l, c, ...]`; dakika = mum indeksi + 1.
  - `bucket_stats(samples: list[dict], threshold: float) -> dict | None` → `{"n","hit_rate","p50_min","p75_min","mae_p80_pct"}` (MAE yalnız kazananlardan, pozitif % olarak); n < MIN_SAMPLES → None.
  - `bucket_for(source_kind: str, row: dict) -> str` (Global Constraints'teki kova kuralı).
  - `async get_stats(bucket: str, gross_target_pct: float) -> dict | None` (eşik seçimi kuralıyla tek satır okur; önbellek 10 dk).
  - `async eta_loop() -> None`: günde bir; üç kaynaktan (radar `monitoring_notifications` push'u gitmiş; `rising_alerts`; `ma_buy_signals` `push_ok`) son 60 günün ölçülmemiş ve penceresi dolmuş satırları için `binance_tr_public.klines(sym, "1m", limit=1000, start_time_ms=...)` ×2 çağrıyla 1440 mum çekip örnek yazar, sonra tüm kovaların istatistiğini yeniden hesaplar. Tur başına örnek sınırı config `SIGNAL_ETA_BATCH` (varsayılan 200).

- [ ] **Step 1: Failing testler**

```python
def _c(i, h, l):  # 1m mum
    return [i * 60_000, 1.0, h, l, 1.0]

def test_first_hits_minutes_and_mae():
    candles = [_c(0, 1.01, 0.97), _c(1, 1.04, 0.99), _c(2, 1.06, 1.0)]
    hits, mae = signal_eta.first_hits(candles, 1.0, (3.6, 5.0, 8.0))
    assert hits == {"3.6": 2, "5.0": 3, "8.0": None}
    assert mae["3.6"] == pytest.approx(-3.0)

def test_bucket_stats_needs_30():
    s = [{"hits": {"3.6": 10}, "mae_before": {"3.6": -1.0}}] * 29
    assert signal_eta.bucket_stats(s, 3.6) is None

def test_bucket_stats_percentiles():
    s = ([{"hits": {"3.6": m}, "mae_before": {"3.6": -m / 10}} for m in range(1, 31)]
         + [{"hits": {"3.6": None}, "mae_before": {"3.6": None}}] * 10)
    r = signal_eta.bucket_stats(s, 3.6)
    assert r["n"] == 40 and r["hit_rate"] == pytest.approx(0.75)
    assert r["p50_min"] == pytest.approx(15.5) and r["mae_p80_pct"] > 0

def test_bucket_for():
    assert signal_eta.bucket_for("rising", {"kind": "erken"}) == "rising:erken"
    assert signal_eta.bucket_for("ma_buy", {"timeframe": "4h"}) == "ma_buy:4h"
```

- [ ] **Step 2:** `python -m pytest tests/test_signal_eta.py -v` → FAIL.
- [ ] **Step 3:** Migration + `signal_eta.py` + database yardımcıları (`insert_eta_samples`, `list_eta_samples(bucket, since_ts)`, `upsert_eta_stats`, `get_eta_stats(bucket, threshold)`, `list_unmeasured_signals(kind, since_ts, until_ts, limit)`) + `main.py` döngü başlatma. Persentil: `statistics.quantiles(..., n=100, method="inclusive")` yerine doğrusal enterpolasyonlu `numpy.percentile` (projede numpy var).
- [ ] **Step 4:** Aynı komut → PASS. Ek: `python -m pytest tests/test_database_purity.py -v` (migration keşfi bozulmadı) → PASS.

---

### Task 3: Plan kurucu + süre-dolarsa kuralı + mesaj metni

**Files:**
- Create: `backend/app/notification_plan.py`
- Test: `backend/tests/test_notification_plan.py`

**Interfaces:**
- Consumes: Task 1 `max_safe_amount`, `gross_target_pct`, `parse_levels`; Task 2 `get_stats`, `bucket_for`; `binance_tr_public.depth(symbol, limit=100)`; `market` 24s hacim: `binance_tr_public.ticker_24h([sym])` satırının `quoteVolume`'u.
- Produces:
  - `compose_plan(*, symbol, bucket, price, signal_target_pct, book: dict, quote_volume_try, stats: dict | None, fee_frac, now, profile: dict | None) -> dict` (saf). Plan alanları: `symbol, bucket, entry_ref_price, max_amount_try, max_amount_binding, target_net_pct (3.0), target_gross_pct, target_price, stop_pct, stop_price, eta_minutes, exit_at, grace_minutes, hit_rate, sample_n, profile_exit, warnings, created_at`. `profile` verilirse ve `signal_target_pct > brüt` → `profile_exit=True`, `stop_pct = profile["stop_loss_pct"]`, `exit_at = now + profile["max_hold_minutes"]*60`, `eta_minutes` istatistikten.
  - `async build_plan(symbol, bucket, price, signal_target_pct, profile=None, now=None) -> dict | None` — depth+ticker+stats'i toplar, `compose_plan` çağırır; `asyncio.wait_for(..., 2.0)`; her hata → `None` + `logger.warning`.
  - `exit_advice(plan: dict, entry_price: float, last_price: float, now: float, fee_frac: float) -> str | None` → `None` (henüz `exit_at` değil), `"cik"` (net ≥ 0 ya da `now ≥ exit_at + grace`), `"bekle_stop"` (net < 0).
  - `plan_text(plan: dict) -> str` — tek satır, ör. `Maks: 40.000 TL | Hedef 6,22 (+%3 net) | ~35 dk (geçmişte %62) | Çıkış 20:45'e kadar | Stop 5,82`. Saat Europe/Istanbul. `veri_yetersiz` → `Süre: veri yetersiz`; `hedef_gercekci_degil` → başa `⚠ %3 net bu defterde zor · `.

- [ ] **Step 1: Failing testler**

```python
def test_compose_signal_target_wins_and_profile_exit():
    p = notification_plan.compose_plan(symbol="X", bucket="ma_buy:4h", price=1.0, signal_target_pct=10.0,
        book=BOOK, quote_volume_try=1e9, stats=STATS, fee_frac=0.001125, now=1000.0,
        profile={"stop_loss_pct": 8.0, "max_hold_minutes": 1440})
    assert p["target_gross_pct"] == 10.0 and p["profile_exit"] is True
    assert p["stop_pct"] == 8.0 and p["exit_at"] == 1000.0 + 1440 * 60

def test_compose_no_stats():
    p = notification_plan.compose_plan(..., stats=None, profile=None)
    assert p["eta_minutes"] is None and "veri_yetersiz" in p["warnings"]

def test_stop_clamped():
    p = notification_plan.compose_plan(..., stats={**STATS, "mae_p80_pct": 14.0})
    assert p["stop_pct"] == 10.0

def test_exit_advice_rules():
    plan = {"exit_at": 100.0, "grace_minutes": 10}
    assert notification_plan.exit_advice(plan, 1.0, 1.05, 99.0, 0.001) is None
    assert notification_plan.exit_advice(plan, 1.0, 1.01, 100.0, 0.001) == "cik"
    assert notification_plan.exit_advice(plan, 1.0, 0.95, 100.0, 0.001) == "bekle_stop"
    assert notification_plan.exit_advice(plan, 1.0, 0.95, 100.0 + 600, 0.001) == "cik"

async def test_build_plan_timeout_returns_none():  # Review Focus 2
    with patch.object(binance_tr_public, "depth", side_effect=asyncio.TimeoutError):
        assert await notification_plan.build_plan("XTRY", "radar", 1.0, 2.0) is None

def test_plan_text_contains_numbers():
    t = notification_plan.plan_text(SAMPLE_PLAN)
    assert "Maks: 40.000 TL" in t and "+%3 net" in t and "Çıkış" in t
```

(`BOOK`, `STATS`, `SAMPLE_PLAN` test dosyasında sabit fixture; `...` = ilk testteki ortak argümanlar.)

- [ ] **Step 2:** `python -m pytest tests/test_notification_plan.py -v` → FAIL.
- [ ] **Step 3:** Modülü yaz. `fee_frac` = `config.effective_commission_pct()` (bacak başı kesir).
- [ ] **Step 4:** → PASS.

---

### Task 4: Planı üç bildirime ekle + dondur + uç nokta

**Files:**
- Modify: `backend/app/routers/monitoring.py` (`_build_notification` ~1605, `_build_rising_notification` ~2933, `_send_push` ~902 çağıran yerler), `backend/app/ma_buy_notify.py` (`deliver`), `backend/app/database.py`
- Test: `backend/tests/test_notification_plan_wiring.py`

**Interfaces:**
- Consumes: Task 3 `build_plan`, `plan_text`.
- Produces:
  - `async notification_plan.attach_plan(notif: dict, bucket: str, profile: dict | None = None) -> dict` — `build_plan` çağırır, `notif["trade_plan"] = plan`, plan varsa `notif["message"] += " | " + plan_text(plan)`, `database.save_trade_plan(notif["notification_key"] veya notif["tag"]+detected_at, symbol, bucket, plan)` (ON CONFLICT DO NOTHING; mevcut plan varsa onu okuyup zarfa koyar). Kurucular senkron kaldığından çağrı, kurucu sonrası ve `_send_push` ÖNCESİ yapılır.
  - Zarfa `plan_key` alanı eklenir (diyalog/SW bunu taşır).
  - `GET /api/monitoring/trade-plan?key=<plan_key>` → `{"plan": {...}}` veya 404.

- [ ] **Step 1: Failing testler**

```python
async def test_attach_plan_appends_text_and_freezes():
    with patch.object(notification_plan, "build_plan", AsyncMock(return_value=SAMPLE_PLAN)):
        n = await notification_plan.attach_plan({"symbol": "XTRY", "message": "m", "notification_key": "k1"}, "radar")
    assert n["trade_plan"] == SAMPLE_PLAN and "Maks:" in n["message"] and n["plan_key"] == "k1"

async def test_second_attach_keeps_first_plan():  # Review Focus 3
    ...  # aynı key ile farklı plan → dönen zarf ilk planı taşır

async def test_attach_plan_none_keeps_message():
    with patch.object(notification_plan, "build_plan", AsyncMock(return_value=None)):
        n = await notification_plan.attach_plan({"symbol": "XTRY", "message": "m", "notification_key": "k2"}, "radar")
    assert n["message"] == "m" and n["trade_plan"] is None
```

- [ ] **Step 2:** `python -m pytest tests/test_notification_plan_wiring.py -v` → FAIL.
- [ ] **Step 3:** `attach_plan` + DB yardımcıları (`save_trade_plan`, `get_trade_plan(key)`) + üç yolda çağrı (MA BUY'da profil: `ma_buy_profiles.profile(tf)`) + uç nokta. WS `monitoring_alert` yayını aynı zarfı taşıdığı için uygulama içi veri otomatik aynı olur.
- [ ] **Step 4:** → PASS. Regresyon: `python -m pytest tests/test_auto_paper.py tests/test_daily_first_notification.py -v` → PASS.

---

### Task 5: Otonom paper planı kullanır

**Files:**
- Modify: `backend/app/routers/auto_paper.py` (`try_open_from_notification` ~905 tutar, ~966-1048 hedef/stop/ATR, `_manage_single_trade` ~1292 çıkış)
- Test: `backend/tests/test_auto_paper.py` (yeni testler eklenir)

**Interfaces:**
- Consumes: zarftaki `trade_plan` (Task 4), `notification_plan.exit_advice`.
- Davranış (yalnız `trade_plan` varsa ve `veri_yetersiz` yoksa; aksi halde bugünkü davranış):
  - `order_value = min(<mevcut çarpanlar sonrası tutar>, plan["max_amount_try"])`.
  - `profile_exit` False ise: hedef = `target_gross_pct`, bu işlem için hedefte satış AÇIK, stop = `stop_pct`, ATR genişletmesi KAPALI, `max_hold_minutes` = (`exit_at` − giriş + `grace_minutes`×60)/60; trade satırına `exit_profile="plan"` ve planın `exit_at`/`grace_minutes` değerleri (mevcut `entry_context` JSON'una) yazılır.
  - `profile_exit` True ise: mevcut profil yolu aynen (yalnız tutar sınırı uygulanır).
  - `_manage_single_trade`: `exit_profile=="plan"` işlemlerde `exit_advice(...) == "cik"` → `exit_reason="plan_sure_doldu"` ile kapat. Rejim/LLM/bayat fiyat çıkışları aynen kalır.

- [ ] **Step 1: Failing testler** — `test_plan_caps_order_value`, `test_plan_sets_tp_enabled_and_stop_without_atr`, `test_plan_exit_at_closes_when_net_positive`, `test_plan_keeps_open_when_negative_before_grace`, `test_profile_exit_keeps_profile_stop`, `test_no_plan_unchanged` (her biri ilgili alanı `assert` eder: ör. `trade["order_value"] == 40_000`, `trade["stop_loss_pct"] == 4.2`, `closed["exit_reason"] == "plan_sure_doldu"`).
- [ ] **Step 2:** `python -m pytest tests/test_auto_paper.py -v -k plan` → FAIL.
- [ ] **Step 3:** Uygula.
- [ ] **Step 4:** `python -m pytest tests/test_auto_paper.py -v` → tamamı PASS.

---

### Task 6: Gerçek alım — plan stop/hedef'i ayrı geçirme + kayıt

**Files:**
- Modify: `backend/app/open_position.py` (`build_plan` ~71, `place_order` ~165), `backend/app/trade_plan.py` (`compute_plan` ~42), `backend/app/routers/binance_trade.py` (~168 payload)
- Test: `backend/tests/test_binance_trade_endpoints.py` (eklenir)

**Interfaces:**
- `compute_plan(price, amount_try, sl_pct, rr, filters, fee_rate, tp_pct: float | None = None)` — `tp_pct` verilirse `tp_price = price × (1 + tp_pct/100)` ve `rr` yok sayılır.
- `build_plan(..., tp_pct: float | None = None)` — `tp_pct` verilince RR sınırı uygulanmaz; `sl_pct` sınırı (0,5–10) aynen.
- `place_order` payload yeni alanlar: `tp_pct`, `plan_key`. `claim_order_request` meta'sına ve sonuç gövdesine `plan_key`, `tp_pct`, `exit_at` (= dolum anı + (plan `exit_at` − plan `created_at`); plan yoksa alan yok), `grace_minutes` yazılır.

- [ ] **Step 1: Failing testler**

```python
def test_compute_plan_explicit_tp_pct():
    p = trade_plan.compute_plan(100.0, 1000.0, 5.0, 1.0, FILTERS, 0.001, tp_pct=3.6)
    assert p["tp_price"] == pytest.approx(103.6)

async def test_place_order_records_plan_key_and_exit_at():
    status, body = await open_position.place_order(FAKE_EX, 1, {..., "sl_pct": 4.0, "tp_pct": 3.6, "plan_key": "k1"}, ...)
    assert body["plan_key"] == "k1" and body["exit_at"] > time.time()
```

- [ ] **Step 2:** `python -m pytest tests/test_binance_trade_endpoints.py -v -k "tp_pct or plan_key"` → FAIL.
- [ ] **Step 3:** Uygula (plan, `database.get_trade_plan(plan_key)` ile sunucu tarafında okunur; istemciden gelen fiyatlara güvenilmez).
- [ ] **Step 4:** `python -m pytest tests/test_binance_trade_endpoints.py tests/test_buy_sell_idempotency.py -v` → PASS.

---

### Task 7: Gerçek pozisyon için "çıkış zamanı geldi" push'u

**Files:**
- Create: `backend/app/real_exit_reminder.py`
- Modify: `backend/app/database.py` (`list_plan_order_requests_due(now)`, `mark_exit_reminder(user_id, cid, stage)`), `backend/app/main.py` (döngü başlatma)
- Test: `backend/tests/test_real_exit_reminder.py`

**Interfaces:**
- Consumes: `order_requests` satırları (Task 6 alanları), `notification_plan.exit_advice`, `monitoring._send_push`, kullanıcının borsa istemcisi (mevcut `open_position.protect_position` ile aynı yoldan: OCO durumu + coin bakiyesi).
- Produces: `async reminder_tick(now: float) -> int` (gönderilen push sayısı), `async reminder_loop()` (60 sn).
- Kurallar: aşama 1 `now ≥ exit_at`; aşama 2 `now ≥ exit_at + grace`. Her aşama bir kez (`mark_exit_reminder`). OCO tetiklendiyse veya coin bakiyesi < `executed_qty × 0.5` → push yok, aşama "kapali" işaretlenir. Push metni: `"{SYM} çıkış zamanı geldi: şu an {net:+.1f}% net → {çık | stop'a kadar bekle}"`, `url` `/binance-tr`. EMİR GÖNDERİLMEZ.

- [ ] **Step 1: Failing testler** — `test_stage1_push_when_open_and_due`, `test_no_push_when_oco_filled`, `test_no_push_when_sold_manually` (Review Focus 4), `test_stage2_after_grace_says_cik`, `test_each_stage_once`, `test_never_places_orders` (sahte borsa `buy`/`sell` çağrılmadı `assert_not_called`).
- [ ] **Step 2:** `python -m pytest tests/test_real_exit_reminder.py -v` → FAIL.
- [ ] **Step 3:** Uygula.
- [ ] **Step 4:** → PASS.

---

### Task 8: Frontend — modal, kart, alım diyaloğu, service worker

**Files:**
- Create: `frontend/app/components/user/home/tradePlan.ts` (tip + biçim yardımcıları)
- Modify: `frontend/app/components/RadarAlertModal.tsx` (~268-310 kutucuklar), `frontend/app/components/user/home/NotificationCard.tsx` (~138-184), `frontend/app/components/user/home/BuyDialog.tsx` (~36, ~59, ~93, ~135, ~201), `frontend/app/components/user/home/buyDialogMath.ts`, `frontend/app/components/QuickBuyFromUrl.tsx` (~26), `frontend/app/sw.js/sw.template.js` (~129-138)
- Test: `frontend/app/components/user/home/tradePlan.test.ts`, mevcut `buyDialogMath.test.ts`, `notificationCard.test.tsx`

**Interfaces:**
- `type TradePlan` = Task 3 plan alanları (camelCase değil, backend adlarıyla birebir).
- `planSummary(plan: TradePlan, now: number): string` — backend `plan_text` ile aynı metin (aynı sıra ve biçim; saat `Europe/Istanbul`).
- `planDialogDefaults(plan: TradePlan | null, freeTry: number): { amountTry: number; slPct: number | null; tpPct: number | null; oco: boolean }` — plan varsa `amountTry = min(plan.max_amount_try, freeTry)`, `slPct = plan.stop_pct`, `tpPct = plan.target_gross_pct`, `oco = slPct != null`; plan yoksa bugünkü varsayılan (`amountFromFree(freeTry, 25)`, null, null, false).
- Modal + kart: plan varsa "MAKS TUTAR", "HEDEF (+%3 net)", "STOP", "SÜRE", "ÇIKIŞ" kutucukları + `planSummary` satırı; `warnings` rozetleri.
- BuyDialog: `plan` prop'u; gönderimde `tp_pct`, `plan_key` eklenir; canlı fiyat `entry_ref_price`'tan %1'den fazla saptıysa uyarı bandı.
- SW: `buyUrl = /?buy=SYM&buy_price=<price>&key=<plan_key>`; `QuickBuyFromUrl` `key` varsa `GET /api/monitoring/trade-plan?key=` ile planı çeker, 404'te plansız açar.

- [ ] **Step 1: Failing testler**

```ts
it("plan varsa tutar min(maks, boş)", () => {
  expect(planDialogDefaults(PLAN, 100_000)).toEqual({ amountTry: 40_000, slPct: 4.2, tpPct: 3.6, oco: true });
  expect(planDialogDefaults(PLAN, 10_000).amountTry).toBe(10_000);
});
it("plan yoksa eski varsayılan", () => {  // Review Focus 5
  expect(planDialogDefaults(null, 1000)).toEqual({ amountTry: 250, slPct: null, tpPct: null, oco: false });
});
it("planSummary backend metniyle aynı", () => {
  expect(planSummary(PLAN, NOW)).toBe("Maks: 40.000 TL | Hedef 6,22 (+%3 net) | ~35 dk (geçmişte %62) | Çıkış 20:45'e kadar | Stop 5,82");
});
```
`notificationCard.test.tsx`'e: plan alanları render edilince "MAKS TUTAR" ve "40.000 TL" metni görünür.

- [ ] **Step 2:** `npx vitest run app/components/user/home` → FAIL.
- [ ] **Step 3:** Uygula.
- [ ] **Step 4:** `npx vitest run` → tamamı PASS; `npx tsc --noEmit` → hata yok.

---

### Task 9: Uçtan uca doğrulama

- [ ] **Step 1:** `cd backend && python -m pytest -v -p no:cacheprovider 2>&1 | tail -5` → başarısız yok (önceden kırık olanlar varsa listeyle karşılaştır).
- [ ] **Step 2:** Yerel sunucuda sahte bir radar bildirimi tetikle (mevcut test/admin uç noktası veya `deliver` çağrısı); push gövdesinde ve WS `monitoring_alert` zarfında aynı `Maks/Hedef/Çıkış` metni olduğunu, `GET /api/monitoring/trade-plan?key=` aynı planı döndürdüğünü doğrula.
- [ ] **Step 3:** Tarayıcıda radar modalı ve "Alım yap" diyaloğunun plan değerleriyle dolu açıldığını ekran görüntüsüyle göster (gerçek emir GÖNDERME).
- [ ] **Step 4:** Değişiklikleri commit'lemeden kullanıcıya özetle (dosya listesi + migration 030 notu).
