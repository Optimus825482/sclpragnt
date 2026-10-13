CREATE TABLE IF NOT EXISTS user_favorites (
  username TEXT PRIMARY KEY,
  symbols JSONB NOT NULL DEFAULT '[]'::jsonb,
  updated_at DOUBLE PRECISION NOT NULL
);
