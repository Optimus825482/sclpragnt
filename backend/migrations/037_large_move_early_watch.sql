CREATE TABLE IF NOT EXISTS large_move_early_watch (
  symbol TEXT NOT NULL,
  seed_ms BIGINT NOT NULL,
  base_price DOUBLE PRECISION NOT NULL,
  watch_ms BIGINT NOT NULL,
  watch_price DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (symbol, seed_ms)
);

CREATE INDEX IF NOT EXISTS idx_large_move_early_watch_time
  ON large_move_early_watch (watch_ms DESC);
