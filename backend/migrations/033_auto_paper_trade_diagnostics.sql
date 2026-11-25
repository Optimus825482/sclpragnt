CREATE TABLE IF NOT EXISTS auto_paper_trade_diagnostics (
    trade_id BIGINT PRIMARY KEY REFERENCES auto_paper_trades(id) ON DELETE CASCADE,
    entry_evidence JSONB,
    exit_evidence JSONB
);
