-- İşlem günlüğü (journal): kullanıcıya özel scalping disiplin notları.
-- Her satır bağımsız bir nottur (sembol + isteğe bağlı strateji etiketi);
-- notlar append-only'dir, silme satır bazında yapılır.
CREATE TABLE IF NOT EXISTS trade_journal (
  id BIGSERIAL PRIMARY KEY,
  username TEXT NOT NULL,
  symbol TEXT NOT NULL,
  strategy_tag TEXT,
  note TEXT NOT NULL,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trade_journal_username_created
  ON trade_journal(username, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trade_journal_symbol
  ON trade_journal(username, symbol);
