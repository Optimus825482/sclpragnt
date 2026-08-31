"""Deterministic market-intelligence helpers for Binance TR paper trading.

This adapts the useful parts of the referenced quant/regime skills without
introducing DEX, wallet, futures, or live-execution assumptions.
"""

from __future__ import annotations

from statistics import mean


def trade_economics(entry_price: float, stop_price: float | None = None,
                    take_profit: float | None = None, quantity: float = 0.0,
                    commission_pct: float = 0.0015,
                    spread_pct: float = 0.0,
                    slippage_pct: float = 0.00025,
                    min_net_pnl: float = 0.5) -> dict:
    """Calculate fee-aware LONG paper economics without authorizing a trade."""
    entry = float(entry_price or 0)
    qty = float(quantity or 0)
    notional = entry * qty
    round_trip_cost_pct = max(0.0, float(commission_pct)) * 2 + max(0.0, float(spread_pct)) + max(0.0, float(slippage_pct)) * 2
    round_trip_cost = notional * round_trip_cost_pct
    break_even_price = entry * (1 + round_trip_cost_pct) if entry > 0 else None
    target_move_pct = ((float(take_profit) / entry) - 1) if take_profit and entry > 0 else None
    stop_move_pct = (1 - (float(stop_price) / entry)) if stop_price and entry > 0 else None
    expected_net = (notional * target_move_pct - round_trip_cost) if target_move_pct is not None else None
    edge_cost_ratio = ((notional * target_move_pct) / round_trip_cost) if target_move_pct is not None and round_trip_cost > 0 else None
    return {
        "entry_price": entry, "quantity": qty, "notional": round(notional, 8),
        "round_trip_cost_pct": round(round_trip_cost_pct, 8),
        "round_trip_cost": round(round_trip_cost, 8),
        "break_even_price": round(break_even_price, 8) if break_even_price else None,
        "target_move_pct": round(target_move_pct, 8) if target_move_pct is not None else None,
        "stop_move_pct": round(stop_move_pct, 8) if stop_move_pct is not None else None,
        "expected_net_pnl": round(expected_net, 8) if expected_net is not None else None,
        "edge_cost_ratio": round(edge_cost_ratio, 4) if edge_cost_ratio is not None else None,
        "minimum_net_pnl": float(min_net_pnl),
        "economically_viable": bool(expected_net is not None and expected_net >= float(min_net_pnl)),
        "paper_only": True,
    }


def microstructure_snapshot(snapshot: dict, order_value_try: float = 500.0) -> dict:
    """Normalize realtime liquidity/order-flow fields for an LLM decision."""
    liquidity = snapshot.get("liquidity") or {}
    micro = snapshot.get("microstructure") or {}
    flow = {
        "spread_pct": liquidity.get("spread_pct"),
        "orderbook_depth_try": liquidity.get("orderbook_depth_try"),
        "depth_multiplier": liquidity.get("depth_multiplier"),
        "orderflow_imbalance": liquidity.get("orderflow_imbalance"),
        "depth_imbalance": micro.get("depth_imbalance"),
        "last_trade_side": liquidity.get("last_trade_side"),
        "last_trade_qty": liquidity.get("last_trade_qty"),
        "updated_at": liquidity.get("updated_at"),
        "source": liquidity.get("source"),
    }
    imbalance = flow["orderflow_imbalance"]
    depth = flow["orderbook_depth_try"]
    flags = []
    if imbalance is None: flags.append("order-flow imbalance bilinmiyor")
    if depth in (None, 0): flags.append("order-book derinliği bilinmiyor")
    stale = False
    if flow["updated_at"]:
        import time
        stale = time.time() - float(flow["updated_at"]) > 15
        if stale: flags.append("mikro yapı verisi eski")
    return {"symbol": snapshot.get("symbol"), "order_value_try": float(order_value_try),
            "fields": flow, "flags": flags, "data_ready": not flags,
            "stale": stale, "paper_only": True}


def estimate_local_regime(rows: list[dict]) -> dict:
    """Estimate a degraded, local regime from already-fetched TR snapshots.

    This is deliberately descriptive: it is not a portfolio allocation rule.
    """
    ready = [r for r in rows if r.get("data_ready") and isinstance(r.get("snapshot"), dict)]
    if len(ready) < 3:
        return {"zone": "UNKNOWN", "score": None, "confidence": 0.0,
                "reason": "Yeterli sembol snapshot'ı yok", "data_available": False}
    scores = [float(r.get("score") or 0) for r in ready]
    bullish = [r for r in ready if str(r.get("trend_direction", "")).lower() in {"bullish", "bull", "up"}]
    participation = len(bullish) / len(ready)
    avg_score = mean(scores)
    score = max(0.0, min(100.0, 50 + participation * 35 + max(-15.0, min(15.0, avg_score * 5))))
    if score >= 70:
        zone = "RISK_ON"
        reason = "Sembollerin çoğunda pozitif teknik katılım var"
    elif score <= 35:
        zone = "RISK_OFF"
        reason = "Pozitif teknik katılım zayıf"
    else:
        zone = "NEUTRAL"
        reason = "Sembol bazlı sinyaller karışık"
    return {"zone": zone, "score": round(score, 2),
            "confidence": round(min(0.9, 0.35 + len(ready) / 40), 3),
            "reason": reason, "data_available": True,
            "sample_size": len(ready), "bullish_participation": round(participation, 4),
            "methodology": "local_binance_tr_snapshot_v1"}


def execution_quality(snapshot: dict, order_value_try: float = 500.0) -> dict:
    """Translate execution-model concepts into TR spot paper constraints."""
    liquidity = snapshot.get("liquidity") or {}
    depth = liquidity.get("orderbook_depth_try")
    volume = (snapshot.get("volume") or {}).get("volume_ratio_20")
    reasons = []
    quality = 1.0
    if depth is None or float(depth or 0) <= 0:
        quality -= 0.35; reasons.append("derinlik bilinmiyor")
    elif float(depth) < order_value_try * 5:
        quality -= 0.2; reasons.append("derinlik emir tutarına göre zayıf")
    if volume in (None, 0):
        quality -= 0.2; reasons.append("hacim oranı bilinmiyor")
    elif float(volume) < 1.0:
        quality -= 0.1; reasons.append("hacim ortalamanın altında")
    return {"score": round(max(0.0, quality), 3), "reasons": reasons,
            "order_value_try": order_value_try,
            "data_available": depth is not None and depth > 0}


def symbol_safety(snapshot: dict) -> dict:
    """Centralized-exchange safety gate; no contract/wallet claims are made."""
    liquidity = snapshot.get("liquidity") or {}
    volume = (snapshot.get("volume") or {}).get("volume_ratio_20")
    flags = []
    if not snapshot.get("data_ready"):
        flags.append("snapshot hazır değil")
    if volume in (None, 0):
        flags.append("hacim bilinmiyor")
    return {"status": "PASS" if not flags else "REVIEW", "flags": flags,
            "scope": "Binance TR listeleme/likidite; contract ve deployer analizi yok"}


def cost_aware_trade_metrics(trades: list[dict]) -> dict:
    """Summarize realized trades using net PnL, not win rate alone."""
    pnls = [float(t.get("pnl") or 0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {"trades": len(pnls), "net_pnl": round(sum(pnls), 6),
            "wins": len(wins), "losses": len(losses),
            "win_rate_pct": round(len(wins) / len(pnls) * 100, 2) if pnls else 0.0,
            "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
            "commission": round(sum(float(t.get("commission") or 0) for t in trades), 6),
            "paper_only": True}


def symbol_outcome_profile(trades: list[dict], symbol: str | None = None,
                           strategy: str | None = None, limit: int = 100) -> dict:
    rows = [t for t in (trades or [])
            if (not symbol or str(t.get("symbol", "")).upper() == str(symbol).upper())
            and (not strategy or str(t.get("strategy", "")) == str(strategy))]
    rows = rows[-max(1, min(int(limit), 500)):]
    metrics = cost_aware_trade_metrics(rows)
    pnls = [float(t.get("pnl") or 0) for t in rows]
    positive = [p for p in pnls if p > 0]
    negative = [p for p in pnls if p <= 0]
    expectancy = sum(pnls) / len(pnls) if pnls else None
    peak = 0.0; equity = 0.0; max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl; peak = max(peak, equity); max_drawdown = max(max_drawdown, peak - equity)
    streak = 0; longest = 0
    for pnl in reversed(pnls):
        if pnl <= 0: streak += 1
        else: break
    for pnl in pnls:
        longest = longest + 1 if pnl <= 0 else 0
    return {**metrics, "symbol": symbol, "strategy": strategy,
            "expectancy_net_pnl": round(expectancy, 6) if expectancy is not None else None,
            "average_win": round(sum(positive) / len(positive), 6) if positive else None,
            "average_loss": round(sum(negative) / len(negative), 6) if negative else None,
            "max_drawdown_try": round(max_drawdown, 6),
            "current_loss_streak": streak, "longest_loss_streak": longest,
            "recent_trades": rows[-10:], "sample_sufficient_for_inference": len(rows) >= 30,
            "paper_only": True}


def symbol_behavior_profile(snapshot: dict, history: dict | None = None) -> dict:
    """Sembolün 'kişiliğini' derler: günün hangi saatinde hareketli olduğu ve
    güncel kırılım potansiyeli (hacim/volatilite rejimi).

    ``history`` yalnız zaten yüklenmiş kapanmış mum sözlüğüdür (timeframe →
    {timestamps, closes, highs, lows, volumes}); bu fonksiyon yeni REST çağrısı
    yapmaz ve tahmin/garanti değildir.
    """
    symbol = str(snapshot.get("symbol") or "")
    flow = snapshot.get("liquidity") or {}
    volume = snapshot.get("volume") or {}
    volatility = snapshot.get("volatility") or {}
    flags = []
    hour_profile = None
    if history:
        tf = snapshot.get("timeframe") or "5m"
        kline = history.get(tf) or {}
        timestamps = kline.get("timestamps") or []
        closes = kline.get("closes") or []
        volumes = kline.get("volumes") or []
        if len(timestamps) >= 12:
            buckets: dict[int, dict] = {}
            for ts, close, vol in zip(timestamps, closes, volumes):
                try:
                    hour = int(ts / 3_600_000) % 24
                except (TypeError, ValueError, ZeroDivisionError):
                    continue
                bucket = buckets.setdefault(hour, {"count": 0, "range_sum": 0.0, "vol_sum": 0.0, "last_close": None})
                bucket["count"] += 1
                bucket["vol_sum"] += float(vol or 0)
                bucket["last_close"] = float(close or 0)
            for hour, bucket in buckets.items():
                if bucket["count"] >= 4:
                    bucket["avg_vol"] = bucket["vol_sum"] / bucket["count"]
            if buckets:
                total_vol = sum(b["vol_sum"] for b in buckets.values()) or 1.0
                hour_profile = {
                    "active_hours_tst": sorted(
                        ({"hour": hour, "volume_share": round(b["vol_sum"] / total_vol, 4)}
                         for hour, b in buckets.items() if b["count"] >= 4),
                        key=lambda item: -item["volume_share"],
                    )[:5],
                    "last_hour": sorted(buckets)[-1] % 24,
                }
    volume_ratio = volume.get("volume_ratio_20")
    atr_pct = volatility.get("atr_pct")
    spread = flow.get("spread_pct")
    if volume_ratio is None: flags.append("volume_ratio bilinmiyor")
    if atr_pct is None: flags.append("atr_pct bilinmiyor")
    activity_level = "unknown"
    if volume_ratio is not None:
        activity_level = ("high" if volume_ratio >= 1.5 else
                          "normal" if volume_ratio >= 0.5 else "low")
    volatility_regime = "unknown"
    if atr_pct is not None:
        volatility_regime = ("expanding" if atr_pct >= 0.5 else
                             "normal" if atr_pct >= 0.15 else "contracting")
    return {"symbol": symbol,
            "activity_level": activity_level,
            "volatility_regime": volatility_regime,
            "volume_ratio_20": round(float(volume_ratio), 4) if volume_ratio is not None else None,
            "atr_pct": round(float(atr_pct), 6) if atr_pct is not None else None,
            "spread_pct": round(float(spread), 6) if spread is not None else None,
            "hour_profile": hour_profile,
            "flags": flags,
            "data_available": bool(flow) or bool(volume),
            "methodology": "symbol-behavior-v1",
            "paper_only": True}


def regime_transition_signal(snapshot: dict) -> dict:
    """Range → trend geçişlerini önceden sezdiren türetilmiş sinyaller.

    Bunlar tahmin değildir; yalnız anlık rejim göstergelerinin eşik geçişidir
    ve kanıt olarak snapshot alanlarını kullanır.
    """
    volatility = snapshot.get("volatility") or {}
    volume = snapshot.get("volume") or {}
    indicators = snapshot.get("volatility_indicators") or {}
    volume_ratio = volume.get("volume_ratio_20")
    choppiness = indicators.get("choppiness_14")
    adx = (snapshot.get("trend") or {}).get("adx") or {}
    adx_value = adx.get("adx") if isinstance(adx, dict) else adx
    signals = []
    # Düşük choppiness + hacim sıçraması → range kırılımı adayı
    if choppiness is not None and volume_ratio is not None:
        if choppiness < 45 and volume_ratio >= 1.5:
            signals.append("range_breakout_volume")
    if choppiness is not None and choppiness < 35:
        signals.append("trending_strengthening")
    # ADX düşükken yükselmeye başlaması → yeni trend oluşumu
    if adx_value is not None:
        if adx_value > 25:
            signals.append("trend_confirmed")
        elif adx_value > 20:
            signals.append("trend_forming")
    # ATR rejimi
    atr_pct = volatility.get("atr_pct")
    if atr_pct is not None:
        if atr_pct >= 0.5:
            signals.append("volatility_expanding")
        elif atr_pct < 0.15:
            signals.append("volatility_contracting")
    return {"signals": signals,
            "regime": "range_breakout_candidate" if "range_breakout_volume" in signals else
                     ("trend" if "trend_confirmed" in signals else
                      ("range" if "volatility_contracting" in signals else "mixed")),
            "choppiness_14": round(float(choppiness), 4) if choppiness is not None else None,
            "volume_ratio_20": round(float(volume_ratio), 4) if volume_ratio is not None else None,
            "adx_14": round(float(adx_value), 4) if adx_value is not None else None,
            "atr_pct": round(float(atr_pct), 6) if atr_pct is not None else None,
            "paper_only": True}


# ---------------------------------------------------------------------------
# Whale accumulation / distribution detection.
#
# Binance TR spot exposes no wallet/position data, so "who entered" cannot be
# known directly. What the public aggTrade tape *does* give us is the price
# impact that follows each large fill. A whale buy whose price holds above the
# pre-trade mid is consistent with genuine accumulation (buyer absorbing the
# offer side); a whale buy that immediately gives the move back is consistent
# with distribution into retail bids. Same logic mirrored for whale sells.
# These are directional proxies, not order-book truths.
# ---------------------------------------------------------------------------

# Bir whale işleminden sonra fiyat etkisinin ölçüldüğü saniye penceresi.
WHALE_IMPACT_WINDOW_SEC = 30.0
# Whale işleminin en az ne kadar öncesinden referans fiyatı alınır.
WHALE_REFERENCE_BACK_MS = 5_000


def classify_whale_trade(whale: dict, tape: list[dict]) -> dict:
    """Bir whale işleminin giriş (birikim) mi çıkış (dağıtım) mı olduğunu
    işlem-sonrası fiyat etkisiyle sınıflandırır.

    ``whale``: {"t": ms, "p": fiyat, "q": miktar, "m": bool} (buyer_is_maker).
    ``tape``: aynı şemada, whale işlemini de içeren, artan zaman sıralı işlem
    akışı. Fiyat etkisi, whale işleminden sonraki 15s içindeki işlemlerin
    medyan fiyatı ile whale işleminden 5s önceki referans fiyatı arasındaki
    değişimdir. Etki eşiği ~0.10%'dir; daha küçük hareketler "nötr/absorbed"
    sayılır.
    """
    try:
        whale_ms = int(whale.get("t") or 0)
        whale_price = float(whale.get("p") or 0)
    except (TypeError, ValueError):
        return {"verdict": "unknown", "reason": "geçersiz whale kaydı"}
    if whale_ms <= 0 or whale_price <= 0:
        return {"verdict": "unknown", "reason": "geçersiz whale zaman/fiyat"}
    reference = None
    for trade in (tape or []):
        try:
            if int(trade.get("t") or 0) < whale_ms - WHALE_REFERENCE_BACK_MS:
                reference = float(trade.get("p") or 0)
            else:
                break
        except (TypeError, ValueError):
            continue
    # Tape whale ile başlıyorsa (canlı akışın ilk saniyeleri) hemen önceki
    # trade referans olarak kullanılır; böylece "unknown" yerine en azından
    # mevcut fiyat seviyesine göre sınıflandırma yapılabilir.
    if reference is None:
        for trade in reversed(tape or []):
            try:
                if int(trade.get("t") or 0) < whale_ms:
                    reference = float(trade.get("p") or 0)
                    break
            except (TypeError, ValueError):
                continue
    if reference is None or reference <= 0:
        return {"verdict": "unknown", "reason": "referans fiyat yok"}
    impact_prices = []
    for trade in (tape or []):
        try:
            ts = int(trade.get("t") or 0)
            price = float(trade.get("p") or 0)
        except (TypeError, ValueError):
            continue
        if whale_ms < ts <= whale_ms + int(WHALE_IMPACT_WINDOW_SEC * 1000) and price > 0:
            impact_prices.append(price)
    # Pencerede işlem yoksa (büyük işlem sonrası sessizlik) tape'te whale'den
    # sonraki ilk işlem referans alınır; yine yoksa gerçekten bilgi yoktur.
    if not impact_prices:
        for trade in (tape or []):
            try:
                ts = int(trade.get("t") or 0)
                price = float(trade.get("p") or 0)
            except (TypeError, ValueError):
                continue
            if ts > whale_ms and price > 0:
                impact_prices.append(price)
                break
    if not impact_prices:
        return {"verdict": "unknown", "reason": "etki penceresinde işlem yok"}
    impact_prices.sort()
    n = len(impact_prices)
    post_median = float(impact_prices[n // 2])
    change_pct = (post_median / reference - 1) * 100 if reference > 0 else 0.0
    threshold = 0.10  # %0.10
    is_buy = not bool(whale.get("m", False))
    if is_buy:
        if change_pct >= threshold:
            verdict = "accumulation"
            reason = f"whale buy sonrası fiyat +{change_pct:.3f}% korundu (referans {reference}, medyan {post_median})"
        elif change_pct <= -threshold:
            verdict = "distribution"
            reason = f"whale buy sonrası fiyat {change_pct:.3f}% geri verildi — satıcı absorb ediyor"
        else:
            verdict = "neutral"
            reason = f"whale buy fiyatı {change_pct:+.3f}% — nötr/absorbed"
    else:
        if change_pct <= -threshold:
            verdict = "distribution"
            reason = f"whale sell sonrası fiyat {change_pct:.3f}% düştü — çıkış baskısı gerçek"
        elif change_pct >= threshold:
            verdict = "accumulation"
            reason = f"whale sell fiyatı +{change_pct:.3f}% toparladı — alıcı emiyor (birikim lehine)"
        else:
            verdict = "neutral"
            reason = f"whale sell fiyatı {change_pct:+.3f}% — nötr/absorbed"
    return {"verdict": verdict, "side": "buy" if is_buy else "sell",
            "notional_try": round(whale_price * float(whale.get("q") or 0), 2),
            "reference_price": round(reference, 8),
            "post_median_price": round(post_median, 8),
            "impact_pct": round(change_pct, 4),
            "impact_window_sec": WHALE_IMPACT_WINDOW_SEC,
            "impact_trades": n,
            "reason": reason}


def whale_activity_from_tape(tape: list[dict], whale_threshold_try: float = 25_000.0,
                             limit: int = 8) -> dict:
    """Tapedeki tüm whale işlemlerini sınıflandırıp birikim/dağıtım özeti üretir.

    ``tape`` artan zaman sıralı olmalıdır. Son ``limit`` whale işlemi
    sınıflandırılır; özet hem toplam notional ağırlığını hem de son whale'in
    yönünü verir. Tahmin/garanti değildir, paper-only'dir.
    """
    whales = []
    for trade in (tape or []):
        try:
            ts = int(trade.get("t") or 0)
            price = float(trade.get("p") or 0)
            qty = float(trade.get("q") or 0)
        except (TypeError, ValueError):
            continue
        if ts > 0 and price > 0 and qty > 0 and price * qty >= whale_threshold_try:
            whales.append({"t": ts, "p": price, "q": qty, "m": bool(trade.get("m", False))})
    if not whales:
        return {"whale_count": 0, "accumulation": 0, "distribution": 0, "neutral": 0,
                "net_direction": "none", "verdict": "no_whale", "classified": [], "data_ready": True}
    classified = []
    for whale in whales[-limit:]:
        result = classify_whale_trade(whale, tape)
        result["t"] = whale["t"]
        classified.append(result)
    acc = sum(1 for item in classified if item.get("verdict") == "accumulation")
    dist = sum(1 for item in classified if item.get("verdict") == "distribution")
    neu = sum(1 for item in classified if item.get("verdict") == "neutral")
    if acc > dist and acc > 0:
        verdict = "accumulation"
    elif dist > acc and dist > 0:
        verdict = "distribution"
    elif acc == dist and acc > 0:
        verdict = "mixed"
    else:
        verdict = "neutral"
    return {"whale_count": len(whales), "classified_count": len(classified),
            "accumulation": acc, "distribution": dist, "neutral": neu,
            "net_direction": "buy" if acc > dist else "sell" if dist > acc else "neutral",
            "verdict": verdict,
            "accumulation_notional_try": round(sum(item.get("notional_try") or 0 for item in classified if item.get("verdict") == "accumulation"), 2),
            "distribution_notional_try": round(sum(item.get("notional_try") or 0 for item in classified if item.get("verdict") == "distribution"), 2),
            "last_whale": classified[-1] if classified else None,
            "classified": classified,
            "threshold_try": whale_threshold_try,
            "data_ready": True}


def walk_forward_assessment(windows: list[dict]) -> dict:
    """Flag degradation across ordered historical windows without overclaiming."""
    if len(windows) < 2:
        return {"status": "INSUFFICIENT_WINDOWS", "degradation_ratio": None}
    first = float(windows[0].get("net_pnl") or 0)
    last = float(windows[-1].get("net_pnl") or 0)
    ratio = round(last / first, 4) if first > 0 else None
    status = "STABLE" if ratio is not None and ratio >= 0.5 else "DEGRADED"
    return {"status": status, "degradation_ratio": ratio,
            "note": "Pencereler farklı tarih aralıklarıdır; gerçek IS/OOS ayrımı değildir."}
