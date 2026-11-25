"""Read-only evidence for reviewing closed autonomous paper trades."""

from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response

from app import database, security

router = APIRouter(prefix="/api/auto-paper/diagnostics", tags=["auto-paper"])
_REPORT_TZ = timezone(timedelta(hours=3))
_BAR_MS = 300_000
_BOOK_LOOKBACK_SECONDS = 300


async def _closed_trades(start: float, end: float, limit: int, offset: int, include_archived: bool):
    def op(conn):
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '5s'")
        reset_at = database._get_reset_cutoff_sync(conn)
        floor = start if include_archived else max(start, database._report_floor_sync(conn))
        rows = conn.execute(
            """
            WITH selected AS (
              SELECT id, symbol, entry_time, exit_time, entry_price, exit_price, quantity,
                     order_value_try, pnl, pnl_pct, commission, entry_commission_pct,
                     exit_commission_pct, exit_reason, notification_id, notification_key,
                     notification_score, notification_target_pct, notification_expected_price,
                     entry_volume_ratio, oi_change_pct, exit_profile, max_hold_minutes, plan_context,
                     stop_loss, take_profit, tp_cancelled, max_adverse_pct, max_favorable_pct,
                     peak_price, breakeven_activated, breakeven_stop, trailing_activated, trailing_stop
              FROM auto_paper_trades
              WHERE status = 'closed' AND exit_time >= ? AND exit_time < ?
                AND (? OR COALESCE(exit_reason, '') <> 'reset')
              ORDER BY exit_time DESC, id DESC LIMIT ? OFFSET ?
            )
            SELECT t.*,
                   CASE WHEN n.id IS NOT NULL THEN jsonb_build_object(
                       'id', n.id, 'detected_at', n.detected_at, 'mode', n.mode,
                       'price', n.price, 'score', n.score, 'target_pct', n.target_pct,
                       'expected_price', n.expected_price, 'horizon_minutes', n.horizon_minutes,
                       'sources', n.sources, 'sent_via_push', n.sent_via_push
                   ) END AS notification,
                   opened.reason AS entry_decision,
                   closed.reason AS exit_decision
            FROM selected t
            LEFT JOIN monitoring_notifications n ON n.id = t.notification_id AND n.symbol = t.symbol
            LEFT JOIN LATERAL (
                SELECT reason FROM signals
                WHERE trade_id = 'auto_paper-' || t.id::text AND symbol = t.symbol
                  AND strategy = 'AUTO_PAPER' AND action = 'BUY_SIGNAL'
                ORDER BY timestamp, id LIMIT 1
            ) opened ON true
            LEFT JOIN LATERAL (
                SELECT reason FROM signals
                WHERE trade_id = 'auto_paper-' || t.id::text AND symbol = t.symbol
                  AND strategy = 'AUTO_PAPER' AND action = 'CLOSE_LONG'
                ORDER BY timestamp DESC, id DESC LIMIT 1
            ) closed ON true
            ORDER BY t.exit_time DESC, t.id DESC
            """,
            (floor, end, include_archived, limit + 1, offset),
        ).fetchall()
        return {"trades": [dict(row) for row in rows[:limit]], "reset_at": reset_at,
                "effective_start": floor, "has_more": len(rows) > limit}

    return await database._run_db(op)


async def _market_context(trade_id: int):
    def op(conn):
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '5s'")
        trade = conn.execute(
            "SELECT symbol, entry_time, exit_time FROM auto_paper_trades WHERE id = ? "
            "AND status = 'closed' AND exit_time IS NOT NULL",
            (trade_id,),
        ).fetchone()
        if trade is None:
            return None

        symbol = trade["symbol"]
        context = {}
        for event, timestamp in (("entry", trade["entry_time"]), ("exit", trade["exit_time"])):
            event_bar_ms = int(timestamp * 1000) // _BAR_MS * _BAR_MS
            start_ms = event_bar_ms - 6 * _BAR_MS
            end_ms = event_bar_ms + 7 * _BAR_MS
            candles = conn.execute(
                "SELECT open_time, close_time, open, high, low, close, volume, quote_volume, trade_count "
                "FROM historical_candles WHERE symbol = ? AND timeframe = '5m' "
                "AND open_time >= ? AND open_time < ? ORDER BY open_time",
                (symbol, start_ms, end_ms),
            ).fetchall()
            book = conn.execute(
                "SELECT captured_at, bid_price, ask_price, spread_pct, depth_try, orderflow_imbalance "
                "FROM microstructure_snapshots WHERE symbol = ? AND captured_at BETWEEN ? AND ? "
                "ORDER BY captured_at DESC LIMIT 1",
                (symbol, timestamp - _BOOK_LOOKBACK_SECONDS, timestamp),
            ).fetchone()
            context[event] = {
                "timestamp": timestamp,
                "candle_start_ms": start_ms,
                "candle_end_ms_exclusive": end_ms,
                "candles_5m": [dict(row) for row in candles],
                "last_book_sample": dict(book) if book is not None else None,
            }
        return {"trade_id": trade_id, "symbol": symbol, **context}

    return await database._run_db(op)


@router.get("")
async def closed_trade_diagnostics(
    request: Request,
    response: Response,
    day: date,
    limit: Annotated[int, Query(ge=1, le=250)] = 100,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
    include_archived: bool = False,
):
    """List closed positions and linked entry/exit evidence for one UTC+3 day."""
    security.require_admin(request)
    start = datetime.combine(day, time.min, _REPORT_TZ).timestamp()
    end = start + 86_400
    data = await _closed_trades(start, end, limit, offset, include_archived)
    response.headers["Cache-Control"] = "no-store"
    return {"paper_only": True, "day": day, "timezone": "UTC+03:00", "offset": offset, **data}


@router.get("/{trade_id}/market")
async def closed_trade_market(
    request: Request,
    response: Response,
    trade_id: Annotated[int, Path(ge=1, le=9_223_372_036_854_775_807)],
):
    """Return stored five-minute bars and preceding book samples around entry and exit."""
    security.require_admin(request)
    data = await _market_context(trade_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Kapalı otonom paper işlemi bulunamadı")
    response.headers["Cache-Control"] = "no-store"
    return data
