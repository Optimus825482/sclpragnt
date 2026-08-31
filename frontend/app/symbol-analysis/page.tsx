"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import SymbolLink from "../components/SymbolLink";
import { Badge, Button, Card as UiCard, SectionHeader, StatCard, Tabs } from "../components/ui";

const value = (v: any) => v == null ? "—" : Number(v).toLocaleString("tr-TR", { maximumFractionDigits: 4 });
const percent = (v: any) => v == null ? "—" : `${(v * 100).toFixed(2)}%`;
const Card = ({ title, children }: { title: string; children: React.ReactNode }) => <div className="card bg-bunker-950"><p className="eyebrow">{title}</p><div className="mt-3">{children}</div></div>;

const DIRECTION_META: Record<string, { label: string; icon: string; tone: "positive" | "negative" | "warning" }> = {
  up: { label: "YUKARI", icon: "↑", tone: "positive" },
  down: { label: "AŞAĞI", icon: "↓", tone: "negative" },
  range: { label: "YATAY", icon: "→", tone: "warning" },
};
const horizonLabel = (h: number) => h === 60 ? "H1 · 60 DK" : h === 5 ? "M5 · 5 DK" : h === 15 ? "M15 · 15 DK" : `${h} DK`;

function ForecastCard({ item, currentPrice }: { item: any; currentPrice?: number }) {
  const meta = DIRECTION_META[item.direction] || DIRECTION_META.range;
  const confidence = Math.round(Number(item.confidence) || 0);
  const invalidation = item.invalidation_price == null ? null : Number(item.invalidation_price);
  const distancePct = invalidation != null && currentPrice ? (invalidation / currentPrice - 1) * 100 : null;
  return <div className="rounded-lg border border-bunker-700 bg-bunker-900/50 p-4 space-y-3">
    <div className="flex items-center justify-between gap-2">
      <p className="eyebrow">{horizonLabel(item.horizon_minutes)}</p>
      <Badge tone={meta.tone}>{meta.icon} {meta.label}</Badge>
    </div>
    <div>
      <div className="flex items-center justify-between text-xs text-bunker-muted">
        <span>Güven</span><span className="font-mono">%{confidence}</span>
      </div>
      <div className="mt-1 h-1.5 rounded bg-bunker-800 overflow-hidden">
        <div className={`h-full rounded ${confidence >= 65 ? "bg-neon-green" : confidence >= 45 ? "bg-yellow-400" : "bg-bunker-500"}`}
          style={{ width: `${Math.max(4, confidence)}%` }} />
      </div>
    </div>
    <p className="text-xs leading-5 text-slate-200">{item.scenario}</p>
    {item.counter_scenario && <p className="text-xs leading-5 text-bunker-muted border-l-2 border-bunker-700 pl-2">Karşı: {item.counter_scenario}</p>}
    <p className="text-xs text-bunker-muted">
      Bozulma: {invalidation == null ? "belirtilmedi" : `₺${value(invalidation)}`}
      {distancePct != null && <span className="text-bunker-500"> ({distancePct > 0 ? "+" : ""}{distancePct.toFixed(2)}% uzaklık)</span>}
    </p>
  </div>;
}

export default function SymbolAnalysisPage() {
  const [symbol, setSymbol] = useState("BTCTRY");
  const [symbols, setSymbols] = useState<string[]>([]);
  const [timeframe, setTimeframe] = useState("5m");
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const [commentary, setCommentary] = useState<any>(null);
  const [commentaryLoading, setCommentaryLoading] = useState(false);
  const [forecastHistory, setForecastHistory] = useState<any>(null);
  const analyzedSymbol = useRef<string | null>(null);

  useEffect(() => {
    apiRequest(`${API_BASE}/api/config`).then(r => r.json()).then(d => {
      const list = d.symbols || [];
      setSymbols(list);
      setSymbol(new URLSearchParams(location.search).get("symbol") || list[0] || "BTCTRY");
    }).catch(() => setError("Konfigürasyon alınamadı"));
  }, []);
  useEffect(() => {
    setData(null);
    const load = () => apiRequest(`${API_BASE}/api/symbol-analysis/${symbol}?timeframe=${timeframe}`, { cache: "no-store" })
      .then(r => r.json()).then(setData).catch(() => setError("Sembol analizi alınamadı"));
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [symbol, timeframe]);
  useEffect(() => {
    apiRequest(`${API_BASE}/api/symbol-analysis/${symbol}/forecasts?limit=12`, { cache: "no-store" })
      .then(r => r.json()).then(setForecastHistory).catch(() => undefined);
  }, [symbol, commentary]);

  const askCommentary = async () => {
    setCommentaryLoading(true); setCommentary(null);
    try {
      const response = await apiRequest(`${API_BASE}/api/symbol-analysis/${symbol}/llm/commentary`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({})
      });
      const result = await response.json();
      setCommentary(response.ok ? result : { error: result.error || "Yorum alınamadı" });
    } catch { setCommentary({ error: "LLM yorumuna ulaşılamadı" }); }
    finally { setCommentaryLoading(false); }
  };

  // The Charts page opens this screen from its single “Analiz” button.  Run
  // the brief LLM forecast automatically so a second click is never needed.
  useEffect(() => {
    if (!symbols.length || analyzedSymbol.current === symbol) return;
    analyzedSymbol.current = symbol;
    void askCommentary();
  }, [symbol, symbols.length]);

  const trend = data?.trend || {}, momentum = data?.momentum || {}, volatility = data?.volatility || {};
  const volume = data?.volume || {}, oscillators = data?.oscillators?.values || {}, averages = data?.moving_averages || {};
  const jq = commentary?.symbol_journal_quality;
  const hasForecastError = Boolean(commentary?.error);
  return <div className="max-w-7xl mx-auto space-y-6">
    <header className="space-y-4">
      <div className="flex flex-wrap justify-between gap-3">
        <div>
          <h1 className="font-mono text-xl font-bold"><span className="text-neon-green">SEMBOL</span> ANALİZİ</h1>
          <p className="eyebrow mt-1"><SymbolLink symbol={symbol} className="text-bunker-muted hover:text-neon-green" /> · {timeframe} · canlı public data</p>
        </div>
        <select value={symbol} onChange={e => setSymbol(e.target.value)} className="input max-w-40">{symbols.map(s => <option key={s}>{s}</option>)}</select>
      </div>
      <Tabs items={["1m", "5m", "15m", "30m", "1h", "4h", "1d"].map(tf => ({ id: tf, label: tf }))}
        active={timeframe} onChange={setTimeframe} className="w-fit" />
    </header>

    <section className="card border-neon-green/25 bg-gradient-to-br from-neon-green/10 via-bunker-950 to-bunker-950 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="eyebrow text-neon-green">OLASILIKLI LLM SENARYOSU</p>
          <p className="mt-1 text-sm text-bunker-muted">M5 · M15 · H1 tahminleri; sembol hafızası, ölçülmüş dersler ve journal kalitesiyle güven kalibre edilir.</p>
        </div>
        <div className="flex items-center gap-2">
          {commentary?.model && <Badge tone="info">{commentary.model}</Badge>}
          {commentary && !hasForecastError && <Badge tone="positive">KAYDEDİLDİ · ÖLÇÜM BEKLİYOR</Badge>}
          <Button variant="secondary" onClick={askCommentary} disabled={commentaryLoading}>
            {commentaryLoading ? "LLM DEĞERLENDİRİYOR…" : commentary ? "↻ YENİDEN ANALİZ" : "ANALİZ ET"}
          </Button>
        </div>
      </div>

      {jq && <div className="flex flex-wrap gap-2 text-xs">
        <Badge tone="neutral">Öğrenilmiş profil: {jq.evaluated} ölçüm</Badge>
        <Badge tone={(jq.touched || 0) > 0 ? "positive" : "warning"}>{jq.touched} dokunuş</Badge>
        <Badge tone={(jq.avg_mfe_pct || 0) >= 2 ? "positive" : (jq.avg_mfe_pct || 0) >= 0.8 ? "warning" : "negative"}>
          ort. MFE %{Number(jq.avg_mfe_pct).toFixed(2)}
        </Badge>
        <span className="text-bunker-500 self-center">— sistem bu sembolde öğrendikleriyle güveni kalibre eder</span>
      </div>}

      {commentaryLoading && <div className="space-y-3 animate-pulse">
        <div className="h-4 rounded bg-bunker-800 w-3/4" />
        <div className="grid gap-3 md:grid-cols-3"><div className="h-40 rounded bg-bunker-800" /><div className="h-40 rounded bg-bunker-800" /><div className="h-40 rounded bg-bunker-800" /></div>
      </div>}

      {!commentaryLoading && commentary && <div className="rounded-lg border border-bunker-700 bg-bunker-950/70 p-4 text-sm text-slate-200">
        {hasForecastError ? <div className="space-y-3">
          <p className="text-yellow-300">⚠ {commentary.error}</p>
          <p className="text-xs text-bunker-muted">Sistem şemaya uymayan yanıtı otomatik düzeltmeyi denedi; bu turda başarılı olunamadı. Tekrar deneyebilirsiniz.</p>
          <Button variant="primary" onClick={askCommentary}>TEKRAR DENE</Button>
        </div> : <>
          <p className="leading-7">{commentary.commentary}</p>
          {commentary.forecasts?.length > 0 && <div className="mt-4 grid gap-3 md:grid-cols-3">
            {commentary.forecasts.map((item: any) => <ForecastCard key={item.forecast_id} item={item} currentPrice={data?.price} />)}
          </div>}
        </>}
      </div>}
    </section>

    {forecastHistory?.forecasts?.length > 0 && <section className="card">
      <SectionHeader eyebrow="TAHMİN GÜNLÜĞÜ" title="Kapanmış mumlarla ölçülen geçmiş tahminler"
        description={`Ölçülen: ${forecastHistory.evaluated_count ?? "—"} · Doğruluk: ${forecastHistory.directional_accuracy == null ? "—" : `%${(forecastHistory.directional_accuracy * 100).toFixed(0)}`}`} />
      <div className="mt-3 space-y-2">
        {forecastHistory.forecasts.slice(0, 8).map((item: any) => {
          const meta = DIRECTION_META[item.direction] || DIRECTION_META.range;
          const evaluated = item.status === "evaluated";
          return <div key={item.forecast_id} className="rounded border border-bunker-800 px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
              <span className="font-mono text-white">{horizonLabel(item.horizon_minutes)} <span className="text-bunker-muted">{meta.icon}</span></span>
              <Badge tone={!evaluated ? "warning" : item.direction_correct ? "positive" : "negative"}>
                {!evaluated ? "BEKLİYOR" : item.direction_correct ? "DOĞRU" : "YANLIŞ"}
              </Badge>
              <span className={evaluated && item.outcome_return_pct != null ? ((item.outcome_return_pct || 0) >= 0 ? "text-neon-green font-mono" : "text-neon-red font-mono") : "text-bunker-muted"}>
                {evaluated && item.outcome_return_pct != null ? `${(item.outcome_return_pct * 100).toFixed(2)}%` : "—"}
              </span>
            </div>
            {item.scenario && <p className="mt-1 text-xs text-bunker-muted truncate">{item.scenario}</p>}
          </div>;
        })}
      </div>
    </section>}

    {!data?.data_ready ? <Card title="VERİ DURUMU"><p className="text-bunker-muted">{error || data?.error || "Veri hazırlanıyor..."}</p></Card> : <>
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="FİYAT" value={`₺${value(data.price)}`} />
        <StatCard label="TREND" value={String(trend.alignment || "—").toUpperCase()} tone={trend.alignment === "bullish" ? "positive" : trend.alignment === "bearish" ? "negative" : "default"} />
        <StatCard label="ÖZET" value={String(data.summary || "—").toUpperCase()} />
        <StatCard label="ADR KALAN" value={percent(volatility.remaining_capacity_pct)} tone={(volatility.remaining_capacity_pct || 0) < 0 ? "warning" : "default"} />
      </div>
      <div className="grid md:grid-cols-3 gap-4">
        <Card title="OSİLATÖRLER"><div className="space-y-2">{[["RSI", oscillators.rsi_14], ["Stochastic", oscillators.stochastic_k], ["CCI", oscillators.cci_20], ["ADX", oscillators.adx_14], ["MACD", oscillators.macd_histogram], ["Williams %R", oscillators.williams_r]].map(([name, val]) => <div className="flex justify-between text-sm" key={name}><span className="text-bunker-muted">{name}</span><span className="font-mono">{value(val)}</span></div>)}</div></Card>
        <Card title="HAREKETLİ ORTALAMALAR"><div className="grid grid-cols-2 gap-2">{Object.entries(averages).map(([name, val]: any) => <div key={name}><p className="text-xs text-bunker-muted">{name}</p><p className="font-mono text-sm">{value(val)}</p></div>)}</div></Card>
        <Card title="HACİM / MOMENTUM"><div className="grid grid-cols-2 gap-3">{[["Hacim", volume.volume_ratio_20 == null ? "—" : `${value(volume.volume_ratio_20)}x`], ["VWAP", value(volume.vwap)], ["ATR %", percent(volatility.atr_pct)], ["RSI", value(momentum.rsi_14)], ["MACD", value(momentum.macd?.histogram)], ["ADX", value(trend.adx?.adx)]].map(([name, val]) => <div key={name}><p className="text-xs text-bunker-muted">{name}</p><p className="font-mono text-sm">{val}</p></div>)}</div></Card>
      </div>
    </>}
  </div>;
}
