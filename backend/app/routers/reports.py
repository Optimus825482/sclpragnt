"""Read-only report endpoints: signals, forecasts, chat predictions, decisions."""
import asyncio
import time
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from app.config import config
from app import database
from app.state import market, analyzer
from app.api_common import _start_background
from app import chat_prediction_learning
from app import chat_prediction_replay
from app.forecast_learning import normalize_direction, evaluate_forecast, derive_lessons
from app.binance_tr_public import klines as fetch_klines, historical_klines
from app.routers.llm_chat import (_forecast_evaluation_state, _chat_prediction_learning_state,
                                  _chat_pattern_state, _chat_auto_trade_state)

logger = logging.getLogger("scalper.reports")
router = APIRouter()


@router.get("/api/signals")
async def get_signals(limit: int = 100, offset: int = 0, symbol: str = "", action: str = ""):
    return {"signals": await database.get_signals(limit, offset, symbol or None, action or None), "total": await database.get_signal_count(symbol or None, action or None), "limit": limit, "offset": offset}

@router.get("/api/analysis-snapshots/{symbol}")
async def get_analysis_snapshots(symbol: str, limit: int = 50):
    """İşlem açılışında kaydedilen metodoloji snapshot'larını getirir."""
    limit = max(1, min(int(limit), 500))
    def op(conn):
        rows = conn.execute("SELECT * FROM analysis_snapshots WHERE symbol=? ORDER BY captured_at DESC LIMIT ?", (symbol.upper(), limit)).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["payload"] = database._json_value(item.get("payload"), {})
            output.append(item)
        return output
    return {"symbol": symbol.upper(), "snapshots": await database._run_db(op)}


@router.get("/api/symbol-analysis/{symbol}/forecasts")
async def get_symbol_forecasts(symbol: str, limit: int = 30):
    """Read-only forecast journal and measured outcomes for the analysis UI."""
    rows = await database.get_llm_forecasts(symbol=symbol, limit=limit)
    evaluated = [row for row in rows if row.get("status") == "evaluated"]
    accuracy = (sum(bool(row.get("direction_correct")) for row in evaluated) / len(evaluated)) if evaluated else None
    return {"symbol": symbol.upper(), "paper_only": True, "forecasts": rows,
            "evaluated_count": len(evaluated), "directional_accuracy": accuracy,
            "evaluator": dict(_forecast_evaluation_state)}


@router.get("/api/reports/llm-forecasts")
async def get_llm_forecast_report():
    """Read-only, all-symbol success view for the report center."""
    horizons = await database.get_llm_forecast_report()
    recent = await database.get_llm_forecasts(limit=20)
    evaluated = sum(int(row.get("evaluated_count") or 0) for row in horizons)
    correct = sum(int(row.get("correct_count") or 0) for row in horizons)
    pending = sum(int(row.get("pending_count") or 0) for row in horizons)
    for row in horizons:
        count = int(row.get("evaluated_count") or 0)
        row["directional_accuracy"] = (int(row.get("correct_count") or 0) / count) if count else None
    return {"paper_only": True, "evaluated_count": evaluated, "correct_count": correct,
            "pending_count": pending, "directional_accuracy": (correct / evaluated) if evaluated else None,
            "horizons": horizons, "recent": recent}

@router.get("/api/reports/llm-chat-forecasts")
async def get_llm_chat_forecast_report():
    """Chat button candidate forecasts only; separate from other LLM forecasts."""
    horizons = await database.get_llm_forecast_report(source="chat")
    recent = await database.get_llm_forecasts(limit=50, source="chat")
    evaluated = sum(int(row.get("evaluated_count") or 0) for row in horizons)
    correct = sum(int(row.get("correct_count") or 0) for row in horizons)
    pending = sum(int(row.get("pending_count") or 0) for row in horizons)
    for row in horizons:
        count = int(row.get("evaluated_count") or 0)
        row["directional_accuracy"] = (int(row.get("correct_count") or 0) / count) if count else None
    return {"paper_only": True, "source": "chat_upside_candidate_buttons", "evaluated_count": evaluated,
            "correct_count": correct, "pending_count": pending,
            "directional_accuracy": (correct / evaluated) if evaluated else None,
            "horizons": horizons, "recent": recent}


@router.get("/api/reports/upside-scout-forecasts")
async def get_upside_scout_forecast_report(limit: int = 100):
    """Upside-scout (en hızlı yükseliş keşfi) journal'ı: hedefe ulaşma başarısı.

    Hedefe ulaşma: ufuk içinde en yüksek fiyat (max_favorable_pct) tahmin
    edilen min_move_pct hedefine değdi mi? Snapshot'lar satırla birlikte döner.
    """
    limit = max(1, min(int(limit), 500))
    horizons = await database.get_llm_forecast_report(source="upside_scout")
    recent = await database.get_llm_forecasts(limit=limit, source="upside_scout")
    now = time.time()
    for row in recent:
        # min_move_pct kesirdir (0.02 = %2); evaluate_forecast ile aynı kural.
        target = row.get("min_move_pct")
        entry = row.get("entry_price")
        row["target_pct_display"] = float(target) * 100 if target is not None else None
        row["target_price"] = (float(entry) * (1 + float(target))
                               if entry and target is not None else None)
        if row.get("status") == "evaluated" and row.get("direction") == "up":
            mfe = row.get("max_favorable_pct")
            row["target_hit"] = (mfe is not None and target is not None and float(mfe) >= float(target))
        else:
            row["target_hit"] = None
        details = row.get("outcome_details") or {}
        row["first_hit_minutes"] = details.get("first_hit_minutes")
        row["eventual_hit"] = bool(details.get("eventual_hit")) if row.get("status") == "evaluated" else None
        row["window_closed"] = bool(row.get("created_at") and
                                    float(row["created_at"]) + int(row.get("horizon_minutes") or 0) * 60 <= now)
        # Gölge mod: ML hedefi vs sabit hedef sapması (ölçülen satırlarda).
        ml_target = (row.get("snapshot") or {}).get("ml_target_pct")
        row["ml_target_pct"] = ml_target
        row["ml_hit_probability"] = (row.get("snapshot") or {}).get("ml_hit_probability")
        if row.get("status") == "evaluated" and row.get("max_favorable_pct") is not None:
            actual_pct = float(row["max_favorable_pct"]) * 100
            row["fixed_error_pct"] = (abs(float(target) * 100 - actual_pct)
                                      if target is not None else None)
            row["ml_error_pct"] = (abs(float(ml_target) - actual_pct)
                                   if ml_target is not None else None)
        else:
            row["fixed_error_pct"] = None
            row["ml_error_pct"] = None
    evaluated = sum(int(row.get("evaluated_count") or 0) for row in horizons)
    correct = sum(int(row.get("correct_count") or 0) for row in horizons)
    target_hits = sum(int(row.get("target_hit_count") or 0) for row in horizons)
    eventual_hits = sum(int(row.get("eventual_hit_count") or 0) for row in horizons)
    pending = sum(int(row.get("pending_count") or 0) for row in horizons)
    for row in horizons:
        count = int(row.get("evaluated_count") or 0)
        row["directional_accuracy"] = (int(row.get("correct_count") or 0) / count) if count else None
        row["target_hit_rate"] = (int(row.get("target_hit_count") or 0) / count) if count else None
        row["eventual_hit_rate"] = (int(row.get("eventual_hit_count") or 0) / count) if count else None
    fixed_errs = [float(r["fixed_error_pct"]) for r in recent if r.get("fixed_error_pct") is not None]
    ml_errs = [float(r["ml_error_pct"]) for r in recent if r.get("ml_error_pct") is not None]
    shadow = {"ml_rows": len(ml_errs),
              "fixed_mae_pct": round(sum(fixed_errs) / len(fixed_errs), 3) if fixed_errs else None,
              "ml_mae_pct": round(sum(ml_errs) / len(ml_errs), 3) if ml_errs else None}
    if shadow["fixed_mae_pct"] is not None and shadow["ml_mae_pct"] is not None:
        shadow["ml_better"] = shadow["ml_mae_pct"] < shadow["fixed_mae_pct"]
        shadow["improvement_pct"] = round(
            (shadow["fixed_mae_pct"] - shadow["ml_mae_pct"]) / shadow["fixed_mae_pct"] * 100, 1)
    # Madencilenen desen dersleri: aktif önce, adaylar sonra.
    pattern_rows = await database.get_llm_forecast_lessons(regime="pattern", status=None, limit=14)
    pattern_rows.sort(key=lambda r: (0 if r.get("status") == "active" else 1,
                                     -(int(r.get("sample_size") or 0))))
    return {"paper_only": True, "source": "upside_scout", "evaluated_count": evaluated,
            "correct_count": correct, "target_hit_count": target_hits,
            "eventual_hit_count": eventual_hits, "pending_count": pending,
            "directional_accuracy": (correct / evaluated) if evaluated else None,
            "target_hit_rate": (target_hits / evaluated) if evaluated else None,
            "eventual_hit_rate": (eventual_hits / evaluated) if evaluated else None,
            "shadow": shadow, "patterns": pattern_rows,
            "horizons": horizons, "recent": recent,
            "evaluator": dict(_forecast_evaluation_state)}


@router.get("/api/reports/chat-predictions")
async def get_chat_predictions_report(symbol: str | None = None, limit: int = 50):
    """Chat M5/M15 prediction journal: measured success + LLM postmortems + insights."""
    horizons = await database.get_chat_prediction_aggregates()
    recent = await database.get_chat_predictions(symbol=symbol, limit=limit)
    insights = await database.get_chat_prediction_insights(limit=12)
    evaluated = sum(int(row.get("evaluated_count") or 0) for row in horizons.get("horizons", []))
    correct = sum(int(row.get("correct_count") or 0) for row in horizons.get("horizons", []))
    pending = sum(int(row.get("pending_count") or 0) for row in horizons.get("horizons", []))
    analyzed = sum(int(row.get("analyzed_count") or 0) for row in horizons.get("horizons", []))
    for row in horizons.get("horizons", []):
        count = int(row.get("evaluated_count") or 0)
        row["directional_accuracy"] = (int(row.get("correct_count") or 0) / count) if count else None
    for row in horizons.get("symbols", []):
        count = int(row.get("evaluated_count") or 0)
        row["directional_accuracy"] = (int(row.get("correct_count") or 0) / count) if count else None
    auto_trade_enabled = config.CHAT_PREDICTION_AUTO_TRADE_ENABLED and \
        (await database.get_llm_setting("llm_paper_trade_enabled", "0")) == "1"
    return {"paper_only": True, "evaluated_count": evaluated, "correct_count": correct,
            "pending_count": pending, "analyzed_count": analyzed,
            "directional_accuracy": (correct / evaluated) if evaluated else None,
            "horizons": horizons.get("horizons", []), "symbols": horizons.get("symbols", []),
            "insights": insights, "recent": recent, "learning_state": dict(_chat_prediction_learning_state),
            "pattern_state": dict(_chat_pattern_state),
            "auto_trade": {"enabled": bool(auto_trade_enabled),
                            "config": {"min_pattern_matches": config.CHAT_PREDICTION_MIN_PATTERN_MATCHES,
                                        "high_confidence_matches": config.CHAT_PREDICTION_HIGH_CONFIDENCE_MATCHES,
                                        "tp_pct": config.CHAT_PREDICTION_TP_PCT, "sl_pct": config.CHAT_PREDICTION_SL_PCT,
                                        "max_hold_seconds": config.CHAT_PREDICTION_MAX_HOLD_SEC,
                                        "max_open_positions": config.CHAT_PREDICTION_MAX_OPEN_POSITIONS,
                                        "order_value_try": config.CHAT_PREDICTION_ORDER_VALUE_TRY},
                            "state": {key: value for key, value in _chat_auto_trade_state.items() if key != "last_enqueued"}}}


@router.get("/api/reports/chat-predictions/insights")
async def get_chat_prediction_insights_endpoint(symbol: str | None = None, horizon_minutes: int | None = None):
    """Learned lessons from analyzed chat predictions; read-only."""
    rows = await database.get_chat_prediction_insights(symbol=symbol, horizon_minutes=horizon_minutes, limit=20)
    return {"paper_only": True, "insights": rows,
            "learning_state": dict(_chat_prediction_learning_state)}


_chat_prediction_replay_state = {"status": "idle", "running": False, "started_at": None, "finished_at": None,
                                  "progress": 0, "total": 0, "message": None, "result": None}


async def _run_chat_prediction_replay(symbols: list[str], lookback_hours: int, horizons: list[int], step_minutes: int):
    """Background replay job; state is polled by the reports UI."""

    def log(message: str):
        _chat_prediction_replay_state["message"] = message

    try:
        runner = chat_prediction_replay.ReplayRunner(
            symbols, lookback_hours=lookback_hours, horizons=horizons, step_minutes=step_minutes,
            fetch_klines=fetch_klines, log=log)
        _chat_prediction_replay_state["total"] = len(runner.symbols)
        result = await runner.run()
        _chat_prediction_replay_state["result"] = result
        _chat_prediction_replay_state["status"] = "completed" if result.get("status") == "ok" else "failed"
        _chat_prediction_replay_state["message"] = None if result.get("status") == "ok" else result.get("message")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("Chat prediction replay failed: %s", exc)
        _chat_prediction_replay_state["status"] = "failed"
        _chat_prediction_replay_state["message"] = str(exc)
    finally:
        _chat_prediction_replay_state["running"] = False
        _chat_prediction_replay_state["finished_at"] = time.time()


@router.get("/api/reports/chat-predictions/replay")
async def get_chat_prediction_replay(lookback_hours: int = 6, horizons: str = "5,15",
                                     step_minutes: int | None = None, symbols: str | None = None,
                                     refresh: bool = False):
    """Causal replay backtest of the chat M5/M15 candidate pipeline.

    Default: last 6 hours, both horizons, at most 20 active symbols. Public
    data only; read-only research that never writes the prediction journal.
    """
    try:
        horizon_list = sorted({int(item) for item in str(horizons).split(",") if item.strip()})
    except ValueError:
        raise HTTPException(status_code=400, detail="horizons virgülle ayrılmış sayı olmalı, örn. 5,15")
    horizon_list = [value for value in horizon_list if value in (5, 15)] or [5, 15]
    lookback_hours = max(1, min(int(lookback_hours), 48))
    step_minutes = max(max(horizon_list), min(int(step_minutes or max(horizon_list)), 240))
    if symbols and symbols.strip():
        symbol_list = [token.strip().upper() for token in symbols.split(",") if token.strip()][:20]
    else:
        symbol_list = [str(symbol).upper() for symbol in config.SYMBOLS][:20]
    if refresh or not _chat_prediction_replay_state.get("result") or not _chat_prediction_replay_state.get("running"):
        if not _chat_prediction_replay_state.get("running"):
            _chat_prediction_replay_state.update({"status": "running", "running": True, "started_at": time.time(),
                                                   "finished_at": None, "progress": 0, "message": "1m verileri yükleniyor…",
                                                   "result": None})
            _start_background(_run_chat_prediction_replay(symbol_list, lookback_hours, horizon_list, step_minutes),
                              "chat-prediction-replay")
    return {"paper_only": True, "state": dict(_chat_prediction_replay_state),
            "parameters": {"lookback_hours": lookback_hours, "horizons": horizon_list,
                            "step_minutes": step_minutes, "symbols": symbol_list}}


@router.get("/api/reports/overview")
async def get_report_overview():
    """Admin Rapor Merkezi Özet sekmesi: yalnız AUTO_PAPER (monitoring bildiriminden
    tetiklenen otonom) işlem verilerini gösterir. Diğer stratejiler (LLM_PAPER,
    GAINER_RADAR, CHAT_PREDICTION, VELOCITY) bu raporda yer almaz — 2026-09-06.
    """
    decision_summary = await database.get_report_decision_summary()
    ap_stats = await database.get_auto_paper_stats()
    symbols = await database.get_auto_paper_symbol_breakdown()
    try:
        balance = await database.get_wallet_balance("TRY")
    except Exception:
        balance = None
    now = time.time()
    total_pnl = (ap_stats or {}).get("total_pnl_try", 0) or 0
    total_commission = round(sum(float(s.get("commission") or 0) for s in symbols), 2)
    overall = {
        "trade_count": (ap_stats or {}).get("closed", 0) or 0,
        "net_pnl": round(total_pnl, 2),
        "winning": (ap_stats or {}).get("winning", 0) or 0,
        "commission": total_commission,
        "open_positions": (ap_stats or {}).get("open", 0) or 0,
        "try_balance": balance or 0,
    }
    return {
        "paper_only": True,
        "generated_at": now,
        "overall": overall,
        "symbols": symbols,
        "decision_summary": decision_summary[:40],
        "open_positions": [],
    }


@router.get("/api/reports/symbols")
async def get_report_symbols(limit: int = 200):
    """Sembol bazlı detaylı rapor: net PnL, başarı, MFE/DD ve ilk/son işlem."""
    limit = max(1, min(int(limit) or 200, 500))
    breakdown = await database.get_report_trade_breakdown()
    symbols = [row for row in breakdown.get("symbols", [])][:limit]
    velocity = await database.get_report_symbol_velocity_quality()
    velocity_by_symbol = {str(row.get("symbol", "")).upper(): row for row in velocity}
    for row in symbols:
        sym = str(row.get("symbol", "")).upper()
        vrow = velocity_by_symbol.get(sym) or {}
        row["velocity_evaluated"] = int(vrow.get("evaluated") or 0)
        row["velocity_touched"] = int(vrow.get("touched") or 0)
        ev = int(vrow.get("evaluated") or 0)
        row["velocity_touch_rate"] = round(int(vrow.get("touched") or 0) / ev * 100, 2) if ev else None
    return {"paper_only": True, "symbols": symbols, "total": len(symbols)}


@router.get("/api/reports/autonomous-log")
async def get_report_autonomous_log(limit: int = 200, offset: int = 0,
                                    symbol: str = "", strategy: str = ""):
    """Geçmiş otonom işlem akışı (signals) — yönetici raporu için salt okunur."""
    limit = max(1, min(int(limit) or 200, 500))
    offset = max(0, int(offset) or 0)
    rows = await database.get_report_autonomous_log(
        limit=limit, offset=offset, symbol=symbol, strategy=strategy)
    return {"paper_only": True, "rows": rows, "limit": limit, "offset": offset,
            "next_offset": offset + len(rows) if len(rows) == limit else None}


@router.get("/api/reports/self-learning")
async def get_report_self_learning(limit: int = 12):
    """Self-learning sistem özeti: dersler + velocity pattern kırılımı + ML durumu.

    Salt okunur; öğrenme sistemi durumunu ve türetilmiş dersleri raporlar.
    Öğrenme hiçbir zaman aktif strateji parametrelerini değiştirmez.
    """
    limit = max(1, min(int(limit) or 12, 50))
    from app.self_learning import build_learning_context
    trades = await database.get_trades(limit=200)
    learning = build_learning_context(trades, limit=200)
    lessons = await database.get_llm_forecast_lessons(limit=limit)
    velocity_patterns = await database.get_velocity_pattern_hit_rates()
    ml_artifact = await database.get_latest_ml_model_artifact()
    return {
        "paper_only": True,
        "learning": learning,
        "lessons": lessons,
        "velocity_patterns": velocity_patterns,
        "ml_artifact": ml_artifact,
    }


@router.get("/api/reports/autonomous-decisions")
async def get_report_autonomous_decisions(limit: int = 100, offset: int = 0,
                                          symbol: str = "", strategy: str = ""):
    """Karar logu özeti (decision_logs) — yönetici raporu için salt okunur."""
    limit = max(1, min(int(limit) or 100, 300))
    offset = max(0, int(offset) or 0)
    decisions = await database.get_decision_logs(limit=limit, offset=offset,
                                                  symbol=symbol or None,
                                                  strategy=strategy or None)
    summary = await database.get_report_decision_summary(symbol=symbol, limit=30)
    return {"paper_only": True, "decisions": decisions, "summary": summary,
            "limit": limit, "offset": offset,
            "next_offset": offset + len(decisions) if len(decisions) == limit else None}


@router.get("/api/reports/capital-lock")
async def get_capital_lock_report():
    """Read-only BB-MFI capital-lock outcomes; never changes positions or rules."""
    return await database.get_capital_lock_report()

@router.get("/api/microstructure-snapshots/{symbol}")
async def get_microstructure_snapshots(symbol: str, limit: int = 500, start: float = 0, end: float = 0):
    """Return archived live spread/depth samples; read-only and paper-only."""
    safe_limit = max(1, min(int(limit), 5000))
    def op(conn):
        clauses = ["symbol=?"]
        values = [symbol.upper()]
        if start:
            clauses.append("captured_at>=?"); values.append(float(start))
        if end:
            clauses.append("captured_at<=?"); values.append(float(end))
        values.append(safe_limit)
        rows = conn.execute(f"SELECT * FROM microstructure_snapshots WHERE {' AND '.join(clauses)} ORDER BY captured_at DESC LIMIT ?", values).fetchall()
        return [dict(row) for row in rows]
    return {"symbol": symbol.upper(), "snapshots": await database._run_db(op), "source": "binance_tr_public_archived", "paper_only": True}

@router.get("/api/research/ma-cascade-shadow")
async def ma_cascade_shadow_status(limit: int = 200, symbol: str = ""):
    """Read-only paper research events for the 1m SMA(7/25/99) hypothesis."""
    records = await database.get_decision_logs(limit=min(max(1, limit) * 4, 500), symbol=symbol or None,
                                               strategy="SMA_CASCADE_SHADOW")
    records = [row for row in records if str(row.get("decision", "")).upper() in {
        "CASCADE_DETECTED", "BREAKOUT_OBSERVED", "OUTCOME_30M",
    }]
    return {
        "paper_only": True,
        "enabled": config.SMA_CASCADE_SHADOW_ENABLED,
        "rule": "closed 1m SMA7>SMA25 crossover, then SMA7>SMA99, then SMA25>SMA99 within the configured window",
        "windows": {
            "max_sequence_minutes": config.SMA_CASCADE_MAX_SEQUENCE_MINUTES,
            "breakout_minutes": config.SMA_CASCADE_BREAKOUT_WINDOW_MINUTES,
            "outcome_minutes": config.SMA_CASCADE_OUTCOME_WINDOW_MINUTES,
        },
        "events": records[:max(1, min(limit, 200))],
    }


@router.get("/api/decisions")
async def get_decisions(limit: int = 500, offset: int = 0, symbol: str = "", strategy: str = ""):
    return {"decisions": await database.get_decision_logs(limit, symbol or None, strategy or None, offset), "limit": limit, "offset": offset}

@router.get("/api/llm/tool-logs")
async def get_llm_tool_logs(limit: int = 500):
    return {"logs": await database.get_llm_tool_logs(limit)}
