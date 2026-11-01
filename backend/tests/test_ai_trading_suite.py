"""
Unit and Integration Test Suite for Scalper Global Agent AI Trading Suite.
Validates all 10 architectures individually and their end-to-end orchestration.
"""
import pytest
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.ai_trading_suite import (
    OctoBotMatrixEvaluator,
    IndicatorEvaluation,
    FinRobotMacroAnalyzer,
    MacroEvent,
    VibeBreakoutTracker,
    VibeMetric,
    FinRLAdaptiveEngine,
    AITraderSelfReflectionAuditor,
    TradeThesis,
    HummingbotMicrostructureAnalyzer,
    OrderbookDepthSnapshot,
    NautilusExecutionModel,
    FreqtradeProtectionsEngine,
    HedgeFundCouncil,
    RiskChiefVetoEngine,
    TradeContractProposal,
    TradeAction,
    AssetClass,
    AITradingSuiteOrchestrator,
    UnifiedEvaluationRequest,
    evaluate_qlib_alpha,
    evaluate_openbb_macro,
    evaluate_jesse_risk,
    evaluate_fingpt_sentiment,
    evaluate_rd_agent_hypothesis,
    evaluate_lean_portfolio
)


# 10. OctoBot Tests
def test_10_octobot_matrix_evaluator():
    evaluator = OctoBotMatrixEvaluator(consensus_threshold=0.60)
    indicators = [
        IndicatorEvaluation(indicator_name="ZL_MACD", signal=0.8, weight=1.5),
        IndicatorEvaluation(indicator_name="WaveTrend", signal=0.7, weight=1.2),
        IndicatorEvaluation(indicator_name="Supertrend", signal=0.9, weight=1.0),
        IndicatorEvaluation(indicator_name="RSI", signal=-0.2, weight=0.5),
    ]
    res = evaluator.evaluate(symbol="BTCUSDT", asset_type="SPOT", evaluations=indicators)
    assert res.consensus_signal in ("BUY", "STRONG_BUY")
    assert res.is_actionable is True
    assert res.composite_score > 0.40
    assert res.consensus_confidence >= 0.60


# 9. FinRobot Tests
def test_09_finrobot_macro_analyzer():
    analyzer = FinRobotMacroAnalyzer()
    events = [
        MacroEvent(event_name="FOMC Rate Decision", currency="USD", impact="HIGH", sentiment_score=0.75, minutes_until_event=15),
        MacroEvent(event_name="US CPI YoY", currency="USD", impact="HIGH", sentiment_score=0.60, minutes_until_event=120)
    ]
    res = analyzer.analyze(events=events)
    assert res.dxy_bias == "BULLISH"
    assert res.xau_bias == "BEARISH"
    assert res.high_impact_near is True
    assert res.recommended_action == "PAUSE_TRADING"


# 8. Vibe-Trading Tests
def test_08_vibe_trading_breakout():
    tracker = VibeBreakoutTracker()
    metric = VibeMetric(
        symbol="SOLUSDT",
        asset_type="SPOT",
        price_change_pct=3.2,
        volume_ratio=2.4,
        social_buzz_score=0.85,
        sentiment_velocity=0.3,
        orderbook_depth_ratio=1.6
    )
    res = tracker.analyze_vibe(metric)
    assert res.vibe_category == "HYPER_BULLISH"
    assert res.breakout_confirmed is True
    assert res.is_fomo_trap is False

    # Test FOMO trap condition
    fomo_metric = VibeMetric(
        symbol="MEMECOIN",
        asset_type="SPOT",
        price_change_pct=4.5,
        volume_ratio=0.8,  # weak volume
        social_buzz_score=0.9,
        sentiment_velocity=0.5,
        orderbook_depth_ratio=0.7  # thin book
    )
    fomo_res = tracker.analyze_vibe(fomo_metric)
    assert fomo_res.is_fomo_trap is True
    assert fomo_res.breakout_confirmed is False


# 7. FinRL Tests
def test_07_finrl_adaptive_trailing():
    engine = FinRLAdaptiveEngine(spot_fee_pct=0.001)
    # Scenario: Price surged, trailing stop should raise above breakeven
    plan = engine.compute_exit_policy(
        symbol="ETHUSDT",
        asset_type="SPOT",
        entry_price=2600.0,
        current_price=2690.0,
        atr=25.0,
        holding_bars=8,
        highest_price_since_entry=2700.0,
        side="BUY"
    )
    assert plan.trailing_activated is True
    assert plan.recommended_stop_loss > 2600.0 * 1.002  # Above entry plus roundtrip fees
    assert plan.exit_urgency in ("TIGHTEN_STOP", "PARTIAL_CLOSE", "IMMEDIATE_EXIT")


# 6. AI-Trader Tests
def test_06_ai_trader_self_reflection():
    auditor = AITraderSelfReflectionAuditor()
    # Bull trap setup: Price pushing resistance with declining volume and negative CVD
    thesis = TradeThesis(
        symbol="XAUUSD",
        asset_type="FOREX",
        proposed_action="BUY",
        timeframe="5m",
        primary_reason="Breakout above daily high",
        indicators_supporting=["EMA20"],
        volume_trend="DECLINING",
        cvd_alignment=False,
        near_key_resistance=True,
        near_key_support=False
    )
    report = auditor.audit_trade_proposal(thesis=thesis, raw_confidence=0.85)
    assert report.trap_detected == "BULL_TRAP"
    assert report.final_verdict == "REJECTED_TRAP"
    assert report.final_confidence < 0.50


# 5. Hummingbot Tests
def test_05_hummingbot_microstructure():
    analyzer = HummingbotMicrostructureAnalyzer()
    snapshot = OrderbookDepthSnapshot(
        symbol="BTCUSDT",
        bids=[(68000.0, 15.0), (67990.0, 20.0), (67980.0, 30.0)],
        asks=[(68002.0, 4.0), (68010.0, 5.0), (68020.0, 6.0)],
        timestamp=1000.0
    )
    res = analyzer.analyze_orderbook(snapshot=snapshot, max_spread_pct=0.001)
    assert res.flow_direction == "BULLISH_PRESSURE"
    assert res.imbalance_top_of_book > 0.40
    assert res.is_spread_acceptable is True


# 4. NautilusTrader Tests
def test_04_nautilus_execution_simulation():
    model = NautilusExecutionModel(default_fee_bps=10.0, base_latency_ms=40.0)
    res = model.simulate_fill(
        symbol="EURUSD",
        side="BUY",
        requested_price=1.0850,
        quantity=1.0,
        current_atr=0.0012,
        is_market_order=True
    )
    assert res.execution_status == "FILLED"
    assert res.filled_price >= 1.0850  # Slippage simulated on buy
    assert res.simulated_latency_ms >= 5.0
    assert res.fee_incurred > 0.0


# 3. Freqtrade Tests
def test_03_freqtrade_protections():
    engine = FreqtradeProtectionsEngine(
        max_consecutive_stops=2,
        stoploss_guard_cooldown_sec=300.0,
        symbol_cooldown_sec=120.0,
        max_drawdown_limit_pct=4.0
    )
    # Register 2 stoploss exits
    engine.register_trade_exit("BTCUSDT", pnl_pct=-0.012, exit_type="STOP_LOSS")
    engine.register_trade_exit("ETHUSDT", pnl_pct=-0.015, exit_type="STOP_LOSS")

    status = engine.evaluate_protection(symbol="SOLUSDT")
    assert status.is_trading_allowed is False
    assert status.active_circuit_breaker == "STOPLOSS_GUARD"

    # Test dynamic ROI
    assert engine.check_dynamic_roi(trade_duration_minutes=20, current_profit_pct=0.018) is True
    assert engine.check_dynamic_roi(trade_duration_minutes=5, current_profit_pct=0.005) is False


# 2. ai-hedge-fund Tests
def test_02_hedge_fund_council():
    council = HedgeFundCouncil()
    res = council.deliberate(
        symbol="XAUUSD",
        asset_type="FOREX",
        macro_score=0.65,
        quant_z_score=-0.2,
        volatility_regime="NORMAL",
        rsi_value=58.0,
        trend_slope=0.012
    )
    assert res.soros_vote.vote == "BULLISH"
    assert res.simons_vote.vote == "BULLISH"
    assert res.consensus_decision == "LONG"
    assert res.aggregate_score > 0.40


# 1. TradingAgents Tests
def test_01_trading_agents_desk_veto():
    desk = RiskChiefVetoEngine()
    
    # Contract with poor R:R ratio
    bad_proposal = TradeContractProposal(
        symbol="BTCUSDT",
        asset_class=AssetClass.SPOT,
        action=TradeAction.BUY,
        confidence=0.85,
        current_price=68000.0,
        entry_target=68000.0,
        stop_loss=67000.0,  # 1000 risk
        take_profit_1=68500.0,  # 500 reward -> R:R 0.5 < 1.4
        take_profit_2=69000.0,
        risk_reward_ratio=0.5,
        proposed_lot_or_qty=1.0,
        account_margin_used_pct=5.0,
        spread_pips_or_pct=0.0004,
        thesis_summary="Test setup"
    )
    verdict = desk.review_contract(bad_proposal)
    assert verdict.approved is False
    assert verdict.final_action == TradeAction.WAIT
    assert any("Substandard R:R ratio" in r for r in verdict.veto_reasons)

    # Valid proposal
    valid_proposal = TradeContractProposal(
        symbol="BTCUSDT",
        asset_class=AssetClass.SPOT,
        action=TradeAction.BUY,
        confidence=0.88,
        current_price=68000.0,
        entry_target=68000.0,
        stop_loss=67500.0,  # 500 risk
        take_profit_1=69500.0,  # 1500 reward -> R:R 3.0
        take_profit_2=70500.0,
        risk_reward_ratio=3.0,
        proposed_lot_or_qty=1.0,
        account_margin_used_pct=5.0,
        spread_pips_or_pct=0.0004,
        thesis_summary="High conviction confluence setup"
    )
    good_verdict = desk.review_contract(valid_proposal)
    assert good_verdict.approved is True
    assert good_verdict.final_action == TradeAction.BUY



# 11. Microsoft Qlib Tests
def test_11_qlib_alpha_evaluator():
    res = evaluate_qlib_alpha(
        symbol="BTCUSDT",
        price=65000.0,
        indicators={"rsi": 58.0, "atr": 1000.0, "volume_ratio": 1.4, "adx": 26.0}
    )
    assert res.alpha_score >= 50.0
    assert res.alpha_rank in ("STRONG_ALPHA", "MODERATE_ALPHA")
    assert res.action_bias == "BUY"


# 12. OpenBB Macro Tests
def test_12_openbb_macro_intel():
    res = evaluate_openbb_macro(
        symbol="EURUSD",
        asset_class="FOREX",
        dxy_change_pct=-0.45,
        minutes_to_next_major_event=240
    )
    assert res.macro_regime == "RISK_ON"
    assert res.dxy_bias == "BEARISH"
    assert res.safe_to_trade is True


# 13. Jesse Dynamic Risk Tests
def test_13_jesse_adaptive_risk():
    res = evaluate_jesse_risk(
        symbol="ETHUSDT",
        entry_price=3000.0,
        atr=40.0,
        volatility_mode="NORMAL"
    )
    assert res.risk_reward_ratio >= 1.40
    assert res.optimized_tp1 > 3000.0
    assert res.optimized_sl < 3000.0
    assert res.passes_jesse_standard is True


# 14. FinGPT Financial NLP Tests
def test_14_fingpt_sentiment():
    titles = ["Bitcoin surges past key level as institutional inflows hit record", "Major bank upgrade for crypto"]
    res = evaluate_fingpt_sentiment(symbol="BTCUSDT", news_titles=titles, social_volume_ratio=1.5)
    assert res.sentiment_score > 0.30
    assert res.narrative_type == "BULLISH_CATALYST"
    assert res.veto_trade is False


# 15. Microsoft RD-Agent Tests
def test_15_rd_agent_discovery():
    res = evaluate_rd_agent_hypothesis(
        symbol="SOLUSDT",
        setup_name="BREAKOUT",
        metrics={"score": 80.0, "atr_pct": 2.0, "volume_ratio": 1.5, "consensus_pct": 75.0}
    )
    assert res.is_hypothesis_supported is True
    assert res.empirical_confidence >= 65.0


# 16. QuantConnect LEAN Portfolio Tests
def test_16_lean_portfolio_engine():
    res = evaluate_lean_portfolio(
        symbol="BTCUSDT",
        account_balance=10000.0,
        risk_pct_per_trade=1.0,
        atr_pct=2.0,
        asset_class="CRYPTO"
    )
    assert res.allocated_risk_usd == 100.0
    assert res.suggested_units_or_lot > 0.0
    assert res.portfolio_approved is True


# End-to-End Orchestrator Tests for Spot & Forex
def test_master_orchestrator_spot():
    orchestrator = AITradingSuiteOrchestrator()
    req = UnifiedEvaluationRequest(
        symbol="BTCUSDT",
        asset_type="SPOT",
        current_price=68500.0,
        atr=450.0,
        indicators=[
            IndicatorEvaluation("ZL_MACD", 0.85, 1.5),
            IndicatorEvaluation("WaveTrend", 0.75, 1.2),
            IndicatorEvaluation("Supertrend", 0.90, 1.0)
        ],
        macro_events=[
            MacroEvent("Fed Speech", "USD", "LOW", -0.1, minutes_until_event=180)
        ],
        orderbook_bids=[(68495.0, 18.0), (68490.0, 25.0)],
        orderbook_asks=[(68505.0, 5.0), (68510.0, 6.0)],
        price_change_pct=1.8,
        volume_ratio=2.1,
        social_buzz=0.65,
        quant_z_score=-0.1,
        rsi_value=58.0,
        trend_slope=0.015,
        proposed_action="BUY",
        daily_drawdown_pct=0.5,
        account_margin_used_pct=4.0,
        spread_pips_or_pct=0.0003
    )
    resp = orchestrator.evaluate(req)
    assert resp.symbol == "BTCUSDT"
    assert resp.final_verdict == "APPROVED_BUY"
    assert resp.risk_chief_approved is True
    assert resp.simulated_execution is not None


def test_master_orchestrator_forex_news_veto():
    orchestrator = AITradingSuiteOrchestrator()
    # High impact news in 10 minutes should trigger Risk Chief veto
    req = UnifiedEvaluationRequest(
        symbol="XAUUSD",
        asset_type="FOREX",
        current_price=2735.50,
        atr=12.0,
        indicators=[
            IndicatorEvaluation("EMA_Cross", 0.8, 1.0)
        ],
        macro_events=[
            MacroEvent("US Non-Farm Payrolls", "USD", "HIGH", 0.8, minutes_until_event=10)
        ],
        orderbook_bids=[(2735.30, 20.0)],
        orderbook_asks=[(2735.70, 22.0)],
        price_change_pct=0.5,
        volume_ratio=1.1,
        social_buzz=0.2,
        quant_z_score=0.1,
        rsi_value=52.0,
        trend_slope=0.002,
        proposed_action="BUY",
        daily_drawdown_pct=0.0,
        account_margin_used_pct=3.0,
        spread_pips_or_pct=1.8
    )
    resp = orchestrator.evaluate(req)
    assert resp.symbol == "XAUUSD"
    assert resp.final_verdict == "VETOED"
    assert resp.risk_chief_approved is False
    assert any("macroeconomic event" in r for r in resp.veto_verdict["veto_reasons"])


# API Router Direct Tests
def test_api_routes_status_and_evaluation():
    from app.routers.ai_trading_suite_routes import get_suite_status, evaluate_symbol, EvaluationPayload, IndicatorInput

    # 1. Status route
    status = get_suite_status()
    assert status["status"] == "ONLINE"
    assert len(status["integrated_architectures"]) == 16

    # 2. Evaluation route
    payload = EvaluationPayload(
        symbol="EURUSD",
        asset_type="FOREX",
        current_price=1.0850,
        atr=0.0015,
        indicators=[
            IndicatorInput(indicator_name="EMA_Cross", signal=0.8, weight=1.0)
        ],
        price_change_pct=0.2,
        volume_ratio=1.5,
        social_buzz=0.0,
        quant_z_score=0.1,
        rsi_value=54.0,
        trend_slope=0.005,
        proposed_action="BUY",
        daily_drawdown_pct=0.1,
        account_margin_used_pct=2.0,
        spread_pips_or_pct=1.2
    )
    res = evaluate_symbol(payload)
    assert res["symbol"] == "EURUSD"
    assert res["asset_type"] == "FOREX"
    assert "veto_verdict" in res
    assert "matrix_consensus" in res
    assert "macro_analysis" in res
    assert "vibe_analysis" in res
    assert "adaptive_exit" in res
    assert "self_reflection" in res
    assert "microstructure" in res
    assert "protections_status" in res
    assert "hedge_fund_council" in res
    assert "qlib_alpha" in res
    assert "openbb_macro" in res
    assert "jesse_risk" in res
    assert "fingpt_sentiment" in res
    assert "rd_agent" in res
    assert "lean_portfolio" in res

