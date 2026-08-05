"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

export default function StrategyComparisonPage() {
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => { apiFetch("/api/strategies/comparison").then(x => setRows(x.strategies || [])).catch(() => undefined); }, []);
  return <main className="page-shell"><div className="page-heading"><p className="eyebrow">STRATEJİLER</p><h1>Strateji Karşılaştırma</h1><p className="text-bunker-muted">Komisyon sonrası gerçekleşmiş performans ve timeout görünümü.</p></div><div className="panel overflow-x-auto"><table className="data-table"><thead><tr>{["Strateji","İşlem","Başarı","Net PnL","Komisyon","Ort. PnL","Ort. Süre","Timeout","Profit factor"].map(x => <th key={x}>{x}</th>)}</tr></thead><tbody>{rows.map(r => <tr key={r.strategy}><td>{r.strategy}</td><td>{r.trades}</td><td>%{Number(r.win_rate).toFixed(1)}</td><td className={r.net_pnl >= 0 ? "text-neon-green" : "text-red-400"}>{Number(r.net_pnl).toFixed(2)} ₺</td><td>{Number(r.commission).toFixed(2)} ₺</td><td>{Number(r.avg_pnl).toFixed(2)} ₺</td><td>{Math.round(r.avg_hold_seconds / 60)} dk</td><td>{r.timeouts}</td><td>{r.profit_factor == null ? "—" : Number(r.profit_factor).toFixed(2)}</td></tr>)}</tbody></table>{!rows.length && <p className="p-5 text-bunker-muted">Henüz kapanmış işlem bulunmuyor.</p>}</div></main>;
}
