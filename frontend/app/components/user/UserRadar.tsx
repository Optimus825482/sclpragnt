"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { API_BASE, apiRequest } from "../../lib/api";
import { formatPrice, toMs } from "../../lib/format";
import { useLiveMessages } from "../../lib/liveSocket";
import { useModalA11y } from "../../lib/useModalA11y";
import { useVisibleInterval } from "../../lib/useVisibleInterval";
import { useWatchPrices } from "../../lib/useWatchPrices";
import { confidenceBadge, pctChange } from "../../lib/userUi";
import SymbolLink from "../SymbolLink";

type TabId = "warm" | "watch" | "history";

type RadarItem = {
  key: string;
  symbol: string;
  price: number | null;
  targetPct: number | null;
  score: number | null;
  horizonMin: number | null;
  message: string | null;
  detectedAt: number | null;
  sentence: string;
};

const TAB_KEY = "scalper:user-radar-tab";
const TABS: { id: TabId; label: string; empty: string }[] = [
  { id: "warm", label: "Isınanlar", empty: "Şu an ısınan coin yok. Sistem tarama yapmaya devam ediyor." },
  { id: "watch", label: "İzlemedekiler", empty: "Şu an izlemede coin yok. Güçlü bir hareket olduğunda burada görünür." },
  { id: "history", label: "Gönderilen bildirimler", empty: "Henüz gönderilmiş bir bildirim yok." },
];

const DEFAULT_REASON = "Sistem bu coinde güçlü bir yükseliş sinyali buldu";
const SCORE_LOG_REF = 25000;

const num = (v: unknown): number | null => {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

/** Ham hız skoru (büyük olabilir) -> 0-100 panel ölçeği (admin Radar ile aynı log haritası). */
function toPanelScore(panel: unknown, raw: unknown): number | null {
  const p = num(panel);
  if (p != null) return p;
  const r = num(raw);
  if (r == null) return null;
  if (r <= 0) return 0;
  if (r <= 100) return r;
  return Math.round((100 * Math.log1p(r)) / Math.log1p(SCORE_LOG_REF) * 10) / 10;
}

function relativeTime(ts: unknown, now: number): string {
  const ms = toMs(ts as number | null);
  if (!ms) return "az önce";
  const sec = Math.max(0, Math.round((now - ms) / 1000));
  if (sec < 60) return "az önce";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} dk önce`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} sa önce`;
  return `${Math.floor(hr / 24)} gün önce`;
}

function firstSentence(text: string | null): string {
  if (!text) return DEFAULT_REASON;
  const t = text.trim();
  if (!t) return DEFAULT_REASON;
  const m = t.match(/^[^.!?\n]+[.!?]?/);
  return (m ? m[0] : t).trim() || DEFAULT_REASON;
}

function mapItems(raw: unknown, kind: "warm" | "watch"): RadarItem[] {
  if (!Array.isArray(raw)) return [];
  const sentence = kind === "warm" ? "Hareketlenme başladı, henüz izlemede değil" : "Sistem bu coini izliyor";
  const out: RadarItem[] = [];
  raw.forEach((it, i) => {
    if (!it || typeof it !== "object") return;
    const v = it as Record<string, unknown>;
    if (typeof v.symbol !== "string" || !v.symbol) return;
    out.push({
      key: `${kind}-${v.symbol}-${i}`,
      symbol: v.symbol,
      price: num(v.price),
      targetPct: num(v.target_pct),
      score: toPanelScore(v.panel_score, v.velocity_score),
      horizonMin: num(v.horizon_minutes),
      message: typeof v.message === "string" ? v.message : null,
      detectedAt: num(v.detected_at),
      sentence,
    });
  });
  return out;
}

function mapHistory(raw: unknown, now: number): RadarItem[] {
  if (!Array.isArray(raw)) return [];
  const out: RadarItem[] = [];
  raw.slice(0, 30).forEach((it, i) => {
    if (!it || typeof it !== "object") return;
    const v = it as Record<string, unknown>;
    if (typeof v.symbol !== "string" || !v.symbol) return;
    out.push({
      key: `history-${v.symbol}-${v.detected_at ?? i}-${i}`,
      symbol: v.symbol,
      price: num(v.price),
      targetPct: num(v.target_pct),
      score: toPanelScore(null, v.score),
      horizonMin: num(v.horizon_minutes),
      message: typeof v.message === "string" ? v.message : null,
      detectedAt: num(v.detected_at),
      sentence: `Bildirim gönderildi · ${relativeTime(v.detected_at, now)}`,
    });
  });
  return out;
}

const toneClass = (b: string) =>
  b === "Yüksek"
    ? "bg-emerald-100 text-emerald-800 border-emerald-300"
    : b === "Orta"
      ? "bg-amber-100 text-amber-800 border-amber-300"
      : "bg-slate-100 text-slate-700 border-slate-300";

function RadarCard({ item, live, onOpen }: { item: RadarItem; live: number | undefined; onOpen: () => void }) {
  const change = pctChange(item.price, live);
  const badge = confidenceBadge(item.score);
  return (
    <li className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex min-h-[44px] items-start justify-between gap-3 p-3">
        <div className="min-w-0">
          <SymbolLink symbol={item.symbol} className="font-bold text-base text-slate-900 hover:underline" />
          <p className="mt-0.5 text-sm text-slate-600">{item.sentence}</p>
        </div>
        <span className={`shrink-0 rounded-full border px-2.5 py-1 text-xs font-semibold ${toneClass(badge)}`}>
          Güven: {badge}
        </span>
      </div>
      <button
        type="button"
        onClick={onOpen}
        className="flex min-h-[44px] w-full items-center justify-between gap-2 rounded-b-2xl border-t border-slate-100 px-3 py-2 text-left text-sm hover:bg-slate-50"
        aria-label={`${item.symbol} detayını aç`}
      >
        <span className="flex flex-wrap gap-x-4 gap-y-1">
          <span className="text-slate-500">Fiyat <b className="text-slate-900">{item.price != null ? formatPrice(item.price) : "—"}</b></span>
          <span className="text-slate-500">Hedef <b className="text-emerald-700">{item.targetPct != null ? `+%${item.targetPct.toFixed(1)}` : "—"}</b></span>
          <span className="text-slate-500">
            Şu an{" "}
            <b className={change == null ? "text-slate-500" : change >= 0 ? "text-emerald-700" : "text-red-700"}>
              {change == null ? "—" : `${change >= 0 ? "+" : ""}${change.toFixed(2)}%`}
            </b>
          </span>
        </span>
        <span aria-hidden className="text-slate-400">Detay ›</span>
      </button>
    </li>
  );
}

function DetailModal({ item, onClose }: { item: RadarItem; onClose: () => void }) {
  const a11y = useModalA11y(true, onClose, `${item.symbol} detayı`);
  const sym = item.symbol.replace(/_/g, "").toUpperCase();
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={a11y.label}
      onKeyDown={a11y.onKeyDown}
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-4"
      onClick={onClose}
    >
      <section
        ref={a11y.ref}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-t-2xl bg-white p-5 text-slate-900 shadow-xl outline-none sm:rounded-2xl"
      >
        <h2 className="text-lg font-bold">{item.symbol}</h2>
        <h3 className="mt-3 text-sm font-semibold text-slate-700">Neden önerildi</h3>
        <p className="mt-1 text-sm text-slate-700">{firstSentence(item.message)}</p>
        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
          <div className="rounded-xl bg-slate-50 p-3">
            <dt className="text-slate-500">Hedef</dt>
            <dd className="font-bold text-emerald-700">{item.targetPct != null ? `+%${item.targetPct.toFixed(1)}` : "—"}</dd>
          </div>
          <div className="rounded-xl bg-slate-50 p-3">
            <dt className="text-slate-500">Ufuk</dt>
            <dd className="font-bold">{item.horizonMin != null ? `${Math.round(item.horizonMin)} dk` : "—"}</dd>
          </div>
        </dl>
        <div className="mt-5 flex gap-3">
          <Link
            href={`/charts?symbol=${encodeURIComponent(sym)}`}
            className="flex min-h-[44px] flex-1 items-center justify-center rounded-xl bg-emerald-600 px-4 text-sm font-semibold text-white hover:bg-emerald-700"
          >
            Grafikte gör
          </Link>
          <button
            type="button"
            onClick={onClose}
            className="min-h-[44px] rounded-xl border border-slate-300 px-4 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            Kapat
          </button>
        </div>
      </section>
    </div>
  );
}

export default function UserRadar() {
  const [tab, setTab] = useState<TabId>("warm");
  const [warm, setWarm] = useState<RadarItem[] | null>(null);
  const [watch, setWatch] = useState<RadarItem[] | null>(null);
  const [history, setHistory] = useState<RadarItem[] | null>(null);
  const [error, setError] = useState(false);
  const [selected, setSelected] = useState<RadarItem | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    try {
      const saved = window.localStorage.getItem(TAB_KEY);
      if (saved === "warm" || saved === "watch" || saved === "history") setTab(saved);
    } catch {
      /* localStorage yok */
    }
    return () => {
      mounted.current = false;
    };
  }, []);

  const selectTab = (id: TabId) => {
    setTab(id);
    try {
      window.localStorage.setItem(TAB_KEY, id);
    } catch {
      /* yok sayılır */
    }
  };

  const load = useCallback(async () => {
    try {
      const [sRes, hRes] = await Promise.all([
        apiRequest(`${API_BASE}/api/monitoring/state`, { cache: "no-store" }),
        apiRequest(`${API_BASE}/api/monitoring/notifications`, { cache: "no-store" }),
      ]);
      if (!mounted.current) return;
      if (sRes.ok) {
        const s = await sRes.json();
        if (!mounted.current) return;
        setWarm(mapItems(s?.warm, "warm"));
        setWatch(mapItems(s?.watchlist, "watch"));
      }
      if (hRes.ok) {
        const h = await hRes.json();
        if (!mounted.current) return;
        setHistory(mapHistory(h?.history, Date.now()));
      }
      setError(!sRes.ok && !hRes.ok);
    } catch {
      if (mounted.current) setError(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);
  useVisibleInterval(() => void load(), 30_000);

  const timerRef = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (timerRef.current != null) window.clearTimeout(timerRef.current);
    },
    [],
  );
  const onLive = useCallback(
    (m: { type: string }) => {
      if (m?.type !== "monitoring_alert" || timerRef.current != null) return;
      timerRef.current = window.setTimeout(() => {
        timerRef.current = null;
        void load();
      }, 2500);
    },
    [load],
  );
  useLiveMessages(onLive, ["monitoring_alert"]);

  const lists: Record<TabId, RadarItem[] | null> = { warm, watch, history };
  const items = lists[tab];
  const symbols = (items ?? []).map((i) => i.symbol);
  const prices = useWatchPrices(symbols);
  const current = TABS.find((t) => t.id === tab)!;

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-4">
      <h1 className="text-xl font-bold text-slate-900">Radar</h1>
      <div role="tablist" aria-label="Radar bölümleri" className="mt-3 flex gap-2 overflow-x-auto pb-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`radar-tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls="radar-panel"
            onClick={() => selectTab(t.id)}
            className={`min-h-[44px] shrink-0 rounded-full border px-4 text-sm font-semibold ${
              tab === t.id ? "border-emerald-600 bg-emerald-600 text-white" : "border-slate-300 bg-white text-slate-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="radar-panel" aria-labelledby={`radar-tab-${tab}`} className="mt-3">
        {items == null ? (
          <p className="py-8 text-center text-sm text-slate-500">
            {error ? "Veriler şu an alınamıyor. Biraz sonra tekrar denenecek." : "Yükleniyor…"}
          </p>
        ) : items.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-slate-300 bg-white py-8 text-center text-sm text-slate-600">
            {current.empty}
          </p>
        ) : (
          <ul className="space-y-3">
            {items.map((it) => (
              <RadarCard key={it.key} item={it} live={prices[it.symbol.toUpperCase()]} onOpen={() => setSelected(it)} />
            ))}
          </ul>
        )}
      </div>
      {selected && <DetailModal item={selected} onClose={() => setSelected(null)} />}
    </main>
  );
}
