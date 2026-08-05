CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS migration_meta (
  version TEXT PRIMARY KEY,
  source_path TEXT,
  source_sha256 TEXT,
  source_counts JSONB,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS positions (symbol TEXT PRIMARY KEY, side TEXT, entry_price DOUBLE PRECISION, stop_price DOUBLE PRECISION, take_profit DOUBLE PRECISION, peak_price DOUBLE PRECISION, breakeven_hit BOOLEAN, quantity DOUBLE PRECISION, entry_time DOUBLE PRECISION, strategy TEXT, entry_context JSONB);
CREATE TABLE IF NOT EXISTS trades (id BIGINT PRIMARY KEY, symbol TEXT, strategy TEXT, side TEXT, entry_price DOUBLE PRECISION, exit_price DOUBLE PRECISION, quantity DOUBLE PRECISION, pnl DOUBLE PRECISION, pnl_pct DOUBLE PRECISION, entry_time DOUBLE PRECISION, exit_time DOUBLE PRECISION, commission DOUBLE PRECISION, reason TEXT, entry_context JSONB, max_favorable_pct DOUBLE PRECISION, max_adverse_pct DOUBLE PRECISION, hold_seconds DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS signals (id BIGINT PRIMARY KEY, timestamp DOUBLE PRECISION, symbol TEXT, action TEXT, price DOUBLE PRECISION, reason TEXT);
CREATE TABLE IF NOT EXISTS decision_logs (id BIGINT PRIMARY KEY, timestamp DOUBLE PRECISION NOT NULL, symbol TEXT, strategy TEXT, decision TEXT, reason TEXT, price DOUBLE PRECISION, metadata JSONB);
CREATE TABLE IF NOT EXISTS llm_tool_logs (id BIGINT PRIMARY KEY, timestamp DOUBLE PRECISION NOT NULL, scope TEXT, tool_name TEXT, arguments JSONB, result_summary TEXT, duration_ms DOUBLE PRECISION, success BOOLEAN);
CREATE TABLE IF NOT EXISTS virtual_wallet (asset TEXT PRIMARY KEY, amount DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS chart_settings (symbol TEXT PRIMARY KEY, data JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS llm_providers (id BIGINT PRIMARY KEY, name TEXT NOT NULL, base_url TEXT NOT NULL, api_key_encrypted TEXT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE, created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS llm_models (id BIGINT PRIMARY KEY, provider_id BIGINT NOT NULL, name TEXT NOT NULL, temperature DOUBLE PRECISION NOT NULL DEFAULT 0.2, model_type TEXT NOT NULL DEFAULT 'chat', dimensions INTEGER, embedding_metric TEXT NOT NULL DEFAULT 'cosine', enabled BOOLEAN NOT NULL DEFAULT TRUE, created_at DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS llm_skills (id BIGINT PRIMARY KEY, name TEXT NOT NULL, instructions TEXT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE, created_at DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS llm_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS backtests (id BIGINT PRIMARY KEY, timestamp DOUBLE PRECISION, symbol TEXT, interval TEXT, strategy TEXT, params JSONB, days_back INTEGER, initial_balance DOUBLE PRECISION, final_balance DOUBLE PRECISION, net_pnl DOUBLE PRECISION, net_pnl_pct DOUBLE PRECISION, total_trades INTEGER, wins INTEGER, losses INTEGER, win_rate DOUBLE PRECISION, order_size DOUBLE PRECISION, stop_loss_pct DOUBLE PRECISION, take_profit_pct DOUBLE PRECISION, trailing_stop_pct DOUBLE PRECISION, trades JSONB, max_drawdown_pct DOUBLE PRECISION);

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
CREATE INDEX IF NOT EXISTS memory_embeddings_hnsw_idx ON memory_embeddings USING hnsw (embedding halfvec_cosine_ops);

CREATE TABLE IF NOT EXISTS memory_retrieval_logs (
  id BIGSERIAL PRIMARY KEY,
  query_scope TEXT, query_text_hash TEXT, filters JSONB NOT NULL DEFAULT '{}'::jsonb,
  model_id BIGINT, result_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  latency_ms DOUBLE PRECISION, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
