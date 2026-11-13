"""Regresyon: "WS bağlı ama fiyat BAYAT" — asıl kök neden (2026-11-10).

CANLI BULGU ZİNCİRİ:
1. `config.SYMBOLS` yalnız ~20 sembol içeriyor → WS bireysel
   (`<sym>@miniTicker`, `@kline`, `@depth5`) yalnız BU sembollere abone.
2. `!miniTicker@arr` TÜM evreni KAPSAMIYOR: canlı ölçümde yalnız ~49 satır
   döndürüyor (AXLTRY/BTCTRY YOK). Önceki "arr tüm 310 sembolü taşır"
   varsayımı YANLIŞTI; bu yüzden mini-ticker birleştirme düzeltmesi
   (68acdb36) tek başına yetmedi.
3. Abone olmayan sembol için `tickers` de `mini_tickers` de boş kalıyor →
   `auto_paper` her turda "ticker BAYAT" deyip REST yedeğine düşüyor.
4. KÖK NEDEN: `extend_stream_universe` / `apply_symbol_universe`
   `market.symbols`'u yazıyordu ama **WS aboneliğini yenilemiyordu**
   (`reconnect_requested` yalnız `stop()` içinde set ediliyordu).
   Yani pozisyon açılan sembolün akışı hiç kurulmuyordu.
"""
import inspect

from app import state
from app.market_data import MarketData


def test_request_stream_refresh_sets_flag():
    """`request_stream_refresh` reconnect bayrağını set etmeli."""
    md = MarketData(["BTCTRY"])
    md.reconnect_requested = False
    md.request_stream_refresh()
    assert md.reconnect_requested is True, "abonelik yenileme bayrağı set edilmedi"


def test_extend_stream_universe_triggers_refresh(monkeypatch):
    """Akış evrenine YENİ sembol eklenince WS aboneliği yenilenmeli."""
    calls = {"n": 0}

    def _spy():
        calls["n"] += 1

    monkeypatch.setattr(type(state.market), "request_stream_refresh",
                        lambda self: _spy(), raising=True)
    monkeypatch.setattr(state, "config", state.config, raising=False)
    before = list(state.market.symbols)
    try:
        state.extend_stream_universe(["AXLTRY"], source="test_regression")
        assert calls["n"] >= 1, "yeni sembol eklendi ama WS aboneliği yenilenmedi"
    finally:
        state.market.symbols = before


def test_extend_stream_universe_no_refresh_when_no_new(monkeypatch):
    """Zaten akışta olan sembol için gereksiz yeniden bağlanma YAPILMAMALI."""
    calls = {"n": 0}
    monkeypatch.setattr(type(state.market), "request_stream_refresh",
                        lambda self: calls.__setitem__("n", calls["n"] + 1), raising=True)
    present = state.market.symbols[0].upper()
    state.extend_stream_universe([present], source="test_noop")
    assert calls["n"] == 0, "değişiklik yokken gereksiz WS yenilemesi tetiklendi"


def test_apply_symbol_universe_triggers_refresh(monkeypatch):
    """Tarama evreni değişince de abonelik yenilenmeli (tek yazma kapısı)."""
    calls = {"n": 0}
    monkeypatch.setattr(type(state.market), "request_stream_refresh",
                        lambda self: calls.__setitem__("n", calls["n"] + 1), raising=True)
    before_syms, before_cfg = list(state.market.symbols), list(state.config.SYMBOLS)
    try:
        state.apply_symbol_universe([*before_cfg, "AXLTRY"], source="test_apply")
        assert calls["n"] == 1, "evren değişti ama abonelik yenilenmedi"
    finally:
        state.market.symbols = before_syms
        state.config.SYMBOLS = before_cfg


def test_reconnect_flag_is_checked_while_streaming():
    """Bayrak, SAĞLIKLI akış döngüsünün İÇİNDE kontrol edilmeli.

    Yalnız yeniden-bağlanma denemelerinde kontrol edilseydi, akış sağlıklıyken
    set edilen bayrak bir sonraki doğal kopmaya kadar yok sayılırdı.
    """
    src = inspect.getsource(MarketData._run_ws_group) if hasattr(MarketData, "_run_ws_group") else ""
    assert "reconnect_requested" in src, "akış döngüsü bayrağı kontrol etmiyor"


def test_mini_ticker_arr_does_not_cover_full_universe():
    """BULGU KAYDI: `!miniTicker@arr` tüm evreni kapsamaz — varsayım kilitli.

    Bu test kodu değil, TASARIM KARARINI korur: get_ticker'ın mini_tickers
    yedeği faydalıdır ama abone olmayan sembolleri KURTARMAZ. Bir gün biri
    "arr hepsini taşıyor, aboneliğe gerek yok" derse bu test gerekçeyi gösterir.
    """
    get_ticker_src = inspect.getsource(MarketData.get_ticker)
    assert "mini_tickers" in get_ticker_src
    # Karar: abone olmayan sembol için akış kurulması ŞARTTIR.
    from app import market_data as md_mod
    assert hasattr(md_mod.MarketData, "request_stream_refresh")
