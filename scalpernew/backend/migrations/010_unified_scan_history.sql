CREATE TABLE IF NOT EXISTS unified_scan_runs (
  scan_id TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  started_at DOUBLE PRECISION NOT NULL,
  completed_at DOUBLE PRECISION NOT NULL,
  source TEXT NOT NULL,
  algorithm_version TEXT NOT NULL,
  candidate_count INTEGER NOT NULL DEFAULT 0,
  candidates JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_unified_scan_runs_user_started
  ON unified_scan_runs (username, started_at DESC);
