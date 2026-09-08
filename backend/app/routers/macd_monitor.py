"""MACD MONITOR — aktif sembollerin çoklu zaman dilimi MACD histogram yönü.

"MACD MONITOR" sayfası + monitoring sayfasının "YÜKSELİŞ EĞİLİMİ ADAYLARI"
bölümü için arka plan döngüsü + snapshot API.

Tasarım:
  - Evren: activity taramasında ACTIVE olan semboller + açık pozisyonlar
    (bot + auto paper). Activity haritası henüz boşsa config.SYMBOLS yedeği.
  - Her ~1 sn'de fiyatı değişen semboller için M1/M3/M5/M15/M30/H1 MACD
    histogramı yeniden hesaplanır. Cache yalnızca KAPANMIŞ mum tuttuğundan,
    oluşan mumu temsil etmek için serinin sonuna canlı ticker fiyatı eklenir
    (bar kapanınca kapanış ≈ son canlı fiyat olduğu için seri süreklidir).
  - Yeşil/kırmızı kuralı: histogram > 0 → yeşil, < 0 → kırmızı.
  - Yalnızca gerçek değişiklik varsa ws_manager üzerinden
    {"type": "macd_monitor", "data": {...}} yayınlanır (en fazla ~1/sn);
    UI kendini onarsın diye her N. pass'ta koşulsuz tam yayın yapılır.
  - M3/M30 varsayılan WS abonelik setinde (PRIORITY_TIMEFRAMES) YOKTUR; bu
    seriler market.refresh_series() ile REST'ten periyodik tazelenir
    (3m ~75 sn, 30m ~31 dk — kendi aralıklarına göre).
"""
import asyncio
import logging
import time

from fastapi import APIRouter

from app.config import config
from app import database
from app.api_common import _background_tasks
from app.state import market, analyzer
from app.technical_analysis import _macd
from app.ws_runtime import ws_manager

logger = logging.getLogger("scalper.macd_monitor")
router = APIRouter()

TF_LIST = ("1m", "3m", "5m", "15m", "30m", "1h")
# MACD için yeterli mum: slow(26) + signal(9)
_MACD_MIN_CANDLES = 26 + 9
LOOP_SEC = 1.0
_FIRST_WAIT_SEC = 2.0
# REST ile tazelenen (WS aboneliği olmayan) zaman dilimleri ve aralıkları
_REST_REFRESH_TFS = {"3m": 75.0, "30m": 31 * 60.0}
# Her pass'ta en fazla bu kadar REST tazeleme (Binance TR limit nazikliği)
_MAX_REST_PER_PASS = 8
# Kaç pass'ta bir koşulsuz tam yayın yapılır (UI kendini onarır)
_FULL_BROADCAST_EVERY = 5

# ADR (Ortalama Günlük Hareket): calculate_snapshot ile aynı tanım —
# kapanmış 1d mumlarının son 14 günlük (yüksek-düşük)/kapanış ortalaması.
_ADR_WINDOW = 15  # [-15:-1] → 14 gün
_ADR_CACHE_TTL_SEC = 120.0
# 0-10 normalize skorda güç dilimleri
_STRONG_MIN = 7.0
_WEAK_MAX = 4.0

_loop_task = None

# Son hesaplanan görünüm. symbols: {SYM: {"last": fiyat|None,
# "tfs": {tf: {"green": bool, "hist": float}|None}}}
_SNAPSHOT: dict = {"universe": [], "symbols": {}, "generated_at": 0.0}
# Sembol başına son işlenen canlı fiyat (değişmeyeni yeniden hesaplama)
_last_price_seen: dict[str, float] = {}
# (symbol, tf) → son REST tazeleme zamanı
_last_rest_refresh: dict[tuple[str, str], float] = {}
# symbol → (adr_pct|None, hesap zamanı) — 1d serisi günde bir değişir; 2 dk TTL
_adr_cache: dict[str, tuple[float | None, float]] = {}
_dirty = False


def _status_value(info) -> str:
    """config.SYMBOL_ACTIVITY_STATUS girdisinden status metnini çıkar."""
    if isinstance(info, dict):
        return str(info.get("status") or "")
    return str(info or "")


async def _active_symbols() -> list[str]:
    """Aktif evren: ACTIVE durumdakiler + açık pozisyonlar (bot + auto paper).

    Activity haritası boşsa (ilk tarama öncesi) tüm takip listesi döner.
    """
    statuses = getattr(config, "SYMBOL_ACTIVITY_STATUS", None) or {}
    active = {str(s).upper() for s, info in statuses.items() if _status_value(info).upper() == "ACTIVE"}
    open_syms = {str(s).upper() for s in (analyzer.positions or {})}
    try:
        auto_open = await database.list_auto_paper_trades(status="open")
        open_syms |= {str(t.get("symbol") or "").upper() for t in (auto_open or [])}
    except Exception as exc:
        logger.debug("macd_monitor açık auto-paper pozisyonları okunamadı: %s", exc)
    symbols = sorted(active | open_syms)
    if not symbols:
        tracked = [str(s).upper() for s in (getattr(config, "SYMBOLS", None) or [])]
        symbols = sorted(set(tracked))
    return symbols


def _compute_cell(symbol: str, tf: str):
    """Tek (sembol, zaman dilimi) için histogram yönü.

    Kapanmış mum serisine taze canlı fiyat eklenerek oluşan mum da işin içine
    girer; yetersiz mum (< MACD_MIN_CANDLES) veya veri yoksa None döner.
    """
    history = market.get_ut_kline(symbol, tf)
    closes = history.get("closes") or []
    if not closes:
        return None
    now = time.time()
    ticker = market.get_ticker(symbol)
    live_price = float((ticker or {}).get("last_price") or 0)
    tick_ts = float((ticker or {}).get("timestamp") or 0)
    series = list(closes)
    # Kapanmamış son mumu canlı fiyatla temsil et (tazelik kapısı MAX_TICKER_AGE)
    if live_price > 0 and tick_ts and now * 1000 - tick_ts <= config.MAX_TICKER_AGE_SEC * 1000:
        series.append(live_price)
    if len(series) < _MACD_MIN_CANDLES:
        return None
    macd = _macd(series)
    if macd is None:
        return None
    hist = float(macd["histogram"])
    return {"green": bool(hist > 0), "hist": round(hist, 12)}


def _symbol_adr_pct(symbol: str) -> float | None:
    """Ortalama Günlük Hareket yüzdesi (calculate_snapshot ile aynı tanım).

    1d kapanmış mumlar: son 14 günün (high-low)/close ortalaması × 100.
    Günlük seri yavaş değiştiği için sonuç kısa TTL ile önbelleklenir.
    """
    now = time.time()
    cached = _adr_cache.get(symbol)
    if cached and now - cached[1] < _ADR_CACHE_TTL_SEC:
        return cached[0]
    pct: float | None = None
    try:
        daily = market.get_ut_kline(symbol, "1d")
        dhigh = daily.get("highs") or []
        dlow = daily.get("lows") or []
        dclose = daily.get("closes") or []
        if len(dclose) >= _ADR_WINDOW:
            ranges = [
                (high - low) / close
                for high, low, close in zip(
                    dhigh[-_ADR_WINDOW:-1], dlow[-_ADR_WINDOW:-1], dclose[-_ADR_WINDOW:-1]
                )
                if close
            ]
            if ranges:
                pct = float(sum(ranges) / len(ranges) * 100.0)
    except Exception as exc:
        logger.debug("macd_monitor adr %s: %s", symbol, exc)
    _adr_cache[symbol] = (pct, now)
    return pct


def _strength_meta(pct: float | None, lo: float | None, hi: float | None):
    """Evren içi min-max ile 0-10 güç skoru + GÜÇLÜ/NORMAL/ZAYIF dilimi."""
    if pct is None or lo is None or hi is None or pct <= 0:
        return None, None
    if hi <= lo:
        score = 5.0
    else:
        score = (pct - lo) / (hi - lo) * 10.0
    score = round(max(0.0, min(10.0, score)), 1)
    if score >= _STRONG_MIN:
        tier = "strong"
    elif score < _WEAK_MAX:
        tier = "weak"
    else:
        tier = "normal"
    return score, tier


async def _compute_pass(pass_no: int) -> dict:
    """Bir hesaplama turu: evreni tazele, değişen sembolleri yeniden hesapla.

    Yayın yapmaz; güncel snapshot'ı döndürür (loop yayını yönetir).
    """
    global _SNAPSHOT, _dirty, _last_price_seen
    now = time.time()
    universe = await _active_symbols()
    snapshot_symbols = _SNAPSHOT.setdefault("symbols", {})
    universe_changed = universe != list(_SNAPSHOT.get("universe") or [])

    # Evrenden düşen sembolleri temizle
    keep = set(universe)
    for sym in [s for s in list(snapshot_symbols) if s not in keep]:
        snapshot_symbols.pop(sym, None)
        _last_price_seen.pop(sym, None)

    # M3/M30 REST tazeleme (yalnızca süresi gelenler; pass başına sınırlı)
    due = []
    for sym in universe:
        for tf, interval in _REST_REFRESH_TFS.items():
            key = (sym, tf)
            last = _last_rest_refresh.get(key, 0.0)
            if not last or now - last > interval:
                due.append(key)
    if due:
        async def _refresh(key):
            sym, tf = key
            try:
                if await market.refresh_series(sym, tf, limit=150):
                    _last_rest_refresh[key] = time.time()
            except Exception as exc:
                logger.debug("macd_monitor refresh_series %s/%s: %s", sym, tf, exc)
        await asyncio.gather(*(_refresh(k) for k in due[:_MAX_REST_PER_PASS]),
                             return_exceptions=True)

    recomputed = 0
    for sym in universe:
        ticker = market.get_ticker(sym)
        price = float((ticker or {}).get("last_price") or 0) if ticker else 0
        is_new = sym not in snapshot_symbols
        if not is_new and not universe_changed and price == float(_last_price_seen.get(sym) or 0):
            continue  # fiyat değişmedi → sonuç da değişmez
        _last_price_seen[sym] = price
        row = snapshot_symbols.get(sym) or {}
        tfs = row.get("tfs") or {}
        for tf in TF_LIST:
            tfs[tf] = _compute_cell(sym, tf)
        row["tfs"] = tfs
        row["last"] = price if price > 0 else row.get("last")
        snapshot_symbols[sym] = row
        recomputed += 1

    if universe_changed or recomputed:
        _dirty = True

    # ADR tabanlı güç: her sembolün ortalama günlük hareketini evren içinde
    # min-max normalize edip 0-10 skor + GÜÇLÜ/NORMAL/ZAYIF dilimi üret.
    adr_map = {sym: _symbol_adr_pct(sym) for sym in snapshot_symbols}
    valid = [pct for pct in adr_map.values() if pct is not None and pct > 0]
    lo, hi = (min(valid), max(valid)) if valid else (None, None)
    for sym, row in snapshot_symbols.items():
        pct = adr_map.get(sym)
        score, tier = _strength_meta(pct, lo, hi)
        updated = {
            "adr_pct": round(pct, 3) if pct is not None else None,
            "strength": score,
            "tier": tier,
        }
        if (row.get("adr_pct"), row.get("strength"), row.get("tier")) != (
            updated["adr_pct"], updated["strength"], updated["tier"]
        ):
            _dirty = True
        row.update(updated)

    _SNAPSHOT.update({
        "universe": universe,
        "symbols": snapshot_symbols,
        "generated_at": now,
        "timeframes": list(TF_LIST),
    })
    return _SNAPSHOT


async def macd_monitor_loop():
    """~1 sn'de bir: değişen sembolleri hesapla, değişiklik varsa yayınla."""
    logger.info("macd_monitor döngüsü başladı")
    await asyncio.sleep(_FIRST_WAIT_SEC)
    global _dirty
    pass_no = 0
    while True:
        try:
            pass_no += 1
            await _compute_pass(pass_no)
            force_full = (pass_no % _FULL_BROADCAST_EVERY) == 0
            if _dirty or force_full:
                await ws_manager.broadcast({"type": "macd_monitor", "data": dict(_SNAPSHOT)})
                _dirty = False
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("macd_monitor turu: %s", exc)
        await asyncio.sleep(LOOP_SEC)


@router.get("/api/macd-monitor")
async def get_macd_monitor():
    """MACD MONITOR snapshot'ı (REST ilk yükleme/yedek).

    Veri yalnızca public market verisinden türetilir (kapanış fiyatları +
    MACD/ADR); monitoring sayfasındaki "YÜKSELİŞ EĞİLİMİ ADAYLARI" bölümü
    de bu ucu kullandığından admin kısıtı YOKTUR.
    """
    try:
        payload = await _compute_pass(0)
    except Exception as exc:
        logger.warning("macd_monitor snapshot hesaplanamadı: %s", exc)
        payload = dict(_SNAPSHOT)
    payload["running"] = _loop_task is not None and not _loop_task.done()
    return {"paper_only": True, **payload}


def start_macd_monitor_loop() -> bool:
    """Arka plan döngüsünü bir kez başlat (idempotent)."""
    global _loop_task
    if _loop_task is not None and not _loop_task.done():
        return False
    _loop_task = asyncio.create_task(macd_monitor_loop(), name="macd-monitor-loop")
    _background_tasks.add(_loop_task)
    return True


def stop_macd_monitor_loop():
    """Döngüyü durdur (arka plan task havuzundan çıkar)."""
    global _loop_task
    if _loop_task is not None:
        _loop_task.cancel()
        _background_tasks.discard(_loop_task)
        _loop_task = None
