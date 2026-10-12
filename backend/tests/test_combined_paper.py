"""KOMBİNE PAPER PORTFÖY testleri (2026-10-11 kullanıcı kararı).

Kapsam:
- Config varsayılanları: 5000 TL başlangıç, %10 pozisyon, max 5 açık.
- DB yardımcıları mevcut (open/close/list/stats/wallet).
- `_plan_entry`: serbest bakiyenin %10'u; TP potansiyele göre; SL tabanı.
- API uçları kayıtlı (state/reset/close).
- Motor: main.py döngüsü + kombine liste gönderiminde otonom açılış çağrısı.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from app import config  # noqa: E402
from app import database  # noqa: E402
from app import combined_paper  # noqa: E402


def test_combined_paper_config_defaults():
    c = config.config
    assert c.COMBINED_PAPER_ENABLED is True
    assert c.COMBINED_PAPER_INITIAL_BALANCE_TRY == 5000.0
    assert c.COMBINED_PAPER_POSITION_PCT == 10.0
    assert c.COMBINED_PAPER_MAX_OPEN == 5


def test_combined_paper_db_helpers_exist():
    for name in ("open_combined_paper_trade", "close_combined_paper_trade",
                 "list_combined_paper_trades", "get_combined_paper_stats",
                 "get_combined_paper_wallet", "reset_combined_paper_portfolio",
                 "update_combined_paper_trade"):
        assert hasattr(database, name), f"database.{name} eksik"


def test_plan_entry_position_is_10pct_and_tp_from_potential():
    """Pozisyon = serbest bakiyenin %10'u; TP potansiyele göre; SL tabanı uygulanır."""
    plan = combined_paper._plan_entry(
        {"symbol": "WTEST", "price": 100.0, "potential_pct": 20.0, "quality_score": 88},
        cash=5000.0)
    assert plan is not None
    assert plan["order_value_try"] == 500.0          # 5000 * %10
    assert abs(plan["quantity"] - 5.0) < 1e-9        # 500 / 100
    # TP potansiyele göre anlamlı (taban %3, potansiyelin altında)
    assert 3.0 <= plan["tp_pct"] <= 20.0
    assert plan["take_profit"] > plan["entry_price"]
    assert plan["stop_loss"] < plan["entry_price"]


def test_plan_entry_skips_tiny_balance():
    """Çok küçük kalan bakiye (< 50 TL pozisyon) → plan yok (anlamsız işlem açılmaz)."""
    assert combined_paper._plan_entry({"symbol": "X", "price": 1.0}, cash=100.0) is None


def test_plan_entry_tp_min_floor():
    """Potansiyel düşük/yoksa TP en az %3 tabanında kalır (uydurma yok)."""
    plan = combined_paper._plan_entry({"symbol": "Y", "price": 10.0, "potential_pct": None}, 5000.0)
    assert plan is not None and plan["tp_pct"] == 3.0


def test_combined_paper_endpoints_registered():
    from app.routers.monitoring import router
    paths = {r.path for r in router.routes}
    assert "/api/combined-paper/state" in paths
    assert "/api/combined-paper/reset" in paths
    assert "/api/combined-paper/close/{trade_id}" in paths


def test_combined_paper_trail_trigger_and_gap_not_too_tight():
    """Kullanıcı geri bildirimi (2026-10-11): "trailing mesafeleri çok yakın takip
    ediyor, hemen yakalanıyorlar." Gap %1.0 (tepeden anlamlı geri çekilme
    toleransı) ve trigger %1.0 olmalı — %0.3 gibi sıkı değerler DEĞİL."""
    c = config.config
    assert c.COMBINED_PAPER_TRAIL_GAP_PCT >= 0.8, "trailing gap çok dar — hemen yakalanır"
    assert c.COMBINED_PAPER_TRAIL_TRIGGER_PCT >= 0.8


def test_trailing_trigger_greater_than_gap_no_loss():
    """Kullanıcı mantığı (2026-10-11): "trailing %1 kârda aktive olup %1 geriden
    takip ederse işlem ZARARDA kapanabilir; %2 kârda başlayıp %1 geriden takip
    etmeli." KURAL: trigger > gap → stop her zaman GİRİŞİN ÜSTÜNDE kalır."""
    c = config.config
    assert c.COMBINED_PAPER_TRAIL_TRIGGER_PCT > c.COMBINED_PAPER_TRAIL_GAP_PCT, \
        "trigger, gap'ten büyük olmalı (aksi halde kâr zarara döner)"
    assert c.AUTO_PAPER_TRAILING_TRIGGER_PCT > c.AUTO_PAPER_TRAILING_GAP_PCT, \
        "otonom paper: trigger, gap'ten büyük olmalı"
    # Somut doğrulama: en erken aktivasyonda bile stop girişin üstünde.
    entry = 100.0
    peak = entry * (1 + c.AUTO_PAPER_TRAILING_TRIGGER_PCT / 100)
    stop = peak * (1 - c.AUTO_PAPER_TRAILING_GAP_PCT / 100)
    assert stop > entry, "aktivasyonda stop girişin altında → kâr zarara döner"


def test_price_has_rest_fallback_for_passive_symbols():
    """Kullanıcı geri bildirimi (2026-10-11): pasife alınan sembol (WS akışında yok)
    kombine paper'da fiyat "—" görünüyordu. `_price` WS yoksa REST yedeğine düşmeli
    → pasif coinin de fiyatı gelir ve pozisyon yönetimi kopmaz. Ayrıca pasif sembol
    KAPATILMAZ (symbol_deactivated yolu YOK)."""
    import inspect
    from app import combined_paper as cp
    src = inspect.getsource(cp._price)
    assert "ticker_price" in src, "REST yedeği eksik"
    assert "_ticker_price" in src, "önce WS denenmeli"
    # `_manage_single` yeni `_price`'ı kullanmalı.
    msrc = inspect.getsource(cp._manage_single)
    assert "await _price(" in msrc
    # Pasif-kapatma yolu OLMAMALI (kullanıcı isteği: kapanmasına gerek yok).
    assert "symbol_deactivated" not in inspect.getsource(cp)


def test_autonomous_and_combined_trailing_equal():
    """Kullanıcı isteği (2026-10-11): "bu trailing ayarlarını NORMAL paper trade'de
    de aynı şekilde yapalım." Otonom paper ve kombine paper trailing tetik/boşluğu
    BİREBİR aynı olmalı (DB'deki kayıtlı otonom değer de config ile eşitlenir)."""
    c = config.config
    assert c.COMBINED_PAPER_TRAIL_GAP_PCT == c.AUTO_PAPER_TRAILING_GAP_PCT, \
        "gap eşit değil — iki paper sistemi ayrışır"
    assert c.COMBINED_PAPER_TRAIL_TRIGGER_PCT == c.AUTO_PAPER_TRAILING_TRIGGER_PCT, \
        "trigger eşit değil — iki paper sistemi ayrışır"
    # Onarım fonksiyonu eski/dar değerleri (0.8 ve 1.8) config'e çekmeli.
    import inspect
    from app.routers import auto_paper as ap
    src = inspect.getsource(ap._migrate_bad_settings_once)
    assert "0.8" in src and "1.8" in src


def test_trailing_stop_stays_below_price_on_first_activation():
    """İlk aktivasyonda stop fiyatın ALTINDA kalmalı (anında kapanma yok) ve
    tepeden gap kadar geride olmalı."""
    import inspect
    from app import combined_paper as cp
    src = inspect.getsource(cp._manage_single)
    # İlk aktivasyon koruması + tepeden gap.
    assert "was_active" in src
    assert "peak * (1 - gap / 100.0)" in src
    assert "cost_floor" in src


def test_auto_paper_settings_repair_targets_bad_values():
    """Kök neden düzeltmesi: DB'de kayıtlı kötü kombinasyon (SL 1.5 / trig 1.8 /
    gap 0.6) tek-seferlik onarımla düzeltilir; iyi değerlere DOKUNULMAZ."""
    import inspect
    from app.routers import auto_paper as ap
    src = inspect.getsource(ap._migrate_bad_settings_once)
    # Yalnız eski/kötü değerler hedeflenir.
    assert "1.5" in src and "1.8" in src and "0.6" in src
    assert "stop_loss_pct" in src and "trailing_trigger_pct" in src and "trailing_gap_pct" in src
    # Başlangıçta çağrılıyor.
    start_src = inspect.getsource(ap.start_auto_paper_loop)
    assert "_migrate_bad_settings_once" in start_src


def test_combined_list_send_triggers_autopaper():
    """Kombine liste gönderildiğinde ayrı portföyde otonom açılış TETİKLENİR."""
    import inspect
    from app.routers import monitoring as mo
    src = inspect.getsource(mo._send_combined_list)
    assert "combined_paper" in src and "on_combined_list_sent" in src


def test_manager_loop_registered_in_main():
    import inspect
    import app.main as m
    src = inspect.getsource(m)
    assert "combined_paper_management_loop" in src
    assert "combined-paper" in src


def test_tp_cancelled_when_trailing_active(monkeypatch):
    """Kullanıcı kararı (2026-10-12): trailing bağlandıysa TP KALDIRILIR —
    kazanan pozisyon TP'ye (ör. %4) takılıp erken kapanmaz, trend sürer.

    GERÇEK davranış: trailing_activated=True iken fiyat TP'nin üzerinde olsa bile
    kapanış olmamalı (take_profit çağrılmamalı)."""
    import asyncio
    import time
    from app import combined_paper as cp

    closed = []

    async def _close(tid, price, now, reason):
        closed.append(reason)
        return {"pnl": 0}
    monkeypatch.setattr(cp.database, "close_combined_paper_trade", _close)

    async def _price(_s):
        return 105.0   # TP=104'ün üzerinde
    monkeypatch.setattr(cp, "_price", _price)
    async def _upd(*_a, **_k):
        return None
    monkeypatch.setattr(cp.database, "update_combined_paper_trade", _upd)

    trade = {"id": 1, "symbol": "T", "entry_price": 100.0, "quantity": 1.0,
             "take_profit": 104.0, "stop_loss": 97.0, "peak_price": 105.0,
             "trailing_activated": True, "trailing_stop": 103.0,
             "entry_time": time.time()}
    asyncio.run(cp._manage_single(trade, time.time()))
    assert "take_profit" not in closed, "trailing aktifken TP ile kapanmamalı"


def test_tp_fires_when_trailing_not_active(monkeypatch):
    """Trailing YOKSA TP normal çalışır (klasik davranış korunur)."""
    import asyncio
    import time
    from app import combined_paper as cp
    closed = []
    async def _close(tid, price, now, reason):
        closed.append(reason); return {"pnl": 0}
    monkeypatch.setattr(cp.database, "close_combined_paper_trade", _close)
    async def _price(_s):
        return 105.0
    monkeypatch.setattr(cp, "_price", _price)
    trade = {"id": 1, "symbol": "T", "entry_price": 100.0, "quantity": 1.0,
             "take_profit": 104.0, "stop_loss": 97.0, "peak_price": 100.0,
             "trailing_activated": False, "entry_time": time.time()}
    asyncio.run(cp._manage_single(trade, time.time()))
    assert "take_profit" in closed


def test_no_profit_timeout_closes_loser(monkeypatch):
    """Kullanıcı kararı (2026-10-12): pozisyon 30 dk içinde KÂRA GEÇMEDİYSE
    (peak <= giriş) otomatik kapanır → no_profit_timeout."""
    import asyncio
    import time
    from app import combined_paper as cp
    closed = []
    async def _close(tid, price, now, reason):
        closed.append(reason); return {"pnl": -1.0}
    monkeypatch.setattr(cp.database, "close_combined_paper_trade", _close)
    async def _price(_s):
        return 99.0   # hâlâ zararda, hiç kâra geçmedi
    monkeypatch.setattr(cp, "_price", _price)
    trade = {"id": 1, "symbol": "T", "entry_price": 100.0, "quantity": 1.0,
             "take_profit": 110.0, "stop_loss": 90.0, "peak_price": 100.0,
             "trailing_activated": False, "entry_time": time.time() - 31 * 60}
    asyncio.run(cp._manage_single(trade, time.time()))
    assert "no_profit_timeout" in closed


def test_no_profit_timeout_skips_winner(monkeypatch):
    """Kâra GEÇMİŞ (peak > giriş) pozisyon no_profit_timeout ile KAPANMAZ —
    kazanan erken kesilmez (normal trailing/max-hold işler)."""
    import asyncio
    import time
    from app import combined_paper as cp
    closed = []
    async def _close(tid, price, now, reason):
        closed.append(reason); return {"pnl": 1.0}
    monkeypatch.setattr(cp.database, "close_combined_paper_trade", _close)
    async def _price(_s):
        return 100.5   # girişin hafif üstünde ama TP'ye uzak
    monkeypatch.setattr(cp, "_price", _price)
    async def _upd(*_a, **_k):
        return None
    monkeypatch.setattr(cp.database, "update_combined_paper_trade", _upd)
    trade = {"id": 1, "symbol": "T", "entry_price": 100.0, "quantity": 1.0,
             "take_profit": 110.0, "stop_loss": 90.0, "peak_price": 102.0,
             "trailing_activated": False, "entry_time": time.time() - 31 * 60}
    asyncio.run(cp._manage_single(trade, time.time()))
    assert "no_profit_timeout" not in closed


def test_sl_pct_calibrated_to_one_percent():
    """KALİBRASYON KİLİDİ (2026-10-12): SL tabanı %1.0.

    `scripts/calibrate_combined_paper.py` 5.909 gerçek velocity adayı + gerçek
    mumlar üzerinde walk-forward taradı: %3 stop kaybı -0.83 puan/işlem iken
    %1 stop -0.42'ye indiriyor (eşleştirilmiş t≈7, 5m+1m, her slippage'da).
    Bu test ayarın sessizce eski geniş değere dönmesini engeller."""
    c = config.config
    assert c.COMBINED_PAPER_SL_PCT == 1.0, \
        "SL kalibrasyonla %1.0 seçildi; genişletmek veriyle gerekçelendirilmeli"


def test_paper_sim_reads_same_sl_as_combined_paper():
    """Simülasyon (raporlardaki 'gerçekleşebilir %') ve canlı paper AYNI SL
    sabitini okumalı — yoksa sim ekranda yanıltıcı olur."""
    import inspect
    from app import database as db
    src = inspect.getsource(db.evaluate_daily_rising_report)
    assert "COMBINED_PAPER_SL_PCT" in src, "sim SL'i canlı sabitten okumalı"


def test_calibration_grid_respects_deployable_constraints():
    """Kalibrasyon grid'i YALNIZ uygulanabilir konfig üretmeli: gap>=0.8 ve
    trigger>gap (trail testleriyle çakışmasın)."""
    import importlib.util
    import pathlib
    p = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "calibrate_combined_paper.py"
    spec = importlib.util.spec_from_file_location("calib", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    grid = mod._grid(mod.DEFAULT_CFG)
    assert grid, "grid boş"
    for cfg in grid:
        assert cfg["trail_gap_pct"] >= 0.8, f"uygulanamaz dar gap: {cfg}"
        assert cfg["trail_trigger_pct"] > cfg["trail_gap_pct"], f"trigger<=gap: {cfg}"
    # Varsayılan taban kalibrasyonla hizalı olmalı.
    assert mod.DEFAULT_CFG["sl_pct"] == 1.0
