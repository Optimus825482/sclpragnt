"""Gerçek pozisyon "çıkış zamanı geldi" hatırlatıcısı. Sahte borsa/DB/push; GERÇEK EMİR YOK, EMİR HİÇ GÖNDERİLMEZ."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from app import alerting, database, real_exit_reminder as rer
from app.routers import monitoring

EXIT_AT = 1_000_000.0
FEE = 0.001


class FakeExchange:
    def __init__(self, coin_free=0.0, coin_locked=10.0, price=110.0):
        self.coin_free, self.coin_locked, self.px = coin_free, coin_locked, price
        self.error = None
        # Emir üreten / emir okuyan tüm yollar: çağrılırsa test kırılır.
        self.buy = AsyncMock()
        self.sell = AsyncMock()
        self.cancel = AsyncMock()
        self.oco = AsyncMock()
        self.open_orders = AsyncMock()

    async def asset_balance(self, asset):
        if self.error:
            raise self.error
        assert asset == "ADA"
        return self.coin_free, self.coin_locked

    async def price(self, symbol_u):
        return self.px


def _row(cid="cid00001", user_id=7, grace=30, reminder=None, protection=None, exit_at=EXIT_AT):
    result = {"symbol": "ADA_TRY", "executed_qty": 10.0, "avg_price": 100.0, "plan_key": "pk1",
              "exit_at": exit_at, "grace_minutes": grace,
              "protection": protection or {"status": "placed", "order_list_id": "900", "qty": 10.0}}
    if reminder:
        result["exit_reminder"] = reminder
    return {"user_id": user_id, "client_order_id": cid, "symbol": "ADA_TRY", "result": result}


class FakeDB:
    def __init__(self, rows):
        self.rows = rows
        self.marks = []
        self.unmarks = []

    def _get(self, user_id, cid):
        return next(r for r in self.rows if r["user_id"] == user_id and r["client_order_id"] == cid)

    async def list_due(self, now):
        return [r for r in self.rows if r["result"].get("exit_at") is not None and r["result"]["exit_at"] <= now]

    async def mark(self, user_id, cid, stage):
        rem = self._get(user_id, cid)["result"].setdefault("exit_reminder", {})
        key = rer.STAGE_KEYS[stage]
        if rem.get(key):
            return False
        rem[key] = 1.0
        self.marks.append((user_id, cid, stage))
        return True

    async def unmark(self, user_id, cid, stage):
        self._get(user_id, cid)["result"].get("exit_reminder", {}).pop(rer.STAGE_KEYS[stage], None)
        self.unmarks.append((user_id, cid, stage))


class Env:
    def __init__(self):
        self.ex = FakeExchange()
        self.db = FakeDB([_row()])
        self.pushes = []
        self.push_result = {"ok": True, "count": 1, "total": 1}


@pytest.fixture
def env(monkeypatch):
    e = Env()

    async def fake_push(message, **kw):
        e.pushes.append({"message": message, **kw})
        return dict(e.push_result)

    async def fake_exchange_for_user(user_id):
        return e.ex, "erkan"

    monkeypatch.setattr(database, "list_plan_order_requests_due", e.db.list_due)
    monkeypatch.setattr(database, "mark_exit_reminder", e.db.mark)
    monkeypatch.setattr(database, "unmark_exit_reminder", e.db.unmark)
    monkeypatch.setattr(alerting, "deliver_web_push", fake_push)
    monkeypatch.setattr(rer, "_exchange_for_user", fake_exchange_for_user)
    monkeypatch.setattr(rer, "_fee_frac", lambda: FEE)
    monkeypatch.setattr(rer, "_last_warn", {})
    monkeypatch.setattr(rer, "_no_keys_logged", set())
    monkeypatch.setattr(monitoring, "get_user_notification_settings",
                        AsyncMock(return_value={"enabled": True, "quiet_hours_start": None, "quiet_hours_end": None}))
    monkeypatch.setattr(monitoring, "_vapid_configured", lambda: True)
    return e


def _tick(now):
    return asyncio.run(rer.reminder_tick(now))


def _net(last, entry=100.0, f=FEE):
    return (last * (1 - f) / (entry * (1 + f)) - 1) * 100


def test_stage1_push_when_open_and_due(env):
    assert _tick(EXIT_AT - 1) == 0
    assert env.pushes == []
    assert _tick(EXIT_AT + 5) == 1
    p = env.pushes[0]
    assert p["message"] == f"ADATRY çıkış zamanı geldi: şu an {_net(110.0):+.1f}% net → çık"
    assert p["url"] == "/binance-tr"
    assert p["tag"] == "exit-ADATRY-cid00001"
    assert p["usernames"] == ["erkan"]          # yalnız pozisyon sahibine
    # SW "Alım yap" düğmesini bu kaynakta kapatır; alım planı anahtarı taşınmaz
    assert p["extra"]["source"] == "real_exit_reminder" and "plan_key" not in p["extra"]
    assert env.db.marks == [(7, "cid00001", "stage1")]


def test_stage1_says_wait_for_stop_when_net_negative(env):
    env.ex.px = 99.0
    assert _tick(EXIT_AT + 5) == 1
    assert env.pushes[0]["message"] == f"ADATRY çıkış zamanı geldi: şu an {_net(99.0):+.1f}% net → stop'a kadar bekle"


def test_no_push_when_oco_filled(env):
    env.ex.coin_free, env.ex.coin_locked = 0.0, 0.0     # OCO doldu: coin satıldı, bakiye düştü
    assert _tick(EXIT_AT + 5) == 0
    assert env.pushes == []
    assert env.db.marks == [(7, "cid00001", "kapali")]
    assert _tick(EXIT_AT + 30 * 60 + 5) == 0             # kapalı: aşama 2 de gelmez
    assert env.pushes == []


def test_no_push_when_sold_manually(env):
    env.db.rows[0]["result"]["protection"] = {"status": "failed"}   # OCO yok
    env.ex.coin_free, env.ex.coin_locked = 4.0, 0.0                  # < 10 × 0.5
    assert _tick(EXIT_AT + 5) == 0
    assert env.pushes == []
    assert env.db.marks == [(7, "cid00001", "kapali")]


def test_open_without_oco_still_reminds(env):
    env.db.rows[0]["result"]["protection"] = {"status": "failed"}
    env.ex.coin_free, env.ex.coin_locked = 10.0, 0.0
    assert _tick(EXIT_AT + 5) == 1


def test_cancelled_oco_but_coin_held_still_reminds(env):
    # protection "placed" ama kullanıcı OCO'yu iptal etti: coin serbest bakiyede duruyor → yine hatırlat
    env.ex.coin_free, env.ex.coin_locked = 10.0, 0.0
    assert _tick(EXIT_AT + 5) == 1
    assert env.db.marks == [(7, "cid00001", "stage1")]
    env.ex.open_orders.assert_not_called()      # kapanış yalnız bakiyeden anlaşılır


def test_stage2_after_grace_says_cik(env):
    env.ex.px = 95.0                              # zararda bile aşama 2 "çık"
    assert _tick(EXIT_AT + 5) == 1
    assert env.pushes[0]["message"].endswith("→ stop'a kadar bekle")
    assert _tick(EXIT_AT + 29 * 60) == 0
    assert _tick(EXIT_AT + 30 * 60 + 1) == 1
    assert env.pushes[1]["message"] == f"ADATRY çıkış zamanı geldi: şu an {_net(95.0):+.1f}% net → çık"
    assert env.db.marks == [(7, "cid00001", "stage1"), (7, "cid00001", "stage2")]


def test_no_stage2_without_grace(env):
    env.db.rows[0]["result"]["grace_minutes"] = None
    assert _tick(EXIT_AT + 5) == 1
    assert _tick(EXIT_AT + 10 * 3600) == 0
    assert len(env.pushes) == 1


def test_late_first_tick_sends_only_stage2(env):
    assert _tick(EXIT_AT + 31 * 60) == 1      # aşama 1 kaçırıldı (ör. sessiz saat) → tek push
    assert env.pushes[0]["message"].endswith("→ çık")
    assert {m[2] for m in env.db.marks} == {"stage1", "stage2"}


def test_each_stage_once(env):
    assert _tick(EXIT_AT + 5) == 1
    assert _tick(EXIT_AT + 65) == 0
    assert _tick(EXIT_AT + 125) == 0
    assert _tick(EXIT_AT + 30 * 60 + 5) == 1
    assert _tick(EXIT_AT + 30 * 60 + 65) == 0
    assert len(env.pushes) == 2


def test_exchange_error_skips_without_marking(env):
    env.ex.error = RuntimeError("borsa yok")
    assert _tick(EXIT_AT + 5) == 0
    assert env.db.marks == [] and env.pushes == []
    env.ex.error = None
    assert _tick(EXIT_AT + 65) == 1


def test_transient_push_failure_releases_stage_for_retry(env):
    env.push_result = {"ok": False, "count": 0, "total": 1, "dead_count": 0}   # abonelik var, teslim edilemedi
    assert _tick(EXIT_AT + 5) == 0
    assert env.db.unmarks == [(7, "cid00001", "stage1")]
    env.push_result = {"ok": True, "count": 1, "total": 1}
    assert _tick(EXIT_AT + 65) == 1
    assert len(env.pushes) == 2


def test_push_exception_error_releases_stage(env):
    env.push_result = {"ok": False, "error": "boom"}
    assert _tick(EXIT_AT + 5) == 0
    assert env.db.unmarks == [(7, "cid00001", "stage1")]


def test_transient_failure_on_stage2_retries_stage2(env):
    env.push_result = {"ok": False, "error": "boom"}
    assert _tick(EXIT_AT + 31 * 60) == 0
    assert env.db.unmarks == [(7, "cid00001", "stage2")]
    env.push_result = {"ok": True, "count": 1, "total": 1}
    assert _tick(EXIT_AT + 32 * 60) == 1
    assert env.pushes[-1]["message"].endswith("→ çık")


@pytest.mark.parametrize("res", [{"ok": False, "skipped": True, "reason": "vapid_not_configured"},
                                 {"ok": False, "count": 0, "total": 0, "dead_count": 0}])
def test_permanent_push_failure_keeps_stage(env, res):
    env.push_result = res
    assert _tick(EXIT_AT + 5) == 0
    assert env.db.unmarks == []
    assert _tick(EXIT_AT + 65) == 0
    assert len(env.pushes) == 1                   # aşama tüketildi, yeniden denenmez


def test_exchange_error_warning_debounced(env, caplog):
    env.ex.error = RuntimeError("borsa yok")
    with caplog.at_level("WARNING", logger=rer.logger.name):
        for i in range(5):
            _tick(EXIT_AT + 5 + i * 60)
        _tick(EXIT_AT + 5 + 3601)
    warns = [r for r in caplog.records if "borsa okunamadı" in r.getMessage()]
    assert len(warns) == 2


def test_no_keys_logged_once_and_never_pushes(env, monkeypatch, caplog):
    async def none_for_user(user_id):
        return None

    monkeypatch.setattr(rer, "_exchange_for_user", none_for_user)
    with caplog.at_level("DEBUG", logger=rer.logger.name):
        _tick(EXIT_AT + 5)
        _tick(EXIT_AT + 65)
    assert env.pushes == [] and env.db.marks == []
    assert len([r for r in caplog.records if "anahtar" in r.getMessage()]) == 1


def test_quiet_hours_defers_without_marking(env, monkeypatch):
    monkeypatch.setattr(monitoring, "_in_quiet_hours", lambda s: True)
    assert _tick(EXIT_AT + 5) == 0
    assert env.db.marks == [] and env.pushes == []
    monkeypatch.setattr(monitoring, "_in_quiet_hours", lambda s: False)
    assert _tick(EXIT_AT + 65) == 1


def test_notifications_disabled_sends_nothing(env, monkeypatch):
    monkeypatch.setattr(monitoring, "get_user_notification_settings", AsyncMock(return_value={"enabled": False}))
    assert _tick(EXIT_AT + 5) == 0
    assert env.db.marks == [] and env.pushes == []


def test_multi_user_rows(env):
    env.db.rows.append(_row(cid="cid00002", user_id=8))
    assert _tick(EXIT_AT + 5) == 2
    assert {p["tag"] for p in env.pushes} == {"exit-ADATRY-cid00001", "exit-ADATRY-cid00002"}


def test_never_places_orders(env):
    for now in (EXIT_AT + 5, EXIT_AT + 30 * 60 + 5):
        _tick(now)
    env.ex.coin_free, env.ex.coin_locked = 0.0, 0.0
    env.db.rows.append(_row(cid="cid00003"))
    _tick(EXIT_AT + 40 * 60)
    for m in (env.ex.buy, env.ex.sell, env.ex.cancel, env.ex.oco):
        m.assert_not_called()


class _RecConn:
    def __init__(self, rows=(), rowcount=1):
        self.sql, self.params, self._rows, self.rowcount = [], [], list(rows), rowcount

    def execute(self, sql, params=()):
        self.sql.append(sql)
        self.params.append(params)
        return self

    def fetchall(self):
        return self._rows

    def commit(self):
        pass


def test_db_helpers_sql(monkeypatch):
    conn = _RecConn(rows=[(7, "cid00001", "ADA_TRY", '{"exit_at": 5}')])

    async def run(op):
        return op(conn)

    monkeypatch.setattr(database, "_run_db", run)
    rows = asyncio.run(database.list_plan_order_requests_due(100.0))
    assert rows == [{"user_id": 7, "client_order_id": "cid00001", "symbol": "ADA_TRY", "result": {"exit_at": 5}}]
    assert "order_requests" in conn.sql[0] and "exit_reminder" in conn.sql[0]
    assert asyncio.run(database.mark_exit_reminder(7, "cid00001", "stage1")) is True
    assert "jsonb_set" in conn.sql[1] and "stage1_at" in conn.params[1]
    conn.rowcount = 0
    assert asyncio.run(database.mark_exit_reminder(7, "cid00001", "kapali")) is False
    with pytest.raises(ValueError):
        asyncio.run(database.mark_exit_reminder(7, "cid00001", "bogus"))
    asyncio.run(database.unmark_exit_reminder(7, "cid00001", "stage2"))
    assert "jsonb_set" in conn.sql[-1] and "stage2_at" in conn.params[-1]
