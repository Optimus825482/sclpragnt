"""
AI Trading Suite Master Orchestrator for Scalper Global Agent.
Unifies all 16 open-source AI trading architectures into a single pipeline for Spot and Forex:
16. QuantConnect LEAN (Portfolio Parity & Clustered Risk Sizing)
15. Microsoft RD-Agent (Autonomous Hypothesis & Self-Correction R&D)
14. FinGPT (Financial News Sentiment & Polarization)
13. Jesse (Genetic Dynamic Risk/Reward & Trailing Stop Optimizer)
12. OpenBB (Global Macro & Economic Calendar Regime Intelligence)
11. Microsoft Qlib (Alpha158/Alpha360 Multi-Factor Quantitative Scoring)
10. OctoBot (Matrix Evaluators & Consensus)
9. FinRobot (Macro News & Event Interpreters)
8. Vibe-Trading (Social Buzz & FOMO Trap Tracker)
7. FinRL (Adaptive Trailing Exit & Fee Aware Policies)
6. AI-Trader (Self-Reflection & Bull/Bear Trap Auditor)
5. Hummingbot (High-Frequency Orderbook Imbalance)
4. NautilusTrader (Realistic Execution & Latency Fill Models)
3. Freqtrade (Protections, Cooldown & Dynamic ROI Table)
2. ai-hedge-fund (Multi-Persona Investment Committee)
1. TradingAgents (Institutional Desk Contracts & Risk Chief Veto)
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
from .qlib_alpha_evaluator import evaluate_qlib_alpha, QlibAlphaResult
from .openbb_macro_intel import evaluate_openbb_macro, OpenBBMacroResult
from .jesse_adaptive_risk import evaluate_jesse_risk, JesseRiskResult
from .fingpt_sentiment import evaluate_fingpt_sentiment, FinGPTSentimentResult
from .rd_agent_discovery import evaluate_rd_agent_hypothesis, RDAgentDiscoveryResult
from .lean_portfolio_engine import evaluate_lean_portfolio, LeanPortfolioResult


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
    dxy_change_pct: float = 0.0
    account_balance: float = 10000.0


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
    qlib_alpha: dict
    openbb_macro: dict
    jesse_risk: dict
    fingpt_sentiment: dict
    rd_agent: dict
    lean_portfolio: dict
    simulated_execution: Optional[dict]
    execution_directive: str


class AITradingSuiteOrchestrator:
    """
    Master coordinator orchestrating all 16 trading AI subsystems.
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

        # 9. (NEW) Microsoft Qlib Multi-Factor Alpha Evaluator
        qlib_ind = {
            "rsi": req.rsi_value,
            "atr": req.atr,
            "volume_ratio": req.volume_ratio,
            "adx": 25.0
        }
        qlib_res = evaluate_qlib_alpha(
            symbol=req.symbol,
            price=req.current_price,
            indicators=qlib_ind
        )

        # 10. (NEW) OpenBB Macroeconomic & Event Intelligence
        minutes_to_next = req.macro_events[0].minutes_until_event if req.macro_events else None
        openbb_res = evaluate_openbb_macro(
            symbol=req.symbol,
            asset_class="FOREX" if req.asset_type.upper() == "FOREX" else "CRYPTO",
            dxy_change_pct=req.dxy_change_pct,
            minutes_to_next_major_event=minutes_to_next
        )

        # 11. (NEW) Jesse Adaptive Risk & Execution Model
        jesse_res = evaluate_jesse_risk(
            symbol=req.symbol,
            entry_price=req.current_price,
            atr=req.atr,
            volatility_mode="HIGH" if abs(req.price_change_pct) > 4.0 else "NORMAL"
        )

        # 12. (NEW) FinGPT Financial Sentiment & Narrative Analyzer
        fingpt_res = evaluate_fingpt_sentiment(
            symbol=req.symbol,
            social_volume_ratio=req.volume_ratio,
            sentiment_hint=macro_res.macro_sentiment_score
        )

        # 13. (NEW) Microsoft RD-Agent Hypothesis & Feedback Engine
        rd_metrics = {
            "score": matrix_res.consensus_confidence * 100.0,
            "atr_pct": (req.atr / max(req.current_price, 0.0001)) * 100.0,
            "volume_ratio": req.volume_ratio,
            "consensus_pct": matrix_res.consensus_confidence * 100.0
        }
        rd_res = evaluate_rd_agent_hypothesis(
            symbol=req.symbol,
            setup_name="AI_CONSENSUS_BREAKOUT",
            metrics=rd_metrics
        )

        # 14. (NEW) QuantConnect LEAN Portfolio & Volatility Parity Sizing
        lean_res = evaluate_lean_portfolio(
            symbol=req.symbol,
            account_balance=req.account_balance,
            risk_pct_per_trade=1.0,
            atr_pct=(req.atr / max(req.current_price, 0.0001)) * 100.0,
            asset_class=req.asset_type
        )

        # 15. TradingAgents Institutional Contract & Risk Chief Veto
        action_enum = TradeAction.BUY if req.proposed_action == "BUY" else (
            TradeAction.SELL if req.proposed_action == "SELL" else TradeAction.WAIT
        )

        # Harmonize with Jesse dynamic parameters
        if req.proposed_action == "BUY":
            entry_target = req.current_price
            stop_loss = min(exit_plan.recommended_stop_loss, jesse_res.optimized_sl)
            tp1 = max(exit_plan.take_profit_target_1, jesse_res.optimized_tp1)
            tp2 = max(exit_plan.take_profit_target_2, jesse_res.optimized_tp2)
            risk_dist = max(0.0001, entry_target - stop_loss)
            reward_dist = max(0.0001, tp1 - entry_target)
            target_risk_reward = round(reward_dist / risk_dist, 2)
        elif req.proposed_action == "SELL":
            entry_target = req.current_price
            stop_loss = max(exit_plan.recommended_stop_loss, req.current_price + (req.current_price - jesse_res.optimized_sl))
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
            target_risk_reward = 2.0

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
            proposed_lot_or_qty=lean_res.suggested_units_or_lot,
            account_margin_used_pct=req.account_margin_used_pct,
            spread_pips_or_pct=req.spread_pips_or_pct,
            macro_event_within_minutes=minutes_to_next,
            daily_drawdown_so_far_pct=req.daily_drawdown_pct,
            thesis_summary=thesis.primary_reason
        )

        # Risk Chief Veto Evaluation
        veto_res = self.desk.review_contract(proposal)

        # Extended vetos from new architectures
        if not protection.is_trading_allowed:
            veto_res.approved = False
            veto_res.final_action = TradeAction.WAIT
            veto_res.veto_reasons.append(f"Freqtrade Koruması Devrede: {protection.reason}")
        if not openbb_res.safe_to_trade:
            veto_res.approved = False
            veto_res.final_action = TradeAction.WAIT
            veto_res.veto_reasons.append(f"OpenBB Makro Vetosu: {openbb_res.verdict}")
        if fingpt_res.veto_trade:
            veto_res.approved = False
            veto_res.final_action = TradeAction.WAIT
            veto_res.veto_reasons.append(f"FinGPT NLP Vetosu: {fingpt_res.sentiment_summary}")
        if not lean_res.portfolio_approved:
            veto_res.approved = False
            veto_res.final_action = TradeAction.WAIT
            veto_res.veto_reasons.append(f"QuantConnect LEAN Vetosu: {lean_res.cluster_warning}")

        # 16. NautilusTrader Realistic Latency & Slippage Fill Simulation
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
            directive = f"16-Yapay Zeka Mimarisi Onayladı: {req.current_price:.4f} seviyesinde alım. Stop: {stop_loss:.4f}, TP1: {tp1:.4f} (R:R: {target_risk_reward:.2f})."
        elif veto_res.approved and veto_res.final_action == TradeAction.SELL:
            final_verdict = "APPROVED_SELL"
            directive = f"16-Yapay Zeka Mimarisi Onayladı: {req.current_price:.4f} seviyesinde satım. Stop: {stop_loss:.4f}, TP1: {tp1:.4f}."
        elif not veto_res.approved:
            final_verdict = "VETOED"
            directive = f"Risk Şefi Vetosu: {', '.join(veto_res.veto_reasons)}"
        else:
            final_verdict = "WAIT"
            directive = "Piyasa dengede veya belirsiz. Aktif takip devam ediyor."

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
            qlib_alpha=qlib_res.model_dump(),
            openbb_macro=openbb_res.model_dump(),
            jesse_risk=jesse_res.model_dump(),
            fingpt_sentiment=fingpt_res.model_dump(),
            rd_agent=rd_res.model_dump(),
            lean_portfolio=lean_res.model_dump(),
            simulated_execution=asdict(simulated_fill) if simulated_fill else None,
            execution_directive=directive
        )
