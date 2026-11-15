"use client";

// Sinyal İzleme (2026-11-10)
//
// Otonom paper kararlarının ARKASINDAKİ ölçülmüş kanıtı ve canlı filtre
// davranışını tek ekranda gösterir. Amaç: "bu parametreler canlıda ne yapıyor?"
// sorusunu panelden cevaplanabilir kılmak.
//
// Bölümler:
//   1) AKTİF PARAMETRELER — panelde geçerli değerler + ölçülmüş olan
//   2) CANLI FİLTRE SAYAÇLARI — son 24s aday / ATR'de elenen / geçen
//   3) AKIŞ TAZELİĞİ — son aday ne zaman geldi ("BAYAT" uyarısı)
//   4) CANLI SONUÇLAR — son N gün win rate, ort. kazanç/kayıp, çıkış nedeni
//   5) ÖLÇÜLMÜŞ KANIT TABLOSU — 15 hipotez, uygulandı / korundu / reddedildi
//
// Veri: GET /api/signal-insights/overview | /evidence | /outcomes

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { Card, Badge, Button, StatCard } from "../components/ui";

type Params = {
  min_atr_pct: number | null;
  min_oi_change_pct: number | null;
  oi_window_min: number | null;
  max_sl_tp_ratio: number | null;
  trailing_enabled: boolean;
  trailing_trigger_pct: number | null;
  trailing_gap_pct: number | null;
};

type Filters = {
  window_hours: number;
  candidates: number | null;
  with_atr_pct: number | null;
  avg_atr_pct: number | null;
  atr_rejected: number | null;
  with_oi: number | null;
  oi_rejected: number | null;
  passed: number | null;
  error: string | null;
};

type Freshness = { last_candidate_at: number | null; age_sec: number | null; total: number | null };

type Evidence = {
  id: string;
  name: string;
  status: "applied" | "kept" | "rejected";
  summary: string;
  detail: string;
  source: string;
  param: string | null;
};

type Outcome = {
  trades: number;
  wins: number;
  win_rate: number | null;
  avg_pnl_pct: number | null;
  avg_win_pct: number | null;
  avg_loss_pct: number | null;
};

const fmt = (v: number | null | undefined, digits = 2, suffix = "") =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : `${v.toFixed(digits)}${suffix}`;

const STATUS_META: Record<string, { label: string; tone: "positive" | "info" | "negative" }> = {
  applied: { label: "UYGULANDI", tone: "positive" },
  kept: { label: "KORUNDU", tone: "info" },
  rejected: { label: "REDDEDİLDİ", tone: "negative" },
};

function ageLabel(sec: number | null): string {
  if (sec === null) return "—";
  if (sec < 120) return `${Math.round(sec)} sn önce`;
  if (sec < 7200) return `${Math.round(sec / 60)} dk önce`;
  return `${Math.round(sec / 3600)} saat önce`;
}

export default function SignalInsightsPage() {
  const [overview, setOverview] = useState<any>(null);
  const [evidence, setEvidence] = useState<any>(null);
  const [outcomes, setOutcomes] = useState<any>(null);
  const [days, setDays] = useState(7);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [ov, ev, oc] = await Promise.all([
        apiFetch("/api/signal-insights/overview"),
        apiFetch("/api/signal-insights/evidence"),
        apiFetch(`/api/signal-insights/outcomes?days=${days}`),
      ]);
      setOverview(ov);
      setEvidence(ev);
      setOutcomes(oc);
    } catch (e: any) {
      setError(e?.message || "Yüklenemedi");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    void load();
  }, [load]);

  const params: Params | null = overview?.params ?? null;
  const filters: Filters | null = overview?.filters_24h ?? null;
  const fresh: Freshness | null = overview?.freshness ?? null;
  const outcome: Outcome | null = outcomes?.summary ?? null;

  const stale = fresh?.age_sec !== null && fresh?.age_sec !== undefined && fresh.age_sec > 3600;

  return (
    <div className="mx-auto w-full max-w-6xl space-y-5 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Sinyal İzleme</h1>
          <p className="text-sm text-[var(--muted)]">
            Ölçülmüş kanıt + canlı filtre davranışı + işlem sonuçları
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm"
          >
            <option value={1}>1 gün</option>
            <option value={7}>7 gün</option>
            <option value={30}>30 gün</option>
            <option value={90}>90 gün</option>
          </select>
          <Button onClick={() => void load()} disabled={loading}>
            {loading ? "Yükleniyor…" : "Yenile"}
          </Button>
        </div>
      </div>

      {error && (
        <Card className="border-red-500/40">
          <div className="text-sm text-red-400">Hata: {error}</div>
        </Card>
      )}

      {/* 1) AKTİF PARAMETRELER */}
      <Card>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold">Aktif Parametreler</h2>
          <span className="text-xs text-[var(--muted)]">paneldan değiştirilebilir</span>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          <StatCard label="ATR tabanı" value={fmt(params?.min_atr_pct, 2, "%")}
            detail="altında aday elenir" />
          <StatCard label="OI eşiği" value={fmt(params?.min_oi_change_pct, 2, "%")}
            detail={`${fmt(params?.oi_window_min, 0)} dk pencerede`} />
          <StatCard label="SL/TP oranı" value={fmt(params?.max_sl_tp_ratio, 2)}
            detail="yüksekse SL kısalır" />
          <StatCard label="Trailing" value={params?.trailing_enabled ? "AÇIK" : "KAPALI"}
            detail={`tetik ${fmt(params?.trailing_trigger_pct, 1, "%")} / gap ${fmt(params?.trailing_gap_pct, 2, "%")}`} />
        </div>
        {params && Number(params.min_oi_change_pct) === 0 && (
          <div className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-300">
            OI eşiği şu an <b>0 (kapalı)</b>. Ölçülen değer 1,2% —
            Ayarlar → Otonom Paper bölümünden açabilirsin.
          </div>
        )}
      </Card>

      {/* 2) CANLI FİLTRE SAYAÇLARI */}
      <Card>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold">Filtre Sayaçları (son {filters?.window_hours ?? 24} saat)</h2>
          {filters?.error && <Badge tone="warning">kısmi veri</Badge>}
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <StatCard label="Aday" value={filters?.candidates ?? "—"} />
          <StatCard label="ATR'de elendi" value={filters?.atr_rejected ?? "—"}
            tone={(filters?.atr_rejected ?? 0) > 0 ? "warning" : "default"} />
          <StatCard label="Geçen" value={filters?.passed ?? "—"} tone="positive" />
          <StatCard label="Ort. ATR" value={fmt(filters?.avg_atr_pct, 2, "%")} />
          <StatCard label="OI'de elendi" value="ölçülemiyor"
            detail="DB'de kayıtlı değil" />
        </div>
        {overview?.note && (
          <p className="mt-2 text-xs text-[var(--muted)]">{overview.note}</p>
        )}
      </Card>

      {/* 3) AKIŞ TAZELİĞİ */}
      <Card className={stale ? "border-amber-500/40" : ""}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-base font-semibold">Akış Tazeliği</h2>
            <p className="text-xs text-[var(--muted)]">
              son aday: {ageLabel(fresh?.age_sec ?? null)}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {stale && <Badge tone="warning">BAYAT — 1 saatten eski</Badge>}
            <Badge tone="neutral">toplam {(fresh?.total ?? 0).toLocaleString("tr-TR")} aday</Badge>
          </div>
        </div>
      </Card>

      {/* 4) CANLI SONUÇLAR */}
      <Card>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold">Canlı İşlem Sonuçları (son {days} gün)</h2>
          {outcomes?.error && <Badge tone="warning">kısmi veri</Badge>}
        </div>
        {outcome ? (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              <StatCard label="İşlem" value={outcome.trades} />
              <StatCard label="Kazanan" value={fmt(outcome.win_rate, 1, "%")}
                tone={(outcome.win_rate ?? 0) >= 50 ? "positive" : "negative"} />
              <StatCard label="Ort. sonuç" value={fmt(outcome.avg_pnl_pct, 3, "%")}
                tone={(outcome.avg_pnl_pct ?? 0) > 0 ? "positive" : "negative"} />
              <StatCard label="Ort. kazanç" value={fmt(outcome.avg_win_pct, 3, "%")} tone="positive" />
              <StatCard label="Ort. kayıp" value={fmt(outcome.avg_loss_pct, 3, "%")} tone="negative" />
            </div>
            {(outcomes?.by_reason ?? []).length > 0 && (
              <div className="mt-3">
                <div className="mb-1 text-xs font-medium text-[var(--muted)]">Çıkış nedeni dağılımı</div>
                <div className="flex flex-wrap gap-2">
                  {(outcomes.by_reason as any[]).map((r) => (
                    <span key={r.reason}
                      className="rounded-lg border border-[var(--border)] px-2 py-1 text-xs">
                      {r.reason}: <b>{r.count}</b>
                      <span className={r.avg_pnl_pct > 0 ? "text-emerald-400" : "text-red-400"}>
                        {" "}{r.avg_pnl_pct > 0 ? "+" : ""}{r.avg_pnl_pct.toFixed(3)}%
                      </span>
                    </span>
                  ))}
                </div>
              </div>
            )}
          </>
        ) : (
          <p className="text-sm text-[var(--muted)]">Veri yok.</p>
        )}
      </Card>

      {/* 5) ÖLÇÜLMÜŞ KANIT */}
      <Card>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-semibold">Ölçülmüş Kanıt ({evidence?.total ?? 0} hipotez)</h2>
          <div className="flex gap-2">
            {(["applied", "kept", "rejected"] as const).map((k) => (
              <Badge key={k} tone={STATUS_META[k].tone}>
                {STATUS_META[k].label} {evidence?.counts?.[k] ?? 0}
              </Badge>
            ))}
          </div>
        </div>
        <div className="divide-y divide-[var(--border)]">
          {(evidence?.items ?? []).map((item: Evidence) => (
            <div key={item.id} className="py-2">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={STATUS_META[item.status].tone}>
                  {STATUS_META[item.status].label}
                </Badge>
                <span className="font-medium">{item.name}</span>
                {item.param && (
                  <code className="rounded bg-[var(--surface-2)] px-1.5 py-0.5 text-[11px]">
                    {item.param}
                  </code>
                )}
                <span className="text-[11px] text-[var(--muted)]">{item.source}</span>
              </div>
              <div className="mt-1 text-sm">{item.summary}</div>
              <div className="text-xs text-[var(--muted)]">{item.detail}</div>
            </div>
          ))}
        </div>
        {evidence?.warning && (
          <p className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-300">
            {evidence.warning}
          </p>
        )}
      </Card>
    </div>
  );
}
