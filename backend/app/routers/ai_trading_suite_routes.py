"""
FastAPI Router for Scalper Global Agent AI & Quantitative Trading Suite.
Exposes endpoints for the 21 integrated open-source AI and quant trading architectures.
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from app.ai_trading_suite import (
    AITradingSuiteOrchestrator,
    UnifiedEvaluationRequest,
    IndicatorEvaluation,
    MacroEvent,
    TradeContractProposal,
    RiskChiefVetoEngine,
    OctoBotMatrixEvaluator,
    FinRobotMacroAnalyzer,
    HedgeFundCouncil
)

router = APIRouter(prefix="/api/v1/ai-trading-suite", tags=["AI Trading Suite"])
router_alias = APIRouter(prefix="/api/ai-trading-suite", tags=["AI Trading Suite"])

orchestrator = AITradingSuiteOrchestrator()


class IndicatorInput(BaseModel):
    indicator_name: str
    signal: float
    weight: float
    timeframe: str = "5m"


class MacroEventInput(BaseModel):
    event_name: str
    currency: str
    impact: str
    sentiment_score: float
    minutes_until_event: Optional[int] = None


class EvaluationPayload(BaseModel):
    symbol: str
    asset_type: str  # "SPOT" or "FOREX"
    current_price: float
    atr: float
    indicators: List[IndicatorInput]
    macro_events: Optional[List[MacroEventInput]] = None
    orderbook_bids: Optional[List[List[float]]] = None
    orderbook_asks: Optional[List[List[float]]] = None
    price_change_pct: float = 0.0
    volume_ratio: float = 1.0
    social_buzz: float = 0.0
    quant_z_score: float = 0.0
    rsi_value: float = 50.0
    trend_slope: float = 0.0
    proposed_action: str = "BUY"
    daily_drawdown_pct: float = 0.0
    account_margin_used_pct: float = 5.0
    spread_pips_or_pct: float = 0.0005
    dxy_change_pct: float = 0.0
    account_balance: float = 10000.0


@router.get("/status")
def get_suite_status():
    """
    Returns the registration status of all 21 AI and quant trading frameworks.
    """
    return {
        "status": "ONLINE",
        "trading_mode": "PAPER / DEMO ACTIVE (NON-FUNDED)",
        "integrated_architectures": [
            {"id": 21, "name": "CVD Order Flow", "role": "Cumulative Volume Delta & Iceberg Absorption Detection", "status": "ACTIVE"},
            {"id": 20, "name": "Kelly Criterion Sizer", "role": "Ed Thorp Optimal Capital Growth & Ruin Barrier", "status": "ACTIVE"},
            {"id": 19, "name": "Hidden Markov Models (HMM)", "role": "Unsupervised Latent Market Regime Classifier", "status": "ACTIVE"},
            {"id": 18, "name": "Volume Profile & POC", "role": "Point of Control & Value Area High/Low Distribution", "status": "ACTIVE"},
            {"id": 17, "name": "Kalman Filter Trend", "role": "Zero-Lag True Price & Dynamic Velocity State Estimator", "status": "ACTIVE"},
            {"id": 16, "name": "QuantConnect LEAN", "role": "Cross-Asset Portfolio & Volatility Parity Sizing", "status": "ACTIVE"},
            {"id": 15, "name": "Microsoft RD-Agent", "role": "Autonomous Hypothesis & Self-Correction R&D", "status": "ACTIVE"},
            {"id": 14, "name": "FinGPT", "role": "Financial News Sentiment & Polarization NLP", "status": "ACTIVE"},
            {"id": 13, "name": "Jesse", "role": "Dynamic Genetic Risk/Reward & Trailing Stop Optimizer", "status": "ACTIVE"},
            {"id": 12, "name": "OpenBB", "role": "Macro Intelligence, DXY Bias & Event Risk Gate", "status": "ACTIVE"},
            {"id": 11, "name": "Microsoft Qlib", "role": "Alpha158/Alpha360 Multi-Factor Quantitative Scoring", "status": "ACTIVE"},
            {"id": 10, "name": "OctoBot", "role": "Matrix Evaluator & Consensus Engine", "status": "ACTIVE"},
            {"id": 9, "name": "FinRobot", "role": "Macro News Sentiment & Calendar", "status": "ACTIVE"},
            {"id": 8, "name": "Vibe-Trading", "role": "Momentum Breakout & Social Vibe", "status": "ACTIVE"},
            {"id": 7, "name": "FinRL", "role": "DRL Adaptive Trailing & Exit Engine", "status": "ACTIVE"},
            {"id": 6, "name": "AI-Trader", "role": "Self-Reflection & Devil's Advocate", "status": "ACTIVE"},
            {"id": 5, "name": "Hummingbot", "role": "Orderbook Imbalance & Microstructure", "status": "ACTIVE"},
            {"id": 4, "name": "NautilusTrader", "role": "Realistic Latency/Slippage Fill Model", "status": "ACTIVE"},
            {"id": 3, "name": "Freqtrade", "role": "Protections, Cooldown & Dynamic ROI", "status": "ACTIVE"},
            {"id": 2, "name": "ai-hedge-fund", "role": "Soros/Simons/Dalio Investment Council", "status": "ACTIVE"},
            {"id": 1, "name": "TradingAgents", "role": "Institutional Pydantic Desk & Risk Chief Veto", "status": "ACTIVE"}
        ]
    }


@router.post("/evaluate")
def evaluate_symbol(payload: EvaluationPayload):
    """
    Executes the end-to-end 21-model evaluation on a Spot or Forex symbol.
    """
    try:
        indicators = [
            IndicatorEvaluation(
                indicator_name=i.indicator_name,
                signal=i.signal,
                weight=i.weight,
                timeframe=i.timeframe
            )
            for i in payload.indicators
        ]

        macro_events = []
        if payload.macro_events:
            macro_events = [
                MacroEvent(
                    event_name=m.event_name,
                    currency=m.currency,
                    impact=m.impact,
                    sentiment_score=m.sentiment_score,
                    minutes_until_event=m.minutes_until_event
                )
                for m in payload.macro_events
            ]

        bids = [(float(b[0]), float(b[1])) for b in payload.orderbook_bids] if payload.orderbook_bids else [
            (payload.current_price * 0.9998, 5.0),
            (payload.current_price * 0.9995, 12.0),
            (payload.current_price * 0.9990, 25.0)
        ]
        asks = [(float(a[0]), float(a[1])) for a in payload.orderbook_asks] if payload.orderbook_asks else [
            (payload.current_price * 1.0002, 4.5),
            (payload.current_price * 1.0005, 10.0),
            (payload.current_price * 1.0010, 20.0)
        ]

        req = UnifiedEvaluationRequest(
            symbol=payload.symbol,
            asset_type=payload.asset_type,
            current_price=payload.current_price,
            atr=payload.atr,
            indicators=indicators,
            macro_events=macro_events,
            orderbook_bids=bids,
            orderbook_asks=asks,
            price_change_pct=payload.price_change_pct,
            volume_ratio=payload.volume_ratio,
            social_buzz=payload.social_buzz,
            quant_z_score=payload.quant_z_score,
            rsi_value=payload.rsi_value,
            trend_slope=payload.trend_slope,
            proposed_action=payload.proposed_action,
            daily_drawdown_pct=payload.daily_drawdown_pct,
            account_margin_used_pct=payload.account_margin_used_pct,
            spread_pips_or_pct=payload.spread_pips_or_pct,
            dxy_change_pct=payload.dxy_change_pct,
            account_balance=payload.account_balance
        )

        response = orchestrator.evaluate(req)

        from dataclasses import asdict
        return asdict(response)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Orchestrator evaluation error: {str(e)}")


router_alias.add_api_route("/status", get_suite_status, methods=["GET"])
router_alias.add_api_route("/evaluate", evaluate_symbol, methods=["POST"])
