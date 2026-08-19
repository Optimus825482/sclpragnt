"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { API_BASE, apiRequest, fetchAllPages } from "../lib/api";
import { useLiveMessages } from "../lib/liveSocket";

const STRATEGY_LABEL: Record<string, string> = {
  EMA_VWAP_PULLBACK: "EMA + VWAP Pullback",
  BB_SQUEEZE_ORDERFLOW: "BB Squeeze + Order-Flow",
  ORDERFLOW: "Order-Flow Imbalance",
  MOMENTUM: "MTF Momentum Ranking",
  VWAP_MEAN_REVERSION: "VWAP Mean Reversion",
  KELTNER_BREAKOUT: "Keltner Breakout",
  CHOP_TREND_FILTER: "CHOP Trend Filter",
  DONCHIAN_BREAKOUT: "Donchian Breakout",
  LLM_PAPER: "LLM Paper",
  PUMP_MONITOR: "Pump Monitor · M15 + M5",
};

type Position = {
  symbol: string;
  side?: string;
  entry: number;
  current: number;
  pnl_pct: number;
  pnl_try?: number;
  value: number;
  quantity?: number;
  entry_time?: number;
  stop?: number;
  take_profit?: number;
  entry_context?: Record<string, unknown> | string | null;
  strategy?: string;
  llm_managed?: boolean;
  llm_stop_price?: number;
  llm_take_profit_price?: number;
  llm_max_hold_sec?: number;
  plan_revision?: number;
  last_plan_reason?: string;
  last_plan_updated_at?: number;
};

type Portfolio = {
  try: number;
  total_value: number;
  realized_pnl?: number;
  unrealized_pnl?: number;
  reconciliation_delta?: number;
  positions: Position[];
};

type Trade = {
  id: number;
  symbol: string;
  strategy: string;
  side?: string;
  entry_price: number;
  exit_price: number;
  quantity?: number;
  pnl: number;
  pnl_pct: number;
  commission?: number;
  reason?: string;
  entry_time?: number;
  exit_time?: number;
  hold_seconds?: number;
  max_favorable_pct?: number;
  max_adverse_pct?: number;
  trade_id?: string;
  entry_context?: Record<string, unknown> | string | null;
};

const money = (value?: number) =>
  (value ?? 0).toLocaleString("tr-TR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
const pnlTone = (value?: number) =>
  value == null || value === 0
    ? ""
    : value > 0
      ? "ui-tone-positive"
      : "ui-tone-negative";
const entrySignal = (strategy?: string, raw?: Record<string, unknown> | string | null) => {
  let context: Record<string, any> = {};
  try { context = typeof raw === "string" ? JSON.parse(raw) : (raw || {}); } catch { context = {}; }
  const signal = context.signal_context;
  if (strategy === "PUMP_MONITOR" && signal) return `${signal.signal_name || "Pump Monitor"} · skor ${signal.score ?? "—"}/4`;
  return STRATEGY_LABEL[strategy || ""] || strategy || "—";
};
const when = (value?: number) =>
  value
    ? new Date(value * 1000).toLocaleString("tr-TR", { hour12: false })
    : "—";
const duration = (trade: Trade) => {
  const seconds = Math.max(
    0,
    trade.hold_seconds ??
      (trade.exit_time && trade.entry_time
        ? trade.exit_time - trade.entry_time
        : 0),
  );
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = Math.floor(seconds % 60);
  return hours
    ? `${hours}s ${minutes}dk`
    : minutes
      ? `${minutes}dk ${rest}sn`
      : `${rest}sn`;
};
const planMinutes = (seconds?: number) =>
  seconds == null ? "—" : `${Math.round(seconds / 60)} dk`;
const asNumber = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
const normalizedEntryContext = (
  value: Trade["entry_context"],
): Record<string, unknown> => {
  if (value && typeof value === "object" && !Array.isArray(value))
    return value as Record<string, unknown>;
  if (typeof value !== "string" || !value.trim()) return {};
  try {
    const parsed: unknown = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
};
const csvNumber = (value: number | null | undefined) => value ?? "";
const positionDuration = (position: Position) =>
  duration({
    hold_seconds: position.entry_time
      ? Math.max(0, Math.floor(Date.now() / 1000) - position.entry_time)
      : 0,
  } as Trade);

function exportOpenPositionsCsv(positions: Position[]) {
  if (!positions.length) return;
  const head = [
    "Sembol", "Strateji", "Yön", "Giriş", "Anlık", "Miktar", "Giriş tutarı (TL)",
    "Anlık değer (TL)", "Gerçekleşmemiş PnL (TL)", "PnL %", "Giriş zamanı",
    "Aktif süre", "Planlanan TP", "Planlanan SL", "Giriş bağlamı (JSON)",
  ];
  const body = positions.map((position) => {
    const context = normalizedEntryContext(position.entry_context);
    const entryNotional = position.quantity == null ? null : position.entry * position.quantity;
    return [
      position.symbol, position.strategy ?? "", position.side ?? "LONG", position.entry,
      position.current, csvNumber(position.quantity), csvNumber(entryNotional), position.value,
      position.pnl_try ?? "", position.pnl_pct, when(position.entry_time), positionDuration(position),
      position.take_profit ?? "", position.stop ?? "", JSON.stringify(context),
    ];
  });
  const csv = [head, ...body]
    .map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(","))
    .join("\n");
  const anchor = document.createElement("a");
  anchor.href = URL.createObjectURL(new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" }));
  anchor.download = "acik-pozisyonlar.csv";
  anchor.click();
  URL.revokeObjectURL(anchor.href);
}

function ExportActions({ trades }: { trades: Trade[] }) {
  const exportCsv = () => {
    if (!trades.length) return;
    const head = [
      "ID",
      "Sembol",
      "Strateji",
      "Giriş",
      "Çıkış",
      "Yön",
      "Miktar",
      "Giriş tutarı (TL)",
      "Çıkış tutarı (TL)",
      "Brüt PnL (TL)",
      "Komisyon",
      "Maliyet oranı %",
      "PnL",
      "PnL %",
      "Fiyat hareketi %",
      "MFE %",
      "MAE %",
      "Neden",
      "Giriş zamanı",
      "Çıkış zamanı",
      "Aktif süre",
      "İşlem kimliği",
      "Strateji sürümü",
      "Planlanan TP %",
      "Planlanan SL %",
      "Planlanan azami süre sn",
      "Beklenen net PnL (TL)",
      "Giriş bağlamı (JSON)",
    ];
    const body = trades.map((trade: Trade) => {
      const context = normalizedEntryContext(trade.entry_context);
      const quantity = asNumber(trade.quantity);
      const entryNotional = quantity == null ? null : trade.entry_price * quantity;
      const exitNotional = quantity == null ? null : trade.exit_price * quantity;
      const grossPnl = trade.pnl + (trade.commission ?? 0);
      const priceMovePct =
        trade.entry_price > 0
          ? ((trade.exit_price - trade.entry_price) / trade.entry_price) * 100
          : null;
      const costPct =
        entryNotional && entryNotional > 0
          ? ((trade.commission ?? 0) / entryNotional) * 100
          : null;
      const plannedTakeProfitPct = asNumber(context.profit_target_pct);
      const plannedStopLossPct = asNumber(context.stop_loss_pct);
      return [
        trade.id,
        trade.symbol,
        trade.strategy,
        trade.entry_price,
        trade.exit_price,
        trade.side ?? "LONG",
        csvNumber(quantity),
        csvNumber(entryNotional),
        csvNumber(exitNotional),
        grossPnl,
        trade.commission ?? 0,
        csvNumber(costPct),
        trade.pnl,
        trade.pnl_pct,
        csvNumber(priceMovePct),
        csvNumber(trade.max_favorable_pct == null ? null : trade.max_favorable_pct * 100),
        csvNumber(trade.max_adverse_pct == null ? null : trade.max_adverse_pct * 100),
        trade.reason || "",
        when(trade.entry_time),
        when(trade.exit_time),
        duration(trade),
        trade.trade_id ?? "",
        String(context.strategy_revision ?? ""),
        csvNumber(plannedTakeProfitPct == null ? null : plannedTakeProfitPct * 100),
        csvNumber(plannedStopLossPct == null ? null : plannedStopLossPct * 100),
        csvNumber(asNumber(context.max_hold_sec)),
        csvNumber(asNumber(context.expected_net_pnl_try)),
        JSON.stringify(context),
      ];
    });
    const csv = [head, ...body]
      .map((row) =>
        row
          .map((value: unknown) => `"${String(value).replaceAll('"', '""')}"`)
          .join(","),
      )
      .join("\n");
    const anchor = document.createElement("a");
    anchor.href = URL.createObjectURL(
      new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" }),
    );
    anchor.download = "islem-gecmisi.csv";
    anchor.click();
    URL.revokeObjectURL(anchor.href);
  };

  return (
    <div className="portfolio-actions">
      <button
        onClick={exportCsv}
        className="ui-button ui-button-primary"
        disabled={!trades.length}
        title={!trades.length ? "Dışa aktarılacak işlem bulunmuyor." : undefined}
      >
        CSV DIŞA AKTAR ({trades.length})
      </button>
      <button
        onClick={() => window.print()}
        className="ui-button ui-button-secondary"
      >
        PDF / YAZDIR
      </button>
    </div>
  );
}

function LlmPlanPanel({
  positions,
  trades,
}: {
  positions: Position[];
  trades: Trade[];
}) {
  const managed = positions.filter(
    (position) => position.llm_managed || position.strategy === "LLM_PAPER",
  );
  return (
    <section className="ui-card portfolio-plan-panel">
      <div className="ui-section-header">
        <div>
          <p className="eyebrow">LLM POZİSYON PLANLARI</p>
          <p className="ui-section-description">
            Sembol bazlı karar · SL / TP / max-hold · yalnızca paper
          </p>
        </div>
        <div className="ui-section-actions">
          <ExportActions trades={trades} />
          <span className="ui-badge ui-badge-info">{managed.length} aktif</span>
        </div>
      </div>
      {managed.length === 0 ? (
        <p className="text-sm text-bunker-muted">
          Aktif LLM_PAPER pozisyonu yok.
        </p>
      ) : (
        <div className="portfolio-plan-grid">
          {managed.map((position) => (
            <div key={position.symbol} className="portfolio-plan-card">
              <div className="portfolio-plan-heading">
                <SymbolBadge
                  symbol={position.symbol}
                  positive={position.pnl_pct > 0}
                  href={`/charts?symbol=${encodeURIComponent(position.symbol)}&timeframe=5m`}
                />
                <span className="ui-badge ui-badge-info">
                  REV {position.plan_revision ?? 0}
                </span>
              </div>
              <div className="portfolio-plan-values">
                <div>
                  <span>SL</span>
                  <strong className="ui-tone-negative">
                    ₺{money(position.llm_stop_price)}
                  </strong>
                </div>
                <div>
                  <span>TP</span>
                  <strong className="ui-tone-positive">
                    ₺{money(position.llm_take_profit_price)}
                  </strong>
                </div>
                <div>
                  <span>MAX</span>
                  <strong>{planMinutes(position.llm_max_hold_sec)}</strong>
                </div>
              </div>
              <p
                className="portfolio-plan-reason"
                title={position.last_plan_reason || "LLM planı"}
              >
                {position.last_plan_reason ||
                  "LLM tarafından henüz güncellenmedi"}
              </p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function MetricCard({
  label,
  value,
  tone = "",
}: {
  label: string;
  value: string | number;
  tone?: string;
}) {
  return (
    <div className="ui-card ui-stat-card">
      <p className="eyebrow">{label}</p>
      <p className={`ui-stat-value ${tone}`}>{value}</p>
    </div>
  );
}

function SymbolBadge({
  symbol,
  positive,
  href,
}: {
  symbol: string;
  positive: boolean;
  href?: string;
}) {
  const chartHref = href || `/charts?symbol=${encodeURIComponent(symbol)}&timeframe=5m`;
  const content = (
    <span
      className={`portfolio-symbol-badge ${positive ? "positive" : "negative"}`}
    >
      {symbol}
    </span>
  );
  return <Link href={chartHref} title={`${symbol} M5 grafiğini aç`}>{content}</Link>;
}

function PositionTable({
  positions,
  closePosition,
  closing,
}: {
  positions: Position[];
  closePosition: (symbol: string) => void;
  closing: string | null;
}) {
  return (
    <section className="ui-card portfolio-table-card">
      <div className="ui-section-header">
        <div>
          <p className="eyebrow">AÇIK POZİSYONLAR</p>
          <p className="ui-section-description">
            Anlık değerler ve paper pozisyon yönetimi
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => exportOpenPositionsCsv(positions)}
            className="ui-button ui-button-primary ui-button-compact"
            disabled={!positions.length}
            title={!positions.length ? "Dışa aktarılacak açık pozisyon bulunmuyor." : undefined}
          >
            CSV DIŞA AKTAR ({positions.length})
          </button>
          <span className="ui-badge ui-badge-neutral">{positions.length} açık</span>
        </div>
      </div>
      {positions.length === 0 ? (
        <p className="empty-state">Açık pozisyon yok.</p>
      ) : (
        <div className="table-scroll portfolio-table-scroll">
          <table className="data-table portfolio-table">
            <thead>
              <tr>
                <th>SEMBOL</th>
                <th>STRATEJİ</th>
                <th>GİRİŞ</th>
                <th>ANLIK</th>
                <th>PnL</th>
                <th>DEĞER</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {positions.map((position) => (
                <tr key={position.symbol}>
                  <td>
                    <SymbolBadge
                      symbol={position.symbol}
                      positive={position.pnl_pct > 0}
                      href={`/charts?symbol=${encodeURIComponent(position.symbol)}&timeframe=5m`}
                    />
                  </td>
                  <td>
                    <span className="portfolio-strategy">
                      {STRATEGY_LABEL[position.strategy || ""] ||
                        position.strategy ||
                        "—"}
                    </span>
                    {position.strategy === "PUMP_MONITOR" && <small className="table-subvalue">{entrySignal(position.strategy, position.entry_context)}</small>}
                  </td>
                  <td>₺{money(position.entry)}</td>
                  <td>₺{money(position.current)}</td>
                  <td
                    className={pnlTone(position.pnl_try ?? position.pnl_pct)}
                  >
                    ₺{money(position.pnl_try)}
                    <small className="table-subvalue">
                      {position.pnl_pct.toFixed(2)}%
                    </small>
                  </td>
                  <td>₺{money(position.value)}</td>
                  <td>
                    <button
                      onClick={() => closePosition(position.symbol)}
                      disabled={closing === position.symbol}
                      className="ui-button ui-button-danger ui-button-compact"
                    >
                      {closing === position.symbol ? "KAPANIYOR" : "KAPAT"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function TradeCard({ trade, onClick }: { trade: Trade; onClick: () => void }) {
  return (
    <article
      className="portfolio-trade-card"
      onClick={onClick}
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") onClick();
      }}
    >
      <div className="portfolio-trade-top">
        <SymbolBadge
          symbol={trade.symbol}
          positive={trade.pnl > 0}
                      href={`/charts?symbol=${encodeURIComponent(trade.symbol)}&timeframe=5m`}
        />
        <span
          className={
            trade.pnl > 0
              ? "ui-badge ui-badge-positive"
              : "ui-badge ui-badge-negative"
          }
        >
          {trade.pnl > 0 ? "KÂR" : "ZARAR"}
        </span>
      </div>
      <div className="portfolio-trade-meta">
        <span>{STRATEGY_LABEL[trade.strategy] || trade.strategy || "—"}</span>
        <span>{when(trade.exit_time)}</span>
      </div>
      <div className="portfolio-trade-values">
        <div>
          <span>GİRİŞ</span>
          <strong>₺{money(trade.entry_price)}</strong>
        </div>
        <div>
          <span>ÇIKIŞ</span>
          <strong>₺{money(trade.exit_price)}</strong>
        </div>
        <div>
          <span>NET PnL</span>
          <strong
            className={pnlTone(trade.pnl)}
          >
            ₺{money(trade.pnl)}
            <small>{trade.pnl_pct.toFixed(2)}%</small>
          </strong>
        </div>
      </div>
      <div className="portfolio-trade-footer">
        <span>{trade.reason || "Kapanış nedeni yok"}</span>
        <span>{duration(trade)}</span>
      </div>
    </article>
  );
}

function TradeDetail({
  trade,
  onClose,
}: {
  trade: Trade;
  onClose: () => void;
}) {
  return (
    <div className="portfolio-detail-backdrop" onClick={onClose}>
      <section
        className="portfolio-detail-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`${trade.symbol} işlem detayı`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="portfolio-detail-head">
          <div>
            <p className="eyebrow">İŞLEM DETAYI</p>
            <SymbolBadge symbol={trade.symbol} positive={trade.pnl > 0} />
          </div>
          <button className="ui-button ui-button-ghost" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="portfolio-detail-status">
          <span
            className={`ui-badge ${trade.pnl > 0 ? "ui-badge-positive" : "ui-badge-negative"}`}
          >
            {trade.pnl > 0 ? "KÂRLI İŞLEM" : "ZARARLI İŞLEM"}
          </span>
          <span className="text-bunker-muted">
            {STRATEGY_LABEL[trade.strategy] || trade.strategy || "—"}
          </span>
        </div>
        <div className="portfolio-detail-grid">
          <div>
            <span>GİRİŞ FİYATI</span>
            <strong>₺{money(trade.entry_price)}</strong>
          </div>
          <div>
            <span>ÇIKIŞ FİYATI</span>
            <strong>₺{money(trade.exit_price)}</strong>
          </div>
          <div>
            <span>NET PnL</span>
            <strong
              className={pnlTone(trade.pnl)}
            >
              ₺{money(trade.pnl)}
              <small>{trade.pnl_pct.toFixed(2)}%</small>
            </strong>
          </div>
          <div>
            <span>KOMİSYON</span>
            <strong>₺{money(trade.commission)}</strong>
          </div>
          <div>
            <span>AÇIK KALDIĞI SÜRE</span>
            <strong>{duration(trade)}</strong>
          </div>
          <div>
            <span>KAPANIŞ ZAMANI</span>
            <strong>{when(trade.exit_time)}</strong>
          </div>
        </div>
        <div className="portfolio-detail-reason">
          <span>KAPANIŞ NEDENİ</span>
          <p>{trade.reason || "Kapanış nedeni kaydedilmemiş."}</p>
        </div>
      </section>
    </div>
  );
}

export default function PortfolioPage() {
  const [tab, setTab] = useState<"portfolio" | "history">("portfolio");
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [closing, setClosing] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [strategy, setStrategy] = useState("all");
  const [reason, setReason] = useState("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [sortState, setSortState] = useState<{
    key: keyof Trade;
    dir: "asc" | "desc";
  }>({ key: "exit_time", dir: "desc" });
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null);
  const loadVersion = useRef(0);
  const loadTrades = useCallback(() => {
    const version = ++loadVersion.current;
    return (
    fetchAllPages<Trade>("/api/trades", "trades")
      .then((result) => { if (version === loadVersion.current) setTrades(result.rows); })
      .catch(() => undefined));
  }, []);
  const onLiveMessage = useCallback((message: any) => {
    if (message.type === "portfolio") setPortfolio(message.data);
    if (["signal", "trade_updated", "reset"].includes(message.type)) loadTrades();
  }, [loadTrades]);
  useLiveMessages(onLiveMessage);

  useEffect(() => {
    loadTrades();
  }, [loadTrades]);

  const formatTab = (next: "portfolio" | "history") => {
    setTab(next);
    setPage(1);
    window.history.replaceState(
      {},
      "",
      `/portfolio${next === "history" ? "?tab=history" : ""}`,
    );
  };
  const closePosition = async (symbol: string) => {
    setClosing(symbol);
    setMsg(null);
    try {
      const response = await apiRequest(
        `${API_BASE}/api/positions/${symbol}/close`,
        { method: "POST" },
      );
      const data = await response.json();
      setMsg(
        data.message ||
          (data.ok ? "Pozisyon kapatıldı." : "Pozisyon kapatılamadı."),
      );
    } catch {
      setMsg("Pozisyon kapatılamadı.");
    } finally {
      setClosing(null);
    }
  };
  const sortedFiltered = useMemo(() => {
    const normalized = query.trim().toUpperCase();
    const filtered = trades.filter(
      (trade) =>
        (!normalized ||
          `${trade.symbol} ${trade.strategy} ${trade.reason || ""}`
            .toUpperCase()
            .includes(normalized)) &&
        (strategy === "all" || trade.strategy === strategy) &&
        (reason === "all" || trade.reason === reason),
    );
    return [...filtered].sort((a, b) => {
      const av = a[sortState.key] ?? "";
      const bv = b[sortState.key] ?? "";
      const comparison =
        typeof av === "number" && typeof bv === "number"
          ? av - bv
          : String(av).localeCompare(String(bv), "tr");
      return sortState.dir === "asc" ? comparison : -comparison;
    });
  }, [trades, query, strategy, reason, sortState]);
  const rows = sortedFiltered.slice((page - 1) * pageSize, page * pageSize);
  const pages = Math.max(1, Math.ceil(sortedFiltered.length / pageSize));
  const winners = trades.filter((trade) => trade.pnl > 0);
  const losers = trades.filter((trade) => trade.pnl <= 0);
  const netClosed = trades.reduce((sum, trade) => sum + trade.pnl, 0);
  const winRate = trades.length ? (winners.length / trades.length) * 100 : 0;
  const strategyStats = useMemo(() => Object.entries(trades.reduce<Record<string, { count: number; pnl: number; wins: number }>>((all, trade) => {
    const key = trade.strategy || "UNKNOWN";
    const row = all[key] || { count: 0, pnl: 0, wins: 0 };
    row.count += 1; row.pnl += trade.pnl; row.wins += trade.pnl > 0 ? 1 : 0; all[key] = row;
    return all;
  }, {})).sort(([, a], [, b]) => b.pnl - a.pnl), [trades]);
  const formatKey = (key: keyof Trade) => (
    <button
      onClick={() => {
        setSortState((previous) => ({
          key,
          dir: previous.key === key && previous.dir === "asc" ? "desc" : "asc",
        }));
        setPage(1);
      }}
      className="table-sort"
    >
      {key}
      {sortState.key === key ? (sortState.dir === "asc" ? " ▲" : " ▼") : " ↕"}
    </button>
  );

  return (
    <main className="page-shell portfolio-page">
      <header className="page-heading portfolio-heading">
        <div>
          <p className="eyebrow">PAPER PORTFÖY</p>
          <h1>
            <span className="text-neon-green">PORTFÖY</span> YÖNETİMİ
          </h1>
          <p>Sermaye dağılımı, strateji başarısı ve komisyon sonrası net sonuç özeti.</p>
        </div>
        <span className="ui-badge ui-badge-info">CANLI / PAPER</span>
      </header>
      <div className="flex flex-wrap gap-2"><Link href="/reports" className="ui-button ui-button-secondary">📋 İŞLEM RAPORLARINI AÇ</Link><Link href="/" className="ui-button ui-button-secondary">⚡ CANLI SCALPING MONITOR</Link></div>
      {msg && (
        <div className="portfolio-alert" role="status">
          {msg}
        </div>
      )}
      {tab === "portfolio" ? (
        <div className="portfolio-content">
          <div className="portfolio-metrics">
            <MetricCard
              label="TOPLAM DEĞER"
              value={`₺${money(portfolio?.total_value)}`}
            />
            <MetricCard
              label="MEVCUT TL"
              value={`₺${money(portfolio?.try)}`}
              tone="ui-tone-positive"
            />
            <MetricCard
              label="AÇIK POZİSYON"
              value={portfolio?.positions.length ?? 0}
            />
            <MetricCard
              label="GERÇEKLEŞMİŞ + AÇIK PnL"
              value={`₺${money((portfolio?.realized_pnl ?? 0) + (portfolio?.unrealized_pnl ?? 0))}`}
              tone={
                (portfolio?.realized_pnl ?? 0) +
                  (portfolio?.unrealized_pnl ?? 0) >=
                0
                  ? "ui-tone-positive"
                  : "ui-tone-negative"
              }
            />
          </div>
          <section className="ui-card"><div className="ui-section-header"><div><p className="eyebrow">STRATEJİ PERFORMANSI</p><p className="ui-section-description">Kapanmış paper işlemler, komisyon sonrası net sonuç.</p></div><span className="font-mono text-xs text-bunker-muted">{trades.length} işlem</span></div><div className="table-scroll mt-3"><table className="data-table"><thead><tr><th>Strateji</th><th>İşlem</th><th>Başarı</th><th>Net PnL</th></tr></thead><tbody>{strategyStats.map(([name, stat]) => <tr key={name}><td>{STRATEGY_LABEL[name] || name}</td><td>{stat.count}</td><td className={stat.wins / stat.count >= .5 ? "ui-tone-positive" : "ui-tone-negative"}>%{(stat.wins / stat.count * 100).toFixed(1)}</td><td className={stat.pnl >= 0 ? "ui-tone-positive" : "ui-tone-negative"}>₺{money(stat.pnl)}</td></tr>)}{!strategyStats.length && <tr><td colSpan={4} className="py-6 text-center text-bunker-muted">Kapanmış işlem verisi bekleniyor.</td></tr>}</tbody></table></div></section>
          <LlmPlanPanel positions={portfolio?.positions || []} trades={trades} />
        </div>
      ) : (
        <div className="portfolio-content">
          <div className="portfolio-metrics portfolio-history-metrics">
            <MetricCard label="TOPLAM İŞLEM" value={trades.length} />
            <MetricCard
              label="KÂRLI İŞLEM"
              value={winners.length}
              tone="ui-tone-positive"
            />
            <MetricCard
              label="ZARARLI İŞLEM"
              value={losers.length}
              tone="ui-tone-negative"
            />
            <MetricCard
              label="KAPANAN NET SONUÇ"
              value={`₺${money(netClosed)}`}
              tone={netClosed >= 0 ? "ui-tone-positive" : "ui-tone-negative"}
            />
            <MetricCard label="BAŞARI ORANI" value={`%${winRate.toFixed(1)}`} />
          </div>
          <section className="ui-card portfolio-filters print:hidden">
            <div className="portfolio-filter-grid">
              <label className="portfolio-filter portfolio-filter-search">
                <span>ARAMA</span>
                <input
                  value={query}
                  onChange={(event) => {
                    setQuery(event.target.value);
                    setPage(1);
                  }}
                  placeholder="Sembol, strateji veya neden"
                />
              </label>
              <label className="portfolio-filter">
                <span>STRATEJİ</span>
                <select
                  value={strategy}
                  onChange={(event) => {
                    setStrategy(event.target.value);
                    setPage(1);
                  }}
                >
                  <option value="all">Tüm stratejiler</option>
                  {Array.from(new Set(trades.map((trade) => trade.strategy)))
                    .filter(Boolean)
                    .map((value) => (
                      <option key={value} value={value}>
                        {STRATEGY_LABEL[value] || value}
                      </option>
                    ))}
                </select>
              </label>
              <label className="portfolio-filter">
                <span>KAPANIŞ NEDENİ</span>
                <select
                  value={reason}
                  onChange={(event) => {
                    setReason(event.target.value);
                    setPage(1);
                  }}
                >
                  <option value="all">Tüm nedenler</option>
                  {Array.from(
                    new Set(
                      trades.map((trade) => trade.reason).filter(Boolean),
                    ),
                  ).map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
              <label className="portfolio-filter portfolio-filter-page">
                <span>SAYFA</span>
                <select
                  value={pageSize}
                  onChange={(event) => {
                    setPageSize(Number(event.target.value));
                    setPage(1);
                  }}
                >
                  <option value={10}>10 kayıt</option>
                  <option value={25}>25 kayıt</option>
                  <option value={50}>50 kayıt</option>
                  <option value={100}>100 kayıt</option>
                </select>
              </label>
            </div>
          </section>
          <section className="ui-card portfolio-history-card">
            <div className="ui-section-header">
              <div>
                <p className="eyebrow">TAMAMLANAN İŞLEMLER</p>
                <p className="ui-section-description">
                  Komisyon sonrası gerçekleşmiş sonuçlar ·{" "}
                  {sortedFiltered.length} kayıt
                </p>
              </div>
              <div className="ui-section-actions">
                <ExportActions trades={sortedFiltered} />
              </div>
            </div>
            {rows.length === 0 ? (
              <p className="empty-state">
                Filtrelere uyan tamamlanan işlem yok.
              </p>
            ) : (
              <>
                <div className="portfolio-history-table-wrap">
                  <table className="data-table portfolio-history-table">
                    <thead>
                      <tr>
                        <th>{formatKey("symbol")}</th>
                        <th>{formatKey("strategy")}</th>
                        <th>{formatKey("entry_price")}</th>
                        <th>{formatKey("exit_price")}</th>
                        <th>{formatKey("pnl")}</th>
                        <th>{formatKey("exit_time")}</th>
                        <th>AKTİF SÜRE</th>
                        <th>NEDEN</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((trade) => (
                        <tr
                          key={trade.id}
                          onClick={() => setSelectedTrade(trade)}
                          tabIndex={0}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ")
                              setSelectedTrade(trade);
                          }}
                        >
                          <td>
                            <SymbolBadge
                              symbol={trade.symbol}
                              positive={trade.pnl > 0}
                            href={`/charts?symbol=${encodeURIComponent(trade.symbol)}&timeframe=5m`}
                            />
                          </td>
                          <td>
                            <span className="portfolio-strategy">
                              {STRATEGY_LABEL[trade.strategy] ||
                                trade.strategy ||
                                "—"}
                            </span>
                          </td>
                          <td>₺{money(trade.entry_price)}</td>
                          <td>₺{money(trade.exit_price)}</td>
                          <td
                            className={
                              trade.pnl > 0
                                ? "ui-tone-positive"
                                : trade.pnl < 0
                                  ? "ui-tone-negative"
                                  : ""
                            }
                          >
                            ₺{money(trade.pnl)}
                            <small className="table-subvalue">
                              {trade.pnl_pct.toFixed(2)}%
                            </small>
                          </td>
                          <td>{when(trade.exit_time)}</td>
                          <td>{duration(trade)}</td>
                          <td>
                            <span
                              className="portfolio-reason"
                              title={trade.reason || "—"}
                            >
                              {trade.reason || "—"}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="portfolio-mobile-trades">
                  {rows.map((trade) => (
                    <TradeCard
                      key={trade.id}
                      trade={trade}
                      onClick={() => setSelectedTrade(trade)}
                    />
                  ))}
                </div>
                <div className="portfolio-pagination">
                  <span>
                    Sayfa {page} / {pages} · {sortedFiltered.length} kayıt
                  </span>
                  <div>
                    <button
                      disabled={page <= 1}
                      onClick={() => setPage((value) => Math.max(1, value - 1))}
                      className="ui-button ui-button-secondary ui-button-compact"
                    >
                      ÖNCEKİ
                    </button>
                    <button
                      disabled={page >= pages}
                      onClick={() =>
                        setPage((value) => Math.min(pages, value + 1))
                      }
                      className="ui-button ui-button-secondary ui-button-compact"
                    >
                      SONRAKİ
                    </button>
                  </div>
                </div>
              </>
            )}
          </section>
        </div>
      )}
      {selectedTrade && (
        <TradeDetail
          trade={selectedTrade}
          onClose={() => setSelectedTrade(null)}
        />
      )}
    </main>
  );
}
