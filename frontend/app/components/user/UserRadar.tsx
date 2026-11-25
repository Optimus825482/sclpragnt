"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { API_BASE, apiRequest } from "../../lib/api";
import { formatPrice, toMs } from "../../lib/format";
import { useLiveMessages } from "../../lib/liveSocket";
import { useModalA11y } from "../../lib/useModalA11y";
import { useVisibleInterval } from "../../lib/useVisibleInterval";
import { useWatchPrices } from "../../lib/useWatchPrices";
import { SCORE_LABEL, SCORE_TOOLTIP, confidenceBadge, hitProbLabel, netTargetText, pctChange } from "../../lib/userUi";
import SymbolLink from "../SymbolLink";
import TopGainersList from "../TopGainersList";
import SuperScanList from "../SuperScanList";
import { RadarScanLogButton } from "../admin/RadarScanLogModal";

// 2026-10-17 (basit arayüz): "Isınanlar" sekmesi kaldırıldı — kullanıcıyı karıştırıyordu;
// yalnız izlemedekiler ve gönderilen bildirimler gösterilir.
// 2026-11-25 (kullanıcı isteği): MA kesişim gösterimleri kaldırıldı — radar
// sayfasında MA BUY kartı ve "H4 kesişimleri" sekmesi yok.
type TabId = "watch" | "history" | "gainers" | "super";

type RadarItem = {
  key: string;
  symbol: string;
  price: number | null;
  targetPct: number | null;
  score: number | null;
  hitProb: number | null;
  breakeven: number | null;
  netTargetPct: number | null;
  horizonMin: number | null;
  message: string | null;
  detectedAt: number | null;
  sentence: string;
};

const TAB_KEY = "scalper:user-radar-tab";
const TABS: { id: TabId; label: string; empty: string }[] = [
  { id: "watch", label: "İzlemedekiler", empty: "Şu an izlemede coin yok. Güçlü bir hareket olduğunda burada görünür." },
  { id: "history", label: "Gönderilen bildirimler", empty: "Henüz gönderilmiş bir bildirim yok." },
  { id: "gainers", label: "Yükselenler", empty: "Şu an yükselen çift yok." },
  { id: "super", label: "Süper Tarama", empty: "Kalite kapılarını geçen aday yok." },
];

function readRadarTab(): TabId {
  try {
    if (typeof window !== "undefined") {
      const saved = window.localStorage.getItem(TAB_KEY);
      return TABS.find((item) => item.id === saved)?.id ?? "watch";
    }
  } catch {
    // Depolama kapalıysa ilk sekme açılır.
  }
  return "watch";
}

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

function mapItems(raw: unknown, kind: "warm" | "watch"): RadarItem[] {  // "warm" türü yalnız geriye uyum için
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
      hitProb: num(v.hit_prob_calibrated),
      breakeven: num(v.breakeven_hit_prob),
      netTargetPct: num(v.target_net_pct),
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
      hitProb: num(v.hit_prob_calibrated),
      breakeven: num(v.breakeven_hit_prob),
      netTargetPct: num(v.target_net_pct),
      horizonMin: num(v.horizon_minutes),
      message: typeof v.message === "string" ? v.message : null,
      detectedAt: num(v.detected_at),
      sentence: `Bildirim gönderildi · ${relativeTime(v.detected_at, now)}`,
    });
  });
  return out;
}

// Skor bir hareket ŞİDDETİdir (iyi/kötü değil) -> yeşil/sarı verilmez.
const toneClass = (b: string) =>
  b === "Çok hızlı"
    ? "bg-sky-400/10 text-sky-500 border-sky-400"
    : "bg-bunker-950 text-bunker-muted border-bunker-700";

function RadarCard({ item, live, onOpen }: { item: RadarItem; live: number | undefined; onOpen: () => void }) {
  const change = pctChange(item.price, live);
  const badge = confidenceBadge(item.score);
  const prob = hitProbLabel(item.hitProb, item.breakeven);
  const probClass = prob.tone === "good" ? "text-neon-green" : prob.tone === "warn" ? "text-neon-yellow" : "text-bunker-muted";
  const net = netTargetText(item.netTargetPct);
  return (
    <li className="rounded-2xl border border-bunker-800 bg-white shadow-sm">
      <div className="flex min-h-[44px] items-start justify-between gap-3 p-3">
        <div className="min-w-0">
          <SymbolLink symbol={item.symbol} className="font-bold text-base text-white hover:underline" />
          <p className="mt-0.5 text-sm text-bunker-muted">{item.sentence}</p>
        </div>
        <span className={`shrink-0 rounded-full border px-2.5 py-1 text-xs font-semibold ${toneClass(badge)}`} title={SCORE_TOOLTIP}>
          Hareket: {badge}
        </span>
      </div>
      <button
        type="button"
        onClick={onOpen}
        className="flex min-h-[44px] w-full items-center justify-between gap-2 rounded-b-2xl border-t border-bunker-800 px-3 py-2 text-left text-sm hover:bg-bunker-950"
        aria-label={`${item.symbol} detayını aç`}
      >
        <span className="flex flex-wrap gap-x-4 gap-y-1">
          <span className="text-bunker-muted">Fiyat <b className="text-white">{item.price != null ? formatPrice(item.price) : "—"}</b></span>
          <span className="text-bunker-muted">Hedef <b className="text-neon-green">{item.targetPct != null ? `+%${item.targetPct.toFixed(1)}` : "—"}</b>{net && <span className="text-xs"> ({net})</span>}</span>
          <span className="text-bunker-muted" title={prob.title}>Olasılık <b className={probClass}>{prob.text}</b></span>
          <span className="text-bunker-muted">
            Şu an{" "}
            <b className={change == null ? "text-bunker-muted" : change >= 0 ? "text-neon-green" : "text-neon-red"}>
              {change == null ? "—" : `${change >= 0 ? "+" : ""}${change.toFixed(2)}%`}
            </b>
          </span>
        </span>
        <span aria-hidden className="text-bunker-muted">Detay ›</span>
      </button>
    </li>
  );
}

function DetailModal({ item, onClose }: { item: RadarItem; onClose: () => void }) {
  const a11y = useModalA11y(true, onClose, `${item.symbol} detayı`);
  const sym = item.symbol.replace(/_/g, "").toUpperCase();
  const prob = hitProbLabel(item.hitProb, item.breakeven);
  const net = netTargetText(item.netTargetPct);
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
        className="w-full max-w-md rounded-t-2xl bg-white p-5 text-white shadow-xl outline-none sm:rounded-2xl"
      >
        <h2 className="text-lg font-bold">{item.symbol}</h2>
        <h3 className="mt-3 text-sm font-semibold text-bunker-muted">Neden önerildi</h3>
        <p className="mt-1 text-sm text-bunker-muted">{firstSentence(item.message)}</p>
        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
          <div className="rounded-xl bg-bunker-950 p-3">
            <dt className="text-bunker-muted">Hedef</dt>
            <dd className="font-bold text-neon-green">{item.targetPct != null ? `+%${item.targetPct.toFixed(1)}` : "—"}</dd>
            {net && <dd className="text-xs text-bunker-muted">{net}</dd>}
          </div>
          <div className="rounded-xl bg-bunker-950 p-3">
            <dt className="text-bunker-muted">Ufuk</dt>
            <dd className="font-bold">{item.horizonMin != null ? `${Math.round(item.horizonMin)} dk` : "—"}</dd>
          </div>
          <div className="rounded-xl bg-bunker-950 p-3" title={SCORE_TOOLTIP}>
            <dt className="text-bunker-muted">{SCORE_LABEL}</dt>
            <dd className="font-bold">{item.score != null ? Math.round(item.score) : "—"}</dd>
          </div>
          <div className="rounded-xl bg-bunker-950 p-3" title={prob.title}>
            <dt className="text-bunker-muted">Olasılık</dt>
            <dd className={`font-bold ${prob.tone === "good" ? "text-neon-green" : prob.tone === "warn" ? "text-neon-yellow" : "text-bunker-muted"}`}>{prob.text}</dd>
          </div>
        </dl>
        <div className="mt-5 flex gap-3">
          <Link
            href={`/charts?symbol=${encodeURIComponent(sym)}`}
            className="flex min-h-[44px] flex-1 items-center justify-center rounded-xl bg-neon-green px-4 text-sm font-semibold text-white hover:bg-neon-greenHover"
          >
            Grafikte gör
          </Link>
          <button
            type="button"
            onClick={onClose}
            className="min-h-[44px] rounded-xl border border-bunker-700 px-4 text-sm font-semibold text-bunker-muted hover:bg-bunker-950"
          >
            Kapat
          </button>
        </div>
      </section>
    </div>
  );
}

export default function UserRadar() {
  const [tab, setTab] = useState<TabId>(readRadarTab);
  const [focusedTab, setFocusedTab] = useState<TabId | null>(null);
  const radarId = useId();
  const [watch, setWatch] = useState<RadarItem[] | null>(null);
  const [history, setHistory] = useState<RadarItem[] | null>(null);
  const [errorTab, setErrorTab] = useState<TabId | null>(null);
  const [selected, setSelected] = useState<RadarItem | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const timerRef = useRef<number | null>(null);
  const listTab = tab === "watch" || tab === "history" ? tab : null;

  const selectTab = (id: TabId) => {
    setTab(id);
    try {
      window.localStorage.setItem(TAB_KEY, id);
    } catch {
      /* yok sayılır */
    }
  };

  const load = useCallback(async () => {
    if (!listTab || document.hidden || requestRef.current) return;
    const request = new AbortController();
    requestRef.current = request;
    const path = listTab === "watch" ? "state" : "notifications";
    try {
      const response = await apiRequest(`${API_BASE}/api/monitoring/${path}`, { signal: request.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (request.signal.aborted) return;
      if (listTab === "watch") setWatch(mapItems(data?.watchlist, "watch"));
      else setHistory(mapHistory(data?.history, Date.now()));
      setErrorTab((previous) => previous === listTab ? null : previous);
    } catch {
      if (!request.signal.aborted) setErrorTab(listTab);
    } finally {
      if (requestRef.current === request) requestRef.current = null;
    }
  }, [listTab]);

  useEffect(() => {
    void load();
    return () => {
      requestRef.current?.abort();
      requestRef.current = null;
      if (timerRef.current != null) window.clearTimeout(timerRef.current);
      timerRef.current = null;
    };
  }, [load]);
  useVisibleInterval(load, listTab ? 30_000 : null);

  const onLive = useCallback(
    (m: { type: string }) => {
      if (!listTab || document.hidden || m?.type !== "monitoring_alert" || timerRef.current != null) return;
      timerRef.current = window.setTimeout(() => {
        timerRef.current = null;
        void load();
      }, 2500);
    },
    [listTab, load],
  );
  useLiveMessages(onLive, ["monitoring_alert"]);

  const lists: Record<TabId, RadarItem[] | null> = { watch, history, gainers: [], super: [] };
  const items = lists[tab];
  const symbols = (items ?? []).map((i) => i.symbol);
  const prices = useWatchPrices(symbols);
  const current = TABS.find((t) => t.id === tab)!;

  return (
    <section aria-labelledby={`${radarId}-title`} className="mx-auto w-full max-w-2xl px-4 py-4">
      <div className="flex items-center justify-between gap-2">
        <h1 id={`${radarId}-title`} className="text-xl font-bold text-white">Radar</h1>
        <RadarScanLogButton />
      </div>
      {/* 2026-10-18: rejim bandı kaldırıldı — kalkan rozet modunda (RADAR_SHIELD_MODE=badge) bildirimler durmaz;
          durum bildirim kartındaki "BTC rejim" rozetiyle gösterilir. */}
      <div
        role="tablist"
        aria-label="Radar bölümleri"
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget)) setFocusedTab(null);
        }}
        className="mt-3 flex gap-2 overflow-x-auto pb-1"
      >
        {TABS.map((t, index) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`${radarId}-tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`${radarId}-panel-${t.id}`}
            tabIndex={(focusedTab ?? tab) === t.id ? 0 : -1}
            onFocus={() => setFocusedTab(t.id)}
            onClick={() => selectTab(t.id)}
            onKeyDown={(event) => {
              let next: number;
              switch (event.key) {
                case "ArrowLeft": next = (index + TABS.length - 1) % TABS.length; break;
                case "ArrowRight": next = (index + 1) % TABS.length; break;
                case "Home": next = 0; break;
                case "End": next = TABS.length - 1; break;
                default: return;
              }
              event.preventDefault();
              document.getElementById(`${radarId}-tab-${TABS[next].id}`)?.focus();
            }}
            className={`min-h-[44px] shrink-0 rounded-full border px-4 text-sm font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-3px] focus-visible:outline-sky-600 ${
              tab === t.id ? "border-neon-green bg-neon-green text-white" : "border-bunker-700 bg-white text-bunker-muted"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {TABS.filter((t) => t.id !== tab).map((t) => (
        <div key={t.id} role="tabpanel" id={`${radarId}-panel-${t.id}`} aria-labelledby={`${radarId}-tab-${t.id}`} hidden />
      ))}
      <div role="tabpanel" id={`${radarId}-panel-${tab}`} aria-labelledby={`${radarId}-tab-${tab}`} tabIndex={0} className="mt-3">
        {tab === "super" ? (
          <SuperScanList />
        ) : tab === "gainers" ? (
          <TopGainersList />
        ) : items == null ? (
          <p className="py-8 text-center text-sm text-bunker-muted">
            {errorTab === tab ? "Veriler şu an alınamıyor. Biraz sonra tekrar denenecek." : "Yükleniyor…"}
          </p>
        ) : items.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-bunker-700 bg-white py-8 text-center text-sm text-bunker-muted">
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
    </section>
  );
}
