"use client";

// Günlük Yükseliş Adayları (2026-10-10)
//
// Sistemin "günlük momentum" katmanının önerdiği adayları gösterir:
// önerildiği andaki fiyat ↔ anlık fiyat, değişim %, beklenen maksimum (tavan)
// ve gerçekleşen maksimum (MFE). Veri kaynağı: GET /api/daily-rising/state.

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import { formatPrice, formatNumber2, toMs, fmtDateTime } from "../lib/format";
import { Card, Badge, StatCard } from "../components/ui";

type Row = {
  symbol: string;
  created_at: number | null;
  entry_price: number | null;
  current_price: number | null;
  change_pct: number | null;
  target_pct: number | null;
  ceiling_pct: number | null;
  ceiling_price: number | null;
  velocity_score: number | null;
  ret_8h: number | null;
  adx: number | null;
  atr_pct: number | null;
  slope: number | null;
  spread_pct: number | null;
  mfe_pct: number | null;
  mae_pct: number | null;
  status: string | null;
  notified: boolean | null;
};

type Stats = {
  total: number;
  filled: number;
  pending: number;
  hit_count: number;
  hit_rate: number | null;
  avg_mfe_pct: number | null;
  max_mfe_pct: number | null;
};

const REFRESH_MS = 30_000;

function pctTone(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-bunker-muted";
  if (v > 0.5) return "text-neon-green";
  if (v < -0.5) return "text-neon-red";
  return "text-bunker-muted";
}

function fmtPct(v: number | null | undefined, signed = true): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  return `${signed && n > 0 ? "+" : ""}${formatNumber2(n)}%`;
}

function statusLabel(s: string | null | undefined): string {
  if (s === "pending") return "BEKLİYOR";
  if (s === "filled") return "TAMAMLANDI";
  if (s === "touched") return "DOKUNDU";
  if (s === "expired") return "SÜRESİ DOLDU";
  return s || "—";
}

export default function DailyRisingPage() {
  const [rows, setRows] = useState<Row[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await apiRequest(`${API_BASE}/api/daily-rising/state`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setRows(Array.isArray(data?.candidates) ? data.candidates : []);
      setStats(data?.stats ?? null);
      setUpdatedAt(Date.now());
      setError(null);
    } catch (e: any) {
      setError(e?.message || "Veri alınamadı");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      if (!alive) return;
      if (!document.hidden) await load();
      if (alive) timerRef.current = setTimeout(tick, REFRESH_MS);
    };
    load();
    timerRef.current = setTimeout(tick, REFRESH_MS);
    const onVis = () => { if (!document.hidden) load(); };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      alive = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [load]);

  const active = rows;

  return (
    <div className="page-shell">
      <div className="page-heading">
        <div>
          <div className="eyebrow">Günlük Momentum Katmanı</div>
          <h1 className="text-xl font-semibold">🌅 Yükseliş Adayları</h1>
          <p className="text-sm text-bunker-muted mt-1">
            Sistemin günlük yükseliş için işaretlediği adaylar. Önerildiği andaki fiyat ile anlık
            fiyat karşılaştırılır; <b>tavan</b> beklenen maksimum yükseliştir.
          </p>
        </div>
        <div className="text-right text-xs text-bunker-muted">
          {updatedAt ? <>Son güncelleme: {fmtDateTime(updatedAt)}</> : null}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 my-4">
        <StatCard label="Toplam Aday (7g)" value={stats?.total ?? "—"} />
        <StatCard label="İsabet Oranı" value={stats?.hit_rate != null ? `%${formatNumber2(stats.hit_rate)}` : "—"} />
        <StatCard label="Ort. Gerçekleşen Max" value={stats?.avg_mfe_pct != null ? `+${formatNumber2(stats.avg_mfe_pct)}%` : "—"} />
        <StatCard label="En Yüksek" value={stats?.max_mfe_pct != null ? `+${formatNumber2(stats.max_mfe_pct)}%` : "—"} />
      </div>

      <Card>
        {loading ? (
          <div className="p-6 text-sm text-bunker-muted">Yükleniyor…</div>
        ) : error ? (
          <div className="p-6 text-sm text-neon-red">Hata: {error}</div>
        ) : active.length === 0 ? (
          <div className="p-6 text-sm text-bunker-muted">
            Henüz günlük momentum adayı yok. Katman kapalı olabilir
            (<code>DAILY_MOMENTUM_ENABLED</code>) veya bugün koşulları sağlayan aday bulunamadı.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full font-mono text-xs">
              <thead>
                <tr className="text-left text-bunker-muted border-b border-bunker-700">
                  <th className="p-2">Sembol</th>
                  <th className="p-2">Öneri Saati</th>
                  <th className="p-2 text-right">Öneri Fiyatı</th>
                  <th className="p-2 text-right">Tavan (maks.)</th>
                  <th className="p-2 text-right">Anlık Fiyat</th>
                  <th className="p-2 text-right">Değişim</th>
                  <th className="p-2 text-right">Gerçekleşen Max</th>
                  <th className="p-2">Durum</th>
                </tr>
              </thead>
              <tbody>
                {active.map((r, i) => (
                  <tr key={`${r.symbol}-${r.created_at}-${i}`} className="border-b border-bunker-800 hover:bg-bunker-800/40">
                    <td className="p-2">
                      <a className="text-neon-green hover:underline" href={`/charts?symbol=${r.symbol}`}>
                        {r.symbol}
                      </a>
                    </td>
                    <td className="p-2 text-bunker-muted">{r.created_at ? fmtDateTime(toMs(r.created_at)) : "—"}</td>
                    <td className="p-2 text-right">{r.entry_price != null ? formatPrice(r.entry_price) : "—"}</td>
                    <td className="p-2 text-right">
                      {r.ceiling_price != null ? (
                        <span title={`Beklenen maksimum: +${fmtPct(r.ceiling_pct)}`}>
                          {formatPrice(r.ceiling_price)}{" "}
                          <span className="text-neon-yellow">({fmtPct(r.ceiling_pct)})</span>
                        </span>
                      ) : "—"}
                    </td>
                    <td className="p-2 text-right">{r.current_price != null ? formatPrice(r.current_price) : "—"}</td>
                    <td className={`p-2 text-right font-semibold ${pctTone(r.change_pct)}`}>{fmtPct(r.change_pct)}</td>
                    <td className={`p-2 text-right ${pctTone(r.mfe_pct)}`}>{r.mfe_pct != null ? fmtPct(r.mfe_pct) : "—"}</td>
                    <td className="p-2">
                      <Badge tone={r.status === "filled" ? "positive" : r.status === "pending" ? "warning" : "neutral"}>
                        {statusLabel(r.status)}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <p className="text-[11px] text-bunker-muted mt-3">
        Bu ekran bilgilendirme amaçlıdır; otonom paper işlemleri mevcut bildirim yoluyla açılır.
        <code> DAILY_MOMENTUM_ENABLED=false</code> iken katman çalışmaz.
      </p>
    </div>
  );
}
