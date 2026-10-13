// Backend yanıt tipleri — alan adları FastAPI handler'larından birebir okundu.
// Yalnız bu arayüzün KULLANDIĞI alanlar tanımlanır (dar tutulur).

/** /api/daily-rising/state → candidates[] */
export type Opportunity = {
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
  status?: string;
};

export type DailyRisingState = {
  paper_only: boolean;
  generated_at: number;
  source: string;
  sent_at?: number | null;
  schedule?: { list_min: number; top_n: number; last_list_sent: number | null; next_list_at: number | null } | null;
  stats?: {
    total?: number;
    hit?: number;
    hit_rate?: number | null;
    avg_mfe_pct?: number | null;
    pending?: number;
  } | null;
  candidates: Opportunity[];
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

export type PositionsResponse = {
  positions: Position[];
  auto_paper_error?: string | null;
};

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
  metrics: {
    closed_trades: number;
    winning_trades: number;
    net_pnl: number;
    win_rate: number;
  };
  generated_at: number;
  paper_only: boolean;
};

/** /api/monitoring/state (kısmi) */
export type MonitoringState = {
  data_ready: boolean;
  last_scan_at: number | null;
  scan_count: number;
  loop_active: boolean;
  next_scan_in_sec: number | null;
  candidates: Array<Record<string, unknown>>;
  warm: Array<Record<string, unknown>>;
  pulse: Array<Record<string, unknown>>;
  risk_off?: boolean;
};

/** /api/strategy/pipeline → strategies{} */
export type PipelineEntry = {
  stage: string;
  created_at?: number;
  updated_at?: number;
  evidence?: Record<string, unknown>;
  transitions?: Array<{ from: string; to: string; at: number; evidence?: Record<string, unknown> }>;
};
export type PipelineResponse = { strategies: Record<string, PipelineEntry>; paper_only: boolean };

/** /api/risk/summary */
export type RiskSummary = {
  open_positions: number;
  realized_pnl: number;
  today_pnl: number;
  commission: number;
  consecutive_losses: number;
  max_positions: number;
  scan_limit: number;
  global_gate: { halt: boolean; reason: string | null; limit_try: number | null };
  risk_flags: Record<string, boolean>;
};

/** /api/system/health (kısmi) */
export type SystemHealth = {
  status: string;
  generated_at?: string;
  market?: Record<string, unknown>;
  database?: Record<string, unknown>;
};

export type AuthStatus = {
  configured: boolean;
  authenticated: boolean;
  username?: string | null;
  role?: string | null;
};
