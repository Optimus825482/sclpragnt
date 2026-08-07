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
CREATE TABLE IF NOT EXISTS signals (id BIGINT PRIMARY KEY, timestamp DOUBLE PRECISION, symbol TEXT, action TEXT, price DOUBLE PRECISION, reason TEXT);
CREATE TABLE IF NOT EXISTS decision_logs (id BIGINT PRIMARY KEY, timestamp DOUBLE PRECISION NOT NULL, symbol TEXT, strategy TEXT, decision TEXT, reason TEXT, price DOUBLE PRECISION, metadata JSONB);
CREATE TABLE IF NOT EXISTS llm_tool_logs (id BIGINT PRIMARY KEY, timestamp DOUBLE PRECISION NOT NULL, scope TEXT, tool_name TEXT, arguments JSONB, result_summary TEXT, duration_ms DOUBLE PRECISION, success BOOLEAN);
CREATE TABLE IF NOT EXISTS a2a_messages (message_id TEXT PRIMARY KEY, correlation_id TEXT, direction TEXT NOT NULL, message_type TEXT NOT NULL, sender TEXT, recipient TEXT, status TEXT NOT NULL DEFAULT 'queued', payload JSONB NOT NULL, created_at DOUBLE PRECISION NOT NULL, delivered_at DOUBLE PRECISION, acknowledged_at DOUBLE PRECISION, last_error TEXT, attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS virtual_wallet (asset TEXT PRIMARY KEY, amount DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS chart_settings (symbol TEXT PRIMARY KEY, data JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS llm_providers (id BIGINT PRIMARY KEY, name TEXT NOT NULL, base_url TEXT NOT NULL, api_key_encrypted TEXT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE, created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS llm_models (id BIGINT PRIMARY KEY, provider_id BIGINT NOT NULL, name TEXT NOT NULL, temperature DOUBLE PRECISION NOT NULL DEFAULT 0.2, model_type TEXT NOT NULL DEFAULT 'chat', dimensions INTEGER, embedding_metric TEXT NOT NULL DEFAULT 'cosine', enabled BOOLEAN NOT NULL DEFAULT TRUE, created_at DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS llm_skills (id BIGINT PRIMARY KEY, name TEXT NOT NULL, instructions TEXT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE, created_at DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS llm_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS backtests (id BIGINT PRIMARY KEY, timestamp DOUBLE PRECISION, symbol TEXT, interval TEXT, strategy TEXT, params JSONB, days_back INTEGER, initial_balance DOUBLE PRECISION, final_balance DOUBLE PRECISION, net_pnl DOUBLE PRECISION, net_pnl_pct DOUBLE PRECISION, total_trades INTEGER, wins INTEGER, losses INTEGER, win_rate DOUBLE PRECISION, order_size DOUBLE PRECISION, stop_loss_pct DOUBLE PRECISION, take_profit_pct DOUBLE PRECISION, trailing_stop_pct DOUBLE PRECISION, trades JSONB, max_drawdown_pct DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS analysis_snapshots (id BIGSERIAL PRIMARY KEY, symbol TEXT NOT NULL, timeframe TEXT NOT NULL, captured_at DOUBLE PRECISION NOT NULL, source TEXT NOT NULL DEFAULT 'entry', methodology_version TEXT, regime TEXT, regime_confidence DOUBLE PRECISION, confluence_score DOUBLE PRECISION, payload JSONB NOT NULL DEFAULT '{}'::jsonb, trade_id TEXT);
CREATE INDEX IF NOT EXISTS idx_analysis_snapshots_symbol_time ON analysis_snapshots(symbol, captured_at DESC);

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
