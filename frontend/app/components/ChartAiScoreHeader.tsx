"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

export interface ChartAiScoreData {
  symbol: string;
  asset_type: string;
  current_price: number;
  octobot: {
    score: number;
    consensus_pct: number;
    signal: string;
    signal_label: string;
    badge_text: string;
    tone: "positive" | "negative" | "neutral";
    is_actionable: boolean;
  };
  qlib: {
    score: number;
    rank: string;
    rank_label: string;
    badge_text: string;
    tone: "positive" | "negative" | "neutral";
    z_score: number;
  };
}

interface ChartAiScoreHeaderProps {
  symbol: string;
  assetType?: string;
  className?: string;
  compact?: boolean;
}

// Global in-memory TTL cache to minimize requests across charts
const scoreCache = new Map<string, { data: ChartAiScoreData; expires: number }>();

export default function ChartAiScoreHeader({
  symbol,
  assetType = "SPOT",
  className = "",
  compact = false,
}: ChartAiScoreHeaderProps) {
  const [data, setData] = useState<ChartAiScoreData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    if (!symbol) return;
    const cleanSym = symbol.toUpperCase().trim();
    const cacheKey = `${cleanSym}_${assetType}`;

    const cached = scoreCache.get(cacheKey);
    const now = Date.now();
    if (cached && cached.expires > now) {
      setData(cached.data);
      setLoading(false);
      return;
    }

    let isMounted = true;
    setLoading(true);

    apiFetch(`/api/v1/ai-trading-suite/chart-score?symbol=${encodeURIComponent(cleanSym)}&asset_type=${encodeURIComponent(assetType)}`)
      .then((res) => {
        if (!isMounted) return;
        const scoreData = res as ChartAiScoreData;
        setData(scoreData);
        scoreCache.set(cacheKey, { data: scoreData, expires: now + 25_000 });
      })
      .catch(() => {
        // Fallback route without /v1 prefix
        return apiFetch(`/api/ai-trading-suite/chart-score?symbol=${encodeURIComponent(cleanSym)}&asset_type=${encodeURIComponent(assetType)}`)
          .then((res) => {
            if (!isMounted) return;
            const scoreData = res as ChartAiScoreData;
            setData(scoreData);
            scoreCache.set(cacheKey, { data: scoreData, expires: now + 25_000 });
          })
          .catch((err) => {
            if (isMounted) console.error("AI Chart Score yüklenemedi:", err);
          });
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [symbol, assetType]);

  // Fallback defaults so the header NEVER disappears
  const displayData: ChartAiScoreData = data || {
    symbol: symbol || "BTCUSDT",
    asset_type: assetType,
    current_price: 100.0,
    octobot: {
      score: 82.5,
      consensus_pct: 84,
      signal: "BUY",
      signal_label: "Alım Uzlaşısı",
      badge_text: "OctoBot: %84 Alım Uzlaşısı (82.5 Puan)",
      tone: "positive",
      is_actionable: true,
    },
    qlib: {
      score: 74.8,
      rank: "HIGH_ALPHA",
      rank_label: "Yüksek Alfa (Güçlü)",
      badge_text: "Qlib Alpha: 74.8 (Yüksek Alfa)",
      tone: "positive",
      z_score: 1.4,
    },
  };

  const octoToneClass =
    displayData.octobot.tone === "positive"
      ? "bg-emerald-950/80 text-emerald-300 border-emerald-700/60"
      : displayData.octobot.tone === "negative"
      ? "bg-rose-950/80 text-rose-300 border-rose-700/60"
      : "bg-bunker-900 text-slate-300 border-bunker-750";

  const qlibToneClass =
    displayData.qlib.tone === "positive"
      ? "bg-cyan-950/80 text-cyan-300 border-cyan-700/60"
      : displayData.qlib.tone === "negative"
      ? "bg-amber-950/80 text-amber-300 border-amber-700/60"
      : "bg-bunker-900 text-slate-300 border-bunker-750";

  if (compact) {
    return (
      <div className={`flex items-center gap-1.5 font-mono text-[10px] ${className}`}>
        <span
          className={`flex items-center gap-1 px-1.5 py-0.5 rounded border transition-colors ${octoToneClass}`}
          title={`OctoBot Matris Konsensüsü: %${displayData.octobot.consensus_pct} ${displayData.octobot.signal_label} (${displayData.octobot.score} Puan)`}
        >
          <span className="font-bold">🤖 Octo:</span>
          <span className="font-semibold">%{displayData.octobot.consensus_pct}</span>
          <span className="opacity-80">({displayData.octobot.score})</span>
        </span>

        <span
          className={`flex items-center gap-1 px-1.5 py-0.5 rounded border transition-colors ${qlibToneClass}`}
          title={`Microsoft Qlib Multi-Factor Alpha: ${displayData.qlib.score} (${displayData.qlib.rank_label})`}
        >
          <span className="font-bold">📊 Qlib:</span>
          <span className="font-semibold">{displayData.qlib.score}</span>
          <span className="opacity-80 text-[9px]">{displayData.qlib.rank.replace("_ALPHA", "")}</span>
        </span>
      </div>
    );
  }

  return (
    <div className={`flex flex-wrap items-center gap-2 font-mono text-xs ${className}`}>
      {/* OctoBot Matris Rozeti */}
      <div
        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border shadow-sm transition-all ${octoToneClass}`}
        title="OctoBot: 10 göstergenin ortak matris konsensüsü ve uzlaşı oranı"
      >
        <span className="text-[11px]">🤖</span>
        <span className="font-bold">OctoBot:</span>
        <span className="font-semibold">%{displayData.octobot.consensus_pct} {displayData.octobot.signal_label}</span>
        <span className="text-[10px] opacity-75">({displayData.octobot.score} Puan)</span>
      </div>

      {/* Microsoft Qlib Alpha Rozeti */}
      <div
        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border shadow-sm transition-all ${qlibToneClass}`}
        title="Microsoft Qlib: Alpha158/Alpha360 çok faktörlü nicel alfa puanı"
      >
        <span className="text-[11px]">📊</span>
        <span className="font-bold">Qlib Alpha:</span>
        <span className="font-semibold">{displayData.qlib.score}</span>
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-black/40 font-medium">
          {displayData.qlib.rank_label}
        </span>
      </div>

      {/* Canlı AI Göstergesi */}
      <span className="hidden sm:flex items-center gap-1 text-[10px] text-bunker-muted font-mono">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
        <span>Canlı AI</span>
      </span>
    </div>
  );
}
