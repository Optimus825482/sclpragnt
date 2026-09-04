# Taste — Workflow & testing

- Requires every strategy/signal change to be validated empirically before going live: research → backtest/replay → compare against the current live strategy → only integrate if positive. Confidence: 0.9
- Wants each test to mirror the live strategy exactly (same SL/TP and rules) except for the single variable under test; runs separate tests per isolated change. Confidence: 0.85
- Rejects lookahead/hindsight analysis — evaluations must use only conditions measurable at signal time ("giriş anındaki ölçülebilir koşullar"), never reasoning from what happened afterward. Confidence: 0.8
- Prefers replay/backtest on historical data pulled from the public API (e.g., 48–72h) that reproduces live behavior, including which symbols would have been active at that time. Confidence: 0.75
- Wants quantitative comparison of variants and thresholds (e.g., score ≥3 vs ≥4, accuracy %, 15-min post-signal direction/move) rather than subjective verdicts. Confidence: 0.8
- Likes multi-timeframe pattern analysis of entry-time snapshots (M1/M5/M15/H1/H4) to find features separating profitable from losing trades before finalizing a rule set. Confidence: 0.85
