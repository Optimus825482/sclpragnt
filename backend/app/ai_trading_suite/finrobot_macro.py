"""
FinRobot-inspired Macro News Sentiment & Economic Event Analyzer.
Extracts macroeconomic sentiment, FOMC/NFP/CPI impact, and DXY/Gold directional bias.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime, timezone


@dataclass
class MacroEvent:
    event_name: str
    currency: str  # "USD", "EUR", "GBP", "JPY", "ALL"
    impact: str    # "HIGH", "MEDIUM", "LOW"
    sentiment_score: float  # -1.0 (Dovish/Bearish) to +1.0 (Hawkish/Bullish)
    actual: Optional[float] = None
    forecast: Optional[float] = None
    previous: Optional[float] = None
    minutes_until_event: Optional[int] = None


@dataclass
class MacroAnalysisResult:
    timestamp: str
    dxy_bias: str           # "BULLISH", "BEARISH", "NEUTRAL"
    xau_bias: str           # "BULLISH", "BEARISH", "NEUTRAL"
    crypto_bias: str        # "BULLISH", "BEARISH", "NEUTRAL"
    macro_sentiment_score: float  # -1.0 to +1.0
    high_impact_near: bool
    recommended_action: str  # "NORMAL_TRADING", "REDUCE_SIZE", "PAUSE_TRADING"
    currency_sentiments: Dict[str, float]
    events_considered: List[MacroEvent]
    rationale: str


class FinRobotMacroAnalyzer:
    """
    Analyzes macro headlines, central bank outlook, and economic calendar prints.
    Crucial for MT5 Forex (EURUSD, GBPUSD, USDJPY, XAUUSD) and BTC macro correlations.
    """

    HIGH_IMPACT_RESTRICT_MINUTES = 30

    def analyze(self, events: List[MacroEvent], custom_headlines: Optional[List[str]] = None) -> MacroAnalysisResult:
        if not events:
            return MacroAnalysisResult(
                timestamp=datetime.now(timezone.utc).isoformat(),
                dxy_bias="NEUTRAL",
                xau_bias="NEUTRAL",
                crypto_bias="NEUTRAL",
                macro_sentiment_score=0.0,
                high_impact_near=False,
                recommended_action="NORMAL_TRADING",
                currency_sentiments={"USD": 0.0, "EUR": 0.0, "GBP": 0.0},
                events_considered=[],
                rationale="No macro events currently in queue; macro conditions remain neutral."
            )

        currency_scores: Dict[str, List[float]] = {}
        high_impact_near = False

        for ev in events:
            curr = ev.currency.upper()
            currency_scores.setdefault(curr, []).append(ev.sentiment_score)

            if ev.impact.upper() == "HIGH" and ev.minutes_until_event is not None:
                if 0 <= ev.minutes_until_event <= self.HIGH_IMPACT_RESTRICT_MINUTES:
                    high_impact_near = True

        currency_sentiments: Dict[str, float] = {}
        for curr, scores in currency_scores.items():
            currency_sentiments[curr] = round(sum(scores) / len(scores), 3)

        usd_score = currency_sentiments.get("USD", 0.0)

        # DXY is directly proportional to USD sentiment
        if usd_score >= 0.25:
            dxy_bias = "BULLISH"
        elif usd_score <= -0.25:
            dxy_bias = "BEARISH"
        else:
            dxy_bias = "NEUTRAL"

        # Gold (XAUUSD) has an inverse relationship with strong USD & real yields
        if usd_score >= 0.30:
            xau_bias = "BEARISH"
        elif usd_score <= -0.30:
            xau_bias = "BULLISH"
        else:
            xau_bias = "NEUTRAL"

        # Crypto (BTC/ETH) generally thrives in risk-on / weaker dollar liquidity
        if usd_score >= 0.40:
            crypto_bias = "BEARISH"
        elif usd_score <= -0.20:
            crypto_bias = "BULLISH"
        else:
            crypto_bias = "NEUTRAL"

        if high_impact_near:
            action = "PAUSE_TRADING"
            rationale = "High-impact economic release imminent within 30 minutes. Spread widening danger."
        elif abs(usd_score) > 0.65:
            action = "REDUCE_SIZE"
            rationale = f"Elevated USD volatility detected (USD Score: {usd_score}). Scale down leverage/size."
        else:
            action = "NORMAL_TRADING"
            rationale = "Macro factors are within stable operational parameters."

        return MacroAnalysisResult(
            timestamp=datetime.now(timezone.utc).isoformat(),
            dxy_bias=dxy_bias,
            xau_bias=xau_bias,
            crypto_bias=crypto_bias,
            macro_sentiment_score=usd_score,
            high_impact_near=high_impact_near,
            recommended_action=action,
            currency_sentiments=currency_sentiments,
            events_considered=events,
            rationale=rationale
        )
