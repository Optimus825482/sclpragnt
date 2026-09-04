CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS migration_meta (
  version TEXT PRIMARY KEY,
  source_path TEXT,
  source_sha256 TEXT,
  source_counts JSONB,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS positions (symbol TEXT PRIMARY KEY, side TEXT, entry_price DOUBLE PRECISION, stop_price DOUBLE PRECISION, take_profit DOUBLE PRECISION, peak_price DOUBLE PRECISION, breakeven_hit BOOLEAN, quantity DOUBLE PRECISION, entry_time DOUBLE PRECISION, strategy TEXT, entry_context JSONB, trade_id TEXT);
CREATE TABLE IF NOT EXISTS trades (id BIGINT PRIMARY KEY, symbol TEXT, strategy TEXT, side TEXT, entry_price DOUBLE PRECISION, exit_price DOUBLE PRECISION, quantity DOUBLE PRECISION, pnl DOUBLE PRECISION, pnl_pct DOUBLE PRECISION, entry_time DOUBLE PRECISION, exit_time DOUBLE PRECISION, commission DOUBLE PRECISION, reason TEXT, entry_context JSONB, max_favorable_pct DOUBLE PRECISION, max_adverse_pct DOUBLE PRECISION, hold_seconds DOUBLE PRECISION, trade_id TEXT);
ALTER TABLE positions ADD COLUMN IF NOT EXISTS trade_id TEXT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS trade_id TEXT;
CREATE TABLE IF NOT EXISTS signals (id BIGINT PRIMARY KEY, timestamp DOUBLE PRECISION, symbol TEXT, action TEXT, price DOUBLE PRECISION, reason TEXT, strategy TEXT, trade_id TEXT);
ALTER TABLE signals ADD COLUMN IF NOT EXISTS strategy TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS trade_id TEXT;
CREATE TABLE IF NOT EXISTS decision_logs (id BIGINT PRIMARY KEY, timestamp DOUBLE PRECISION NOT NULL, symbol TEXT, strategy TEXT, decision TEXT, reason TEXT, price DOUBLE PRECISION, metadata JSONB);
CREATE INDEX IF NOT EXISTS idx_trades_exit_symbol_strategy ON trades(exit_time DESC, symbol, strategy);
CREATE INDEX IF NOT EXISTS idx_signals_time_symbol_action ON signals(timestamp DESC, symbol, action);
CREATE INDEX IF NOT EXISTS idx_decisions_time_symbol_strategy ON decision_logs(timestamp DESC, symbol, strategy);
CREATE TABLE IF NOT EXISTS llm_tool_logs (id BIGINT PRIMARY KEY, timestamp DOUBLE PRECISION NOT NULL, scope TEXT, tool_name TEXT, arguments JSONB, result_summary TEXT, duration_ms DOUBLE PRECISION, success BOOLEAN);
CREATE TABLE IF NOT EXISTS llm_symbol_guards (symbol TEXT PRIMARY KEY, guard_type TEXT NOT NULL DEFAULT 'cooldown', status TEXT NOT NULL DEFAULT 'active', blocked_until DOUBLE PRECISION, reason TEXT, evidence JSONB, revision INTEGER NOT NULL DEFAULT 1, created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS virtual_wallet (asset TEXT PRIMARY KEY, amount DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS chart_settings (symbol TEXT PRIMARY KEY, data JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS llm_providers (id BIGINT PRIMARY KEY, name TEXT NOT NULL, base_url TEXT NOT NULL, api_key_encrypted TEXT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE, created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS llm_models (id BIGINT PRIMARY KEY, provider_id BIGINT NOT NULL, name TEXT NOT NULL, temperature DOUBLE PRECISION NOT NULL DEFAULT 0.2, model_type TEXT NOT NULL DEFAULT 'chat', dimensions INTEGER, embedding_metric TEXT NOT NULL DEFAULT 'cosine', enabled BOOLEAN NOT NULL DEFAULT TRUE, created_at DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS llm_skills (id BIGINT PRIMARY KEY, name TEXT NOT NULL, instructions TEXT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE, created_at DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS llm_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS backtests (id BIGINT PRIMARY KEY, timestamp DOUBLE PRECISION, symbol TEXT, interval TEXT, strategy TEXT, params JSONB, days_back INTEGER, initial_balance DOUBLE PRECISION, final_balance DOUBLE PRECISION, net_pnl DOUBLE PRECISION, net_pnl_pct DOUBLE PRECISION, total_trades INTEGER, wins INTEGER, losses INTEGER, win_rate DOUBLE PRECISION, order_size DOUBLE PRECISION, stop_loss_pct DOUBLE PRECISION, take_profit_pct DOUBLE PRECISION, trailing_stop_pct DOUBLE PRECISION, trades JSONB, max_drawdown_pct DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS analysis_snapshots (id BIGSERIAL PRIMARY KEY, symbol TEXT NOT NULL, timeframe TEXT NOT NULL, captured_at DOUBLE PRECISION NOT NULL, source TEXT NOT NULL DEFAULT 'entry', methodology_version TEXT, regime TEXT, regime_confidence DOUBLE PRECISION, confluence_score DOUBLE PRECISION, payload JSONB NOT NULL DEFAULT '{}'::jsonb, trade_id TEXT);
CREATE INDEX IF NOT EXISTS idx_analysis_snapshots_symbol_time ON analysis_snapshots(symbol, captured_at DESC);
CREATE TABLE IF NOT EXISTS llm_forecasts (
  forecast_id TEXT PRIMARY KEY, forecast_group_id TEXT NOT NULL,
  symbol TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL, horizon_minutes INTEGER NOT NULL,
  entry_price DOUBLE PRECISION NOT NULL, direction TEXT NOT NULL, confidence DOUBLE PRECISION NOT NULL,
  invalidation_price DOUBLE PRECISION, min_move_pct DOUBLE PRECISION NOT NULL,
  regime TEXT, timeframe_context JSONB NOT NULL DEFAULT '{}'::jsonb,
  scenario TEXT NOT NULL, counter_scenario TEXT, summary TEXT,
  model TEXT, prompt_version TEXT NOT NULL, snapshot_hash TEXT NOT NULL,
  snapshot JSONB NOT NULL DEFAULT '{}'::jsonb, status TEXT NOT NULL DEFAULT 'pending',
  evaluated_at DOUBLE PRECISION, outcome_price DOUBLE PRECISION, outcome_return_pct DOUBLE PRECISION,
  outcome_direction TEXT, direction_correct BOOLEAN, max_favorable_pct DOUBLE PRECISION,
  max_adverse_pct DOUBLE PRECISION, outcome_details JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_llm_forecasts_due ON llm_forecasts(status, created_at, horizon_minutes);
CREATE INDEX IF NOT EXISTS idx_llm_forecasts_symbol_time ON llm_forecasts(symbol, created_at DESC);
CREATE TABLE IF NOT EXISTS llm_forecast_lessons (
  lesson_key TEXT PRIMARY KEY, symbol TEXT, horizon_minutes INTEGER NOT NULL,
  regime TEXT, direction TEXT, sample_size INTEGER NOT NULL,
  in_sample_accuracy DOUBLE PRECISION, holdout_accuracy DOUBLE PRECISION, confidence_calibration_error DOUBLE PRECISION,
  lesson TEXT NOT NULL, evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'candidate', generated_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_forecast_lessons_lookup ON llm_forecast_lessons(status, symbol, horizon_minutes);
CREATE TABLE IF NOT EXISTS chat_predictions (
  prediction_id TEXT PRIMARY KEY, forecast_group_id TEXT NOT NULL,
  symbol TEXT NOT NULL, horizon_minutes INTEGER NOT NULL, created_at DOUBLE PRECISION NOT NULL,
  entry_price DOUBLE PRECISION NOT NULL, direction TEXT NOT NULL, confidence DOUBLE PRECISION NOT NULL,
  score DOUBLE PRECISION, min_move_pct DOUBLE PRECISION NOT NULL, regime TEXT,
  evidence JSONB NOT NULL DEFAULT '[]'::jsonb, risks JSONB NOT NULL DEFAULT '[]'::jsonb,
  snapshot JSONB NOT NULL DEFAULT '{}'::jsonb, snapshot_hash TEXT NOT NULL,
  model TEXT, prompt_version TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  evaluated_at DOUBLE PRECISION, outcome_price DOUBLE PRECISION, outcome_return_pct DOUBLE PRECISION,
  outcome_direction TEXT, direction_correct BOOLEAN, max_favorable_pct DOUBLE PRECISION,
  max_adverse_pct DOUBLE PRECISION, outcome_details JSONB NOT NULL DEFAULT '{}'::jsonb,
  analysis_status TEXT NOT NULL DEFAULT 'pending', analysis TEXT,
  analysis_factors JSONB NOT NULL DEFAULT '{}'::jsonb, analysis_model TEXT, analysis_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_chat_predictions_due ON chat_predictions(status, created_at, horizon_minutes);
CREATE INDEX IF NOT EXISTS idx_chat_predictions_symbol_time ON chat_predictions(symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_predictions_analysis ON chat_predictions(status, analysis_status);
CREATE TABLE IF NOT EXISTS chat_prediction_insights (
  insight_key TEXT PRIMARY KEY, scope TEXT NOT NULL, symbol TEXT, horizon_minutes INTEGER,
  sample_size INTEGER NOT NULL, success_count INTEGER NOT NULL DEFAULT 0, failure_count INTEGER NOT NULL DEFAULT 0,
  insight TEXT NOT NULL, factors JSONB NOT NULL DEFAULT '{}'::jsonb, source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  status TEXT NOT NULL DEFAULT 'active', generated_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_prediction_insights_lookup ON chat_prediction_insights(status, symbol, horizon_minutes);
CREATE TABLE IF NOT EXISTS velocity_candidates (
  candidate_id TEXT PRIMARY KEY, created_at DOUBLE PRECISION NOT NULL,
  symbol TEXT NOT NULL, price DOUBLE PRECISION NOT NULL, target_pct DOUBLE PRECISION NOT NULL,
  ml_target_pct DOUBLE PRECISION, ml_hit_probability DOUBLE PRECISION,
  atr_pct DOUBLE PRECISION NOT NULL, volume_ratio DOUBLE PRECISION NOT NULL, ret3_pct DOUBLE PRECISION NOT NULL,
  velocity_score DOUBLE PRECISION NOT NULL, passes BOOLEAN NOT NULL,
  rank INTEGER, status TEXT NOT NULL DEFAULT 'pending',
  evaluated_at DOUBLE PRECISION, mfe_pct DOUBLE PRECISION, touched_target BOOLEAN,
  outcome_details JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_velocity_candidates_due ON velocity_candidates(status, created_at);
CREATE INDEX IF NOT EXISTS idx_velocity_candidates_symbol ON velocity_candidates(symbol, created_at DESC);

-- Mevcut (pre-ML) tabloyu da idempotent sekilde ML hedef sutunlarina tasi.
ALTER TABLE velocity_candidates ADD COLUMN IF NOT EXISTS ml_target_pct DOUBLE PRECISION;
ALTER TABLE velocity_candidates ADD COLUMN IF NOT EXISTS ml_hit_probability DOUBLE PRECISION;

-- Sembol bazlı adaptif hedef öğrenme (2026-09-03): Her sembol için başarı/başarısız
-- sayısı tutulur, hedef otomatik ayarlanır. ML tahmin + adaptif durum harmanlanır.
CREATE TABLE IF NOT EXISTS symbol_target_state (
  symbol TEXT PRIMARY KEY,
  target_pct DOUBLE PRECISION NOT NULL DEFAULT 2.0,
  horizon_minutes INTEGER NOT NULL DEFAULT 5,
  success_count INTEGER NOT NULL DEFAULT 0,
  fail_count INTEGER NOT NULL DEFAULT 0,
  total_count INTEGER NOT NULL DEFAULT 0,
  last_adjusted_at DOUBLE PRECISION NOT NULL DEFAULT 0,
  created_at DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS microstructure_snapshots (id BIGSERIAL PRIMARY KEY, symbol TEXT NOT NULL, captured_at DOUBLE PRECISION NOT NULL, bid_price DOUBLE PRECISION, ask_price DOUBLE PRECISION, bid_qty DOUBLE PRECISION, ask_qty DOUBLE PRECISION, spread_pct DOUBLE PRECISION, depth_try DOUBLE PRECISION, orderflow_imbalance DOUBLE PRECISION, source TEXT NOT NULL DEFAULT 'binance_tr_public_ws', updated_at DOUBLE PRECISION, UNIQUE(symbol, captured_at));
CREATE INDEX IF NOT EXISTS microstructure_snapshots_lookup_idx ON microstructure_snapshots(symbol, captured_at DESC);
CREATE INDEX IF NOT EXISTS microstructure_snapshots_captured_idx ON microstructure_snapshots(captured_at);

CREATE TABLE IF NOT EXISTS ml_model_artifacts (
  id BIGSERIAL PRIMARY KEY,
  created_at DOUBLE PRECISION NOT NULL,
  horizons JSONB NOT NULL,
  sample_count BIGINT NOT NULL,
  journal_sample_count BIGINT NOT NULL DEFAULT 0,
  symbol_count INTEGER NOT NULL,
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  artifact_path TEXT NOT NULL,
  feature_version TEXT NOT NULL DEFAULT 'v1',
  status TEXT NOT NULL DEFAULT 'ready'
);
CREATE INDEX IF NOT EXISTS ml_model_artifacts_created_idx ON ml_model_artifacts(created_at DESC);

CREATE TABLE IF NOT EXISTS historical_candles (
  symbol TEXT NOT NULL, timeframe TEXT NOT NULL, open_time BIGINT NOT NULL,
  close_time BIGINT NOT NULL, open DOUBLE PRECISION NOT NULL, high DOUBLE PRECISION NOT NULL,
  low DOUBLE PRECISION NOT NULL, close DOUBLE PRECISION NOT NULL, volume DOUBLE PRECISION NOT NULL,
  quote_volume DOUBLE PRECISION, trade_count INTEGER, source TEXT NOT NULL DEFAULT 'binance_tr_public',
  fetched_at DOUBLE PRECISION NOT NULL, PRIMARY KEY(symbol, timeframe, open_time)
);
CREATE INDEX IF NOT EXISTS historical_candles_lookup_idx ON historical_candles(symbol, timeframe, open_time);
CREATE TABLE IF NOT EXISTS historical_feature_snapshots (
  symbol TEXT NOT NULL, timeframe TEXT NOT NULL, open_time BIGINT NOT NULL,
  captured_at BIGINT NOT NULL, feature_version TEXT NOT NULL, payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  regime TEXT, regime_confidence DOUBLE PRECISION, confluence_score DOUBLE PRECISION,
  data_ready BOOLEAN NOT NULL DEFAULT FALSE, PRIMARY KEY(symbol, timeframe, open_time, feature_version)
);
CREATE INDEX IF NOT EXISTS historical_features_lookup_idx ON historical_feature_snapshots(symbol, timeframe, open_time);

DO $$
DECLARE table_name TEXT; seq_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['trades','signals','decision_logs','llm_tool_logs','llm_providers','llm_models','llm_skills','backtests'] LOOP
    seq_name := table_name || '_id_seq';
    EXECUTE format('CREATE SEQUENCE IF NOT EXISTS %I', seq_name);
    EXECUTE format('ALTER TABLE %I ALTER COLUMN id SET DEFAULT nextval(%L)', table_name, seq_name);
    EXECUTE format('SELECT setval(%L, COALESCE((SELECT MAX(id) FROM %I), 1), (SELECT COUNT(*) > 0 FROM %I))', seq_name, table_name, table_name);
  END LOOP;
END $$;

CREATE TABLE IF NOT EXISTS memory_documents (
  id BIGSERIAL PRIMARY KEY,
  layer TEXT NOT NULL CHECK (layer IN ('session','symbol','strategy','trade','system','user')),
  scope TEXT NOT NULL,
  symbol TEXT, strategy TEXT, timeframe TEXT,
  source_type TEXT NOT NULL, source_id TEXT,
  content TEXT NOT NULL, metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  observed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  embedding_model_id BIGINT, embedding_dimensions INTEGER,
  embedding_status TEXT NOT NULL DEFAULT 'pending',
  content_hash TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS memory_documents_hash_idx ON memory_documents(content_hash, embedding_model_id);
CREATE INDEX IF NOT EXISTS memory_documents_scope_idx ON memory_documents(layer, symbol, strategy, timeframe, observed_at DESC);
CREATE INDEX IF NOT EXISTS memory_documents_metadata_idx ON memory_documents USING GIN(metadata);
ALTER TABLE memory_documents ADD COLUMN IF NOT EXISTS search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(content,'') || ' ' || coalesce(symbol,'') || ' ' || coalesce(strategy,''))) STORED;
CREATE INDEX IF NOT EXISTS memory_documents_search_idx ON memory_documents USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS memory_documents_filter_idx ON memory_documents(layer, symbol, strategy, timeframe, observed_at DESC);

-- Embeddings are dimension-specific by design. The first active embedding model
-- creates the vector(D) table for its declared dimension; another dimension must
-- be migrated explicitly instead of silently mixing incompatible vectors.
CREATE TABLE IF NOT EXISTS memory_embeddings (
  memory_document_id BIGINT PRIMARY KEY REFERENCES memory_documents(id) ON DELETE CASCADE,
  model_id BIGINT NOT NULL,
  dimensions INTEGER NOT NULL,
  embedding halfvec(2048),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='memory_embeddings' AND column_name='embedding') THEN
    BEGIN
      ALTER TABLE memory_embeddings ALTER COLUMN embedding TYPE halfvec(2048) USING embedding::halfvec(2048);
    EXCEPTION WHEN others THEN
      NULL;
    END;
  END IF;
END $$;
-- HNSW index is intentionally created after the first embedding model is
-- configured. Creating it during the base migration can block on an existing
-- PostgreSQL relation and is unnecessary while the table has no embeddings.
-- Keep large HNSW builds out of startup migrations. Create this index in a
-- controlled maintenance job after the first embedding backfill:
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS memory_embeddings_hnsw_idx
--   ON memory_embeddings USING hnsw (embedding halfvec_cosine_ops);

CREATE TABLE IF NOT EXISTS memory_retrieval_logs (
  id BIGSERIAL PRIMARY KEY,
  query_scope TEXT, query_text_hash TEXT, filters JSONB NOT NULL DEFAULT '{}'::jsonb,
  model_id BIGINT, result_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  latency_ms DOUBLE PRECISION, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_messages (
  id BIGSERIAL PRIMARY KEY, session_id TEXT NOT NULL, sequence_no INTEGER NOT NULL,
  role TEXT NOT NULL, content TEXT NOT NULL, symbol TEXT, strategy TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), embedded_at TIMESTAMPTZ,
  UNIQUE(session_id, sequence_no)
);
CREATE INDEX IF NOT EXISTS chat_messages_session_idx ON chat_messages(session_id, sequence_no);

CREATE TABLE IF NOT EXISTS embedding_jobs (
  id BIGSERIAL PRIMARY KEY, document JSONB NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0, available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_error TEXT, locked_at TIMESTAMPTZ, completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS embedding_jobs_ready_idx ON embedding_jobs(status, available_at);

CREATE TABLE IF NOT EXISTS agent_traces (
  id BIGSERIAL PRIMARY KEY, trace_id TEXT NOT NULL UNIQUE, parent_trace_id TEXT,
  session_id TEXT, intent TEXT, status TEXT NOT NULL DEFAULT 'running',
  model_id BIGINT, prompt_version TEXT, memory_snapshot_id TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS agent_traces_session_idx ON agent_traces(session_id, started_at DESC);
CREATE INDEX IF NOT EXISTS agent_traces_status_idx ON agent_traces(status, started_at DESC);

CREATE TABLE IF NOT EXISTS agent_trace_events (
  id BIGSERIAL PRIMARY KEY, trace_id TEXT NOT NULL REFERENCES agent_traces(trace_id) ON DELETE CASCADE,
  sequence_no INTEGER NOT NULL, event_type TEXT NOT NULL, tool_name TEXT,
  input_json JSONB, output_json JSONB, latency_ms DOUBLE PRECISION,
  success BOOLEAN, error_code TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(trace_id, sequence_no)
);
CREATE INDEX IF NOT EXISTS agent_trace_events_trace_idx ON agent_trace_events(trace_id, sequence_no);

CREATE TABLE IF NOT EXISTS agent_experiences (
  id BIGSERIAL PRIMARY KEY, trace_id TEXT REFERENCES agent_traces(trace_id) ON DELETE SET NULL,
  experience_type TEXT NOT NULL, symbol TEXT, strategy TEXT, timeframe TEXT,
  trigger TEXT, action TEXT, outcome TEXT, lesson TEXT, evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  confidence DOUBLE PRECISION NOT NULL DEFAULT 0.3, status TEXT NOT NULL DEFAULT 'candidate',
  observed_at TIMESTAMPTZ NOT NULL DEFAULT now(), validated_at TIMESTAMPTZ,
  content_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS agent_experiences_filter_idx ON agent_experiences(experience_type, symbol, strategy, status, confidence DESC);

CREATE TABLE IF NOT EXISTS trading_instincts (
  id BIGSERIAL PRIMARY KEY, instinct_key TEXT NOT NULL UNIQUE, scope TEXT NOT NULL DEFAULT 'strategy',
  symbol TEXT, strategy TEXT, domain TEXT NOT NULL, trigger TEXT NOT NULL, action TEXT NOT NULL,
  confidence DOUBLE PRECISION NOT NULL DEFAULT 0.3, evidence_count INTEGER NOT NULL DEFAULT 0,
  contradiction_count INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'candidate',
  source_experience_ids JSONB NOT NULL DEFAULT '[]'::jsonb, metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  approved_at TIMESTAMPTZ, deprecated_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS trading_instincts_active_idx ON trading_instincts(status, scope, symbol, strategy, confidence DESC);
CREATE TABLE IF NOT EXISTS memory_relations (
  source_id BIGINT NOT NULL REFERENCES memory_documents(id) ON DELETE CASCADE,
  target_id BIGINT NOT NULL REFERENCES memory_documents(id) ON DELETE CASCADE,
  relation_type TEXT NOT NULL CHECK (relation_type IN ('supports','contradicts','supersedes')),
  confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(source_id,target_id,relation_type)
);
CREATE INDEX IF NOT EXISTS memory_relations_target_idx ON memory_relations(target_id, relation_type);

CREATE TABLE IF NOT EXISTS agent_evaluations (
  id BIGSERIAL PRIMARY KEY, trace_id TEXT REFERENCES agent_traces(trace_id) ON DELETE SET NULL,
  evaluator_type TEXT NOT NULL, score DOUBLE PRECISION, passed BOOLEAN NOT NULL,
  rubric JSONB NOT NULL DEFAULT '{}'::jsonb, failure_category TEXT, explanation TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_evaluations_trace_idx ON agent_evaluations(trace_id, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_eval_cases (
  id BIGSERIAL PRIMARY KEY, case_key TEXT NOT NULL UNIQUE, category TEXT NOT NULL,
  input JSONB NOT NULL, expected JSONB NOT NULL DEFAULT '{}'::jsonb,
  enabled BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS agent_eval_runs (
  id BIGSERIAL PRIMARY KEY, case_id BIGINT REFERENCES agent_eval_cases(id) ON DELETE CASCADE,
  trace_id TEXT, attempt_no INTEGER NOT NULL DEFAULT 1, passed BOOLEAN NOT NULL,
  score DOUBLE PRECISION, details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_eval_runs_case_idx ON agent_eval_runs(case_id, created_at DESC);

CREATE TABLE IF NOT EXISTS paper_orders (
  order_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, side TEXT NOT NULL,
  order_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN',
  order_value_try DOUBLE PRECISION, price DOUBLE PRECISION, limit_price DOUBLE PRECISION,
  stop_price DOUBLE PRECISION, take_profit_price DOUBLE PRECISION,
  stop_loss_pct DOUBLE PRECISION, take_profit_pct DOUBLE PRECISION,
  max_hold_seconds INTEGER, oco_group TEXT, reference_price DOUBLE PRECISION,
  client_request_id TEXT UNIQUE, trace_id TEXT, payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  filled_at TIMESTAMPTZ, cancelled_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS paper_orders_symbol_status_idx ON paper_orders(symbol, status, created_at DESC);
CREATE INDEX IF NOT EXISTS paper_orders_oco_idx ON paper_orders(oco_group) WHERE oco_group IS NOT NULL;

CREATE TABLE IF NOT EXISTS alert_rules (
  id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL DEFAULT '5m', rule_type TEXT NOT NULL DEFAULT 'price',
  operator TEXT NOT NULL, threshold DOUBLE PRECISION NOT NULL,
  cooldown_seconds INTEGER NOT NULL DEFAULT 1800, enabled BOOLEAN NOT NULL DEFAULT TRUE,
  armed BOOLEAN NOT NULL DEFAULT TRUE,
  last_triggered_at TIMESTAMPTZ, last_value DOUBLE PRECISION, rearm_threshold DOUBLE PRECISION,
  expires_at TIMESTAMPTZ, notify_channels JSONB NOT NULL DEFAULT '["websocket"]'::jsonb,
  created_by TEXT NOT NULL DEFAULT 'user', reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE alert_rules ADD COLUMN IF NOT EXISTS armed BOOLEAN NOT NULL DEFAULT TRUE;
CREATE INDEX IF NOT EXISTS alert_rules_active_idx ON alert_rules(enabled, symbol);
CREATE TABLE IF NOT EXISTS alert_events (
  id BIGSERIAL PRIMARY KEY, rule_id BIGINT NOT NULL REFERENCES alert_rules(id) ON DELETE CASCADE,
  symbol TEXT NOT NULL, event_key TEXT NOT NULL UNIQUE, value DOUBLE PRECISION,
  message TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'info',
  triggered_at TIMESTAMPTZ NOT NULL DEFAULT now(), acknowledged_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS alert_events_recent_idx ON alert_events(triggered_at DESC);
CREATE TABLE IF NOT EXISTS notification_channels (
  id BIGSERIAL PRIMARY KEY, channel_type TEXT NOT NULL, destination TEXT NOT NULL,
  secret_ref TEXT, enabled BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(channel_type, destination)
);
CREATE TABLE IF NOT EXISTS push_subscriptions (
  id BIGSERIAL PRIMARY KEY, endpoint TEXT NOT NULL UNIQUE, subscription JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Paper-only pattern research registry. Research evidence is separate from
-- live strategy configuration so an LLM cannot promote a candidate by merely
-- writing a strategy setting.
CREATE TABLE IF NOT EXISTS research_runs (
  id BIGSERIAL PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  run_type TEXT NOT NULL, scope TEXT NOT NULL DEFAULT 'active',
  symbols JSONB NOT NULL DEFAULT '[]'::jsonb, timeframes JSONB NOT NULL DEFAULT '[]'::jsonb,
  parameters JSONB NOT NULL DEFAULT '{}'::jsonb, result JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'completed', paper_only BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS research_runs_recent_idx ON research_runs(created_at DESC, run_type);
CREATE TABLE IF NOT EXISTS research_patterns (
  id BIGSERIAL PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  name TEXT NOT NULL, description TEXT, symbols_scope TEXT NOT NULL DEFAULT 'active',
  symbols JSONB NOT NULL DEFAULT '[]'::jsonb, timeframes JSONB NOT NULL DEFAULT '[]'::jsonb,
  definition JSONB NOT NULL DEFAULT '{}'::jsonb, evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'candidate', confidence DOUBLE PRECISION NOT NULL DEFAULT 0.3, source_run_id BIGINT
);
CREATE INDEX IF NOT EXISTS research_patterns_status_idx ON research_patterns(status, updated_at DESC);

-- Users & roles for username+password auth (2026-09-03). Username is stored
-- lowercased (admin/ADMIN accepted case-insensitively); passwords are PBKDF2
-- hashed, never plaintext.
CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'user',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS users_username_idx ON users(username);

-- Chart-page ML price forecasts (2026-09-03). Model-only (no LLM); measured
-- from closed M1 candles when the horizon elapses; evaluated rows feed the ML
-- training journal.
CREATE TABLE IF NOT EXISTS chart_forecasts (
  id BIGSERIAL PRIMARY KEY,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  horizon_minutes INTEGER NOT NULL,
  entry_price DOUBLE PRECISION NOT NULL,
  target_pct DOUBLE PRECISION NOT NULL,
  target_price DOUBLE PRECISION,
  hit_probability DOUBLE PRECISION,
  model TEXT,
  created_at DOUBLE PRECISION NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  evaluated_at DOUBLE PRECISION,
  outcome_price DOUBLE PRECISION,
  outcome_return_pct DOUBLE PRECISION,
  outcome_direction TEXT,
  direction_correct BOOLEAN,
  max_favorable_pct DOUBLE PRECISION,
  max_adverse_pct DOUBLE PRECISION,
  outcome_details JSONB
);
CREATE INDEX IF NOT EXISTS chart_forecasts_symbol_time_idx ON chart_forecasts(symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS chart_forecasts_status_created_idx ON chart_forecasts(status, created_at);

-- Monitoring page notification history (2026-09-03). The server-side scan
-- loop persists every delivered (or quiet-hours deferred) candidate
-- notification so history survives restarts and is visible even when the
-- PWA is closed. Follows the paper-only double precision epoch convention.
CREATE TABLE IF NOT EXISTS monitoring_notifications (
  id BIGSERIAL PRIMARY KEY,
  symbol TEXT NOT NULL,
  message TEXT NOT NULL,
  title TEXT,
  score DOUBLE PRECISION,
  target_pct DOUBLE PRECISION,
  price DOUBLE PRECISION,
  expected_price DOUBLE PRECISION,
  horizon_minutes INTEGER,
  mode TEXT,
  detected_at DOUBLE PRECISION NOT NULL,
  sent_via_push BOOLEAN NOT NULL DEFAULT FALSE,
  created_at DOUBLE PRECISION NOT NULL,
  ml_target_pct DOUBLE PRECISION,
  ml_hit_probability DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS monitoring_notifications_detected_idx ON monitoring_notifications(detected_at DESC);
CREATE INDEX IF NOT EXISTS monitoring_notifications_symbol_idx ON monitoring_notifications(symbol, detected_at DESC);

-- Mevcut (pre-ML) tabloyu da idempotent sekilde ML hedef sutunlarina tasi.
ALTER TABLE monitoring_notifications ADD COLUMN IF NOT EXISTS ml_target_pct DOUBLE PRECISION;
ALTER TABLE monitoring_notifications ADD COLUMN IF NOT EXISTS ml_hit_probability DOUBLE PRECISION;

-- Audit trail for user-triggered actions (2026-09-03). Records who did what
-- and when (login/logout, password changes, config saves, manual trade
-- closes, alert changes, monitoring resets) together with the caller's IP
-- and device fingerprint. Autonomous bot loops are NOT logged here — they
-- already persist in decision_logs/trades/monitoring_notifications. Never
-- cleared by reset_trading_data; an admin-only DELETE prunes history.
CREATE TABLE IF NOT EXISTS audit_logs (
  id BIGSERIAL PRIMARY KEY,
  actor_username TEXT,
  actor_role TEXT,
  category TEXT NOT NULL,
  action TEXT NOT NULL,
  target TEXT,
  details JSONB,
  ip TEXT,
  user_agent TEXT,
  accept_language TEXT,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_logs_created_idx ON audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS audit_logs_actor_idx ON audit_logs(actor_username, created_at DESC);
CREATE INDEX IF NOT EXISTS audit_logs_category_idx ON audit_logs(category, created_at DESC);

-- Otonom paper trade (monitoring bildiriminden tetiklenen, 2026-09-04).
-- Ana positions/trades tablosundan bagimsiz; yalnizca bildirim -> pozisyon akisini kaydeder.
CREATE TABLE IF NOT EXISTS auto_paper_trades (
  id BIGSERIAL PRIMARY KEY,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL DEFAULT 'LONG',
  status TEXT NOT NULL DEFAULT 'open',
  notification_id BIGINT,
  entry_price DOUBLE PRECISION NOT NULL,
  quantity DOUBLE PRECISION NOT NULL,
  order_value_try DOUBLE PRECISION NOT NULL,
  stop_loss DOUBLE PRECISION,
  take_profit DOUBLE PRECISION,
  peak_price DOUBLE PRECISION,
  entry_time DOUBLE PRECISION NOT NULL,
  exit_price DOUBLE PRECISION,
  exit_time DOUBLE PRECISION,
  pnl DOUBLE PRECISION,
  pnl_pct DOUBLE PRECISION,
  commission DOUBLE PRECISION,
  exit_reason TEXT,
  breakeven_activated BOOLEAN NOT NULL DEFAULT FALSE,
  breakeven_stop DOUBLE PRECISION,
  notification_score DOUBLE PRECISION,
  notification_target_pct DOUBLE PRECISION,
  notification_expected_price DOUBLE PRECISION,
  last_checked_at DOUBLE PRECISION,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS auto_paper_trades_status_idx ON auto_paper_trades(status, entry_time DESC);
CREATE INDEX IF NOT EXISTS auto_paper_trades_symbol_status_idx ON auto_paper_trades(symbol, status);
-- Sembol başına tek açık pozisyon garantisi (aynı anda yalnız bir 'open' olabilir).
-- Mevcut veride ihlal varsa oluşturulamaz; temizlik sonrası uygulanır.
CREATE UNIQUE INDEX IF NOT EXISTS auto_paper_trades_one_open_per_symbol
  ON auto_paper_trades(symbol) WHERE status='open';
