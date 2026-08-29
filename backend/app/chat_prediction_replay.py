"""Causal replay backtest for Chat M5/M15 upside-candidate predictions.

Replays the exact live pipeline against historical Binance TR public klines:
at each horizon boundary in the lookback window it rebuilds a snapshot that
only sees candles closed before that moment, ranks candidates with the same
deterministic scoring, then measures each pick against closed M1 candles
afterwards.  Live endpoints, order flow and 24h tickers are not available
historically, so spread/depth fields stay unknown — the same "missing values
remain unknown" policy the live path uses.  The replay is read-only research
and never touches the prediction journal.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict

from app.forecast_learning import evaluate_forecast
from app.technical_analysis import calculate_snapshot


DEFAULT_HORIZONS = (5, 15)
DEFAULT_LOOKBACK_HOURS = 6
MIN_SYMBOL_CANDLES = 60  # calculate_snapshot needs >= 55 closed bars
MAX_SCAN_SYMBOLS = 20
MAX_CANDIDATES_PER_STEP = 3


def _resample_1m(rows: list, factor: int) -> dict:
    """Aggregate closed 1m kline rows into `factor`-minute OHLCV buckets."""
    result = {"opens": [], "highs": [], "lows": [], "closes": [], "volumes": [], "timestamps": []}
    if factor <= 1:
        for row in rows:
            try:
                result["timestamps"].append(int(row[0])); result["opens"].append(float(row[1]))
                result["highs"].append(float(row[2])); result["lows"].append(float(row[3]))
                result["closes"].append(float(row[4])); result["volumes"].append(float(row[5]))
            except (TypeError, ValueError, IndexError):
                continue
    else:
        bucket = []
        for row in rows:
            try:
                bucket.append((int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])))
            except (TypeError, ValueError, IndexError):
                continue
            if len(bucket) == factor:
                result["timestamps"].append(bucket[0][0])
                result["opens"].append(bucket[0][1])
                result["highs"].append(max(item[2] for item in bucket))
                result["lows"].append(min(item[3] for item in bucket))
                result["closes"].append(bucket[-1][4])
                result["volumes"].append(sum(item[5] for item in bucket))
                bucket = []
    if result["timestamps"]:
        result["last_closed_at_ms"] = result["timestamps"][-1]
    return result


def _atr_pct(closes: list[float], highs: list[float], lows: list[float]) -> float:
    if len(closes) < 15:
        return 0.0
    period = 14
    trs = []
    for index in range(len(closes) - period, len(closes)):
        prev = closes[index - 1]
        trs.append(max(highs[index] - lows[index], abs(highs[index] - prev), abs(lows[index] - prev)))
    atr = sum(trs) / len(trs) if trs else 0.0
    return atr / closes[-1] if closes[-1] else 0.0


def _candidate_score(snapshot: dict) -> tuple[float, list[str], list[str]]:
    """Mirrors main._market_candidate_score minus execution-quality, which
    needs live spread/depth. Missing microstructure is a known replay gap."""
    trend = snapshot.get("trend") or {}
    momentum = snapshot.get("momentum") or {}
    volume = snapshot.get("volume") or {}
    regime = (((snapshot.get("methodologies") or {}).get(snapshot.get("timeframe") or "5m") or {})
              .get("regime") or {}).get("name")
    score, evidence, risks = 0.0, [], []
    alignment = str(trend.get("alignment") or "").lower()
    if alignment == "bullish":
        score += 2.5; evidence.append("EMA hizalaması bullish")
    elif alignment == "bearish":
        score -= 2.5; risks.append("EMA hizalaması bearish")
    else:
        risks.append("EMA hizalaması karışık")
    adx = trend.get("adx")
    if isinstance(adx, dict):
        adx = adx.get("adx")
    if adx is not None:
        if float(adx) >= 20:
            score += 1.0; evidence.append(f"ADX {float(adx):.1f} ile trend gücü var")
        else:
            risks.append(f"ADX düşük ({float(adx):.1f})")
    for key in ("return_5m", "return_15m", "return_1h"):
        value = momentum.get(key)
        if value is not None:
            score += 0.35 if float(value) > 0 else (-0.35 if float(value) < 0 else 0)
    if float(momentum.get("return_15m") or 0) > 0 and float(momentum.get("return_1h") or 0) > 0:
        score += 1.0; evidence.append("15m ve 1h momentum aynı yönde")
    vr = volume.get("volume_ratio_20")
    if vr is not None and float(vr) >= 1.1:
        score += 0.6; evidence.append("hacim ortalamanın üzerinde")
    elif vr in (None, 0):
        risks.append("hacim verisi eksik veya sıfır")
    if regime and str(regime).startswith("bull"):
        score += 0.8; evidence.append(f"rejim {regime}")
    return round(score, 3), evidence, risks


def _label_policy(horizon_minutes: int, atr_pct: float) -> dict:
    from app.config import config
    noise_ratio = 0.25 if horizon_minutes == 5 else 0.35
    min_move_pct = max(config.LLM_FORECAST_MIN_MOVE_PCT,
                       config.min_net_exit_pct(config.DEFAULT_ORDER_USDT) * 1.05,
                       atr_pct * noise_ratio)
    return {"min_move_pct": min_move_pct, "atr_pct": atr_pct, "noise_ratio": noise_ratio,
            "round_trip_cost_floor": config.min_net_exit_pct(config.DEFAULT_ORDER_USDT)}


def _close_time(row) -> int:
    return int(row[0]) + 59_999


class ReplayRunner:
    def __init__(self, symbols: list[str], *, lookback_hours: int, horizons: list[int],
                 step_minutes: int, fetch_klines, log=None):
        self.symbols = symbols
        self.lookback_hours = lookback_hours
        self.horizons = horizons
        self.step_minutes = max(step_minutes, max(horizons))
        self.fetch_klines = fetch_klines  # injected to reuse the live public-data client
        self.log = log or (lambda message: None)

    async def _load_symbol_data(self, symbol: str) -> dict | None:
        """Fetch one 1m series long enough for every replay step."""
        span_ms = (self.lookback_hours * 60 + max(self.horizons) + self.step_minutes) * 60_000
        bars_needed = int(span_ms / 60_000) + 20
        try:
            rows = await self.fetch_klines(symbol, "1m", min(1000, max(300, bars_needed)))
        except Exception as exc:
            self.log(f"{symbol} 1m verisi alınamadı: {exc}")
            return None
        rows = [row for row in rows if _close_time(row) <= int(row[0]) + 59_999]  # closed bars only
        if len(rows) < MIN_SYMBOL_CANDLES:
            self.log(f"{symbol} yeterli kapalı 1m mum yok ({len(rows)})")
            return None
        return {"rows_1m": rows}

    def _snapshot_at(self, symbol: str, data: dict, decision_ms: int) -> dict | None:
        """Snapshot strictly from candles closed at or before decision_ms."""
        rows = [row for row in data["rows_1m"] if _close_time(row) <= decision_ms]
        if len(rows) < MIN_SYMBOL_CANDLES:
            return None
        entry_index = len(rows) - 1
        klines_by_tf = {"1m": _resample_1m(rows, 1)}
        for tf, factor in (("3m", 3), ("5m", 5), ("15m", 15)):
            klines_by_tf[tf] = _resample_1m(rows, factor)
        primary = "5m" if 5 in self.horizons else "15m"
        price = float(rows[-1][4])
        snapshot = calculate_snapshot(symbol, price, klines_by_tf, {}, 0, 0, primary)
        if not snapshot.get("data_ready"):
            return None
        volatility = snapshot.get("volatility") or {}
        atr_pct = float(volatility.get("atr_pct") or _atr_pct(klines_by_tf["1m"]["closes"],
                                                              klines_by_tf["1m"]["highs"],
                                                              klines_by_tf["1m"]["lows"]))
        snapshot["atr_pct"] = atr_pct
        snapshot["_entry_index"] = entry_index
        snapshot["_rows"] = rows
        return snapshot

    def _measure(self, prediction: dict, data: dict, decision_ms: int) -> dict | None:
        """Causal outcome from closed M1 candles between entry and due time."""
        rows = [row for row in data["rows_1m"] if _close_time(row) > decision_ms]
        due_ms = decision_ms + prediction["horizon_minutes"] * 60_000
        window = [row for row in rows if _close_time(row) <= due_ms]
        if len(window) < prediction["horizon_minutes"]:
            return None
        highs = [float(row[2]) for row in window]
        lows = [float(row[3]) for row in window]
        observed = {
            "outcome_price": float(window[-1][4]),
            "max_high": max(highs),
            "min_low": min(lows),
        }
        return evaluate_forecast(prediction, evaluated_at=due_ms / 1000, **observed)

    async def run(self) -> dict:
        from app.config import config
        now_ms = int(time.time() * 1000)
        loaded = {}
        for symbol in self.symbols[:MAX_SCAN_SYMBOLS]:
            data = await self._load_symbol_data(symbol)
            if data:
                loaded[symbol] = data
        if not loaded:
            return {"status": "no_data", "message": "Hiçbir sembol için yeterli kapalı 1m mum alınamadı.", "paper_only": True}

        end_ms = max(max(_close_time(row) for row in data["rows_1m"]) for data in loaded.values())
        first_ms = min(min(int(row[0]) for row in data["rows_1m"]) for data in loaded.values())
        window_ms = self.lookback_hours * 3_600_000
        start_ms = max(first_ms, end_ms - window_ms)
        steps = []
        step_ms = self.step_minutes * 60_000
        cursor = ((start_ms // step_ms) + 1) * step_ms
        while cursor + max(self.horizons) * 60_000 <= end_ms:
            steps.append(cursor)
            cursor += step_ms

        per_horizon: dict[int, dict] = {h: {"predictions": 0, "evaluated": 0, "correct": 0, "range": 0,
                                             "sum_return": 0.0, "sum_confidence": 0.0, "calibration": 0.0}
                                         for h in self.horizons}
        per_symbol: dict[str, dict] = defaultdict(lambda: {"evaluated": 0, "correct": 0, "sum_return": 0.0})
        picks = []
        for decision_ms in steps:
            ranked = []
            for symbol, data in loaded.items():
                snapshot = self._snapshot_at(symbol, data, decision_ms)
                if not snapshot:
                    continue
                score, evidence, risks = _candidate_score(snapshot)
                ranked.append((symbol, snapshot, score, evidence, risks))
            ranked.sort(key=lambda item: item[2], reverse=True)
            for symbol, snapshot, score, evidence, risks in ranked[:MAX_CANDIDATES_PER_STEP]:
                if str(snapshot.get("summary") or "").lower() == "bearish":
                    continue
                atr_pct = float(snapshot.get("atr_pct") or 0)
                for horizon in self.horizons:
                    policy = _label_policy(horizon, atr_pct)
                    prediction = {"entry_price": float(snapshot["price"]), "direction": "up",
                                  "confidence": max(35.0, min(85.0, 50.0 + score * 8.0)),
                                  "min_move_pct": policy["min_move_pct"], "horizon_minutes": horizon}
                    outcome = self._measure(prediction, loaded[symbol], decision_ms)
                    bucket = per_horizon[horizon]
                    bucket["predictions"] += 1
                    entry = {"decision_at": decision_ms / 1000, "symbol": symbol, "horizon_minutes": horizon,
                             "score": score, "confidence": prediction["confidence"], "entry_price": prediction["entry_price"],
                             "evidence": evidence[:3], "risks": risks[:3]}
                    if outcome is None:
                        entry["status"] = "unmeasured"
                    else:
                        bucket["evaluated"] += 1
                        entry.update({"status": "evaluated", "direction_correct": bool(outcome["direction_correct"]),
                                      "outcome_return_pct": outcome["outcome_return_pct"],
                                      "outcome_direction": outcome["outcome_direction"],
                                      "max_favorable_pct": outcome["max_favorable_pct"],
                                      "max_adverse_pct": outcome["max_adverse_pct"]})
                        if outcome["direction_correct"]:
                            bucket["correct"] += 1
                            entry["correct"] = True
                        if outcome["outcome_direction"] == "range":
                            bucket["range"] += 1
                        bucket["sum_return"] += float(outcome["outcome_return_pct"] or 0)
                        bucket["sum_confidence"] += float(prediction["confidence"])
                        bucket["calibration"] += abs(prediction["confidence"] / 100.0 -
                                                     float(bool(outcome["direction_correct"])))
                        stats = per_symbol[symbol]
                        stats["evaluated"] += 1
                        stats["correct"] += 1 if outcome["direction_correct"] else 0
                        stats["sum_return"] += float(outcome["outcome_return_pct"] or 0)
                    picks.append(entry)

        horizons = []
        for horizon in sorted(per_horizon):
            bucket = per_horizon[horizon]
            evaluated = bucket["evaluated"]
            horizons.append({
                "horizon_minutes": horizon, "predictions": bucket["predictions"], "evaluated": evaluated,
                "correct": bucket["correct"], "directional_accuracy": (bucket["correct"] / evaluated) if evaluated else None,
                "range_count": bucket["range"],
                "average_return_pct": (bucket["sum_return"] / evaluated) if evaluated else None,
                "average_confidence": (bucket["sum_confidence"] / evaluated) if evaluated else None,
                "calibration_error": (bucket["calibration"] / evaluated) if evaluated else None,
            })
        symbols = []
        for symbol, stats in sorted(per_symbol.items(), key=lambda item: (item[1]["evaluated"], item[0]), reverse=True):
            symbols.append({"symbol": symbol, "evaluated": stats["evaluated"], "correct": stats["correct"],
                            "directional_accuracy": (stats["correct"] / stats["evaluated"]) if stats["evaluated"] else None,
                            "average_return_pct": (stats["sum_return"] / stats["evaluated"]) if stats["evaluated"] else None})
        picks.sort(key=lambda item: item["decision_at"], reverse=True)
        return {"status": "ok", "paper_only": True,
                "lookback_hours": self.lookback_hours, "horizons_minutes": sorted(self.horizons),
                "step_minutes": self.step_minutes, "symbols_scanned": len(loaded),
                "steps": len(steps), "window_start_ms": start_ms, "window_end_ms": end_ms,
                "label_policy_note": "min_move_pct = max(tutarlılık eşiği, tur maliyeti x1.05, ATR x gürültü oranı) — canlı journal ile aynı etiketleme",
                "replay_gaps": ["canlı orderbook/spread/24h ticker geçmişi yok; spread-derinlik bilinmiyor sayılır",
                                 "aday havuzu canlı Top-20 gainer taraması yerine aktif sembol listesinden sınırlıdır"],
                "horizons": horizons, "symbols": symbols[:25], "picks": picks[:120]}
