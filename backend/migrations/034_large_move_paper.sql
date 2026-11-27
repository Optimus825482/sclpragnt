CREATE TABLE IF NOT EXISTS large_move_paper (
  symbol TEXT NOT NULL,
  seed_ms BIGINT NOT NULL,
  base_price DOUBLE PRECISION NOT NULL,
  watch_ms BIGINT NOT NULL,
  signal_ms BIGINT,
  signal_price DOUBLE PRECISION,
  spread_pct DOUBLE PRECISION,
  status TEXT NOT NULL CHECK (status IN ('watch', 'blocked', 'open', 'closed')),
  reason TEXT,
  opened_at DOUBLE PRECISION,
  entry_price DOUBLE PRECISION,
  quantity DOUBLE PRECISION,
  entry_cost DOUBLE PRECISION,
  fee_rate DOUBLE PRECISION,
  mark_price DOUBLE PRECISION,
  mark_net_pct DOUBLE PRECISION,
  marked_at DOUBLE PRECISION,
  exit_due_at DOUBLE PRECISION,
  closed_at DOUBLE PRECISION,
  exit_price DOUBLE PRECISION,
  net_pnl_try DOUBLE PRECISION,
  net_pnl_pct DOUBLE PRECISION,
  PRIMARY KEY (symbol, seed_ms)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_large_move_paper_open_symbol
  ON large_move_paper (symbol) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx_large_move_paper_watch
  ON large_move_paper (watch_ms DESC);
