import { API_BASE, apiRequest } from "./api";

export type ApiResult<T = Record<string, unknown>> = { ok: boolean; status: number; body: T; error: string };

/** JSON isteği: HTTP hatasını fırlatmaz; durum kodu + gövde + okunur hata metni döner (202 gibi durumlar için). */
export async function call<T = Record<string, unknown>>(
  method: "GET" | "POST" | "PUT" | "DELETE",
  path: string,
  payload?: unknown,
): Promise<ApiResult<T>> {
  try {
    const response = await apiRequest(`${API_BASE}${path}`, {
      method,
      headers: payload === undefined ? undefined : { "Content-Type": "application/json" },
      body: payload === undefined ? undefined : JSON.stringify(payload),
    });
    let body: unknown = {};
    try {
      body = await response.json();
    } catch {
      body = {};
    }
    const detail = (body as { detail?: unknown })?.detail;
    return {
      ok: response.ok,
      status: response.status,
      body: body as T,
      error: response.ok ? "" : typeof detail === "string" && detail ? detail : `İstek başarısız (${response.status})`,
    };
  } catch {
    return { ok: false, status: 0, body: {} as T, error: "Sunucuya ulaşılamadı. Bağlantını kontrol et." };
  }
}

export type RiskSettings = { max_position_pct: number; default_rr: number };

export type Plan = {
  loss_try: number;
  gain_try: number;
  sl_price: number;
  tp_price: number;
  sl_pct: number;
  rr: number;
  qty: number;
  cost_try: number;
  fee_buy_try?: number;
  break_even_price?: number;
  /** Açık kâr al yüzdesi gönderildiyse (bildirim planı) sunucunun yankısı. */
  tp_pct?: number;
};

export type TradePlanResponse = {
  ok: boolean;
  symbol: string;
  price: number;
  amount_try: number;
  free_try: number;
  cap_try: number;
  max_position_pct: number;
  mode: "auto" | "manual";
  suggestion: { sl_pct: number; rr: number; source: string; rationale: string };
  plan: Plan;
  warnings: string[];
  warning_texts: string[];
  disclaimer: string;
};

export type Holding = {
  asset: string;
  free: number;
  locked: number;
  total: number;
  price_try: number | null;
  value_try: number | null;
  avg_cost_try?: number | null;
  pnl_try?: number | null;
  pnl_pct?: number | null;
  has_active_order?: boolean;
  side?: string | null;
  volume_try?: number | null;
  active_sl_price?: number | null;
  active_tp_price?: number | null;
  active_orders?: unknown[];
};

export type OpenOrder = {
  orderId: number;
  symbol: string;
  side: string;
  type: string;
  price: string;
  stopPrice: string;
  origQty: string;
  executedQty: string;
  status: string;
  time: number;
};

export type DayTrade = {
  id: number;
  symbol: string;
  price: string;
  qty: string;
  quoteQty: string;
  time: number;
  isBuyer: boolean;
  realized_pnl_try?: number;
};
