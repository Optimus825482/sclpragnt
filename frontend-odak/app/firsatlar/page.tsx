"use client";

import { useEffect, useMemo, useState } from "react";
import { apiRequest } from "../lib/api";
import { useAuth } from "../lib/auth";
import { usePoll } from "../lib/hooks";
import { formatPct, fmtDateTime } from "../lib/format";
import { baseAsset, toOpportunityView } from "../lib/opportunity";
import { sourceLabel } from "../lib/sources";
import type { MonitoringState, NotificationsResponse } from "../lib/types";
import { Badge, Card, EmptyState, SectionHeader, Skeleton, Tabs } from "../components/ui";

type Tab = "live" | "history";
type LiveRow = { view: ReturnType<typeof toOpportunityView>; kind: string; detectedAt: number | null };

/**
 * FIRSATLAR (tarama) sayfası.
 *   - Üst blok: sistemin ANLIK tespit ettiği adaylar (tek motor beslemesi:
 *     monitoring/state candidates + warm + pulse), her satırda KAYNAK etiketi.
 *   - Alt blok: SAYFALI tarama/bildirim geçmişi (/api/reports/notifications).
 *
 * Not: `/api/reports/notifications` sunucu tarafında `offset` DESTEKLEMEZ
 * (yalnız limit + gün filtresi). Bu yüzden geçmiş, sunucudan genişçe çekilip
 * İSTEMCİDE sayfalanır — kullanıcıya gerçek sayfalama deneyimi verir.
 */
const PAGE_SIZE = 25;

export default function FirsatlarPage() {
  const [tab, setTab] = useState<Tab>("live");
  const { role } = useAuth();
  const [manualBusy, setManualBusy] = useState(false);
  const [manualError, setManualError] = useState<string | null>(null);
  const [manualMessage, setManualMessage] = useState<string | null>(null);
  const [seenCandidates, setSeenCandidates] = useState<Record<string, Record<string, unknown>>>({});
  const monitoring = usePoll<MonitoringState>("/api/monitoring/state", 20_000);
  const pendingSignals = usePoll<NotificationsResponse>(tab === "live" ? "/api/reports/notifications?day=all&limit=400&history_only=true" : null, tab === "live" ? 60_000 : null);

  useEffect(() => {
    const current = monitoring.data;
    if (!current) return;
    const now = Date.now() / 1000;
    setSeenCandidates((previous) => {
      const next: Record<string, Record<string, unknown>> = {};
      for (const [key, candidate] of Object.entries(previous)) {
        const detected = Number(candidate.detected_at ?? candidate.created_at ?? 0);
        const horizon = Number(candidate.horizon_minutes ?? 0);
        if (detected && horizon > 0 && now < detected + horizon * 60 + 120) next[key] = candidate;
      }
      const fresh = [...(current.candidates || []), ...(current.warm || []), ...(current.pulse || [])];
      for (const candidate of fresh) {
        const row = candidate as Record<string, unknown>;
        const symbol = String(row.symbol || "").toUpperCase();
        if (!symbol) continue;
        const horizon = Number(row.horizon_minutes ?? 0);
        if (horizon <= 0) continue;
        const detected = Number(row.detected_at ?? row.created_at ?? now);
        next[`${symbol}:${horizon}`] = { ...row, detected_at: detected };
      }
      return next;
    });
  }, [monitoring.data]);

  async function runManualScan() {
    if (manualBusy) return;
    setManualBusy(true);
    setManualError(null);
    setManualMessage(null);
    try {
      const response = await apiRequest("/api/monitoring/scan", { method: "POST" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body?.detail || body?.error || `Tarama başarısız (HTTP ${response.status})`);
      if (body?.error) throw new Error(String(body.error));
      const scannedAt = Number(body?.scan_at || Date.now() / 1000);
      setSeenCandidates((previous) => {
        const next = { ...previous };
        for (const candidate of body?.candidates || []) {
          const row = candidate as Record<string, unknown>;
          const symbol = String(row.symbol || "").toUpperCase();
          if (!symbol) continue;
          const horizon = Number(row.horizon_minutes ?? 0);
          if (horizon <= 0) continue;
          next[`${symbol}:${horizon}`] = { ...row, detected_at: Number(row.detected_at || scannedAt) };
        }
        return next;
      });
      setManualMessage(`Tarama tamamlandı · ${Number(body?.candidates?.length || 0)} aday bulundu.`);
      monitoring.reload();
      pendingSignals.reload();
    } catch (error) {
      setManualError(error instanceof Error ? error.message : "Manuel tarama başarısız oldu.");
    } finally {
      setManualBusy(false);
    }
  }

  const live = useMemo(() => {
    const m = monitoring.data;
    if (!m) return [];
    const rows: LiveRow[] = [];
    for (const c of m.candidates || []) rows.push({ view: toOpportunityView(c as Record<string, unknown>), kind: "Aday", detectedAt: Number((c as Record<string, unknown>).detected_at ?? (c as Record<string, unknown>).created_at) || null });
    // "Isınıyor" (warm) satırları SEMBOL BAŞINA farklı ufuk profilleriyle gelebilir;
    // aynı sembolü tabloda 3-4 kez tekrarlamak gürültü olur → sembol başına EN
    // YAKIN (warm_proximity en yüksek) olanı tut.
    const warmBest = new Map<string, Record<string, unknown>>();
    for (const w of m.warm || []) {
      const sym = String((w as Record<string, unknown>).symbol ?? "");
      if (!sym) continue;
      const cur = warmBest.get(sym);
      const prox = Number((w as Record<string, unknown>).warm_proximity ?? 0);
      const curProx = cur ? Number(cur.warm_proximity ?? 0) : -Infinity;
      if (!cur || prox > curProx) warmBest.set(sym, w as Record<string, unknown>);
    }
    for (const w of warmBest.values()) rows.push({ view: toOpportunityView(w), kind: "Isınıyor", detectedAt: Number(w.detected_at ?? w.created_at) || null });
    for (const p of m.pulse || []) rows.push({ view: toOpportunityView(p as Record<string, unknown>), kind: "Nabız", detectedAt: Number((p as Record<string, unknown>).detected_at ?? (p as Record<string, unknown>).created_at) || null });
    const currentKeys = new Set(rows.map(({ view }) => `${view.symbol}:${view.horizonMinutes ?? 5}`));
    for (const [key, candidate] of Object.entries(seenCandidates)) {
      if (currentKeys.has(key)) continue;
      rows.push({ view: toOpportunityView(candidate), kind: "Ufuk süresince", detectedAt: Number(candidate.detected_at ?? candidate.created_at) || null });
      currentKeys.add(key);
    }
    const now = Date.now() / 1000;
    for (const n of pendingSignals.data?.notifications || []) {
      const detectedAt = Number(n.detected_at || 0);
      const horizon = Math.max(1, Number(n.horizon_minutes || 5));
      if (!detectedAt || now >= detectedAt + horizon * 60 + 120 || n.status !== "BEKLİYOR") continue;
      const view = toOpportunityView({ ...n, created_at: detectedAt });
      const key = `${view.symbol}:${view.horizonMinutes ?? horizon}`;
      if (!currentKeys.has(key)) rows.push({ view, kind: "Ufuk süresince", detectedAt });
      currentKeys.add(key);
    }
    return rows;
  }, [monitoring.data, pendingSignals.data, seenCandidates]);

  return (
    <div className="space-y-5">
      <SectionHeader
        eyebrow="Fırsatlar"
        title="Tarama & tespit"
        description="Sistemin şu an tespit ettikleri ve geçmiş tarama kayıtları (hangi sistem ürettiğiyle birlikte)."
        actions={
          <div className="flex flex-wrap items-center justify-end gap-2">
            {role === "admin" ? (
              <button type="button" onClick={runManualScan} disabled={manualBusy} className="rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-white disabled:opacity-60">
                {manualBusy ? "Tarama yapılıyor…" : "Şimdi Tara"}
              </button>
            ) : null}
            <Tabs
              items={[
                { id: "live", label: "Anlık Tespitler" },
                { id: "history", label: "Tarama Geçmişi" },
              ]}
              active={tab}
              onChange={(id) => setTab(id as Tab)}
            />
          </div>
        }
      />

      {manualError ? <div role="alert" className="rounded-lg border border-loss/30 bg-loss/5 px-4 py-2 text-sm text-loss">{manualError}</div> : null}
      {manualMessage ? <div role="status" className="rounded-lg border border-gain/30 bg-gain/5 px-4 py-2 text-sm text-gain">{manualMessage}</div> : null}
      {tab === "live" ? <LiveFeed monitoring={monitoring} rows={live} /> : <HistoryTable />}
    </div>
  );
}

function LiveFeed({
  monitoring,
  rows,
}: {
  monitoring: ReturnType<typeof usePoll<MonitoringState>>;
  rows: LiveRow[];
}) {
  if (monitoring.loading && !monitoring.data) return <Skeleton className="h-64" />;
  if (monitoring.error && !monitoring.data)
    return <EmptyState title="Tarama durumu alınamadı" hint={monitoring.error} tone="loss" />;
  if (rows.length === 0)
    return <EmptyState title="Anlık tespit yok" hint="Radar arka planda çalışıyor; uygun aday çıkınca burada görünür." />;

  const kindTone: Record<string, "accent" | "warn" | "gain"> = { Aday: "gain", Isınıyor: "warn", Nabız: "accent" };

  return (
    <Card className="p-4">
      <div className="odak-scroll">
        <table className="w-full min-w-[820px] border-collapse text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wide text-ink-400">
              <th className="pb-2 pr-3 font-medium">Sembol</th>
              <th className="pb-2 pr-3 font-medium">Durum</th>
              <th className="pb-2 pr-3 font-medium">Üreten Sistem</th>
              <th className="pb-2 pr-3 text-right font-medium">Fiyat</th>
              <th className="pb-2 pr-3 text-right font-medium">Değişim</th>
              <th className="pb-2 pr-3 text-right font-medium">Potansiyel</th>
              <th className="pb-2 pr-3 text-right font-medium">Sinyal</th>
              <th className="pb-2 text-right font-medium">Ufuk</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ view, kind }, i) => (
              <tr key={`${view.symbol}-${view.horizonMinutes ?? 5}-${kind}-${i}`} className="border-t border-line">
                <td className="py-2 pr-3">
                  <span className="font-mono font-semibold text-ink-900">{view.base}</span>
                  <span className="text-ink-400"> / TRY</span>
                </td>
                <td className="py-2 pr-3">
                  <Badge tone={kindTone[kind] || "neutral"}>{kind}</Badge>
                </td>
                <td className="py-2 pr-3">
                  <div className="flex flex-wrap gap-1">
                    {view.sources.length ? (
                      view.sources.slice(0, 3).map((s) => (
                        <Badge key={s} tone="accent">
                          {s}
                        </Badge>
                      ))
                    ) : (
                      <span className="text-xs text-ink-400">—</span>
                    )}
                  </div>
                </td>
                <td className="py-2 pr-3 text-right font-mono text-ink-700">{view.price != null ? view.price.toLocaleString("tr-TR", { maximumFractionDigits: 4 }) : "—"}</td>
                <td className={`py-2 pr-3 text-right font-mono ${(view.changePct ?? 0) >= 0 ? "text-gain" : "text-loss"}`}>
                  {formatPct(view.changePct, 2, true)}
                </td>
                <td className="py-2 pr-3 text-right font-mono text-ink-700">{formatPct(view.potentialPct, 1, true)}</td>
                <td className="py-2 pr-3 text-right font-mono text-ink-500">{view.strength != null ? Math.round(view.strength) : "—"}</td>
                <td className="py-2 text-right font-mono text-ink-500">{view.horizonMinutes != null ? `${view.horizonMinutes} dk` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function HistoryTable() {
  const [page, setPage] = useState(0);
  // Geniş çekim (400 kayıt); istemcide sayfalanır.
  const { data, error, loading } = usePoll<NotificationsResponse>("/api/reports/notifications?day=all&limit=400&history_only=true", 60_000);

  const items = data?.notifications || [];
  const pageCount = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const slice = items.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);

  if (loading && !data) return <Skeleton className="h-64" />;
  if (error && !data) return <EmptyState title="Tarama geçmişi alınamadı" hint={error} tone="loss" />;
  if (items.length === 0) return <EmptyState title="Kayıt yok" hint="Henüz tarama/bildirim kaydı oluşmamış." />;

  return (
    <Card className="p-4">
      <div className="odak-scroll">
        <table className="w-full min-w-[900px] border-collapse text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wide text-ink-400">
              <th className="pb-2 pr-3 font-medium">Zaman</th>
              <th className="pb-2 pr-3 font-medium">Sembol</th>
              <th className="pb-2 pr-3 font-medium">Üreten Sistem</th>
              <th className="pb-2 pr-3 text-right font-medium">Skor</th>
              <th className="pb-2 pr-3 text-right font-medium">Fiyat</th>
              <th className="pb-2 pr-3 text-right font-medium">Hedef</th>
              <th className="pb-2 pr-3 text-right font-medium">MFE</th>
              <th className="pb-2 font-medium">Durum</th>
            </tr>
          </thead>
          <tbody>
            {slice.map((n, i) => {
              const srcs = (n.sources || []).map(sourceLabel).filter(Boolean);
              const ok = String(n.status || "").includes("BAŞARILI");
              const bad = String(n.status || "").includes("BAŞARISIZ");
              return (
                <tr key={n.id ?? `${n.symbol}-${i}`} className="border-t border-line">
                  <td className="py-2 pr-3 font-mono text-xs text-ink-500">{fmtDateTime(n.detected_at)}</td>
                  <td className="py-2 pr-3">
                    <span className="font-mono font-semibold text-ink-900">{baseAsset(n.symbol)}</span>
                  </td>
                  <td className="py-2 pr-3">
                    <div className="flex flex-wrap gap-1">
                      {srcs.length ? srcs.slice(0, 3).map((s) => <Badge key={s} tone="accent">{s}</Badge>) : <span className="text-xs text-ink-400">—</span>}
                    </div>
                  </td>
                  <td className="py-2 pr-3 text-right font-mono text-ink-700">{n.score != null ? Math.round(n.score) : "—"}</td>
                  <td className="py-2 pr-3 text-right font-mono text-ink-700">{n.price != null ? Number(n.price).toLocaleString("tr-TR", { maximumFractionDigits: 4 }) : "—"}</td>
                  <td className="py-2 pr-3 text-right font-mono text-ink-700">{formatPct(n.target_pct, 1, true)}</td>
                  <td className="py-2 pr-3 text-right font-mono text-ink-500">{formatPct(n.mfe_pct, 1, true)}</td>
                  <td className="py-2">
                    <Badge tone={ok ? "gain" : bad ? "loss" : "neutral"}>{n.status || "—"}</Badge>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-3 flex items-center justify-between text-xs text-ink-500">
        <span>
          {items.length} kayıt · sayfa {safePage + 1}/{pageCount}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={safePage === 0}
            className="rounded-md border border-line px-3 py-1 hover:border-accent hover:text-accent disabled:opacity-40"
          >
            ← Önceki
          </button>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
            disabled={safePage >= pageCount - 1}
            className="rounded-md border border-line px-3 py-1 hover:border-accent hover:text-accent disabled:opacity-40"
          >
            Sonraki →
          </button>
        </div>
      </div>
    </Card>
  );
}
