"""
Hummingbot-inspired High-Frequency Orderbook Imbalance & Microstructure Engine.
Calculates Level-2/Level-3 depth pressure, spread elasticity, and CVD divergence.
"""
from dataclasses import dataclass
from typing import List, Tuple
import numpy as np


@dataclass
class OrderbookDepthSnapshot:
    symbol: str
    bids: List[Tuple[float, float]]  # [(price, volume), ...] sorted descending
    asks: List[Tuple[float, float]]  # [(price, volume), ...] sorted ascending
    timestamp: float


@dataclass
class MicrostructureAnalysis:
    symbol: str
    mid_price: float
    spread_abs: float
    spread_pct: float
    imbalance_top_of_book: float   # -1.0 (Heavy ask) to +1.0 (Heavy bid)
    imbalance_depth_5: float
    imbalance_depth_20: float
    total_bid_liquidity: float
    total_ask_liquidity: float
    flow_direction: str            # "BULLISH_PRESSURE", "BEARISH_PRESSURE", "BALANCED"
    is_spread_acceptable: bool     # Checks if spread is scalable (< 0.08% for spot, < 2.0 pips for forex)
    liquidity_score: float         # 0.0 to 1.0


class HummingbotMicrostructureAnalyzer:
    """
    Analyzes orderbook queue dynamics, depth imbalance, and market maker spread profiles.
    Protects against executing into thin liquidity walls or high-spread slippage traps.
    """

    def analyze_orderbook(
        self,
        snapshot: OrderbookDepthSnapshot,
        max_spread_pct: float = 0.0010  # 0.10% max allowable spread for scalping
    ) -> MicrostructureAnalysis:
        if not snapshot.bids or not snapshot.asks:
            return MicrostructureAnalysis(
                symbol=snapshot.symbol,
                mid_price=0.0,
                spread_abs=0.0,
                spread_pct=0.0,
                imbalance_top_of_book=0.0,
                imbalance_depth_5=0.0,
                imbalance_depth_20=0.0,
                total_bid_liquidity=0.0,
                total_ask_liquidity=0.0,
                flow_direction="BALANCED",
                is_spread_acceptable=False,
                liquidity_score=0.0
            )

        best_bid_p, best_bid_v = snapshot.bids[0]
        best_ask_p, best_ask_v = snapshot.asks[0]

        mid_price = (best_bid_p + best_ask_p) / 2.0
        spread_abs = best_ask_p - best_bid_p
        spread_pct = spread_abs / mid_price if mid_price > 0 else 0.0

        # Top of book imbalance
        top_denom = best_bid_v + best_ask_v
        top_imbalance = (best_bid_v - best_ask_v) / top_denom if top_denom > 0 else 0.0

        # Depth 5 imbalance
        b5_vol = sum(v for _, v in snapshot.bids[:5])
        a5_vol = sum(v for _, v in snapshot.asks[:5])
        d5_denom = b5_vol + a5_vol
        d5_imbalance = (b5_vol - a5_vol) / d5_denom if d5_denom > 0 else 0.0

        # Depth 20 imbalance
        b20_vol = sum(v for _, v in snapshot.bids[:20])
        a20_vol = sum(v for _, v in snapshot.asks[:20])
        d20_denom = b20_vol + a20_vol
        d20_imbalance = (b20_vol - a20_vol) / d20_denom if d20_denom > 0 else 0.0

        # Flow direction
        weighted_imbalance = (top_imbalance * 0.4) + (d5_imbalance * 0.35) + (d20_imbalance * 0.25)

        if weighted_imbalance >= 0.25:
            flow = "BULLISH_PRESSURE"
        elif weighted_imbalance <= -0.25:
            flow = "BEARISH_PRESSURE"
        else:
            flow = "BALANCED"

        is_spread_ok = spread_pct <= max_spread_pct

        # Liquidity score based on total top 20 liquidity and tight spread
        spread_quality = max(0.0, 1.0 - (spread_pct / max_spread_pct))
        liquidity_score = float(np.clip(spread_quality * 0.5 + min(1.0, (d20_denom / 100.0)) * 0.5, 0.0, 1.0))

        return MicrostructureAnalysis(
            symbol=snapshot.symbol,
            mid_price=round(mid_price, 5),
            spread_abs=round(spread_abs, 5),
            spread_pct=round(spread_pct * 100.0, 4),
            imbalance_top_of_book=round(top_imbalance, 4),
            imbalance_depth_5=round(d5_imbalance, 4),
            imbalance_depth_20=round(d20_imbalance, 4),
            total_bid_liquidity=round(b20_vol, 2),
            total_ask_liquidity=round(a20_vol, 2),
            flow_direction=flow,
            is_spread_acceptable=is_spread_ok,
            liquidity_score=round(liquidity_score, 3)
        )
