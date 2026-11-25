"use client";

/**
 * Veritabanı boyutu kartı (Ayarlar > Uygulama Ayarları).
 *
 * NEDEN: disk şişmesi ancak sunucu loglarına bakınca fark ediliyordu. Bu kart
 * toplam DB boyutunu, sınırı ve en büyük tabloları gösterir; "BUDAMA ÇALIŞTIR"
 * zaman budamasını elle tetikler (retention + boyut koruması).
 *
 * Salt-okunur ölçüm + yönetici onaylı bakım; işlem/pozisyon verisine dokunmaz.
 */
import { useCallback, useEffect, useState } from "react";

import { API_BASE, apiRequest } from "../lib/api";

type TableRow = { table: string; total_mb: number; heap_mb: number; index_mb: number; rows: number };
type DbStats = {
  ok?: boolean;
  available?: boolean;
  reason?: string;
  size_mb?: number;
  limit_mb?: number;
  over_limit?: boolean;
  usage_pct?: number | null;
  tables?: TableRow[];
  generated_at?: number;
};

function fmt(value: number | null | undefined, unit = ""): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  return `${Number(value).toLocaleString("tr-TR")}${unit}`;
}

export default function DbStatsCard() {
  const [stats, setStats] = useState<DbStats | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [limitInput, setLimitInput] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await apiRequest(`${API_BASE}/api/system/db-stats`, { cache: "no-store" });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof d?.detail === "string" ? d.detail : "Ölçüm alınamadı");
      setStats(d);
      if (d?.limit_mb !== undefined) setLimitInput(String(d.limit_mb));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ölçüm alınamadı");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const prune = async () => {
    if (busy) return;
    setBusy(true); setError(""); setNote("");
    try {
      const r = await apiRequest(`${API_BASE}/api/system/db-prune`, { method: "POST" });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof d?.detail === "string" ? d.detail : "Budama başarısız");
      const total = Object.values(d?.deleted || {}).reduce((a: number, b: any) => a + Number(b || 0), 0);
      setNote(`Budama bitti: ${total.toLocaleString("tr-TR")} satır silindi.`);
      if (d?.size_mb !== undefined) setStats((prev) => ({ ...(prev || {}), ...d }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Budama başarısız");
    } finally {
      setBusy(false);
    }
  };

  const saveLimit = async () => {
    if (busy) return;
    setBusy(true); setError(""); setNote("");
    try {
      const value = Number(limitInput);
      if (!Number.isFinite(value) || value < 0) throw new Error("Sınır 0 veya pozitif sayı olmalı");
      const r = await apiRequest(`${API_BASE}/api/system/db-limit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit_mb: value }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof d?.detail === "string" ? d.detail : "Kaydedilemedi");
      setNote(value === 0 ? "Boyut koruması kapatıldı." : `Sınır ${value.toLocaleString("tr-TR")} MB olarak kaydedildi.`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Kaydedilemedi");
    } finally {
      setBusy(false);
    }
  };

  const limitOn = Number(stats?.limit_mb || 0) > 0;
  const over = Boolean(stats?.over_limit);

  return (
    <div className="card bg-bunker-950">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="eyebrow text-neon-green">💾 VERİTABANI BOYUTU</p>
          <p className="text-xs text-bunker-muted mt-1">
            Toplam boyut, sınır ve en büyük tablolar. Sınır aşılırsa budama pencereleri otomatik kısalır
            (6 saatte bir kontrol). “BUDAMA ÇALIŞTIR” elle temizler; işlem/pozisyon kayıtlarına dokunmaz.
          </p>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={load} disabled={busy} className="ui-button ui-button-secondary">
            YENİLE
          </button>
          <button type="button" onClick={prune} disabled={busy} className="ui-button ui-button-primary">
            {busy ? "ÇALIŞIYOR…" : "BUDAMA ÇALIŞTIR"}
          </button>
        </div>
      </div>

      {error && <p className="mt-3 font-mono text-xs text-neon-red">⚠ {error}</p>}
      {note && <p className="mt-3 font-mono text-xs text-neon-green">✓ {note}</p>}
      {!stats && !error && <p className="mt-3 font-mono text-xs text-bunker-muted animate-pulse">Yükleniyor...</p>}

      {stats && !stats.available && (
        <p className="mt-3 font-mono text-xs text-amber-300">
          Ölçüm alınamadı{stats.reason ? `: ${stats.reason}` : "."}
        </p>
      )}

      {stats?.available && (
        <>
          <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className={`rounded-lg border px-3 py-2 ${over ? "border-neon-red/50 bg-neon-red/10" : "border-bunker-800 bg-bunker-900/60"}`}>
              <p className="text-[10px] font-mono uppercase tracking-wide text-bunker-muted">TOPLAM</p>
              <p className={`mt-0.5 font-mono text-sm ${over ? "text-neon-red" : "text-white"}`}>{fmt(stats.size_mb, " MB")}</p>
            </div>
            <div className="rounded-lg border border-bunker-800 bg-bunker-900/60 px-3 py-2">
              <p className="text-[10px] font-mono uppercase tracking-wide text-bunker-muted">SINIR</p>
              <p className={`mt-0.5 font-mono text-sm ${limitOn ? "text-white" : "text-bunker-muted"}`}>
                {limitOn ? fmt(stats.limit_mb, " MB") : "KAPALI"}
              </p>
            </div>
            <div className="rounded-lg border border-bunker-800 bg-bunker-900/60 px-3 py-2">
              <p className="text-[10px] font-mono uppercase tracking-wide text-bunker-muted">KULLANIM</p>
              <p className="mt-0.5 font-mono text-sm text-white">{stats.usage_pct == null ? "—" : `%${stats.usage_pct}`}</p>
            </div>
            <div className="rounded-lg border border-bunker-800 bg-bunker-900/60 px-3 py-2">
              <p className="text-[10px] font-mono uppercase tracking-wide text-bunker-muted">DURUM</p>
              <p className={`mt-0.5 font-mono text-sm ${over ? "text-neon-red" : "text-neon-green"}`}>
                {over ? "SINIR AŞILDI" : "NORMAL"}
              </p>
            </div>
          </div>

          {over && (
            <p className="mt-3 font-mono text-xs text-neon-red">
              ⚠ Boyut sınırın üstünde. Budama çalıştır; kalıcı küçülme için (VACUUM FULL) bakım penceresi gerekir.
            </p>
          )}

          <div className="mt-4 flex flex-wrap items-end gap-3 rounded-lg border border-bunker-800 bg-bunker-900/40 px-3 py-3">
            <div>
              <p className="text-[10px] font-mono uppercase tracking-wide text-bunker-muted">BOYUT SINIRI (MB · 0 = KAPALI)</p>
              <input
                type="number"
                min={0}
                step={256}
                value={limitInput}
                onChange={(e) => setLimitInput(e.target.value)}
                className="mt-1 w-40 bg-bunker-950 border border-bunker-700 rounded-lg px-2 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none"
              />
              <p className="mt-1 text-[11px] text-bunker-muted">
                {limitOn ? "Sınır aşılırsa budama pencereleri otomatik kısalır." : "Koruma kapalı: hiçbir satır boyut nedeniyle silinmez."}
              </p>
            </div>
            <button type="button" onClick={saveLimit} disabled={busy} className="ui-button ui-button-primary">
              SINIRI KAYDET
            </button>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left font-mono text-xs">
              <thead>
                <tr className="text-bunker-muted">
                  <th className="py-1 pr-3">TABLO</th>
                  <th className="py-1 pr-3 text-right">TOPLAM</th>
                  <th className="py-1 pr-3 text-right">VERİ</th>
                  <th className="py-1 pr-3 text-right">İNDEKS</th>
                  <th className="py-1 text-right">SATIR (tahmini)</th>
                </tr>
              </thead>
              <tbody>
                {(stats.tables || []).map((t) => (
                  <tr key={t.table} className="border-t border-bunker-800/60">
                    <td className="py-1 pr-3 text-white">{t.table}</td>
                    <td className="py-1 pr-3 text-right">{fmt(t.total_mb, " MB")}</td>
                    <td className="py-1 pr-3 text-right text-bunker-muted">{fmt(t.heap_mb, " MB")}</td>
                    <td className="py-1 pr-3 text-right text-bunker-muted">{fmt(t.index_mb, " MB")}</td>
                    <td className="py-1 text-right">{fmt(t.rows)}</td>
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
