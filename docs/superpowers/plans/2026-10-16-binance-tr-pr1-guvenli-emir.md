# Binance TR — PR 1: Güvenli emir, Risk ayarları, Plan (arka uç) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (yerel). Adımlar TDD: önce kırmızı test.

**Goal:** Kullanıcıya özel Risk Merkezi ayarları, sembole özel RR planı (LLM + kural yedek), idempotent güvenli `open-position` (alım → gerçekleşen miktar → OCO) ve hız iyileştirmeleri.

**Architecture:** Saf modüller (`risk_settings`, `trade_plan`) + DB tabloları (migration 017: `user_risk_settings`, `order_requests`) + yeni router `routers/binance_trade.py` (mevcut `main.py` yardımcılarını tembel içe aktarır) + `binance_tr_private` içinde öncelikli emir yuvası. Gerçek emir testlerde YOK: `binance_tr_private` fonksiyonları sahte.

**Tech Stack:** FastAPI, PostgreSQL (psycopg), pytest.

**Spec:** `docs/superpowers/specs/2026-10-16-binance-tr-kullanici-ticaret-design.md`

## Global Constraints
- Gerçek Binance emri HİÇBİR testte/geliştirme denemesinde gönderilmez (sahte katman).
- Migration kuralları (`backend/migrations/README.md`): `017`, idempotent, `BEGIN/COMMIT/CONCURRENTLY` yok.
- Her uç yalnız oturumdaki kullanıcının verisi; önbellekler kullanıcıya özel.
- LLM çıktısı sunucuda doğrulanıp kenetlenir; LLM emir vermez.
- Tutar sınırı sunucuda zorlanır (UI'a güvenilmez). Canlı işlem bayrağı (`_real_sell_state_for`) alım/OCO için zorunludur.
- Türkçe, kısa hata metinleri; `ruff check app tests scripts` temiz.

## Review Focus
- Aynı `client_order_id` iki kez gelirse ikinci gerçek emir YOK (eşzamanlı çift istek dahil).
- Alım başarılı, OCO başarısız → `protection:"failed"` ve `protect` ile yeniden deneme; kullanıcı korumasız kalırsa açık işaret.
- Kısmi dolum / `executedQty` yok → OCO yalnız gerçekleşen (adım yuvarlı) miktarla; 0 ise OCO atlanır ve uyarı.
- LLM yok/zaman aşımı/bozuk JSON/aşırı değer → kural tabanlı yedek; asla istisna.
- `max_position_pct` aşımı, min notional altı, LOT_SIZE adımı → reddedilir (422), emir gitmez.
- Belirsiz sonuç (zaman aşımı) → 202 UNKNOWN; sorgulanmadan yeniden emir üretilmez.

---

### Task 1: Risk ayarları (migration, doğrulama, DB, uçlar)
**Files:** Create `backend/migrations/017_binance_trade.sql`, `backend/app/risk_settings.py`, `backend/tests/test_risk_settings.py`; Modify `backend/app/database.py`.
**Interfaces — Produces:**
- `risk_settings.DEFAULTS = {"max_position_pct": 20.0, "default_rr": 2.0}`
- `risk_settings.validate(payload: dict) -> dict` (ValueError): `max_position_pct` 1–100, `default_rr` 1–5; yalnız gelen alanlar; NaN/inf reddedilir.
- `database.get_user_risk_settings(user_id) -> dict` (kayıt yoksa DEFAULTS), `database.set_user_risk_settings(user_id, values) -> dict`.
Migration: `user_risk_settings(user_id BIGINT PK REFERENCES users ON DELETE CASCADE, max_position_pct DOUBLE PRECISION NOT NULL DEFAULT 20, default_rr DOUBLE PRECISION NOT NULL DEFAULT 2, updated_at DOUBLE PRECISION NOT NULL)` ve `order_requests(user_id BIGINT, client_order_id TEXT, status TEXT NOT NULL, symbol TEXT, request JSONB, result JSONB, created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL, PRIMARY KEY (user_id, client_order_id))`.
Testler: sınırlar, NaN/inf, kısmi güncelleme, varsayılanlar, SQL yer tutucu sayısı (sahte bağlantı).

### Task 2: Plan hesabı + RR önerisi (saf)
**Files:** Create `backend/app/trade_plan.py`, `backend/tests/test_trade_plan.py`.
**Interfaces — Produces:**
- `round_down(value, step) -> float`, `round_to_tick(value, tick) -> float`.
- `compute_plan(price, amount_try, sl_pct, rr, filters, fee_rate) -> dict`: `{qty, cost_try, fee_buy_try, sl_price, tp_price, sl_pct, rr, loss_try (negatif), gain_try, break_even_price, warnings:[...]}`. SL=price×(1−sl_pct/100); TP=price×(1+sl_pct×rr/100); miktar `step_size` aşağı yuvarlı; fiyatlar tick'e; senaryolar komisyon dahil (alım+satım).
- `rule_suggestion(atr_pct, default_rr) -> {"sl_pct": clamp(1.5*atr_pct, 0.8, 6.0), "rr": default_rr, "source": "kural"}`.
- `validate_llm_suggestion(raw) -> dict | None`: JSON (düz metin içinde süslü parantez dahil) → `{sl_pct (0.5–10 kenetli), rr (1–5 kenetli), rationale (≤240 karakter)}`; geçersiz → None.
Testler: yuvarlama, iyi/kötü senaryo aritmetiği (komisyonla), min notional uyarısı, kural yedeği, LLM çıktısı geçerli/bozuk/aşırı değer/metin içinde JSON.

### Task 3: Öneri hizmeti (LLM + önbellek + zaman aşımı)
**Files:** Modify `backend/app/trade_plan.py` (async `suggest_rr`), Test `backend/tests/test_trade_plan_llm.py`.
**Interfaces — Consumes:** `llm_analysis.chat(snapshot, messages, json_mode=True, max_tokens=300)`, snapshot sözlüğü. **Produces:** `async suggest_rr(symbol, snapshot, default_rr, *, now=None, timeout=6.0) -> dict {sl_pct, rr, rationale, source:"llm"|"kural"}`; sembol başına 60 sn önbellek; zaman aşımı/hata/None/devre dışı → kural.
Testler: LLM geçerli → "llm"; LLM bozuk/zaman aşımı/devre dışı → "kural"; önbellek (ikinci çağrıda LLM çağrılmaz).

### Task 4: İdempotent emir kaydı
**Files:** Create `backend/app/order_requests.py`, `backend/tests/test_order_requests.py`; Modify `backend/app/database.py`.
**Interfaces — Produces:** `database.claim_order_request(user_id, client_order_id, symbol, request) -> bool` (INSERT … ON CONFLICT DO NOTHING; True=bu çağrı sahibi), `database.finish_order_request(user_id, client_order_id, status, result)`, `database.get_order_request(user_id, client_order_id) -> dict | None`. Durumlar: `in_progress|done|failed|unknown`.
Testler: ilk istek sahibi, ikinci istek sahibi değil, `finish` sonrası `get` sonucu döner, `client_order_id` doğrulama (8–64, `[A-Za-z0-9_-]`).

### Task 5: Uçlar (router)
**Files:** Create `backend/app/routers/binance_trade.py`, `backend/tests/test_binance_trade_endpoints.py`; Modify `backend/app/main.py` (router kaydı), `README.md` (router tablosu).
**Uçlar:** `GET/PUT /api/binance/risk`; `GET /api/binance/symbol-info`; `POST /api/binance/trade-plan`; `POST /api/binance/open-position`; `POST /api/binance/protect`; `DELETE /api/binance/keys`; `POST /api/binance/user-stream/start`.
`open-position` akışı: (1) bayrak+girdi doğrulama, (2) `claim_order_request` — yinelenen id: `done/unknown/in_progress` yanıtı döner, (3) risk sınırı (`amount ≤ free_try × pct`), filtre/min notional, taze bakiye, (4) `place_market_buy(..., client_order_id)`, belirsizse `unknown`+202, (5) `get_order_detail` ile `executedQty` (≤3 deneme/1 sn), (6) `place_oco_sell(qty, tp, sl)`; sonuç `{bought, executed_qty, avg_price, protection:"placed"|"failed"|"skipped", client_order_id}`, `finish_order_request`.
Testler (sahte `binance_tr_private`): başarılı akış; yinelenen id ikinci alım üretmez; eşzamanlı çift istek; limit aşımı 422; bayrak kapalı 403; OCO başarısız → `failed` ve `protect`; kısmi dolum miktarı; belirsiz → 202; kullanıcı izolasyonu.

### Task 6: Hız ve sağlamlaştırma
**Files:** Modify `backend/app/binance_tr_private.py`, `backend/app/main.py`; Test `backend/tests/test_order_priority.py`.
- Emir POST'ları için ayrı (öncelikli) `Semaphore`; okuma istekleri emir yuvasını işgal etmez.
- Açılışta sembol filtreleri ısıtılır (arka plan görevi).
- `notify=true` push'u emir yanıtından ayrılır (arka plan görevi).
- API anahtarı kaydında borsada doğrulama (`account/spot`); anahtar silme `delete_user_binance_keys` + kullanıcı akışını durdurma.
- Emir süresi log'u (`emir_ms`): onaydan borsaya gönderime sunucu süresi.
Testler: emir yuvası okuma yoğunluğunda bloklanmaz; push gecikmesi yanıtı geciktirmez; anahtar doğrulama başarısızsa kayıt reddedilir.

### Task 7: Sahte borsa ile uçtan uca ve PR
**Files:** Create `backend/tests/fake_binance_tr.py` (yerel HTTP sahte sunucu), `backend/tests/test_open_position_e2e.py`.
Sahte sunucu `REST_BASE`'e yönlendirilerek alım→detay→OCO akışı doğrulanır (gerçek istek YOK). Ardından tam test seti, `ruff`, PR.

## Self-Review (spec ↔ plan)
Spec §3 güvenlik → Task 4/5/6; §4 uçlar → Task 5; Risk Merkezi ayarları → Task 1; plan hesabı + LLM → Task 2/3; hız → Task 6; test → Task 7. PR 2 (arayüz) ve PR 3 (yönetici sayfası) bu planın kapsamı dışıdır.
