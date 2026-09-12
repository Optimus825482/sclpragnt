"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { formatTL } from "../lib/format";

// H-25: kâr yeşil, zarar kırmızı, bilinmeyen/başabaş nötr (0'ı yeşile boyamak
// yasak — proje kuralı: veri yok = nötr).
const tone = (v: unknown) => {
  if (v == null || v === "") return "text-bunker-muted";
  const n = Number(v);
  if (!Number.isFinite(n)) return "text-bunker-muted";
  return n > 0 ? "text-neon-green" : n < 0 ? "text-neon-red" : "text-bunker-muted";
};

export default function RiskPage() {
  const [data, setData] = useState<any>(null);
  useEffect(() => { apiFetch("/api/risk/summary").then(setData).catch(() => undefined); }, []);
  if (!data) return <main className="page-shell"><p className="font-mono text-bunker-muted">Risk özeti yükleniyor…</p></main>;
  // H-31: `risk_flags` null ise sayfa çöküyordu; PnL alanları da NaN basabiliyordu.
  const flags = data.risk_flags || {};
  // H-15/H-25: TL biçimi TEK kaynaktan (`lib/format`; ₺ önek, 2 ondalık,
  // null → "—") ve K/Z kartları kâr/zarar rengini uygular.
  const cards: Array<[string, string, string]> = [
    ["Açık pozisyon", `${data.open_positions ?? "—"} / ${data.max_positions ?? "—"}`, ""],
    ["Gerçekleşmiş PnL", formatTL(data.realized_pnl), tone(data.realized_pnl)],
    ["Bugünkü PnL", formatTL(data.today_pnl), tone(data.today_pnl)],
    ["Komisyon", formatTL(data.commission), ""],
    ["Ardışık zarar", String(data.consecutive_losses ?? "—"), ""],
  ];
  return <main className="page-shell"><div className="page-heading"><p className="eyebrow">RİSK MERKEZİ</p><h1>Risk ve Pozisyon Özeti</h1><p className="text-bunker-muted">Paper-trading kayıtlarından hesaplanan görünürlük paneli.</p></div><div className="grid grid-cols-2 md:grid-cols-5 gap-3">{cards.map(([a, b, t]) => <div className="panel p-4" key={a}><p className="eyebrow">{a}</p><p className={`text-xl font-mono mt-2 ${t}`}>{b}</p></div>)}</div><div className="panel p-5 mt-5"><h2 className="font-mono text-lg">Risk uyarıları</h2><p className={flags.consecutive_loss_streak ? "text-red-400 mt-3" : "text-neon-green mt-3"}>{flags.consecutive_loss_streak ? "Ardışık zarar serisi: inceleme gerekli." : "Ardışık zarar eşiği aşılmadı."}</p><p className={flags.daily_loss ? "text-amber-400 mt-2" : "text-neon-green mt-2"}>{flags.daily_loss ? "Bugünkü PnL negatif." : "Bugünkü PnL negatif değil."}</p></div></main>;
}
