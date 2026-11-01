"""
Scalper Global Agent - AI & Quantitative Trading Suite (21 Integrated Architectures & Models):
21. CVD & Order Flow Absorption (Cumulative Volume Delta & Iceberg Detection)
20. Kelly Criterion Sizing (Optimal Capital Growth & Ruin Barrier)
19. Hidden Markov Models (HMM Latent Market Regime Classifier)
18. Institutional Volume Profile & POC (Point of Control & Value Area VAH/VAL)
17. Kalman Filter Zero-Lag Trend (Noise-Filtered State Velocity)
16. QuantConnect LEAN (Portfolio Parity & Clustered Risk Sizing)
15. Microsoft RD-Agent (Autonomous Hypothesis & Self-Correction R&D)
14. FinGPT (Financial News Sentiment & Polarization)
13. Jesse (Genetic Dynamic Risk/Reward & Trailing Stop Optimizer)
12. OpenBB (Global Macro & Economic Calendar Regime Intelligence)
11. Microsoft Qlib (Alpha158/Alpha360 Multi-Factor Quantitative Scoring)
10. OctoBot (Matrix Evaluators & Consensus)
9. FinRobot (Macro News Sentiment & Calendar)
8. Vibe-Trading (Market Vibe & Social Momentum)
7. FinRL (Adaptive Trailing Exit & Fee Aware Policies)
6. AI-Trader (Self-Reflection & Bull/Bear Trap Auditor)
5. Hummingbot (High-Frequency Orderbook Imbalance)
4. NautilusTrader (Realistic Execution & Latency Fill Models)
3. Freqtrade (Protections & Dynamic ROI Table)
2. ai-hedge-fund (Multi-Persona Investment Committee)
1. TradingAgents (Institutional Desk Contracts & Risk Chief Veto)
"""

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
from .kalman_filter_trend import evaluate_kalman_trend, KalmanTrendResult
from .volume_profile_poc import evaluate_volume_profile, VolumeProfileResult
from .hmm_regime_classifier import evaluate_hmm_regime, HMMRegimeResult
from .kelly_criterion_sizer import evaluate_kelly_sizing, KellySizingResult
from .cvd_order_flow import evaluate_cvd_order_flow, CVDOrderFlowResult
from .orchestrator import (
    AITradingSuiteOrchestrator,
    UnifiedEvaluationRequest,
    UnifiedEvaluationResponse
)

__all__ = [
    "OctoBotMatrixEvaluator",
    "IndicatorEvaluation",
    "MatrixConsensusResult",
    "FinRobotMacroAnalyzer",
    "MacroEvent",
    "MacroAnalysisResult",
    "VibeBreakoutTracker",
    "VibeMetric",
    "VibeAnalysisResult",
    "FinRLAdaptiveEngine",
    "AdaptiveExitPlan",
    "AITraderSelfReflectionAuditor",
    "TradeThesis",
    "ReflectionAuditReport",
    "HummingbotMicrostructureAnalyzer",
    "OrderbookDepthSnapshot",
    "MicrostructureAnalysis",
    "NautilusExecutionModel",
    "OrderFillResult",
    "FreqtradeProtectionsEngine",
    "ProtectionStatus",
    "HedgeFundCouncil",
    "CouncilConsensus",
    "RiskChiefVetoEngine",
    "TradeContractProposal",
    "VetoVerdict",
    "TradeAction",
    "AssetClass",
    "evaluate_qlib_alpha",
    "QlibAlphaResult",
    "evaluate_openbb_macro",
    "OpenBBMacroResult",
    "evaluate_jesse_risk",
    "JesseRiskResult",
    "evaluate_fingpt_sentiment",
    "FinGPTSentimentResult",
    "evaluate_rd_agent_hypothesis",
    "RDAgentDiscoveryResult",
    "evaluate_lean_portfolio",
    "LeanPortfolioResult",
    "evaluate_kalman_trend",
    "KalmanTrendResult",
    "evaluate_volume_profile",
    "VolumeProfileResult",
    "evaluate_hmm_regime",
    "HMMRegimeResult",
    "evaluate_kelly_sizing",
    "KellySizingResult",
    "evaluate_cvd_order_flow",
    "CVDOrderFlowResult",
    "AITradingSuiteOrchestrator",
    "UnifiedEvaluationRequest",
    "UnifiedEvaluationResponse"
]
