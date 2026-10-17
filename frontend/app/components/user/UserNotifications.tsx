"use client";
import { useCallback, useEffect, useState } from "react";
import { getJSON } from "../../lib/api";
import { useVisibleInterval } from "../../lib/useVisibleInterval";
import SymbolLink from "../SymbolLink";
import { formatPrice, toMs } from "../../lib/format";
import { hitProbLabel, netTargetText, statusLabel, windowEnd, type Tone } from "../../lib/userUi";

type Row = {
  symbol: string;
  price?: number;
  detected_at: number;
  target_pct?: number | null;
  horizon_minutes?: number | null;
  hit_prob_calibrated?: number | null;
  breakeven_hit_prob?: number | null;
  target_net_pct?: number | null;
  status: string;
};
type Filter = "today" | "all" | "hit";

const TONE_CLASS: Record<Tone, string> = {
  good: "bg-neon-green/15 text-neon-green",
  warn: "bg-neon-yellow/15 text-neon-yellow",
  bad: "bg-neon-red/15 text-neon-red",
  wait: "bg-bunker-700 text-white",
  mute: "bg-bunker-700 text-bunker-muted",
};

/** Bugünün tarihi (YYYY-MM-DD), UTC+3. */
function todayTR(): string {
  return new Date(Date.now() + 3 * 3600_000).toISOString().slice(0, 10);
}

function clock(ts: number): string {
  const ms = toMs(ts);
  return ms ? new Date(ms).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" }) : "—";
}

function windowText(r: Row): string {
  const end = windowEnd(r.detected_at, Number(r.horizon_minutes));
  if (statusLabel(r.status).tone === "wait") {
    const left = Math.max(0, Math.ceil((toMs(end) - Date.now()) / 60000));
    return `kalan ${left} dk`;
  }
  return clock(end);
}

/** "%62" (ipucu: başabaş) — kalibre isabet; ham ML olasılığı gösterilmez. */
function ProbText({ r }: { r: Row }) {
  const p = hitProbLabel(r.hit_prob_calibrated, r.breakeven_hit_prob);
  const cls = p.tone === "good" ? "text-neon-green" : p.tone === "warn" ? "text-neon-yellow" : "text-bunker-muted";
  return <span className={cls} title={p.title}>{p.text}</span>;
}

function NetText({ r }: { r: Row }) {
  const t = netTargetText(r.target_net_pct);
  return t ? <span className="ml-1 text-xs text-bunker-muted">({t})</span> : null;
}

function StatusBadge({ status }: { status: string }) {
  const s = statusLabel(status);
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${TONE_CLASS[s.tone]}`}>{s.label}</span>;
}

const FILTERS: { id: Filter; label: string }[] = [
  { id: "today", label: "Bugün" },
  { id: "all", label: "Tümü" },
  { id: "hit", label: "Yalnız hedefe ulaşanlar" },
];

export default function UserNotifications() {
  const [filter, setFilter] = useState<Filter>("today");
  const [rows, setRows] = useState<Row[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const day = filter === "today" ? todayTR() : "all";
    try {
      const d = await getJSON<{ notifications?: Row[] }>(`/api/reports/notifications?limit=200&day=${day}`);
      const list = d?.notifications ?? [];
      setRows(filter === "hit" ? list.filter((r) => r.status === "TAMAMEN BAŞARILI") : list);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Bildirimler yüklenemedi");
    } finally {
      setLoaded(true);
    }
  }, [filter]);
  useVisibleInterval(load, 30_000);
  useEffect(() => { void load(); }, [load]);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Bildirimler</h1>
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Bildirim filtresi">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            role="tab"
            aria-selected={filter === f.id}
            onClick={() => { setLoaded(false); setFilter(f.id); }}
            className={`min-h-[44px] rounded-lg border px-4 text-sm ${filter === f.id ? "border-neon-green bg-neon-green/10 text-neon-green" : "border-bunker-700 text-white"}`}
          >
            {f.label}
          </button>
        ))}
      </div>
      {error && <p role="alert" className="rounded-lg bg-neon-red/10 p-3 text-sm text-neon-red">{error}</p>}
      {loaded && rows.length === 0 && !error ? (
        <div className="card p-4 text-sm text-bunker-muted">Bu filtrede bildirim yok.</div>
      ) : (
        <>
          <div className="space-y-2 md:hidden">
            {rows.map((r, i) => (
              <div key={`${r.symbol}-${r.detected_at}-${i}`} className="card p-3">
                <div className="flex min-h-[44px] items-center justify-between">
                  <SymbolLink symbol={r.symbol} className="font-mono text-base font-semibold text-white hover:text-neon-green" />
                  <StatusBadge status={r.status} />
                </div>
                <p className="text-xs text-bunker-muted">{clock(r.detected_at)}</p>
                <dl className="mt-1 grid grid-cols-2 gap-2 text-sm">
                  <div><dt className="text-bunker-muted">Bildirim fiyatı</dt><dd>{formatPrice(r.price)}</dd></div>
                  <div><dt className="text-bunker-muted">Hedef</dt><dd>{r.target_pct != null ? `%${r.target_pct}` : "—"}<NetText r={r} /></dd></div>
                  <div><dt className="text-bunker-muted">Olasılık</dt><dd><ProbText r={r} /></dd></div>
                  <div><dt className="text-bunker-muted">Ufuk</dt><dd>{r.horizon_minutes ? `${r.horizon_minutes} dk` : "—"}</dd></div>
                  <div><dt className="text-bunker-muted">Pencere bitişi</dt><dd>{windowText(r)}</dd></div>
                </dl>
              </div>
            ))}
          </div>
          <div className="card hidden overflow-x-auto md:block">
            <table className="w-full text-sm">
              <thead className="text-left text-bunker-muted">
                <tr>
                  <th className="p-3 font-medium">Zaman</th>
                  <th className="p-3 font-medium">Sembol</th>
                  <th className="p-3 font-medium">Bildirim fiyatı</th>
                  <th className="p-3 font-medium">Hedef %</th>
                  <th className="p-3 font-medium">Olasılık</th>
                  <th className="p-3 font-medium">Ufuk</th>
                  <th className="p-3 font-medium">Sonuç</th>
                  <th className="p-3 font-medium">Pencere bitişi</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={`${r.symbol}-${r.detected_at}-${i}`} className="border-t border-bunker-700">
                    <td className="p-3">{clock(r.detected_at)}</td>
                    <td className="p-3"><SymbolLink symbol={r.symbol} /></td>
                    <td className="p-3">{formatPrice(r.price)}</td>
                    <td className="p-3">{r.target_pct != null ? `%${r.target_pct}` : "—"}<NetText r={r} /></td>
                    <td className="p-3"><ProbText r={r} /></td>
                    <td className="p-3">{r.horizon_minutes ? `${r.horizon_minutes} dk` : "—"}</td>
                    <td className="p-3"><StatusBadge status={r.status} /></td>
                    <td className="p-3">{windowText(r)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
