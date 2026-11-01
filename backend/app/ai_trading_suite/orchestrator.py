"""
AI Trading Suite Master Orchestrator for Scalper Global Agent.
Unifies all 10 open-source AI trading architectures into a single pipeline for Spot and Forex.
"""
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
import time

from .octobot_matrix import OctoBotMatrixEvaluator, IndicatorEvaluation, MatrixConsensusResult
from .finrobot_macro import FinRobotMacroAnalyzer, MacroEvent, MacroAnalysisResult
from .vibe_trading import VibeBreakoutTracker, VibeMetric, VibeAnalysisResult
from .finrl_adaptive import FinRLAdaptiveEngine, AdaptiveExitPlan
from .ai_trader_reflection import AITraderSelfReflectionAuditor, TradeThesis, ReflectionAuditReport
from .hummingbot_microstructure import HummingbotMicrostructureAnalyzer, OrderbookDepthSnapshot, MicrostructureAnalysis
from .nautilus_execution import NautilusExecutionModel, OrderFillResult
from .freqtrade_protections import FreqtradeProtectionsEngine, ProtectionStatus
from .hedge_fund_council import HedgeFundCouncil, CouncilConsensus
from .trading_agents_desk import (
    RiskChiefVetoEngine,
    TradeContractProposal,
    VetoVerdict,
    TradeAction,
    AssetClass
)


@dataclass
class UnifiedEvaluationRequest:
    symbol: str
    asset_type: str  # "SPOT" or "FOREX"
    current_price: float
    atr: float
    indicators: List[IndicatorEvaluation]
    macro_events: List[MacroEvent]
    orderbook_bids: List[tuple]
    orderbook_asks: List[tuple]
    price_change_pct: float
    volume_ratio: float
    social_buzz: float
    quant_z_score: float
    rsi_value: float
    trend_slope: float
    proposed_action: str  # "BUY", "SELL", or "WAIT"
    daily_drawdown_pct: float = 0.0
    account_margin_used_pct: float = 5.0
    spread_pips_or_pct: float = 0.0005


@dataclass
class UnifiedEvaluationResponse:
    symbol: str
    asset_type: str
    timestamp: float
    final_verdict: str  # "APPROVED_BUY", "APPROVED_SELL", "VETOED", "WAIT"
    risk_chief_approved: bool
    confidence_score: float
    proposed_contract: Optional[dict]
    veto_verdict: dict
    matrix_consensus: dict
    macro_analysis: dict
    vibe_analysis: dict
    adaptive_exit: dict
    self_reflection: dict
    microstructure: dict
    protections_status: dict
    hedge_fund_council: dict
    simulated_execution: Optional[dict]
    execution_directive: str


class AITradingSuiteOrchestrator:
    """
    Central coordinator orchestrating all 10 trading AI subsystems.
    """

    def __init__(self):
        self.octobot = OctoBotMatrixEvaluator(consensus_threshold=0.60)
        self.finrobot = FinRobotMacroAnalyzer()
        self.vibe = VibeBreakoutTracker()
        self.finrl = FinRLAdaptiveEngine()
        self.ai_trader = AITraderSelfReflectionAuditor()
        self.hummingbot = HummingbotMicrostructureAnalyzer()
        self.nautilus = NautilusExecutionModel()
        self.freqtrade = FreqtradeProtectionsEngine()
        self.council = HedgeFundCouncil()
        self.desk = RiskChiefVetoEngine()

    def evaluate(self, req: UnifiedEvaluationRequest) -> UnifiedEvaluationResponse:
        now = time.time()
        asset_class = AssetClass.SPOT if req.asset_type.upper() == "SPOT" else AssetClass.FOREX

        # 1. Freqtrade Protections Check
        protection = self.freqtrade.evaluate_protection(
            symbol=req.symbol,
            current_drawdown_pct=req.daily_drawdown_pct
        )

        # 2. OctoBot Matrix Consensus
        matrix_res = self.octobot.evaluate(
            symbol=req.symbol,
            asset_type=req.asset_type,
            evaluations=req.indicators
        )

        # 3. FinRobot Macro Analysis
        macro_res = self.finrobot.analyze(events=req.macro_events)

        # 4. Hummingbot Microstructure
        book_snapshot = OrderbookDepthSnapshot(
            symbol=req.symbol,
            bids=req.orderbook_bids,
            asks=req.orderbook_asks,
            timestamp=now
        )
        micro_res = self.hummingbot.analyze_orderbook(snapshot=book_snapshot)

        # 5. Vibe-Trading Sentiment & Breakout
        vibe_metric = VibeMetric(
            symbol=req.symbol,
            asset_type=req.asset_type,
            price_change_pct=req.price_change_pct,
            volume_ratio=req.volume_ratio,
            social_buzz_score=req.social_buzz,
            sentiment_velocity=0.1,
            orderbook_depth_ratio=max(0.1, micro_res.total_bid_liquidity / max(0.1, micro_res.total_ask_liquidity))
        )
        vibe_res = self.vibe.analyze_vibe(vibe_metric)

        # 6. ai-hedge-fund Deliberation
        council_res = self.council.deliberate(
            symbol=req.symbol,
            asset_type=req.asset_type,
            macro_score=macro_res.macro_sentiment_score,
            quant_z_score=req.quant_z_score,
            volatility_regime="EXTREME" if abs(req.price_change_pct) > 5.0 else "NORMAL",
            rsi_value=req.rsi_value,
            trend_slope=req.trend_slope
        )

        # 7. AI-Trader Self-Reflection & Trap Audit
        thesis = TradeThesis(
            symbol=req.symbol,
            asset_type=req.asset_type,
            proposed_action=req.proposed_action,
            timeframe="5m",
            primary_reason=f"Matrix consensus {matrix_res.consensus_signal} with council {council_res.consensus_decision}",
            indicators_supporting=[i.indicator_name for i in req.indicators if i.signal > 0.2],
            volume_trend="EXPANDING" if req.volume_ratio > 1.2 else "DECLINING",
            cvd_alignment=(micro_res.flow_direction == "BULLISH_PRESSURE" and req.proposed_action == "BUY"),
            near_key_resistance=(req.quant_z_score > 1.8),
            near_key_support=(req.quant_z_score < -1.8)
        )
        reflection_res = self.ai_trader.audit_trade_proposal(
            thesis=thesis,
            raw_confidence=matrix_res.consensus_confidence
        )

        # 8. FinRL Adaptive Exit Planning
        exit_plan = self.finrl.compute_exit_policy(
            symbol=req.symbol,
            asset_type=req.asset_type,
            entry_price=req.current_price,
            current_price=req.current_price,
            atr=req.atr,
            holding_bars=1,
            highest_price_since_entry=req.current_price,
            side=req.proposed_action
        )

        # 9. TradingAgents Institutional Contract & Risk Chief Veto
        action_enum = TradeAction.BUY if req.proposed_action == "BUY" else (
            TradeAction.SELL if req.proposed_action == "SELL" else TradeAction.WAIT
        )

        target_risk_reward = 2.0
        if req.proposed_action == "BUY":
            entry_target = req.current_price
            stop_loss = exit_plan.recommended_stop_loss
            tp1 = exit_plan.take_profit_target_1
            tp2 = exit_plan.take_profit_target_2
            risk_dist = max(0.0001, entry_target - stop_loss)
            reward_dist = max(0.0001, tp1 - entry_target)
            target_risk_reward = round(reward_dist / risk_dist, 2)
        elif req.proposed_action == "SELL":
            entry_target = req.current_price
            stop_loss = exit_plan.recommended_stop_loss
            tp1 = exit_plan.take_profit_target_1
            tp2 = exit_plan.take_profit_target_2
            risk_dist = max(0.0001, stop_loss - entry_target)
            reward_dist = max(0.0001, entry_target - tp1)
            target_risk_reward = round(reward_dist / risk_dist, 2)
        else:
            entry_target = req.current_price
            stop_loss = req.current_price * 0.98
            tp1 = req.current_price * 1.02
            tp2 = req.current_price * 1.04

        proposal = TradeContractProposal(
            symbol=req.symbol,
            asset_class=asset_class,
            action=action_enum,
            confidence=reflection_res.final_confidence,
            current_price=req.current_price,
            entry_target=entry_target,
            stop_loss=stop_loss,
            take_profit_1=tp1,
            take_profit_2=tp2,
            risk_reward_ratio=target_risk_reward,
            proposed_lot_or_qty=1.0,
            account_margin_used_pct=req.account_margin_used_pct,
            spread_pips_or_pct=req.spread_pips_or_pct,
            macro_event_within_minutes=req.macro_events[0].minutes_until_event if req.macro_events else None,
            daily_drawdown_so_far_pct=req.daily_drawdown_pct,
            thesis_summary=thesis.primary_reason
        )

        # Apply Freqtrade protection override into Risk Chief
        veto_res = self.desk.review_contract(proposal)
        if not protection.is_trading_allowed:
            veto_res.approved = False
            veto_res.final_action = TradeAction.WAIT
            veto_res.veto_reasons.append(f"Freqtrade Protection Triggered: {protection.reason}")
            veto_res.audit_notes = "Vetoed due to circuit breaker protection."

        # 10. NautilusTrader Simulated Fill if Approved
        simulated_fill = None
        if veto_res.approved and veto_res.final_action in (TradeAction.BUY, TradeAction.SELL):
            simulated_fill = self.nautilus.simulate_fill(
                symbol=req.symbol,
                side=veto_res.final_action.value,
                requested_price=req.current_price,
                quantity=veto_res.adjusted_lot_or_qty,
                current_atr=req.atr
            )

        if veto_res.approved and veto_res.final_action == TradeAction.BUY:
            final_verdict = "APPROVED_BUY"
            directive = f"Paper/Demo Buy order authorized at {req.current_price:.4f} with dynamic trail stop at {exit_plan.recommended_stop_loss:.4f}."
        elif veto_res.approved and veto_res.final_action == TradeAction.SELL:
            final_verdict = "APPROVED_SELL"
            directive = f"Paper/Demo Sell order authorized at {req.current_price:.4f} with dynamic trail stop at {exit_plan.recommended_stop_loss:.4f}."
        elif not veto_res.approved:
            final_verdict = "VETOED"
            directive = f"Order blocked by Risk Chief: {', '.join(veto_res.veto_reasons)}"
        else:
            final_verdict = "WAIT"
            directive = "Market in non-actionable equilibrium. Maintain active monitoring."

        return UnifiedEvaluationResponse(
            symbol=req.symbol,
            asset_type=req.asset_type.upper(),
            timestamp=now,
            final_verdict=final_verdict,
            risk_chief_approved=veto_res.approved,
            confidence_score=reflection_res.final_confidence,
            proposed_contract=proposal.model_dump(),
            veto_verdict=veto_res.model_dump(),
            matrix_consensus=asdict(matrix_res),
            macro_analysis=asdict(macro_res),
            vibe_analysis=asdict(vibe_res),
            adaptive_exit=asdict(exit_plan),
            self_reflection=asdict(reflection_res),
            microstructure=asdict(micro_res),
            protections_status=asdict(protection),
            hedge_fund_council=asdict(council_res),
            simulated_execution=asdict(simulated_fill) if simulated_fill else None,
            execution_directive=directive
        )
