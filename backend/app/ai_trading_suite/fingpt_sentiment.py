"""AI4Finance FinGPT inspired Financial Sentiment & Narrative Analyzer.

Features:
- Quantitative financial sentiment polarity (-1.0 to +1.0)
- News and social media polarization index
- Market narrative classification (BULLISH_CATALYST, BEARISH_PANIC, RUMOR, NORMAL)
- Sentiment-based veto for extreme negative news spikes.
"""
from __future__ import annotations

import re
from typing import List, Optional
from pydantic import BaseModel, Field


class FinGPTSentimentResult(BaseModel):
    symbol: str
    sentiment_score: float = Field(..., ge=-1.0, le=1.0, description="FinGPT Polarity (-1.0 to +1.0)")
    polarization_index: float = Field(..., ge=0.0, le=1.0, description="0=Consensus, 1=Extreme disagreement")
    narrative_type: str = Field(..., description="BULLISH_CATALYST, BEARISH_PANIC, RUMOR, or BALANCED")
    veto_trade: bool
    sentiment_summary: str


_POSITIVE_KEYWORDS = {
    "breakout", "partnership", "upgrade", "growth", "inflow", "rally", "listing",
    "profit", "approval", "surge", "acquisition", "record", "bullish", "expansion"
}

_NEGATIVE_KEYWORDS = {
    "hack", "exploit", "investigation", "lawsuit", "ban", "crash", "downgrade",
    "outflow", "delist", "scam", "halt", "insolvency", "fraud", "bearish", "dump"
}


def evaluate_fingpt_sentiment(
    symbol: str,
    news_titles: Optional[List[str]] = None,
    social_volume_ratio: float = 1.0,
    sentiment_hint: Optional[float] = None
) -> FinGPTSentimentResult:
    """Evaluates financial news sentiment and polarization inspired by FinGPT."""
    sym = symbol.upper()
    news_titles = news_titles or []

    pos_count = 0
    neg_count = 0

    for title in news_titles:
        text = title.lower()
        words = set(re.findall(r'\b[a-z]{3,}\b', text))
        pos_count += len(words & _POSITIVE_KEYWORDS)
        neg_count += len(words & _NEGATIVE_KEYWORDS)

    total_matches = pos_count + neg_count

    if sentiment_hint is not None:
        score = max(-1.0, min(1.0, sentiment_hint))
    elif total_matches > 0:
        score = (pos_count - neg_count) / float(total_matches)
    else:
        score = 0.15  # Mild baseline optimistic default for candidate tracking

    # Polarization: high if both positive and negative signals are warring
    if total_matches >= 3 and pos_count > 0 and neg_count > 0:
        polarization = round(min(1.0, (min(pos_count, neg_count) * 2.0) / total_matches), 2)
    else:
        polarization = 0.20

    if score >= 0.40:
        narrative = "BULLISH_CATALYST"
        summary = "FinGPT NLP: Pozitif haber ve güçlü alım katalizörü tespit edildi."
    elif score <= -0.40:
        narrative = "BEARISH_PANIC"
        summary = "FinGPT NLP: Negatif haber akışı ve panik satışı baskısı mevcut."
    elif polarization >= 0.60:
        narrative = "RUMOR"
        summary = "FinGPT NLP: Yüksek kutuplaşma ve dedikodu volatilitesi, yönsüz çalkantı riski."
    else:
        narrative = "BALANCED"
        summary = "FinGPT NLP: Dengeli haber akışı, olağandışı negatif haber baskısı yok."

    veto = (score <= -0.50) or (narrative == "BEARISH_PANIC" and social_volume_ratio > 2.0)

    return FinGPTSentimentResult(
        symbol=sym,
        sentiment_score=round(score, 2),
        polarization_index=polarization,
        narrative_type=narrative,
        veto_trade=veto,
        sentiment_summary=summary
    )
