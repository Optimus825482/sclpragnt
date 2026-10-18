"""Üst menü altındaki portföy bandı için TEK istekte özet (`GET /api/portfolio/band`).

NEDEN: Band hem gerçek Binance TR hem paper değerlerini gösterir. İstemci
aksi halde key-durumu + hesap/pozisyon + günlük K/Z (+ paper için özet,
pozisyonlar, otonom istatistik) için 4-5 istek atmak zorunda kalırdı.

KAYNAK KURALI: kullanıcının Binance TR key+secret'ı kayıtlıysa GERÇEK Binance
değerleri (`source="binance"`), değilse PAPER değerleri (`source="paper"`).
Binance anahtarı kayıtlı ama borsa çağrısı başarısızsa sessizce paper'a DÜŞÜLMEZ
(kaynak karışırdı) — 502 döner, istemci "veri alınamadı" gösterir.

Binance yükü: mevcut `binance_positions` ve `binance_trades_day` işleyicileri
olduğu gibi çağrılır (yeni Binance ucu yok). Sonuç kullanıcı başına kısa süre
(`_BINANCE_TTL_SEC`) önbelleğe alınır; birden çok sekme/istemci borsaya ek
yük bindirmez. `binance_trades_day` kendi 120 sn önbelleğini zaten kullanır.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

from app import database
from app.config import config

logger = logging.getLogger("scalper.portfolio_band")
router = APIRouter()

#: Gerçek Binance özeti için kullanıcı başına önbellek süresi (sn).
_BINANCE_TTL_SEC = 10.0
# 2026-10-18: TTL sonrası ≤ bu kadar saniye bayat özet HEMEN döner, arka planda tek-uçuş tazeleme başlar
# (Binance TR sayfası ve bant aynı yanıtı paylaşır; ilk boyama beklemez).
_BINANCE_STALE_MAX_SEC = 120.0
#: Bu TL değerinin altındaki varlıklar (toz) "açık işlem" sayılmaz.
DUST_TRY = 10.0

_TR_TZ = timezone(timedelta(hours=3))
_binance_cache: dict[str, tuple[float, dict]] = {}
_binance_locks: dict[str, asyncio.Lock] = {}
_binance_refresh_tasks: dict[str, asyncio.Task] = {}


def _main():
    # Dairesel içe aktarmayı önlemek için fonksiyon düzeyinde (binance_trade.py ile aynı desen).
    from app import main
    return main


def _num(value) -> float | None:
    """Sonlu sayıya çevirir; None/boş/NaN/Inf -> None (0 DEĞİL: "veri yok")."""
    if value is None or value == "":
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def build_binance_band(positions: dict, daily: dict | None, now: float | None = None) -> dict:
    """`/api/binance/positions` + `/api/binance/trades-day` yanıtlarından bant özeti."""
    holdings = [h for h in (positions.get("holdings") or []) if isinstance(h, dict)]
    free_try = 0.0
    for b in positions.get("balances") or []:
        if str(b.get("asset") or "").upper() == "TRY":
            free_try = _num(b.get("free")) or 0.0
            break

    open_count = 0
    unrealized = 0.0
    cost_basis = 0.0
    measured = 0
    # 2026-10-17: istemci `binance_price` WS tikleriyle (2 sn) toplam değeri ve anlık K/Z'yi
    # canlı yeniden hesaplasın diye varlık başına taban değerler (fiyat · adet · maliyet).
    # K/Z kuralı `main.binance_positions` ile aynı: (fiyat − ortalama maliyet) × adet.
    live_holdings: list[dict] = []
    for h in holdings:
        asset_u = str(h.get("asset") or "").upper()
        if asset_u == "TRY":
            continue
        value = _num(h.get("value_try"))
        price = _num(h.get("price_try"))
        qty_all = _num(h.get("total"))
        if price and qty_all:
            live_holdings.append({
                "asset": asset_u,
                "symbol": str(h.get("symbol") or f"{asset_u}TRY").replace("_", "").upper(),
                "qty": qty_all,
                "price_try": price,
                "avg_cost_try": _num(h.get("avg_cost_try")),
                "counted": bool(value is not None and value >= DUST_TRY),
            })
        if value is None or value < DUST_TRY:
            continue
        open_count += 1
        pnl = _num(h.get("pnl_try"))
        avg_cost = _num(h.get("avg_cost_try"))
        qty = _num(h.get("total"))
        if pnl is None or not avg_cost or not qty:
            continue
        unrealized += pnl
        cost_basis += avg_cost * qty
        measured += 1

    # Pozisyon var ama hiçbirinin maliyeti bilinmiyorsa "veri yok" (None);
    # pozisyon yoksa K/Z meşru olarak 0'dır.
    if open_count == 0:
        unrealized_try: float | None = 0.0
        unrealized_pct: float | None = 0.0
    elif measured == 0:
        unrealized_try = None
        unrealized_pct = None
    else:
        unrealized_try = unrealized
        unrealized_pct = (unrealized / cost_basis * 100.0) if cost_basis > 0 else None

    daily_pnl = _num(((daily or {}).get("daily") or {}).get("realized_pnl_try")) if daily else None
    return {
        "source": "binance",
        "total_try": _round(_num(positions.get("total_value_try"))),
        "free_try": _round(free_try),
        "open_count": open_count,
        "unrealized_try": _round(unrealized_try),
        "unrealized_pct": _round(unrealized_pct, 4),
        "daily_pnl_try": _round(daily_pnl),
        "updated_at": time.time() if now is None else now,
        "holdings": live_holdings,
    }


def _net_open_pnl(entry, current, qty, side, commission_pct: float) -> tuple[float, float] | None:
    """Kanonik net açık K/Z (gidiş-dönüş komisyon düşülmüş) — `frontend/app/lib/pnl.ts` ile aynı kural."""
    e, c, q = _num(entry), _num(current), _num(qty)
    if not e or not c or not q or e <= 0 or c <= 0 or q <= 0:
        return None
    sign = -1.0 if str(side or "").upper() == "SHORT" else 1.0
    net = (c - e) * q * sign - commission_pct * q * (e + c)
    return net, e * q


def build_paper_band(snapshot: dict | None, daily_pnl: float | None, now: float | None = None) -> dict:
    """WS portföy anlık görüntüsü (ana + otonom paper) + günlük kapanmış K/Z'den bant özeti.

    `positions` alanı ham açık pozisyonları taşır: istemci WS ile canlı kalırken
    K/Z'yi kendi kanonik yardımcılarıyla (lib/pnl.ts) yeniden hesaplayabilsin.
    """
    snap = snapshot or {}
    raw = [p for p in (snap.get("positions") or []) if isinstance(p, dict)]
    raw += [p for p in (snap.get("auto_paper_positions") or []) if isinstance(p, dict)]
    pct = _num(snap.get("commission_pct")) or float(getattr(config, "COMMISSION_PCT", 0.0015) or 0.0015)

    unrealized = 0.0
    cost = 0.0
    measured = 0
    for p in raw:
        res = _net_open_pnl(p.get("entry"), p.get("current"), p.get("quantity"), p.get("side"), pct)
        if res is None:
            continue
        unrealized += res[0]
        cost += res[1]
        measured += 1
    if not raw:
        unrealized_try: float | None = 0.0
        unrealized_pct: float | None = 0.0
    elif measured == 0:
        unrealized_try = None
        unrealized_pct = None
    else:
        unrealized_try = unrealized
        unrealized_pct = (unrealized / cost * 100.0) if cost > 0 else None

    return {
        "source": "paper",
        "total_try": _round(_num(snap.get("total_value"))),
        "free_try": _round(_num(snap.get("try"))),
        "open_count": len(raw),
        "unrealized_try": _round(unrealized_try),
        "unrealized_pct": _round(unrealized_pct, 4),
        "daily_pnl_try": _round(daily_pnl),
        "updated_at": time.time() if now is None else now,
        "positions": [
            {"symbol": p.get("symbol"), "side": p.get("side"), "entry": _num(p.get("entry")),
             "current": _num(p.get("current")), "quantity": _num(p.get("quantity"))}
            for p in raw
        ],
        "commission_pct": pct,
    }


def _today_tr() -> tuple[str, float]:
    """TR saatine (UTC+3) göre bugünün tarihi ve gün başlangıcı (epoch sn)."""
    now = datetime.now(_TR_TZ)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return now.strftime("%Y-%m-%d"), start.timestamp()


async def _paper_daily_pnl() -> float | None:
    """Bugün kapanan paper işlemlerin net K/Z'si: ana (trades) + otonom (auto_paper_trades)."""
    _, day_start = _today_tr()
    total = 0.0
    got = False
    try:
        trades = await database.get_trades(limit=500)
        total += sum(float(t.get("pnl") or 0.0) for t in trades
                     if float(t.get("exit_time") or 0.0) >= day_start)
        got = True
    except Exception as exc:
        logger.warning("Band: ana paper günlük K/Z okunamadı: %s", exc)
    try:
        stats = await database.get_auto_paper_stats()
        total += float(stats.get("total_pnl_try") or 0.0)
        got = True
    except Exception as exc:
        logger.warning("Band: otonom paper günlük K/Z okunamadı: %s", exc)
    return total if got else None


async def _paper_snapshot_fallback() -> dict:
    """2026-10-17 (basit arayüz): WS anlık görüntüsü henüz üretilmemişse (backend yeni
    açıldı / yayın döngüsü ilk turunu bitirmedi) bant "—" gösteriyordu. Cüzdan ve açık
    paper pozisyonlardan asgari bir görüntü kurulur; fiyat yoksa giriş fiyatı kullanılır."""
    try:
        from app.routers.runtime import _cached_try_balance
        from app.state import analyzer, market
        try_bal = float(await _cached_try_balance() or 0.0)
        positions = []
        total = try_bal
        for sym, pos in dict(getattr(analyzer, "positions", {}) or {}).items():
            qty = float(pos.get("quantity") or 0.0)
            entry = float(pos.get("entry_price") or 0.0)
            ticker = market.get_ticker(sym) if hasattr(market, "get_ticker") else None
            current = float((ticker or {}).get("last_price") or entry)
            value = qty * current
            total += value
            positions.append({"symbol": sym, "entry": entry, "current": current, "quantity": qty,
                              "value": value, "side": pos.get("side", "LONG"),
                              "strategy": pos.get("strategy", "UT")})
        return {"try": try_bal, "total_value": total, "positions": positions,
                "auto_paper_positions": [], "fallback": True}
    except Exception as exc:  # fail-open: bant yine "—" gösterir, uç çökmez
        logger.debug("paper band fallback başarısız: %s", exc)
        return {}


async def _paper_band() -> dict:
    from app.routers.runtime import _ws_snapshot_cache
    snapshot = _ws_snapshot_cache.get("portfolio") or {}
    if not snapshot or snapshot.get("total_value") is None:
        snapshot = await _paper_snapshot_fallback()
    try:
        snapshot = database._json_safe(snapshot)
    except Exception:
        pass
    return build_paper_band(snapshot, await _paper_daily_pnl())


# 2026-10-18: pozisyonlar hazır olunca gün işlemleri için en çok bu kadar beklenir; bitmemişse
# bant `daily_pnl_try=None` ile HEMEN döner, gün işlemleri arka planda kendi cache'ini doldurur
# (sonraki bant turu cache'ten anında okur).
_DAILY_GRACE_SEC = 0.25


def _consume_day_result(task: asyncio.Task, username: str) -> None:
    """Arka planda biten gün-işlemleri görevinin istisnasını tüket ("never retrieved" uyarısı olmasın)."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("Band: Binance günlük işlemler alınamadı (kullanıcı=%s): %s", username, exc)


async def _binance_band(request: Request, username: str) -> dict:
    m = _main()
    today, _ = _today_tr()
    day_task = asyncio.ensure_future(m.binance_trades_day(request, date=today))
    try:
        pos_res = await m.binance_positions(request)
    except BaseException:
        day_task.add_done_callback(lambda t: _consume_day_result(t, username))
        raise
    if not day_task.done():
        await asyncio.wait({day_task}, timeout=_DAILY_GRACE_SEC)
    daily = None
    if day_task.done():
        if day_task.cancelled():
            pass
        elif day_task.exception() is not None:
            logger.warning("Band: Binance günlük işlemler alınamadı (kullanıcı=%s): %s",
                           username, day_task.exception())
        else:
            daily = day_task.result()
    else:
        day_task.add_done_callback(lambda t: _consume_day_result(t, username))
    return build_binance_band(pos_res, daily)


@router.get("/api/portfolio/band")
async def portfolio_band(request: Request):
    """Üst bant özeti: Binance anahtarı kayıtlıysa gerçek, değilse paper."""
    m = _main()
    principal = m._require_user(request)
    username = str(principal.get("username") or "").strip().lower()
    settings = await m.get_binance_settings(request)
    if not settings.get("configured"):
        return await _paper_band()

    cached = _binance_cache.get(username)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    # 2026-10-18 stale-while-revalidate (bkz. _BINANCE_STALE_MAX_SEC).
    if cached and cached[0] + _BINANCE_STALE_MAX_SEC > time.monotonic():
        _schedule_binance_refresh(request, username)
        return cached[1]
    return await _refresh_binance_band(request, username)


async def _refresh_binance_band(request: Request, username: str) -> dict:
    """Tek-uçuş kilit altında taze bant özeti; cache'e yazar."""
    lock = _binance_locks.setdefault(username, asyncio.Lock())
    async with lock:
        cached = _binance_cache.get(username)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        try:
            payload = await _binance_band(request, username)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Binance TR portföy özeti alınamadı: {type(exc).__name__}")
        # Günlük K/Z henüz yoksa (gün işlemleri arka planda) kısa TTL: sonraki tur cache'ten tamamlar.
        ttl = _BINANCE_TTL_SEC if payload.get("daily_pnl_try") is not None else min(_BINANCE_TTL_SEC, 3.0)
        _binance_cache[username] = (time.monotonic() + ttl, payload)
        return payload


def _schedule_binance_refresh(request: Request, username: str) -> None:
    """Arka planda tek-uçuş tazeleme; hata yalnız loglanır (bayat yanıt zaten verildi)."""
    task = _binance_refresh_tasks.get(username)
    if task is not None and not task.done():
        return

    async def _run():
        try:
            await _refresh_binance_band(request, username)
        except Exception as exc:  # noqa: BLE001
            logger.info("Band arka plan tazeleme (kullanıcı=%s): %s", username, exc)

    _binance_refresh_tasks[username] = asyncio.get_running_loop().create_task(_run())
