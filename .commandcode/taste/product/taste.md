# Taste — Product direction

- Prioritizes signal quality, profitability, and capital efficiency over trade count: false signals and positions that sit stagnant (capital-locking, "turtle"-like symbols) must be filtered, but filters should be developed via backward replay so profitable trades are minimally affected. Confidence: 0.9
- Wants LLM commentary focused on the near-term future ("ne olacak") and kept concise; predictions should be recorded to the DB and later scored for accuracy so the system can learn from its own past calls (self-learning loop). Confidence: 0.85
- Prefers consolidating related screens into one page with tabs, and clear at-a-glance visual states (e.g., PnL in green/red, bullish/bearish arrows per timeframe). Confidence: 0.7
- Wants user-facing monitoring/dashboard pages built with the user experience in the foreground: minimal technical jargon, plain-language status labels (balance, free balance, PnL, success/win-rate), and at-a-glance tracking rather than dense technical detail ("kullanıcı deneyimini ön planda tutarak çok fazla teknik detay içermeyen ve kullanıcıya net bilgi veren"). Confidence: 0.85
- Wants monitoring/dashboard features visible to BOTH regular users and the admin (added to the shared/sidebar menus), not admin-restricted — e.g., the portfolio-monitoring page tracking the autonomous paper-trade system. Confidence: 0.75
