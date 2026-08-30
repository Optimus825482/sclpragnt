"""Long-running runtime loops: broadcast, alerts, strategy, radar, activity."""
import asyncio
import time
import logging
from collections import deque
from datetime import datetime, timedelta, timezone

from app.config import config
from app import database
from app.state import market, analyzer
from app.api_common import _start_background, _record_strategy_scan_log
from app.circuit_breaker import breaker as strategy_breaker
from app.technical_analysis import calculate_snapshot, _atr, _bollinger, _cci, _ema, _mfi, _sma
from app.binance_tr_public import klines as fetch_klines, historical_klines, trading_symbols, ticker_24h, top_gainers
from app.sma_cascade_shadow import SmaCascadeShadow
from app.ws_runtime import ws_manager
from app import alerting
from app import memory_service
from app import llm_analysis
import json
from app import migration_monitor
from app.analyzer import ScalpAnalyzer
from app.api_common import _json_safe_positions, correlation_monitor
from app.correlation import cluster_exposure


async def correlation_refresh_loop():
    """S5: periodically recompute BTC/ETH correlations from the candle cache."""
    await asyncio.sleep(300)  # let candles warm up first
    while True:
        try:
            symbols = [s.upper() for s in config.SYMBOLS]
            result = await correlation_monitor.refresh(market, symbols=symbols)
            if result.get("ok") and result.get("updated"):
                print(f"[Correlation] {result['updated']} sembol güncellendi", flush=True)
        except Exception as exc:
            print(f"[Correlation] yenileme hatası: {exc}")
        await asyncio.sleep(config.CORRELATION_REFRESH_SEC)

async def correlation_exposure_status():
    """Current cluster exposure snapshot for gating and the UI."""
    try_balance = await database.get_wallet_balance("TRY")
    equity = try_balance + sum(
        float(p.get("entry_price") or 0) * float(p.get("quantity") or 0)
        for p in analyzer.positions.values())
    return cluster_exposure(analyzer.positions, None, 0.0,
                            correlation_monitor, "BTC", equity)

from app.self_learning import build_learning_context

logger = logging.getLogger("scalper.runtime")


_llm_replenish_lock = asyncio.Lock()
_llm_last_idle_attempt_at = time.time()
_radar_lock = asyncio.Lock()
_top_gainers_lock = asyncio.Lock()
_ws_snapshot_cache = {"tickers": None, "portfolio": None, "generated_at": 0.0}

_radar_snapshot = {"generated_at": 0.0, "items": {}}
_radar_response_cache = {"generated_at": 0.0, "result": None}
_pump_monitor_snapshot = {"generated_at": 0.0, "items": {}, "last_execution": []}
_pump_monitor_seen_candles = {}

async def ws_broadcast_loop():
    while True:
        try:
            if market.tickers:
                tickers = []
                for t in market.tickers.values():
                    item = dict(t)
                    item["avg_volume"] = market.get_avg_volume(t["symbol"])
                    tickers.append(item)
                _ws_snapshot_cache["tickers"] = tickers
                _ws_snapshot_cache["generated_at"] = time.time()
                await ws_manager.broadcast({"type": "tickers", "data": _ws_snapshot_cache["tickers"]})

                try_bal = await database.get_wallet_balance("TRY")
                total_value = try_bal
                open_positions = []
                for sym, pos in analyzer.positions.items():
                    ticker = market.get_ticker(sym)
                    ticker_age = time.time() - float((ticker or {}).get("timestamp", 0) or 0) / 1000 if ticker else float("inf")
                    # A stale/missing ticker must not make a real open position
                    # disappear from equity or reconciliation. Mark it at entry
                    # until a fresh public price arrives.
                    current_price = float((ticker or {}).get("last_price") or pos["entry_price"])
                    current_value = pos["quantity"] * current_price
                    total_value += current_value
                    gross_pnl_try = (current_price - pos["entry_price"]) * pos["quantity"]
                    entry_commission = pos["entry_price"] * pos["quantity"] * config.COMMISSION_PCT
                    pnl_try = gross_pnl_try - entry_commission
                    pnl_pct = (pnl_try / (pos["entry_price"] * pos["quantity"]) * 100) if pos["entry_price"] and pos["quantity"] else 0.0
                    open_positions.append({
                        "symbol": sym, "entry": pos["entry_price"], "current": current_price,
                        "pnl_pct": pnl_pct, "pnl_try": pnl_try, "value": current_value,
                        "entry_time": pos.get("entry_time"), "quantity": pos.get("quantity"),
                        "side": pos.get("side", "LONG"), "stop": pos.get("stop_price"),
                        "take_profit": pos.get("take_profit"), "entry_context": pos.get("entry_context"),
                        "strategy": pos.get("strategy", "UT"), "price_stale": ticker_age > config.MAX_TICKER_AGE_SEC,
                        "price_age_seconds": round(ticker_age, 2) if ticker_age != float("inf") else None,
                        "llm_managed": pos.get("strategy") == "LLM_PAPER",
                        "llm_stop_price": pos.get("llm_stop_price"),
                        "llm_take_profit_price": pos.get("llm_take_profit_price"),
                        "llm_max_hold_sec": pos.get("llm_max_hold_sec"),
                        "plan_revision": (pos.get("entry_context") or {}).get("plan_revision", 0),
                        "last_plan_reason": (pos.get("entry_context") or {}).get("last_plan_reason"),
                    })
                open_positions.sort(key=lambda item: float(item.get("entry_time") or 0), reverse=True)
                realized_pnl = await database.get_realized_pnl()
                unrealized_pnl = sum(item["pnl_try"] for item in open_positions)
                # pnl_try above already nets each position's entry commission;
                # subtracting it again here double-counted open fees.
                reconciliation_expected = config.INITIAL_BALANCE_TRY + realized_pnl + unrealized_pnl
                reconciliation_delta = total_value - reconciliation_expected
                _ws_snapshot_cache["portfolio"] = {"try": try_bal, "total_value": total_value, "realized_pnl": realized_pnl,
                                                    "unrealized_pnl": unrealized_pnl, "reconciliation_expected": reconciliation_expected,
                                                    "reconciliation_delta": reconciliation_delta, "positions": open_positions}
                # NaN/±Infinity tek bir WS portfolio mesajını da tüketicilerde
                # bozabilir; /api/positions ile aynı güvenlik uygulanır.
                await ws_manager.broadcast({"type": "portfolio", "data": _json_safe_positions(_ws_snapshot_cache["portfolio"])})
        except Exception as exc:
            logger.warning("ws_broadcast_loop hatasi (atlanıyor): %s", exc, exc_info=True)
        await asyncio.sleep(1.0)
async def alert_loop():
    await asyncio.sleep(8)
    while True:
        try:
            for event in await alerting.evaluate_rules(market, on_paper_trigger=auto_open_from_alert):
                await ws_manager.broadcast(event)
        except Exception as exc:
            print(f"[Alerts] değerlendirme hatası: {exc}")
        await asyncio.sleep(1.0)

async def auto_open_from_alert(rule, event):
    """Alarm sonrası mevcut LLM giriş kapılarını yeniden doğrulayıp paper açar."""
    if not config.LLM_AUTO_OPEN_ENABLED:
        return {"status": "blocked", "reason": "llm_automatic_open_disabled", "paper_only": True}
    if (await database.get_llm_setting("llm_paper_trade_enabled", "0")) != "1":
        return {"status": "blocked", "reason": "llm_paper_trading_disabled", "paper_only": True}
    result = await llm_open_paper_trade({
        "symbol": str(rule.get("symbol") or "").upper(),
        "source": "market_alert", "alert_id": rule.get("id"),
        "plan": {"order_value_try": config.DEFAULT_ORDER_USDT,
                 "stop_loss_pct": config.HARD_STOP_LOSS_PCT,
                 "take_profit_pct": config.SPOT_PROFIT_TARGET_PCT,
                 "max_hold_seconds": config.MAX_POSITION_HOLD_SEC},
    })
    signal = result.get("signal") or {}
    return {"status": "opened" if signal.get("action") == "BUY_SIGNAL" else "blocked",
            "symbol": rule.get("symbol"), "signal": signal, "details": result, "paper_only": True}

def _pump_monitor_snapshot_for(symbol: str, timeframe: str, price: float, order_value: float):
    """Return a completed-candle technical snapshot from the hot public cache."""
    bars = market.get_ut_kline(symbol, timeframe) or {}
    daily = market.get_ut_kline(symbol, "1d") or {}
    return calculate_snapshot(
        symbol, price, {timeframe: bars, "1d": daily}, market.get_orderflow(symbol),
        market.ticker_24h.get(symbol, 0), order_value, timeframe,
    )


async def strategy_loop():
    await asyncio.sleep(5)
    # Entry checks are aligned to the exchange 5m candle boundary, not to
    # the process start time or a drifting sleep interval. Position
    # management continues every loop between candle closes.
    scan_interval = max(60, int(config.STRATEGY_ENTRY_SCAN_INTERVAL_SEC))
    last_entry_candle = int(time.time() // scan_interval)
    while True:
        current_candle = int(time.time() // scan_interval)
        entry_scan_due = current_candle != last_entry_candle
        scan_checked = scan_fresh = scan_stale = scan_evaluated = scan_no_signal = scan_errors = scan_passive = scan_ineligible = 0
        scan_buy = scan_blocked = 0
        scan_id = f"automatic-{int(time.time() * 1000)}" if entry_scan_due else None
        if entry_scan_due:
            print(f"[Strategy] giriş taraması başladı | symbols={len(config.SYMBOLS)} trigger=5m_candle_close", flush=True)
        for sym in config.SYMBOLS:
            if sym in config.PASSIVE_SYMBOLS and sym not in analyzer.positions:
                scan_passive += 1
                if entry_scan_due:
                    _record_strategy_scan_log("automatic", sym, "PASSIVE", scan_id=scan_id)
                continue
            scan_checked += 1
            if migration_monitor.state["status"] == "running":
                if entry_scan_due:
                    _record_strategy_scan_log("automatic", sym, "MIGRATION_BLOCKED", scan_id=scan_id)
                await asyncio.sleep(0.1)
                continue
            ticker = market.get_ticker(sym)
            if not ticker or (time.time() - (ticker.get("timestamp", 0) / 1000)) > config.MAX_TICKER_AGE_SEC:
                scan_stale += 1
                if entry_scan_due:
                    _record_strategy_scan_log("automatic", sym, "STALE_TICKER", scan_id=scan_id)
                continue
            kline_freshness = market.kline_freshness(sym, config.ACTIVE_STRATEGY_TIMEFRAME)
            allow_entry = entry_scan_due and bool(kline_freshness.get("fresh"))
            if entry_scan_due and not allow_entry:
                scan_stale += 1
                _record_strategy_scan_log("automatic", sym, "STALE_KLINE", scan_id=scan_id,
                                          timeframe=config.ACTIVE_STRATEGY_TIMEFRAME,
                                          age_sec=kline_freshness.get("age_sec"))
            if allow_entry and sym not in analyzer.positions:
                eligible, eligibility = await analyzer.entry_liquidity_preflight(sym, config.ACTIVE_STRATEGY)
                if not eligible:
                    scan_ineligible += 1
                    allow_entry = False
                    _record_strategy_scan_log(
                        "automatic", sym, "ENTRY_INELIGIBLE", price=ticker.get("last_price"),
                        reason=eligibility.get("reason", "entry_ineligible"),
                        timeframe=config.ACTIVE_STRATEGY_TIMEFRAME, scan_id=scan_id,
                        liquidity=eligibility,
                    )
            scan_fresh += 1
            try:
                if allow_entry:
                    scan_evaluated += 1
                signals = await analyzer.evaluate(sym, ticker, allow_entry=allow_entry)
                if allow_entry and not signals:
                    scan_no_signal += 1
                    _record_strategy_scan_log("automatic", sym, "NO_SIGNAL", price=ticker.get("price"), timeframe=config.ACTIVE_STRATEGY_TIMEFRAME, scan_id=scan_id)
            except Exception as exc:
                scan_errors += 1
                # Tek bir sembolün DB/strateji hatası bütün strategy loop'u düşürmemeli.
                print(f"[Strategy] {sym} değerlendirme hatası: {exc}")
                if entry_scan_due:
                    _record_strategy_scan_log("automatic", sym, "ERROR", error=str(exc), scan_id=scan_id)
                continue
            for sig in signals:
                action = str(sig.get("action", ""))
                if action == "BUY_SIGNAL": scan_buy += 1
                elif action == "BUY_BLOCKED": scan_blocked += 1
                print(f"[Sinyal] {sig}")
                _record_strategy_scan_log("automatic", sym, str(sig.get("action", "SIGNAL")), price=sig.get("price", ticker.get("last_price")), reason=sig.get("reason"), timeframe=config.ACTIVE_STRATEGY_TIMEFRAME, scan_id=scan_id)
                if action != "ENTRY_INELIGIBLE":
                    await ws_manager.broadcast({"type": "signal", "data": sig})
                if str(sig.get("action", "")).startswith("CLOSE"):
                    await ws_manager.broadcast({"type": "trade_updated", "data": {"symbol": sig.get("symbol"), "reason": sig.get("reason")}})
                    # An LLM close is a risk decision, not an instruction to
                    # immediately buy again. Let the symbol guard settle and
                    # wait for a later idle research cycle.
                    if str(sig.get("strategy", "")).upper() != "LLM_PAPER":
                        pass
        if entry_scan_due:
            last_entry_candle = current_candle
            print("[Strategy] giriş taraması tamamlandı", flush=True)
            print(
                f"[Strategy] scan summary | checked={scan_checked} passive={scan_passive} "
                f"fresh={scan_fresh} stale={scan_stale} evaluated={scan_evaluated} "
                f"no_signal={scan_no_signal} ineligible={scan_ineligible} buy={scan_buy} blocked={scan_blocked} errors={scan_errors}",
                flush=True,
            )
        await asyncio.sleep(2)


def _ma_cascade_observation_context(symbol: str, event: dict) -> dict:
    """Attach current radar/liquidity context without turning it into a gate."""
    ticker = market.get_ticker(symbol) or {}
    flow = market.get_orderflow(symbol) or {}
    price = float(event.get("price") or ticker.get("last_price") or 0)
    bid_qty = float(flow.get("bid_qty") or 0)
    ask_qty = float(flow.get("ask_qty") or 0)
    total_qty = bid_qty + ask_qty
    bars_5m = market.get_ut_kline(symbol, "5m") or {}
    volumes = list(bars_5m.get("volumes") or [])
    average_volume = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else None
    volume_ratio = float(volumes[-1]) / average_volume if average_volume and volumes else None
    radar = (_radar_snapshot.get("items") or {}).get(symbol.upper())
    return {
        **event,
        "paper_only": True,
        "observation_only": True,
        "m5_volume_ratio_20": volume_ratio,
        "orderflow": {
            "imbalance_pct": ((bid_qty - ask_qty) / total_qty * 100) if total_qty else None,
            "spread_pct": flow.get("spread_pct"),
            "depth_try": total_qty * price if price else None,
            "updated_at": flow.get("updated_at"),
            "source": flow.get("source"),
        },
        "freshness": market.data_freshness(symbol, "1m"),
        "radar": radar,
    }


async def ma_cascade_shadow_loop():
    """Persist closed-candle MA observations; it never calls the trade executor."""
    observer = SmaCascadeShadow(
        config.SMA_CASCADE_MAX_SEQUENCE_MINUTES,
        config.SMA_CASCADE_BREAKOUT_WINDOW_MINUTES,
        config.SMA_CASCADE_OUTCOME_WINDOW_MINUTES,
    )
    await asyncio.sleep(10)
    while True:
        try:
            if config.SMA_CASCADE_SHADOW_ENABLED and migration_monitor.state["status"] != "running":
                for symbol in list(config.SYMBOLS):
                    for event in observer.process(symbol, market.get_ut_kline(symbol, "1m")):
                        metadata = _ma_cascade_observation_context(symbol, event)
                        decision = str(event["type"]).upper()
                        await database.save_decision_log({
                            "timestamp": time.time(), "symbol": symbol, "strategy": "SMA_CASCADE_SHADOW",
                            "decision": decision, "reason": "closed_1m_observation_only",
                            "price": event.get("price"), "metadata": metadata,
                        })
                        _record_strategy_scan_log("ma_cascade_shadow", symbol, decision,
                                                  price=event.get("price"), event_id=event.get("event_id"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("MA cascade shadow monitor error: %s", exc)
        await asyncio.sleep(5)


async def radar_loop():
    await asyncio.sleep(15)
    while True:
        if migration_monitor.state["status"] == "running":
            await asyncio.sleep(1)
            continue
        try:
            await gainers_radar(execute=True)
        except Exception as exc:
            print(f"[Radar] otomatik tarama hatası: {exc}")
        await asyncio.sleep(config.GAINER_RADAR_INTERVAL_SEC)

async def refresh_top_gainer_symbols():
    """Refresh active TRY symbols from Binance TR's public 24h ticker data."""
    if not config.TOP_GAINERS_AUTO_ACTIVATE:
        return {"ok": False, "enabled": False, "symbols": config.SYMBOLS}
    async with _top_gainers_lock:
        all_tickers = await ticker_24h()
        known_try = set(await trading_symbols("TRY"))
        ranked = []
        for item in all_tickers or []:
            symbol = str(item.get("symbol", "")).replace("_", "").upper()
            if symbol not in known_try:
                continue
            try:
                change = float(item.get("priceChangePercent", 0) or 0)
                volume = float(item.get("quoteVolume", 0) or 0)
            except (TypeError, ValueError):
                continue
            ranked.append({"symbol": symbol, "change_pct": change, "quote_volume": volume})
        ranked.sort(key=lambda row: (row["change_pct"], row["quote_volume"]), reverse=True)
        selected = [row["symbol"] for row in ranked[:config.TOP_GAINERS_LIMIT]]
        open_symbols = set(analyzer.positions) | set((await database.load_positions()).keys())
        active = list(dict.fromkeys(selected + sorted(open_symbols)))
        previous_active = set(str(symbol).upper() for symbol in market.symbols)
        if not active:
            raise RuntimeError("Binance TR top-gainer TRY listesi boş döndü")
        config.SYMBOLS = active
        config.UT_SYMBOLS = list(active)
        market.symbols = [symbol.lower() for symbol in active]
        # Newly activated symbols would otherwise wait ~4.6h on the WS alone
        # to collect enough closed 5m candles; hydrate them up front so MTF
        # gates are usable from the first scan.
        new_symbols = sorted(set(active) - previous_active)
        if new_symbols:
            try:
                hydration = await market.ensure_history(
                    market._all_timeframes(), min_candles=55, candle_limit=300)
                print(f"[Top Gainers] {len(new_symbols)} yeni sembol hidrasyonu: "
                      f"{hydration.get('hydrated', 0)} seri dolduruldu", flush=True)
            except Exception as exc:
                print(f"[Top Gainers] Yeni sembol hidrasyon hatası: {exc}", flush=True)
        market.reconnect_requested = True
        analyzer._last_signal_lengths.clear()
        persisted = await database.get_llm_setting("runtime_config", "{}")
        try:
            runtime = json.loads(persisted or "{}")
        except json.JSONDecodeError:
            runtime = {}
        runtime.update({"symbols": active, "ut_symbols": active,
                        "top_gainers_limit": config.TOP_GAINERS_LIMIT,
                        "top_gainers_refreshed_at": time.time()})
        await database.set_llm_setting("runtime_config", json.dumps(runtime, ensure_ascii=False))
        try:
            from app import universe_registry
            await universe_registry.record_universe(active, source="top_gainers")
        except Exception as exc:
            print(f"[Universe] kayıt hatası: {exc}", flush=True)
        return {"ok": True, "enabled": True, "limit": config.TOP_GAINERS_LIMIT,
                "symbols": active, "selected": selected,
                "preserved_open_positions": sorted(open_symbols),
                "generated_at": time.time(), "source": "binance_tr_public_24h_ticker"}

async def top_gainers_refresh_loop():
    await asyncio.sleep(10)
    while True:
        try:
            result = await refresh_top_gainer_symbols()
            if result.get("ok"):
                print(f"[Top Gainers] {len(result.get('selected', []))} TRY sembolü aktive edildi")
        except Exception as exc:
            print(f"[Top Gainers] {config.TOP_GAINERS_REFRESH_SEC // 60} dakikalık yenileme hatası: {exc}")
        await asyncio.sleep(config.TOP_GAINERS_REFRESH_SEC)

def _is_real_candle(high: float, low: float) -> bool:
    """Gerçek bir mum mu? High ve Low farklı olmalı."""
    if low <= 0:
        return False
    range_pct = (high - low) / low * 100
    return range_pct > 0.001  # En az %0.001 hareket


def _all_same(values: list) -> bool:
    """Tüm değerler birbirine eşit mi?"""
    if not values:
        return True
    first = values[0]
    return all(abs(v - first) < 1e-10 for v in values)


def _comprehensive_passive_analysis(m1_bars: dict, m5_bars: dict, now_ms: int) -> dict:
    """Kapsamlı pasif sembol tespiti: son 50 M1 mum + son 30 M5 mum analizi.
    
    Bir sembolün gerçekten pasif olup olmadığını anlamak için:
    1. M1 (1dk): Son 50 mumun hacim, hareket ve flat oranını analiz eder
    2. M5 (5dk): Son 30 mumun aynı metriklerini analiz eder
    3. Her iki timeframe'da da pasif işaretler arar
    """
    def analyze_timeframe(bars: dict, lookback: int, name: str) -> dict:
        """Tek bir timeframe için derinlemesine analiz."""
        timestamps = list((bars or {}).get("timestamps") or [])
        closes = list((bars or {}).get("closes") or [])
        highs = list((bars or {}).get("highs") or [])
        lows = list((bars or {}).get("lows") or [])
        volumes = list((bars or {}).get("volumes") or [])
        
        # Sadece tamamlanmış mumları al (şu anki mum hariç)
        completed_timestamps = []
        completed_closes = []
        completed_highs = []
        completed_lows = []
        completed_volumes = []
        
        for i in range(len(timestamps)):
            try:
                ts = int(timestamps[i])
                # Mum tamamlanmışsa (şu anki zamandan önce bitmişse)
                bar_interval = 60_000 if name == "M1" else 300_000  # M1=60sn, M5=300sn
                if ts + bar_interval <= now_ms:
                    completed_timestamps.append(ts)
                    completed_closes.append(float(closes[i]))
                    completed_highs.append(float(highs[i]))
                    completed_lows.append(float(lows[i]))
                    completed_volumes.append(float(volumes[i]))
            except (TypeError, ValueError):
                continue
        
        if len(completed_closes) < lookback:
            return {
                "name": name,
                "ready": False,
                "reason": f"yetersiz_veri: {len(completed_closes)}/{lookback}",
                "sample_count": len(completed_closes),
            }
        
        # Son N mumu al
        closes_n = completed_closes[-lookback:]
        highs_n = completed_highs[-lookback:]
        lows_n = completed_lows[-lookback:]
        volumes_n = completed_volumes[-lookback:]
        
        # YENİ: Gerçek mum tespiti - H-L farkı olmalı ve OHLC birbirine eşit olmamalı
        real_candle_count = 0
        for h, l in zip(highs_n, lows_n):
            if _is_real_candle(h, l):
                real_candle_count += 1
        
        # Son 10 M1 için en az 7, son 5 M5 için en az 3 gerçek mum olmalı
        required_real = 7 if name == "M1" else 3
        required_total = 10 if name == "M1" else 5
        real_candle_ratio = real_candle_count / min(required_total, len(highs_n)) if highs_n else 0
        
        # Gerçek mum oranı kontrolü
        sufficient_real_candles = real_candle_count >= required_real
        
        # 1. HACİM ANALİZİ (sadece gerçek mumlarla)
        real_volumes = [v for h, l, v in zip(highs_n, lows_n, volumes_n) if _is_real_candle(h, l)]
        avg_volume = sum(real_volumes) / len(real_volumes) if real_volumes else 0
        current_volume = volumes_n[-1] if volumes_n else 0
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        # Son 10 mumun hacim ortalaması (kısa vadeli)
        short_avg = sum(volumes_n[-10:]) / min(10, len(volumes_n)) if len(volumes_n) >= 2 else avg_volume
        short_volume_ratio = current_volume / short_avg if short_avg > 0 else 0
        
        # 2. HAREKET ANALİZİ (sadece gerçek mumlarla)
        valid_ranges = [(highs_n[i] - lows_n[i]) / lows_n[i] * 100 
                        for i in range(len(highs_n)) 
                        if lows_n[i] > 0 and _is_real_candle(highs_n[i], lows_n[i])]
        
        price_range = max(highs_n) - min(lows_n) if highs_n and lows_n else 0
        avg_price = sum(closes_n) / len(closes_n) if closes_n else 0
        range_pct = (price_range / avg_price * 100) if avg_price > 0 else 0
        
        # Mum başına ortalama hareket (sadece gerçek mumlarla)
        candle_moves = []
        for i in range(1, len(closes_n)):
            if _is_real_candle(highs_n[i], lows_n[i]) and closes_n[i-1] > 0:
                move = abs(closes_n[i] - closes_n[i-1]) / closes_n[i-1] * 100
                candle_moves.append(move)
        avg_candle_move = sum(candle_moves) / len(candle_moves) if candle_moves else 0
        
        # 3. FLAT MUM ANALİZİ
        flat_threshold = 0.02  # %0.02'den az hareket = flat
        flat_count = 0
        for high, low in zip(highs_n, lows_n):
            if _is_real_candle(high, low):
                candle_range = (high - low) / low * 100
                if candle_range <= flat_threshold:
                    flat_count += 1
        flat_ratio = flat_count / real_candle_count if real_candle_count > 0 else 1.0
        
        # 4. SON MUMUN HAREKET DURUMU
        last_is_real = _is_real_candle(highs_n[-1], lows_n[-1]) if highs_n and lows_n else False
        last_range = (highs_n[-1] - lows_n[-1]) / lows_n[-1] * 100 if lows_n[-1] and last_is_real else 0
        last_direction = "up" if closes_n[-1] > closes_n[-2] else "down" if closes_n[-1] < closes_n[-2] else "flat"
        
        # 5. VOLATILITY (ATR benzeri - sadece gerçek mumlarla)
        true_ranges = []
        for i in range(1, len(closes_n)):
            if _is_real_candle(highs_n[i], lows_n[i]) and closes_n[i-1] > 0:
                tr = max(
                    highs_n[i] - lows_n[i],
                    abs(highs_n[i] - closes_n[i-1]),
                    abs(lows_n[i] - closes_n[i-1])
                )
                true_ranges.append(tr)
        avg_tr = sum(true_ranges) / len(true_ranges) if true_ranges else 0
        volatility_pct = (avg_tr / avg_price * 100) if avg_price > 0 else 0
        
        return {
            "name": name,
            "ready": True,
            "sample_count": len(closes_n),
            "real_candle_count": real_candle_count,
            "real_candle_ratio": round(real_candle_ratio, 4),
            "sufficient_real_candles": sufficient_real_candles,
            # Hacim metrikleri
            "volume_ratio": round(volume_ratio, 4),
            "short_volume_ratio": round(short_volume_ratio, 4),
            "current_volume": round(current_volume, 2),
            "avg_volume": round(avg_volume, 2),
            # Hareket metrikleri
            "range_pct": round(range_pct, 4),
            "avg_candle_move_pct": round(avg_candle_move, 4),
            "last_candle_range_pct": round(last_range, 4),
            "last_direction": last_direction,
            "last_is_real_candle": last_is_real,
            "volatility_pct": round(volatility_pct, 4),
            # Flat analizi
            "flat_count": flat_count,
            "flat_ratio": round(flat_ratio, 4),
        }
    
    # Her iki timeframe'ı analiz et
    m1_analysis = analyze_timeframe(m1_bars, 50, "M1")
    m5_analysis = analyze_timeframe(m5_bars, 30, "M5")
    
    # PASIF KARARI
    def is_passive(tf: dict) -> tuple[bool, str]:
        """Tek timeframe için pasif kararı verir.
        
        ÖNEMLİ: Gerçek mum = High > Low. Çizgi veri (H=L) = mum yok!
        """
        if not tf.get("ready", False):
            return True, f"veri_yok ({tf.get('reason', 'bilinmiyor')})"
        
        # YENİ: Gerçek mum sayısı yetersizse KESİNLİKLE pasif say
        real_count = tf.get("real_candle_count", 0)
        required = 7 if tf["name"] == "M1" else 3
        sample_count = tf.get("sample_count", 0)
        
        # M1: Son 10 mumdan en az 7'si, M5: Son 5 mumdan en az 3'ü gerçek mum olmalı
        if real_count < required:
            return True, f"yetersiz_gercek_mum:{real_count}/{required}"
        
        # Tüm son N mumların gerçek mum olup olmadığını kontrol et
        # (AITRY gibi vr=0.00 ama flat=0.00% olanlar için)
        real_ratio = real_count / sample_count if sample_count > 0 else 0
        
        # Eğer gerçek mum oranı çok düşükse pasif
        min_real_ratio = 0.70  # En az %70'i gerçek mum olmalı
        if real_ratio < min_real_ratio:
            return True, f"dusuk_gercek_mum_orani:{real_ratio:.0%}"
        
        # Gerçek mum oranı yeterli ama flat oranı çok yüksekse pasif
        if tf["flat_ratio"] > 0.7:
            return True, "cok_fazla_flat_mum"
        
        return False, "aktif"
    
    m1_passive, m1_reason = is_passive(m1_analysis)
    m5_passive, m5_reason = is_passive(m5_analysis)
    
    # Birleşik karar: Her iki timeframe'da da pasif olmalı
    is_purely_passive = m1_passive and m5_passive
    
    return {
        "ready": m1_analysis.get("ready", False) and m5_analysis.get("ready", False),
        "is_passive": is_purely_passive,
        "confidence": "high" if (m1_passive and m5_passive) or (not m1_passive and not m5_passive) else "low",
        "m1": m1_analysis,
        "m5": m5_analysis,
        "m1_passive": m1_passive,
        "m1_reason": m1_reason,
        "m5_passive": m5_passive,
        "m5_reason": m5_reason,
        "combined_reason": f"M1={m1_reason}, M5={m5_reason}" if is_purely_passive else "her_iki_timeframe_da_aktif",
    }


def _m1_flat_candle_activity(bars: dict, now_ms: int) -> dict:
    """Measure only completed M1 candles whose high-low range is flat."""
    timestamps = list((bars or {}).get("timestamps") or [])
    highs = list((bars or {}).get("highs") or [])
    lows = list((bars or {}).get("lows") or [])
    usable = []
    for timestamp, high, low in zip(timestamps, highs, lows):
        try:
            timestamp, high, low = int(timestamp), float(high), float(low)
        except (TypeError, ValueError):
            continue
        if timestamp + 60_000 > now_ms or low <= 0:
            continue
        usable.append((high - low) / low * 100)
    recent_30 = usable[-30:]
    recent_5 = recent_30[-5:]
    max_range_pct = float(config.SYMBOL_ACTIVITY_M1_FLAT_MAX_RANGE_PCT)
    return {
        "ready": len(recent_30) >= 30,
        "flat_max_range_pct": max_range_pct,
        "flat_5m_count": sum(value <= max_range_pct for value in recent_5),
        "flat_30m_count": sum(value <= max_range_pct for value in recent_30),
        "sample_5m": len(recent_5),
        "sample_30m": len(recent_30),
    }

def _m1_activity_features(indicator_analyzer: ScalpAnalyzer, bars: dict, now_ms: int) -> dict:
    """Observation-only M1 context for later inactivity-filter research.

    Every value uses only completed M1 candles.  These fields deliberately do
    not make a symbol active/passive yet: their job is to label later replay
    candidates without introducing a look-ahead or an unvalidated live rule.
    """
    closed = {key: [] for key in ("closes", "highs", "lows", "volumes")}
    for values in zip(bars.get("timestamps") or [], bars.get("closes") or [], bars.get("highs") or [], bars.get("lows") or [], bars.get("volumes") or []):
        timestamp, close, high, low, volume = values
        try:
            if int(timestamp) + 60_000 > now_ms:
                continue
            for key, value in zip(closed, (close, high, low, volume)):
                closed[key].append(float(value))
        except (TypeError, ValueError):
            continue
    if len(closed["closes"]) < 101:
        return {"ready": False}
    closes, highs, lows, volumes = (closed[key] for key in ("closes", "highs", "lows", "volumes"))
    bb = _bollinger(closes, 20, 2.0) or {}
    atr = _atr(highs, lows, closes, 14) or 0.0
    vwap_volume = sum(volumes[-20:])
    vwap = (sum(close * volume for close, volume in zip(closes[-20:], volumes[-20:])) / vwap_volume) if vwap_volume else None
    price = closes[-1]
    donchian_high, donchian_low = max(highs[-20:]), min(lows[-20:])
    donchian_span = donchian_high - donchian_low
    money_flow_multiplier = [
        ((close - low) - (high - close)) / (high - low) if high != low else 0.0
        for high, low, close in zip(highs[-20:], lows[-20:], closes[-20:])
    ]
    cmf_volume = sum(volumes[-20:])
    cmf_20 = (
        sum(multiplier * volume for multiplier, volume in zip(money_flow_multiplier, volumes[-20:])) / cmf_volume
        if cmf_volume else None
    )
    force = [(closes[index] - closes[index - 1]) * volumes[index] for index in range(1, len(closes))]
    efi_13 = _ema(force, 13)
    # Raw EFI scales with the market's volume and price.  Normalising it by
    # recent traded value makes it comparable across TRY symbols.
    recent_traded_value = sum(close * volume for close, volume in zip(closes[-13:], volumes[-13:]))
    efi_13_normalized = (efi_13 / recent_traded_value * 100) if efi_13 is not None and recent_traded_value else None

    def ema_series(values: list[float], period: int) -> list[float]:
        if len(values) < period:
            return []
        alpha = 2.0 / (period + 1)
        current = sum(values[:period]) / period
        result = [current]
        for value in values[period:]:
            current = alpha * value + (1 - alpha) * current
            result.append(current)
        return result

    momentum = [closes[index] - closes[index - 1] for index in range(1, len(closes))]
    first_momentum = ema_series(momentum, 25)
    first_absolute_momentum = ema_series([abs(value) for value in momentum], 25)
    double_momentum = ema_series(first_momentum, 13)
    double_absolute_momentum = ema_series(first_absolute_momentum, 13)
    tsi_25_13 = (
        double_momentum[-1] / double_absolute_momentum[-1] * 100
        if double_momentum and double_absolute_momentum and double_absolute_momentum[-1] else None
    )
    atr_series = [
        max(highs[index] - lows[index], abs(highs[index] - closes[index - 1]), abs(lows[index] - closes[index - 1]))
        for index in range(1, len(closes))
    ]
    atr_ema_13 = _ema(atr_series, 13)
    return {
        "ready": True,
        "rsi_14": round(float(indicator_analyzer.calculate_rsi(closes, 14) or 0), 4),
        "mfi_14": round(float(_mfi(highs, lows, closes, volumes, 14) or 0), 4),
        "cmo_9": round(float(indicator_analyzer.calculate_cmo(closes, 9) or 0), 4),
        "crsi": round(float(indicator_analyzer.calculate_crsi(closes) or 0), 4),
        "atr_pct": round(atr / closes[-1] * 100, 5) if closes[-1] else None,
        "bb_width_pct": round(float(bb.get("width_pct") or 0) * 100, 5),
        "bb_position": round(float(bb.get("position") or 0), 4) if bb.get("position") is not None else None,
        "vwap_distance_pct": round((closes[-1] / vwap - 1) * 100, 5) if vwap else None,
        "ema_7_25_gap_pct": round(abs((_ema(closes, 7) or 0) / (_ema(closes, 25) or closes[-1]) - 1) * 100, 5),
        "ema_25_99_gap_pct": round(abs((_ema(closes, 25) or 0) / (_ema(closes, 99) or closes[-1]) - 1) * 100, 5),
        "cci_20": round(float(_cci(highs, lows, closes, 20) or 0), 4),
        "sma_7_25_gap_pct": round(abs((_sma(closes, 7) or 0) / (_sma(closes, 25) or price) - 1) * 100, 5),
        "sma_25_99_gap_pct": round(abs((_sma(closes, 25) or 0) / (_sma(closes, 99) or price) - 1) * 100, 5),
        "donchian_20_width_pct": round(donchian_span / price * 100, 5) if price else None,
        "donchian_20_position": round((price - donchian_low) / donchian_span, 4) if donchian_span else None,
        "cmf_20": round(cmf_20, 5) if cmf_20 is not None else None,
        "efi_13_normalized_pct": round(efi_13_normalized, 6) if efi_13_normalized is not None else None,
        "tsi_25_13": round(tsi_25_13, 4) if tsi_25_13 is not None else None,
        "atr_ema_13_pct": round(atr_ema_13 / price * 100, 5) if atr_ema_13 is not None and price else None,
    }

async def refresh_symbol_activity():
    """Refresh the full Binance TR TRY universe and mark inactive symbols."""
    known_try = set(await trading_symbols("TRY"))
    open_symbols = set(analyzer.positions) | set((await database.load_positions()).keys())
    universe = list(dict.fromkeys(sorted(known_try | open_symbols)))
    if not universe:
        raise RuntimeError("Binance TR TRY sembol evreni boş döndü")
    # Activity is an observation over the public TRY universe. It must not
    # replace the user's configured paper-trading scan universe; otherwise a
    # background refresh silently activates every Binance TR symbol in
    # Settings and makes the strategy loop scan symbols the user did not pick.
    all_tickers = await ticker_24h()
    market.ticker_24h = {
        str(row.get("symbol", "")).upper(): float(row.get("quoteVolume", 0) or 0)
        for row in all_tickers or [] if row.get("symbol")
    }
    now_ms = int(time.time() * 1000)
    tracked_symbols = set(config.SYMBOLS) | open_symbols
    m1_bars = {symbol: market.get_ut_kline(symbol, "1m") or {} for symbol in tracked_symbols}
    missing_m1 = [symbol for symbol, bars in m1_bars.items() if len(bars.get("timestamps") or []) < 30]
    if missing_m1:
        semaphore = asyncio.Semaphore(8)
        async def hydrate_m1(symbol):
            async with semaphore:
                try:
                    rows = await fetch_klines(symbol, "1m", limit=150)
                    return symbol, {
                        "timestamps": [int(row[0]) for row in rows or []],
                        "closes": [float(row[4]) for row in rows or []],
                        "highs": [float(row[2]) for row in rows or []],
                        "lows": [float(row[3]) for row in rows or []],
                        "volumes": [float(row[5]) for row in rows or []],
                    }
                except Exception as exc:
                    print(f"[Activity M1] {symbol}: {exc}", flush=True)
                    return symbol, {}
        for symbol, bars in await asyncio.gather(*(hydrate_m1(symbol) for symbol in missing_m1)):
            if bars.get("timestamps"):
                m1_bars[symbol] = bars
    # M5 mumlarını al (kapsamlı analiz için)
    m5_bars = {symbol: market.get_ut_kline(symbol, "5m") or {} for symbol in tracked_symbols}
    missing_m5 = [symbol for symbol, bars in m5_bars.items() if len(bars.get("closes") or []) < 30]
    if missing_m5:
        semaphore_m5 = asyncio.Semaphore(8)
        async def hydrate_m5(symbol):
            async with semaphore_m5:
                try:
                    rows = await fetch_klines(symbol, "5m", limit=80)
                    return symbol, {
                        "timestamps": [int(row[0]) for row in rows or []],
                        "closes": [float(row[4]) for row in rows or []],
                        "highs": [float(row[2]) for row in rows or []],
                        "lows": [float(row[3]) for row in rows or []],
                        "volumes": [float(row[5]) for row in rows or []],
                    }
                except Exception as exc:
                    print(f"[Activity M5] {symbol}: {exc}", flush=True)
                    return symbol, {}
        for symbol, bars in await asyncio.gather(*(hydrate_m5(symbol) for symbol in missing_m5)):
            if bars.get("closes"):
                m5_bars[symbol] = bars
    statuses = {}
    for symbol in universe:
        ticker = market.get_ticker(symbol) or {}
        quote_volume = float(market.ticker_24h.get(symbol, 0) or 0)
        bars = market.get_ut_kline(symbol, "5m")
        closes = bars.get("closes", [])
        highs = bars.get("highs", [])
        lows = bars.get("lows", [])
        # Websocket/REST geçmişi henüz ısınmadıysa bu sembolü düşük hareketli
        # sanma; aktivasyon kararı sonraki kontrolde verilecek.
        if not ticker or len(closes) < 7 or len(highs) < 7 or len(lows) < 7:
            statuses[symbol] = {
                "symbol": symbol, "status": "WARMING",
                "quote_volume": quote_volume, "range_15m_pct": None,
                "reason": "market_data_warming", "checked_at": time.time(),
            }
            continue
        m1_activity = _m1_flat_candle_activity(m1_bars.get(symbol) or {}, now_ms)
        m1_features = _m1_activity_features(analyzer, m1_bars.get(symbol) or {}, now_ms)
        
        # YENİ: Kapsamlı pasif analizi (M1 50 mum + M5 30 mum)
        comprehensive = _comprehensive_passive_analysis(
            m1_bars.get(symbol) or {},
            m5_bars.get(symbol) or {},
            now_ms
        )
        
        range_pct = 0.0
        low, high = min(lows[-3:]), max(highs[-3:])
        range_pct = ((high - low) / low * 100) if low else 0.0
        volume_ok = quote_volume >= config.SYMBOL_ACTIVITY_MIN_QUOTE_VOLUME_TRY
        movement_ok = range_pct >= config.SYMBOL_ACTIVITY_MIN_RANGE_15M_PCT
        atr = analyzer.calculate_atr(bars, 14) if len(closes) >= 15 else None
        atr_pct = (atr / closes[-1]) if atr and closes[-1] else 0.0
        avg_volume = sum(bars.get("volumes", [])[-21:-1]) / max(1, len(bars.get("volumes", [])[-21:-1])) if len(bars.get("volumes", [])) >= 21 else 0.0
        volume_ratio = (bars.get("volumes", [])[-1] / avg_volume) if avg_volume else 0.0
        flow = market.get_orderflow(symbol) or {}
        spread_pct = float(flow.get("spread_pct") or 0.0)
        atr_ok = atr_pct >= config.SYMBOL_ACTIVITY_MIN_ATR_PCT
        volume_ratio_ok = volume_ratio >= config.SYMBOL_ACTIVITY_MIN_VOLUME_RATIO
        spread_ok = (spread_pct <= config.SYMBOL_ACTIVITY_MAX_SPREAD_PCT if spread_pct else False)
        spread_required = config.SYMBOL_ACTIVITY_SPREAD_FILTER_ENABLED
        spread_gate_ok = spread_ok if spread_required else True
        movement_gate_ok = True if config.SYMBOL_ACTIVITY_VOLUME_ONLY else (movement_ok and atr_ok)
        flat_5m_blocked = m1_activity["flat_5m_count"] >= config.SYMBOL_ACTIVITY_M1_FLAT_5M_MAX_COUNT
        flat_30m_blocked = m1_activity["flat_30m_count"] >= config.SYMBOL_ACTIVITY_M1_FLAT_30M_MAX_COUNT
        m1_flat_ok = (not config.SYMBOL_ACTIVITY_M1_FLAT_FILTER_ENABLED or
                      not m1_activity["ready"] or not (flat_5m_blocked or flat_30m_blocked))
        
        # YENİ: Kapsamlı pasif kontrolü - M1 ve M5'de de pasif olmalı
        truly_passive = comprehensive.get("is_passive", False)
        
        active = bool(ticker and volume_ok and movement_gate_ok and volume_ratio_ok and spread_gate_ok and m1_flat_ok and not truly_passive)
        flat_reason = (f"m1_flat_candles:5m={m1_activity['flat_5m_count']}/5,"
                       f"30m={m1_activity['flat_30m_count']}/30")
        statuses[symbol] = {
            "symbol": symbol, "status": "ACTIVE" if active else "PASSIVE",
            "quote_volume": quote_volume, "range_15m_pct": round(range_pct, 4),
            "atr_pct": round(atr_pct * 100, 4), "volume_ratio": round(volume_ratio, 4),
            "spread_pct": round(spread_pct, 4),
            "m1_flat_5m_count": m1_activity["flat_5m_count"],
            "m1_flat_30m_count": m1_activity["flat_30m_count"],
            "m1_flat_sample_30m": m1_activity["sample_30m"],
            "m1_flat_max_range_pct": m1_activity["flat_max_range_pct"],
            "m1_features": m1_features,
            # YENİ: Kapsamlı pasif analiz sonuçları
            "comprehensive_passive": {
                "is_passive": comprehensive.get("is_passive", False),
                "confidence": comprehensive.get("confidence", "unknown"),
                "m1": comprehensive.get("m1", {}),
                "m5": comprehensive.get("m5", {}),
                "m1_passive": comprehensive.get("m1_passive", False),
                "m1_reason": comprehensive.get("m1_reason", ""),
                "m5_passive": comprehensive.get("m5_passive", False),
                "m5_reason": comprehensive.get("m5_reason", ""),
                "combined_reason": comprehensive.get("combined_reason", ""),
            },
            "checks": {"quote_volume": volume_ok, "range_15m": movement_ok, "atr": atr_ok, "volume_ratio": volume_ratio_ok, "spread": spread_ok, "m1_flat_candles": m1_flat_ok, "comprehensive_passive": not truly_passive},
            "gates": {"spread_required": spread_required, "volume_only": config.SYMBOL_ACTIVITY_VOLUME_ONLY, "m1_flat_filter_enabled": config.SYMBOL_ACTIVITY_M1_FLAT_FILTER_ENABLED, "m1_flat_data_ready": m1_activity["ready"]},
            "has_open_position": symbol in analyzer.positions,
            "reason": "active" if active else (comprehensive.get("combined_reason", flat_reason if not m1_flat_ok else "volume_or_liquidity_below_threshold")),
            "checked_at": time.time(),
        }
    config.PASSIVE_SYMBOLS = {symbol for symbol, item in statuses.items() if item["status"] == "PASSIVE"}
    config.SYMBOL_ACTIVITY_STATUS = statuses
    await database.set_llm_setting("symbol_activity_status", json.dumps(statuses, ensure_ascii=False))
    active_count = sum(1 for item in statuses.values() if item["status"] == "ACTIVE")
    warming_count = sum(1 for item in statuses.values() if item["status"] == "WARMING")
    
    # Debug: Yeni kapsamlı analiz sonuçlarını logla
    for symbol, status in sorted(statuses.items()):
        comp = status.get("comprehensive_passive", {})
        if comp.get("m1", {}).get("ready") and comp.get("m5", {}).get("ready"):
            m1 = comp.get("m1", {})
            m5 = comp.get("m5", {})
            m1_real = m1.get("real_candle_count", 0)
            m5_real = m5.get("real_candle_count", 0)
            print(f"[Activity Debug] {symbol}: passive={comp.get('is_passive')} | "
                  f"M1: real={m1_real}/10 vr={m1.get('volume_ratio',0):.2f} flat={m1.get('flat_ratio',0):.0%} move={m1.get('avg_candle_move_pct',0):.4f}% | "
                  f"M5: real={m5_real}/5 vr={m5.get('volume_ratio',0):.2f} flat={m5.get('flat_ratio',0):.0%} move={m5.get('avg_candle_move_pct',0):.4f}%", flush=True)
    
    print(f"[Activity] universe={len(universe)} ACTIVE={active_count} PASSIVE={len(config.PASSIVE_SYMBOLS)} WARMING={warming_count}", flush=True)
    return {"ok": True, "statuses": statuses, "active_count": active_count,
            "passive_count": len(config.PASSIVE_SYMBOLS), "warming_count": warming_count}

async def bootstrap_symbol_activity():
    """Warm all symbols enough for the first activity decision before trading starts."""
    known_try = set(await trading_symbols("TRY"))
    open_symbols = set(analyzer.positions) | set((await database.load_positions()).keys())
    universe = list(dict.fromkeys(sorted(known_try | open_symbols)))
    if not universe:
        raise RuntimeError("Binance TR TRY sembol evreni boş döndü")
    # Keep expensive candle/depth WebSocket streams limited to the configured
    # paper universe and open positions. Full-universe discovery uses 24h REST.
    hot_symbols = list(dict.fromkeys([*config.SYMBOLS, *sorted(open_symbols)]))
    market.symbols = [symbol.lower() for symbol in hot_symbols]
    all_tickers = await ticker_24h()
    market.ticker_24h = {str(row.get("symbol", "")).upper(): float(row.get("quoteVolume", 0) or 0) for row in all_tickers or [] if row.get("symbol")}
    semaphore = asyncio.Semaphore(8)
    async def warm(symbol):
        async with semaphore:
            try:
                rows = await fetch_klines(symbol, "5m", limit=80)
                if not rows:
                    return
                hist = market.klines["5m"][symbol]
                for key, index in (("opens", 1), ("highs", 2), ("lows", 3), ("closes", 4), ("volumes", 5)):
                    hist[key] = [float(row[index]) for row in rows]
                market.tickers[symbol] = {"symbol": symbol, "last_price": float(rows[-1][4]), "timestamp": int(time.time() * 1000), "source": "binance_tr_public_rest"}
            except Exception as exc:
                print(f"[Activity warmup] {symbol}: {exc}", flush=True)
    await asyncio.gather(*(warm(symbol) for symbol in hot_symbols))
    result = await refresh_symbol_activity()
    print(f"[Activity] ilk kontrol tamamlandı | universe={len(universe)} active={result['active_count']} passive={result['passive_count']} warming={result['warming_count']}", flush=True)

async def symbol_activity_loop():
    await asyncio.sleep(20)
    while True:
        try:
            await refresh_symbol_activity()
        except Exception as exc:
            print(f"[Activity] sembol aktivite kontrolü başarısız: {exc}", flush=True)
        await asyncio.sleep(config.SYMBOL_ACTIVITY_REFRESH_SEC)

async def llm_replenish_after_close():
    """Replace each closed paper position with one fresh eligible candidate."""
    if not config.LLM_AUTO_OPEN_ENABLED:
        print("[LLM replenish] atlandı: otomatik LLM pozisyon açma kapalı")
        return
    if (await database.get_llm_setting("llm_auto_paper_enabled", "0")) != "1":
        print("[LLM replenish] tetikleme atlandı: otomatik paper yenileme ayarı kapalı")
        return
    if (await database.get_llm_setting("llm_paper_trade_enabled", "0")) != "1":
        print("[LLM replenish] tetikleme atlandı: LLM paper işlem yetkisi kapalı")
        return
    async with _llm_replenish_lock:
        if len(analyzer.positions) >= analyzer.max_open_positions():
            print("[LLM replenish] tetikleme atlandı: maksimum açık pozisyon limiti dolu")
            return
        try:
            result = await llm_open_paper_trade({"source": "llm_after_close"})
            signal = result.get("signal") or {}
            print(f"[LLM replenish] kapanış sonrası yeni paper işlem: {signal.get('symbol')} action={signal.get('action')}")
            global _llm_last_idle_attempt_at
            _llm_last_idle_attempt_at = time.time()
        except Exception as exc:
            print(f"[LLM replenish] yeni aday bulunamadı: {exc}")

async def llm_idle_trigger_loop():
    """Trigger LLM paper research after 10 minutes of idle time and cash."""
    global _llm_last_idle_attempt_at
    await asyncio.sleep(15)
    while True:
        try:
            if not config.LLM_AUTO_OPEN_ENABLED:
                await asyncio.sleep(30)
                continue
            enabled = (await database.get_llm_setting("llm_auto_paper_enabled", "0")) == "1"
            paper_enabled = (await database.get_llm_setting("llm_paper_trade_enabled", "0")) == "1"
            balance = float(await database.get_wallet_balance("TRY") or 0)
            idle = time.time() - _llm_last_idle_attempt_at
            if enabled and paper_enabled and balance > 100.0 and idle >= 10 * 60:
                async with _llm_replenish_lock:
                    # Re-check after waiting for a concurrent close-triggered run.
                    now = time.time()
                    if now - _llm_last_idle_attempt_at < 10 * 60:
                        continue
                    _llm_last_idle_attempt_at = now
                    try:
                        result = await llm_open_paper_trade({"source": "llm_idle_10m", "balance_try": balance})
                        signal = result.get("signal") or {}
                        print(f"[LLM idle] 10 dakika sonrası paper işlem: {signal.get('symbol')} action={signal.get('action')} balance={balance:.2f}")
                    except Exception as exc:
                        print(f"[LLM idle] aday bulunamadı/işlem açılmadı: {exc}")
        except Exception as exc:
            print(f"[LLM idle] tetikleyici hatası: {exc}")
        await asyncio.sleep(15)
