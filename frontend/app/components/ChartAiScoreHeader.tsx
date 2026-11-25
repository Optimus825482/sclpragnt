"use client";

import { useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";

type Tone = "positive" | "negative" | "neutral";

interface ChartAiScoreData {
  status: "ok";
  source: "binance_spot";
  symbol: string;
  asset_type: string;
  current_price: number;
  octobot: {
    score: number;
    consensus_pct: number;
    signal_label: string;
    tone: Tone;
  };
  qlib: {
    score: number;
    rank: string;
    rank_label: string;
    tone: Tone;
  };
}

interface ChartAiScoreHeaderProps {
  symbol: string;
  assetType?: string;
  className?: string;
  compact?: boolean;
}

const scoreCache = new Map<string, { data: ChartAiScoreData; expires: number }>();
const requests = new Map<string, Promise<ChartAiScoreData | null>>();

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function isTone(value: unknown): value is Tone {
  return value === "positive" || value === "negative" || value === "neutral";
}

function isChartAiScore(value: unknown, symbol: string, assetType: string): value is ChartAiScoreData {
  const data = record(value);
  const octobot = record(data?.octobot);
  const qlib = record(data?.qlib);
  return data?.status === "ok" && data.source === "binance_spot"
    && data.symbol === symbol && data.asset_type === assetType
    && typeof data.current_price === "number" && Number.isFinite(data.current_price) && data.current_price > 0
    && octobot !== null && Number.isFinite(octobot.score)
    && typeof octobot.consensus_pct === "number" && octobot.consensus_pct >= 0 && octobot.consensus_pct <= 100
    && typeof octobot.signal_label === "string" && isTone(octobot.tone)
    && qlib !== null && Number.isFinite(qlib.score)
    && typeof qlib.rank === "string" && typeof qlib.rank_label === "string" && isTone(qlib.tone);
}

async function fetchScore(symbol: string, assetType: string): Promise<ChartAiScoreData | null> {
  const query = new URLSearchParams({ symbol, asset_type: assetType });
  let response = await apiRequest(`${API_BASE}/api/v1/ai-trading-suite/chart-score?${query}`);
  if (response.status === 404) {
    response = await apiRequest(`${API_BASE}/api/ai-trading-suite/chart-score?${query}`);
  }
  if (!response.ok) return null;
  const data: unknown = await response.json();
  return isChartAiScore(data, symbol, assetType) ? data : null;
}

function loadScore(symbol: string, assetType: string, key: string): Promise<ChartAiScoreData | null> {
  const now = Date.now();
  for (const [cachedKey, cached] of scoreCache) {
    if (cached.expires <= now) scoreCache.delete(cachedKey);
  }
  const cached = scoreCache.get(key);
  if (cached) return Promise.resolve(cached.data);
  const inProgress = requests.get(key);
  if (inProgress) return inProgress;

  const request = fetchScore(symbol, assetType)
    .then((data) => {
      if (data) scoreCache.set(key, { data, expires: Date.now() + 25_000 });
      return data;
    })
    .catch(() => null)
    .finally(() => requests.delete(key));
  requests.set(key, request);
  return request;
}

export default function ChartAiScoreHeader({ symbol, assetType = "SPOT", ...props }: ChartAiScoreHeaderProps) {
  const normalizedSymbol = symbol.trim().toUpperCase().replace(/_/g, "");
  const normalizedAssetType = assetType.trim().toUpperCase();
  const requestKey = `${normalizedSymbol}:${normalizedAssetType}`;
  return <ChartAiScore key={requestKey} requestKey={requestKey} symbol={normalizedSymbol} assetType={normalizedAssetType} {...props} />;
}

function ChartAiScore({
  symbol,
  assetType,
  requestKey,
  className = "",
  compact = false,
}: ChartAiScoreHeaderProps & { assetType: string; requestKey: string }) {
  const [displayData, setDisplayData] = useState<ChartAiScoreData | null | undefined>(undefined);

  useEffect(() => {
    if (!symbol) return;
    let active = true;
    loadScore(symbol, assetType, requestKey).then((score) => {
      if (active) setDisplayData(score);
    });
    return () => {
      active = false;
    };
  }, [symbol, assetType, requestKey]);

  const layout = `flex min-w-0 max-w-full flex-wrap items-center gap-1.5 font-mono ${compact ? "text-[10px]" : "text-xs"} ${className}`;
  if (!displayData) {
    return (
      <div className={layout} role="status">
        <span className="rounded border border-bunker-700 px-2 py-1 text-bunker-muted">
          {symbol && displayData === undefined ? "Grafik skoru yükleniyor…" : "Güncel skor alınamadı"}
        </span>
      </div>
    );
  }
  const octoToneClass =
    displayData.octobot.tone === "positive"
      ? "bg-emerald-950/95 text-emerald-100 border-emerald-500/70 font-semibold shadow-sm"
      : displayData.octobot.tone === "negative"
      ? "bg-rose-950/95 text-rose-100 border-rose-500/70 font-semibold shadow-sm"
      : "bg-slate-900/95 text-slate-100 border-slate-600 font-semibold shadow-sm";

  const qlibToneClass =
    displayData.qlib.tone === "positive"
      ? "bg-cyan-950/95 text-cyan-100 border-cyan-500/70 font-semibold shadow-sm"
      : displayData.qlib.tone === "negative"
      ? "bg-amber-950/95 text-amber-100 border-amber-500/70 font-semibold shadow-sm"
      : "bg-slate-900/95 text-slate-100 border-slate-600 font-semibold shadow-sm";

  if (compact) {
    return (
      <div className={layout}>
        <span
          className={`flex min-w-0 max-w-full flex-wrap items-center gap-1 px-1.5 py-0.5 rounded border transition-colors ${octoToneClass}`}
          title={`OctoBot Matris Konsensüsü: %${displayData.octobot.consensus_pct} ${displayData.octobot.signal_label} (${displayData.octobot.score} Puan)`}
        >
          <span className="font-bold text-white">🤖 Octo:</span>
          <span className="font-bold text-emerald-300">%{displayData.octobot.consensus_pct}</span>
          <span className="text-[9px] text-emerald-100 font-bold bg-black/40 px-1 rounded">({displayData.octobot.score})</span>
        </span>

        <span
          className={`flex min-w-0 max-w-full flex-wrap items-center gap-1 px-1.5 py-0.5 rounded border transition-colors ${qlibToneClass}`}
          title={`Microsoft Qlib Multi-Factor Alpha: ${displayData.qlib.score} (${displayData.qlib.rank_label})`}
        >
          <span className="font-bold text-white">📊 Qlib:</span>
          <span className="font-bold text-cyan-300">{displayData.qlib.score}</span>
          <span className="text-[9px] text-cyan-100 font-bold bg-black/40 px-1 rounded break-words min-w-0">{displayData.qlib.rank.replace("_ALPHA", "")}</span>
        </span>
      </div>
    );
  }

  return (
    <div className={layout}>
      {/* OctoBot Matris Rozeti */}
      <div
        className={`flex min-w-0 max-w-full flex-wrap items-center gap-1.5 px-2 py-1 rounded-lg border shadow-sm transition-colors ${octoToneClass}`}
        title="OctoBot: 15 dakikalık mumlardan hesaplanan uzlaşı"
      >
        <span className="text-[12px]">🤖</span>
        <span className="font-bold text-white tracking-wide">OctoBot:</span>
        <span className="min-w-0 break-words font-bold text-emerald-300">%{displayData.octobot.consensus_pct} {displayData.octobot.signal_label}</span>
        <span className="text-[11px] font-bold text-emerald-100 bg-emerald-900/80 px-1.5 py-0.5 rounded border border-emerald-500/40">({displayData.octobot.score} Puan)</span>
      </div>

      {/* Microsoft Qlib Alpha Rozeti */}
      <div
        className={`flex min-w-0 max-w-full flex-wrap items-center gap-1.5 px-2 py-1 rounded-lg border shadow-sm transition-colors ${qlibToneClass}`}
        title="Qlib: 15 dakikalık mumlardan hesaplanan alfa skoru"
      >
        <span className="text-[12px]">📊</span>
        <span className="font-bold text-white tracking-wide">Qlib Alpha:</span>
        <span className="font-bold text-cyan-300">{displayData.qlib.score}</span>
        <span className="min-w-0 break-words text-[10px] px-1.5 py-0.5 rounded bg-black/50 text-white font-bold border border-cyan-500/30">
          {displayData.qlib.rank_label}
        </span>
      </div>
    </div>
  );
}
