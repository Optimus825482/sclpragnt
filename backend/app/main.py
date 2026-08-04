import os
import asyncio
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config import config
from app.market_data import MarketData
from app.analyzer import ScalpAnalyzer
from app import database
from app.backtest import run_backtest
from app.binance_tr_public import trading_symbols, ticker_24h

app = FastAPI(title="Scalper Agent V4 - Paper Trading")
cors_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3004,http://localhost:3000").split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

market = MarketData(config.SYMBOLS)
analyzer = ScalpAnalyzer(market)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WELL_KNOWN_DIR = os.path.join(BASE_DIR, "..", ".well-known")
app.mount("/.well-known", StaticFiles(directory=WELL_KNOWN_DIR), name="wellknown")

class ConnectionManager:
    def __init__(self): self.active_connections = []
    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.append(ws)
    def disconnect(self, ws: WebSocket):
        if ws in self.active_connections: self.active_connections.remove(ws)
    async def broadcast(self, message: dict):
        for c in list(self.active_connections):
            try: await c.send_json(message)
            except: self.disconnect(c)

ws_manager = ConnectionManager()

@app.on_event("startup")
async def startup():
    await database.init_db()
    await analyzer.load_state()
    asyncio.create_task(market.connect())
    asyncio.create_task(strategy_loop())
    asyncio.create_task(radar_loop())
    asyncio.create_task(ws_broadcast_loop())

@app.on_event("shutdown")
async def shutdown():
    market.stop()
    await database.close_db()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect: ws_manager.disconnect(websocket)

async def ws_broadcast_loop():
    while True:
        if market.tickers:
            tickers = []
            for t in market.tickers.values():
                item = dict(t)
                item["avg_volume"] = market.get_avg_volume(t["symbol"])
                tickers.append(item)
            await ws_manager.broadcast({"type": "tickers", "data": tickers})
            
            try_bal = await database.get_wallet_balance("TRY")
            total_value = try_bal
            open_positions = []
            for sym, pos in analyzer.positions.items():
                ticker = market.get_ticker(sym)
                if ticker:
                    current_value = pos["quantity"] * ticker["last_price"]
                    total_value += current_value
                    pnl_pct = ((ticker["last_price"] - pos["entry_price"]) / pos["entry_price"]) * 100
                    pnl_try = (ticker["last_price"] - pos["entry_price"]) * pos["quantity"]
                    open_positions.append({
                        "symbol": sym, "entry": pos["entry_price"], "current": ticker["last_price"],
                        "pnl_pct": pnl_pct, "pnl_try": pnl_try, "value": current_value, "strategy": pos.get("strategy", "UT")
                    })
                    
            await ws_manager.broadcast({
                "type": "portfolio", 
                "data": {"try": try_bal, "total_value": total_value, "positions": open_positions}
            })
        await asyncio.sleep(1.0)

async def strategy_loop():
    await asyncio.sleep(5)
    while True:
        for sym in config.SYMBOLS:
            ticker = market.get_ticker(sym)
            if not ticker or (time.time() - (ticker.get("timestamp", 0) / 1000)) > config.MAX_TICKER_AGE_SEC:
                continue
            signals = await analyzer.evaluate(sym, ticker)
            for sig in signals:
                print(f"[Sinyal] {sig}")
                await ws_manager.broadcast({"type": "signal", "data": sig})
        await asyncio.sleep(2)

async def radar_loop():
    await asyncio.sleep(15)
    while True:
        try:
            await gainers_radar(execute=True)
        except Exception as exc:
            print(f"[Radar] otomatik tarama hatası: {exc}")
        await asyncio.sleep(30)

@app.get("/health")
async def health():
    age = time.time() - market.last_event_at if market.last_event_at else None
    return {
        "status": "alive" if market.running and (age is None or age <= config.MAX_TICKER_AGE_SEC * 2) else "degraded",
        "mode": "paper", "market_data": "binance_tr_public",
        "history_loaded": market.history_loaded, "ticker_age_sec": age,
        "market_error": market.last_error, "open_positions": list(analyzer.positions.keys())
    }

CONFIG_FIELDS = {
    "gainer_radar_min_score": "GAINER_RADAR_MIN_SCORE",
    "min_notional": "MIN_NOTIONAL",
    "default_order_usdt": "DEFAULT_ORDER_USDT",
    "take_profit_pct": "SPOT_PROFIT_TARGET_PCT",
    "ut_enabled": "UT_ENABLED",
    "ut_key_value": "UT_KEY_VALUE",
    "ut_atr_period": "UT_ATR_PERIOD",
    "ut_heikin_ashi": "UT_HEIKIN_ASHI",
    "ut_timeframe": "UT_TIMEFRAME",
    "bb_squeeze_enabled": "BB_SQUEEZE_ENABLED",
    "ema_pullback_enabled": "EMA_PULLBACK_ENABLED",
    "vwap_macd_enabled": "VWAP_MACD_ENABLED",
    "cmo_crsi_enabled": "CMO_CRSI_ENABLED",
    "ema_vwap_enabled": "EMA_VWAP_ENABLED",
    "breakout_enabled": "BREAKOUT_ENABLED",
    "orderflow_enabled": "ORDERFLOW_ENABLED",
    "momentum_enabled": "MOMENTUM_ENABLED",
    "mean_reversion_enabled": "MEAN_REVERSION_ENABLED",
    "keltner_enabled": "KELTNER_ENABLED", "chop_enabled": "CHOP_ENABLED", "donchian_enabled": "DONCHIAN_ENABLED",
    "bb_squeeze_timeframe": "BB_SQUEEZE_TIMEFRAME",
    "ema_pullback_timeframe": "EMA_PULLBACK_TIMEFRAME",
    "vwap_macd_timeframe": "VWAP_MACD_TIMEFRAME",
    "cmo_crsi_timeframe": "CMO_CRSI_TIMEFRAME",
    "ema_vwap_timeframe": "EMA_VWAP_TIMEFRAME",
    "breakout_timeframe": "BREAKOUT_TIMEFRAME",
    "orderflow_timeframe": "ORDERFLOW_TIMEFRAME",
    "momentum_timeframe": "MOMENTUM_TIMEFRAME",
    "mean_reversion_timeframe": "MEAN_REVERSION_TIMEFRAME",
    "keltner_timeframe": "KELTNER_TIMEFRAME", "chop_timeframe": "CHOP_TIMEFRAME", "donchian_timeframe": "DONCHIAN_TIMEFRAME",
    "squeeze_lookback": "SQUEEZE_LOOKBACK",
    "bb_period": "BB_PERIOD",
    "bb_std_dev": "BB_STD_DEV",
    "ema_short": "EMA_SHORT",
    "ema_mid": "EMA_MID",
    "ema_trend": "EMA_TREND",
    "rsi_period": "RSI_PERIOD",
    "vwap_period": "VWAP_PERIOD",
    "macd_fast": "MACD_FAST",
    "macd_slow": "MACD_SLOW",
    "macd_signal": "MACD_SIGNAL",
}

BOOL_FIELDS = {"ut_enabled", "ut_heikin_ashi", "bb_squeeze_enabled", "ema_pullback_enabled", "vwap_macd_enabled", "cmo_crsi_enabled", "ema_vwap_enabled", "breakout_enabled", "orderflow_enabled", "momentum_enabled", "mean_reversion_enabled", "keltner_enabled", "chop_enabled", "donchian_enabled"}
INT_FIELDS = {"gainer_radar_min_score", "squeeze_lookback", "bb_period", "ema_short", "ema_mid", "ema_trend", "rsi_period", "vwap_period", "macd_fast", "macd_slow", "macd_signal", "ut_atr_period"}
STR_FIELDS = {"ut_timeframe", "bb_squeeze_timeframe", "ema_pullback_timeframe", "vwap_macd_timeframe", "cmo_crsi_timeframe", "ema_vwap_timeframe", "breakout_timeframe", "orderflow_timeframe", "momentum_timeframe", "mean_reversion_timeframe", "keltner_timeframe", "chop_timeframe", "donchian_timeframe"}

@app.get("/api/config")
async def get_config():
    return {
        "gainer_radar_min_score": config.GAINER_RADAR_MIN_SCORE,
        "symbols": config.SYMBOLS,
        "min_notional": config.MIN_NOTIONAL,
        "default_order_usdt": config.DEFAULT_ORDER_USDT,
        "max_open_positions": max(1, len(config.SYMBOLS) * 2),
        "hard_stop_loss_pct": 0.0,
        "take_profit_pct": config.SPOT_PROFIT_TARGET_PCT,
        "trailing_stop_pct": 0.0,
        "ut_enabled": config.UT_ENABLED,
        "ut_symbols": config.UT_SYMBOLS,
        "ut_key_value": config.UT_KEY_VALUE,
        "ut_atr_period": config.UT_ATR_PERIOD,
        "ut_heikin_ashi": config.UT_HEIKIN_ASHI,
        "ut_timeframe": config.UT_TIMEFRAME,
        "bb_squeeze_enabled": config.BB_SQUEEZE_ENABLED,
        "ema_pullback_enabled": config.EMA_PULLBACK_ENABLED,
        "vwap_macd_enabled": config.VWAP_MACD_ENABLED,
        "cmo_crsi_enabled": config.CMO_CRSI_ENABLED,
        "ema_vwap_enabled": config.EMA_VWAP_ENABLED, "breakout_enabled": config.BREAKOUT_ENABLED,
        "orderflow_enabled": config.ORDERFLOW_ENABLED, "momentum_enabled": config.MOMENTUM_ENABLED,
        "mean_reversion_enabled": config.MEAN_REVERSION_ENABLED,
        "keltner_enabled": config.KELTNER_ENABLED, "chop_enabled": config.CHOP_ENABLED, "donchian_enabled": config.DONCHIAN_ENABLED,
        "bb_squeeze_timeframe": config.BB_SQUEEZE_TIMEFRAME,
        "ema_pullback_timeframe": config.EMA_PULLBACK_TIMEFRAME,
        "vwap_macd_timeframe": config.VWAP_MACD_TIMEFRAME,
        "cmo_crsi_timeframe": config.CMO_CRSI_TIMEFRAME,
        "ema_vwap_timeframe": config.EMA_VWAP_TIMEFRAME, "breakout_timeframe": config.BREAKOUT_TIMEFRAME,
        "orderflow_timeframe": config.ORDERFLOW_TIMEFRAME, "momentum_timeframe": config.MOMENTUM_TIMEFRAME,
        "mean_reversion_timeframe": config.MEAN_REVERSION_TIMEFRAME,
        "keltner_timeframe": config.KELTNER_TIMEFRAME, "chop_timeframe": config.CHOP_TIMEFRAME, "donchian_timeframe": config.DONCHIAN_TIMEFRAME,
        "squeeze_lookback": config.SQUEEZE_LOOKBACK,
        "bb_period": config.BB_PERIOD,
        "bb_std_dev": config.BB_STD_DEV,
        "ema_short": config.EMA_SHORT,
        "ema_mid": config.EMA_MID,
        "ema_trend": config.EMA_TREND,
        "rsi_period": config.RSI_PERIOD,
        "vwap_period": config.VWAP_PERIOD,
        "macd_fast": config.MACD_FAST,
        "macd_slow": config.MACD_SLOW,
        "macd_signal": config.MACD_SIGNAL,
        "initial_balance_try": config.INITIAL_BALANCE_TRY,
        "mode": "paper",
        "market_data": "public",
    }

@app.get("/api/market-symbols")
async def get_market_symbols():
    try:
        return {"symbols": await trading_symbols("TRY"), "quote_asset": "TRY"}
    except Exception as exc:
        return {"symbols": [], "quote_asset": "TRY", "error": str(exc)}

@app.get("/api/radar/gainers")
async def gainers_radar(execute: bool = False):
    """Public-data fırsat tarayıcı: pump kovalamaz, devam edebilecek %2 adaylarını sıralar."""
    rows = []
    radar_analyzer = ScalpAnalyzer(None)
    auto_added = []
    try:
        all_tickers = await ticker_24h()
        known_try = set(await trading_symbols("TRY"))
        gainer_candidates = []
        for item in all_tickers:
            symbol = str(item.get("symbol", "")).upper()
            change = float(item.get("priceChangePercent", 0) or 0)
            quote_volume = float(item.get("quoteVolume", 0) or 0)
            if symbol in known_try and 5 <= change <= 25 and quote_volume >= 100000:
                gainer_candidates.append((change, quote_volume, symbol))
        for _, _, symbol in sorted(gainer_candidates, reverse=True)[:10]:
            if symbol not in config.SYMBOLS:
                config.SYMBOLS.append(symbol)
                config.UT_SYMBOLS = list(config.SYMBOLS)
                if symbol.lower() not in market.symbols:
                    market.symbols.append(symbol.lower())
                    market.reconnect_requested = True
                auto_added.append(symbol)
    except Exception as exc:
        print(f"[Radar] gainer tarama hatası: {exc}")
    for symbol in config.SYMBOLS:
        bars = market.get_ut_kline(symbol, "5m")
        closes, volumes = bars.get("closes", []), bars.get("volumes", [])
        if len(closes) < 25 or len(volumes) < 25:
            continue
        price = closes[-1]
        ret_5m = (closes[-1] / closes[-2] - 1) * 100
        ret_1h = (closes[-1] / closes[-13] - 1) * 100 if len(closes) >= 13 else 0
        ret_24h = (closes[-1] / closes[0] - 1) * 100
        avg_volume = sum(volumes[-21:-1]) / 20
        volume_ratio = volumes[-1] / avg_volume if avg_volume else 0
        flow = market.get_orderflow(symbol)
        bid, ask = flow.get("bid_qty", 0), flow.get("ask_qty", 0)
        imbalance = ((bid - ask) / (bid + ask) * 100) if bid + ask else 0
        spread = flow.get("spread_pct") or 999
        ema9 = sum(closes[-9:]) / 9
        ema21 = sum(closes[-21:]) / 21
        trend = price > ema9 > ema21
        crsi = radar_analyzer.calculate_crsi(closes)
        crsi_score = 10 if crsi is not None and 20 <= crsi <= 75 else 0
        score = 0
        score += min(max(volume_ratio / 2, 0), 20)
        score += min(max(imbalance, 0), 25)
        score += 20 if trend else 0
        score += min(max(ret_1h * 3, 0), 15)
        score += 10 if 0 < spread <= 0.20 else 0
        score += crsi_score
        eligible = 5 <= ret_24h <= 25 and ret_1h > 0 and volume_ratio >= 1.5 and spread <= 0.20 and crsi is not None and 15 <= crsi <= 85 and score >= config.GAINER_RADAR_MIN_SCORE
        rows.append({"symbol": symbol, "price": price, "score": round(score, 1), "eligible": eligible,
                     "ret_5m": round(ret_5m, 2), "ret_1h": round(ret_1h, 2), "ret_24h": round(ret_24h, 2),
                     "volume_ratio": round(volume_ratio, 2), "imbalance": round(imbalance, 2), "spread": round(spread, 3), "trend": trend, "crsi": round(crsi, 2) if crsi is not None else None})
    rows.sort(key=lambda row: row["score"], reverse=True)
    radar_trades = []
    if execute and config.GAINER_RADAR_AUTO_TRADE:
        for candidate in [row for row in rows if row["eligible"]][:1]:
            symbol = candidate["symbol"]
            ticker = market.get_ticker(symbol)
            if ticker and symbol not in analyzer.positions:
                bars = market.get_ut_kline(symbol, "5m")
                closes = bars.get("closes", [])
                macd, macd_signal, hist = radar_analyzer.calculate_macd(closes, config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL) if len(closes) >= 35 else (None, None, None)
                rsi = radar_analyzer.calculate_rsi(closes, 14) if closes else None
                if macd is not None and hist is not None and macd > macd_signal and hist > 0 and rsi is not None and rsi < 70:
                    signal = await analyzer.open_position(symbol, ticker["last_price"], "LONG", "GAINER_RADAR")
                    if signal:
                        radar_trades.append(signal)
                        await ws_manager.broadcast({"type": "signal", "data": signal})
    return {"items": rows[:20], "auto_added": auto_added, "symbols": config.SYMBOLS, "paper_trades": radar_trades,
            "auto_trade": config.GAINER_RADAR_AUTO_TRADE, "generated_at": time.time(), "model": "public_data_continuation_2pct"}

@app.post("/api/radar/execute")
async def execute_gainers_radar():
    return await gainers_radar(execute=True)

@app.put("/api/config")
async def update_config(payload: dict):
    for key, attr in CONFIG_FIELDS.items():
        if key in payload:
            val = payload[key]
            if key in BOOL_FIELDS:
                if isinstance(val, str):
                    val = val.strip().lower() in {"1", "true", "yes", "on"}
                setattr(config, attr, bool(val))
            elif key in INT_FIELDS:
                number = int(val)
                if key == "max_open_positions" and not 1 <= number <= 17:
                    raise ValueError("max_open_positions 1 ile 17 arasında olmalıdır")
                if key == "gainer_radar_min_score" and not 0 <= number <= 100:
                    raise ValueError("gainer_radar_min_score 0 ile 100 arasında olmalıdır")
                setattr(config, attr, number)
            elif key in STR_FIELDS:
                setattr(config, attr, str(val))
            else:
                number = float(val)
                if key in {"min_notional", "default_order_usdt"} and number <= 0:
                    raise ValueError(f"{key} pozitif olmalıdır")
                if key in {"hard_stop_loss_pct", "take_profit_pct", "trailing_stop_pct"} and not 0 < number < 1:
                    raise ValueError(f"{key} 0 ile 1 arasında olmalıdır")
                setattr(config, attr, number)
    if "ut_symbols" in payload:
        config.UT_SYMBOLS = payload["ut_symbols"]
    if "symbols" in payload:
        symbols = sorted({str(s).replace("_", "").upper() for s in payload["symbols"] if str(s).strip()})
        allowed = set(await trading_symbols("TRY"))
        invalid = sorted(set(symbols) - allowed)
        if invalid:
            raise ValueError(f"Binance TR'de geçersiz TRY sembolü: {', '.join(invalid)}")
        if not symbols:
            raise ValueError("En az bir aktif sembol seçilmelidir")
        config.SYMBOLS = symbols
        config.UT_SYMBOLS = symbols
        market.symbols = [s.lower() for s in symbols]
        market.timeframes = market._all_timeframes()
    # timeframe değiştiyse market veri setini güncelle
    market.timeframes = market._all_timeframes()
    return await get_config()

@app.get("/api/chart/{symbol}")
async def get_chart_settings(symbol: str):
    data = await database.get_chart_settings(symbol)
    if data is None:
        return {"symbol": symbol, "settings": None}
    return {"symbol": symbol, "settings": data}

@app.put("/api/chart/{symbol}")
async def save_chart_settings(symbol: str, payload: dict):
    await database.save_chart_settings(symbol, payload)
    return {"symbol": symbol, "saved": True}

@app.get("/api/positions")
async def get_positions():
    positions = []
    for sym, pos in analyzer.positions.items():
        ticker = market.get_ticker(sym)
        current = ticker["last_price"] if ticker else pos["entry_price"]
        pnl_pct = ((current - pos["entry_price"]) / pos["entry_price"]) * 100 if pos["entry_price"] else 0.0
        pnl_try = (current - pos["entry_price"]) * pos["quantity"]
        positions.append({
            "symbol": sym,
            "side": pos["side"],
            "strategy": pos.get("strategy", "UT"),
            "entry": pos["entry_price"],
            "current": current,
            "pnl_pct": pnl_pct,
            "pnl_try": pnl_try,
            "quantity": pos["quantity"],
            "entry_time": pos.get("entry_time"),
            "stop": pos.get("stop_price"),
            "take_profit": pos.get("take_profit")
        })
    return {"positions": positions}

@app.post("/api/positions/{symbol}/close")
async def close_position_manual(symbol: str):
    """Açık pozisyonu manuel kapat (komisyon + işlem geçmişi dahil)."""
    ticker = market.get_ticker(symbol)
    price = ticker["last_price"] if ticker else None
    if price is None:
        return {"ok": False, "message": f"{symbol} için güncel fiyat bulunamadı"}
    sig = await analyzer.close_position(symbol.upper(), price, "manual_close")
    if not sig:
        return {"ok": False, "message": f"{symbol} için açık pozisyon yok"}
    await ws_manager.broadcast({"type": "signal", "data": sig})
    return {"ok": True, "message": f"{symbol} kapatıldı @ {price:.2f}", "signal": sig}

@app.get("/api/trades")
async def get_trades():
    """Kapanan pozisyonların işlem geçmişi."""
    return {"trades": await database.get_trades()}

@app.get("/api/strategies/stats")
async def get_strategy_stats():
    """Her stratejinin başarı istatistikleri (işlem sayısı, kazanma oranı, PnL)."""
    trades = await database.get_trades()
    stats = {}
    for t in trades:
        s = stats.setdefault(t["strategy"], {"trades": 0, "wins": 0, "pnl": 0.0, "commission": 0.0})
        s["trades"] += 1
        s["pnl"] += t["pnl"] or 0.0
        s["commission"] += t["commission"] or 0.0
        if (t["pnl"] or 0.0) > 0:
            s["wins"] += 1
    for s in stats.values():
        s["win_rate"] = (s["wins"] / s["trades"] * 100) if s["trades"] else 0.0
    return {"stats": stats}

@app.post("/api/reset")
async def reset_all():
    """Paper trading geçmişini ve açık pozisyonları sil, cüzdanı 10.000 TRY'ye sıfırla."""
    analyzer.positions.clear()
    await database.reset_trading_data()
    await ws_manager.broadcast({"type": "reset", "data": {"ok": True}})
    return {"ok": True, "message": "Paper trading kayıtları silindi, cüzdan 10.000 TRY'ye sıfırlandı"}

@app.post("/api/backtest/run")
async def backtest_run(payload: dict):
    """Backtest çalıştır ve sonucu DB'ye kaydet."""
    symbol = str(payload.get("symbol", "BTCTRY")).upper()
    interval = str(payload.get("interval", "5m"))
    days_back = int(payload.get("days_back", 30))
    strategy = str(payload.get("strategy", "EMA_VWAP_PULLBACK"))
    params = payload.get("params") or {}
    order_size = float(payload.get("order_size", 500.0))
    stop_pct = float(payload.get("stop_loss_pct", 0.005))
    tp_pct = float(payload.get("take_profit_pct", 0.015))
    trail_pct = float(payload.get("trailing_stop_pct", 0.003))
    try:
        run_id, result = await run_backtest(
            symbol, interval, days_back, strategy, params,
            order_size, stop_pct, tp_pct, trail_pct
        )
        return {"ok": True, "run_id": run_id, "result": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/backtests")
async def backtest_list(limit: int = 50):
    """Kayıtlı backtest sonuçları."""
    return {"backtests": await database.get_backtests(limit)}

@app.delete("/api/backtests/{run_id}")
async def backtest_delete(run_id: int):
    await database.delete_backtest(run_id)
    return {"ok": True}
