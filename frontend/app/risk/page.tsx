"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

export default function RiskPage() {
  const [data, setData] = useState<any>(null);
  useEffect(() => { apiFetch("/api/risk/summary").then(setData).catch(() => undefined); }, []);
  if (!data) return <main className="page-shell"><p className="font-mono text-bunker-muted">Risk özeti yükleniyor…</p></main>;
  const cards = [["Açık pozisyon", `${data.open_positions} / ${data.max_positions}`], ["Gerçekleşmiş PnL", `${Number(data.realized_pnl).toFixed(2)} ₺`], ["Bugünkü PnL", `${Number(data.today_pnl).toFixed(2)} ₺`], ["Komisyon", `${Number(data.commission).toFixed(2)} ₺`], ["Ardışık zarar", String(data.consecutive_losses)]];
  return <main className="page-shell"><div className="page-heading"><p className="eyebrow">RİSK MERKEZİ</p><h1>Risk ve Pozisyon Özeti</h1><p className="text-bunker-muted">Paper-trading kayıtlarından hesaplanan görünürlük paneli.</p></div><div className="grid grid-cols-2 md:grid-cols-5 gap-3">{cards.map(([a,b]) => <div className="panel p-4" key={a}><p className="eyebrow">{a}</p><p className="text-xl font-mono mt-2">{b}</p></div>)}</div><div className="panel p-5 mt-5"><h2 className="font-mono text-lg">Risk uyarıları</h2><p className={data.risk_flags.consecutive_loss_streak ? "text-red-400 mt-3" : "text-neon-green mt-3"}>{data.risk_flags.consecutive_loss_streak ? "Ardışık zarar serisi: inceleme gerekli." : "Ardışık zarar eşiği aşılmadı."}</p><p className={data.risk_flags.daily_loss ? "text-amber-400 mt-2" : "text-neon-green mt-2"}>{data.risk_flags.daily_loss ? "Bugünkü PnL negatif." : "Bugünkü PnL negatif değil."}</p></div></main>;
}
