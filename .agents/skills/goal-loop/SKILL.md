---
name: goal-loop
description: Run a bounded plan-act-test-review-iterate loop for long-running, verifiable engineering work. Use for backtests, regression hardening, QA, migrations, or multi-step fixes with an explicit validation command and stop condition.
---

# Goal Loop

Use this workflow only when the task has a concrete, testable finish line. Do not use it for open-ended market commentary or strategy activation.

## Contract

Before acting, define:

- **Objective:** one concrete outcome.
- **Read first:** relevant source, tests, configuration, and repository instructions.
- **Constraints:** files, APIs, dependencies, and safety boundaries that must not change.
- **Validate:** exact commands that prove each increment.
- **Stop when:** the validation passes or further progress requires a product decision.

## Loop

1. Inspect current state and capture a baseline.
2. Make the smallest scoped change.
3. Run targeted tests or checks immediately.
4. Review the diff and failure output.
5. Fix, re-run, and only then broaden validation.
6. Report changed files, commands, results, and remaining gaps.

Never delete, weaken, skip, or narrow tests to make the goal pass. Do not refactor unrelated code or add dependencies without an explicit need.

## Scalper guardrails

For Scalper work, preserve paper-only/public-data behavior, the 10,000 TL initial balance, and the distinction between `BUY_BLOCKED` and `BUY_SIGNAL`. A backtest or research result is not permission to activate a strategy. Require fee-aware results and state data limitations explicitly.
