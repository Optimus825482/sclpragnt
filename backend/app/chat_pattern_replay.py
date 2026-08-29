"""Two-phase pattern replay for Chat M5/M15 upside predictions.

Phase A (train, first N hours): at each step, detect the risers (symbols that
actually rose during the phase), build rich causal snapshots right before
their rise window, and mine the common feature patterns shared by winners.

Phase B (test, next N hours): apply the mined pattern rules as candidate
filters; every pick is journaled and measured from closed M1 candles exactly
like the live journal, so train vs test accuracy is directly comparable.

Snapshot quality upgrades vs the first replay:
- estimated 24h quote volume from the loaded 1m series (was 0),
- realistic order value for ATR/depth fields (was 0),
- explicit feature vector (returns, EMAs, ADX/DI, RSI, MFI, volume ratio,
  ATR%, choppiness, regime) suitable for pattern mining.

Read-only research; never touches the prediction journal.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter, defaultdict

from app.forecast_learning import evaluate_forecast
from app.technical_analysis import calculate_snapshot


DEFAULT_STEP_MINUTES = 15
MIN_SYMBOL_CANDLES = 60
HORIZON_RISER_MIN_PCT = 0.10  # a symbol "rose" in a window if return >= +0.10%
# Journal verisi henüz desen madenciliğini beslemeden önce kullanılacak
# başlangıç etiketleri (replay 2026-08-29 train penceresinden).
DEFAULT_TRAIN_TAGS = ("atr_yuksek", "vol_spike", "vol_spike_strong")


def _close_time(row) -> int:
    return int(row[0]) + 59_999


def _resample(rows: list, factor: int) -> dict:
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
                result["timestamps"].append(bucket[0][0]); result["opens"].append(bucket[0][1])
                result["highs"].append(max(i[2] for i in bucket)); result["lows"].append(min(i[3] for i in bucket))
                result["closes"].append(bucket[-1][4]); result["volumes"].append(sum(i[5] for i in bucket))
                bucket = []
    if result["timestamps"]:
        result["last_closed_at_ms"] = result["timestamps"][-1]
    return result


def _atr_pct(closes, highs, lows) -> float:
    if len(closes) < 15:
        return 0.0
    trs = []
    for i in range(len(closes) - 14, len(closes)):
        prev = closes[i - 1]
        trs.append(max(highs[i] - lows[i], abs(highs[i] - prev), abs(lows[i] - prev)))
    atr = sum(trs) / len(trs) if trs else 0.0
    return atr / closes[-1] if closes[-1] else 0.0


def rich_features(symbol: str, rows: list, horizon_minutes: int) -> dict | None:
    """Causal, numeric feature vector from closed 1m bars only."""
    klines_by_tf = {"1m": _resample(rows, 1), "3m": _resample(rows, 3),
                    "5m": _resample(rows, 5), "15m": _resample(rows, 15)}
    primary = "5m" if horizon_minutes <= 5 else "15m"
    snapshot = calculate_snapshot(symbol, float(rows[-1][4]), klines_by_tf, {}, 0, 1000, primary)
    if not snapshot.get("data_ready"):
        return None
    closes_1m = [float(r[4]) for r in rows]
    highs_1m = [float(r[2]) for r in rows]
    lows_1m = [float(r[3]) for r in rows]
    vols_1m = [float(r[5]) for r in rows]
    trend = snapshot.get("trend") or {}
    momentum = snapshot.get("momentum") or {}
    volume = snapshot.get("volume") or {}
    vol_ind = snapshot.get("volatility_indicators") or {}
    flow = snapshot.get("flow_indicators") or {}
    osc = (snapshot.get("oscillators") or {}).get("values") or {}
    regime = (((snapshot.get("methodologies") or {}).get(primary) or {}).get("regime") or {}).get("name")
    adx = trend.get("adx")
    if isinstance(adx, dict):
        adx = adx.get("adx")
    features = {
        "symbol": symbol,
        "atr_pct": round(_atr_pct(closes_1m, highs_1m, lows_1m) * 100, 4),
        "vol_ratio_1m20": round(vols_1m[-1] / (sum(vols_1m[-20:-1]) / 19), 3) if sum(vols_1m[-20:-1]) else None,
        "quote_volume_24h_est": round(sum(vols_1m[-min(1440, len(vols_1m)):]) * closes_1m[-1] / 1000, 1),  # bin TRY
        "ret_5m": momentum.get("return_5m"), "ret_15m": momentum.get("return_15m"),
        "ret_1h": momentum.get("return_1h"),
        "rsi_14": momentum.get("rsi_14"), "mfi_14": momentum.get("mfi_14"),
        "adx": adx, "chop_14": vol_ind.get("choppiness_14") if isinstance(vol_ind.get("choppiness_14"), (int, float)) else None,
        "cmf_20": flow.get("cmf_20"),
        "alignment": trend.get("alignment"), "regime": regime,
        "range_pos": None,
    }
    # range_pos: 20-bar high-low band içindeki konum (0=taban, 1=tavan)
    window = closes_1m[-20:]
    if window:
        hi, lo = max(window), min(window)
        features["range_pos"] = round((closes_1m[-1] - lo) / (hi - lo), 3) if hi > lo else None
    features["price"] = closes_1m[-1]
    return features


def mine_patterns(train_rows: list[dict], *, min_support: int = 4,
                  lift_floor: float = 1.3) -> list[dict]:
    """Frequency + lift mining over binarized feature tags of winners vs all.

    train_rows: dicts with 'features' (rich_features output) and 'win' (bool).
    A pattern is a single tag; lift = P(tag|win)/P(tag|all). Only tags with
    support >= min_support in winners and lift >= lift_floor are returned.
    """
    def tags_of(feat: dict) -> set:
        tags = set()
        if feat.get("alignment") == "bullish": tags.add("ema_bullish")
        if feat.get("regime") and str(feat.get("regime")).startswith("bull"): tags.add("regime_bull")
        if (feat.get("adx") or 0) >= 20: tags.add("adx20")
        if (feat.get("adx") or 0) >= 28: tags.add("adx28")
        if (feat.get("ret_15m") or 0) > 0: tags.add("ret15_pos")
        if (feat.get("ret_1h") or 0) > 0: tags.add("ret1h_pos")
        if (feat.get("ret_5m") or 0) > 0: tags.add("ret5_pos")
        if (feat.get("rsi_14") or 50) >= 55: tags.add("rsi_ge55")
        if (feat.get("rsi_14") or 50) <= 45: tags.add("rsi_le45")
        if (feat.get("mfi_14") or 50) >= 55: tags.add("mfi_ge55")
        if (feat.get("vol_ratio_1m20") or 0) >= 1.5: tags.add("vol_spike")
        if (feat.get("vol_ratio_1m20") or 0) >= 2.5: tags.add("vol_spike_strong")
        if (feat.get("chop_14") or 100) < 61.8: tags.add("chop_trending")
        if (feat.get("range_pos") or 0) >= 0.8: tags.add("band_tepe")
        if (feat.get("range_pos") or 1) <= 0.3: tags.add("band_taban")
        if (feat.get("atr_pct") or 0) >= 0.15: tags.add("atr_yuksek")
        if (feat.get("atr_pct") or 1) < 0.05: tags.add("atr_dusuk")
        if (feat.get("cmf_20") or 0) > 0: tags.add("cmf_pos")
        if (feat.get("quote_volume_24h_est") or 0) >= 50_000: tags.add("hacim_50k_trx")
        return tags
    winners, everyone = [], []
    tag_win, tag_all = Counter(), Counter()
    for row in train_rows:
        feat = row.get("features") or {}
        tags = tags_of(feat)
        everyone.append(tags)
        if row.get("win"):
            winners.append(tags)
        for t in tags:
            tag_all[t] += 1
            if row.get("win"):
                tag_win[t] += 1
    n_all, n_win = len(everyone), len(winners)
    if not n_all or not n_win:
        return []
    patterns = []
    for tag, win_count in tag_win.items():
        support_all = tag_all[tag]
        if win_count < min_support or support_all < min_support:
            continue
        lift = (win_count / n_win) / (support_all / n_all)
        if lift < lift_floor:
            continue
        patterns.append({"tag": tag, "win_support": win_count, "all_support": support_all,
                         "lift": round(lift, 2),
                         "precision": round(win_count / support_all, 3)})
    patterns.sort(key=lambda item: (-item["lift"], -item["win_support"]))
    return patterns


def tags_of_features(feat: dict) -> set:
    """Public re-export of the same tag rule used by mining (for test phase)."""
    # duplicated intentionally via mine_patterns internal closure to keep one
    # source of truth; simplest: call mine with a single row and read nothing.
    # Instead, reimplement minimal:
    tags = set()
    if feat.get("alignment") == "bullish": tags.add("ema_bullish")
    if feat.get("regime") and str(feat.get("regime")).startswith("bull"): tags.add("regime_bull")
    if (feat.get("adx") or 0) >= 20: tags.add("adx20")
    if (feat.get("adx") or 0) >= 28: tags.add("adx28")
    if (feat.get("ret_15m") or 0) > 0: tags.add("ret15_pos")
    if (feat.get("ret_1h") or 0) > 0: tags.add("ret1h_pos")
    if (feat.get("ret_5m") or 0) > 0: tags.add("ret5_pos")
    if (feat.get("rsi_14") or 50) >= 55: tags.add("rsi_ge55")
    if (feat.get("rsi_14") or 50) <= 45: tags.add("rsi_le45")
    if (feat.get("mfi_14") or 50) >= 55: tags.add("mfi_ge55")
    if (feat.get("vol_ratio_1m20") or 0) >= 1.5: tags.add("vol_spike")
    if (feat.get("vol_ratio_1m20") or 0) >= 2.5: tags.add("vol_spike_strong")
    if (feat.get("chop_14") or 100) < 61.8: tags.add("chop_trending")
    if (feat.get("range_pos") or 0) >= 0.8: tags.add("band_tepe")
    if (feat.get("range_pos") or 1) <= 0.3: tags.add("band_taban")
    if (feat.get("atr_pct") or 0) >= 0.15: tags.add("atr_yuksek")
    if (feat.get("atr_pct") or 1) < 0.05: tags.add("atr_dusuk")
    if (feat.get("cmf_20") or 0) > 0: tags.add("cmf_pos")
    if (feat.get("quote_volume_24h_est") or 0) >= 50_000: tags.add("hacim_50k_trx")
    return tags


class PatternReplayRunner:
    """Train on first `train_hours`, apply patterns on the following test window."""

    def __init__(self, symbols: list[str], *, train_hours: int = 6, test_hours: int = 6,
                 horizons: list[int] | None = None, step_minutes: int = DEFAULT_STEP_MINUTES,
                 fetch_klines, log=None, use_top_gainers: bool = True,
                 min_pattern_matches: int = 2, score_threshold: float = 1.0):
        self.symbols = symbols
        self.train_hours, self.test_hours = train_hours, test_hours
        self.horizons = horizons or [5, 15]
        self.step_minutes = max(step_minutes, max(self.horizons))
        self.fetch_klines = fetch_klines
        self.log = log or (lambda m: None)
        self.use_top_gainers = use_top_gainers
        self.min_pattern_matches = min_pattern_matches
        self.score_threshold = score_threshold

    async def _load(self, symbol: str) -> dict | None:
        span = int((self.train_hours + self.test_hours) * 60 + max(self.horizons) + self.step_minutes + 30)
        try:
            rows = await self.fetch_klines(symbol, "1m", min(1000, max(600, span)))
        except Exception as exc:
            self.log(f"{symbol} veri hatası: {exc}")
            return None
        rows = [r for r in rows if _close_time(r) <= int(r[0]) + 59_999]
        if len(rows) < MIN_SYMBOL_CANDLES:
            self.log(f"{symbol}: yetersiz kapalı mum ({len(rows)})")
            return None
        return {"rows": rows}

    def _features_at(self, data: dict, decision_ms: int, horizon: int) -> dict | None:
        rows = [r for r in data["rows"] if _close_time(r) <= decision_ms]
        if len(rows) < MIN_SYMBOL_CANDLES:
            return None
        return rich_features("SYM", rows, horizon)

    def _measure(self, prediction: dict, data: dict, decision_ms: int) -> dict | None:
        rows = [r for r in data["rows"] if _close_time(r) > decision_ms]
        due = decision_ms + prediction["horizon_minutes"] * 60_000
        window = [r for r in rows if _close_time(r) <= due]
        if len(window) < prediction["horizon_minutes"]:
            return None
        return evaluate_forecast(prediction, evaluated_at=due / 1000,
                                 outcome_price=float(window[-1][4]),
                                 max_high=max(float(r[2]) for r in window),
                                 min_low=min(float(r[3]) for r in window))

    async def run(self) -> dict:
        from app.config import config
        from app.chat_prediction_replay import _label_policy, _candidate_score
        universe = list(self.symbols)
        if self.use_top_gainers:
            from app.binance_tr_public import top_gainers as fetch_top
            try:
                live = await fetch_top(20)
                self.log(f"Canlı Top-Gaining evreni: {', '.join(i['symbol'] for i in live[:10])}…")
            except Exception as exc:
                self.log(f"Top-Gaining alınamadı ({exc}); config sembolleri")
                live = []
            for item in live:
                if item["symbol"] not in universe:
                    universe.append(item["symbol"])
        universe = universe[:40]
        loaded = {}
        for symbol in universe:
            data = await self._load(symbol)
            if data:
                loaded[symbol] = data
        if not loaded:
            return {"status": "no_data", "message": "Veri yok", "paper_only": True}
        self.log(f"{len(loaded)} sembol yüklendi")

        end_ms = max(max(_close_time(r) for r in d["rows"]) for d in loaded.values())
        step_ms = self.step_minutes * 60_000
        split_ms = end_ms - self.test_hours * 3_600_000
        train_start_ms = end_ms - (self.train_hours + self.test_hours) * 3_600_000

        def steps_between(start_ms, end):
            out, cur = [], ((start_ms // step_ms) + 1) * step_ms
            while cur + max(self.horizons) * 60_000 <= end:
                out.append(cur); cur += step_ms
            return out

        train_steps = steps_between(train_start_ms, split_ms)
        test_steps = steps_between(split_ms, end_ms)

        # ---------- FAZ A: TRAIN — artanları tespit + özellik madenciliği ----------
        train_rows = []
        risers_found = 0
        for decision_ms in train_steps:
            for symbol, data in loaded.items():
                for horizon in self.horizons:
                    feat = self._features_at(data, decision_ms, horizon)
                    if not feat:
                        continue
                    rows = [r for r in data["rows"] if decision_ms < _close_time(r) <= decision_ms + horizon * 60_000]
                    if len(rows) < horizon:
                        continue
                    ret = float(rows[-1][4]) / float(rows[0][1]) - 1
                    win = ret * 100 >= HORIZON_RISER_MIN_PCT
                    risers_found += 1 if win else 0
                    train_rows.append({"decision_ms": decision_ms, "symbol": symbol,
                                       "horizon_minutes": horizon, "features": dict(feat, symbol=symbol),
                                       "win": win, "return_pct": ret * 100})
        patterns = mine_patterns(train_rows, min_support=max(3, len(train_rows) // 150), lift_floor=1.25)
        pattern_tags = {item["tag"] for item in patterns[:8]}
        self.log(f"Faz A: {len(train_steps)} adım, {len(train_rows)} gözlem, {risers_found} artış; "
                 f"{len(patterns)} desen → filtre: {', '.join(sorted(pattern_tags)) or 'yok'}")

        # ---------- FAZ B: TEST — desen filtreli tahminler ----------
        per_horizon = {h: {"picked": 0, "evaluated": 0, "correct": 0, "range": 0,
                            "sum_ret": 0.0, "calib": 0.0} for h in self.horizons}
        baseline = {h: {"picked": 0, "evaluated": 0, "correct": 0, "sum_ret": 0.0} for h in self.horizons}
        picks, skipped_by_pattern = [], Counter()
        for decision_ms in test_steps:
            for symbol, data in loaded.items():
                score, evidence, risks = 0.0, [], []
                snap = None
                for horizon in self.horizons:
                    feat = self._features_at(data, decision_ms, horizon)
                    if not feat:
                        continue
                    tags = tags_of_features(feat)
                    matches = tags & pattern_tags
                    if self.score_threshold > 0 and not snap:
                        snap_rows = [r for r in data["rows"] if _close_time(r) <= decision_ms]
                        klines_by_tf = {"1m": _resample(snap_rows, 1), "5m": _resample(snap_rows, 5), "15m": _resample(snap_rows, 15)}
                        primary = "5m" if 5 in self.horizons else "15m"
                        snap = calculate_snapshot(symbol, float(snap_rows[-1][4]), klines_by_tf, {}, 0, 1000, primary)
                        if snap.get("data_ready"):
                            score, evidence, risks = _candidate_score(snap)
                        else:
                            snap = None
                    # baseline: her data-ready sembol için skor eşiğiyle (eski davranış)
                    if score >= self.score_threshold and str((snap or {}).get("summary") or "").lower() != "bearish":
                        baseline[horizon]["picked"] += 1
                    # pattern-filtered pick
                    if len(matches) < self.min_pattern_matches:
                        skipped_by_pattern[f"eksik_desen({len(matches)} eşleşme)"] += 1
                        continue
                    if str((snap or {}).get("summary") or "").lower() == "bearish":
                        skipped_by_pattern["bearish"] += 1
                        continue
                    from app.chat_prediction_replay import _label_policy as _lp
                    policy = _lp(horizon, (feat.get("atr_pct") or 0) / 100)
                    prediction = {"entry_price": feat["price"], "direction": "up",
                                  "confidence": max(35.0, min(85.0, 50.0 + score * 8.0)),
                                  "min_move_pct": policy["min_move_pct"], "horizon_minutes": horizon}
                    outcome = self._measure(prediction, data, decision_ms)
                    per_horizon[horizon]["picked"] += 1
                    entry = {"decision_at": decision_ms / 1000, "symbol": symbol,
                             "horizon_minutes": horizon, "score": score,
                             "pattern_matches": sorted(matches), "features": feat,
                             "status": "unmeasured"}
                    if outcome:
                        per_horizon[horizon]["evaluated"] += 1
                        entry.update({"status": "evaluated",
                                      "direction_correct": bool(outcome["direction_correct"]),
                                      "outcome_return_pct": outcome["outcome_return_pct"],
                                      "outcome_direction": outcome["outcome_direction"],
                                      "max_favorable_pct": outcome["max_favorable_pct"],
                                      "max_adverse_pct": outcome["max_adverse_pct"]})
                        if outcome["direction_correct"]:
                            per_horizon[horizon]["correct"] += 1
                        if outcome["outcome_direction"] == "range":
                            per_horizon[horizon]["range"] += 1
                        per_horizon[horizon]["sum_ret"] += float(outcome["outcome_return_pct"] or 0)
                        per_horizon[horizon]["calib"] += abs(prediction["confidence"] / 100 - float(bool(outcome["direction_correct"])))
                    picks.append(entry)

        def summarize(bucket, key_ret="sum_ret"):
            ev = bucket["evaluated"]
            return {"picked": bucket["picked"], "evaluated": ev, "correct": bucket.get("correct", 0),
                    "directional_accuracy": (bucket.get("correct", 0) / ev) if ev else None,
                    "range_count": bucket.get("range", 0),
                    "average_return_pct": (bucket[key_ret] / ev) if ev else None}
        test_results = {h: summarize(per_horizon[h]) for h in sorted(per_horizon)}
        baseline_results = {h: summarize(baseline[h]) for h in sorted(baseline)}
        # baseline'ın da sonuçlarını ölç (adalet için)
        picks.sort(key=lambda p: p["decision_at"], reverse=True)
        return {"status": "ok", "paper_only": True,
                "train_hours": self.train_hours, "test_hours": self.test_hours,
                "step_minutes": self.step_minutes, "symbols_loaded": len(loaded),
                "train_observations": len(train_rows), "train_risers": risers_found,
                "patterns": patterns[:12], "pattern_tags_used": sorted(pattern_tags),
                "min_pattern_matches": self.min_pattern_matches,
                "test": test_results, "baseline": baseline_results,
                "skipped_by_pattern": dict(skipped_by_pattern),
                "picks": picks[:100]}

# Şema: pattern_tags_used hem train desenlerini hem test filtresini temsil eder.


def live_pattern_tags(kline_rows: list, horizon_minutes: int) -> dict | None:
    """Canlı aday için zengin özellik + etiket üretimi (snapshot'tan).

    kline_rows: kapanmış 1m kline satırları (Binance public klines çıktısı).
    Dönen sözlük features/tags içerir; hiçbir alan geleceğe bakmaz.
    """
    try:
        closed = [r for r in kline_rows if _close_time(r) <= int(r[0]) + 59_999]
        if len(closed) < MIN_SYMBOL_CANDLES:
            return None
        feat = rich_features("LIVE", closed, horizon_minutes)
        if not feat:
            return None
        return {"features": feat, "tags": tags_of_features(feat)}
    except Exception:
        return None


def evaluate_live_candidate(kline_rows: list, horizon_minutes: int, *,
                            pattern_tags, min_matches: int, high_confidence_matches: int) -> dict | None:
    """Canlı adayı desen kapısından geçirir.

    Dönen: {'confidence_tier': 'high'|'watch'|'rejected', 'matches': [...],
            'features': {...}} — journal ve auto-trade bu kararı kullanır.
    pattern_tags boşsa (henüz train yok) aday 'watch' olarak geçer.
    """
    try:
        evaluated = live_pattern_tags(kline_rows, horizon_minutes)
    except Exception:
        return None
    if not evaluated:
        return None
    tags = evaluated["tags"]
    if not pattern_tags:
        return {"confidence_tier": "watch", "matches": [], "features": evaluated["features"]}
    matches = sorted(set(pattern_tags) & tags)
    if len(matches) >= max(1, high_confidence_matches):
        tier = "high"
    elif len(matches) >= max(1, min_matches):
        tier = "watch"
    else:
        tier = "rejected"
    return {"confidence_tier": tier, "matches": matches, "features": evaluated["features"]}


def live_trade_plan(horizon_minutes: int, atr_pct: float) -> dict:
    """Replay simülasyonundan gelen asimetrik çıkış planı (paper-only)."""
    from app.config import config
    return {"take_profit_pct": config.CHAT_PREDICTION_TP_PCT / 100.0,
            "stop_loss_pct": config.CHAT_PREDICTION_SL_PCT / 100.0,
            "max_hold_seconds": config.CHAT_PREDICTION_MAX_HOLD_SEC,
            "tp_pct_display": config.CHAT_PREDICTION_TP_PCT,
            "sl_pct_display": config.CHAT_PREDICTION_SL_PCT,
            "basis": "replay_2026-08-29 TP0.8/SL0.5 worst-case pozitif"}
