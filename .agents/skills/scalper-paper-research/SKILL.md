---
name: scalper-paper-research
description: Conduct auditable paper-trading research for Scalper Agent using fresh public market data, reproducible backtests, fee-aware metrics, and out-of-sample checks. Use for strategy research, candidate ranking, performance analysis, or deciding whether a paper strategy is eligible for further testing.
---

# Scalper Paper Research

The system is paper-only. Never place real orders, request exchange API keys, or describe a candidate as profitable without evidence.

## Required workflow

1. Read the active strategy/configuration and identify the real data adapter, timeframe, symbols, fees, slippage assumptions, and date window.
2. Use fresh public data where available; record source, retrieval time, time zone, missing intervals, and candle count. Never substitute mock rows or label a proxy as spot data.
3. Establish a baseline before changing a strategy. Keep in-sample, validation, and out-of-sample windows separate; avoid look-ahead and overlapping leakage.
4. Evaluate aggregate net PnL after commission and modeled slippage, trade count, expectancy, drawdown, profit factor, exposure, exit reasons, and wallet reconciliation. Win rate alone is insufficient.
5. Segment results by symbol, timeframe, strategy, market regime, and exit reason. Call out small samples and missing microstructure fields such as spread, depth, and entry slippage.
6. Stress-test reasonable fee/slippage changes and compare against a simple baseline. Do not activate a candidate based on a short favorable window.

## Paper execution rules

- Initial paper balance remains 10,000 TL unless explicitly changed.
- `BUY_BLOCKED` or `liquidity_filter:*` means no trade and no opened position.
- Only `BUY_SIGNAL` opens a paper position.
- Retry eligible ranked candidates after a rejection, while preserving the rejection reason in the normal log flow.
- Preserve the existing order-size default and confirm its currency before interpreting PnL.

## Report format

Return: data provenance, exact configuration, sample/window, gross and net metrics, fees/slippage, risk and reconciliation checks, failure modes, confidence, and a recommendation of `continue-testing`, `paper-candidate`, or `reject`. Separate observed facts from inference. A missing field is unknown, not zero.

## Verification

Run the narrowest relevant backtest/test first, then `git diff --check`, backend compilation/tests, and frontend build when touched. If real-data integration or a full build cannot run, state that limitation explicitly.
