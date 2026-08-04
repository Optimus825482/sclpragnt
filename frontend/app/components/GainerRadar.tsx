"use client";
import { useEffect, useState } from "react";
import { API_BASE } from "../lib/api";

type Candidate = { symbol: string; score: number; eligible: boolean; ret_5m: number; ret_1h: number; ret_24h: number; volume_ratio: number; imbalance: number; spread: number; trend: boolean; crsi?: number | null };

export default function GainerRadar() {
  const [items, setItems] = useState<Candidate[]>([]);
  const [added, setAdded] = useState<string[]>([]);
  const [secondsLeft, setSecondsLeft] = useState(30);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let active = true;
    const load = () => {
      setLoading(true);
      fetch(`${API_BASE}/api/radar/gainers`).then((r) => r.json()).then((d) => {
        if (!active) return;
        setItems(d.items || []);
        setAdded(d.auto_added || []);
        setSecondsLeft(30);
        const persist = d.auto_added?.length ? fetch(`${API_BASE}/api/config`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbols: d.symbols }) }) : Promise.resolve();
        return persist.then(() => d.auto_trade ? fetch(`${API_BASE}/api/radar/execute`, { method: "POST" }) : undefined);
      }).catch(() => { if (active) setItems([]); }).finally(() => { if (active) setLoading(false); });
    };
    load();
    const countdown = setInterval(() => setSecondsLeft((value) => value > 0 ? value - 1 : 30), 1000);
    const refresh = setInterval(load, 30000);
    return () => { active = false; clearInterval(countdown); clearInterval(refresh); };
  }, []);
  return <div className="card bg-bunker-950 overflow-hidden">
    <div className="p-4 border-b border-bunker-800 flex justify-between items-center"><div><p className="eyebrow text-neon-green">GAINER RADAR</p><p className="text-xs text-bunker-muted mt-1">%0,5 hedef için devam potansiyeli · public veri · paper</p></div><div className="text-right"><span className="text-xs font-mono text-bunker-muted">YENİLEME <span className="text-neon-green font-bold">00:{String(secondsLeft).padStart(2, "0")}</span></span><p className="text-[10px] text-bunker-muted mt-1">{loading ? "TARANIYOR..." : "CANLI"}</p></div></div>
    {added.length > 0 && <p className="px-4 py-2 text-xs font-mono text-neon-green border-b border-bunker-800">Otomatik eklendi: {added.join(", ")}</p>}
    <div className="overflow-x-auto"><table className="w-full text-left font-mono text-xs"><thead className="text-bunker-muted"><tr><th className="p-3">Sembol</th><th className="p-3">Skor</th><th className="p-3">CRSI</th><th className="p-3">5dk</th><th className="p-3">1s</th><th className="p-3">24s</th><th className="p-3">Hacim</th><th className="p-3">Akış</th><th className="p-3">Durum</th></tr></thead><tbody>{items.map((x) => <tr key={x.symbol} className="border-t border-bunker-800/60"><td className="p-3 font-bold text-white">{x.symbol}</td><td className="p-3 text-neon-green">{x.score}</td><td className="p-3">{x.crsi == null ? "—" : x.crsi.toFixed(1)}</td><td className="p-3">{x.ret_5m.toFixed(2)}%</td><td className="p-3">{x.ret_1h.toFixed(2)}%</td><td className="p-3">{x.ret_24h.toFixed(2)}%</td><td className="p-3">{x.volume_ratio.toFixed(1)}x</td><td className="p-3">{x.imbalance.toFixed(1)}%</td><td className={`p-3 ${x.eligible ? "text-neon-green" : "text-bunker-muted"}`}>{x.eligible ? "ADAY" : "İZLE"}</td></tr>)}</tbody></table>{!items.length && <p className="p-4 text-sm text-bunker-muted">Yeterli canlı mum verisi bekleniyor.</p>}</div>
  </div>;
}
