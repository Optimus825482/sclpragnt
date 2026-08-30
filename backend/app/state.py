"""Shared market singletons.

`market` and `analyzer` are created once at import time (same lifecycle the
old app.main module had) and imported by main.py and every router module.
"""
from app.config import config
from app.market_data import MarketData
from app.analyzer import ScalpAnalyzer

market = MarketData(config.SYMBOLS)
analyzer = ScalpAnalyzer(market)
