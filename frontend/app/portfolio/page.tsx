"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { API_BASE, WS_BASE } from "../lib/api";

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
};

type Position = {
  symbol: string;
  entry: number;
  current: number;
  pnl_pct: number;
  pnl_try?: number;
  value: number;
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
  entry_price: number;
  exit_price: number;
  pnl: number;
  pnl_pct: number;
  commission?: number;
  reason?: string;
  entry_time?: number;
  exit_time?: number;
  hold_seconds?: number;
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

function ExportActions({ trades }: { trades: Trade[] }) {
  const exportCsv = async () => {
    const source = trades.length
      ? trades
      : (
          await fetch(`${API_BASE}/api/trades`, { cache: "no-store" })
            .then((r) => r.json())
            .catch(() => ({ trades: [] }))
        ).trades || [];
    const head = [
      "ID",
      "Sembol",
      "Strateji",
      "Giriş",
      "Çıkış",
      "Komisyon",
      "PnL",
      "PnL %",
      "Neden",
      "Giriş zamanı",
      "Çıkış zamanı",
      "Aktif süre",
    ];
    const body = source.map((trade: Trade) => [
      trade.id,
      trade.symbol,
      trade.strategy,
      trade.entry_price,
      trade.exit_price,
      trade.commission ?? 0,
      trade.pnl,
      trade.pnl_pct,
      trade.reason || "",
      when(trade.entry_time),
      when(trade.exit_time),
      duration(trade),
    ]);
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
      <button onClick={exportCsv} className="ui-button ui-button-primary">
        CSV DIŞA AKTAR
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
                  href={`/symbol-analysis?symbol=${position.symbol}`}
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
  const content = (
    <span
      className={`portfolio-symbol-badge ${positive ? "positive" : "negative"}`}
    >
      {symbol}
    </span>
  );
  return href ? <Link href={href}>{content}</Link> : content;
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
        <span className="ui-badge ui-badge-neutral">
          {positions.length} açık
        </span>
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
                      href={`/symbol-analysis?symbol=${position.symbol}`}
                    />
                  </td>
                  <td>
                    <span className="portfolio-strategy">
                      {STRATEGY_LABEL[position.strategy || ""] ||
                        position.strategy ||
                        "—"}
                    </span>
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
          href={`/symbol-analysis?symbol=${trade.symbol}`}
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
            className={trade.pnl > 0 ? "ui-tone-positive" : "ui-tone-negative"}
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
              className={
                trade.pnl > 0 ? "ui-tone-positive" : "ui-tone-negative"
              }
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

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("tab") === "history")
      setTab("history");
  }, []);
  useEffect(() => {
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let ws: WebSocket | null = null;
    const loadTrades = () =>
      fetch(`${API_BASE}/api/trades`, { cache: "no-store" })
        .then((response) => response.json())
        .then((data) => {
          if (!closed) setTrades(data.trades || []);
        })
        .catch(() => undefined);
    const connect = () => {
      ws = new WebSocket(`${WS_BASE}/ws`);
      ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "portfolio") setPortfolio(message.data);
        if (["signal", "trade_updated", "reset"].includes(message.type))
          loadTrades();
      };
      ws.onclose = () => {
        if (!closed) retry = setTimeout(connect, 2000);
      };
    };
    loadTrades();
    connect();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      ws?.close();
    };
  }, []);

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
      const response = await fetch(
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
          <p>
            Sanal cüzdan, açık pozisyonlar ve tamamlanan işlemleri tek bir
            taşmasız çalışma alanında izleyin.
          </p>
        </div>
        <span className="ui-badge ui-badge-info">CANLI / PAPER</span>
      </header>
      <nav className="ui-tabs portfolio-tabs" aria-label="Portföy sekmeleri">
        <button
          className={tab === "portfolio" ? "active" : ""}
          onClick={() => formatTab("portfolio")}
        >
          📊 PORTFÖY <small>{portfolio?.positions.length ?? 0}</small>
        </button>
        <button
          className={tab === "history" ? "active" : ""}
          onClick={() => formatTab("history")}
        >
          📜 TAMAMLANAN İŞLEMLER <small>{trades.length}</small>
        </button>
      </nav>
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
          <LlmPlanPanel
            positions={portfolio?.positions || []}
            trades={trades}
          />
          <PositionTable
            positions={portfolio?.positions || []}
            closePosition={closePosition}
            closing={closing}
          />
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
                              href={`/symbol-analysis?symbol=${trade.symbol}`}
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
