// Backend yanıt tipleri — alan adları FastAPI handler'larından / canlı
// yanıtlardan birebir alındı. Yalnız kullanılan alanlar tanımlanır.

/** /api/monitoring/state → candidates[] (velocity aday sözlüğü + zengin ekler) */
export type Candidate = Record<string, unknown> & {
  symbol: string;
  price?: number | null;
  change_24h?: number | null;
  horizon_minutes?: number | null;
  target_pct?: number | null;
  ceiling_pct?: number | null;
  ceiling_price?: number | null;
  potential_pct?: number | null;
  velocity_score?: number | null;
  unified_score?: number | null;
  panel_score?: number | null;
  quality_score?: number | null;
  scan_score?: number | null;
  passes?: boolean;
  block_reason?: string | null;
  pool_source?: string | null;
  unified_sources?: string[] | null;
  strategy?: string | null;
  warm?: boolean;
  warm_reason?: string | null;
  candidate_id?: string;
};

export type MonitoringState = {
  data_ready: boolean;
  last_scan_at: number | null;
  scan_count: number;
  loop_active: boolean;
  next_scan_in_sec: number | null;
  candidates: Candidate[];
  watchlist?: Candidate[];
  warm: Array<Record<string, unknown>>;
  pulse: Array<Record<string, unknown>>;
  risk_off?: boolean;
};

/** /api/daily-rising/state → candidates[] */
export type DailyOpportunity = {
  symbol: string;
  created_at?: number | null;
  entry_price?: number | null;
  current_price?: number | null;
  change_pct?: number | null;
  ceiling_pct?: number | null;
  ceiling_price?: number | null;
  potential_pct?: number | null;
  potential_price?: number | null;
  scan_score?: number | null;
  quality_score?: number | null;
  target_probability?: number | null;
  strategy?: string | null;
  status?: string | null;
};

export type DailyRisingState = {
  paper_only: boolean;
  generated_at: number;
  source: string;
  sent_at?: number | null;
  schedule?: { list_min: number; top_n: number; last_list_sent: number | null; next_list_at: number | null } | null;
  stats?: { total?: number; hit?: number; hit_rate?: number | null; avg_mfe_pct?: number | null; pending?: number } | null;
  candidates: DailyOpportunity[];
};

/** /api/positions → positions[] */
export type Position = {
  symbol: string;
  side: string;
  strategy: string;
  entry: number;
  current: number | null;
  pnl_pct: number | null;
  pnl_try: number | null;
  quantity: number;
  entry_time?: number | null;
  stop?: number | null;
  take_profit?: number | null;
  auto_paper_id?: number | null;
  notification_score?: number | null;
  error?: string;
  price_stale?: boolean;
};

export type PositionsResponse = { positions: Position[]; auto_paper_error?: string | null };

/** /api/dashboard/summary */
export type DashboardSummary = {
  paper_only: boolean;
  signals_today: { total: number; buy_signals: number; close_signals: number };
  auto_paper_today: { trades: number; pnl: number; winning: number; losing: number };
  portfolio: {
    balance: number;
    open_positions: number;
    auto_paper_open: number;
    positions_value: number;
    auto_paper_value: number;
    total_value: number;
    basis: string;
  };
};

/** /api/portfolio/summary → metrics */
export type PortfolioSummary = {
  portfolio: Record<string, unknown>;
  metrics: { closed_trades: number; winning_trades: number; net_pnl: number; win_rate: number };
  generated_at: number;
  paper_only: boolean;
};

/** /api/trades (kapalı işlemler, sayfalı) */
export type ClosedTrade = {
  id: number;
  symbol: string;
  strategy: string;
  side: string;
  entry_price: number;
  exit_price: number | null;
  quantity: number;
  pnl: number | null;
  pnl_pct: number | null;
  entry_time: number | null;
  exit_time: number | null;
  commission: number | null;
  reason: string | null;
  max_favorable_pct?: number | null;
  max_adverse_pct?: number | null;
  hold_seconds?: number | null;
};
export type TradesResponse = { trades: ClosedTrade[]; total: number; limit: number; offset: number };

/** /api/reports/notifications (tarama/bildirim geçmişi) */
export type ScanNotification = {
  id?: number | string;
  symbol: string;
  title?: string | null;
  message?: string | null;
  score?: number | null;
  target_pct?: number | null;
  price?: number | null;
  mfe_pct?: number | null;
  net_pct?: number | null;
  status?: string | null;
  mode?: string | null;
  horizon_minutes?: number | null;
  detected_at?: number | null;
  sources?: string[] | null;
  candidate_id?: string | null;
};
export type NotificationsResponse = {
  paper_only: boolean;
  day: string;
  notifications: ScanNotification[];
  total: number;
};

/** /api/market-ticker/{symbol} */
export type MarketTicker = {
  symbol: string;
  available: boolean;
  last?: number | null;
  change_pct?: number | null;
  high?: number | null;
  low?: number | null;
  quote_volume?: number | null;
};

/** /api/market-symbols */
export type MarketSymbols = { symbols: string[]; quote_asset: string };

/** /api/binance/settings */
export type BinanceSettings = {
  configured: boolean;
  sell_enabled: boolean;
  sell_source: string;
  is_admin: boolean;
};

/** /api/binance/positions */
export type BinanceHolding = {
  asset: string;
  free: number;
  locked: number;
  total: number;
  price_try: number | null;
  value_try: number | null;
  avg_cost_try: number | null;
  pnl_try: number | null;
  pnl_pct: number | null;
  has_active_order: boolean;
};
export type BinancePositions = {
  holdings: BinanceHolding[];
  balances: Array<{ asset: string; free: string; locked: string }>;
  total_value_try: number;
};

/** /api/user/preferences + /api/monitoring/settings (global) */
export type UserPreferences = {
  app_notifications: boolean;
  sound: boolean;
  whatsapp_enabled: boolean;
  phone_masked: string;
  phone_set: boolean;
  whatsapp_available: boolean;
};

export type MonitoringSettings = {
  enabled: boolean;
  min_score: number | null;
  min_target_pct: number;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  combined_rising_enabled: boolean;
  combined_rising_top_n: number;
};

/** /api/profile */
export type Profile = {
  ok: boolean;
  user: { id: number; username: string; role: string; is_active: boolean };
  paper_only: boolean;
};

export type AuthStatus = {
  configured: boolean;
  authenticated: boolean;
  username?: string | null;
  role?: string | null;
};
