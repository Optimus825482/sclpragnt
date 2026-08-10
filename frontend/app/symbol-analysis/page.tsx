"use client";

import { useEffect, useState } from "react";
import { API_BASE } from "../lib/api";
import SymbolLink from "../components/SymbolLink";

const value = (v: any) => v == null ? "—" : Number(v).toLocaleString("tr-TR", { maximumFractionDigits: 4 });
const percent = (v: any) => v == null ? "—" : `${(v * 100).toFixed(2)}%`;
const Card = ({ title, children }: { title: string; children: React.ReactNode }) => <div className="card bg-bunker-950"><p className="eyebrow">{title}</p><div className="mt-3">{children}</div></div>;

export default function SymbolAnalysisPage() {
  const [symbol, setSymbol] = useState("BTCTRY");
  const [symbols, setSymbols] = useState<string[]>([]);
  const [timeframe, setTimeframe] = useState("5m");
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const [commentary, setCommentary] = useState<any>(null);
  const [commentaryLoading, setCommentaryLoading] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/config`).then(r => r.json()).then(d => {
      const list = d.symbols || [];
      setSymbols(list);
      setSymbol(new URLSearchParams(location.search).get("symbol") || list[0] || "BTCTRY");
    }).catch(() => setError("Konfigürasyon alınamadı"));
  }, []);
  useEffect(() => {
    setData(null);
    const load = () => fetch(`${API_BASE}/api/symbol-analysis/${symbol}?timeframe=${timeframe}`, { cache: "no-store" })
      .then(r => r.json()).then(setData).catch(() => setError("Sembol analizi alınamadı"));
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [symbol, timeframe]);

  const askCommentary = async () => {
    setCommentaryLoading(true); setCommentary(null);
    try {
      const response = await fetch(`${API_BASE}/api/symbol-analysis/${symbol}/llm/commentary`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({})
      });
      const result = await response.json();
      setCommentary(response.ok ? result : { error: result.error || "Yorum alınamadı" });
    } catch { setCommentary({ error: "LLM yorumuna ulaşılamadı" }); }
    finally { setCommentaryLoading(false); }
  };

  const trend = data?.trend || {}, momentum = data?.momentum || {}, volatility = data?.volatility || {};
  const volume = data?.volume || {}, oscillators = data?.oscillators?.values || {}, averages = data?.moving_averages || {};
  return <div className="max-w-7xl mx-auto space-y-6">
    <header className="space-y-4"><div className="flex flex-wrap justify-between gap-3"><div><h1 className="font-mono text-xl font-bold"><span className="text-neon-green">SEMBOL</span> ANALİZİ</h1><p className="eyebrow mt-1"><SymbolLink symbol={symbol} className="text-bunker-muted hover:text-neon-green" /> · {timeframe} · canlı public data</p></div><select value={symbol} onChange={e => setSymbol(e.target.value)} className="input max-w-40">{symbols.map(s => <option key={s}>{s}</option>)}</select></div><div className="flex max-w-full gap-1 overflow-x-auto border border-bunker-800 rounded-lg p-1 w-fit">{["1m", "5m", "15m", "30m", "1h", "4h", "1d"].map(tf => <button key={tf} onClick={() => setTimeframe(tf)} className={`min-h-10 shrink-0 px-3 rounded font-mono text-xs ${timeframe === tf ? "bg-neon-green/15 text-neon-green" : "text-bunker-muted"}`}>{tf}</button>)}</div></header>
    <section className="card border-neon-green/25 bg-gradient-to-br from-neon-green/10 via-bunker-950 to-bunker-950"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="eyebrow text-neon-green">SADE LLM YORUMU</p><p className="mt-1 text-sm text-bunker-muted">M1 · M5 · M15 · M30 · H1 · H4 · D1 verilerini birlikte değerlendirir.</p></div><button onClick={askCommentary} disabled={commentaryLoading} className="ui-button ui-button-primary">{commentaryLoading ? "YORUMLANIYOR..." : "LLM YORUMU AL"}</button></div>{commentary && <div className="mt-4 whitespace-pre-wrap rounded-lg border border-bunker-700 bg-bunker-950/70 p-4 text-sm leading-7 text-slate-200">{commentary.error || commentary.commentary}</div>}</section>
    {!data?.data_ready ? <Card title="VERİ DURUMU"><p className="text-bunker-muted">{error || data?.error || "Veri hazırlanıyor..."}</p></Card> : <><div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4"><Card title="FİYAT"><p className="font-mono text-2xl">₺{value(data.price)}</p></Card><Card title="TREND"><p className="font-mono text-xl text-neon-green">{trend.alignment?.toUpperCase()}</p></Card><Card title="ÖZET"><p className="font-mono text-xl">{data.summary?.toUpperCase()}</p></Card><Card title="ADR KALAN"><p className="font-mono text-xl text-yellow-300">{percent(volatility.remaining_capacity_pct)}</p></Card></div><div className="grid md:grid-cols-3 gap-4"><Card title="OSİLATÖRLER"><div className="space-y-2">{[["RSI", oscillators.rsi_14], ["Stochastic", oscillators.stochastic_k], ["CCI", oscillators.cci_20], ["ADX", oscillators.adx_14], ["MACD", oscillators.macd_histogram], ["Williams %R", oscillators.williams_r]].map(([name, val]) => <div className="flex justify-between text-sm" key={name}><span className="text-bunker-muted">{name}</span><span className="font-mono">{value(val)}</span></div>)}</div></Card><Card title="HAREKETLİ ORTALAMALAR"><div className="grid grid-cols-2 gap-2">{Object.entries(averages).map(([name, val]: any) => <div key={name}><p className="text-xs text-bunker-muted">{name}</p><p className="font-mono text-sm">{value(val)}</p></div>)}</div></Card><Card title="HACİM / MOMENTUM"><div className="grid grid-cols-2 gap-3">{[["Hacim", volume.volume_ratio_20 == null ? "—" : `${value(volume.volume_ratio_20)}x`], ["VWAP", value(volume.vwap)], ["ATR %", percent(volatility.atr_pct)], ["RSI", value(momentum.rsi_14)], ["MACD", value(momentum.macd?.histogram)], ["ADX", value(trend.adx?.adx)]].map(([name, val]) => <div key={name}><p className="text-xs text-bunker-muted">{name}</p><p className="font-mono text-sm">{val}</p></div>)}</div></Card></div></>}
  </div>;
}
