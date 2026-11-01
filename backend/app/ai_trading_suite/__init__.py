"""
Scalper Global Agent - AI Trading Suite
Incorporates proven mechanisms from:
10. OctoBot (Matrix Evaluators)
9. FinRobot (Macro News Sentiment)
8. Vibe-Trading (Market Vibe & Social Momentum)
7. FinRL (Adaptive Trailing Exit & Fee Aware Policies)
6. AI-Trader (Self-Reflection & Trap Defense)
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
    "AITradingSuiteOrchestrator",
    "UnifiedEvaluationRequest",
    "UnifiedEvaluationResponse"
]
