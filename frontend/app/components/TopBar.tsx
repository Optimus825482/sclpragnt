"use client";
import { usePathname } from "next/navigation";

const labels: Record<string, string> = { "/": "Canlı terminal", "/chat": "Chat merkezi", "/portfolio": "Portföy yönetimi", "/reports": "Raporlar", "/memory": "LLM hafızası", "/backtest": "Backtest", "/charts": "Grafik", "/symbol-analysis": "Sembol analizi", "/settings": "Ayarlar" };

export default function TopBar() {
  const pathname = usePathname();
  return <div className="topbar"><div><p className="topbar-kicker">SCALPERAGENT · PAPER TRADING</p><p className="topbar-title">{labels[pathname] || "Scalper Agent"}</p></div><div className="topbar-status"><span className="status-dot" /> CANLI PUBLIC DATA</div></div>;
}
