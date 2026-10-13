"use client";

import { useMemo, useState } from "react";
import { apiRequest } from "../lib/api";
import { usePoll } from "../lib/hooks";
import { fmtDateTime, formatFixed, formatPrice, formatSignedTL } from "../lib/format";
import { baseAsset } from "../lib/opportunity";
import type { BinanceSettings } from "../lib/types";
import { Badge, Card, EmptyState, SectionHeader, Skeleton } from "../components/ui";
import { downloadCsv, toCsv } from "../lib/csv";

type BinanceFill = {
  id?: number | string; symbol: string; time?: number; price?: number; qty?: number;
  quoteQty?: number; isBuyer?: boolean; commission?: number; commissionAsset?: string;
  basis_price?: number; realized_pnl_try?: number;
};
type BinanceDay = { trades?: BinanceFill[]; count?: number; daily?: { realized_pnl_try?: number; wins?: number; losses?: number } };

type EquityCurve = {
  points: Array<{ t: number; equity: number; symbol: string; pnl: number }>;
  closed_trades: number;
  net_pnl: number;
  wins: number;
  losses: number;
  win_rate: number;
  profit_factor: number | null;
  max_drawdown_try: number;
  expectancy_try: number;
  daily: Array<{ day: string; pnl: number; trades: number }>;
};

type JournalNote = { id: number; symbol: string; strategy_tag: string | null; note: string; created_at: number; updated_at: number };
const PAGE_SIZE = 25;

function todayIstanbul() {
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Istanbul", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const get = (type: string) => parts.find((part) => part.type === type)?.value || "00";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

/** Gerçek Binance TR dolum geçmişi; gün filtresi sunucuya, sayfalama ekrana uygulanır. */
export default function GecmisIslemlerPage() {
  const [date, setDate] = useState(todayIstanbul);
  const [page, setPage] = useState(0);
  const settings = usePoll<BinanceSettings>("/api/binance/settings", 30_000);
  const result = usePoll<BinanceDay>(settings.data?.configured ? `/api/binance/trades-day?date=${date}` : null, 120_000, 30_000);
  const trades = useMemo(() => result.data?.trades || [], [result.data]);
  const pageCount = Math.max(1, Math.ceil(trades.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const visible = trades.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);

  if (settings.loading) return <Skeleton className="h-64" />;
  if (!settings.data?.configured) return <EmptyState title="Binance TR hesabı bağlı değil" hint="Gerçek alım/satım geçmişini görüntülemek için Ayarlar'dan hesabınızı bağlayın." />;

  return <div className="space-y-5">
    <SectionHeader eyebrow="Geçmiş İşlemler" title="Binance TR işlem geçmişi" description="Seçilen günde gerçekleşen gerçek spot alım ve satım dolumları." actions={
      <label className="flex items-center gap-2 text-sm text-ink-500">Gün
        <input type="date" value={date} onChange={(e) => { setDate(e.target.value); setPage(0); }} className="rounded-lg border border-line bg-white px-3 py-2 font-mono text-sm text-ink-900" />
      </label>
    } />

    {result.loading && !result.data ? <Skeleton className="h-64" /> : result.error && !result.data ? <EmptyState title="Binance geçmişi alınamadı" hint={result.error} tone="loss" /> : trades.length === 0 ? <EmptyState title="Bu günde işlem yok" hint="Seçilen tarihte Binance TR hesabında gerçekleşmiş dolum bulunmuyor." /> : <Card className="p-4">
      <div className="mb-3 grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg bg-canvas p-3"><p className="odak-kicker">Dolum</p><p className="mt-1 font-mono font-semibold text-ink-900">{result.data?.count ?? trades.length}</p></div>
        <div className="rounded-lg bg-canvas p-3"><p className="odak-kicker">Günlük Gerçekleşen Net K/Z</p><p className={`mt-1 font-mono font-semibold ${(result.data?.daily?.realized_pnl_try || 0) >= 0 ? "text-gain" : "text-loss"}`}>{formatSignedTL(result.data?.daily?.realized_pnl_try)}</p></div>
        <div className="rounded-lg bg-canvas p-3"><p className="odak-kicker">Sonuç</p><p className="mt-1 font-mono font-semibold text-ink-900">{result.data?.daily?.wins ?? 0} kâr · {result.data?.daily?.losses ?? 0} zarar</p></div>
      </div>
      <div className="odak-scroll"><table className="w-full min-w-[900px] border-collapse text-sm">
        <thead><tr className="text-left text-[11px] uppercase tracking-wide text-ink-400">
          <th className="pb-2 pr-3 font-medium">Zaman</th><th className="pb-2 pr-3 font-medium">Coin</th><th className="pb-2 pr-3 font-medium">Yön</th>
          <th className="pb-2 pr-3 text-right font-medium">Fiyat</th><th className="pb-2 pr-3 text-right font-medium">Miktar</th>
          <th className="pb-2 pr-3 text-right font-medium">Tutar</th><th className="pb-2 pr-3 text-right font-medium">Komisyon</th><th className="pb-2 pr-3 text-right font-medium">Net K/Z</th><th className="pb-2 font-medium">Emir No</th>
        </tr></thead>
        <tbody>{visible.map((trade, i) => {
          const buying = Boolean(trade.isBuyer);
          const pnl = trade.realized_pnl_try;
          const tone = pnl == null ? "text-ink-400" : pnl >= 0 ? "text-gain" : "text-loss";
          return <tr key={`${trade.symbol}-${trade.id ?? i}`} className="border-t border-line">
            <td className="py-2 pr-3 font-mono text-xs text-ink-500">{fmtDateTime(trade.time)}</td>
            <td className="py-2 pr-3 font-mono font-semibold text-ink-900">{baseAsset(trade.symbol)}</td>
            <td className="py-2 pr-3"><Badge tone={buying ? "gain" : "loss"}>{buying ? "AL" : "SAT"}</Badge></td>
            <td className="py-2 pr-3 text-right font-mono text-ink-700">{formatPrice(trade.price)}</td>
            <td className="py-2 pr-3 text-right font-mono text-ink-500">{formatFixed(trade.qty, 6)}</td>
            <td className="py-2 pr-3 text-right font-mono text-ink-700">{formatFixed(trade.quoteQty, 2)}</td>
            <td className="py-2 pr-3 text-right font-mono text-ink-500">{formatFixed(trade.commission, 6)} {trade.commissionAsset || ""}</td>
            <td className={`py-2 pr-3 text-right font-mono ${tone}`}>{formatSignedTL(pnl)}</td>
            <td className="py-2 font-mono text-xs text-ink-400">{trade.id ?? "—"}</td>
          </tr>;
        })}</tbody>
      </table></div>
      <div className="mt-3 flex items-center justify-between text-xs text-ink-500">
        <span>{trades.length} kayıt · sayfa {safePage + 1}/{pageCount}</span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => downloadCsv(
              `binance-islemleri-${date}.csv`,
              toCsv(
                ["zaman", "coin", "yon", "fiyat", "miktar", "tutar", "komisyon", "komisyon_varligi", "net_kz_try", "emir_no"],
                trades.map((trade) => [
                  trade.time ? fmtDateTime(trade.time) : "",
                  baseAsset(trade.symbol),
                  trade.isBuyer ? "ALIS" : "SATIS",
                  trade.price ?? null,
                  trade.qty ?? null,
                  trade.quoteQty ?? null,
                  trade.commission ?? null,
                  trade.commissionAsset || "",
                  trade.realized_pnl_try ?? null,
                  trade.id ?? "",
                ]),
              ),
            )}
            disabled={trades.length === 0}
            className="rounded-md border border-line px-3 py-1 font-semibold text-accent hover:bg-accent-soft disabled:opacity-40"
            title="Bu günün işlemlerini CSV olarak indir"
          >
            ⤓ CSV indir
          </button>
          <button type="button" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={safePage === 0} className="rounded-md border border-line px-3 py-1 hover:border-accent hover:text-accent disabled:opacity-40">← Önceki</button>
          <button type="button" onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))} disabled={safePage >= pageCount - 1} className="rounded-md border border-line px-3 py-1 hover:border-accent hover:text-accent disabled:opacity-40">Sonraki →</button>
        </div>
      </div>
    </Card>}

    <PerformanceSection settingsConfigured={settings.data?.configured} />
    <JournalSection />
  </div>;
}

/** Portföy performans analitiği: equity eğrisi + kâr kalitesi metrikleri (paper). */
function PerformanceSection({ settingsConfigured }: { settingsConfigured?: boolean }) {
  const curve = usePoll<EquityCurve>("/api/portfolio/equity-curve", 60_000);
  const data = curve.data;

  const path = useMemo(() => {
    const points = data?.points || [];
    if (points.length < 2) return null;
    const width = 600;
    const height = 120;
    const equities = points.map((p) => p.equity);
    const min = Math.min(0, ...equities);
    const max = Math.max(0, ...equities);
    const span = max - min || 1;
    const stepX = width / (points.length - 1);
    return points.map((point, i) => `${i === 0 ? "M" : "L"}${(i * stepX).toFixed(1)},${(height - ((point.equity - min) / span) * height).toFixed(1)}`).join(" ");
  }, [data?.points]);

  if (curve.loading && !data) return <Skeleton className="h-48" />;
  if (curve.error && !data) return null;
  if (!data || data.closed_trades === 0) return null;

  const metrics = [
    { label: "Net K/Z (paper)", value: formatSignedTL(data.net_pnl), tone: data.net_pnl >= 0 ? "text-gain" : "text-loss" },
    { label: "Win Rate", value: `%${data.win_rate}`, tone: data.win_rate >= 50 ? "text-gain" : "text-loss" },
    { label: "Profit Factor", value: data.profit_factor != null ? String(data.profit_factor) : "—", tone: (data.profit_factor ?? 0) >= 1 ? "text-gain" : "text-loss" },
    { label: "Max Drawdown", value: formatSignedTL(-data.max_drawdown_try), tone: "text-loss" },
    { label: "Expectancy / işlem", value: formatSignedTL(data.expectancy_try), tone: data.expectancy_try >= 0 ? "text-gain" : "text-loss" },
  ];

  return (
    <Card className="p-4">
      <SectionHeader
        eyebrow="Portföy Performansı"
        title="Equity eğrisi ve kâr kalitesi"
        description={`Kapanan ${data.closed_trades} paper işlemden hesaplanır (salt-okunur). ${settingsConfigured ? "" : "Not: gerçek hesap işlemleri yukarıdaki gün filtresindedir."}`}
      />
      <div className="mt-3 grid gap-3 sm:grid-cols-5">
        {metrics.map((metric) => (
          <div key={metric.label} className="rounded-lg bg-canvas p-3">
            <p className="odak-kicker">{metric.label}</p>
            <p className={`mt-1 font-mono text-lg font-bold ${metric.tone}`}>{metric.value}</p>
          </div>
        ))}
      </div>
      {path && (
        <div className="mt-3">
          <svg viewBox="0 0 600 120" preserveAspectRatio="none" className="h-28 w-full" role="img" aria-label="Kümülatif K/Z eğrisi">
            <line x1="0" y1={120 - (0 / 1) * 120} x2="600" y2="60" stroke="currentColor" className="text-line" strokeWidth="1" strokeDasharray="4 4" />
            <path d={path} fill="none" strokeWidth="2" className={data.net_pnl >= 0 ? "stroke-[color:var(--color-gain)]" : "stroke-[color:var(--color-loss)]"} />
          </svg>
          <p className="mt-1 text-[10px] text-ink-400">{data.wins} kâr · {data.losses} zarar · sıfır çizgisi = başabaş</p>
        </div>
      )}
    </Card>
  );
}

/** İşlem günlüğü: sembole özel scalping disiplin notları (kullanıcıya özel). */
function JournalSection() {
  const journal = usePoll<{ notes: JournalNote[]; count: number }>("/api/journal", 45_000);
  const [symbol, setSymbol] = useState("");
  const [tag, setTag] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "gain" | "loss"; text: string } | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);

  async function addNote() {
    if (!symbol.trim() || !note.trim()) {
      setMessage({ tone: "loss", text: "Sembol ve not zorunludur." });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const response = await apiRequest("/api/journal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: symbol.trim(), note: note.trim(), strategy_tag: tag.trim() || undefined }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body?.detail || `Not kaydedilemedi (${response.status})`);
      setNote("");
      setMessage({ tone: "gain", text: "Not günlüğe eklendi." });
      journal.reload();
    } catch (reason) {
      setMessage({ tone: "loss", text: reason instanceof Error ? reason.message : "Not kaydedilemedi" });
    } finally {
      setBusy(false);
    }
  }

  async function deleteNote(id: number) {
    setBusy(true);
    try {
      const response = await apiRequest(`/api/journal/${id}`, { method: "DELETE" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body?.detail || `Not silinemedi (${response.status})`);
      journal.reload();
    } catch (reason) {
      setMessage({ tone: "loss", text: reason instanceof Error ? reason.message : "Not silinemedi" });
    } finally {
      setBusy(false);
      setDeleting(null);
    }
  }

  const notes = journal.data?.notes || [];

  return (
    <Card className="p-4">
      <SectionHeader
        eyebrow="İşlem Günlüğü"
        title="Disiplin notları"
        description="Pozisyon kararlarını, hataları ve strateji gözlemlerini sembol başına not al; yalnız sen görebilirsin."
      />
      <div className="mt-3 grid gap-2 sm:grid-cols-[130px_150px_1fr_auto]">
        <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} placeholder="Sembol (F_TRY)" aria-label="Sembol" className="rounded-lg border border-line bg-white px-3 py-2 font-mono text-sm text-ink-900 outline-none focus:border-accent" />
        <input value={tag} onChange={(e) => setTag(e.target.value)} placeholder="Strateji etiketi" aria-label="Strateji etiketi" className="rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink-900 outline-none focus:border-accent" />
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Not: örn. erken giriş yaptım, hacim teyidi yoktu…" aria-label="Not" className="rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink-900 outline-none focus:border-accent" />
        <button type="button" disabled={busy} onClick={addNote} className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">Ekle</button>
      </div>
      {message && <p role="status" className={`mt-2 text-xs ${message.tone === "gain" ? "text-gain" : "text-loss"}`}>{message.text}</p>}
      {journal.loading && !journal.data ? <Skeleton className="mt-3 h-20" /> : notes.length === 0 ? (
        <p className="mt-3 text-xs text-ink-400">Henüz günlük notu yok.</p>
      ) : (
        <ul className="mt-3 space-y-1.5">
          {notes.map((item) => (
            <li key={item.id} className="flex items-start justify-between gap-3 rounded-lg bg-canvas px-3 py-2 text-sm">
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-2">
                  <span className="font-mono font-semibold text-ink-900">{item.symbol}</span>
                  {item.strategy_tag && <Badge tone="accent">{item.strategy_tag}</Badge>}
                  <span className="text-[10px] text-ink-400">{fmtDateTime(item.created_at)}</span>
                </p>
                <p className="mt-0.5 break-words text-ink-600">{item.note}</p>
              </div>
              {deleting === item.id ? (
                <div className="flex shrink-0 items-center gap-1.5">
                  <button type="button" disabled={busy} onClick={() => deleteNote(item.id)} className="rounded-md bg-loss px-2 py-1 text-[11px] font-semibold text-white">Onayla</button>
                  <button type="button" onClick={() => setDeleting(null)} className="rounded-md border border-line px-2 py-1 text-[11px] text-ink-500">Vazgeç</button>
                </div>
              ) : (
                <button type="button" onClick={() => setDeleting(item.id)} className="shrink-0 rounded-md border border-line px-2 py-1 text-[11px] text-ink-400 hover:border-loss hover:text-loss">Sil</button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
